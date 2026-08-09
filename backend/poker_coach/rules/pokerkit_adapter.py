"""PokerKit 0.7.4 adapter.

Only this module imports PokerKit. Callers receive project-owned Pydantic
models and a project-owned error type instead of upstream state objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version
from typing import Any

from poker_coach.domain.models import (
    ActionEvent,
    ActionType,
    LegalActions,
    ReplayResult,
    ScenarioSpec,
    StateSnapshot,
    Street,
)


class ReplayError(ValueError):
    """A stable error raised when an event cannot be replayed legally."""

    def __init__(self, code: str, message: str, sequence: int | None = None):
        self.code = code
        self.sequence = sequence
        prefix = f"event {sequence}: " if sequence is not None else ""
        super().__init__(f"{prefix}{message}")


@dataclass(frozen=True)
class _SeatMap:
    seat_to_player: dict[int, int]
    player_to_seat: dict[int, int]
    big_blind_seat: int
    button_seat: int


class PokerKitAdapter:
    """Translate ScenarioSpec events to and from one PokerKit state."""

    engine_name = "pokerkit"
    engine_version = package_version("pokerkit")

    def replay(self, scenario: ScenarioSpec) -> ReplayResult:
        if scenario.rake_config.enabled:
            raise ReplayError(
                "rake_not_supported",
                "rake is reserved in the data model but not enabled in the MVP adapter",
            )

        state, seat_map = self._create_initial_state(scenario)
        snapshots = [self._snapshot(state, seat_map)]
        events = scenario.action_history
        cursor = self._consume_forced_blind_events(events, scenario, seat_map)

        for event in events[cursor:]:
            self._apply_event(state, event, scenario, seat_map)
            snapshots.append(self._snapshot(state, seat_map))

        final_state = snapshots[-1]
        return ReplayResult(
            rules_engine=self.engine_name,
            rules_engine_version=self.engine_version,
            snapshots=tuple(snapshots),
            final_state=final_state,
        )

    def legal_actions(self, scenario: ScenarioSpec) -> LegalActions:
        return self.replay(scenario).final_state.legal_actions

    def _create_initial_state(self, scenario: ScenarioSpec) -> tuple[Any, _SeatMap]:
        from pokerkit import Automation, Mode, NoLimitTexasHoldem

        big_blind_seat = next(
            seat.seat_id for seat in scenario.seats if seat.position.value == "big_blind"
        )
        button_seat = scenario.button_seat
        seat_map = _SeatMap(
            seat_to_player={big_blind_seat: 0, button_seat: 1},
            player_to_seat={0: big_blind_seat, 1: button_seat},
            big_blind_seat=big_blind_seat,
            button_seat=button_seat,
        )
        stacks_by_seat = {seat.seat_id: seat.starting_stack for seat in scenario.seats}
        starting_stacks = (stacks_by_seat[big_blind_seat], stacks_by_seat[button_seat])
        automations = [Automation.BET_COLLECTION]
        if scenario.ante:
            automations.insert(0, Automation.ANTE_POSTING)
        state = NoLimitTexasHoldem.create_state(
            tuple(automations),
            False,
            scenario.ante,
            (scenario.small_blind, scenario.big_blind),
            scenario.big_blind,
            starting_stacks,
            2,
            mode=Mode.CASH_GAME,
        )

        # PokerKit's two-player ordering is BB at index 0 and BTN/SB at index 1.
        state.post_blind_or_straddle(0)
        state.post_blind_or_straddle(1)
        hole_cards = "".join(scenario.hero_hole_cards)
        hero_player = seat_map.seat_to_player[scenario.hero_seat]
        for player_index in (0, 1):
            cards = hole_cards if player_index == hero_player else "????"
            state.deal_hole(cards, player_index=player_index)
        return state, seat_map

    def _consume_forced_blind_events(
        self,
        events: tuple[ActionEvent, ...],
        scenario: ScenarioSpec,
        seat_map: _SeatMap,
    ) -> int:
        expected = (
            (seat_map.big_blind_seat, scenario.big_blind),
            (seat_map.button_seat, scenario.small_blind),
        )
        cursor = 0
        for event in events:
            if event.action_type is not ActionType.POST_BLIND:
                break
            if cursor >= len(expected):
                raise ReplayError("duplicate_blind", "more than two blind events", event.sequence)
            expected_seat, expected_amount = expected[cursor]
            if event.actor_seat != expected_seat or event.amount != expected_amount:
                raise ReplayError(
                    "blind_mismatch",
                    f"expected seat {expected_seat} to post {expected_amount}",
                    event.sequence,
                )
            cursor += 1
        if any(event.action_type is ActionType.POST_BLIND for event in events[cursor:]):
            raise ReplayError(
                "blind_order",
                "blind events must be the first events and appear at most once per seat",
            )
        return cursor

    def _apply_event(
        self,
        state: Any,
        event: ActionEvent,
        scenario: ScenarioSpec,
        seat_map: _SeatMap,
    ) -> None:
        if event.action_type in {
            ActionType.DEAL_FLOP,
            ActionType.DEAL_TURN,
            ActionType.DEAL_RIVER,
        }:
            self._deal_board(state, event, scenario)
            return

        player_index = self._require_actor(state, event, seat_map)
        self._validate_before_values(state, event, player_index)

        try:
            if event.action_type is ActionType.CHECK:
                if state.checking_or_calling_amount != 0:
                    raise ReplayError("check_not_legal", "a call is required, not a check", event.sequence)
                state.check_or_call()
            elif event.action_type is ActionType.CALL:
                if event.amount != state.checking_or_calling_amount:
                    raise ReplayError(
                        "call_amount_mismatch",
                        f"expected call amount {state.checking_or_calling_amount}",
                        event.sequence,
                    )
                state.check_or_call()
            elif event.action_type in {ActionType.BET, ActionType.RAISE_TO, ActionType.ALL_IN}:
                self._validate_completion_amount(state, event)
                state.complete_bet_or_raise_to(event.amount)
            elif event.action_type is ActionType.FOLD:
                state.fold()
            elif event.action_type is ActionType.SHOWDOWN:
                state.show_or_muck_hole_cards(True, player_index=player_index)
            elif event.action_type is ActionType.AWARD_POT:
                self._award_pot(state, player_index)
            else:
                raise ReplayError(
                    "unsupported_action",
                    f"action {event.action_type.value} is not supported by the replay adapter",
                    event.sequence,
                )
        except ReplayError:
            raise
        except Exception as exc:
            raise ReplayError("illegal_action", str(exc), event.sequence) from exc

    def _deal_board(self, state: Any, event: ActionEvent, scenario: ScenarioSpec) -> None:
        expected_lengths = {
            ActionType.DEAL_FLOP: (0, 3),
            ActionType.DEAL_TURN: (3, 4),
            ActionType.DEAL_RIVER: (4, 5),
        }
        start, end = expected_lengths[event.action_type]
        current = len(state.board_cards)
        if current != start:
            raise ReplayError(
                "board_order",
                f"{event.action_type.value} requires {start} board cards; found {current}",
                event.sequence,
            )
        if len(scenario.board) < end:
            raise ReplayError(
                "board_missing",
                f"scenario board must contain at least {end} cards",
                event.sequence,
            )
        try:
            if state.can_burn_card():
                state.burn_card("??")
            state.deal_board("".join(scenario.board[start:end]))
        except Exception as exc:
            raise ReplayError("illegal_board_deal", str(exc), event.sequence) from exc

    def _require_actor(self, state: Any, event: ActionEvent, seat_map: _SeatMap) -> int:
        try:
            player_index = seat_map.seat_to_player[event.actor_seat]
        except KeyError as exc:
            raise ReplayError("unknown_actor", f"seat {event.actor_seat} is not in this HU table", event.sequence) from exc
        if state.actor_index != player_index:
            actual = seat_map.player_to_seat.get(state.actor_index)
            raise ReplayError(
                "wrong_actor",
                f"expected actor seat {actual}, received seat {event.actor_seat}",
                event.sequence,
            )
        return player_index

    def _validate_before_values(self, state: Any, event: ActionEvent, player_index: int) -> None:
        if event.pot_before is not None and event.pot_before != state.total_pot_amount:
            raise ReplayError(
                "pot_before_mismatch",
                f"expected pot_before {state.total_pot_amount}",
                event.sequence,
            )
        if event.stack_before is not None and event.stack_before != state.stacks[player_index]:
            raise ReplayError(
                "stack_before_mismatch",
                f"expected stack_before {state.stacks[player_index]}",
                event.sequence,
            )

    def _validate_completion_amount(self, state: Any, event: ActionEvent) -> None:
        amount = event.amount
        minimum = state.min_completion_betting_or_raising_to_amount
        maximum = state.max_completion_betting_or_raising_to_amount
        if amount is None or minimum is None or maximum is None:
            raise ReplayError("raise_not_legal", "PokerKit reports no legal completion amount", event.sequence)
        if amount < minimum or amount > maximum:
            raise ReplayError(
                "raise_amount_out_of_range",
                f"raise-to must be between {minimum} and {maximum}",
                event.sequence,
            )
        if event.action_type is ActionType.ALL_IN and amount != maximum:
            raise ReplayError("all_in_amount_mismatch", f"all-in amount must be {maximum}", event.sequence)

    def _award_pot(self, state: Any, player_index: int) -> None:
        if state.can_push_chips():
            state.push_chips()
        if state.can_pull_chips(player_index):
            state.pull_chips(player_index)

    def _snapshot(self, state: Any, seat_map: _SeatMap) -> StateSnapshot:
        street = _domain_street(state)
        actor_seat = (
            seat_map.player_to_seat.get(state.actor_index) if state.actor_index is not None else None
        )
        stacks = {seat_map.player_to_seat[index]: int(amount) for index, amount in enumerate(state.stacks)}
        bets = {seat_map.player_to_seat[index]: int(amount) for index, amount in enumerate(state.bets)}
        return StateSnapshot(
            street=street,
            actor_seat=actor_seat,
            pot=int(state.total_pot_amount),
            stacks=stacks,
            bets=bets,
            hand_in_progress=bool(state.status),
            legal_actions=self._legal_actions(state, seat_map),
        )

    def _legal_actions(self, state: Any, seat_map: _SeatMap) -> LegalActions:
        actor_seat = (
            seat_map.player_to_seat.get(state.actor_index) if state.actor_index is not None else None
        )
        if state.actor_index is None:
            return LegalActions(actor_seat=actor_seat)
        actions: list[ActionType] = []
        explanations: dict[str, str] = {}
        call_amount = state.checking_or_calling_amount
        if state.can_check_or_call():
            if call_amount == 0:
                actions.append(ActionType.CHECK)
                explanations[ActionType.CHECK.value] = "no chips are required to continue"
            else:
                actions.append(ActionType.CALL)
                explanations[ActionType.CALL.value] = f"call cost is {call_amount} chips"
        if state.can_complete_bet_or_raise_to():
            minimum = state.min_completion_betting_or_raising_to_amount
            maximum = state.max_completion_betting_or_raising_to_amount
            action = ActionType.BET if call_amount == 0 else ActionType.RAISE_TO
            actions.append(action)
            explanations[action.value] = "amount is the total bet after the action"
            if maximum is not None and maximum == state.stacks[state.actor_index] + state.bets[state.actor_index]:
                actions.append(ActionType.ALL_IN)
                explanations[ActionType.ALL_IN.value] = "all remaining chips are committed"
        else:
            minimum = maximum = None
        if state.status:
            actions.append(ActionType.FOLD)
            explanations[ActionType.FOLD.value] = "folding ends this player's hand"
        return LegalActions(
            actor_seat=actor_seat,
            actions=tuple(actions),
            call_amount=None if call_amount is None else int(call_amount),
            min_raise_to=None if minimum is None else int(minimum),
            max_raise_to=None if maximum is None else int(maximum),
            explanations=explanations,
        )


def _domain_street(state: Any) -> Street:
    if not state.status:
        return Street.COMPLETE
    return {
        0: Street.PREFLOP,
        1: Street.FLOP,
        2: Street.TURN,
        3: Street.RIVER,
    }.get(state.street_index, Street.SHOWDOWN)
