"""Focused acceptance tests for the isolated R9-04 HU river CFR engine."""

from __future__ import annotations

from threading import Event
from typing import cast

import pytest

from poker_coach.theory.benchmark import _canonical_digest, evaluate_fixture, load_fixture
from poker_coach.theory.l2_solver import (
    L2Budget,
    L2Cache,
    L2RiverInput,
    L2SolverJobs,
    L2Unsupported,
    RangeCombo,
    RiverBetTree,
    solve_hu_river,
    to_benchmark_candidate,
)


def _tied_input(**changes: object) -> L2RiverInput:
    """A finite exact-small-game: the board plays, so every showdown is a tie."""
    payload = dict(
        game_fingerprint="nlhe-hu-100bb-norake-v1",
        tree_fingerprint="river-check-bet-100-v1",
        range_fingerprint="exact-small-game-range-v1",
        solver_version="riverline-l2-cfr/v1",
        players=(0, 1),
        acting_seat=0,
        pot=100,
        stacks=((0, 100), (1, 100)),
        board=("As", "Ks", "Qs", "Js", "Ts"),
        ranges=(
            (0, (RangeCombo(("2c", "3d"), 1), RangeCombo(("4c", "5d"), 1))),
            (1, (RangeCombo(("6c", "7d"), 1), RangeCombo(("8c", "9d"), 1))),
        ),
        tree=RiverBetTree(bet_amount=100),
        seed=7,
        budget=L2Budget(iterations=200, soft_timeout_ms=2_000, hard_timeout_ms=3_000),
    )
    payload.update(changes)
    return L2RiverInput(**payload)


def test_hu_river_cfr_returns_immutable_b_grade_mixed_policy_and_no_private_combos():
    result = solve_hu_river(_tied_input())

    assert result.evidence_grade == "B"
    assert result.coverage_status == "covered"
    # The finite tree's fold branch makes betting dominant after regret updates,
    # but the averaged CFR policy retains a deterministic non-degenerate mix.
    assert result.action_frequencies == {"check": pytest.approx(0.00125), "bet": pytest.approx(0.99875)}
    assert result.ev_definition == "zero_sum_chips_from_root_player"
    assert result.iterations_completed == 200
    assert result.regret_bound_chips >= 0
    assert result.cache_key == _tied_input().fingerprint
    assert "2c" not in repr(result).lower()
    assert "6c" not in repr(result).lower()


def test_exact_small_game_cross_check_and_r9_00_adapter_green_gate(tmp_path):
    result = solve_hu_river(_tied_input())
    candidate = to_benchmark_candidate(result, selected_action="check", public_range={"tied": 1.0})
    fixture = {
        "schemaVersion": 1,
        "fixtureId": "l2-exact-tied-river",
        "expectedGatePassed": True,
        "thresholdManifestId": "r9-00.calibration.v1",
        "identity": {
            "spotId": "l2-exact-tied-river",
            "gameFingerprint": result.game_fingerprint,
            "treeFingerprint": result.tree_fingerprint,
            "rangeFingerprint": result.range_fingerprint,
            "policyFingerprint": result.solver_version,
        },
        "provenance": {"source": "Riverline-owned exact enumeration", "license": "LicenseRef-Riverline-Internal-Test-Fixture", "version": "l2-test.v1", "method": "independent tied-showdown enumeration", "digest": ""},
        "oracle": {"evidenceGrade": "B", "coverageStatus": "covered", "legalActions": ["check", "bet"], "actionFrequencies": {"check": 0.00125, "bet": 0.99875}, "legalSizings": {"bet": {"min": 100, "max": 100, "target": 100}}, "evDefinition": "zero_sum_chips_from_root_player", "actionEvs": {"check": 0.0, "bet": 0.0}, "range": {"tied": 1.0}},
        "candidate": candidate,
    }
    fixture["provenance"]["digest"] = _canonical_digest(fixture)
    path = tmp_path / "l2.json"
    path.write_text(__import__("json").dumps(fixture), encoding="utf-8")
    assert evaluate_fixture(load_fixture(path)).gate_passed is True

    candidate["fingerprints"]["treeFingerprint"] = "mutant"
    fixture["candidate"] = candidate
    fixture["provenance"]["digest"] = _canonical_digest(fixture)
    path.write_text(__import__("json").dumps(fixture), encoding="utf-8")
    assert evaluate_fixture(load_fixture(path)).gate_passed is False


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"players": (0, 1, 2)}, "multiway_unsupported"),
        ({"street": "turn"}, "street_unsupported"),
        ({"tree": RiverBetTree(bet_amount=101)}, "tree_or_stack_unsupported"),
        ({"ranges": ()}, "range_unsupported"),
        ({"tree": cast(RiverBetTree, object())}, "tree_or_stack_unsupported"),
    ],
)
def test_unsupported_scope_is_typed_and_never_returns_policy(changes, reason):
    result = solve_hu_river(_tied_input(**changes))
    assert isinstance(result, L2Unsupported)
    assert result.reason == reason


def test_dead_cards_and_cross_range_card_collisions_are_rejected_before_solving():
    with pytest.raises(ValueError, match="collides with board"):
        solve_hu_river(_tied_input(ranges=((0, (RangeCombo(("As", "3d"), 1),)), (1, (RangeCombo(("6c", "7d"), 1),)))))
    with pytest.raises(ValueError, match="no card-unique compatible worlds"):
        solve_hu_river(_tied_input(ranges=((0, (RangeCombo(("2c", "3d"), 1),)), (1, (RangeCombo(("2c", "7d"), 1),)))))


def test_cache_is_fingerprint_scoped_bounded_and_hit_is_marked():
    cache = L2Cache(max_entries=1)
    first = solve_hu_river(_tied_input(), cache=cache)
    second = solve_hu_river(_tied_input(), cache=cache)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.elapsed_ms < 500  # measured cache-hit target, not a product SLA
    third = solve_hu_river(_tied_input(range_fingerprint="different-range"), cache=cache)
    assert third.cache_hit is False
    assert len(cache) == 1


def test_cache_miss_can_be_submitted_off_the_foreground_path():
    jobs = L2SolverJobs()
    try:
        result = jobs.submit(_tied_input()).result(timeout=3)
    finally:
        jobs.shutdown()
    assert result.coverage_status == "covered"


def test_budget_and_cancellation_degrade_without_blocking():
    cancelled = Event()
    cancelled.set()
    result = solve_hu_river(_tied_input(), cancel=cancelled)
    assert result.coverage_status == "fallback"
    assert result.degradation_reason == "cancelled"
    result = solve_hu_river(_tied_input(budget=L2Budget(iterations=10_000, soft_timeout_ms=0, hard_timeout_ms=1)))
    assert result.coverage_status == "fallback"
    assert result.degradation_reason in {"soft_timeout", "hard_timeout"}
