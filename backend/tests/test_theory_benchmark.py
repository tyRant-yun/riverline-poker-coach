"""Red/green contract tests for the offline R9 theory benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from poker_coach.theory.benchmark import _canonical_digest, _latency_metrics, _measure_provider_samples, FixtureError, evaluate_fixture, fixture_directory, load_corpus, load_fixture, production_provider_registry, run_benchmark, run_provider_release_gate, run_provider_smoke


def _result_by_id():
    return {result.fixture_id: result for result in (evaluate_fixture(item) for item in load_corpus())}


def test_intentional_red_fixtures_reliably_fail_the_specific_safety_or_quality_gate():
    results = _result_by_id()
    expected_failures = {
        "red-action": "action_set_correctness",
        "red-frequency": "frequency_l1",
        "red-sizing": "sizing_legality",
        "red-range": "weighted_js_range_divergence",
        "red-fingerprint": "fingerprint",
        "red-private": "private_card_boundary",
        "red-illegal": "same_oracle_ev_loss",
    }
    for fixture_id, metric_name in expected_failures.items():
        result = results[fixture_id]
        assert result.gate_passed is False
        assert next(metric for metric in result.metrics if metric.name == metric_name).status == "fail"


def test_frozen_green_fixtures_cover_preflop_hu_and_explicit_downgrades():
    results = _result_by_id()
    for fixture_id in (
        "green-6max-preflop-b",
        "green-hu-river-a",
        "green-hu-turn-b",
        "green-c-fallback",
        "green-unsupported-multiway",
        "green-unsupported-tree",
        "green-unsupported-stack",
    ):
        assert results[fixture_id].gate_passed is True


def test_c_and_unsupported_only_verify_honest_grade_and_fallback_without_policy_scoring():
    results = _result_by_id()
    for fixture_id in ("green-c-fallback", "green-unsupported-multiway"):
        result = results[fixture_id]
        assert result.gate_passed is True
        assert next(metric for metric in result.metrics if metric.name == "same_oracle_ev_loss").detail.startswith("not applicable")


def test_fixture_digest_and_frozen_threshold_manifest_reject_tampering(tmp_path):
    original = fixture_directory() / "green-6max-preflop-b.json"
    payload = json.loads(original.read_text(encoding="utf-8"))
    payload["thresholdManifestId"] = "provider-chosen-looser-v9"
    payload["provenance"]["digest"] = _canonical_digest(payload)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureError, match="threshold manifest"):
        load_fixture(tampered)


def test_benchmark_report_separates_gate_failure_from_expected_mutant_detection():
    report = run_benchmark()
    assert report.gate_passed is False
    assert report.corpus_expectations_met is True
    assert report.performance_note.endswith("not a product SLA.")


def test_cli_verify_corpus_emits_machine_readable_report_and_success():
    completed = subprocess.run(
        [sys.executable, "-m", "poker_coach.theory", "--verify-corpus"],
        cwd=fixture_directory().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["corpus_expectations_met"] is True
    assert report["gate_passed"] is False


def test_cli_default_exit_code_reports_provider_backed_release_gate_success():
    completed = subprocess.run(
        [sys.executable, "-m", "poker_coach.theory"],
        cwd=fixture_directory().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["gate_passed"] is True


@pytest.mark.parametrize("fixture_name", ["green-hu-river-a.json", "green-hu-turn-b.json"])
def test_a_and_b_fixtures_have_distinct_declared_oracle_grades(fixture_name):
    fixture = load_fixture(fixture_directory() / fixture_name)
    assert fixture.payload["oracle"]["evidenceGrade"] in {"A", "B"}


def test_provider_smoke_calls_real_policy_artifact_not_fixture_candidate(monkeypatch):
    fixture = load_fixture(fixture_directory() / "green-6max-preflop-b.json")
    fixture.payload["candidate"]["actionFrequencies"] = {"fold": 1.0}
    monkeypatch.setattr("poker_coach.theory.benchmark.load_fixture", lambda _path: fixture)
    result = run_provider_smoke()
    assert result.gate_passed is True
    assert result.fixture_id == "provider-green-6max-preflop-b"


def test_release_gate_runs_every_declared_production_provider_spot_without_fixture_candidates(monkeypatch):
    """The release gate must use live providers, not the fixture mutant corpus."""
    fixture = load_fixture(fixture_directory() / "green-6max-preflop-b.json")
    fixture.payload["candidate"]["actionFrequencies"] = {"fold": 1.0}
    monkeypatch.setattr("poker_coach.theory.benchmark.load_corpus", lambda _path=None: (fixture,))

    report = run_provider_release_gate()

    assert report.gate_passed is True
    assert report.corpus_expectations_met is True
    assert {result.fixture_id for result in report.fixtures} == {
        "provider-preflop-rfi-utg",
        "provider-preflop-rfi-hj",
        "provider-preflop-rfi-co",
        "provider-preflop-rfi-btn",
        "provider-preflop-rfi-sb",
        "provider-preflop-vs-rfi-hj",
        "provider-preflop-vs-rfi-co",
        "provider-preflop-vs-rfi-btn",
        "provider-preflop-vs-rfi-sb",
        "provider-preflop-vs-rfi-bb",
        "provider-l2-hu-river-root",
        "provider-formula-c-fallback",
        "provider-typed-unsupported-multiway",
    }
    assert all(result.gate_passed for result in report.fixtures)
    assert {entry.category for entry in production_provider_registry()} == {
        "policy_artifact", "l2_bounded_solver", "formula", "typed_unsupported"
    }
    for result in report.fixtures:
        assert next(metric for metric in result.metrics if metric.name == "latency_p50").value is not None
        assert next(metric for metric in result.metrics if metric.name == "latency_p95").value is not None


def test_cli_default_runs_provider_backed_release_gate_not_fixture_corpus():
    completed = subprocess.run(
        [sys.executable, "-m", "poker_coach.theory"],
        cwd=fixture_directory().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["gate_passed"] is True
    assert {item["fixture_id"] for item in report["fixtures"]} >= {"provider-preflop-rfi-utg", "provider-l2-hu-river-root"}


def test_unsupported_with_policy_fields_is_red_not_honest_fallback(tmp_path):
    payload = json.loads((fixture_directory() / "green-unsupported-stack.json").read_text(encoding="utf-8"))
    payload["candidate"]["actionFrequencies"] = {"fold": 1.0}
    payload["candidate"]["selectedAction"] = "fold"
    payload["provenance"]["digest"] = _canonical_digest(payload)
    path = tmp_path / "unsupported-with-policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert evaluate_fixture(load_fixture(path)).gate_passed is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selectedAction", "fold"), ("sizings", {"bet": 100}), ("range", {"AA": 1.0}),
        ("actionFrequencies", {"fold": 1.0}), ("actionEvs", {"fold": 0.0}),
        ("evDefinition", "chips"), ("sameOracleEvLoss", {"chips": None}),
    ],
)
def test_c_and_unsupported_reject_every_strategy_or_value_field(tmp_path, field, value):
    payload = json.loads((fixture_directory() / "green-c-fallback.json").read_text(encoding="utf-8"))
    payload["candidate"][field] = value
    payload["provenance"]["digest"] = _canonical_digest(payload)
    path = tmp_path / f"c-with-{field}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert evaluate_fixture(load_fixture(path)).gate_passed is False


def test_approximately_300ms_provider_fails_p95_latency_gate():
    def slow_provider():
        time.sleep(0.30)
        return {"provider": "slow"}

    samples, _ = _measure_provider_samples(slow_provider, sample_count=3)
    metrics = _latency_metrics(samples)

    assert min(samples) >= 250
    assert next(metric for metric in metrics if metric.name == "latency_p95").status == "fail"


def test_missing_production_provider_category_fails_release_gate():
    registry = tuple(entry for entry in production_provider_registry() if entry.category != "formula")
    report = run_provider_release_gate(registry)
    assert report.gate_passed is False
    failure = next(item for item in report.fixtures if item.fixture_id == "provider-registry-completeness")
    assert "formula" in next(metric.detail for metric in failure.metrics if metric.name == "provider_registry")
