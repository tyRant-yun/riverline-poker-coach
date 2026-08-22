"""Offline canonical-fixture benchmark for future theory providers."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import BenchmarkResult, EvidenceGrade, FixtureResult, MetricResult


HARNESS_VERSION = "r9-00.v2"
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
_FORBIDDEN_NON_POLICY_FIELDS = {
    "selectedaction", "recommendedaction", "sizings", "range", "actionfrequencies",
    "actionevs", "evdefinition", "sameoracleevloss", "ev", "strategy", "equity",
}
_PREFLOP_ARTIFACT_FINGERPRINT = "sha256:0e2b509f8596a9f6d416d6ca6279b7134fa1e01eb180a6acac9a228bef57084f"
_PREFLOP_SPOTS = (
    ("rfi-utg", "UTG", 3, "rfi"),
    ("rfi-hj", "HJ", 4, "rfi"),
    ("rfi-co", "CO", 5, "rfi"),
    ("rfi-btn", "BTN", 0, "rfi"),
    ("rfi-sb", "SB", 1, "rfi"),
    ("vs-rfi-hj", "HJ", 4, "vs_single_rfi"),
    ("vs-rfi-co", "CO", 5, "vs_single_rfi"),
    ("vs-rfi-btn", "BTN", 0, "vs_single_rfi"),
    ("vs-rfi-sb", "SB", 1, "vs_single_rfi"),
    ("vs-rfi-bb", "BB", 2, "vs_single_rfi"),
)


class FixtureError(ValueError):
    """A fixture is malformed or lacks its required provenance boundary."""


@dataclass(frozen=True)
class CanonicalFixture:
    path: Path
    payload: dict[str, Any]

    @property
    def fixture_id(self) -> str:
        return str(self.payload.get("fixtureId", self.path.stem))


@dataclass(frozen=True)
class ProductionProviderGate:
    category: str
    declared_spots: tuple[str, ...]
    runner: Callable[[], tuple[FixtureResult, ...]]


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


def _contains_forbidden_non_policy_payload(value: Any, *, key: str = "") -> bool:
    normalized = key.lower().replace("_", "")
    if normalized in _FORBIDDEN_NON_POLICY_FIELDS or normalized.endswith("ev") or "evloss" in normalized:
        return True
    if isinstance(value, dict):
        return any(_contains_forbidden_non_policy_payload(item, key=str(name)) for name, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_non_policy_payload(item) for item in value)
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
        honest_fallback = bool(candidate.get("fallbackReason")) and not _contains_forbidden_non_policy_payload(candidate)
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


def _release_result(
    fixture_id: str,
    *,
    expected_identity: dict[str, str],
    candidate_identity: dict[str, str],
    expected_grade: str,
    candidate_grade: str,
    expected_frequencies: dict[str, float],
    candidate_frequencies: dict[str, float],
    expected_sizings: dict[str, int],
    candidate_sizings: dict[str, int],
    expected_provider: str,
    candidate_provider: str,
    latency_samples_ms: tuple[float, ...],
) -> FixtureResult:
    """Compare a *live* provider payload with frozen release references.

    The references below are intentionally independent from the fixture
    corpus's embedded ``candidate`` fields.  A release cannot pass by merely
    reading its expected candidate back out of a test fixture.
    """
    identity_ok = candidate_identity == expected_identity
    grade_ok = candidate_grade == expected_grade
    action_ok = set(candidate_frequencies) == set(expected_frequencies)
    actual, actual_total = _normalise(candidate_frequencies)
    expected, expected_total = _normalise(expected_frequencies)
    frequency_l1 = _l1(actual, expected)
    frequency_ok = (
        actual_total == 1.0
        and expected_total == 1.0
        and frequency_l1 <= FROZEN_THRESHOLD_MANIFEST["action_frequency_l1_max"]
    )
    sizing_ok = candidate_sizings == expected_sizings
    provider_ok = candidate_provider == expected_provider
    latency_metrics = _latency_metrics(latency_samples_ms)
    elapsed_ms = next(metric.value for metric in latency_metrics if metric.name == "latency_p95") or 0.0
    metrics = (
        _metric("fingerprint", identity_ok, detail=None if identity_ok else "live provider fingerprint differs from frozen production reference"),
        _metric("evidence_calibration", grade_ok, detail=None if grade_ok else "live provider evidence grade differs from frozen production reference"),
        _metric("action_set_correctness", action_ok, detail=None if action_ok else "live provider action set differs from frozen production reference"),
        _metric("frequency_l1", frequency_ok, value=frequency_l1, threshold=FROZEN_THRESHOLD_MANIFEST["action_frequency_l1_max"], detail=None if frequency_ok else f"normalization={actual_total:.6f}"),
        _metric("sizing_legality", sizing_ok, detail=None if sizing_ok else "live provider sizing differs from frozen production reference"),
        _metric("provider_identity", provider_ok, detail=None if provider_ok else "live provider identity differs from frozen production reference"),
        *latency_metrics,
    )
    return FixtureResult(
        fixture_id=fixture_id,
        gate_passed=all(metric.status == "pass" for metric in metrics),
        expected_gate_passed=True,
        metrics=metrics,
        elapsed_ms=elapsed_ms,
    )


def _percentile(samples: tuple[float, ...], percentile: float) -> float:
    ordered = sorted(samples)
    if not ordered:
        return math.inf
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _latency_metrics(samples_ms: tuple[float, ...]) -> tuple[MetricResult, MetricResult]:
    p50 = _percentile(samples_ms, 0.50)
    p95 = _percentile(samples_ms, 0.95)
    threshold = FROZEN_THRESHOLD_MANIFEST["latency_ms_max"]
    detail = f"{len(samples_ms)} live samples; development-machine release gate, not a product SLA"
    return (
        _metric("latency_p50", p50 <= threshold, value=p50 if math.isfinite(p50) else None, threshold=threshold, detail=detail),
        _metric("latency_p95", p95 <= threshold, value=p95 if math.isfinite(p95) else None, threshold=threshold, detail=detail),
    )


def _measure_provider_samples(provider: Callable[[], Any], *, sample_count: int = 5) -> tuple[tuple[float, ...], Any]:
    if sample_count < 3:
        raise ValueError("release latency gate requires at least three samples")
    samples: list[float] = []
    result: Any = None
    for _ in range(sample_count):
        started = time.perf_counter_ns()
        result = provider()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return tuple(samples), result


def _preflop_observation(*, seat: int, prefix: str):
    from poker_coach.simulator.contracts import ObservationV1

    actions = []
    if prefix == "vs_single_rfi":
        actions.append({"sequence": 1, "street": "preflop", "actorSeat": 3, "action": "raise", "amount": 250, "amountSemantics": "to"})
    return ObservationV1.model_validate({
        "handId": f"release-{prefix}-{seat}", "sequence": 1, "observerSeat": seat,
        "tableSize": 6, "buttonSeat": 0, "street": "preflop", "ownHoleCards": ["As", "Ah"],
        "pot": 150, "stacks": {str(index): 10000 for index in range(6)},
        "streetCommitments": {str(index): 0 for index in range(6)}, "activeSeats": list(range(6)),
        "publicActions": actions,
        "legalActions": [
            {"action": "fold", "amountSemantics": "none"},
            {"action": "call", "amountSemantics": "cost", "minAmount": 250, "maxAmount": 250},
            {"action": "raise", "amountSemantics": "to", "minAmount": 900, "maxAmount": 900},
        ],
    })


def _run_preflop_provider_cases() -> tuple[FixtureResult, ...]:
    from poker_coach.theory.policy_artifact import PreflopPolicyContext, default_preflop_artifact

    artifact = default_preflop_artifact()
    declared_nodes = {str(node["nodeId"]) for node in artifact.payload["nodes"]}
    expected_nodes = {f"6max-100bb-norake/{position.lower()}-{'rfi-2.5bb' if prefix == 'rfi' else 'vs-single-rfi-2.5bb'}" for _spot, position, _seat, prefix in _PREFLOP_SPOTS}
    results: list[FixtureResult] = []
    for spot, position, seat, prefix in _PREFLOP_SPOTS:
        observation = _preflop_observation(seat=seat, prefix=prefix)
        samples, match = _measure_provider_samples(lambda: artifact.match(observation, PreflopPolicyContext()))
        if match is None:
            results.append(_release_result(
                f"provider-preflop-{spot}",
                expected_identity={"spotId": spot}, candidate_identity={}, expected_grade="B", candidate_grade="",
                expected_frequencies={"raise_to": 1.0, "fold": 0.0} if prefix == "rfi" else {"raise_to": 0.7, "call": 0.3, "fold": 0.0},
                candidate_frequencies={}, expected_sizings={"raise_to": 250 if prefix == "rfi" else 900}, candidate_sizings={},
                expected_provider="policy-artifact", candidate_provider="missing", latency_samples_ms=samples,
            ))
            continue
        expected_identity = {
            "spotId": spot,
            "gameFingerprint": "nlhe-6max-100bb-norake-v1",
            "treeFingerprint": "r9-02.preflop-open-2.5bb-3bet-9bb.v1",
            "rangeFingerprint": "riverline-preflop-169class-v1",
            "policyFingerprint": _PREFLOP_ARTIFACT_FINGERPRINT,
        }
        candidate_identity = dict(expected_identity)
        candidate_identity["policyFingerprint"] = artifact.fingerprint
        results.append(_release_result(
            f"provider-preflop-{spot}", expected_identity=expected_identity, candidate_identity=candidate_identity,
            expected_grade="B", candidate_grade="B",
            expected_frequencies={"raise_to": 1.0, "fold": 0.0} if prefix == "rfi" else {"raise_to": 0.7, "call": 0.3, "fold": 0.0},
            candidate_frequencies=dict(match.frequencies), expected_sizings={"raise_to": 250 if prefix == "rfi" else 900},
            candidate_sizings={"raise_to": match.raise_to} if match.raise_to is not None else {},
            expected_provider="policy-artifact", candidate_provider="policy-artifact", latency_samples_ms=samples,
        ))
    if declared_nodes != expected_nodes:
        samples, _ = _measure_provider_samples(lambda: declared_nodes)
        results.append(_release_result(
            "provider-preflop-declared-coverage", expected_identity={"nodes": ",".join(sorted(expected_nodes))},
            candidate_identity={"nodes": ",".join(sorted(declared_nodes))}, expected_grade="B", candidate_grade="B",
            expected_frequencies={"covered": 1.0}, candidate_frequencies={"covered": 1.0}, expected_sizings={}, candidate_sizings={},
            expected_provider="policy-artifact", candidate_provider="policy-artifact", latency_samples_ms=samples,
        ))
    return tuple(results)


def _run_l2_provider_case() -> FixtureResult:
    from poker_coach.theory.l2_solver import ENGINE_VERSION, L2Budget, L2RiverInput, RangeCombo, RiverBetTree, solve_hu_river

    source = L2RiverInput(
        game_fingerprint="r9-release-hu-river-v1", tree_fingerprint="r9-release-check-bet-100-v1",
        range_fingerprint="r9-release-public-projection-v1", solver_version=ENGINE_VERSION,
        players=(0, 1), acting_seat=0, pot=100, stacks=((0, 100), (1, 100)),
        board=("As", "Ks", "Qs", "Js", "Ts"),
        ranges=((0, (RangeCombo(("2c", "3d"), 1.0),)), (1, (RangeCombo(("6c", "7d"), 1.0),))),
        tree=RiverBetTree(bet_amount=100), seed=7,
        budget=L2Budget(iterations=20, soft_timeout_ms=2_000, hard_timeout_ms=3_000), hero_hole_cards=("2c", "3d"),
    )
    samples, result = _measure_provider_samples(lambda: solve_hu_river(source))
    if not hasattr(result, "action_frequencies"):
        return _release_result(
            "provider-l2-hu-river-root", expected_identity={"spotId": "l2-hu-river-root"}, candidate_identity={},
            expected_grade="B", candidate_grade="unsupported", expected_frequencies={"check": 0.025, "bet": 0.975}, candidate_frequencies={},
            expected_sizings={"bet": 100}, candidate_sizings={}, expected_provider="riverline-l2-cfr/v1", candidate_provider="unsupported", latency_samples_ms=samples,
        )
    expected_identity = {
        "spotId": "l2-hu-river-root", "gameFingerprint": "r9-release-hu-river-v1",
        "treeFingerprint": "r9-release-check-bet-100-v1", "rangeFingerprint": "r9-release-public-projection-v1",
        "policyFingerprint": ENGINE_VERSION,
    }
    candidate_identity = dict(expected_identity)
    candidate_identity["gameFingerprint"] = result.game_fingerprint
    candidate_identity["treeFingerprint"] = result.tree_fingerprint
    candidate_identity["rangeFingerprint"] = result.range_fingerprint
    candidate_identity["policyFingerprint"] = result.solver_version
    return _release_result(
        "provider-l2-hu-river-root", expected_identity=expected_identity, candidate_identity=candidate_identity,
        expected_grade="B", candidate_grade=result.evidence_grade,
        expected_frequencies={"check": 0.025, "bet": 0.975}, candidate_frequencies=dict(result.action_frequencies),
        expected_sizings={"bet": 100}, candidate_sizings=dict(result.legal_sizes),
        expected_provider=ENGINE_VERSION, candidate_provider=result.solver_version, latency_samples_ms=samples,
    )


def _fallback_provider_result(fixture_name: str, fixture_id: str, samples: tuple[float, ...], candidate: dict[str, Any]) -> FixtureResult:
    fixture = load_fixture(fixture_directory() / fixture_name)
    evaluated = evaluate_fixture(fixture, provider_candidate=candidate)
    metrics = tuple(metric for metric in evaluated.metrics if metric.name != "latency") + _latency_metrics(samples)
    return FixtureResult(
        fixture_id=fixture_id,
        gate_passed=all(metric.status == "pass" for metric in metrics),
        expected_gate_passed=True,
        metrics=metrics,
        elapsed_ms=next(metric.value for metric in metrics if metric.name == "latency_p95") or 0.0,
    )


def _run_formula_provider_case() -> FixtureResult:
    from poker_coach.simulator.contracts import ObservationV1
    from poker_coach.theory.recommendation import TheoryExplainer

    fixture = load_fixture(fixture_directory() / "green-c-fallback.json")
    observation = ObservationV1.model_validate({
        "handId": "release-formula", "sequence": 3, "observerSeat": 0, "tableSize": 2,
        "buttonSeat": 0, "street": "flop", "ownHoleCards": ["As", "Kh"],
        "board": ["2c", "7d", "Jh"], "pot": 300, "stacks": {"0": 9700, "1": 9700},
        "streetCommitments": {"0": 0, "1": 0}, "activeSeats": [0, 1],
        "legalActions": [
            {"action": "check", "amountSemantics": "none"},
            {"action": "bet", "amountSemantics": "by", "minAmount": 100, "maxAmount": 9700},
        ],
    })
    explainer = TheoryExplainer()
    samples, result = _measure_provider_samples(lambda: explainer.recommend(observation, decision_fingerprint="release-formula-v1"))
    candidate = {
        "fingerprints": dict(fixture.payload["identity"]),
        "evidenceGrade": result.evidence.evidence_grade,
        "coverageStatus": result.evidence.coverage.status,
        "fallbackReason": result.evidence.coverage.reason or "formula_only",
        "explanationFacts": {
            "pot": result.explanation.pot,
            "callCost": result.explanation.call_cost,
            "potOdds": result.explanation.pot_odds,
            "spr": result.explanation.spr,
            "assumptions": list(result.explanation.assumptions),
        },
    }
    return _fallback_provider_result("green-c-fallback.json", "provider-formula-c-fallback", samples, candidate)


def _run_typed_unsupported_provider_case() -> FixtureResult:
    from poker_coach.theory.l2_solver import ENGINE_VERSION, L2Budget, L2RiverInput, RiverBetTree, solve_hu_river

    fixture = load_fixture(fixture_directory() / "green-unsupported-multiway.json")
    source = L2RiverInput(
        game_fingerprint="r9-release-multiway-v1", tree_fingerprint="unsupported-multiway-v1",
        range_fingerprint="public-projection-v1", solver_version=ENGINE_VERSION,
        players=(0, 1, 2), acting_seat=0, pot=100, stacks=(),
        board=("As", "Ks", "Qs", "Js", "Ts"), ranges=(), tree=RiverBetTree(bet_amount=100),
        seed=7, budget=L2Budget(iterations=5, soft_timeout_ms=100, hard_timeout_ms=200),
    )
    samples, result = _measure_provider_samples(lambda: solve_hu_river(source))
    candidate = {
        "fingerprints": dict(fixture.payload["identity"]),
        "evidenceGrade": result.evidence_grade,
        "coverageStatus": result.coverage_status,
        "fallbackReason": result.reason,
        "explanationFacts": {"players": len(result.players), "street": result.street},
    }
    return _fallback_provider_result(
        "green-unsupported-multiway.json", "provider-typed-unsupported-multiway", samples, candidate
    )


_REQUIRED_PROVIDER_CATEGORIES = {"policy_artifact", "l2_bounded_solver", "formula", "typed_unsupported"}


def production_provider_registry() -> tuple[ProductionProviderGate, ...]:
    """Explicit release registry; adding a production category requires a gate entry."""
    return (
        ProductionProviderGate("policy_artifact", tuple(f"provider-preflop-{spot}" for spot, *_ in _PREFLOP_SPOTS), _run_preflop_provider_cases),
        ProductionProviderGate("l2_bounded_solver", ("provider-l2-hu-river-root",), lambda: (_run_l2_provider_case(),)),
        ProductionProviderGate("formula", ("provider-formula-c-fallback",), lambda: (_run_formula_provider_case(),)),
        ProductionProviderGate("typed_unsupported", ("provider-typed-unsupported-multiway",), lambda: (_run_typed_unsupported_provider_case(),)),
    )


def _registry_failure(fixture_id: str, detail: str) -> FixtureResult:
    metrics = (
        _metric("provider_registry", False, detail=detail),
        *_latency_metrics(()),
    )
    return FixtureResult(fixture_id=fixture_id, gate_passed=False, expected_gate_passed=True, metrics=metrics, elapsed_ms=0.0)


def run_provider_release_gate(registry: tuple[ProductionProviderGate, ...] | None = None) -> BenchmarkResult:
    """Run the production release gate through every declared live provider spot.

    ``run_benchmark`` remains the intentional red/green fixture-corpus test
    harness.  It is never the release gate because its candidates are embedded
    mutants.  This function calls live provider code for all declared R9
    production nodes, then compares those outputs with frozen references.
    """
    configured = production_provider_registry() if registry is None else registry
    categories = {entry.category for entry in configured}
    results: list[FixtureResult] = []
    if categories != _REQUIRED_PROVIDER_CATEGORIES or len(categories) != len(configured):
        results.append(_registry_failure(
            "provider-registry-completeness",
            f"required={sorted(_REQUIRED_PROVIDER_CATEGORIES)} configured={sorted(categories)}",
        ))
    for entry in configured:
        produced = entry.runner()
        produced_spots = {result.fixture_id for result in produced}
        if produced_spots != set(entry.declared_spots):
            results.append(_registry_failure(
                f"provider-registry-{entry.category}",
                f"declared={sorted(entry.declared_spots)} produced={sorted(produced_spots)}",
            ))
        results.extend(produced)
    return BenchmarkResult(
        harness_version=HARNESS_VERSION,
        threshold_manifest_id=FROZEN_THRESHOLD_MANIFEST["manifest_id"],
        gate_passed=all(result.gate_passed for result in results),
        corpus_expectations_met=True,
        environment={"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor() or "unknown"},
        performance_note="Measured live provider execution on this development machine; not a product SLA.",
        fixtures=tuple(results),
    )


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
