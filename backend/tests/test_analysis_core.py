from decimal import Decimal
from threading import Event

import pytest

from poker_coach.analysis import (
    EquityEngine,
    analyze_board,
    analyze_hand,
    analyze_range,
    analyze_scenario,
    blocker_effect,
    calculate_metrics,
    expand_range,
    parse_range_notation,
    range_spec_from_notation,
)
from poker_coach.analysis.models import AnalysisCancelled, AnalysisTimeout, InvalidAnalysisInput
from poker_coach.domain.models import (
    AnalysisLevel,
    EquityAlgorithm,
    RangeSpec,
    ScenarioSpec,
)
from poker_coach.rules import PokerKitAdapter


def range_spec(**kwargs):
    payload = {
        "rangeId": "test-range",
        "name": "Test range",
        "version": "1",
        "source": "user_defined",
        "matrix169": kwargs,
    }
    return RangeSpec.model_validate(payload)


def scenario_at_flop():
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "villainHoleCards": ["Qh", "Jc"],
            "board": ["2c", "7d", "Jh"],
            "actionHistory": [
                {
                    "actionId": "call",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "flop",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 0,
                    "actionType": "deal_flop",
                },
            ],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
            "assumptions": {},
        }
    )


def test_math_uses_integer_chips_and_returns_traceable_ratios():
    scenario = scenario_at_flop()
    snapshot = PokerKitAdapter().replay(scenario).final_state

    metrics = calculate_metrics(snapshot, hero_seat=0, villain_seat=1)

    assert metrics.current_pot == 200
    assert metrics.call_cost == 0
    assert metrics.pot_after_call == 200
    assert metrics.effective_stack == 9_900
    assert metrics.pot_odds == Decimal("0")
    assert metrics.spr == Decimal("49.5")
    assert all(isinstance(value, int) for value in (metrics.current_pot, metrics.call_cost))


def test_hand_categories_and_draws_are_specific():
    set_hand = analyze_hand(("8s", "8d"), ("8c", "2h", "Kc"))
    assert set_hand.category.value == "three_of_a_kind"
    assert set_hand.made_hand == "set"

    overpair = analyze_hand(("Qs", "Qd"), ("Jc", "7h", "2s"))
    assert overpair.made_hand == "overpair"

    combo = analyze_hand(("As", "Ks"), ("Qs", "Js", "2d"))
    assert "flush_draw" in [draw.value for draw in combo.draws]
    assert "gutshot" in [draw.value for draw in combo.draws]
    assert "combo_draw" in [draw.value for draw in combo.draws]
    assert combo.out_count == 12

    backdoor = analyze_hand(("As", "Kd"), ("2s", "7s", "Jh"))
    assert "backdoor_flush_draw" in [draw.value for draw in backdoor.draws]
    assert backdoor.out_count == 0


@pytest.mark.parametrize(
    ("hole_cards", "board", "expected_category"),
    [
        (("As", "Kd"), ("2c", "7d", "Jh"), "high_card"),
        (("As", "Qd"), ("Ah", "7c", "2s"), "one_pair"),
        (("As", "7d"), ("Ah", "7c", "2s"), "two_pair"),
        (("8s", "8d"), ("8c", "2h", "Kc"), "three_of_a_kind"),
        (("8s", "9d"), ("6c", "7h", "Ts"), "straight"),
        (("As", "Ks"), ("2s", "7s", "4s"), "flush"),
        (("As", "Ad"), ("Ah", "7c", "7d"), "full_house"),
        (("As", "Ad"), ("Ah", "Ac", "7c"), "four_of_a_kind"),
        (("As", "Ks"), ("Qs", "Js", "Ts"), "straight_flush"),
    ],
)
def test_best_hand_categories_cover_all_holdem_categories(
    hole_cards, board, expected_category
):
    assert analyze_hand(hole_cards, board).category.value == expected_category


def test_double_gutter_and_counterfeit_risk_are_not_labeled_as_made_hands():
    double_gutter = analyze_hand(("2c", "4d"), ("5h", "6s", "8c"))
    assert "double_gutter" in [draw.value for draw in double_gutter.draws]
    assert double_gutter.category.value == "high_card"
    assert double_gutter.out_count == 8

    counterfeit = analyze_hand(("As", "7d"), ("Ah", "7c", "2s"))
    assert counterfeit.made_hand == "two_pair"
    assert counterfeit.counterfeit_risk_cards


def test_board_texture_labels_and_next_street_candidates():
    rainbow = analyze_board(("As", "Kd", "7c"))
    assert rainbow.rainbow
    assert not rainbow.paired
    assert "high_card_structure" in rainbow.labels

    dynamic = analyze_board(("7s", "8s", "9d"))
    assert dynamic.two_tone
    assert dynamic.connectedness == "highly_connected"
    assert dynamic.static_or_dynamic == "dynamic"
    assert dynamic.next_street_change_cards
    assert dynamic.nut_combo_count > 0
    assert dynamic.possible_nut_hands


def test_range_expansion_and_blocker_removal_are_deterministic():
    ranges = range_spec(AKs="1", QQ="0.5")
    combos = expand_range(ranges)
    assert len(combos) == 10
    assert sum((combo.weight for combo in combos), Decimal("0")) == Decimal("7")

    blocked = blocker_effect(ranges, ("As",))
    assert blocked.total_combos == 9
    assert blocked.blocked_combos == 1
    assert blocked.blocked_weight == Decimal("1")

    analyzed = analyze_range(ranges, ("2c", "7d", "Jh"), known_cards=("As", "Kd"))
    assert analyzed.total_combos == 8
    assert analyzed.blocked_combos == 2
    assert analyzed.heuristic


def test_common_range_notation_normalizes_to_169_grid_cells():
    parsed = parse_range_notation("22+, A5s+, K9o+, QJs, AK@0.5")
    assert parsed["22"] == Decimal("1")
    assert parsed["AA"] == Decimal("1")
    assert parsed["A5s"] == Decimal("1")
    assert parsed["AKs"] == Decimal("0.5")
    assert parsed["K9o"] == Decimal("1")
    assert parsed["KQo"] == Decimal("1")
    assert parsed["AKs"] == Decimal("0.5")
    assert parsed["AKo"] == Decimal("0.5")
    imported = range_spec_from_notation("TT-QQ")
    assert set(imported.matrix_169) == {"TT", "JJ", "QQ"}
    dead_filtered = range_spec_from_notation("AKs", dead_cards=("As", "Kd"))
    assert dead_filtered.dead_cards == ("Kd", "As")


def test_exact_equity_handles_known_cards_and_split_pots():
    engine = EquityEngine()
    hero_wins = engine.evaluate_hand_vs_hand(
        ("As", "Kd"),
        ("Qh", "Jc"),
        ("2c", "3d", "4h", "5s", "9c"),
    )
    assert hero_wins.hero_equity == Decimal("1")
    assert hero_wins.villain_equity == Decimal("0")
    assert hero_wins.ties == 0
    assert hero_wins.source_level is AnalysisLevel.ENUMERATED

    split = engine.evaluate_hand_vs_hand(
        ("As", "Kd"),
        ("Ac", "Kh"),
        ("Qs", "Jc", "Ts", "2d", "3h"),
    )
    assert split.hero_equity == Decimal("0.5")
    assert split.villain_equity == Decimal("0.5")
    assert split.ties == 1


def test_hand_vs_range_and_range_vs_range_filter_dead_cards():
    engine = EquityEngine()
    villain = range_spec(QQ="1", AKs="1")
    result = engine.evaluate_hand_vs_range(
        ("As", "Kd"), villain, ("2c", "7d", "Jh", "4s")
    )
    assert result.trials > 0
    assert result.weighted

    hero_range = range_spec(AA="1")
    villain_range = range_spec(KK="1")
    result = engine.evaluate_range_vs_range(
        hero_range, villain_range, ("2c", "7d", "Jh", "4s", "9c")
    )
    assert result.hero_equity == Decimal("1")
    assert result.villain_equity == Decimal("0")


def test_monte_carlo_is_seeded_and_has_uncertainty():
    engine = EquityEngine()
    first = engine.evaluate_hand_vs_hand(
        ("As", "Kd"),
        ("Qh", "Jc"),
        ("2c", "7d", "Jh"),
        algorithm=EquityAlgorithm.MONTE_CARLO,
        trials=200,
        random_seed=42,
    )
    second = engine.evaluate_hand_vs_hand(
        ("As", "Kd"),
        ("Qh", "Jc"),
        ("2c", "7d", "Jh"),
        algorithm=EquityAlgorithm.MONTE_CARLO,
        trials=200,
        random_seed=42,
    )
    assert first.to_json() == second.to_json()
    assert first.source_level is AnalysisLevel.SIMULATED
    assert first.confidence_interval is not None
    assert first.standard_error is not None


def test_equity_rejects_empty_work_and_supports_cancel_and_timeout():
    engine = EquityEngine(max_exact_operations=1)
    with pytest.raises(InvalidAnalysisInput, match="use Monte Carlo"):
        engine.evaluate_hand_vs_hand(("As", "Kd"), ("Qh", "Jc"), ("2c", "7d", "Jh"))

    cancelled = Event()
    cancelled.set()
    with pytest.raises(AnalysisCancelled):
        EquityEngine().evaluate_hand_vs_hand(
            ("As", "Kd"),
            ("Qh", "Jc"),
            ("2c", "7d", "Jh"),
            algorithm=EquityAlgorithm.MONTE_CARLO,
            trials=100,
            random_seed=1,
            cancel_event=cancelled,
        )

    with pytest.raises(AnalysisTimeout):
        EquityEngine().evaluate_hand_vs_hand(
            ("As", "Kd"),
            ("Qh", "Jc"),
            ("2c", "7d", "Jh"),
            algorithm=EquityAlgorithm.MONTE_CARLO,
            trials=100,
            random_seed=1,
            timeout_seconds=0,
        )


def test_analysis_scenario_builds_evidence_without_agent_or_api():
    result = analyze_scenario(scenario_at_flop())

    assert result.equity is not None
    assert result.equity.source_level is AnalysisLevel.ENUMERATED
    assert result.metrics.current_pot == 200
    assert result.board.board == ("2c", "7d", "Jh")
    assert "math.pot_odds" in result.evidence.ids()
    assert "equity.hero" in result.evidence.ids()
    assert result.scenario_hash
    assert result.warnings == ()
    assert "assumptions.equity_algorithm" in result.evidence.ids()
    assert {
        "hand.out_cards",
        "hand.counterfeit_risk",
        "board.next_street_change_cards",
    } <= result.evidence.ids()
    assert result.evidence.to_json() == result.evidence.to_json()


def test_analysis_scenario_binds_both_ranges_and_blocker_evidence():
    scenario = scenario_at_flop().model_copy(
        update={
            "villain_hole_cards": None,
            "hero_range": range_spec(AA="1"),
            "villain_range": range_spec(QQ="1"),
        }
    )

    result = analyze_scenario(scenario)

    assert result.equity is not None
    assert result.range_analysis is not None
    assert result.range_comparison is not None
    assert {
        "assumptions.hero_range_id",
        "assumptions.villain_range_id",
        "assumptions.hero_range_provenance",
        "assumptions.villain_range_provenance",
        "range.blocked_weight",
        "range.blocker_cards",
        "range.equity_distribution",
    } <= result.evidence.ids()
