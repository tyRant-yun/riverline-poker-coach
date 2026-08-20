"""Frozen R8-04 sizing, uncertainty, and robust-recommendation spots."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from poker_coach.simulator import FastSolver, LegalActionV1, ObservationV1


def _belief(seat: int, combos: dict[str, str]):
    return SimpleNamespace(
        seat_id=seat,
        available=True,
        current=SimpleNamespace(
            combos={
                combo: SimpleNamespace(probability=Decimal(weight))
                for combo, weight in combos.items()
            },
            snapshot_id=f"seat-{seat}",
        ),
        provenance=SimpleNamespace(
            artifact_fingerprint="r8-sizing-fixture",
            version="heuristic_likelihood_v2",
        ),
    )


def _spot(
    *,
    board: tuple[str, ...] = ("7c", "6d", "2h"),
    hole: tuple[str, str] = ("As", "Kd"),
    pot: int = 300,
    hero_stack: int = 900,
    hero_commitment: int = 0,
    active_seats: tuple[int, ...] = (0, 1),
    button_seat: int = 0,
    legal_actions: tuple[LegalActionV1, ...] | None = None,
) -> ObservationV1:
    return ObservationV1(
        handId="r8-sizing-spot",
        sequence=11,
        observerSeat=0,
        tableSize=max(active_seats) + 1,
        buttonSeat=button_seat,
        street="river" if len(board) == 5 else "flop",
        ownHoleCards=hole,
        board=board,
        pot=pot,
        stacks={seat: hero_stack if seat == 0 else 900 for seat in active_seats},
        streetCommitments={seat: hero_commitment if seat == 0 else 0 for seat in active_seats},
        activeSeats=active_seats,
        legalActions=legal_actions or (
            LegalActionV1(action="check", amountSemantics="none"),
            LegalActionV1(
                action="bet", amountSemantics="by", minAmount=50, maxAmount=hero_stack
            ),
        ),
    )


def _solve(observation: ObservationV1, combos: dict[str, str], *, iterations=256):
    beliefs = {
        seat: _belief(seat, combos)
        for seat in observation.active_seats
        if seat != observation.observer_seat
    }
    return FastSolver(iteration_cap=iterations, clock=lambda: 0).solve(
        observation,
        decision_fingerprint="r8-sizing-fingerprint",
        range_beliefs=beliefs,
    )


def test_standard_pot_sizings_min_max_and_jam_are_integer_legal_and_deduplicated():
    observation = _spot()
    result = _solve(observation, {"QcQd": "0.5", "JhJd": "0.5"}, iterations=32)
    bets = [candidate for candidate in result.candidates if candidate.action.value == "bet"]

    assert [candidate.amount for candidate in bets] == [50, 99, 150, 198, 225, 300, 900]
    assert [candidate.pot_percentage for candidate in bets] == [
        Decimal("16.66666666666666666666666667"),
        Decimal("33"), Decimal("50"), Decimal("66"), Decimal("75"),
        Decimal("100"), Decimal("300"),
    ]
    assert [candidate.is_jam for candidate in bets] == [False] * 6 + [True]
    assert bets[-1].sizing_class == "jam"
    assert len({candidate.amount for candidate in bets}) == len(bets)
    legal = observation.legal_actions[1]
    assert all(isinstance(candidate.amount, int) for candidate in bets)
    assert all(legal.accepts(action=candidate.action, amount=candidate.amount) for candidate in bets)


def test_raise_to_standard_sizings_preserve_total_amount_and_incremental_cost():
    observation = _spot(
        hero_stack=850,
        hero_commitment=50,
        legal_actions=(
            LegalActionV1(
                action="raise", amountSemantics="to", minAmount=100, maxAmount=900
            ),
        ),
    )
    result = _solve(observation, {"QcQd": "1"}, iterations=32)

    assert [candidate.amount for candidate in result.candidates] == [
        100, 149, 200, 248, 275, 350, 900
    ]
    assert [candidate.incremental_cost for candidate in result.candidates] == [
        50, 99, 150, 198, 225, 300, 850
    ]
    assert result.candidates[-1].is_jam is True
    assert result.candidates[-1].pot_percentage == Decimal("283.3333333333333333333333333")


def test_fold_check_call_and_explicit_overbet_remain_in_the_legal_product_set():
    passive = _spot(legal_actions=(
        LegalActionV1(action="fold", amountSemantics="none"),
        LegalActionV1(action="check", amountSemantics="none"),
        LegalActionV1(action="call", amountSemantics="cost", minAmount=100, maxAmount=100),
    ))
    passive_result = _solve(passive, {"QcQd": "1"}, iterations=32)
    assert [
        (candidate.action.value, candidate.amount, candidate.incremental_cost)
        for candidate in passive_result.candidates
    ] == [("fold", None, 0), ("check", None, 0), ("call", 100, 100)]

    aggressive = _spot(legal_actions=(
        LegalActionV1(action="bet", amountSemantics="by", minAmount=450, maxAmount=900),
    ))
    aggressive_result = _solve(aggressive, {"QcQd": "1"}, iterations=32)
    assert [candidate.amount for candidate in aggressive_result.candidates] == [450, 900]
    assert [candidate.sizing_class for candidate in aggressive_result.candidates] == [
        "overbet", "jam"
    ]


def test_response_mix_is_bounded_normalized_and_sizing_multiway_directional():
    heads_up = _solve(_spot(), {"QcQd": "0.5", "JhJd": "0.5"}, iterations=32)
    multiway = _solve(
        _spot(active_seats=(0, 1, 2)),
        {"QcQd": "0.5", "JhJd": "0.5"},
        iterations=32,
    )
    hu_bets = [candidate for candidate in heads_up.candidates if candidate.action.value == "bet"]
    mw_bets = [candidate for candidate in multiway.candidates if candidate.action.value == "bet"]

    assert [candidate.response_mix.fold for candidate in hu_bets] == sorted(
        candidate.response_mix.fold for candidate in hu_bets
    )
    assert mw_bets[3].response_mix.fold < hu_bets[3].response_mix.fold
    for candidate in (*hu_bets, *mw_bets):
        mix = candidate.response_mix
        assert Decimal("0") <= mix.fold <= Decimal("1")
        assert Decimal("0") <= mix.call <= Decimal("1")
        assert Decimal("0") <= mix.raise_ <= Decimal("1")
        assert mix.fold + mix.call + mix.raise_ == Decimal("1")


def test_response_mix_changes_directionally_with_spr_position_and_range_concentration():
    fixed_bet = (
        LegalActionV1(action="bet", amountSemantics="by", minAmount=150, maxAmount=150),
    )
    shallow = _solve(
        _spot(hero_stack=150, legal_actions=fixed_bet),
        {"QcQd": "0.5", "JhJd": "0.5"},
        iterations=32,
    ).candidates[0]
    deep = _solve(
        _spot(hero_stack=900, legal_actions=fixed_bet),
        {"QcQd": "0.5", "JhJd": "0.5"},
        iterations=32,
    ).candidates[0]
    on_button = _solve(
        _spot(button_seat=0, legal_actions=fixed_bet),
        {"QcQd": "0.5", "JhJd": "0.5"},
        iterations=32,
    ).candidates[0]
    out_of_position = _solve(
        _spot(button_seat=1, legal_actions=fixed_bet),
        {"QcQd": "0.5", "JhJd": "0.5"},
        iterations=32,
    ).candidates[0]
    concentrated = _solve(
        _spot(legal_actions=fixed_bet),
        {"QcQd": "0.99", "JhJd": "0.01"},
        iterations=32,
    ).candidates[0]

    assert shallow.response_mix.fold < deep.response_mix.fold
    assert out_of_position.response_mix.fold < on_button.response_mix.fold
    assert concentrated.response_mix.fold < deep.response_mix.fold
    assert concentrated.response_mix.raise_ > deep.response_mix.raise_


def test_exact_weak_hand_does_not_gain_a_false_positive_jam_recommendation():
    result = _solve(
        _spot(
            board=("2c", "3d", "7h", "8s", "9c"),
            hole=("4s", "5d"),
        ),
        {"AsAd": "1"},
    )
    jam = next(candidate for candidate in result.candidates if candidate.is_jam)

    assert result.recommended_action is not None
    assert result.recommended_action.is_jam is False
    assert jam.delta_ev_chips < 0


def test_exact_nut_hand_can_robustly_recommend_jam_when_margin_is_real():
    result = _solve(
        _spot(
            board=("2c", "3d", "7h", "8s", "9c"),
            hole=("As", "Ad"),
        ),
        {"KcKd": "1"},
    )

    assert result.recommended_action is not None
    assert result.recommended_action.is_jam is True
    assert result.sizing_robustness == "robust"
    assert "deterministic_model_clear" in result.recommendation_reason_codes
    assert result.robustness_margin_confidence_interval_95 is not None
    assert result.robustness_margin_confidence_interval_95.lower > 0


def test_common_sample_delta_ci_and_close_tie_break_are_reproducible():
    observation = _spot()
    first = _solve(observation, {"QcQd": "0.5", "JhJd": "0.5"}, iterations=64)
    second = _solve(observation, {"QcQd": "0.5", "JhJd": "0.5"}, iterations=64)

    assert first.to_dict() == second.to_dict()
    best_ev = max(candidate.approximate_ev_chips for candidate in first.candidates)
    assert all(
        candidate.delta_ev_chips == candidate.approximate_ev_chips - best_ev
        for candidate in first.candidates
    )
    assert all(candidate.uncertainty_status == "available" for candidate in first.candidates)
    assert all(candidate.delta_ev_confidence_interval_95 is not None for candidate in first.candidates)
    if first.sizing_robustness == "close":
        assert first.recommended_action is not None
        assert first.recommended_action.recommendation_tier == "close"
        assert "close_conservative_tiebreak" in first.recommendation_reason_codes


def test_one_sample_marks_candidate_and_robustness_uncertainty_not_available():
    result = _solve(
        _spot(), {"QcQd": "0.5", "JhJd": "0.5"}, iterations=1
    )

    assert result.sizing_robustness == "not_available"
    assert result.robustness_margin_confidence_interval_95 is None
    assert all(candidate.uncertainty_status == "not_available" for candidate in result.candidates)
    assert all(candidate.confidence_interval_95 is None for candidate in result.candidates)
    assert all(candidate.delta_ev_confidence_interval_95 is None for candidate in result.candidates)
    assert result.recommended_action is not None
    assert result.recommended_action.is_jam is False
    assert result.recommended_action.recommendation_tier == "not_available"
