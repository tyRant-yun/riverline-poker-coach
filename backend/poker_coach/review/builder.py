"""Build decision snapshots through the project-owned PokerKit replay seam."""

from __future__ import annotations

from poker_coach.domain.models import ActionType, DecisionPoint, ScenarioSpec
from poker_coach.rules import PokerKitAdapter

from .models import DecisionSnapshot


_PLAYER_DECISION_ACTIONS = frozenset(
    {
        ActionType.CHECK,
        ActionType.CALL,
        ActionType.BET,
        ActionType.RAISE_TO,
        ActionType.FOLD,
        ActionType.ALL_IN,
    }
)


def build_decision_snapshots(
    scenario: ScenarioSpec,
    *,
    adapter: PokerKitAdapter | None = None,
) -> tuple[DecisionSnapshot, ...]:
    """Return one ordered, pre-action snapshot for each real player action.

    A full replay validates the complete imported hand (including every
    actor and action amount).  Each decision then replays only its preceding
    prefix, so future deal events and player actions cannot enter the state
    exposed to that decision.
    """

    rules = adapter or PokerKitAdapter()
    rules.replay(scenario)

    snapshots: list[DecisionSnapshot] = []
    for event in scenario.action_history:
        if event.action_type not in _PLAYER_DECISION_ACTIONS:
            continue

        decision_sequence = event.sequence - 1
        prefix = scenario.model_copy(
            update={
                "action_history": scenario.action_history[:decision_sequence],
                "decision_point": DecisionPoint(
                    street=event.street,
                    actor_seat=event.actor_seat,
                    after_sequence=decision_sequence,
                ),
            }
        )
        state_before_action = rules.replay(prefix).final_state
        snapshots.append(
            DecisionSnapshot(
                action_id=event.action_id,
                event_sequence=event.sequence,
                decision_sequence=decision_sequence,
                street=state_before_action.street,
                actor_seat=event.actor_seat,
                state_before_action=state_before_action,
            )
        )

    return tuple(snapshots)
