"""Combo-level range belief engine tests.

Covers: Bayesian single/multi-step updates, reach vs probability semantics,
zero-likelihood removal, dead-card/board filtering, snapshot traces,
polarized (policy-conditioned, not hand-strength) updates, solver strategy
adapter, off-tree nearest sizing, 169 aggregation mass conservation and
suit-specific combo handling.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from poker_coach.domain.models import (
    ActionEvent,
    ActionType,
    AmountType,
    RangeCombo,
    RangeSource,
    RangeSpec,
    ScenarioSpec,
    Street,
)
from poker_coach.ranges import (
    FixturePolicyProvider,
    InvalidPolicyError,
    NoPolicyError,
    PolicyResult,
    PolicySource,
    SolverPolicyAdapter,
    UnsupportedActionError,
    ZeroProbabilityActionError,
    aggregate_belief_to_matrix169,
    apply_dead_cards,
    build_belief_view,
    build_range_trace,
    match_observed_action,
    snapshot_from_range,
    update_range_belief,
)
from poker_coach.ranges.aggregation import cell_key
from poker_coach.solver.types import SolveMetadata, SolverHand, SolverNode, SolveResult

PRIOR_COMBOS = {
    "AsAh": Decimal("1"),
    "JsJh": Decimal("1"),
    "7s6s": Decimal("0.7"),
    "Js4d": Decimal("0.2"),
}
PRIOR_TOTAL = Decimal("2.9")


def prior_range(combos: dict[str, str | Decimal] | None = None) -> RangeSpec:
    entries = combos or PRIOR_COMBOS
    return RangeSpec(
        range_id="test-prior",
        name="Test prior",
        version="1",
        source=RangeSource.USER_DEFINED,
        combos=tuple(
            RangeCombo(cards=(key[:2], key[2:]), weight=Decimal(weight))
            for key, weight in entries.items()
        ),
    )


def make_event(
    sequence: int,
    seat: int,
    action_type: ActionType,
    *,
    street: Street = Street.FLOP,
    amount: int | None = None,
    amount_type: AmountType = AmountType.NONE,
) -> ActionEvent:
    return ActionEvent(
        action_id=f"a{sequence}",
        sequence=sequence,
        street=street,
        actor_seat=seat,
        action_type=action_type,
        amount=amount,
        amount_type=amount_type,
    )


def raise_event(sequence: int, seat: int, amount: int) -> ActionEvent:
    return make_event(
        sequence, seat, ActionType.RAISE_TO, amount=amount, amount_type=AmountType.TO
    )


def bet_event(sequence: int, seat: int, amount: int) -> ActionEvent:
    return make_event(
        sequence, seat, ActionType.BET, amount=amount, amount_type=AmountType.BY
    )


def check_event(sequence: int, seat: int) -> ActionEvent:
    return make_event(sequence, seat, ActionType.CHECK)


def call_event(sequence: int, seat: int, amount: int) -> ActionEvent:
    return make_event(
        sequence, seat, ActionType.CALL, amount=amount, amount_type=AmountType.COST
    )


def deal_event(sequence: int, street: Street) -> ActionEvent:
    action_type = {
        Street.FLOP: ActionType.DEAL_FLOP,
        Street.TURN: ActionType.DEAL_TURN,
        Street.RIVER: ActionType.DEAL_RIVER,
    }[street]
    return make_event(sequence, 0, action_type, street=street)


def make_scenario(
    *,
    events: tuple[ActionEvent, ...] = (),
    board: tuple[str, ...] = (),
    ranges: dict[int, RangeSpec] | None = None,
    after_sequence: int = 0,
    known_by_seat: dict[int, tuple[str, ...]] | None = None,
) -> ScenarioSpec:
    payload: dict = {
        "schemaVersion": 1,
        "gameVariant": "nlhe",
        "tableSize": 2,
        "smallBlind": 50,
        "bigBlind": 100,
        "buttonSeat": 0,
        "heroSeat": 0,
        "seats": [
            {"seatId": 0, "startingStack": 10000, "position": "button"},
            {"seatId": 1, "startingStack": 10000, "position": "big_blind"},
        ],
        "board": list(board),
        "actionHistory": [event.to_dict() for event in events],
        "decisionPoint": {"street": "flop", "actorSeat": 0, "afterSequence": after_sequence},
        "assumptions": {},
    }
    if ranges is not None:
        payload["rangesBySeat"] = {
            seat: spec.to_dict() for seat, spec in ranges.items()
        }
    if known_by_seat is not None:
        payload["knownHoleCardsBySeat"] = {
            seat: list(cards) for seat, cards in known_by_seat.items()
        }
    return ScenarioSpec.model_validate(payload)


def scenario_with_raise() -> ScenarioSpec:
    return make_scenario(
        events=(raise_event(1, 0, 250),), after_sequence=1
    )


def fixture_raise_policy() -> FixturePolicyProvider:
    return FixturePolicyProvider(
        {
            "raise_to": {
                "AsAh": {"raise": "1"},
                "JsJh": {"raise": "0.8"},
                "7s6s": {"raise": "0.7"},
                "Js4d": {"raise": "0.05"},
            }
        }
    )


class TestSingleActionBayesianUpdate:
    def test_hand_computed_bayes_regression(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        policy = fixture_raise_policy().get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)

        assert updated.combos["AsAh"].reach == Decimal("1.00")
        assert updated.combos["JsJh"].reach == Decimal("0.80")
        assert updated.combos["7s6s"].reach == Decimal("0.49")
        assert updated.combos["Js4d"].reach == Decimal("0.01")
        retained = Decimal("2.30")
        assert updated.retained_mass == retained
        assert updated.prior_mass == PRIOR_TOTAL
        assert updated.source is PolicySource.FIXTURE
        assert updated.confidence == "grounded"
        for key, reach in (
            ("AsAh", Decimal("1.00")),
            ("JsJh", Decimal("0.80")),
            ("7s6s", Decimal("0.49")),
            ("Js4d", Decimal("0.01")),
        ):
            assert updated.combos[key].probability == (reach / retained)

    def test_probabilities_normalize_to_one(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        policy = fixture_raise_policy().get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        total = sum(combo.probability for combo in updated.combos.values())
        assert abs(total - Decimal("1")) < Decimal("1e-9")

    def test_reach_is_monotonic_under_likelihoods(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        policy = fixture_raise_policy().get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        for key, combo in prior.combos.items():
            assert updated.combos[key].reach <= combo.reach

    def test_certain_action_keeps_reach_unchanged(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AsAh": {"raise": "1"},
                    "JsJh": {"raise": "1"},
                    "7s6s": {"raise": "1"},
                    "Js4d": {"raise": "1"},
                }
            }
        )
        policy = provider.get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        for key, combo in prior.combos.items():
            assert updated.combos[key].reach == combo.reach
        for key, combo in prior.combos.items():
            assert updated.combos[key].probability == combo.probability

    def test_relative_belief_prefers_preferred_combo(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        policy = fixture_raise_policy().get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        prior_ratio = prior.combos["AsAh"].probability / prior.combos["JsJh"].probability
        posterior_ratio = (
            updated.combos["AsAh"].probability / updated.combos["JsJh"].probability
        )
        assert posterior_ratio > prior_ratio

    def test_zero_likelihood_removes_combo(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AsAh": {"raise": "1"},
                    "JsJh": {"raise": "0.5"},
                    "7s6s": {"raise": "0.5"},
                    "Js4d": {"raise": "0"},
                }
            }
        )
        policy = provider.get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        assert "Js4d" not in updated.combos
        assert set(updated.combos) == {"AsAh", "JsJh", "7s6s"}

    def test_polarized_action_is_policy_conditioned_not_hand_strength(self):
        # AA and 76s raise at high frequency; JJ and KQo barely raise. After
        # the raise, AA AND 76s must be up while JJ AND KQo are down — the
        # engine follows the policy, not a value/bluff hand-strength rule.
        prior = snapshot_from_range(
            prior_range({"AsAh": "1", "JsJh": "1", "7s6s": "0.7", "KcQd": "1"}),
            seat_id=0,
            street=Street.PREFLOP,
            after_sequence=0,
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AsAh": {"raise": "0.9"},
                    "JsJh": {"raise": "0.2"},
                    "7s6s": {"raise": "0.8"},
                    "KcQd": {"raise": "0.1"},
                }
            }
        )
        policy = provider.get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        updated = update_range_belief(prior, raise_event(1, 0, 250), policy)
        for key in ("AsAh", "7s6s"):
            assert updated.combos[key].probability > prior.combos[key].probability
        for key in ("JsJh", "KcQd"):
            assert updated.combos[key].probability < prior.combos[key].probability

    def test_zero_probability_action_raises_structured_error(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AsAh": {"raise": "0"},
                    "JsJh": {"raise": "0"},
                    "7s6s": {"raise": "0"},
                    "Js4d": {"raise": "0"},
                }
            }
        )
        policy = provider.get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        with pytest.raises(ZeroProbabilityActionError) as exc:
            update_range_belief(prior, raise_event(1, 0, 250), policy)
        assert exc.value.code == "zero_probability_action"

    def test_unsupported_action_type_raises(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        complete = PolicyResult(
            source=PolicySource.FIXTURE,
            actions=("Check", "Bet(100)"),
            frequencies={
                key: {"Check": Decimal("0.5"), "Bet(100)": Decimal("0.5")}
                for key in prior.combos
            },
        )
        with pytest.raises(UnsupportedActionError) as exc:
            update_range_belief(prior, call_event(1, 0, 100), complete)
        assert exc.value.code == "unsupported_action"


class TestDeadCards:
    def test_known_hole_cards_filter_prior(self):
        prior = snapshot_from_range(
            prior_range(),
            seat_id=0,
            street=Street.PREFLOP,
            after_sequence=0,
            dead_cards=("As", "Ah"),
        )
        assert "AsAh" not in prior.combos
        assert set(prior.combos) == {"JsJh", "7s6s", "Js4d"}

    def test_board_transition_removes_and_renormalizes(self):
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        flop = apply_dead_cards(
            prior,
            ("7s", "8c", "2d"),
            street=Street.FLOP,
            after_sequence=3,
            action_type="deal_flop",
            action_label="Deal flop",
        )
        assert "7s6s" not in flop.combos
        remaining = {k: v.reach for k, v in prior.combos.items() if k != "7s6s"}
        total = sum(remaining.values())
        assert flop.retained_mass == total
        assert flop.prior_mass == prior.retained_mass
        for key, reach in remaining.items():
            assert flop.combos[key].reach == reach
            assert flop.combos[key].probability == reach / total
        total_probability = sum(c.probability for c in flop.combos.values())
        assert abs(total_probability - Decimal("1")) < Decimal("1e-9")

    def test_deal_eliminating_every_combo_raises(self):
        narrow = RangeSpec(
            range_id="narrow",
            name="Narrow",
            version="1",
            source=RangeSource.USER_DEFINED,
            combos=(RangeCombo(cards=("As", "Ks"), weight=Decimal("1")),),
        )
        prior = snapshot_from_range(
            narrow, seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        with pytest.raises(ZeroProbabilityActionError):
            apply_dead_cards(
                prior,
                ("As", "7d", "2c"),
                street=Street.FLOP,
                after_sequence=3,
                action_type="deal_flop",
            )


class TestFixtureProvider:
    def test_starting_hand_keys_expand_to_concrete_combos(self):
        provider = FixturePolicyProvider(
            {"raise_to": {"AA": {"raise": "0.5"}, "76s": {"raise": "0.5"}}}
        )
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        policy = provider.get_action_frequencies(
            scenario_with_raise(), 0, 1, tuple(prior.combos)
        )
        assert policy.likelihood_only is True
        assert policy.frequencies["AsAh"]["raise"] == Decimal("0.5")
        assert "AsAh" in policy.frequencies
        assert "Js4d" not in policy.frequencies  # not in the AA/76s fixture

    def test_missing_action_type_raises_no_policy(self):
        provider = FixturePolicyProvider({"check": {"AsAh": {"check": "0.5"}}})
        prior = snapshot_from_range(
            prior_range(), seat_id=0, street=Street.PREFLOP, after_sequence=0
        )
        with pytest.raises(NoPolicyError):
            provider.get_action_frequencies(
                scenario_with_raise(), 0, 1, tuple(prior.combos)
            )

    def test_inconsistent_action_labels_rejected(self):
        with pytest.raises(InvalidPolicyError):
            FixturePolicyProvider(
                {
                    "raise_to": {
                        "AsAh": {"raise": "1"},
                        "JsJh": {"raise": "0.5", "call": "0.5"},
                    }
                }
            )

    def test_invalid_frequency_range_rejected(self):
        with pytest.raises(InvalidPolicyError):
            FixturePolicyProvider({"raise_to": {"AsAh": {"raise": "1.5"}}})


class TestTrace:
    def test_multi_step_trace_with_board_transition(self):
        scenario = make_scenario(
            events=(
                raise_event(1, 0, 250),
                call_event(2, 1, 150),
                deal_event(3, Street.FLOP),
                check_event(4, 1),
                bet_event(5, 0, 100),
            ),
            board=("Ks", "7d", "2c"),
            ranges={0: prior_range()},
            after_sequence=5,
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AsAh": {"raise": "1"},
                    "JsJh": {"raise": "1"},
                    "7s6s": {"raise": "1"},
                    "Js4d": {"raise": "1"},
                },
                "bet": {
                    "AsAh": {"bet": "0.7"},
                    "JsJh": {"bet": "0.4"},
                    "7s6s": {"bet": "0.5"},
                    "Js4d": {"bet": "0.1"},
                },
            }
        )
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=provider
        )
        assert trace.available is True
        # Snapshots only at: prior (seq 0), own raise (1), deal (3), own bet (5).
        assert [snapshot.after_sequence for snapshot in trace.snapshots] == [0, 1, 3, 5]
        assert trace.snapshots[1].parent_snapshot_id == trace.snapshots[0].snapshot_id
        assert trace.snapshots[2].parent_snapshot_id == trace.snapshots[1].snapshot_id
        assert trace.snapshots[3].parent_snapshot_id == trace.snapshots[2].snapshot_id
        # Reach inherits through the deal (board does not block these combos).
        final = trace.current
        assert final.after_sequence == 5
        assert final.combos["AsAh"].reach == Decimal("0.7")
        assert final.combos["JsJh"].reach == Decimal("0.4")
        assert final.combos["7s6s"].reach == Decimal("0.35")
        assert final.combos["Js4d"].reach == Decimal("0.02")
        assert final.retained_mass == Decimal("1.47")
        assert final.update.action_type == "bet"
        assert final.update.policy_source is PolicySource.FIXTURE

    def test_board_blocker_applies_in_trace(self):
        # Matrix prior (like the real app): expansion naturally contains
        # combos blocked by the flop (7s6s), which the deal removes.
        matrix_prior = RangeSpec(
            range_id="matrix-prior",
            name="Matrix prior",
            version="1",
            source=RangeSource.USER_DEFINED,
            matrix169={"AA": "1", "KK": "1", "76s": "1", "J4o": "0.2"},
        )
        scenario = make_scenario(
            events=(
                raise_event(1, 0, 250),
                call_event(2, 1, 150),
                deal_event(3, Street.FLOP),
            ),
            board=("7s", "8c", "2d"),
            ranges={0: matrix_prior},
            after_sequence=3,
        )
        provider = FixturePolicyProvider(
            {
                "raise_to": {
                    "AA": {"raise": "1"},
                    "KK": {"raise": "1"},
                    "76s": {"raise": "1"},
                    "J4o": {"raise": "1"},
                }
            }
        )
        trace = build_range_trace(
            scenario, 0, prior_range=matrix_prior, provider=provider
        )
        assert "7s6s" not in trace.current.combos
        assert trace.current.after_sequence == 3

    def test_no_policy_marks_trace_unavailable_without_fabrication(self):
        scenario = make_scenario(
            events=(raise_event(1, 0, 250),),
            ranges={0: prior_range()},
            after_sequence=1,
        )
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=None
        )
        assert trace.available is False
        assert "no_policy" in trace.unavailable_reason
        assert trace.stalled_at_sequence == 1
        assert len(trace.snapshots) == 1  # only the prior; nothing fabricated

    def test_policy_gap_mid_chain_stops_at_the_gap(self):
        scenario = make_scenario(
            events=(
                raise_event(1, 0, 250),
                call_event(2, 1, 150),
                bet_event(3, 0, 100),
            ),
            ranges={0: prior_range()},
            after_sequence=3,
        )
        # Only the raise has a fixture; the later bet has no policy.
        provider = fixture_raise_policy()
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=provider
        )
        assert trace.available is False
        assert trace.stalled_at_sequence == 3
        assert trace.current.after_sequence == 1  # last grounded snapshot

    def test_fresh_hand_prior_is_available(self):
        scenario = make_scenario(ranges={0: prior_range()}, after_sequence=0)
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=None
        )
        assert trace.available is True
        assert trace.current.after_sequence == 0
        assert trace.current.source is PolicySource.MANUAL
        assert trace.current.confidence == "manual"

    def test_other_seat_actions_do_not_create_snapshots(self):
        scenario = make_scenario(
            events=(
                raise_event(1, 0, 250),
                call_event(2, 1, 150),
                check_event(3, 1),
            ),
            ranges={0: prior_range()},
            after_sequence=3,
        )
        provider = fixture_raise_policy()
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=provider
        )
        assert [snapshot.after_sequence for snapshot in trace.snapshots] == [0, 1]


class TestAggregation:
    def test_mass_conservation(self):
        scenario = make_scenario(
            events=(raise_event(1, 0, 250),),
            ranges={0: prior_range()},
            after_sequence=1,
        )
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=fixture_raise_policy()
        )
        matrix = aggregate_belief_to_matrix169(trace.current, prior=trace.prior)
        combo_total = sum(combo.probability for combo in trace.current.combos.values())
        matrix_total = sum(cell.probability_mass for cell in matrix.values())
        assert abs(matrix_total - Decimal("1")) < Decimal("1e-9")
        assert abs(combo_total - matrix_total) < Decimal("1e-9")

    def test_suit_specific_combos_keep_their_own_mass(self):
        prior = snapshot_from_range(
            prior_range({"AsKs": "1", "AhKh": "1"}),
            seat_id=0,
            street=Street.PREFLOP,
            after_sequence=0,
        )
        provider = FixturePolicyProvider(
            {
                "bet": {
                    "AsKs": {"bet": "0.3"},
                    "AhKh": {"bet": "0.8"},
                }
            }
        )
        scenario = make_scenario(events=(bet_event(1, 0, 100),), after_sequence=1)
        policy = provider.get_action_frequencies(scenario, 0, 1, tuple(prior.combos))
        updated = update_range_belief(prior, bet_event(1, 0, 100), policy)
        assert updated.combos["AsKs"].reach == Decimal("0.3")
        assert updated.combos["AhKh"].reach == Decimal("0.8")
        # Different suit-specific probabilities...
        assert updated.combos["AsKs"].probability != updated.combos["AhKh"].probability
        # ...but one 169 cell with the summed mass.
        matrix = aggregate_belief_to_matrix169(updated, prior=prior)
        assert matrix["AKs"].combo_count == 2
        expected = updated.combos["AsKs"].probability + updated.combos["AhKh"].probability
        assert matrix["AKs"].probability_mass == expected
        assert matrix["AKs"].prior_probability_mass == Decimal("1")

    def test_cell_key_matches_starting_hand_notation(self):
        assert cell_key("AsKs") == "AKs"
        assert cell_key("AhKh") == "AKs"
        assert cell_key("AsKd") == "AKo"
        assert cell_key("AsAh") == "AA"
        assert cell_key("5c4c") == "54s"
        assert cell_key("2d2c") == "22"


class TestView:
    def test_prior_current_delta_view(self):
        scenario = make_scenario(
            events=(raise_event(1, 0, 250),),
            ranges={0: prior_range()},
            after_sequence=1,
        )
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=fixture_raise_policy()
        )
        view = build_belief_view(trace)
        assert view.available is True
        assert view.source is PolicySource.FIXTURE
        combo = view.combos["AsAh"]
        assert combo.prior_probability == Decimal("1") / PRIOR_TOTAL
        assert combo.probability == Decimal("1") / Decimal("2.30")
        assert combo.delta == combo.probability - combo.prior_probability
        assert combo.multiplier == combo.probability / combo.prior_probability
        assert view.matrix169["AA"].delta == combo.delta
        assert view.update.action_type == "raise_to"

    def test_unavailable_view_reports_reason_without_numbers(self):
        scenario = make_scenario(
            events=(raise_event(1, 0, 250),),
            ranges={0: prior_range()},
            after_sequence=1,
        )
        trace = build_range_trace(
            scenario, 0, prior_range=prior_range(), provider=None
        )
        view = build_belief_view(trace)
        assert view.available is False
        assert "no_policy" in view.unavailable_reason
        assert view.combos is not None  # prior combos still visible
        assert view.matrix169 is not None


class TestSolverAdapter:
    def _solver_result(self) -> SolveResult:
        root = SolverNode(
            actions=("Check", "Bet(100)"),
            player=0,
            hands=(
                SolverHand(
                    combo="AsKs",
                    weight=1.0,
                    equity=0.5,
                    ev=0.1,
                    strategy={"Check": 0.7, "Bet(100)": 0.3},
                ),
                SolverHand(
                    combo="AhKh",
                    weight=1.0,
                    equity=0.5,
                    ev=0.2,
                    strategy={"Check": 0.2, "Bet(100)": 0.8},
                ),
            ),
        )
        metadata = SolveMetadata(
            solver="postflop-solver",
            version="test",
            street="flop",
            max_iterations=1,
            exploitability_chips=0.0,
            target_exploitability_chips=0.0,
        )
        return SolveResult(metadata=metadata, root=root, response_node=None)

    def test_observed_bet_raises_preferred_combo_belief(self):
        result = self._solver_result()
        adapter = SolverPolicyAdapter(
            result, oop_seat=1, ip_seat=0, reference_pot=300
        )
        prior = snapshot_from_range(
            prior_range({"AsKs": "1", "AhKh": "1"}),
            seat_id=1,
            street=Street.FLOP,
            after_sequence=3,
        )
        scenario = make_scenario(
            events=(bet_event(1, 1, 100),),
            ranges={1: prior_range({"AsKs": "1", "AhKh": "1"})},
            after_sequence=1,
        )
        policy = adapter.get_action_frequencies(scenario, 1, 1, tuple(prior.combos))
        assert policy.source is PolicySource.SOLVER
        assert policy.actions == ("Check", "Bet(100)")
        updated = update_range_belief(
            prior, bet_event(1, 1, 100), policy, pot_before=300
        )
        assert updated.combos["AhKh"].probability > updated.combos["AsKs"].probability
        assert updated.combos["AhKh"].probability == Decimal("0.8") / Decimal("1.1")
        assert updated.combos["AsKs"].probability == Decimal("0.3") / Decimal("1.1")

    def test_no_node_for_unknown_seat(self):
        result = self._solver_result()
        adapter = SolverPolicyAdapter(result, oop_seat=1, ip_seat=0)
        with pytest.raises(NoPolicyError):
            adapter.get_action_frequencies(make_scenario(), 2, 4, ())

    def test_strategy_frequency_validation_rejects_bad_sums(self):
        with pytest.raises(ValidationError, match="sum to"):
            PolicyResult(
                source=PolicySource.SOLVER,
                actions=("Check", "Bet(100)"),
                frequencies={
                    "AsKs": {"Check": Decimal("0.7"), "Bet(100)": Decimal("0.2")}
                },
            )


class TestOffTreeMatching:
    def test_nearest_size_maps_and_flags_off_tree(self):
        match = match_observed_action(
            bet_event(1, 0, 120),
            ("Check", "Bet(100)", "Bet(225)"),
            pot_before=300,
            reference_pot=300,
        )
        assert match.status.value == "nearest_size"
        assert match.policy_action == "Bet(100)"
        assert match.off_tree is True
        assert match.observed_size == Decimal("0.4")
        assert match.mapped_size == Decimal("100") / Decimal("300")

    def test_exact_size_match_is_not_off_tree(self):
        match = match_observed_action(
            bet_event(1, 0, 100),
            ("Check", "Bet(100)", "Bet(225)"),
            pot_before=300,
            reference_pot=300,
        )
        assert match.status.value == "exact"
        assert match.policy_action == "Bet(100)"
        assert match.off_tree is False

    def test_equidistant_tie_resolves_to_smaller_size(self):
        match = match_observed_action(
            bet_event(1, 0, 150),
            ("Check", "Bet(100)", "Bet(200)"),
            pot_before=300,
            reference_pot=300,
        )
        assert match.status.value == "nearest_size"
        assert match.policy_action == "Bet(100)"  # |50-33.3| == |50-66.7| -> smaller

    def test_call_without_policy_call_is_unsupported(self):
        match = match_observed_action(
            call_event(1, 0, 100),
            ("Check", "Bet(100)"),
            pot_before=300,
            reference_pot=300,
        )
        assert match.status.value == "unsupported"

    def test_raise_to_maps_to_nearest_raise(self):
        match = match_observed_action(
            raise_event(1, 0, 600),
            ("Fold", "Call", "Raise(500)", "Raise(900)"),
            pot_before=300,
            reference_pot=300,
        )
        assert match.policy_action == "Raise(500)"
        assert match.off_tree is True

    def test_chip_amount_fallback_without_pot_context(self):
        match = match_observed_action(
            bet_event(1, 0, 220),
            ("Check", "Bet(100)", "Bet(225)"),
            pot_before=None,
            reference_pot=None,
        )
        assert match.policy_action == "Bet(225)"
        assert match.off_tree is True
