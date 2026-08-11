"""Core Bayesian range update: prior reach x action likelihood, normalize.

The update is a pure function over combo-level reach:

    newReach(h)   = oldReach(h) * P(observedAction | h)
    belief(h)     = newReach(h) / sum(newReach over legal combos)

A zero total reach is an explicit error — never a silent uniform fallback.
Dead cards (other seats' known hole cards plus the board visible at the
transition) eliminate combos before updating and are re-applied on every
transition (street deals renormalize the belief).
"""

from __future__ import annotations

from decimal import Decimal

from poker_coach.analysis.range_analysis import expand_range
from poker_coach.domain.models import ActionEvent, Card, RangeSpec, Street

from .belief import (
    NoPriorRangeError,
    PolicySource,
    RangeBeliefCombo,
    RangeBeliefSnapshot,
    RangeUpdateMetadata,
    UnsupportedActionError,
    ZeroProbabilityActionError,
    combo_key,
    combo_overlaps,
    snapshot_id_for,
)
from .policy import (
    ActionMatchStatus,
    PolicyResult,
    resolve_action_match,
)

# Actions that carry a strategy likelihood in a policy. Blinds, deals and
# settlements never update a player's range belief.
POLICY_ACTION_TYPES = frozenset(
    {
        "check",
        "call",
        "bet",
        "raise_to",
        "all_in",
        "fold",
    }
)


def snapshot_from_range(
    range_spec: RangeSpec,
    *,
    seat_id: int,
    street: Street,
    after_sequence: int,
    dead_cards: tuple[Card, ...] = (),
) -> RangeBeliefSnapshot:
    """Build the initial prior snapshot from a RangeSpec (manual source)."""
    expanded = expand_range(range_spec, dead_cards=dead_cards)
    if not expanded:
        raise NoPriorRangeError(
            "prior range has no playable combos after dead-card filtering"
        )
    total = sum((combo.weight for combo in expanded), Decimal("0"))
    if total <= 0:
        raise NoPriorRangeError("prior range has zero total weight")
    combos: dict[str, RangeBeliefCombo] = {}
    for weighted in expanded:
        key = combo_key(weighted.cards)
        combos[key] = RangeBeliefCombo(
            combo=key,
            reach=weighted.weight,
            probability=weighted.weight / total,
        )
    return RangeBeliefSnapshot(
        snapshot_id=snapshot_id_for(seat_id, street, after_sequence),
        seat_id=seat_id,
        street=street,
        after_sequence=after_sequence,
        source=PolicySource.MANUAL,
        confidence="manual",
        prior_mass=total,
        retained_mass=total,
        combos=combos,
    )


def apply_dead_cards(
    snapshot: RangeBeliefSnapshot,
    dead_cards: tuple[Card, ...],
    *,
    street: Street,
    after_sequence: int,
    action_type: str = "deal",
    action_label: str | None = None,
) -> RangeBeliefSnapshot:
    """Remove combos overlapping new dead cards and renormalize.

    Used for street deals (flop/turn/river) and any other public-card
    change. Keeps the policy source of the parent snapshot — the deal
    itself is not a policy update.
    """
    dead = set(dead_cards)
    surviving = {
        key: combo
        for key, combo in snapshot.combos.items()
        if not combo_overlaps(key, dead)
    }
    if not surviving:
        raise ZeroProbabilityActionError(
            "all combos are eliminated by the new dead cards"
        )
    retained = sum((combo.reach for combo in surviving.values()), Decimal("0"))
    if retained <= 0:
        raise ZeroProbabilityActionError(
            "all combos are eliminated by the new dead cards"
        )
    renormalized = {
        key: RangeBeliefCombo(
            combo=key,
            reach=combo.reach,
            probability=combo.reach / retained,
        )
        for key, combo in surviving.items()
    }
    return RangeBeliefSnapshot(
        snapshot_id=snapshot_id_for(snapshot.seat_id, street, after_sequence),
        seat_id=snapshot.seat_id,
        street=street,
        after_sequence=after_sequence,
        source=snapshot.source,
        confidence=snapshot.confidence,
        prior_mass=snapshot.retained_mass,
        retained_mass=retained,
        combos=renormalized,
        parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(
            action_type=action_type,
            action_label=action_label,
            policy_source=None,
            node=None,
        ),
    )


def update_range_belief(
    prior: RangeBeliefSnapshot,
    observed: ActionEvent,
    policy: PolicyResult,
    *,
    pot_before: int | None = None,
    dead_cards: tuple[Card, ...] = (),
) -> RangeBeliefSnapshot:
    """Apply one observed action to the prior belief via policy likelihoods.

    Raises:
        UnsupportedActionError: observed action type has no policy family.
        ZeroProbabilityActionError: observed action has zero likelihood for
            every surviving combo (no uniform fallback).
    """
    if not prior.combos:
        raise NoPriorRangeError("prior snapshot has no combos to update")

    match = resolve_action_match(observed, policy, pot_before=pot_before)
    if match.status is ActionMatchStatus.UNSUPPORTED:
        raise UnsupportedActionError(
            f"observed {observed.action_type.value} has no matching action in "
            f"policy {{{', '.join(policy.actions)}}}"
        )

    dead = set(dead_cards)
    new_reach: dict[str, Decimal] = {}
    for key, combo in prior.combos.items():
        if combo_overlaps(key, dead):
            continue
        table = policy.frequencies.get(key)
        likelihood = table.get(match.policy_action) if table else Decimal("0")
        new_reach[key] = combo.reach * likelihood

    retained = sum(new_reach.values(), Decimal("0"))
    if retained <= 0:
        raise ZeroProbabilityActionError(
            "Observed action has zero probability under the supplied policy."
        )

    surviving_prior_mass = sum(
        (combo.reach for key, combo in prior.combos.items() if key in new_reach),
        Decimal("0"),
    )
    # Zero likelihood removes the combo from the belief entirely.
    renormalized = {
        key: RangeBeliefCombo(
            combo=key,
            reach=reach,
            probability=reach / retained,
        )
        for key, reach in new_reach.items()
        if reach > 0
    }
    return RangeBeliefSnapshot(
        snapshot_id=snapshot_id_for(prior.seat_id, observed.street, observed.sequence),
        seat_id=prior.seat_id,
        street=observed.street,
        after_sequence=observed.sequence,
        source=policy.source,
        confidence=policy.confidence,
        prior_mass=surviving_prior_mass,
        retained_mass=retained,
        combos=renormalized,
        parent_snapshot_id=prior.snapshot_id,
        update=RangeUpdateMetadata(
            action_type=observed.action_type.value,
            action_label=match.policy_action,
            observed_size=match.observed_size,
            mapped_size=match.mapped_size,
            off_tree=match.off_tree,
            policy_source=policy.source,
            node=policy.node,
            policy_version=policy.version,
            assumptions=policy.assumptions,
        ),
    )
