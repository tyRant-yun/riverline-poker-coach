"""Thin HTTP transport; domain and analysis services remain transport-free."""

from __future__ import annotations

import time
from dataclasses import dataclass
from os import getenv
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from poker_coach.analysis import AnalysisCancelled, AnalysisTimeout, analyze_scenario, range_spec_from_notation
from poker_coach.analysis.models import AnalysisResult, InvalidAnalysisInput
from poker_coach.coach import TeachingService
from poker_coach.domain.models import ScenarioSpec
from poker_coach.persistence import SQLiteStore
from poker_coach.persistence.sqlite_store import StoreNotFound
from poker_coach.rules import PokerKitAdapter, ReplayError


@dataclass(frozen=True)
class AppConfig:
    app_version: str = "0.1.0"
    analysis_version: str = "analysis-core-0.1"

    @classmethod
    def from_environment(cls) -> AppConfig:
        return cls(
            app_version=getenv("POKER_COACH_APP_VERSION", cls.app_version),
            analysis_version=getenv("POKER_COACH_ANALYSIS_VERSION", cls.analysis_version),
        )


class ApiError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None, status_code: int = 422):
        self.code = code
        self.details = details
        self.status_code = status_code
        super().__init__(message)


def create_app(config: AppConfig | None = None, store: SQLiteStore | None = None) -> FastAPI:
    config = config or AppConfig.from_environment()
    adapter = PokerKitAdapter()
    store = store or SQLiteStore(getenv("POKER_COACH_DB_PATH", ".data/poker_coach.sqlite3"))
    teacher = TeachingService(adapter)
    app = FastAPI(
        title="Poker Coach API",
        version=config.app_version,
        description="Local HU NLHE validation and evidence analysis API",
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.code, str(exc), exc.details),
        )

    @app.exception_handler(ReplayError)
    async def replay_error_handler(request: Request, exc: ReplayError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(request, exc.code, str(exc), exc.as_dict()),
        )

    @app.exception_handler(InvalidAnalysisInput)
    async def analysis_input_error_handler(request: Request, exc: InvalidAnalysisInput):
        return JSONResponse(
            status_code=422,
            content=_error_payload(request, "invalid_analysis_input", str(exc)),
        )

    @app.exception_handler(AnalysisCancelled)
    async def analysis_cancelled_handler(request: Request, exc: AnalysisCancelled):
        return JSONResponse(
            status_code=499,
            content=_error_payload(request, "analysis_cancelled", str(exc)),
        )

    @app.exception_handler(AnalysisTimeout)
    async def analysis_timeout_handler(request: Request, exc: AnalysisTimeout):
        return JSONResponse(
            status_code=408,
            content=_error_payload(request, "analysis_timeout", str(exc)),
        )

    @app.exception_handler(StoreNotFound)
    async def store_not_found_handler(request: Request, exc: StoreNotFound):
        return JSONResponse(
            status_code=404,
            content=_error_payload(request, "not_found", f"resource not found: {exc.args[0]}"),
        )

    @app.get("/health")
    async def health(request: Request):
        return {
            "status": "ok",
            "requestId": request.state.request_id,
            "appVersion": config.app_version,
            "analysisVersion": config.analysis_version,
            "rulesEngine": adapter.engine_name,
            "rulesEngineVersion": adapter.engine_version,
        }

    @app.get("/version")
    async def version_info(request: Request):
        return {
            "schemaVersion": 1,
            "appVersion": config.app_version,
            "analysisVersion": config.analysis_version,
            "rulesEngine": adapter.engine_name,
            "rulesEngineVersion": adapter.engine_version,
            "requestId": request.state.request_id,
        }

    @app.post("/v1/scenarios/validate")
    async def validate_scenario(request: Request):
        scenario = _scenario_from_request(await request.json())
        replay = adapter.replay(scenario)
        return {
            "schemaVersion": scenario.schema_version,
            "valid": True,
            "requestId": request.state.request_id,
            "normalizedScenario": scenario.to_dict(),
            "finalState": replay.final_state.to_dict(),
            "settlement": replay.settlement.to_dict(),
            "rulesEngineVersion": replay.rules_engine_version,
        }

    @app.post("/v1/scenarios")
    async def create_scenario(request: Request):
        payload = await request.json()
        scenario, title, tags = _saved_scenario_from_request(payload)
        record = store.create_scenario(scenario, title=title, tags=tags)
        return {"schemaVersion": 1, "requestId": request.state.request_id, "scenario": _record_to_json(record)}

    @app.get("/v1/scenarios")
    async def list_scenarios(request: Request, q: str | None = None, limit: int = 100):
        records = store.list_scenarios(query=q, limit=limit)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "scenarios": [_record_to_json(record) for record in records],
        }

    @app.get("/v1/scenarios/{scenario_id}")
    async def get_scenario(request: Request, scenario_id: str):
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "scenario": _record_to_json(store.get_scenario(scenario_id)),
        }

    @app.put("/v1/scenarios/{scenario_id}")
    async def update_scenario(request: Request, scenario_id: str):
        payload = await request.json()
        scenario, title, tags = _saved_scenario_from_request(payload)
        record = store.update_scenario(scenario_id, scenario, title=title, tags=tags)
        return {"schemaVersion": 1, "requestId": request.state.request_id, "scenario": _record_to_json(record)}

    @app.post("/v1/scenarios/{scenario_id}/copy")
    async def copy_scenario(request: Request, scenario_id: str):
        payload = await request.json()
        title = payload.get("title") if isinstance(payload, dict) else None
        record = store.copy_scenario(scenario_id, title=title)
        return {"schemaVersion": 1, "requestId": request.state.request_id, "scenario": _record_to_json(record)}

    @app.post("/v1/scenarios/{scenario_id}/favorite")
    async def favorite_scenario(request: Request, scenario_id: str):
        payload = await request.json()
        favorite = bool(payload.get("favorite")) if isinstance(payload, dict) else True
        record = store.set_favorite(scenario_id, favorite)
        return {"schemaVersion": 1, "requestId": request.state.request_id, "scenario": _record_to_json(record)}

    @app.delete("/v1/scenarios/{scenario_id}")
    async def delete_scenario(request: Request, scenario_id: str):
        store.delete_scenario(scenario_id)
        return {"schemaVersion": 1, "requestId": request.state.request_id, "deleted": True}

    @app.get("/v1/scenarios/{scenario_id}/analyses")
    async def analysis_history(request: Request, scenario_id: str):
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "analyses": store.list_analyses(scenario_id),
        }

    @app.post("/v1/scenarios/{scenario_id}/analyze")
    async def analyze_saved_scenario(request: Request, scenario_id: str):
        record = store.get_scenario(scenario_id)
        started = time.perf_counter()
        result = analyze_scenario(
            record["scenario"],
            adapter=adapter,
            timeout_seconds=_timeout_query(request),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        analysis_record = store.save_analysis(
            scenario_id,
            result,
            raw_scenario=record["scenario"],
            execution_ms=elapsed_ms,
        )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "executionMs": elapsed_ms,
            "analysis": result.to_dict(),
            "analysisRun": analysis_record,
        }

    @app.post("/v1/scenarios/{scenario_id}/teach")
    async def teach_saved_scenario(request: Request, scenario_id: str):
        record = store.get_scenario(scenario_id)
        payload = await request.json()
        analysis_result = analyze_scenario(record["scenario"], adapter=adapter)
        response = teacher.explain(
            record["scenario"],
            analysis=analysis_result,
            user_question=payload.get("question") if isinstance(payload, dict) else None,
        )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "teacherVersion": teacher.version,
            "response": response.to_dict(),
        }

    @app.post("/v1/scenarios/state")
    async def scenario_state(request: Request):
        scenario = _scenario_from_request(await request.json())
        replay = adapter.replay(scenario)
        return {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "snapshots": [snapshot.to_dict() for snapshot in replay.snapshots],
            "finalState": replay.final_state.to_dict(),
            "settlement": replay.settlement.to_dict(),
            "rulesEngineVersion": replay.rules_engine_version,
        }

    @app.post("/v1/analysis")
    async def analysis(request: Request):
        scenario = _scenario_from_request(await request.json())
        started = time.perf_counter()
        result = analyze_scenario(
            scenario,
            adapter=adapter,
            timeout_seconds=_timeout_query(request),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "analysisVersion": result.analysis_version,
            "executionMs": elapsed_ms,
            "analysis": result.to_dict(),
        }

    @app.post("/v1/teaching")
    async def teaching(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "request body must be a JSON object")
        scenario = _scenario_from_request(payload.get("scenario", payload))
        raw_analysis = payload.get("analysis")
        if isinstance(raw_analysis, dict) and "analysis" in raw_analysis:
            raw_analysis = raw_analysis["analysis"]
        analysis_result = (
            AnalysisResult.model_validate(raw_analysis)
            if raw_analysis
            else analyze_scenario(scenario, adapter=adapter)
        )
        response = teacher.explain(
            scenario,
            analysis=analysis_result,
            depth=payload.get("depth", "intermediate"),
            user_question=payload.get("question"),
        )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "teacherVersion": teacher.version,
            "response": response.to_dict(),
        }

    @app.post("/v1/ranges/parse")
    async def parse_range(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("notation"), str):
            raise ApiError("invalid_range_request", "notation must be a string")
        try:
            range_spec = range_spec_from_notation(
                payload["notation"],
                range_id=payload.get("rangeId", "notation-range"),
                name=payload.get("name", "Imported range"),
                version=payload.get("version", "1"),
            )
        except (ValueError, ValidationError) as exc:
            raise ApiError("invalid_range_notation", str(exc)) from exc
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "range": range_spec.to_dict(),
        }

    return app


def _scenario_from_request(payload: Any) -> ScenarioSpec:
    if not isinstance(payload, dict):
        raise ApiError("invalid_request", "request body must be a JSON object")
    try:
        return ScenarioSpec.model_validate(payload)
    except ValidationError as exc:
        raise ApiError(
            "invalid_scenario",
            "ScenarioSpec validation failed",
            details=_json_safe(exc.errors()),
        ) from exc


def _saved_scenario_from_request(payload: Any) -> tuple[ScenarioSpec, str, tuple[str, ...]]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_request", "request body must be a JSON object")
    raw_scenario = payload.get("scenario")
    scenario = _scenario_from_request(raw_scenario)
    title = payload.get("title", "Untitled scenario")
    tags = payload.get("tags", [])
    if not isinstance(title, str) or not title.strip():
        raise ApiError("invalid_title", "title must be a non-empty string")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ApiError("invalid_tags", "tags must be a list of strings")
    return scenario, title.strip(), tuple(tags)


def _record_to_json(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    scenario = result.get("scenario")
    if isinstance(scenario, ScenarioSpec):
        result["scenario"] = scenario.to_dict()
    return result


def _timeout_query(request: Request) -> float | None:
    raw = request.query_params.get("timeoutSeconds")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ApiError("invalid_timeout", "timeoutSeconds must be numeric") from exc
    if value < 0:
        raise ApiError("invalid_timeout", "timeoutSeconds cannot be negative")
    return value


def _error_payload(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "requestId": getattr(request.state, "request_id", None),
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, BaseException):
        return str(value)
    return value


app = create_app()
