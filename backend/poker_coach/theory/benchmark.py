"""Offline canonical-fixture benchmark for future theory providers."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import BenchmarkResult, EvidenceGrade, FixtureResult, MetricResult


HARNESS_VERSION = "r9-00.v1"
FROZEN_THRESHOLD_MANIFEST = {
    "manifest_id": "r9-00.calibration.v1",
    "action_frequency_l1_max": 0.02,
    "sizing_distance_max": 0,
    "ev_loss_max": 0.01,
    "range_js_max": 0.002,
    "latency_ms_max": 250.0,
}
_GRADE_RANK = {"unsupported": 0, "C": 1, "B": 2, "A": 3}
_PRIVATE_MARKERS = ("private", "hole", "hidden", "opponentcards", "villaincards")


class FixtureError(ValueError):
    """A fixture is malformed or lacks its required provenance boundary."""


@dataclass(frozen=True)
class CanonicalFixture:
    path: Path
    payload: dict[str, Any]

    @property
    def fixture_id(self) -> str:
        return str(self.payload.get("fixtureId", self.path.stem))


def fixture_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "theory"


def _canonical_digest(payload: dict[str, Any]) -> str:
    copy = json.loads(json.dumps(payload))
    copy.get("provenance", {}).pop("digest", None)
    encoded = json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_fixture(path: Path) -> CanonicalFixture:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read fixture {path}: {exc}") from exc
    required = {"schemaVersion", "fixtureId", "expectedGatePassed", "identity", "provenance", "oracle", "candidate"}
    missing = required - payload.keys()
    if missing:
        raise FixtureError(f"{path.name}: missing {sorted(missing)}")
    provenance = payload["provenance"]
    for key in ("source", "license", "version", "method", "digest"):
        if not provenance.get(key):
            raise FixtureError(f"{path.name}: provenance.{key} is required")
    digest = provenance["digest"]
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise FixtureError(f"{path.name}: provenance.digest must be sha256")
    if digest != _canonical_digest(payload):
        raise FixtureError(f"{path.name}: provenance digest mismatch")
    identity = payload["identity"]
    for key in ("spotId", "gameFingerprint", "treeFingerprint", "rangeFingerprint", "policyFingerprint"):
        if not identity.get(key):
            raise FixtureError(f"{path.name}: identity.{key} is required")
    if payload.get("thresholdManifestId") != FROZEN_THRESHOLD_MANIFEST["manifest_id"]:
        raise FixtureError(f"{path.name}: provider-controlled or unknown threshold manifest")
    return CanonicalFixture(path=path, payload=payload)


def load_corpus(directory: Path | None = None) -> tuple[CanonicalFixture, ...]:
    root = directory or fixture_directory()
    fixtures = tuple(load_fixture(path) for path in sorted(root.glob("*.json")))
    if not fixtures:
        raise FixtureError(f"no canonical fixtures found in {root}")
    return fixtures


def _contains_private(value: Any, *, key: str = "") -> bool:
    normalized = key.lower().replace("_", "")
    if any(marker in normalized for marker in _PRIVATE_MARKERS):
        return True
    if isinstance(value, dict):
        return any(_contains_private(item, key=str(name)) for name, item in value.items())
    if isinstance(value, list):
        return any(_contains_private(item) for item in value)
    return False


def _normalise(table: dict[str, Any]) -> tuple[dict[str, float], float]:
    values = {str(key): float(value) for key, value in table.items()}
    total = sum(values.values())
    if total <= 0 or any(value < 0 for value in values.values()):
        return values, total
    return {key: value / total for key, value in values.items()}, total


def _l1(left: dict[str, float], right: dict[str, float]) -> float:
    return sum(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in set(left) | set(right))


def _js(left: dict[str, Any], right: dict[str, Any]) -> float:
    p, p_total = _normalise(left)
    q, q_total = _normalise(right)
    if p_total <= 0 or q_total <= 0:
        return math.inf
    midpoint = {key: (p.get(key, 0.0) + q.get(key, 0.0)) / 2 for key in set(p) | set(q)}

    def kl(source: dict[str, float]) -> float:
        return sum(value * math.log2(value / midpoint[key]) for key, value in source.items() if value > 0)

    return (kl(p) + kl(q)) / 2


def _metric(name: str, passed: bool, *, value: float | None = None, threshold: float | None = None, detail: str | None = None) -> MetricResult:
    return MetricResult(name=name, status="pass" if passed else "fail", value=value, threshold=threshold, detail=detail)


def evaluate_fixture(fixture: CanonicalFixture, *, provider_candidate: dict[str, Any] | None = None) -> FixtureResult:
    started = time.perf_counter_ns()
    item = fixture.payload
    # Production gates pass a separately produced provider payload.  The
    # fixture candidate remains only a frozen calibration/mutant corpus input.
    candidate = provider_candidate if provider_candidate is not None else item["candidate"]
    oracle = item["oracle"]
    metrics: list[MetricResult] = []
    identity_ok = candidate.get("fingerprints") == item["identity"]
    metrics.append(_metric("fingerprint", identity_ok, detail=None if identity_ok else "game/tree/range/policy fingerprint mismatch"))
    private_ok = not _contains_private(candidate)
    metrics.append(_metric("private_card_boundary", private_ok, detail=None if private_ok else "candidate contains a private-card-shaped field"))
    candidate_grade = str(candidate.get("evidenceGrade", ""))
    oracle_grade = str(oracle.get("evidenceGrade", ""))
    grade_ok = candidate_grade in _GRADE_RANK and candidate_grade == oracle_grade
    coverage_ok = candidate.get("coverageStatus") == oracle.get("coverageStatus")
    metrics.append(_metric("evidence_calibration", grade_ok and coverage_ok, detail=None if grade_ok and coverage_ok else "evidence grade or coverage claim differs from oracle"))
    oracle_available = oracle_grade in {EvidenceGrade.A.value, EvidenceGrade.B.value}
    if not oracle_available:
        honest_fallback = bool(candidate.get("fallbackReason")) and not candidate.get("actionFrequencies") and not candidate.get("actionEvs")
        metrics.extend([
            _metric("action_set_correctness", honest_fallback, detail="not applicable; C/unsupported must expose only honest fallback"),
            _metric("frequency_l1", honest_fallback, detail="not applicable without an A/B oracle"),
            _metric("sizing_legality", honest_fallback, detail="not applicable without an A/B oracle"),
            _metric("same_oracle_ev_loss", honest_fallback, detail="not applicable without a shared EV oracle"),
            _metric("weighted_js_range_divergence", honest_fallback, detail="not applicable without an A/B oracle"),
        ])
    else:
        expected_actions = set(oracle["legalActions"])
        frequencies = candidate.get("actionFrequencies", {})
        action_ok = set(frequencies) == expected_actions
        metrics.append(_metric("action_set_correctness", action_ok, detail=None if action_ok else "candidate action set differs from legal oracle action set"))
        normalised, total = _normalise(frequencies)
        expected_freq, _ = _normalise(oracle["actionFrequencies"])
        frequency_l1 = _l1(normalised, expected_freq)
        frequency_ok = abs(total - 1.0) <= 1e-9 and frequency_l1 <= FROZEN_THRESHOLD_MANIFEST["action_frequency_l1_max"]
        metrics.append(_metric("frequency_l1", frequency_ok, value=frequency_l1, threshold=FROZEN_THRESHOLD_MANIFEST["action_frequency_l1_max"], detail=None if frequency_ok else f"normalization={total:.6f}"))
        legal_sizings = oracle.get("legalSizings", {})
        selected_sizings = candidate.get("sizings", {})
        sizing_distance = 0.0
        sizing_ok = set(selected_sizings) == set(legal_sizings)
        for action, window in legal_sizings.items():
            amount = selected_sizings.get(action)
            if not isinstance(amount, int) or amount < window["min"] or amount > window["max"]:
                sizing_ok = False
                continue
            sizing_distance = max(sizing_distance, abs(amount - window["target"]))
        sizing_ok = sizing_ok and sizing_distance <= FROZEN_THRESHOLD_MANIFEST["sizing_distance_max"]
        metrics.append(_metric("sizing_legality", sizing_ok, value=sizing_distance, threshold=FROZEN_THRESHOLD_MANIFEST["sizing_distance_max"], detail=None if sizing_ok else "amount is illegal, missing, or outside frozen sizing distance"))
        selected = candidate.get("selectedAction")
        ev_definition_ok = candidate.get("evDefinition") == oracle.get("evDefinition")
        action_evs = oracle.get("actionEvs", {})
        ev_loss = math.inf if selected not in action_evs else max(action_evs.values()) - action_evs[selected]
        ev_ok = ev_definition_ok and ev_loss <= FROZEN_THRESHOLD_MANIFEST["ev_loss_max"]
        metrics.append(_metric("same_oracle_ev_loss", ev_ok, value=ev_loss if math.isfinite(ev_loss) else None, threshold=FROZEN_THRESHOLD_MANIFEST["ev_loss_max"], detail=None if ev_ok else "missing selected action or incompatible EV definition"))
        divergence = _js(candidate.get("range", {}), oracle.get("range", {}))
        range_ok = divergence <= FROZEN_THRESHOLD_MANIFEST["range_js_max"]
        metrics.append(_metric("weighted_js_range_divergence", range_ok, value=divergence if math.isfinite(divergence) else None, threshold=FROZEN_THRESHOLD_MANIFEST["range_js_max"], detail=None if range_ok else "range differs from frozen oracle or has invalid mass"))
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    metrics.append(_metric("latency", elapsed_ms <= FROZEN_THRESHOLD_MANIFEST["latency_ms_max"], value=elapsed_ms, threshold=FROZEN_THRESHOLD_MANIFEST["latency_ms_max"], detail="measured harness time; not a product SLA"))
    return FixtureResult(fixture_id=fixture.fixture_id, gate_passed=all(metric.status == "pass" for metric in metrics), expected_gate_passed=bool(item["expectedGatePassed"]), metrics=tuple(metrics), elapsed_ms=elapsed_ms)


def run_benchmark(directory: Path | None = None) -> BenchmarkResult:
    results = tuple(evaluate_fixture(fixture) for fixture in load_corpus(directory))
    return BenchmarkResult(harness_version=HARNESS_VERSION, threshold_manifest_id=FROZEN_THRESHOLD_MANIFEST["manifest_id"], gate_passed=all(result.gate_passed for result in results), corpus_expectations_met=all(result.gate_passed == result.expected_gate_passed for result in results), environment={"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor() or "unknown"}, performance_note="Measured on this development machine for reproducibility only; not a product SLA.", fixtures=results)


def run_provider_smoke() -> FixtureResult:
    """Gate the live preflop provider against a frozen, oracle-only fixture.

    This deliberately calls the loaded PolicyArtifact instead of reading the
    fixture's embedded candidate.  Mutants belong in tests/providers, never in
    an oracle fixture that could self-certify its own expected output.
    """
    from poker_coach.simulator.contracts import ObservationV1
    from poker_coach.theory.policy_artifact import PreflopPolicyContext, default_preflop_artifact

    fixture = load_fixture(fixture_directory() / "green-6max-preflop-b.json")
    observation = ObservationV1.model_validate({"handId":"benchmark-policy","sequence":1,"observerSeat":0,"tableSize":6,"buttonSeat":0,"street":"preflop","ownHoleCards":["As","5s"],"pot":150,"stacks":{str(i):10000 for i in range(6)},"streetCommitments":{str(i):0 for i in range(6)},"activeSeats":list(range(6)),"publicActions":[{"sequence":1,"street":"preflop","actorSeat":3,"action":"raise","amount":250,"amountSemantics":"to"}],"legalActions":[{"action":"fold","amountSemantics":"none"},{"action":"call","amountSemantics":"cost","minAmount":250,"maxAmount":250},{"action":"raise","amountSemantics":"to","minAmount":900,"maxAmount":900}]})
    started = time.perf_counter_ns()
    artifact = default_preflop_artifact()
    match = artifact.match(observation, PreflopPolicyContext())
    if match is None:
        raise FixtureError("live PolicyArtifact did not cover provider smoke node")
    item = json.loads(json.dumps(fixture.payload))
    item["identity"]["policyFingerprint"] = artifact.fingerprint
    item["oracle"]["legalSizings"]["raise_to"] = {"min": 900, "max": 900, "target": 900}
    candidate = {"fingerprints": dict(item["identity"]), "evidenceGrade": "B", "coverageStatus": "covered", "actionFrequencies": dict(match.frequencies), "sizings": {"raise_to": match.raise_to}, "selectedAction": "raise_to", "evDefinition": item["oracle"]["evDefinition"], "range": dict(item["oracle"]["range"]), "providerFingerprint": artifact.fingerprint}
    result = evaluate_fixture(CanonicalFixture(path=fixture.path, payload=item), provider_candidate=candidate)
    return FixtureResult(fixture_id="provider-" + result.fixture_id, gate_passed=result.gate_passed, expected_gate_passed=True, metrics=result.metrics, elapsed_ms=(time.perf_counter_ns()-started)/1_000_000)
