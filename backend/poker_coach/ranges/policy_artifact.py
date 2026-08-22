"""Public-range adapter for the verified R9 preflop policy artifact.

The adapter deliberately consumes only ``HandStarted`` and public preflop
actions.  It never creates an ``ObservationV1`` (which would require a
player's hole cards); each candidate combo is mapped to its public 169-class
and receives the exact frequency from the same immutable artifact used by the
mixed Bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from poker_coach.domain.models import Card
from poker_coach.ranges.belief import NoPolicyError, PolicySource
from poker_coach.ranges.policy import PolicyResult
from poker_coach.simulator.contracts import (
    ActionTakenPayloadV1,
    AmountSemanticsV1,
    HandStartedPayloadV1,
    SimulatorActionV1,
)
from poker_coach.theory.policy_artifact import (
    PolicyArtifact,
    default_preflop_artifact,
    hand_class_from_cards,
)


@dataclass(frozen=True)
class ArtifactPolicyUse:
    """The exact public artifact node selected for one observed action."""

    node_id: str
    action_prefix: str
    policy_action: str


class PolicyArtifactRangeAdapter:
    """Expose B-grade range likelihoods without private-card access."""

    def __init__(self, artifact: PolicyArtifact | None = None) -> None:
        self.artifact = artifact or default_preflop_artifact()

    @property
    def fingerprint(self) -> str:
        return self.artifact.fingerprint

    @property
    def version(self) -> str:
        return self.artifact.version

    def coverage_reason(self, started: HandStartedPayloadV1) -> str | None:
        if started.table_size != 6 or len(started.active_seat_ids) != 6:
            return "multiway_or_table_size"
        if started.ante:
            return "ante"
        if started.rake_bps:
            return "rake"
        expected_stack = started.big_blind * 100
        if any(started.starting_stacks[seat] != expected_stack for seat in started.active_seat_ids):
            return "non_100bb"
        return None

    def coverage_reason_for_query(self, query: object) -> str | None:
        """Apply the identical public coverage rule to a prior query.

        ``SeatPriorQueryV1`` deliberately stays free of simulator contracts;
        duck typing keeps that range-local input boundary intact.
        """
        table_size = getattr(query, "table_size")
        active = getattr(query, "active_seat_ids")
        if table_size != 6 or len(active) != 6:
            return "multiway_or_table_size"
        if getattr(query, "street").value != "preflop" or getattr(query, "after_sequence") != 0:
            return "node"
        if getattr(query, "ante"):
            return "ante"
        if getattr(query, "rake_bps"):
            return "rake"
        big_blind = getattr(query, "big_blind")
        stacks = getattr(query, "starting_stacks")
        if any(stacks[seat] != big_blind * 100 for seat in active):
            return "non_100bb"
        return None

    def policy_for_action(
        self,
        started: HandStartedPayloadV1,
        prior_preflop_actions: tuple[ActionTakenPayloadV1, ...],
        action: ActionTakenPayloadV1,
        combos: tuple[str, ...],
    ) -> tuple[PolicyResult, ArtifactPolicyUse]:
        reason = self.coverage_reason(started)
        if reason is not None:
            raise NoPolicyError(f"policy_artifact_fallback:{reason}")
        if action.street.value != "preflop":
            raise NoPolicyError("policy_artifact_fallback:street")
        action_prefix = _action_prefix(prior_preflop_actions, started.big_blind)
        if action_prefix is None:
            raise NoPolicyError("policy_artifact_fallback:tree_or_action_prefix")
        position = _artifact_position(action.actor_seat, started.button_seat)
        node = next(
            (
                item
                for item in self.artifact.payload["nodes"]
                if item["actionPrefix"] == action_prefix
                and item["actorPosition"] == position
                and item["treeFingerprint"] == self.artifact.coverage["treeVersion"]
            ),
            None,
        )
        if node is None:
            raise NoPolicyError("policy_artifact_fallback:tree_or_position_not_covered")
        actions = _policy_actions(node, started.big_blind)
        observed_label = _observed_label(action, actions)
        if observed_label is None:
            raise NoPolicyError("policy_artifact_fallback:action_or_size_not_covered")
        frequencies = _frequency_table(
            self.fingerprint,
            str(node["nodeId"]),
            action_prefix,
            observed_label,
            tuple(sorted(combos)),
            tuple(actions.items()),
            tuple((item["handClass"], tuple(item["frequencies"].items())) for item in node["classFrequencies"]),
        )
        return (
            PolicyResult(
                source=PolicySource.PREFLOP_POLICY,
                actions=tuple(actions.values()),
                frequencies=frequencies,
                node=str(node["nodeId"]),
                version=self.version,
                confidence="policy_artifact_b",
                assumptions=(
                    "R9-02 verified first-party preflop PolicyArtifact",
                    "evidence_grade:B",
                    "coverage_status:covered",
                    f"policy_fingerprint:{self.fingerprint}",
                    f"policy_version:{self.version}",
                    f"action_prefix:{action_prefix}",
                    "independent_marginal_only:true",
                    "public-action likelihood; not joint/player truth",
                ),
            ),
            ArtifactPolicyUse(str(node["nodeId"]), action_prefix, observed_label),
        )


@lru_cache(maxsize=1)
def default_policy_artifact_range_adapter() -> PolicyArtifactRangeAdapter:
    return PolicyArtifactRangeAdapter()


def _action_prefix(
    actions: tuple[ActionTakenPayloadV1, ...], big_blind: int
) -> str | None:
    raises = tuple(item for item in actions if item.action is SimulatorActionV1.RAISE)
    calls = tuple(item for item in actions if item.action is SimulatorActionV1.CALL)
    if not raises and not calls:
        return "rfi"
    if (
        len(raises) == 1
        and not calls
        and raises[0].amount_semantics is AmountSemanticsV1.TO
        and raises[0].amount == int(Decimal("2.5") * big_blind)
    ):
        return "vs_single_rfi"
    return None


def _artifact_position(seat: int, button: int) -> str:
    return ("BTN", "SB", "BB", "UTG", "HJ", "CO")[(seat - button) % 6]


def _policy_actions(node: object, big_blind: int) -> dict[str, str]:
    assert isinstance(node, dict) or hasattr(node, "__getitem__")
    raise_to = int(Decimal(str(node["legalSizing"]["raise_to"]["amountBb"])) * big_blind)
    sample = node["classFrequencies"][0]["frequencies"]
    labels = {"fold": "Fold", "call": "Call", "raise_to": f"Raise({raise_to})"}
    return {name: labels[name] for name in sample}


def _observed_label(action: ActionTakenPayloadV1, actions: dict[str, str]) -> str | None:
    if action.action is SimulatorActionV1.FOLD:
        return actions.get("fold")
    if action.action is SimulatorActionV1.CALL:
        return actions.get("call")
    if action.action is SimulatorActionV1.RAISE and action.amount_semantics is AmountSemanticsV1.TO:
        label = actions.get("raise_to")
        if label == f"Raise({action.amount})":
            return label
    return None


@lru_cache(maxsize=64)
def _frequency_table(
    fingerprint: str,
    node_id: str,
    action_prefix: str,
    observed_label: str,
    combos: tuple[str, ...],
    actions: tuple[tuple[str, str], ...],
    class_frequencies: tuple[tuple[str, tuple[tuple[str, float], ...]], ...],
) -> dict[str, dict[str, Decimal]]:
    """Bounded cache explicitly keyed by fingerprint, node, and action."""
    del fingerprint, node_id, action_prefix, observed_label
    action_labels = dict(actions)
    by_class = {hand_class: dict(frequencies) for hand_class, frequencies in class_frequencies}
    return {
        combo: {
            label: Decimal(str(by_class[hand_class_from_cards((combo[:2], combo[2:]))][action_name]))
            for action_name, label in action_labels.items()
        }
        for combo in combos
    }
