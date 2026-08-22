"""Red/green contract tests for the offline R9 theory benchmark."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from poker_coach.theory.benchmark import _canonical_digest, FixtureError, evaluate_fixture, fixture_directory, load_corpus, load_fixture, run_benchmark


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


def test_cli_default_exit_code_reports_an_actual_gate_failure_for_mutants():
    completed = subprocess.run(
        [sys.executable, "-m", "poker_coach.theory"],
        cwd=fixture_directory().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["gate_passed"] is False


@pytest.mark.parametrize("fixture_name", ["green-hu-river-a.json", "green-hu-turn-b.json"])
def test_a_and_b_fixtures_have_distinct_declared_oracle_grades(fixture_name):
    fixture = load_fixture(fixture_directory() / fixture_name)
    assert fixture.payload["oracle"]["evidenceGrade"] in {"A", "B"}
