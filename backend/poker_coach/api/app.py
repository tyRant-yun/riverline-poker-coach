"""Thin HTTP transport; domain and analysis services remain transport-free."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from os import getenv
from threading import Lock
from uuid import uuid4
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Load the repository-root .env file (if present) without overriding
# variables that are already set in the environment.
load_dotenv(override=False)

from poker_coach.analysis import AnalysisCancelled, AnalysisTimeout, analyze_scenario, expand_range, range_spec_from_notation
from poker_coach.analysis.models import AnalysisResult, InvalidAnalysisInput
from poker_coach.coach import TeachingService
from poker_coach.domain.models import RangeSpec, ScenarioSpec
from poker_coach.jobs import InProcessJobBackend, RedisJobBackend
from poker_coach.learning import LearningService, PracticeUnavailable
from poker_coach.persistence import PostgresStore, SQLiteStore
from poker_coach.persistence.sqlite_store import StoreNotFound
from poker_coach.ranges import (
    FixturePolicyProvider,
    InvalidPolicyError,
    NoPriorRangeError,
    RangeBeliefError,
    SolverPolicyAdapter,
    build_belief_view,
    build_range_trace,
)
from poker_coach.rules import PokerKitAdapter, ReplayError
from poker_coach.solver import (
    SolverJobQueue,
    SolverJobProvenance,
    SolverSpot,
    SolverUnsupportedError,
    build_spot,
    parse_result,
    postflop_seat_pair,
    scenario_at_policy_sequence,
    scenario_fingerprint,
    solver_spot_fingerprint,
)
from poker_coach.strategy.catalog import StrategyCatalog
from poker_coach.strategy.ranges import default_preflop_ranges


audit_logger = logging.getLogger("poker_coach.api")


@dataclass(frozen=True)
class AppConfig:
    app_version: str = "0.1.0"
    analysis_version: str = "analysis-core-0.1"
    store_user_text: bool = False
    max_request_bytes: int = 1_000_000
    max_timeout_seconds: float = 120.0
    rate_limit_per_minute: int = 120
    redis_url: str | None = None
    redis_worker_in_process: bool = True
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    # External teaching models can take 60-120s on large evidence prompts
    # (json_object mode), so the default must exceed the old 60s ceiling
    # that made the teacher randomly degrade to the local template.
    llm_timeout_seconds: float = 180.0

    @classmethod
    def from_environment(cls) -> AppConfig:
        return cls(
            app_version=getenv("POKER_COACH_APP_VERSION") or cls.app_version,
            analysis_version=getenv("POKER_COACH_ANALYSIS_VERSION") or cls.analysis_version,
            store_user_text=getenv("POKER_COACH_STORE_USER_TEXT", "0").lower()
            in {"1", "true", "yes"},
            max_request_bytes=_env_int(
                "POKER_COACH_MAX_REQUEST_BYTES", cls.max_request_bytes, minimum=1
            ),
            max_timeout_seconds=_env_float(
                "POKER_COACH_MAX_TIMEOUT_SECONDS", cls.max_timeout_seconds, minimum=0.0
            ),
            rate_limit_per_minute=_env_int(
                "POKER_COACH_RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute, minimum=0
            ),
            redis_url=getenv("POKER_COACH_REDIS_URL") or None,
            redis_worker_in_process=getenv("POKER_COACH_REDIS_WORKER_IN_PROCESS", "1").lower()
            in {"1", "true", "yes"},
            llm_base_url=getenv("POKER_COACH_LLM_BASE_URL") or cls.llm_base_url,
            llm_api_key=getenv("POKER_COACH_LLM_API_KEY") or None,
            llm_model=getenv("POKER_COACH_LLM_MODEL") or cls.llm_model,
            llm_timeout_seconds=_env_float(
                "POKER_COACH_LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds, minimum=1.0
            ),
        )


class ApiError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None, status_code: int = 422):
        self.code = code
        self.details = details
        self.status_code = status_code
        super().__init__(message)


def _create_job_backend(
    config: AppConfig, adapter: PokerKitAdapter, executor
) -> InProcessJobBackend | RedisJobBackend:
    """Select the analysis job backend: in-process, or Redis with a worker thread."""
    if not config.redis_url:
        return InProcessJobBackend(
            adapter, executor, default_timeout=config.max_timeout_seconds
        )
    from poker_coach.jobs import AnalysisWorker, RedisJobBackend, RedisJobQueue

    queue = RedisJobQueue(config.redis_url)
    if config.redis_worker_in_process:
        # Local convenience: consume the queue in this process. Deployments
        # with a dedicated worker set POKER_COACH_REDIS_WORKER_IN_PROCESS=0.
        worker = AnalysisWorker(
            queue, adapter=adapter, default_timeout=config.max_timeout_seconds
        )
        threading.Thread(
            target=worker.run_forever,
            daemon=True,
            name="poker-analysis-redis-worker",
        ).start()
    return RedisJobBackend(queue)


def _create_teacher(config: AppConfig, adapter: PokerKitAdapter) -> TeachingService:
    """Select the teacher: local principle-only, or the external model adapter."""
    if not config.llm_api_key:
        return TeachingService(adapter)
    from poker_coach.coach import ExternalModelTeacher

    return ExternalModelTeacher(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds,
        adapter=adapter,
    )


def create_app(
    config: AppConfig | None = None,
    store: SQLiteStore | PostgresStore | None = None,
    teacher: TeachingService | None = None,
    solver_queue=None,
) -> FastAPI:
    config = config or AppConfig.from_environment()
    adapter = PokerKitAdapter()
    if store is None:
        database_url = getenv("POKER_COACH_DATABASE_URL")
        store = PostgresStore(database_url) if database_url else SQLiteStore(getenv("POKER_COACH_DB_PATH", ".data/poker_coach.sqlite3"))
    teacher = teacher or _create_teacher(config, adapter)
    learning = LearningService(adapter)
    strategy_catalog = StrategyCatalog()
    store.register_strategy_artifacts(strategy_catalog.artifacts)
    idempotency_cache: dict[str, tuple[str, dict[str, Any]]] = {}
    rate_limit_state: dict[str, list[float]] = {}
    rate_limit_lock = Lock()
    analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="poker-analysis")
    job_backend = _create_job_backend(config, adapter, analysis_executor)
    app = FastAPI(
        title="Poker Coach API",
        version=config.app_version,
        description=(
            "Local NLHE replay, 2-8 seat multiway analysis and heads-up "
            "postflop solve API"
        ),
    )
    cors_origins = tuple(
        origin.strip()
        for origin in getenv(
            "POKER_COACH_CORS_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000",
        ).split(",")
        if origin.strip()
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        request.state.scenario_hash = None
        request.state.cache_hit = False
        started = time.perf_counter()
        raw_length = request.headers.get("content-length")
        status_code = 500
        try:
            if (
                raw_length is not None
                and raw_length.isdigit()
                and int(raw_length) > config.max_request_bytes
            ):
                status_code = 413
                response = JSONResponse(
                    status_code=status_code,
                    content=_error_payload(
                        request,
                        "request_too_large",
                        f"request body exceeds {config.max_request_bytes} bytes",
                    ),
                )
                response.headers["X-Request-ID"] = request_id
                return response
            if config.rate_limit_per_minute and not _allow_request(
                rate_limit_state,
                rate_limit_lock,
                _rate_limit_key(request),
                limit=config.rate_limit_per_minute,
            ):
                status_code = 429
                response = JSONResponse(
                    status_code=status_code,
                    content=_error_payload(
                        request,
                        "rate_limit_exceeded",
                        "anonymous request rate limit exceeded",
                        {"limitPerMinute": config.rate_limit_per_minute},
                    ),
                )
                response.headers["Retry-After"] = "60"
                response.headers["X-Request-ID"] = request_id
                return response
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            audit_logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "scenario_hash": request.state.scenario_hash,
                    "anonymous_session": request.headers.get("X-Anonymous-Session"),
                    "cache_hit": request.state.cache_hit,
                },
            )

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

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request,
                "invalid_payload",
                "request payload validation failed",
                _json_safe(exc.errors()),
            ),
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
        # schemaVersion here is the /version envelope version (1), NOT the
        # scenario schema version: ScenarioSpec is SCENARIO_SCHEMA_VERSION=2
        # and scenario-bearing endpoints echo the scenario's own schemaVersion.
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
        _set_scenario_context(request, scenario)
        replay = adapter.replay(scenario)
        adapter.replay_to_decision(scenario)
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
        scenario, title, tags, raw_scenario_json = _saved_scenario_from_request(payload)
        _set_scenario_context(request, scenario)
        adapter.replay(scenario)
        adapter.replay_to_decision(scenario)
        record = store.create_scenario(
            scenario, title=title, tags=tags, raw_scenario_json=raw_scenario_json
        )
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

    @app.get("/v1/scenarios/{scenario_id}/revisions")
    async def scenario_revisions(request: Request, scenario_id: str):
        revisions = store.list_scenario_revisions(scenario_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "scenarioId": scenario_id,
            "revisions": [_record_to_json(revision) for revision in revisions],
        }

    @app.put("/v1/scenarios/{scenario_id}")
    async def update_scenario(request: Request, scenario_id: str):
        payload = await request.json()
        scenario, title, tags, raw_scenario_json = _saved_scenario_from_request(payload)
        _set_scenario_context(request, scenario)
        adapter.replay(scenario)
        adapter.replay_to_decision(scenario)
        record = store.update_scenario(
            scenario_id,
            scenario,
            title=title,
            tags=tags,
            raw_scenario_json=raw_scenario_json,
        )
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

    @app.get("/v1/scenarios/{scenario_id}/analyses/compare")
    async def compare_analysis_history(request: Request, scenario_id: str):
        left_id = request.query_params.get("leftAnalysisId")
        right_id = request.query_params.get("rightAnalysisId")
        if not left_id or not right_id or left_id == right_id:
            raise ApiError(
                "invalid_analysis_comparison",
                "leftAnalysisId and rightAnalysisId must be two different analysis IDs",
            )
        records = {record["analysisId"]: record for record in store.list_analyses(scenario_id)}
        if left_id not in records or right_id not in records:
            raise StoreNotFound(left_id if left_id not in records else right_id)
        left = records[left_id]
        right = records[right_id]
        fields = ("metrics", "hand", "board", "equity", "rangeAnalysis", "rangeComparison", "strategyMatch", "warnings")
        differences = [
            {
                "field": field,
                "left": left["output"].get(field) if left["output"] else None,
                "right": right["output"].get(field) if right["output"] else None,
            }
            for field in fields
            if (left["output"].get(field) if left["output"] else None)
            != (right["output"].get(field) if right["output"] else None)
        ]
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "scenarioId": scenario_id,
            "leftAnalysisId": left_id,
            "rightAnalysisId": right_id,
            "differences": differences,
            "versions": {
                "left": {"rulesEngineVersion": left["rulesEngineVersion"], "analysisVersion": left["analysisVersion"]},
                "right": {"rulesEngineVersion": right["rulesEngineVersion"], "analysisVersion": right["analysisVersion"]},
            },
        }

    @app.post("/v1/scenarios/{scenario_id}/analyze")
    async def analyze_saved_scenario(request: Request, scenario_id: str):
        record = store.get_scenario(scenario_id)
        started = time.perf_counter()
        result = analyze_scenario(
            record["scenario"],
            adapter=adapter,
            timeout_seconds=_timeout_query(request, config.max_timeout_seconds),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        analysis_record = store.save_analysis(
            scenario_id,
            result,
            raw_scenario=record["scenario"],
            raw_scenario_json=record.get("rawScenarioJson"),
            execution_ms=elapsed_ms,
        )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "executionMs": elapsed_ms,
            "analysis": result.to_dict(),
            "analysisRun": analysis_record,
        }

    @app.post("/v1/scenarios/{scenario_id}/revisions/{revision_no}/analyze")
    async def analyze_saved_revision(request: Request, scenario_id: str, revision_no: int):
        record = store.get_scenario_revision(scenario_id, revision_no)
        _set_scenario_context(request, record["scenario"])
        started = time.perf_counter()
        result = analyze_scenario(
            record["scenario"],
            adapter=adapter,
            timeout_seconds=_timeout_query(request, config.max_timeout_seconds),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        analysis_record = store.save_analysis(
            scenario_id,
            result,
            raw_scenario=record["scenario"],
            raw_scenario_json=record.get("rawScenarioJson"),
            revision_no=revision_no,
            execution_ms=elapsed_ms,
        )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "revisionNo": revision_no,
            "executionMs": elapsed_ms,
            "analysis": result.to_dict(),
            "analysisRun": analysis_record,
        }

    @app.post("/v1/scenarios/{scenario_id}/teach")
    async def teach_saved_scenario(request: Request, scenario_id: str):
        record = store.get_scenario(scenario_id)
        payload = await request.json()
        analysis_result = analyze_scenario(record["scenario"], adapter=adapter)
        question = _question_from_payload(payload)
        depth = _depth_from_payload(payload)
        response = teacher.explain(
            record["scenario"],
            analysis=analysis_result,
            depth=depth,
            user_question=question,
        )
        session = None
        profile_id = payload.get("profileId") if isinstance(payload, dict) else None
        if profile_id is not None:
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ApiError("invalid_profile_id", "profileId must be a non-empty string")
            store.get_or_create_profile(profile_id)
            session = store.save_teaching_session(
                response.to_dict(),
                teacher_version=teacher.version,
                prompt_version=teacher.prompt_version,
                depth=depth,
                user_question=question if config.store_user_text else None,
                profile_id=profile_id,
                scenario_id=scenario_id,
            )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "teacherVersion": teacher.version,
            "promptVersion": teacher.prompt_version,
            "provider": getattr(teacher, "provider", "local"),
            "degraded": getattr(teacher, "degraded", False),
            "response": response.to_dict(),
            "session": session,
        }

    @app.post("/v1/scenarios/state")
    async def scenario_state(request: Request):
        scenario = _scenario_from_request(await request.json())
        _set_scenario_context(request, scenario)
        node_scenario = scenario.model_copy(
            update={"action_history": scenario.action_history[: scenario.decision_point.after_sequence]}
        )
        replay = adapter.replay(node_scenario)
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
        _set_scenario_context(request, scenario)
        scenario_hash = scenario_fingerprint(scenario)
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            cached = idempotency_cache.get(idempotency_key)
            if cached is not None:
                request.state.cache_hit = True
                cached_hash, cached_payload = cached
                if cached_hash != scenario_hash:
                    raise ApiError(
                        "idempotency_conflict",
                        "Idempotency-Key was already used for a different scenario",
                        status_code=409,
                    )
                replay = dict(cached_payload)
                replay["requestId"] = request.state.request_id
                replay["idempotentReplay"] = True
                return replay
        started = time.perf_counter()
        result = analyze_scenario(
            scenario,
            adapter=adapter,
            timeout_seconds=_timeout_query(request, config.max_timeout_seconds),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        response_payload = {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "analysisVersion": result.analysis_version,
            "executionMs": elapsed_ms,
            "analysis": result.to_dict(),
        }
        if idempotency_key:
            idempotency_cache[idempotency_key] = (scenario_hash, response_payload)
        return response_payload

    @app.post("/v1/analysis/equity")
    async def equity_analysis(request: Request):
        scenario = _scenario_from_request(await request.json())
        _set_scenario_context(request, scenario)
        started = time.perf_counter()
        result = analyze_scenario(
            scenario,
            adapter=adapter,
            timeout_seconds=_timeout_query(request, config.max_timeout_seconds),
        )
        if result.equity is None:
            if result.multiway_equity is not None:
                return {
                    "schemaVersion": scenario.schema_version,
                    "requestId": request.state.request_id,
                    "analysisVersion": result.analysis_version,
                    "executionMs": elapsed_ms,
                    "equity": None,
                    "multiwayEquity": result.multiway_equity.to_dict(),
                    "evidence": result.evidence.to_dict(),
                }
            raise ApiError(
                "equity_unavailable",
                "equity requires a concrete villain hand or a non-empty villain range",
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "analysisVersion": result.analysis_version,
            "executionMs": elapsed_ms,
            "equity": result.equity.to_dict(),
            "evidence": result.evidence.to_dict(),
        }

    @app.post("/v1/analysis/jobs", status_code=202)
    async def submit_analysis_job(request: Request):
        scenario = _scenario_from_request(await request.json())
        _set_scenario_context(request, scenario)
        if job_backend.active_count() >= 64:
            raise ApiError("analysis_queue_full", "too many analysis jobs are active", status_code=429)
        job_id = job_backend.submit(
            scenario,
            timeout_seconds=_timeout_query(request, config.max_timeout_seconds),
        )
        return {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": "queued",
        }

    @app.get("/v1/analysis/jobs/{job_id}")
    async def get_analysis_job(request: Request, job_id: str):
        job = job_backend.get(job_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": job["status"],
            "executionMs": job.get("executionMs"),
            "error": job.get("error"),
            "analysis": job.get("analysis"),
        }

    @app.delete("/v1/analysis/jobs/{job_id}", status_code=202)
    async def cancel_analysis_job(request: Request, job_id: str):
        status = job_backend.cancel(job_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": status,
        }

    _solver_queue = solver_queue

    def _get_solver_queue():
        nonlocal _solver_queue
        if _solver_queue is None:
            if not config.redis_url:
                raise ApiError(
                    "solver_unavailable",
                    "solver jobs require POKER_COACH_REDIS_URL and the optional 'redis' dependency",
                    status_code=503,
                )
            _solver_queue = SolverJobQueue(config.redis_url)
        return _solver_queue

    @app.post("/v1/solve/jobs", status_code=202)
    async def submit_solve_job(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "request body must be a JSON object")
        scenario = _scenario_from_request(payload.get("scenario", payload))
        _set_scenario_context(request, scenario)
        # v1 compatibility: request-level legacy ranges override the scenario.
        # Schema v2 spots resolve their ranges from rangesBySeat (the
        # canonical source) inside build_spot, so there is no
        # heroRange/villainRange requirement here.
        hero_range = None
        villain_range = None
        if payload.get("heroRange") is not None:
            hero_range = RangeSpec.model_validate(payload["heroRange"])
        if payload.get("villainRange") is not None:
            villain_range = RangeSpec.model_validate(payload["villainRange"])
        max_iterations = payload.get("maxIterations", 400)
        if not isinstance(max_iterations, int) or max_iterations <= 0:
            raise ApiError("invalid_request", "maxIterations must be a positive integer")
        try:
            spot = build_spot(
                scenario,
                hero_range=hero_range,
                villain_range=villain_range,
                max_iterations=min(max_iterations, 50_000),
            )
        except SolverUnsupportedError as exc:
            raise ApiError("invalid_spot", str(exc)) from exc
        try:
            replay = _REPLAY_ADAPTER.replay_to_decision(scenario)
            active_seats = tuple(
                seat
                for seat in replay.final_state.stacks
                if seat not in replay.final_state.folded_seats
            )
            oop_seat, ip_seat = postflop_seat_pair(scenario, replay=replay)
        except (ReplayError, SolverUnsupportedError) as exc:
            raise ApiError("invalid_spot", str(exc)) from exc
        provenance = SolverJobProvenance(
            scenario_fingerprint=scenario_fingerprint(scenario),
            spot_fingerprint=solver_spot_fingerprint(spot),
            decision_sequence=scenario.decision_point.after_sequence,
            policy_sequence=scenario.decision_point.after_sequence + 1,
            actor_seat=scenario.decision_point.actor_seat,
            active_seats=(oop_seat, ip_seat),
            street=spot.street,
        )
        job_id = _get_solver_queue().submit(spot, provenance=provenance)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": "queued",
            "spot": spot.to_dict(),
            "provenance": provenance.to_dict(),
            "scenarioFingerprint": provenance.scenario_fingerprint,
            "spotFingerprint": provenance.spot_fingerprint,
            "policySequence": provenance.policy_sequence,
            "actorSeat": provenance.actor_seat,
            "activeSeats": list(provenance.active_seats),
        }

    @app.get("/v1/solve/jobs/{job_id}")
    async def get_solve_job(request: Request, job_id: str):
        job = _get_solver_queue().get(job_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": job["status"],
            "executionMs": job.get("executionMs"),
            "error": job.get("error"),
            "spot": job["spot"].to_dict() if job.get("spot") is not None else None,
            "provenance": (
                job["provenance"].to_dict()
                if job.get("provenance") is not None
                else None
            ),
            "result": job["result"].to_dict() if job.get("result") is not None else None,
        }

    @app.post("/v1/solve/jobs/{job_id}/cancel", status_code=202)
    async def cancel_solve_job(request: Request, job_id: str):
        status = _get_solver_queue().cancel(job_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "jobId": job_id,
            "status": status,
        }

    @app.post("/v1/teaching")
    async def teaching(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "request body must be a JSON object")
        scenario = _scenario_from_request(payload.get("scenario", payload))
        _set_scenario_context(request, scenario)
        raw_analysis = payload.get("analysis")
        if isinstance(raw_analysis, dict) and "analysis" in raw_analysis:
            raw_analysis = raw_analysis["analysis"]
        analysis_result = (
            AnalysisResult.model_validate(raw_analysis)
            if raw_analysis
            else analyze_scenario(scenario, adapter=adapter)
        )
        question = _question_from_payload(payload)
        depth = _depth_from_payload(payload)
        response = teacher.explain(
            scenario,
            analysis=analysis_result,
            depth=depth,
            user_question=question,
        )
        session = None
        profile_id = payload.get("profileId")
        if profile_id is not None:
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ApiError("invalid_profile_id", "profileId must be a non-empty string")
            store.get_or_create_profile(profile_id)
            session = store.save_teaching_session(
                response.to_dict(),
                teacher_version=teacher.version,
                prompt_version=teacher.prompt_version,
                depth=depth,
                user_question=question if config.store_user_text else None,
                profile_id=profile_id,
            )
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "teacherVersion": teacher.version,
            "promptVersion": teacher.prompt_version,
            "provider": getattr(teacher, "provider", "local"),
            "degraded": getattr(teacher, "degraded", False),
            "response": response.to_dict(),
            "session": session,
        }

    @app.post("/v1/strategies/match")
    async def strategy_match(request: Request):
        scenario = _scenario_from_request(await request.json())
        _set_scenario_context(request, scenario)
        match = strategy_catalog.match(scenario)
        return {
            "schemaVersion": scenario.schema_version,
            "requestId": request.state.request_id,
            "libraryVersion": strategy_catalog.version,
            "strategyMatch": match.to_dict(),
        }

    @app.get("/v1/ranges/defaults")
    async def default_ranges(request: Request):
        ranges = default_preflop_ranges()
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "version": next(iter(ranges.values())).version,
            "ranges": {key: value.to_dict() for key, value in ranges.items()},
        }

    @app.post("/v1/learning/profiles")
    async def create_learning_profile(request: Request):
        payload = await request.json()
        profile_id = payload.get("profileId") if isinstance(payload, dict) else None
        if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
            raise ApiError("invalid_profile_id", "profileId must be a non-empty string")
        profile = store.get_or_create_profile(profile_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "profile": profile.to_dict(),
        }

    @app.get("/v1/learning/profiles/{profile_id}")
    async def get_learning_profile(request: Request, profile_id: str):
        profile = store.get_profile(profile_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "profile": profile.to_dict(),
        }

    @app.delete("/v1/learning/profiles/{profile_id}")
    async def delete_learning_profile(request: Request, profile_id: str):
        store.delete_profile(profile_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "deleted": True,
        }

    @app.post("/v1/practice/generate")
    async def generate_practice(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "request body must be a JSON object")
        profile_id = payload.get("profileId")
        if profile_id is None:
            profile_id = store.get_or_create_profile().profile_id
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ApiError("invalid_profile_id", "profileId must be a non-empty string")
        source_scenario_id = payload.get("sourceScenarioId")
        if source_scenario_id:
            source = store.get_scenario(source_scenario_id)
            source_scenario = source["scenario"]
        else:
            source_scenario = _scenario_from_request(payload.get("scenario", payload))
        store.get_or_create_profile(profile_id)
        try:
            question = learning.generate_practice(
                source_scenario,
                profile_id=profile_id,
                source_scenario_id=source_scenario_id,
                source_analysis_id=payload.get("sourceAnalysisId"),
                mistake_tag=payload.get("mistakeTag"),
            )
        except PracticeUnavailable as exc:
            raise ApiError("practice_unavailable", str(exc)) from exc
        store.save_practice_question(question)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "learningVersion": learning.version,
            "question": _public_practice(question),
        }

    @app.get("/v1/practice/{question_id}")
    async def get_practice(request: Request, question_id: str):
        question = store.get_practice_question(question_id)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "question": _public_practice(question),
        }

    @app.post("/v1/practice/{question_id}/attempt")
    async def attempt_practice(request: Request, question_id: str):
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("selectedAction"), str):
            raise ApiError("invalid_practice_attempt", "selectedAction must be a string")
        question = store.get_practice_question(question_id)
        legal = adapter.replay(question.scenario).final_state.legal_actions.actions
        if payload["selectedAction"] not in {action.value for action in legal}:
            raise ApiError(
                "illegal_practice_action",
                "selectedAction is not legal at the practice decision point",
                details={"legalActions": [action.value for action in legal]},
            )
        profile = store.get_or_create_profile(question.profile_id)
        outcome = learning.grade(
            question,
            selected_action=payload["selectedAction"],
            rationale=payload.get("rationale"),
            profile=profile,
        )
        saved = store.save_practice_outcome(question, outcome)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "outcome": saved,
        }

    @app.post("/v1/ranges/parse")
    async def parse_range(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("notation"), str):
            raise ApiError("invalid_range_request", "notation must be a string")
        dead_cards = payload.get("deadCards", [])
        if not isinstance(dead_cards, list) or not all(isinstance(card, str) for card in dead_cards):
            raise ApiError("invalid_range_request", "deadCards must be a list of card strings")
        try:
            range_spec = range_spec_from_notation(
                payload["notation"],
                range_id=payload.get("rangeId", "notation-range"),
                name=payload.get("name", "Imported range"),
                version=payload.get("version", "1"),
                dead_cards=tuple(dead_cards),
            )
        except (ValueError, ValidationError) as exc:
            raise ApiError("invalid_range_notation", str(exc)) from exc
        combos = expand_range(range_spec)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "range": range_spec.to_dict(),
            "summary": {
                "totalCombos": len(combos),
                "weightedCombos": sum((combo.weight for combo in combos), start=0),
            },
            "combos": [combo.to_dict() for combo in combos],
        }

    @app.post("/v1/ranges/belief")
    async def range_belief(request: Request):
        """Combo-level action-conditioned belief for one seat.

        Payload: ``{scenario, seatId?, afterSequence?, policy?}``. ``policy``
        may be ``{source: "fixture", frequencies}`` (deterministic override),
        ``{source: "solver", jobId}`` (the preferred persisted artifact
        path). A raw ``result`` remains a compatibility path but is marked
        ``confidence=unverified``. When no grounded policy covers the node the response reports
        ``available=false`` with a reason — numbers are never fabricated.
        """
        payload = await request.json()
        scenario, seat_id, after_sequence, provider = _belief_request(
            payload, solver_queue=_solver_queue_for_belief(payload, _get_solver_queue)
        )
        _set_scenario_context(request, scenario)
        prior_range = _prior_range_for(scenario, seat_id)
        pot_cache: dict[int, int | None] = {}

        def pot_before(sequence: int) -> int | None:
            if sequence not in pot_cache:
                pot_cache[sequence] = _pot_before_sequence(scenario, sequence, adapter)
            return pot_cache[sequence]

        try:
            trace = build_range_trace(
                scenario,
                seat_id,
                prior_range=prior_range,
                providers=provider,
                max_sequence=after_sequence,
                pot_provider=pot_before,
            )
        except NoPriorRangeError as exc:
            raise ApiError("no_prior_range", str(exc)) from exc
        view = build_belief_view(trace)
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            **view.to_dict(),
        }

    @app.post("/v1/ranges/trace")
    async def range_trace(request: Request):
        """Full snapshot chain for one seat up to ``afterSequence``."""
        payload = await request.json()
        scenario, seat_id, after_sequence, provider = _belief_request(
            payload, solver_queue=_solver_queue_for_belief(payload, _get_solver_queue)
        )
        _set_scenario_context(request, scenario)
        prior_range = _prior_range_for(scenario, seat_id)
        pot_cache: dict[int, int | None] = {}

        def pot_before(sequence: int) -> int | None:
            if sequence not in pot_cache:
                pot_cache[sequence] = _pot_before_sequence(scenario, sequence, adapter)
            return pot_cache[sequence]

        try:
            trace = build_range_trace(
                scenario,
                seat_id,
                prior_range=prior_range,
                providers=provider,
                max_sequence=after_sequence,
                pot_provider=pot_before,
            )
        except NoPriorRangeError as exc:
            raise ApiError("no_prior_range", str(exc)) from exc
        return {
            "schemaVersion": 1,
            "requestId": request.state.request_id,
            "seatId": trace.seat_id,
            "available": trace.available,
            "unavailableReason": trace.unavailable_reason,
            "stalledAtSequence": trace.stalled_at_sequence,
            "snapshots": [snapshot.to_dict() for snapshot in trace.snapshots],
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


def _set_scenario_context(request: Request, scenario: ScenarioSpec) -> None:
    request.state.scenario_hash = scenario_fingerprint(scenario)


def _saved_scenario_from_request(
    payload: Any,
) -> tuple[ScenarioSpec, str, tuple[str, ...], str]:
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
    if len(tags) != len(set(tags)):
        raise ApiError("invalid_tags", "tags must be unique")
    return (
        scenario,
        title.strip(),
        tuple(tags),
        json.dumps(raw_scenario, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
    )


def _record_to_json(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("rawScenarioJson", None)
    scenario = result.get("scenario")
    if isinstance(scenario, ScenarioSpec):
        result["scenario"] = scenario.to_dict()
    return result


def _public_practice(question) -> dict[str, Any]:
    result = question.to_dict()
    result.pop("expectedAction", None)
    result.pop("expectedEvidenceReferences", None)
    return result


def _belief_request(
    payload: Any,
    *,
    solver_queue=None,
) -> tuple[ScenarioSpec, int, int | None, Any | None]:
    """Parse and validate a /v1/ranges/belief or /v1/ranges/trace payload.

    Returns ``(scenario, seat_id, after_sequence, policy_provider)``.
    ``after_sequence`` is None when the caller should default to the
    scenario's decision point; ``policy_provider`` is None when no policy
    was supplied (prior-only, current belief unavailable).
    """
    if not isinstance(payload, dict):
        raise ApiError("invalid_request", "request body must be a JSON object")
    scenario = _scenario_from_request(payload.get("scenario", payload))
    seat_id = payload.get("seatId", scenario.hero_seat)
    if not isinstance(seat_id, int):
        raise ApiError("invalid_request", "seatId must be an integer")
    seat_ids = {seat.seat_id for seat in scenario.seats}
    if seat_id not in seat_ids:
        raise ApiError("invalid_request", f"seatId {seat_id} is not a seat in this scenario")
    after_sequence = payload.get("afterSequence")
    if after_sequence is not None and (
        not isinstance(after_sequence, int) or after_sequence < 0
    ):
        raise ApiError("invalid_request", "afterSequence must be a non-negative integer")
    policy_payload = payload.get("policy")
    providers: list[Any] = []
    if policy_payload is not None:
        policy_payloads = policy_payload if isinstance(policy_payload, list) else [policy_payload]
        for item in policy_payloads:
            provider = _belief_policy_provider(
                scenario, item, after_sequence, solver_queue=solver_queue
            )
            if provider is not None:
                providers.append(provider)
    return scenario, seat_id, after_sequence, providers


def _belief_policy_provider(
    scenario: ScenarioSpec,
    policy_payload: Any,
    after_sequence: int | None,
    *,
    solver_queue=None,
):
    if not isinstance(policy_payload, dict) or not isinstance(policy_payload.get("source"), str):
        raise ApiError("invalid_policy", "policy.source must be a string")
    source = policy_payload["source"]
    if source == "manual":
        return None
    if source == "fixture":
        frequencies = policy_payload.get("frequencies")
        if not isinstance(frequencies, dict):
            raise ApiError("invalid_policy", "fixture policy requires a frequencies table")
        try:
            return FixturePolicyProvider(frequencies)
        except InvalidPolicyError as exc:
            raise ApiError("invalid_policy", str(exc)) from exc
    if source == "solver":
        job_id = policy_payload.get("jobId")
        raw_result = policy_payload.get("result")
        if job_id is not None:
            if not isinstance(job_id, str) or not job_id.strip():
                raise ApiError("invalid_policy", "solver policy jobId must be a non-empty string")
            if solver_queue is None:
                raise ApiError("solver_unavailable", "solver job lookup is unavailable", status_code=503)
            try:
                job = solver_queue.get(job_id)
            except StoreNotFound as exc:
                raise ApiError(
                    "solver_artifact_mismatch",
                    f"solver job {job_id!r} was not found",
                ) from exc
            if job.get("status") != "solved" or job.get("result") is None:
                raise ApiError(
                    "no_policy",
                    f"solver job {job_id!r} is not solved and cannot ground a policy",
                )
            provenance = job.get("provenance")
            if provenance is None:
                raise ApiError(
                    "solver_artifact_mismatch",
                    "solver job has no exact-node provenance metadata",
                )
            try:
                node_scenario = scenario_at_policy_sequence(
                    scenario, provenance.policy_sequence
                )
                expected_spot = build_spot(node_scenario)
            except (SolverUnsupportedError, ReplayError) as exc:
                raise ApiError("solver_artifact_mismatch", str(exc)) from exc
            requested_scenario_fingerprint = scenario_fingerprint(node_scenario)
            requested_spot_fingerprint = solver_spot_fingerprint(expected_spot)
            if (
                requested_scenario_fingerprint != provenance.scenario_fingerprint
                or requested_spot_fingerprint != provenance.spot_fingerprint
            ):
                raise ApiError(
                    "solver_artifact_mismatch",
                    "solver artifact does not match the requested scenario/node",
                    details={
                        "expectedScenarioFingerprint": provenance.scenario_fingerprint,
                        "requestedScenarioFingerprint": requested_scenario_fingerprint,
                        "expectedSpotFingerprint": provenance.spot_fingerprint,
                        "requestedSpotFingerprint": requested_spot_fingerprint,
                    },
                )
            try:
                oop_seat, ip_seat = postflop_seat_pair(node_scenario)
            except SolverUnsupportedError as exc:
                raise ApiError("solver_artifact_mismatch", str(exc)) from exc
            if tuple(sorted((oop_seat, ip_seat))) != tuple(sorted(provenance.active_seats)):
                raise ApiError(
                    "solver_artifact_mismatch",
                    "solver artifact active seats do not match the requested node",
                )
            reference_pot = _pot_before_sequence(
                node_scenario, provenance.policy_sequence, _REPLAY_ADAPTER
            )
            return SolverPolicyAdapter(
                job["result"],
                oop_seat=oop_seat,
                ip_seat=ip_seat,
                reference_pot=reference_pot,
                policy_sequence=provenance.policy_sequence,
                actor_seat=provenance.actor_seat,
                confidence="grounded",
            )
        if not isinstance(raw_result, dict):
            raise ApiError(
                "invalid_policy",
                "solver policy requires jobId; raw result is accepted only as unverified compatibility input",
            )
        try:
            result = parse_result(raw_result)
        except (SolverUnsupportedError, KeyError, TypeError, ValidationError) as exc:
            raise ApiError("invalid_policy", f"invalid solver result: {exc}") from exc
        try:
            oop_seat, ip_seat = postflop_seat_pair(scenario)
        except SolverUnsupportedError as exc:
            raise ApiError("invalid_policy", str(exc)) from exc
        max_sequence = (
            after_sequence if after_sequence is not None else scenario.decision_point.after_sequence
        )
        reference_pot = _pot_before_sequence(scenario, max_sequence, _REPLAY_ADAPTER)
        return SolverPolicyAdapter(
            result,
            oop_seat=oop_seat,
            ip_seat=ip_seat,
            reference_pot=reference_pot,
            confidence="unverified",
        )
    raise ApiError("invalid_policy", f"unsupported policy source: {source!r}")


def _solver_queue_for_belief(payload: Any, get_queue):
    """Resolve Redis only for a belief request that explicitly uses jobId."""
    if not isinstance(payload, dict):
        return None
    policy = payload.get("policy")
    items = policy if isinstance(policy, list) else [policy]
    if any(
        isinstance(item, dict)
        and item.get("source") == "solver"
        and "jobId" in item
        for item in items
    ):
        return get_queue()
    return None


def _prior_range_for(scenario: ScenarioSpec, seat_id: int) -> RangeSpec:
    """Resolve the seat's prior range from rangesBySeat (canonical source)."""
    prior = scenario.ranges_by_seat.get(seat_id)
    if prior is None:
        raise ApiError(
            "no_prior_range",
            f"no prior range is available for seat {seat_id} "
            "(set rangesBySeat before requesting a belief)",
        )
    return prior


def _pot_before_sequence(
    scenario: ScenarioSpec, sequence: int, adapter: PokerKitAdapter
) -> int | None:
    """Pot before the action at ``sequence`` (None when unknown)."""
    if sequence <= 0:
        return None
    truncated = scenario.model_copy(
        update={
            "action_history": scenario.action_history[: sequence - 1],
            "decision_point": scenario.decision_point.model_copy(
                update={"after_sequence": sequence - 1}
            ),
        }
    )
    try:
        replay = adapter.replay(truncated)
    except ReplayError:
        return None
    return int(replay.final_state.pot)


# Module-level adapter for pot lookups inside _belief_policy_provider (the
# per-request ``adapter`` closure lives in create_app).
_REPLAY_ADAPTER = PokerKitAdapter()


def _question_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("question") is None:
        return None
    question = payload["question"]
    if not isinstance(question, str):
        raise ApiError("invalid_question", "question must be a string")
    question = question.strip()
    if len(question) > 2_000:
        raise ApiError("question_too_long", "question cannot exceed 2000 characters")
    return question or None


def _depth_from_payload(payload: Any) -> str:
    depth = payload.get("depth", "intermediate") if isinstance(payload, dict) else "intermediate"
    if depth not in {"beginner", "intermediate", "advanced"}:
        raise ApiError("invalid_teaching_depth", "depth must be beginner, intermediate, or advanced")
    return depth


def _timeout_query(request: Request, max_timeout_seconds: float = 120.0) -> float | None:
    raw = request.query_params.get("timeoutSeconds")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ApiError("invalid_timeout", "timeoutSeconds must be numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ApiError("invalid_timeout", "timeoutSeconds must be finite and non-negative")
    if value > max_timeout_seconds:
        raise ApiError(
            "timeout_too_large",
            f"timeoutSeconds cannot exceed {max_timeout_seconds:g}",
            details={"maxTimeoutSeconds": max_timeout_seconds},
        )
    return value


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _rate_limit_key(request: Request) -> str:
    session = request.headers.get("X-Anonymous-Session")
    if session and len(session) <= 128:
        return f"session:{session}"
    host = request.client.host if request.client is not None else "unknown"
    return f"host:{host}"


def _allow_request(
    state: dict[str, list[float]],
    lock: Lock,
    key: str,
    *,
    limit: int,
    now: float | None = None,
) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - 60.0
    with lock:
        timestamps = [stamp for stamp in state.get(key, []) if stamp > cutoff]
        allowed = len(timestamps) < limit
        if allowed:
            timestamps.append(current)
        if timestamps:
            state[key] = timestamps
        else:
            state.pop(key, None)
        return allowed


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
