"""Public-event, independent-marginal Range Belief consumer.

Only public HandEvent V1 payloads are accepted.  The caller supplies the
observer-visible hole cards as blockers; private-card events, RNG, deck state,
and future stream events are deliberately outside this seam.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from threading import Lock

from pydantic import ConfigDict, Field, model_validator

from poker_coach.domain.models import Card, DomainModel, Street
from poker_coach.simulator.contracts import (
    ActionTakenPayloadV1, AmountSemanticsV1, BoardDealtPayloadV1, HandEventV1,
    HandStartedPayloadV1, HoleCardsRecordedPayloadV1, SimulatorActionV1,
)

from .belief import NoPolicyError, PolicySource, RangeBeliefCombo, RangeBeliefSnapshot, RangeUpdateMetadata, combo_overlaps, snapshot_id_for
from .likelihood import PublicActionContext, change_reason, likelihood, size_bucket, spr_bucket
from .policy import PolicyResult
from .policy_artifact import default_policy_artifact_range_adapter
from .seat_priors import SeatPriorQueryV1, SeatPriorResultV1, SeatPriorUnavailableReason, default_seat_prior_provider

_VERSION = "heuristic_likelihood_v2"
_FINGERPRINT = sha256(b"riverline/public-event-belief/heuristic_likelihood_v2/public-size-street-position-spr-hand-features").hexdigest()


class _ImmutableDict(dict[str, RangeBeliefCombo]):
    """JSON-compatible dict whose mutation surface is fully disabled."""

    def _blocked(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("cached range values are immutable")

    __setitem__ = _blocked
    __delitem__ = _blocked
    clear = _blocked
    pop = _blocked
    popitem = _blocked
    setdefault = _blocked
    update = _blocked
    __ior__ = _blocked


class _ImmutableRangeBeliefCombo(RangeBeliefCombo):
    model_config = ConfigDict(frozen=True)


class _ImmutableRangeUpdateMetadata(RangeUpdateMetadata):
    model_config = ConfigDict(frozen=True)


class _ImmutableRangeBeliefSnapshot(RangeBeliefSnapshot):
    model_config = ConfigDict(frozen=True)


_BLOCKER_CACHE_MAX = 48
_BLOCKER_CACHE: OrderedDict[
    tuple[int, tuple[Card, ...], int, Street],
    tuple[RangeBeliefSnapshot, RangeBeliefSnapshot],
] = OrderedDict()
_BLOCKER_CACHE_LOCK = Lock()
_ACTION_CACHE_MAX = 64
_ACTION_CACHE: OrderedDict[
    tuple[object, ...], tuple[RangeBeliefSnapshot, RangeBeliefSnapshot]
] = OrderedDict()
_ACTION_CACHE_LOCK = Lock()
_INACTIVE_CACHE_MAX = 16
_INACTIVE_CACHE: OrderedDict[
    int, tuple[RangeBeliefSnapshot, RangeBeliefSnapshot]
] = OrderedDict()
_INACTIVE_CACHE_LOCK = Lock()
_ACTION_DISTRIBUTION_CACHE_MAX = 64
_ACTION_DISTRIBUTION_CACHE: OrderedDict[
    tuple[object, ...],
    tuple[
        RangeBeliefSnapshot, dict[str, RangeBeliefCombo], Decimal, str, Decimal
    ],
] = OrderedDict()
_ACTION_DISTRIBUTION_CACHE_LOCK = Lock()
_IMMUTABLE_SNAPSHOT_CACHE_MAX = 32
_IMMUTABLE_SNAPSHOT_CACHE: OrderedDict[
    int, tuple[RangeBeliefSnapshot, _ImmutableRangeBeliefSnapshot]
] = OrderedDict()
_IMMUTABLE_SNAPSHOT_CACHE_LOCK = Lock()
_BELIEF_CACHE_MAX = 12
_BELIEF_CACHE: OrderedDict[
    tuple[object, ...], dict[int, "SeatBeliefResultV1"]
] = OrderedDict()
_BELIEF_CACHE_LOCK = Lock()


class SeatBeliefUnavailableReason(str, Enum):
    EMPTY_STREAM = "empty_stream"
    INVALID_STREAM = "invalid_stream"
    PRIVATE_EVENT_FORBIDDEN = "private_event_forbidden"
    PRIOR_UNAVAILABLE = "prior_unavailable"
    OFF_TREE_UNSUPPORTED = "off_tree_unsupported"


class SeatBeliefProvenanceV1(DomainModel):
    provider: str = "riverline.heuristic_likelihood"
    version: str = _VERSION
    artifact_fingerprint: str = _FINGERPRINT
    trust_level: str = "heuristic"
    confidence: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    independent_marginal_only: bool = True
    evidence_grade: str = "C"
    coverage_status: str = "fallback"
    fallback_reason: str | None = None
    policy_fingerprint: str | None = None


class SeatBeliefResultV1(DomainModel):
    seat_id: int
    after_sequence: int
    available: bool
    prior: RangeBeliefSnapshot | None = None
    current: RangeBeliefSnapshot | None = None
    provenance: SeatBeliefProvenanceV1 | None = None
    inactive: bool = False
    approximate: bool = False
    approximation_reason: str | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "SeatBeliefResultV1":
        if self.available != (self.prior is not None and self.current is not None and self.provenance is not None):
            raise ValueError("available result requires prior, current, and provenance")
        if self.available == (self.unavailable_reason is not None):
            raise ValueError("unavailable reason must appear exactly on unavailable results")
        return self


class _ImmutableSeatBeliefProvenance(SeatBeliefProvenanceV1):
    model_config = ConfigDict(frozen=True)


class _ImmutableSeatBeliefResult(SeatBeliefResultV1):
    model_config = ConfigDict(frozen=True)


class PublicEventBeliefConsumer:
    """Replay a bounded public prefix into per-seat independent beliefs."""

    def beliefs_at(
        self, events: tuple[HandEventV1, ...], *, observer_visible_cards: tuple[Card, ...] = (), after_sequence: int | None = None,
    ) -> dict[int, SeatBeliefResultV1]:
        if not events or not isinstance(events[0].payload, HandStartedPayloadV1):
            return {}
        target = events[-1].sequence if after_sequence is None else after_sequence
        prefix = tuple(event for event in events if event.sequence <= target)
        if not prefix or prefix[0].sequence != 1 or any(event.sequence != index + 1 for index, event in enumerate(prefix)):
            return _unavailable_all(events[0].payload, target, SeatBeliefUnavailableReason.INVALID_STREAM)
        if any(isinstance(event.payload, HoleCardsRecordedPayloadV1) for event in prefix):
            return _unavailable_all(events[0].payload, target, SeatBeliefUnavailableReason.PRIVATE_EVENT_FORBIDDEN)
        started = prefix[0].payload
        assert isinstance(started, HandStartedPayloadV1)
        belief_cache_key = _belief_cache_key(
            started, prefix, observer_visible_cards, target
        )
        cached_beliefs = _belief_cache_get(belief_cache_key)
        if cached_beliefs is not None:
            return cached_beliefs
        public_cards = tuple(card for event in prefix if isinstance(event.payload, BoardDealtPayloadV1) for card in event.payload.cards)
        query = SeatPriorQueryV1(table_size=started.table_size, active_seat_ids=started.active_seat_ids,
            button_seat=started.button_seat, small_blind=started.small_blind, big_blind=started.big_blind,
            starting_stacks={seat: started.starting_stacks[seat] for seat in started.active_seat_ids},
            ante=started.ante, rake_bps=started.rake_bps, visible_blockers=(*observer_visible_cards, *public_cards))
        provider = default_seat_prior_provider()
        # Seed before replaying public boards.  Coverage depends on public table
        # facts, not on blockers, so this avoids constructing a discarded second
        # 1326-combo prior on every decision.
        initial_query = query.model_copy(update={"visible_blockers": observer_visible_cards})
        priors: dict[int, SeatPriorResultV1] = {seat: provider.get_prior(initial_query, seat) for seat in started.active_seat_ids}
        if any(not result.available for result in priors.values()):
            return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=False,
                unavailable_reason=f"{SeatBeliefUnavailableReason.PRIOR_UNAVAILABLE.value}:{priors[seat].unavailable_reason.value}") for seat in priors}
        initial_priors = priors
        snapshots = {seat: result.snapshot for seat, result in initial_priors.items()}
        assert all(snapshots.values())
        prior_snapshots = dict(snapshots)
        inactive_seats: set[int] = set()
        preflop_public_actions: list[ActionTakenPayloadV1] = []
        artifact_adapter = default_policy_artifact_range_adapter()
        board: list[Card] = []
        street_contributions = {seat: 0 for seat in started.active_seat_ids}
        stacks = dict(started.starting_stacks)
        pot = started.ante * len(started.active_seat_ids)
        for seat, prior in priors.items():
            forced = started.ante
            if prior.position is not None and prior.position.value == "small_blind":
                forced += started.small_blind
                street_contributions[seat] = started.small_blind
            elif prior.position is not None and prior.position.value == "big_blind":
                forced += started.big_blind
                street_contributions[seat] = started.big_blind
            stacks[seat] = max(0, stacks[seat] - forced)
            pot += forced - started.ante
        for event in prefix[1:]:
            payload = event.payload
            if isinstance(payload, BoardDealtPayloadV1):
                board.extend(payload.cards)
                street_contributions = {seat: 0 for seat in started.active_seat_ids}
                snapshots = {seat: _apply_blockers(snapshot, payload.cards, event.sequence, payload.street) for seat, snapshot in snapshots.items()}
            elif isinstance(payload, ActionTakenPayloadV1):
                if payload.action not in {SimulatorActionV1.FOLD, SimulatorActionV1.CALL, SimulatorActionV1.RAISE, SimulatorActionV1.CHECK, SimulatorActionV1.BET}:
                    return _unavailable_all(started, target, SeatBeliefUnavailableReason.OFF_TREE_UNSUPPORTED)
                position = priors[payload.actor_seat].position
                context = PublicActionContext(
                    board=tuple(board), pot_before=pot,
                    stack_before=stacks[payload.actor_seat],
                    position=position.value.lower() if position is not None else "unknown",
                )
                contribution = _incremental_contribution(
                    payload, stacks, street_contributions
                )
                likelihood_amount = contribution if payload.amount is not None else None
                cache_transition = event.sequence < target
                policy: PolicyResult | None = None
                policy_action: str | None = None
                fallback_reason: str | None = None
                if payload.street is Street.PREFLOP:
                    try:
                        policy, artifact_use = artifact_adapter.policy_for_action(
                            started,
                            tuple(preflop_public_actions),
                            payload,
                            tuple(snapshots[payload.actor_seat].combos),
                        )
                        policy_action = artifact_use.policy_action
                    except NoPolicyError as exc:
                        fallback_reason = str(exc)
                else:
                    fallback_reason = "street"
                if payload.action is SimulatorActionV1.FOLD:
                    inactive_seats.add(payload.actor_seat)
                    snapshots[payload.actor_seat] = _mark_inactive(
                        snapshots[payload.actor_seat], payload, event.sequence, context,
                        likelihood_amount, cache_transition, policy, policy_action,
                        fallback_reason,
                    )
                else:
                    snapshots[payload.actor_seat] = _apply_action(
                        snapshots[payload.actor_seat], payload, event.sequence, context,
                        likelihood_amount, cache_transition, policy, policy_action,
                        fallback_reason,
                    )
                pot = _advance_public_state(
                    payload, pot, stacks, street_contributions, contribution
                )
                if payload.street is Street.PREFLOP:
                    preflop_public_actions.append(payload)
        results = {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=True, prior=prior_snapshots[seat],
            current=snapshots[seat], provenance=_provenance_for(snapshots[seat], priors[seat]), inactive=seat in inactive_seats,
            approximate=True, approximation_reason=priors[seat].coverage.approximation_reason or "bounded_public_likelihood_v2") for seat in snapshots}
        immutable_results = _immutable_beliefs(results)
        _belief_cache_put(belief_cache_key, immutable_results)
        return dict(immutable_results)


def _policy_fingerprint(policy: PolicyResult | None) -> str | None:
    if policy is None:
        return None
    return next(
        (
            item.removeprefix("policy_fingerprint:")
            for item in policy.assumptions
            if item.startswith("policy_fingerprint:")
        ),
        None,
    )


def _action_likelihood(
    combo: str,
    action: ActionTakenPayloadV1,
    likelihood_amount: int | None,
    context: PublicActionContext,
    policy: PolicyResult | None,
    policy_action: str | None,
) -> Decimal:
    if policy is not None:
        if policy_action is None:
            return Decimal("0")
        return policy.frequencies.get(combo, {}).get(policy_action, Decimal("0"))
    return likelihood(combo, action.action, action.street, likelihood_amount, context)


def _provenance_for(
    snapshot: RangeBeliefSnapshot, prior: SeatPriorResultV1
) -> SeatBeliefProvenanceV1:
    update = snapshot.update
    fingerprint = _policy_fingerprint_from_assumptions(update.assumptions if update else ())
    if snapshot.source is PolicySource.PREFLOP_POLICY and fingerprint is not None:
        return SeatBeliefProvenanceV1(
            provider="riverline.policy_artifact_range",
            version=update.policy_version if update and update.policy_version else "unknown",
            artifact_fingerprint=fingerprint.removeprefix("sha256:"),
            policy_fingerprint=fingerprint,
            trust_level="policy_artifact",
            confidence=Decimal("0.70"),
            evidence_grade="B",
            coverage_status="covered",
            independent_marginal_only=True,
        )
    fallback = next(
        (
            item.removeprefix("policy_artifact_fallback:")
            for item in (update.assumptions if update else ())
            if item.startswith("policy_artifact_fallback:")
        ),
        None,
    )
    if fallback is None and prior.provenance is not None and prior.provenance.coverage_status == "fallback":
        fallback = "non_100bb" if prior.coverage.approximate or prior.coverage.effective_stack_bucket != "100bb" else "prior_not_covered"
    return SeatBeliefProvenanceV1(
        coverage_status="fallback",
        fallback_reason=fallback,
        independent_marginal_only=True,
    )


def _policy_fingerprint_from_assumptions(assumptions: tuple[str, ...]) -> str | None:
    return next(
        (
            item.removeprefix("policy_fingerprint:")
            for item in assumptions
            if item.startswith("policy_fingerprint:")
        ),
        None,
    )


def _apply_action(
    snapshot: RangeBeliefSnapshot,
    action: ActionTakenPayloadV1,
    sequence: int,
    context: PublicActionContext,
    likelihood_amount: int | None,
    cache_transition: bool,
    policy: PolicyResult | None = None,
    policy_action: str | None = None,
    fallback_reason: str | None = None,
) -> RangeBeliefSnapshot:
    policy_fingerprint = _policy_fingerprint(policy)
    cache_key = (
        id(snapshot), action.street, action.actor_seat, action.action,
        action.amount, action.amount_semantics, sequence, context,
        likelihood_amount, policy_fingerprint, policy.node if policy else None,
        policy_action,
    )
    if cache_transition:
        with _ACTION_CACHE_LOCK:
            cached = _ACTION_CACHE.get(cache_key)
            if cached is not None and cached[0] is snapshot:
                _ACTION_CACHE.move_to_end(cache_key)
                return cached[1]
    distribution_key = (
        id(snapshot), action.action, action.street,
        size_bucket(action.action, likelihood_amount, context.pot_before),
        context.board, context.position, spr_bucket(context.spr), policy_fingerprint,
        policy.node if policy else None, policy_action,
    )
    probe_key = next(iter(snapshot.combos))
    probe_likelihood = _action_likelihood(
        probe_key, action, likelihood_amount, context, policy, policy_action
    )
    with _ACTION_DISTRIBUTION_CACHE_LOCK:
        distribution = _ACTION_DISTRIBUTION_CACHE.get(distribution_key)
        if (
            distribution is not None
            and distribution[0] is snapshot
            and distribution[3] == probe_key
            and distribution[4] == probe_likelihood
        ):
            _ACTION_DISTRIBUTION_CACHE.move_to_end(distribution_key)
        else:
            distribution = None
    if distribution is None:
        weighted = {
            key: combo.reach * (
                probe_likelihood if key == probe_key else _action_likelihood(
                    key, action, likelihood_amount, context, policy, policy_action
                )
            )
            for key, combo in snapshot.combos.items()
        }
        mass = sum(weighted.values(), Decimal("0"))
        combos = _normalized_combos(weighted, mass)
        distribution = (
            snapshot, combos, mass, probe_key, probe_likelihood
        )
        with _ACTION_DISTRIBUTION_CACHE_LOCK:
            _ACTION_DISTRIBUTION_CACHE[distribution_key] = distribution
            _ACTION_DISTRIBUTION_CACHE.move_to_end(distribution_key)
            while (
                len(_ACTION_DISTRIBUTION_CACHE)
                > _ACTION_DISTRIBUTION_CACHE_MAX
            ):
                _ACTION_DISTRIBUTION_CACHE.popitem(last=False)
    else:
        combos = distribution[1]
        mass = distribution[2]
    reason = (
        f"policy_artifact:{policy.node}:{policy_action}"
        if policy is not None else change_reason(action.action, action.street, likelihood_amount, context)
    )
    result = RangeBeliefSnapshot.model_construct(snapshot_id=snapshot_id_for(snapshot.seat_id, action.street, sequence), seat_id=snapshot.seat_id,
        street=action.street, after_sequence=sequence,
        source=policy.source if policy is not None else PolicySource.HEURISTIC,
        confidence=policy.confidence if policy is not None else "heuristic",
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type=action.action.value, action_label=reason,
            observed_size=action.amount, mapped_size=likelihood_amount,
            policy_source=policy.source if policy is not None else PolicySource.HEURISTIC,
            node=policy.node if policy is not None else f"public-event/{reason}",
            policy_version=policy.version if policy is not None else _VERSION,
            assumptions=policy.assumptions if policy is not None else (
                "bounded heuristic likelihood", "actor-only update",
                f"size_bucket:{size_bucket(action.action, likelihood_amount, context.pot_before)}",
                f"street:{action.street.value}", f"position:{context.position}",
                f"spr_bucket:{spr_bucket(context.spr)}", "hand_features:made-hand/draw-aware",
                "not solver/GTO, player profile, or joint distribution",
                *((f"policy_artifact_fallback:{fallback_reason}",) if fallback_reason else ()),
            )))
    if cache_transition:
        with _ACTION_CACHE_LOCK:
            _ACTION_CACHE[cache_key] = (snapshot, result)
            _ACTION_CACHE.move_to_end(cache_key)
            while len(_ACTION_CACHE) > _ACTION_CACHE_MAX:
                _ACTION_CACHE.popitem(last=False)
    return result


def _mark_inactive(
    snapshot: RangeBeliefSnapshot,
    action: ActionTakenPayloadV1,
    sequence: int,
    context: PublicActionContext,
    likelihood_amount: int | None,
    cache_transition: bool,
    policy: PolicyResult | None = None,
    policy_action: str | None = None,
    fallback_reason: str | None = None,
) -> RangeBeliefSnapshot:
    """A fold updates the final marginal and removes the seat from future action."""
    folded = _apply_action(
        snapshot, action, sequence, context, likelihood_amount, cache_transition,
        policy, policy_action, fallback_reason,
    )
    cache_key = id(folded)
    if cache_transition:
        with _INACTIVE_CACHE_LOCK:
            cached = _INACTIVE_CACHE.get(cache_key)
            if cached is not None and cached[0] is folded:
                _INACTIVE_CACHE.move_to_end(cache_key)
                return cached[1]
    inactive = folded.model_copy(
        update={
            "update": folded.update.model_copy(
                update={
                    "assumptions": (
                        *folded.update.assumptions,
                        "folded seat is inactive; final public-action belief remains replayable",
                    )
                }
            )
        }
    )
    if cache_transition:
        with _INACTIVE_CACHE_LOCK:
            _INACTIVE_CACHE[cache_key] = (folded, inactive)
            _INACTIVE_CACHE.move_to_end(cache_key)
            while len(_INACTIVE_CACHE) > _INACTIVE_CACHE_MAX:
                _INACTIVE_CACHE.popitem(last=False)
    return inactive


def _apply_blockers(snapshot: RangeBeliefSnapshot, cards: tuple[Card, ...], sequence: int, street: Street) -> RangeBeliefSnapshot:
    cache_key = (id(snapshot), cards, sequence, street)
    with _BLOCKER_CACHE_LOCK:
        cached = _BLOCKER_CACHE.get(cache_key)
        if cached is not None and cached[0] is snapshot:
            _BLOCKER_CACHE.move_to_end(cache_key)
            return cached[1]
    kept = {key: combo for key, combo in snapshot.combos.items() if not combo_overlaps(key, set(cards))}
    mass = sum((combo.reach for combo in kept.values()), Decimal("0"))
    combos = _normalized_combos({key: combo.reach for key, combo in kept.items()}, mass)
    result = RangeBeliefSnapshot.model_construct(snapshot_id=snapshot_id_for(snapshot.seat_id, street, sequence), seat_id=snapshot.seat_id,
        street=street, after_sequence=sequence, source=snapshot.source, confidence=snapshot.confidence,
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type="public_board", policy_source=snapshot.source, node="public-event/board", policy_version=_VERSION))
    with _BLOCKER_CACHE_LOCK:
        _BLOCKER_CACHE[cache_key] = (snapshot, result)
        _BLOCKER_CACHE.move_to_end(cache_key)
        while len(_BLOCKER_CACHE) > _BLOCKER_CACHE_MAX:
            _BLOCKER_CACHE.popitem(last=False)
    return result


def _normalized_combos(weights: dict[str, Decimal], mass: Decimal) -> dict[str, RangeBeliefCombo]:
    keys = tuple(sorted(weights))
    probabilities = {key: weights[key] / mass for key in keys[:-1]}
    probabilities[keys[-1]] = Decimal("1") - sum(probabilities.values(), Decimal("0"))
    return _ImmutableDict({
        key: _ImmutableRangeBeliefCombo.model_construct(
            combo=key, reach=weights[key], probability=probabilities[key]
        )
        for key in keys
    })


def _advance_public_state(
    action: ActionTakenPayloadV1,
    pot: int,
    stacks: dict[int, int],
    street_contributions: dict[int, int],
    contribution: int,
) -> int:
    stacks[action.actor_seat] -= contribution
    street_contributions[action.actor_seat] += contribution
    return pot + contribution


def _incremental_contribution(
    action: ActionTakenPayloadV1,
    stacks: dict[int, int],
    street_contributions: dict[int, int],
) -> int:
    amount = action.amount or 0
    if action.amount_semantics is AmountSemanticsV1.TO:
        contribution = max(0, amount - street_contributions[action.actor_seat])
    elif action.amount_semantics in {AmountSemanticsV1.BY, AmountSemanticsV1.COST}:
        contribution = amount
    else:
        contribution = 0
    return min(contribution, stacks[action.actor_seat])


def _belief_cache_key(
    started: HandStartedPayloadV1,
    prefix: tuple[HandEventV1, ...],
    observer_visible_cards: tuple[Card, ...],
    target: int,
) -> tuple[object, ...]:
    artifact = default_policy_artifact_range_adapter()
    public_payloads: list[tuple[object, ...]] = []
    for event in prefix[1:]:
        payload = event.payload
        if isinstance(payload, ActionTakenPayloadV1):
            public_payloads.append((
                "action", event.sequence, payload.street.value, payload.actor_seat,
                payload.action.value, payload.amount, payload.amount_semantics.value,
            ))
        elif isinstance(payload, BoardDealtPayloadV1):
            public_payloads.append((
                "board", event.sequence, payload.street.value, payload.cards,
            ))
    return (
        "public-belief-v2", artifact.fingerprint, artifact.version, target,
        tuple(sorted(observer_visible_cards)),
        started.table_size, started.button_seat, started.small_blind,
        started.big_blind, started.ante, started.rake_bps,
        started.active_seat_ids, tuple(sorted(started.starting_stacks.items())),
        tuple(public_payloads),
    )


def _belief_cache_get(
    key: tuple[object, ...],
) -> dict[int, SeatBeliefResultV1] | None:
    with _BELIEF_CACHE_LOCK:
        cached = _BELIEF_CACHE.get(key)
        if cached is None:
            return None
        _BELIEF_CACHE.move_to_end(key)
        return dict(cached)


def _belief_cache_put(
    key: tuple[object, ...], results: dict[int, SeatBeliefResultV1]
) -> None:
    with _BELIEF_CACHE_LOCK:
        _BELIEF_CACHE[key] = dict(results)
        _BELIEF_CACHE.move_to_end(key)
        while len(_BELIEF_CACHE) > _BELIEF_CACHE_MAX:
            _BELIEF_CACHE.popitem(last=False)


def _immutable_beliefs(
    results: dict[int, SeatBeliefResultV1],
) -> dict[int, SeatBeliefResultV1]:
    immutable: dict[int, SeatBeliefResultV1] = {}
    for seat, result in results.items():
        values = {
            name: getattr(result, name)
            for name in SeatBeliefResultV1.model_fields
        }
        values["prior"] = _immutable_snapshot(result.prior, cache_value=True)
        values["current"] = _immutable_snapshot(
            result.current,
            cache_value=(
                result.current is not None
                and result.current.after_sequence < result.after_sequence
            ),
        )
        if result.provenance is not None:
            values["provenance"] = _ImmutableSeatBeliefProvenance.model_construct(
                **{
                    name: getattr(result.provenance, name)
                    for name in SeatBeliefProvenanceV1.model_fields
                }
            )
        immutable[seat] = _ImmutableSeatBeliefResult.model_construct(
            **values
        )
    return immutable


def _immutable_snapshot(
    snapshot: RangeBeliefSnapshot | None,
    *,
    cache_value: bool,
) -> _ImmutableRangeBeliefSnapshot | None:
    if snapshot is None:
        return None
    cache_key = id(snapshot)
    if cache_value:
        with _IMMUTABLE_SNAPSHOT_CACHE_LOCK:
            cached = _IMMUTABLE_SNAPSHOT_CACHE.get(cache_key)
            if cached is not None and cached[0] is snapshot:
                _IMMUTABLE_SNAPSHOT_CACHE.move_to_end(cache_key)
                return cached[1]
    values = {
        name: getattr(snapshot, name)
        for name in RangeBeliefSnapshot.model_fields
    }
    if isinstance(snapshot.combos, _ImmutableDict):
        values["combos"] = snapshot.combos
    else:
        values["combos"] = _ImmutableDict({
            key: (
                combo if isinstance(combo, _ImmutableRangeBeliefCombo)
                else _ImmutableRangeBeliefCombo.model_construct(
                    combo=combo.combo, reach=combo.reach,
                    probability=combo.probability,
                )
            )
            for key, combo in snapshot.combos.items()
        })
    if snapshot.update is not None:
        values["update"] = _ImmutableRangeUpdateMetadata.model_construct(
            **{
                name: getattr(snapshot.update, name)
                for name in RangeUpdateMetadata.model_fields
            }
        )
    immutable = _ImmutableRangeBeliefSnapshot.model_construct(**values)
    if cache_value:
        with _IMMUTABLE_SNAPSHOT_CACHE_LOCK:
            _IMMUTABLE_SNAPSHOT_CACHE[cache_key] = (snapshot, immutable)
            _IMMUTABLE_SNAPSHOT_CACHE.move_to_end(cache_key)
            while len(_IMMUTABLE_SNAPSHOT_CACHE) > _IMMUTABLE_SNAPSHOT_CACHE_MAX:
                _IMMUTABLE_SNAPSHOT_CACHE.popitem(last=False)
    return immutable


def _unavailable_all(started: object, target: int, reason: SeatBeliefUnavailableReason) -> dict[int, SeatBeliefResultV1]:
    seats = started.active_seat_ids if isinstance(started, HandStartedPayloadV1) else ()
    return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=False, unavailable_reason=reason.value) for seat in seats}
