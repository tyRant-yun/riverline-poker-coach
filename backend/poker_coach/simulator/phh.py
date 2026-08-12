"""PHH exchange adapter over authoritative :class:`HandEventV1` streams.

PokerKit owns PHH TOML parsing and validates its state machine.  This module
only maps the supported NLHE cash subset at the Riverline exchange boundary;
it never supplies a second rules engine or a query source.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from poker_coach.domain.models import Street
from poker_coach.rules import PokerKitAdapter

from .contracts import (
    ActionTakenPayloadV1,
    AmountSemanticsV1,
    BoardDealtPayloadV1,
    ContractProvenanceV1,
    EventSourceV1,
    HandCompletedPayloadV1,
    HandEventV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    SimulatorActionV1,
    SimulatorContractV1,
)
from .replay import EventStreamError, replay_hand, validate_hand_event_stream


class PhhCodecError(ValueError):
    """Stable failure for unsupported or insufficient PHH exchange input."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PhhImportResultV1(SimulatorContractV1):
    """A validated authoritative stream produced at the PHH import seam."""

    hand_id: str = Field(min_length=1, max_length=128)
    events: tuple[HandEventV1, ...]
    warnings: tuple[str, ...] = ()


class HandHistoryCodec:
    """Translate only Riverline's supported completed NLHE cash PHH subset."""

    producer = "riverline-phh-codec"
    producer_version = "1.0.0"

    def export(
        self,
        events: Sequence[HandEventV1],
        *,
        visibility: Literal["public", "authoritative_archive"] = "public",
    ) -> str:
        """Project completed facts without private cards unless archival is explicit."""

        if visibility not in {"public", "authoritative_archive"}:
            raise PhhCodecError("invalid_export_visibility", "unknown PHH export visibility")

        stream = validate_hand_event_stream(events)
        replayed = replay_hand(stream)
        if replayed.state.hand_in_progress:
            raise PhhCodecError("hand_incomplete", "PHH export requires a completed hand")
        started = stream[0].payload
        assert isinstance(started, HandStartedPayloadV1)
        active = started.active_seat_ids
        seat_to_player = _seat_to_player(started)
        actions: list[str] = []
        for event in stream[1:]:
            payload = event.payload
            if (
                isinstance(payload, HoleCardsRecordedPayloadV1)
                and visibility == "authoritative_archive"
            ):
                actions.append(
                    f"d dh p{seat_to_player[payload.seat_id] + 1} {''.join(payload.cards)}"
                )
            elif isinstance(payload, ActionTakenPayloadV1):
                player = seat_to_player[payload.actor_seat] + 1
                if payload.action is SimulatorActionV1.FOLD:
                    actions.append(f"p{player} f")
                elif payload.action in {SimulatorActionV1.CHECK, SimulatorActionV1.CALL}:
                    actions.append(f"p{player} cc")
                elif payload.action is SimulatorActionV1.BET:
                    assert payload.amount is not None
                    actions.append(f"p{player} cbr {payload.amount}")
                elif payload.action is SimulatorActionV1.RAISE:
                    assert payload.amount is not None
                    actions.append(f"p{player} cbr {payload.amount}")
            elif isinstance(payload, BoardDealtPayloadV1):
                actions.append(f"d db {''.join(payload.cards)}")

        from pokerkit import HandHistory

        metadata = {
            "riverline_schema_version": 1,
            "riverline_hand_id": stream[0].hand_id,
            "riverline_table_size": started.table_size,
            "riverline_active_seat_ids": list(active),
            "riverline_button_seat": started.button_seat,
            "riverline_starting_stacks_by_seat": {
                str(seat): stack for seat, stack in started.starting_stacks.items()
            },
            "riverline_rake_bps": started.rake_bps,
            "riverline_rng_seed": started.rng_seed,
            # PHH has no event envelope.  Keep these authority-only facts in
            # an explicit extension instead of pretending its standard fields
            # can represent event IDs/timestamps/provenance.
            "riverline_event_metadata": [
                _event_metadata(event)
                for event in stream
            ],
        }
        history = HandHistory(
            variant="NT",
            antes=[started.ante for _ in active],
            blinds_or_straddles=_blinds(started),
            min_bet=started.big_blind,
            starting_stacks=[started.starting_stacks[seat] for seat in active],
            actions=actions,
            hand=stream[0].hand_id,
            seats=list(active),
            seat_count=started.table_size,
            finishing_stacks=[replayed.state.stacks[seat] for seat in active],
            winnings=[replayed.state.payouts.get(seat, 0) for seat in active],
            user_defined_fields=metadata,
        )
        # Exercise PokerKit's own PHH serializer/parser before returning a
        # projection.  A conversion bug must fail at this exchange boundary.
        text = history.dumps()
        try:
            tuple(HandHistory.loads(text).state_actions)
        except Exception as exc:  # pragma: no cover - defensive upstream seam
            raise PhhCodecError("phh_serialization_invalid", str(exc)) from exc
        return text

    def import_phh(
        self,
        text: str,
        *,
        hand_id: str | None = None,
        imported_at: datetime | None = None,
    ) -> PhhImportResultV1:
        """Import supported PHH only after PokerKit and Riverline replay agree."""

        from pokerkit import HandHistory

        try:
            history = HandHistory.loads(text)
            # Let PokerKit reject malformed PHH first.  Create a fresh iterator
            # afterwards: its State instance is mutable, so retaining it in a
            # tuple would make every action appear to be at the final street.
            tuple(history.state_actions)
        except Exception as exc:
            raise PhhCodecError("invalid_phh", "PokerKit could not parse/replay PHH") from exc
        if history.variant != "NT":
            raise PhhCodecError("unsupported_variant", "only PHH NT (NLHE cash) is supported")
        metadata = history.user_defined_fields
        rake_bps = _integer(metadata.get("riverline_rake_bps", 0), "rake_bps")
        if rake_bps:
            raise PhhCodecError("rake_not_supported", "raked PHH cannot enter the current authority seam")
        active = _active_seats(history, metadata)
        table_size = _integer(metadata.get("riverline_table_size", history.seat_count or len(active)), "table_size")
        if not 2 <= table_size <= 8 or len(active) < 2 or len(active) > 8:
            raise PhhCodecError("unsupported_topology", "PHH must describe a 2-8 seat table")
        if any(seat < 0 or seat >= table_size for seat in active):
            raise PhhCodecError("invalid_stable_seats", "active seat IDs must be table seats")
        button = _integer(metadata.get("riverline_button_seat", active[-1]), "button_seat")
        if button not in active:
            raise PhhCodecError("invalid_button", "button must be an active stable seat")
        if history.blinds_or_straddles is None or len(history.blinds_or_straddles) < 2:
            raise PhhCodecError("missing_blinds", "PHH NT import requires small and big blinds")
        small_blind, big_blind = history.blinds_or_straddles[:2]
        if small_blind <= 0 or big_blind <= small_blind:
            raise PhhCodecError("invalid_blinds", "PHH blinds must satisfy 0 < small < big")
        stacks = _stacks_by_seat(history, metadata, table_size, active)
        resolved_hand_id = hand_id or str(metadata.get("riverline_hand_id") or history.hand or "phh-import")
        if not resolved_hand_id:
            raise PhhCodecError("missing_hand_id", "PHH import requires a non-empty hand ID")
        timestamp = imported_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            raise PhhCodecError("invalid_timestamp", "imported_at must be timezone-aware")
        started = HandStartedPayloadV1(
            table_size=table_size,
            button_seat=button,
            small_blind=int(small_blind),
            big_blind=int(big_blind),
            ante=_uniform_ante(history.antes),
            rake_bps=0,
            starting_stacks=stacks,
            active_seat_ids=active,
            rng_seed=_integer(metadata.get("riverline_rng_seed", 0), "rng_seed"),
        )
        payloads: list[object] = [started]
        player_to_seat = _player_to_seat(active, button)
        parsed_states = ((parsed, state) for state, parsed in history.state_actions if parsed is not None)
        previous_stacks = list(history.starting_stacks)
        for action in history.actions:
            try:
                parsed, state = next(parsed_states)
            except StopIteration as exc:  # pragma: no cover - PokerKit already guards this
                raise PhhCodecError("invalid_phh", "PHH action stream ended unexpectedly") from exc
            if parsed != action:
                raise PhhCodecError("invalid_phh", "PokerKit action ordering disagrees with PHH")
            payload = _payload_from_phh_action(action, player_to_seat, state, previous_stacks)
            payload = _restored_action_payload(payload, metadata, len(payloads))
            if isinstance(payload, BoardDealtPayloadV1) and len(payload.cards) == 1:
                dealt = sum(
                    len(item.cards)
                    for item in payloads
                    if isinstance(item, BoardDealtPayloadV1)
                )
                payload = payload.model_copy(
                    update={"street": Street.TURN if dealt == 3 else Street.RIVER}
                )
            if payload is not None:
                payloads.append(payload)
            previous_stacks = list(getattr(state, "stacks", previous_stacks))
        events = _events_from_payloads(resolved_hand_id, timestamp, payloads, metadata)
        # The project-owned replay uses PokerKit as the authority and rejects
        # actor/order/amount/board inconsistencies after syntax parsing.
        try:
            replayed = replay_hand(events)
        except (EventStreamError, ValueError) as exc:
            raise PhhCodecError("authoritative_replay_rejected", str(exc)) from exc
        if replayed.state.hand_in_progress:
            raise PhhCodecError("incomplete_hand", "PHH import requires a completed hand")
        _validate_standard_settlement(history, replayed, active)
        live = set(active) - {
            payload.actor_seat
            for payload in payloads
            if isinstance(payload, ActionTakenPayloadV1)
            and payload.action is SimulatorActionV1.FOLD
        }
        recorded = {
            payload.seat_id for payload in payloads if isinstance(payload, HoleCardsRecordedPayloadV1)
        }
        if len(live) > 1 and not live.issubset(recorded):
            raise PhhCodecError("insufficient_hole_cards", "showdown PHH must reveal every live seat")
        completed = HandCompletedPayloadV1(
            winner_seats=replayed.state.winner_seats,
            payouts=replayed.state.payouts,
        )
        final_events = _events_from_payloads(resolved_hand_id, timestamp, [*payloads, completed], metadata)
        try:
            replay_hand(final_events)
        except (EventStreamError, ValueError) as exc:  # pragma: no cover - invariant guard
            raise PhhCodecError("authoritative_completion_rejected", str(exc)) from exc
        warnings = () if "riverline_event_metadata" in metadata else ("source_provenance_unavailable",)
        return PhhImportResultV1(hand_id=resolved_hand_id, events=final_events, warnings=warnings)


def _seat_to_player(started: HandStartedPayloadV1) -> dict[int, int]:
    active = started.active_seat_ids
    button_index = active.index(started.button_seat)
    ordered = active[button_index + 1 :] + active[: button_index + 1]
    return {seat: index for index, seat in enumerate(ordered)}


def _event_metadata(event: HandEventV1) -> dict[str, object]:
    values: dict[str, object | None] = {
        "event_id": event.event_id,
        "timestamp": event.timestamp.isoformat(),
        "source": event.source.value,
        "producer": event.provenance.producer,
        "producer_version": event.provenance.producer_version,
        "correlation_id": event.provenance.correlation_id,
        "causation_id": event.provenance.causation_id,
        "payload_kind": event.payload.kind,
        "street": getattr(event.payload, "street", None),
        "actor_seat": getattr(event.payload, "actor_seat", None),
        "action": getattr(event.payload, "action", None),
        "amount": getattr(event.payload, "amount", None),
        "amount_semantics": getattr(event.payload, "amount_semantics", None),
    }
    return {key: value for key, value in values.items() if value is not None}


def _player_to_seat(active: tuple[int, ...], button: int) -> tuple[int, ...]:
    button_index = active.index(button)
    return active[button_index + 1 :] + active[: button_index + 1]


def _blinds(started: HandStartedPayloadV1) -> list[int]:
    # PokerKit's PHH NT ordering follows its player ordering; heads-up remains
    # outside the product default but is kept compatible with its own adapter.
    return [started.small_blind, started.big_blind]


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise PhhCodecError("invalid_metadata", f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PhhCodecError("invalid_metadata", f"{name} must be an integer") from exc


def _active_seats(history: object, metadata: dict[str, object]) -> tuple[int, ...]:
    raw = metadata.get("riverline_active_seat_ids", getattr(history, "seats") or list(range(len(history.starting_stacks))))
    if not isinstance(raw, list) or any(isinstance(seat, bool) for seat in raw):
        raise PhhCodecError("invalid_stable_seats", "active seats must be an integer list")
    seats = tuple(_integer(seat, "active_seat_ids") for seat in raw)
    if tuple(sorted(set(seats))) != seats:
        raise PhhCodecError("invalid_stable_seats", "active seats must be unique and sorted")
    if len(seats) != len(history.starting_stacks):
        raise PhhCodecError("seat_stack_mismatch", "PHH seats and starting stacks must align")
    return seats


def _stacks_by_seat(history: object, metadata: dict[str, object], table_size: int, active: tuple[int, ...]) -> dict[int, int]:
    extension = metadata.get("riverline_starting_stacks_by_seat")
    if isinstance(extension, dict):
        try:
            stacks = {int(seat): _integer(amount, "starting_stack") for seat, amount in extension.items()}
        except (TypeError, ValueError) as exc:
            raise PhhCodecError("invalid_stacks", "invalid stable stack extension") from exc
        if set(stacks) == set(range(table_size)):
            return stacks
    stacks = {seat: 0 for seat in range(table_size)}
    stacks.update(zip(active, map(int, history.starting_stacks), strict=True))
    return stacks


def _uniform_ante(antes: list[int]) -> int:
    if not antes:
        return 0
    if len(set(antes)) != 1 or antes[0] < 0:
        raise PhhCodecError("unsupported_ante", "only uniform antes are supported")
    return int(antes[0])


def _validate_standard_settlement(
    history: object,
    replayed: object,
    active: tuple[int, ...],
) -> None:
    """Reject a PHH that reports a settlement other than no-rake PokerKit facts."""

    finishing = getattr(history, "finishing_stacks", None)
    winnings = getattr(history, "winnings", None)
    if finishing is None or winnings is None:
        raise PhhCodecError(
            "settlement_facts_missing",
            "completed PHH import requires finishing_stacks and winnings",
        )
    if len(finishing) != len(active) or len(winnings) != len(active):
        raise PhhCodecError(
            "settlement_facts_missing",
            "PHH settlement arrays must align with active seats",
        )
    if sum(finishing) != sum(history.starting_stacks):
        raise PhhCodecError(
            "potential_rake",
            "PHH final chips differ from starting chips; rake is unsupported",
        )
    expected_stacks = [replayed.state.stacks[seat] for seat in active]
    expected_winnings = [replayed.state.payouts.get(seat, 0) for seat in active]
    if list(finishing) != expected_stacks or list(winnings) != expected_winnings:
        raise PhhCodecError(
            "settlement_mismatch",
            "PHH finishing_stacks or winnings disagree with no-rake authoritative replay",
        )


def _payload_from_phh_action(
    action: str,
    player_to_seat: tuple[int, ...],
    state: object,
    previous_stacks: list[int],
) -> object | None:
    raw = action.split("#", 1)[0].strip()
    if not raw:
        return None
    tokens = raw.split()
    if tokens[:2] == ["d", "dh"] and len(tokens) == 4:
        seat = _phh_player(tokens[2], player_to_seat)
        cards = tokens[3]
        if len(cards) != 4:
            raise PhhCodecError("unsupported_action", "hole deal must contain two cards")
        return HoleCardsRecordedPayloadV1(seat_id=seat, cards=(cards[:2], cards[2:]))
    if tokens[:2] == ["d", "db"] and len(tokens) == 3:
        cards = tokens[2]
        count = len(cards) // 2
        if len(cards) not in (2, 6):
            raise PhhCodecError("unsupported_action", "board deal must be flop, turn, or river")
        street = Street.FLOP if count == 3 else Street.TURN
        return BoardDealtPayloadV1(street=street, cards=tuple(cards[index:index + 2] for index in range(0, len(cards), 2)))
    if len(tokens) >= 2 and tokens[0].startswith("p"):
        seat = _phh_player(tokens[0], player_to_seat)
        operations = getattr(state, "operations", ())
        player_index = _integer(tokens[0][1:], "player") - 1
        operation = next(
            (
                item
                for item in reversed(operations)
                if type(item).__name__ == "CheckingOrCalling"
                and getattr(item, "player_index", None) == player_index
            ),
            None,
        )
        name = type(operation).__name__ if operation is not None else ""
        count = sum(len(cards) for cards in getattr(state, "board_cards", ()))
        street = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}.get(count, Street.SHOWDOWN)
        if tokens[1:] == ["f"]:
            return ActionTakenPayloadV1(street=street, actor_seat=seat, action="fold")
        if tokens[1:] == ["cc"]:
            call_amount = previous_stacks[player_index] - list(getattr(state, "stacks"))[player_index]
            if name != "CheckingOrCalling":
                raise PhhCodecError("unsupported_action", "PHH cc did not yield a call/check operation")
            if call_amount:
                return ActionTakenPayloadV1(street=street, actor_seat=seat, action="call", amount=int(call_amount), amount_semantics="cost")
            return ActionTakenPayloadV1(street=street, actor_seat=seat, action="check")
        if len(tokens) == 3 and tokens[1] == "cbr":
            return ActionTakenPayloadV1(street=street, actor_seat=seat, action="raise", amount=_integer(tokens[2], "raise_to"), amount_semantics="to")
    raise PhhCodecError("unsupported_action", f"unsupported PHH action: {raw}")


def _phh_player(token: str, player_to_seat: tuple[int, ...]) -> int:
    if not token.startswith("p"):
        raise PhhCodecError("invalid_player", "PHH actor must use pN notation")
    index = _integer(token[1:], "player") - 1
    if index < 0 or index >= len(player_to_seat):
        raise PhhCodecError("invalid_player", "PHH player is outside active seats")
    # PHH p1 is PokerKit's small-blind-relative player, matching _seat_to_player.
    return player_to_seat[index]


def _events_from_payloads(hand_id: str, timestamp: datetime, payloads: Sequence[object], metadata: dict[str, object]) -> tuple[HandEventV1, ...]:
    saved = metadata.get("riverline_event_metadata")
    preserved = saved if isinstance(saved, list) and len(saved) == len(payloads) else None
    events: list[HandEventV1] = []
    for sequence, payload in enumerate(payloads, start=1):
        entry = preserved[sequence - 1] if preserved is not None and isinstance(preserved[sequence - 1], dict) else {}
        event_timestamp = timestamp
        if entry.get("timestamp"):
            try:
                event_timestamp = datetime.fromisoformat(str(entry["timestamp"]))
            except ValueError as exc:
                raise PhhCodecError("invalid_provenance_extension", "invalid event timestamp") from exc
        provenance = ContractProvenanceV1(
            producer=str(entry.get("producer", HandHistoryCodec.producer)),
            producer_version=str(entry.get("producer_version", HandHistoryCodec.producer_version)),
            correlation_id=str(entry.get("correlation_id", f"phh:{hand_id}")),
            causation_id=None if entry.get("causation_id") is None else str(entry["causation_id"]),
        )
        events.append(HandEventV1(
            event_id=str(entry.get("event_id", uuid5(NAMESPACE_URL, f"riverline-phh:{hand_id}:{sequence}"))),
            hand_id=hand_id,
            sequence=sequence,
            timestamp=event_timestamp,
            source=entry.get("source", EventSourceV1.IMPORT.value),
            provenance=provenance,
            payload=payload,
        ))
    return tuple(events)


def _restored_action_payload(payload: object | None, metadata: dict[str, object], index: int) -> object | None:
    """Use the explicit project extension when restoring our own PHH export."""
    saved = metadata.get("riverline_event_metadata")
    if not isinstance(payload, ActionTakenPayloadV1) or not isinstance(saved, list) or index >= len(saved):
        return payload
    entry = saved[index]
    if not isinstance(entry, dict) or entry.get("payload_kind") != "action_taken":
        return payload
    if entry.get("actor_seat") != payload.actor_seat or entry.get("action") != payload.action.value:
        raise PhhCodecError("provenance_extension_mismatch", "PHH action disagrees with Riverline extension")
    return ActionTakenPayloadV1(
        street=str(entry["street"]),
        actor_seat=payload.actor_seat,
        action=payload.action,
        amount=entry.get("amount"),
        amount_semantics=entry.get("amount_semantics", "none"),
    )
