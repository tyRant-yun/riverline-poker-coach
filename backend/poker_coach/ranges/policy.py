"""Policy abstraction: per-combo action frequencies and action mapping.

``ActionPolicyProvider`` decouples the belief engine from any concrete
strategy source (solver sidecar, fixture, future preflop dataset). Providers
return a ``PolicyResult``: a full combo x action frequency table.

Solver action labels are parsed explicitly (``Bet(250)``, ``Raise(625)``,
``AllIn(9750)``, ``Check``, ``Call``, ``Fold``) — never string-contains
heuristics. Off-tree observed sizes map to the nearest policy size and are
flagged as approximations; no interpolation is performed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Annotated, Protocol

from pydantic import Field, model_validator

from poker_coach.domain.models import ActionEvent, ActionType, DomainModel, ScenarioSpec

from .belief import InvalidPolicyError, PolicySource

_FREQUENCY_TOLERANCE = Decimal("0.000001")


class ActionMatchStatus(str, Enum):
    EXACT = "exact"
    NEAREST_SIZE = "nearest_size"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ActionMatch:
    """Result of mapping an observed action onto a policy's action set."""

    status: ActionMatchStatus
    policy_action: str
    observed_size: Decimal | None = None
    mapped_size: Decimal | None = None
    off_tree: bool = False


@dataclass(frozen=True)
class PolicyActionSpec:
    """A parsed policy action label: type plus embedded chip size."""

    label: str
    action_type: ActionType
    size: Decimal | None = None


_ACTION_TYPE_BY_LABEL = {
    "Check": ActionType.CHECK,
    "Call": ActionType.CALL,
    "Fold": ActionType.FOLD,
}


def parse_policy_action(label: str) -> PolicyActionSpec:
    """Parse a solver-style action label into an explicit spec.

    Supports ``Check``/``Call``/``Fold`` (no size) and
    ``Bet(<chips>)``/``Raise(<chips>)``/``AllIn(<chips>)``. Unknown shapes
    raise ``InvalidPolicyError`` instead of guessing.
    """
    normalized = label.strip()
    if normalized in _ACTION_TYPE_BY_LABEL:
        return PolicyActionSpec(label=normalized, action_type=_ACTION_TYPE_BY_LABEL[normalized])
    for prefix, action_type in (
        ("Bet", ActionType.BET),
        ("Raise", ActionType.RAISE_TO),
        ("AllIn", ActionType.ALL_IN),
    ):
        if normalized.startswith(prefix) and normalized[len(prefix) :].startswith("("):
            raw_size = normalized[len(prefix) + 1 : -1]
            try:
                size = Decimal(raw_size)
            except Exception as exc:  # Decimal supplies the detail
                raise InvalidPolicyError(f"invalid policy action size in {label!r}") from exc
            if size < 0:
                raise InvalidPolicyError(f"policy action size must be non-negative: {label!r}")
            return PolicyActionSpec(label=normalized, action_type=action_type, size=size)
    raise InvalidPolicyError(f"unsupported policy action label: {label!r}")


class PolicyResult(DomainModel):
    """Per-combo action frequency table from one policy source.

    ``likelihood_only`` marks partial policies (e.g. fixture tables that
    only supply the observed action's likelihood): each combo table may sum
    to anything in [0, 1]. Complete policies must cover every action and
    sum to ~1 per combo.

    ``reference_pot`` is the pot before the decision the policy applies to;
    it anchors chip-size fractions for off-tree matching.
    """

    source: PolicySource
    actions: tuple[str, ...]
    frequencies: dict[str, dict[str, Decimal]]
    likelihood_only: bool = False
    node: str | None = None
    version: str | None = None
    assumptions: tuple[str, ...] = ()
    reference_pot: Annotated[int, Field(ge=0)] | None = None
    confidence: str = "grounded"

    @model_validator(mode="after")
    def validate_frequencies(self) -> PolicyResult:
        action_set = set(self.actions)
        for combo, table in self.frequencies.items():
            if not table:
                raise InvalidPolicyError(f"combo {combo} has an empty frequency table")
            unknown = set(table) - action_set
            if unknown:
                raise InvalidPolicyError(
                    f"combo {combo} references actions outside the policy: {sorted(unknown)}"
                )
            for action, frequency in table.items():
                if frequency < 0 or frequency > 1:
                    raise InvalidPolicyError(
                        f"frequency {frequency} out of range for {combo} {action}"
                    )
            if not self.likelihood_only and set(table) != action_set:
                raise InvalidPolicyError(
                    f"combo {combo} must cover every policy action; missing "
                    f"{sorted(action_set - set(table))}"
                )
            if not self.likelihood_only:
                total = sum(table.values())
                if abs(total - Decimal("1")) > _FREQUENCY_TOLERANCE:
                    raise InvalidPolicyError(
                        f"combo {combo} frequencies sum to {total} (expected 1)"
                    )
        return self


class ActionPolicyProvider(Protocol):
    """Unified source of per-combo action frequencies at a node.

    Implementations decide which node applies for (seat, sequence) from the
    scenario's action history and raise ``NoPolicyError`` when they have no
    grounded frequencies for that node.
    """

    def get_action_frequencies(
        self,
        scenario: ScenarioSpec,
        seat_id: int,
        sequence: int,
        combos: tuple[str, ...],
    ) -> PolicyResult: ...


def resolve_action_match(
    observed: ActionEvent,
    policy: PolicyResult,
    *,
    pot_before: int | None,
) -> ActionMatch:
    """Map the observed action onto the policy's action set.

    Likelihood-only policies (fixtures) already target the observed action,
    so the single action column is used directly. Complete policies go
    through explicit type/size matching with off-tree nearest-size
    approximation (deterministic: ties resolve to the smaller size).
    """
    if policy.likelihood_only:
        return ActionMatch(
            status=ActionMatchStatus.EXACT,
            policy_action=policy.actions[0],
            off_tree=False,
        )
    return match_observed_action(
        observed,
        policy.actions,
        pot_before=pot_before,
        reference_pot=policy.reference_pot,
    )


def match_observed_action(
    observed: ActionEvent,
    policy_actions: tuple[str, ...],
    *,
    pot_before: int | None,
    reference_pot: int | None = None,
) -> ActionMatch:
    """Explicitly map an observed ActionEvent onto policy action labels."""
    specs = tuple(parse_policy_action(label) for label in policy_actions)
    family = _family_specs(specs, observed.action_type)
    if not family:
        return ActionMatch(
            status=ActionMatchStatus.UNSUPPORTED,
            policy_action="",
            off_tree=False,
        )
    if len(family) == 1 and family[0].size is None:
        return ActionMatch(
            status=ActionMatchStatus.EXACT,
            policy_action=family[0].label,
            off_tree=False,
        )
    sized = tuple(spec for spec in family if spec.size is not None)
    if not sized:
        return ActionMatch(
            status=ActionMatchStatus.UNSUPPORTED,
            policy_action="",
            off_tree=False,
        )
    observed_size = _observed_size(observed, pot_before)
    if observed_size is None or reference_pot is None or reference_pot <= 0:
        # No consistent pot context: nearest chip amount (deterministic).
        observed_chips = Decimal(observed.amount or 0)
        for spec in sorted(sized, key=lambda item: item.size):
            if spec.size == observed_chips:
                return ActionMatch(
                    status=ActionMatchStatus.EXACT,
                    policy_action=spec.label,
                    observed_size=observed_chips,
                    mapped_size=spec.size,
                    off_tree=False,
                )
        chosen = min(sized, key=lambda spec: (abs(spec.size - observed_chips), spec.size))
        return ActionMatch(
            status=ActionMatchStatus.NEAREST_SIZE,
            policy_action=chosen.label,
            observed_size=observed_chips,
            mapped_size=chosen.size,
            off_tree=True,
        )
    # Exact size match wins (ties resolve to the smaller size, documented in
    # tests); otherwise nearest pot fraction — never interpolate.
    for spec in sorted(sized, key=lambda item: item.size):
        if abs(_policy_fraction(spec, reference_pot) - observed_size) <= Decimal("0.000001"):
            return ActionMatch(
                status=ActionMatchStatus.EXACT,
                policy_action=spec.label,
                off_tree=False,
            )
    chosen = min(
        sized,
        key=lambda spec: (
            abs(_policy_fraction(spec, reference_pot) - observed_size),
            spec.size,
        ),
    )
    return ActionMatch(
        status=ActionMatchStatus.NEAREST_SIZE,
        policy_action=chosen.label,
        observed_size=observed_size,
        mapped_size=_policy_fraction(chosen, reference_pot),
        off_tree=True,
    )


def _family_specs(
    specs: tuple[PolicyActionSpec, ...], action_type: ActionType
) -> tuple[PolicyActionSpec, ...]:
    """Policy specs whose family can satisfy the observed action type."""
    if action_type in (ActionType.CHECK, ActionType.CALL, ActionType.FOLD):
        return tuple(spec for spec in specs if spec.action_type is action_type)
    if action_type is ActionType.BET:
        return tuple(spec for spec in specs if spec.action_type is ActionType.BET)
    if action_type is ActionType.ALL_IN:
        return tuple(spec for spec in specs if spec.action_type is ActionType.ALL_IN)
    if action_type is ActionType.RAISE_TO:
        raises = tuple(spec for spec in specs if spec.action_type is ActionType.RAISE_TO)
        if raises:
            return raises
        return tuple(spec for spec in specs if spec.action_type is ActionType.ALL_IN)
    return ()


def _observed_size(observed: ActionEvent, pot_before: int | None) -> Decimal | None:
    if observed.amount is None:
        return None
    if pot_before is not None and pot_before > 0:
        return Decimal(observed.amount) / Decimal(pot_before)
    return None


def _policy_fraction(spec: PolicyActionSpec, reference_pot: int) -> Decimal:
    if spec.size is None:
        return Decimal("0")
    return spec.size / Decimal(reference_pot)
