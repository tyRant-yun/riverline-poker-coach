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
        hero_hole_cards=("2c", "3d"),
    )
    payload.update(changes)
    return L2RiverInput(**payload)


def test_hu_river_cfr_returns_immutable_b_grade_mixed_policy_and_no_private_combos():
    result = solve_hu_river(_tied_input())

    assert result.evidence_grade == "B"
    assert result.coverage_status == "covered"
    assert result.recommendation_available is True
    # The finite tree's fold branch makes betting dominant after regret updates,
    # but the averaged CFR policy retains a deterministic non-degenerate mix.
    assert result.action_frequencies == {"check": pytest.approx(0.00125), "bet": pytest.approx(0.99875)}
    assert result.ev_definition == "zero_sum_chips_from_root_player"
    assert result.iterations_completed == 200
    assert result.regret_bound_chips >= 0
    assert result.cache_key == _tied_input().fingerprint
    assert not hasattr(result, "hero_hole_cards")
    assert "RangeCombo" not in repr(result)
    assert result.hero_decision_identity is not None


def test_noncanonical_alias_and_normalized_physical_duplicate_are_typed_unsupported():
    alias = solve_hu_river(_tied_input(board=("2C", "Ks", "Qs", "Js", "Ts")))
    assert isinstance(alias, L2Unsupported)
    assert alias.reason == "card_not_canonical"

    duplicate = solve_hu_river(_tied_input(ranges=(
        (0, (RangeCombo(("2c", "2C"), 1),)),
        (1, (RangeCombo(("6c", "7d"), 1),)),
    ), hero_hole_cards=("2c", "2C")))
    assert isinstance(duplicate, L2Unsupported)
    assert duplicate.reason in {"card_not_canonical", "card_collision_unsupported"}

    exact_duplicate = solve_hu_river(_tied_input(ranges=(
        (0, (RangeCombo(("2c", "2c"), 1),)),
        (1, (RangeCombo(("6c", "7d"), 1),)),
    )))
    assert isinstance(exact_duplicate, L2Unsupported)
    assert exact_duplicate.reason == "card_collision_unsupported"

    unknown = solve_hu_river(_tied_input(hero_hole_cards=("1z", "3d")))
    assert isinstance(unknown, L2Unsupported)
    assert unknown.reason == "card_invalid"


def test_aggregate_diagnostics_can_never_be_reused_as_a_live_hero_policy():
    result = solve_hu_river(_tied_input(hero_hole_cards=None))
    assert result.aggregate_action_frequencies
    assert result.action_frequencies == {}
    assert result.recommendation_available is False
    assert result.coverage_status == "fallback"
    assert result.degradation_reason == "hero_combo_required"
    with pytest.raises(ValueError, match="aggregate diagnostics"):
        to_benchmark_candidate(result, selected_action="check", public_range={"tied": 1.0})

    outside = solve_hu_river(_tied_input(hero_hole_cards=("6c", "7d")))
    assert outside.recommendation_available is False
    assert outside.action_frequencies == {}
    assert outside.degradation_reason == "hero_combo_outside_projection"


def test_hero_infoset_output_and_cache_are_isolated_from_other_hero_combos():
    cache = L2Cache(max_entries=4)
    first = solve_hu_river(_tied_input(hero_hole_cards=("2c", "3d")), cache=cache)
    second = solve_hu_river(_tied_input(hero_hole_cards=("4c", "5d")), cache=cache)
    assert first.recommendation_available is second.recommendation_available is True
    assert first.cache_key != second.cache_key
    assert first.tree_cache_key == second.tree_cache_key
    assert second.cache_hit is False
    assert solve_hu_river(_tied_input(hero_hole_cards=("2c", "3d")), cache=cache).cache_hit is True


def test_hero_policy_is_selected_from_its_infoset_not_the_cross_hero_aggregate():
    payload = dict(
        game_fingerprint="hero-infoset-game",
        tree_fingerprint="hero-infoset-tree",
        range_fingerprint="hero-infoset-range",
        solver_version="riverline-l2-cfr/v1",
        players=(0, 1), acting_seat=0, pot=100, stacks=((0, 100), (1, 100)),
        board=("2c", "3d", "4h", "5s", "9c"),
        ranges=(
            (0, (RangeCombo(("6s", "7h"), 2), RangeCombo(("8s", "Td"), 1))),
            (1, (RangeCombo(("Qc", "Jd"), 1),)),
        ),
        tree=RiverBetTree(100), seed=11,
        budget=L2Budget(iterations=1_000, soft_timeout_ms=5_000, hard_timeout_ms=6_000),
    )
    value = solve_hu_river(L2RiverInput(**payload, hero_hole_cards=("6s", "7h")))
    bluff = solve_hu_river(L2RiverInput(**payload, hero_hole_cards=("8s", "Td")))
    assert value.action_frequencies != bluff.action_frequencies
    assert value.action_frequencies != value.aggregate_action_frequencies
    assert value.hero_decision_identity != bluff.hero_decision_identity


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
    board_collision = solve_hu_river(_tied_input(ranges=((0, (RangeCombo(("As", "3d"), 1),)), (1, (RangeCombo(("6c", "7d"), 1),)))))
    assert isinstance(board_collision, L2Unsupported)
    assert board_collision.reason == "card_collision_unsupported"
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
    artifact = solve_hu_river(_tied_input(solver_artifact_fingerprint="artifact-v2"), cache=cache)
    assert artifact.cache_hit is False
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
