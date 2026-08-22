from datetime import datetime, timezone
from decimal import Decimal

import pytest

from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer
from poker_coach.ranges.policy_artifact import default_policy_artifact_range_adapter
from poker_coach.ranges.seat_priors import SeatPriorQueryV1, default_seat_prior_provider
from poker_coach.simulator.bot_providers import _sample_action
from poker_coach.simulator.table_insights import _public_stream
from poker_coach.simulator.contracts import (ActionTakenPayloadV1, AmountSemanticsV1, BoardDealtPayloadV1, ContractProvenanceV1, EventSourceV1, HandEventV1, HandStartedPayloadV1, HoleCardsRecordedPayloadV1, SimulatorActionV1)
from poker_coach.domain.models import Street
from poker_coach.theory.policy_artifact import PolicyArtifact, PolicyArtifactError


def _event(sequence, payload):
    return HandEventV1(event_id=f"e{sequence}", hand_id="h", sequence=sequence, timestamp=datetime.now(timezone.utc), source=EventSourceV1.FIXTURE, provenance=ContractProvenanceV1(producer="test", producer_version="1", correlation_id="c"), payload=payload)


def _stream(*payloads, active=(0, 1, 2, 3, 4, 5), button=0, table_size=6, stack=10000):
    started = HandStartedPayloadV1(table_size=table_size, button_seat=button, small_blind=50, big_blind=100, starting_stacks={i: stack for i in range(table_size)}, active_seat_ids=active, rng_seed=1)
    return tuple(_event(i + 1, payload) for i, payload in enumerate((started, *payloads)))


def _action(seat, action):
    semantics = {SimulatorActionV1.FOLD: AmountSemanticsV1.NONE, SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
                 SimulatorActionV1.CALL: AmountSemanticsV1.COST, SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
                 SimulatorActionV1.BET: AmountSemanticsV1.BY}[action]
    return ActionTakenPayloadV1(street=Street.PREFLOP, actor_seat=seat, action=action, amount=None if semantics is AmountSemanticsV1.NONE else 100, amount_semantics=semantics)


def test_actor_only_update_and_historical_prefix_is_deterministic():
    events = _stream(_action(2, SimulatorActionV1.RAISE), _action(3, SimulatorActionV1.CALL))
    consumer = PublicEventBeliefConsumer()
    at_one = consumer.beliefs_at(events, after_sequence=2)
    full = consumer.beliefs_at(events)
    assert at_one[2].current.retained_mass != at_one[2].prior.retained_mass
    assert at_one[3].current.retained_mass == at_one[3].prior.retained_mass
    assert at_one[2].to_json() == consumer.beliefs_at(events, after_sequence=2)[2].to_json()
    assert full[2].current.to_json() == at_one[2].current.to_json()


def test_board_filters_every_seat_and_normalizes_with_hero_blockers():
    events = _stream(BoardDealtPayloadV1(street=Street.FLOP, cards=("As", "Kd", "2c")))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events, observer_visible_cards=("Qh", "Qs"))
    for belief in beliefs.values():
        assert len(belief.current.combos) == 1081
        assert sum(combo.probability for combo in belief.current.combos.values()) == Decimal("1")
        assert all(card not in key for key in belief.current.combos for card in ("As", "Kd", "2c", "Qh", "Qs"))


def test_private_event_is_rejected_and_no_private_data_is_returned():
    events = _stream(HoleCardsRecordedPayloadV1(seat_id=4, cards=("As", "Kd")))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events)
    assert all(not belief.available and belief.unavailable_reason == "private_event_forbidden" for belief in beliefs.values())


def test_fold_call_raise_check_are_supported_and_sparse_seats_work():
    events = _stream(_action(2, SimulatorActionV1.FOLD), _action(3, SimulatorActionV1.CALL), _action(4, SimulatorActionV1.RAISE), _action(5, SimulatorActionV1.CHECK))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events)
    assert all(belief.available for belief in beliefs.values())
    assert beliefs[4].current.retained_mass != beliefs[4].prior.retained_mass
    sparse = _stream(active=(0, 2, 3, 5, 6, 7), button=5, table_size=8)
    unavailable = PublicEventBeliefConsumer().beliefs_at(sparse)
    assert all(belief.unavailable_reason.startswith("prior_unavailable:table_size_unsupported") for belief in unavailable.values())


def test_common_stack_buckets_are_available_and_nearest_bucket_is_explicit():
    provider = default_seat_prior_provider()
    for stack in (2000, 4000, 6000, 8000, 10000, 15000, 20000):
        result = provider.get_prior(
            SeatPriorQueryV1(table_size=6, active_seat_ids=(0, 1, 2, 3, 4, 5), button_seat=0,
                small_blind=50, big_blind=100, starting_stacks={seat: stack for seat in range(6)}),
            3,
        )
        assert result.available
        assert result.coverage.effective_stack_bucket.endswith("bb")
        assert len(result.snapshot.combos) == 1326
        assert abs(sum(combo.probability for combo in result.snapshot.combos.values()) - Decimal("1")) < Decimal("1e-24")
    approximate = PublicEventBeliefConsumer().beliefs_at(_stream(stack=11000))
    assert all(belief.approximate and belief.approximation_reason == "nearest_stack_bucket:100bb" for belief in approximate.values())


def test_policy_root_prior_and_public_actions_are_normalized_and_fold_inactive():
    events = _stream(_action(3, SimulatorActionV1.RAISE), _action(4, SimulatorActionV1.FOLD))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events)
    assert beliefs[0].prior.combos["AsAh"].probability == beliefs[3].prior.combos["AsAh"].probability
    assert beliefs[3].prior.source.value == "preflop_policy"
    assert beliefs[3].current.update.action_type == "raise"
    assert beliefs[3].current.update.action_label == "public_action:preflop:raise:medium:utg:deep"
    assert sum(combo.probability for combo in beliefs[3].current.combos.values()) == Decimal("1")
    assert beliefs[4].inactive is True
    assert beliefs[4].current.update.action_type == "fold"


def test_public_prefix_is_not_poisoned_by_opponent_true_cards():
    public = _stream(_action(3, SimulatorActionV1.RAISE))
    consumer = PublicEventBeliefConsumer()
    baseline = consumer.beliefs_at(public, observer_visible_cards=("Ah", "Kd"))
    poisoned_events = (*public, _event(3, HoleCardsRecordedPayloadV1(seat_id=3, cards=("Qs", "Qc"))))
    # Authoritative opponent cards are deliberately removed before this seam.
    poisoned = consumer.beliefs_at(_public_stream(poisoned_events), observer_visible_cards=("Ah", "Kd"))
    assert baseline[3].current.to_json() == poisoned[3].current.to_json()


def _rfi(seat: int, amount: int = 250) -> ActionTakenPayloadV1:
    return ActionTakenPayloadV1(
        street=Street.PREFLOP,
        actor_seat=seat,
        action=SimulatorActionV1.RAISE,
        amount=amount,
        amount_semantics=AmountSemanticsV1.TO,
    )


def test_covered_rfi_prior_and_likelihood_use_the_same_b_artifact():
    events = _stream(_rfi(3))
    belief = PublicEventBeliefConsumer().beliefs_at(events)[3]
    adapter = default_policy_artifact_range_adapter()
    policy, use = adapter.policy_for_action(
        events[0].payload, (), events[1].payload, tuple(belief.prior.combos)
    )

    assert belief.provenance.evidence_grade == "B"
    assert belief.provenance.coverage_status == "covered"
    assert belief.provenance.policy_fingerprint == adapter.fingerprint
    assert belief.provenance.independent_marginal_only is True
    assert belief.current.update.policy_version == adapter.version
    assert f"policy_fingerprint:{adapter.fingerprint}" in belief.current.update.assumptions
    assert use.action_prefix == "rfi"
    for combo in ("As8s", "7s2c"):
        likelihood = policy.frequencies[combo][use.policy_action]
        assert belief.current.combos[combo].reach / belief.prior.combos[combo].reach == likelihood
    assert sum(combo.probability for combo in belief.current.combos.values()) == Decimal("1")


def test_single_rfi_response_and_bot_sampling_share_exact_artifact_frequency():
    events = _stream(_rfi(3), _rfi(4, 900))
    belief = PublicEventBeliefConsumer().beliefs_at(events)[4]
    adapter = default_policy_artifact_range_adapter()
    policy, use = adapter.policy_for_action(
        events[0].payload, (events[1].payload,), events[2].payload,
        tuple(belief.prior.combos),
    )
    expected = policy.frequencies["As8s"][use.policy_action]
    frequencies = {
        "raise_to": policy.frequencies["As8s"].get("Raise(900)", Decimal("0")),
        "call": policy.frequencies["As8s"].get("Call", Decimal("0")),
        "fold": policy.frequencies["As8s"].get("Fold", Decimal("0")),
    }
    sampled = sum(
        _sample_action(frequencies, seed, use.node_id, "A8s") == "raise_to"
        for seed in range(10_000)
    ) / Decimal("10000")

    assert use.action_prefix == "vs_single_rfi"
    assert belief.current.combos["As8s"].reach / belief.prior.combos["As8s"].reach == expected
    assert abs(sampled - expected) < Decimal("0.02")
    assert belief.provenance.policy_fingerprint == adapter.fingerprint


def test_tree_miss_is_explicit_c_fallback_without_losing_mass_or_privacy_boundary():
    events = _stream(_rfi(3, 300), _action(4, SimulatorActionV1.CALL))
    belief = PublicEventBeliefConsumer().beliefs_at(events)[4]

    assert belief.provenance.evidence_grade == "C"
    assert belief.provenance.coverage_status == "fallback"
    assert belief.provenance.fallback_reason is not None
    assert "tree_or_action_prefix" in belief.provenance.fallback_reason
    assert sum(combo.probability for combo in belief.current.combos.values()) == Decimal("1")
    assert belief.provenance.independent_marginal_only is True


def test_stack_and_postflop_misses_are_explicit_c_fallbacks():
    stack_miss = PublicEventBeliefConsumer().beliefs_at(_stream(stack=11_000))[3]
    postflop = PublicEventBeliefConsumer().beliefs_at(
        _stream(
            BoardDealtPayloadV1(street=Street.FLOP, cards=("As", "Kd", "2c")),
            ActionTakenPayloadV1(
                street=Street.FLOP, actor_seat=3, action=SimulatorActionV1.BET,
                amount=100, amount_semantics=AmountSemanticsV1.BY,
            ),
        )
    )[3]

    assert (stack_miss.provenance.evidence_grade, stack_miss.provenance.fallback_reason) == ("C", "non_100bb")
    assert (postflop.provenance.evidence_grade, postflop.provenance.fallback_reason) == ("C", "street")


def test_corrupt_policy_fingerprint_is_rejected_before_range_cache_or_likelihood_use():
    payload = default_policy_artifact_range_adapter().artifact.to_payload()
    payload["integrity"]["fingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(PolicyArtifactError, match="fingerprint mismatch"):
        PolicyArtifact.load(payload)
