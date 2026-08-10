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
    SettlementResult,
    StateSnapshot,
    Street,
)


class ReplayError(ValueError):
    """A stable error raised when an event cannot be replayed legally."""

    def __init__(
        self,
        code: str,
        message: str,
        sequence: int | None = None,
        state: StateSnapshot | None = None,
    ):
        self.code = code
        self.sequence = sequence
        self.state = state
        prefix = f"event {sequence}: " if sequence is not None else ""
        super().__init__(f"{prefix}{message}")

    def attach_state(self, state: StateSnapshot) -> ReplayError:
        if self.state is None:
            self.state = state
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "sequence": self.sequence,
            "state": None if self.state is None else self.state.to_dict(),
            "legalActions": None
            if self.state is None
            else self.state.legal_actions.to_dict(),
        }


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
        initial_chip_total = sum(seat.starting_stack for seat in scenario.seats)
        self._assert_state_invariants(state, seat_map, initial_chip_total)
        snapshots = [self._snapshot(state, seat_map)]
        events = scenario.action_history
        try:
            cursor = self._consume_forced_blind_events(events, scenario, seat_map)
        except ReplayError as exc:
            raise exc.attach_state(self._snapshot(state, seat_map))
        deferred_awards: list[ActionEvent] = []

        for event in events[cursor:]:
            try:
                if (
                    event.action_type is ActionType.AWARD_POT
                    and state.all_in_status
                    and state.status
                ):
                    deferred_awards.append(event)
                    snapshots.append(self._snapshot(state, seat_map))
                    continue
                self._apply_event(state, event, scenario, seat_map)
                self._assert_state_invariants(state, seat_map, initial_chip_total, event.sequence)
            except ReplayError as exc:
                raise exc.attach_state(self._snapshot(state, seat_map))
            snapshots.append(self._snapshot(state, seat_map))

        try:
            self._auto_runout(state, scenario)
            self._assert_state_invariants(state, seat_map, initial_chip_total)
        except ReplayError as exc:
            raise exc.attach_state(self._snapshot(state, seat_map))

        for event in deferred_awards:
            try:
                self._verify_or_award_pot(state, event, seat_map)
            except ReplayError as exc:
                raise exc.attach_state(self._snapshot(state, seat_map))

        self._assert_state_invariants(state, seat_map, initial_chip_total)

        after_automatic_steps = self._snapshot(state, seat_map)
        if snapshots[-1] != after_automatic_steps:
            snapshots.append(after_automatic_steps)

        settlement = self._settlement(state, seat_map)
        return ReplayResult(
            rules_engine=self.engine_name,
            rules_engine_version=self.engine_version,
            snapshots=tuple(snapshots),
            final_state=after_automatic_steps,
            settlement=settlement,
        )

    def legal_actions(self, scenario: ScenarioSpec) -> LegalActions:
        return self.replay(scenario).final_state.legal_actions

    def replay_to_decision(self, scenario: ScenarioSpec) -> ReplayResult:
        """Replay only the selected node and verify its declared decision point."""

        prefix = scenario.model_copy(
            update={"action_history": scenario.action_history[: scenario.decision_point.after_sequence]}
        )
        result = self.replay(prefix)
        state = result.final_state
        if state.hand_in_progress and state.actor_seat is not None:
            if state.actor_seat != scenario.decision_point.actor_seat:
                raise ReplayError(
                    "decision_point_actor_mismatch",
                    f"decision point actor must be seat {state.actor_seat}",
                    scenario.decision_point.after_sequence,
                    state,
                )
            if state.street is not scenario.decision_point.street:
                raise ReplayError(
                    "decision_point_street_mismatch",
                    f"decision point street must be {state.street.value}",
                    scenario.decision_point.after_sequence,
                    state,
                )
        return result

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
        automations = [
            Automation.BET_COLLECTION,
            Automation.RUNOUT_COUNT_SELECTION,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
            Automation.HAND_KILLING,
            Automation.CHIPS_PUSHING,
            Automation.CHIPS_PULLING,
        ]
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
        hero_player = seat_map.seat_to_player[scenario.hero_seat]
        villain_player = 1 - hero_player
        hole_cards_by_player: dict[int, str] = {
            hero_player: "".join(scenario.hero_hole_cards),
            villain_player: "????"
            if scenario.villain_hole_cards is None
            else "".join(scenario.villain_hole_cards),
        }
        for player_index in (0, 1):
            state.deal_hole(hole_cards_by_player[player_index], player_index=player_index)
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
        remaining_blind = next(
            (event for event in events[cursor:] if event.action_type is ActionType.POST_BLIND),
            None,
        )
        if remaining_blind is not None:
            raise ReplayError(
                "blind_order",
                "blind events must be the first events and appear at most once per seat",
                remaining_blind.sequence,
            )
        return cursor

    def _apply_event(
        self,
        state: Any,
        event: ActionEvent,
        scenario: ScenarioSpec,
        seat_map: _SeatMap,
    ) -> None:
        self._validate_event_street(state, event)

        if event.action_type in {
            ActionType.DEAL_FLOP,
            ActionType.DEAL_TURN,
            ActionType.DEAL_RIVER,
        }:
            self._deal_board(state, event, scenario)
            return

        if event.action_type is ActionType.SHOWDOWN:
            self._verify_showdown_marker(state, event, scenario, seat_map)
            return

        if event.action_type is ActionType.AWARD_POT:
            self._verify_or_award_pot(state, event, seat_map)
            return

        player_index = self._require_actor(state, event, seat_map)
        self._validate_before_values(state, event, player_index)

        try:
            if event.action_type is ActionType.CHECK:
                if state.checking_or_calling_amount != 0:
                    raise ReplayError(
                        "check_not_legal",
                        "a call is required, not a check",
                        event.sequence,
                    )
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
                target = self._completion_target(state, event, player_index)
                self._validate_completion_amount(state, event, target)
                state.complete_bet_or_raise_to(target)
            elif event.action_type is ActionType.FOLD:
                state.fold()
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

    def _completion_target(self, state: Any, event: ActionEvent, player_index: int) -> int:
        if event.amount is None:
            raise ReplayError("missing_amount", "completion action requires an amount", event.sequence)
        if event.action_type is ActionType.BET:
            return state.bets[player_index] + event.amount
        return event.amount

    def _deal_board(self, state: Any, event: ActionEvent, scenario: ScenarioSpec) -> None:
        expected_lengths = {
            ActionType.DEAL_FLOP: (0, 3),
            ActionType.DEAL_TURN: (3, 4),
            ActionType.DEAL_RIVER: (4, 5),
        }
        start, end = expected_lengths[event.action_type]
        current = len(_flatten_board(state.board_cards))
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
            if not state.can_deal_board():
                raise ReplayError(
                    "board_not_pending",
                    "PokerKit reports that no board dealing is pending",
                    event.sequence,
                )
            state.deal_board("".join(scenario.board[start:end]))
        except ReplayError:
            raise
        except Exception as exc:
            raise ReplayError("illegal_board_deal", str(exc), event.sequence) from exc

    def _auto_runout(self, state: Any, scenario: ScenarioSpec) -> None:
        if not state.all_in_status:
            return
        while len(_flatten_board(state.board_cards)) < len(scenario.board):
            current = len(_flatten_board(state.board_cards))
            if current not in (0, 3, 4):
                raise ReplayError("invalid_board_length", f"cannot run out from {current} cards")
            if not state.can_burn_card():
                raise ReplayError("runout_not_pending", "all-in runout is not pending")
            state.burn_card("??")
            if not state.can_deal_board():
                raise ReplayError("runout_board_not_pending", "board dealing did not follow burn")
            end = 3 if current == 0 else current + 1
            state.deal_board("".join(scenario.board[current:end]))

    def _verify_showdown_marker(
        self,
        state: Any,
        event: ActionEvent,
        scenario: ScenarioSpec,
        seat_map: _SeatMap,
    ) -> None:
        if scenario.villain_hole_cards is None:
            raise ReplayError(
                "showdown_requires_hole_cards",
                "showdown requires villain_hole_cards in ScenarioSpec",
                event.sequence,
            )
        if event.actor_seat not in seat_map.seat_to_player:
            raise ReplayError("unknown_actor", f"seat {event.actor_seat} is not in this HU table", event.sequence)
        # With the settlement automations, PokerKit emits showdown and payout
        # operations as soon as the terminal action is replayed. The explicit
        # event is retained as an auditable marker and verified here.
        if not state.status and state.total_pot_amount == 0:
            return
        if state.all_in_status and state.actor_index is None:
            return
        if state.all_in_status:
            raise ReplayError(
                "showdown_not_ready",
                "showdown marker arrived before the remaining player called the all-in",
                event.sequence,
            )
        if state.actor_index is None:
            raise ReplayError("showdown_not_ready", "showdown marker arrived before a terminal street", event.sequence)

    def _verify_or_award_pot(self, state: Any, event: ActionEvent, seat_map: _SeatMap) -> None:
        if event.actor_seat not in seat_map.seat_to_player:
            raise ReplayError("unknown_actor", f"seat {event.actor_seat} is not in this HU table", event.sequence)
        payouts = self._operation_payouts(state, seat_map)
        payout = payouts.get(event.actor_seat, 0)
        if state.all_in_status and state.status and state.actor_index is None:
            return
        if not state.status and state.total_pot_amount == 0:
            if payout != event.amount:
                raise ReplayError(
                    "award_amount_mismatch",
                    f"expected payout for seat {event.actor_seat} is {payout}",
                    event.sequence,
                )
            return
        raise ReplayError("award_not_ready", "pot has not been settled", event.sequence)

    def _require_actor(self, state: Any, event: ActionEvent, seat_map: _SeatMap) -> int:
        if not state.status:
            raise ReplayError(
                "hand_ended",
                "hand has already ended; no further player action is legal",
                event.sequence,
            )
        try:
            player_index = seat_map.seat_to_player[event.actor_seat]
        except KeyError as exc:
            raise ReplayError(
                "unknown_actor",
                f"seat {event.actor_seat} is not in this HU table",
                event.sequence,
            ) from exc
        if state.actor_index != player_index:
            actual = seat_map.player_to_seat.get(state.actor_index)
            raise ReplayError(
                "wrong_actor",
                f"expected actor seat {actual}, received seat {event.actor_seat}",
                event.sequence,
            )
        return player_index

    def _validate_event_street(self, state: Any, event: ActionEvent) -> None:
        if not state.status:
            if event.action_type is ActionType.SHOWDOWN and event.street is Street.SHOWDOWN:
                return
            if event.action_type is ActionType.AWARD_POT and event.street is Street.COMPLETE:
                return
            raise ReplayError(
                "hand_ended",
                "hand has already ended; no further event is legal",
                event.sequence,
            )

        if event.action_type is ActionType.SHOWDOWN:
            expected = Street.SHOWDOWN
        elif event.action_type is ActionType.AWARD_POT:
            expected = Street.COMPLETE
        elif event.action_type is ActionType.DEAL_FLOP:
            expected = Street.FLOP
        elif event.action_type is ActionType.DEAL_TURN:
            expected = Street.TURN
        elif event.action_type is ActionType.DEAL_RIVER:
            expected = Street.RIVER
        elif event.action_type is ActionType.POST_BLIND:
            expected = Street.PREFLOP
        else:
            expected = {
                0: Street.PREFLOP,
                3: Street.FLOP,
                4: Street.TURN,
                5: Street.RIVER,
            }.get(len(_flatten_board(state.board_cards)), Street.SHOWDOWN)

        if event.street is not expected:
            raise ReplayError(
                "wrong_street",
                f"expected event street {expected.value}, received {event.street.value}",
                event.sequence,
            )

    def _assert_state_invariants(
        self,
        state: Any,
        seat_map: _SeatMap,
        initial_chip_total: int,
        sequence: int | None = None,
    ) -> None:
        stacks = [int(amount) for amount in state.stacks]
        bets = [int(amount) for amount in state.bets]
        pot = int(state.total_pot_amount)
        if any(amount < 0 for amount in stacks + bets) or pot < 0:
            raise ReplayError(
                "state_invariant",
                "stacks, bets, and pot must never be negative",
                sequence,
            )
        if sum(stacks) + pot != initial_chip_total:
            raise ReplayError(
                "chip_conservation",
                f"expected {initial_chip_total} chips, found {sum(stacks) + pot}",
                sequence,
            )
        board = _flatten_board(state.board_cards)
        if len(board) != len(set(board)):
            raise ReplayError("duplicate_board_card", "board contains a repeated card", sequence)

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

    def _validate_completion_amount(self, state: Any, event: ActionEvent, target: int) -> None:
        minimum = state.min_completion_betting_or_raising_to_amount
        maximum = state.max_completion_betting_or_raising_to_amount
        if minimum is None or maximum is None:
            raise ReplayError(
                "raise_not_legal",
                "PokerKit reports no legal completion amount",
                event.sequence,
            )
        if target < minimum or target > maximum:
            raise ReplayError(
                "raise_amount_out_of_range",
                f"raise-to must be between {minimum} and {maximum}",
                event.sequence,
            )
        if event.action_type is ActionType.ALL_IN and target != maximum:
            raise ReplayError(
                "all_in_amount_mismatch",
                f"all-in amount must be {maximum}",
                event.sequence,
            )

    def _settlement(self, state: Any, seat_map: _SeatMap) -> SettlementResult:
        payouts = self._operation_payouts(state, seat_map)
        completed = not state.status and state.total_pot_amount == 0
        if not completed:
            return SettlementResult(completed=False)
        folded = any(type(operation).__name__ == "Folding" for operation in state.operations)
        reason = "fold" if folded else "showdown"
        winners = tuple(sorted(seat for seat, amount in payouts.items() if amount > 0))
        return SettlementResult(
            completed=True,
            reason=reason,
            winner_seats=winners,
            payouts={seat: amount for seat, amount in sorted(payouts.items()) if amount > 0},
            total_awarded=sum(payouts.values()),
        )

    def _operation_payouts(self, state: Any, seat_map: _SeatMap) -> dict[int, int]:
        # PokerKit's ChipsPushing operation is authoritative for hand
        # comparison, split pots, and odd-chip remainder assignment. The
        # adapter reports those deltas without reimplementing payout logic.
        payouts: dict[int, int] = {}
        for operation in state.operations:
            if type(operation).__name__ != "ChipsPushing":
                continue
            for player_index, amount in enumerate(operation.amounts):
                if amount:
                    seat = seat_map.player_to_seat[player_index]
                    payouts[seat] = payouts.get(seat, 0) + int(amount)
        return payouts

    def _snapshot(self, state: Any, seat_map: _SeatMap) -> StateSnapshot:
        actor_seat = (
            seat_map.player_to_seat.get(state.actor_index) if state.actor_index is not None else None
        )
        stacks = {seat_map.player_to_seat[index]: int(amount) for index, amount in enumerate(state.stacks)}
        bets = {seat_map.player_to_seat[index]: int(amount) for index, amount in enumerate(state.bets)}
        folded = tuple(
            sorted(
                seat_map.player_to_seat[operation.player_index]
                for operation in state.operations
                if type(operation).__name__ == "Folding"
            )
        )
        return StateSnapshot(
            street=_domain_street(state),
            actor_seat=actor_seat,
            board=tuple(_flatten_board(state.board_cards)),
            pot=int(state.total_pot_amount),
            stacks=stacks,
            bets=bets,
            folded_seats=folded,
            hand_in_progress=bool(state.status),
            legal_actions=self._legal_actions(state, seat_map),
        )

    def _legal_actions(self, state: Any, seat_map: _SeatMap) -> LegalActions:
        actor_seat = (
            seat_map.player_to_seat.get(state.actor_index) if state.actor_index is not None else None
        )
        if state.actor_index is None or not state.status:
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


def _flatten_board(board_cards: Any) -> list[str]:
    return [_card_code(card) for street_cards in board_cards for card in street_cards]


def _card_code(card: Any) -> str:
    rank = getattr(card, "rank", None)
    suit = getattr(card, "suit", None)
    if rank is not None and suit is not None:
        return f"{rank.value}{suit.value}"
    return str(card)


def _domain_street(state: Any) -> Street:
    if not state.status:
        return Street.COMPLETE
    return {
        0: Street.PREFLOP,
        1: Street.FLOP,
        2: Street.TURN,
        3: Street.RIVER,
    }.get(state.street_index, Street.SHOWDOWN)
