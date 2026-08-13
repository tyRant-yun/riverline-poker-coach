"""Polling-friendly application service for the first continuous 6-max table."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from poker_coach.persistence.hand_event_store import SQLiteHandEventStore
from poker_coach.persistence.session_store import (
    GameSessionStoreError,
    SessionRevisionConflict,
    SQLiteGameSessionStore,
    StoredGameSession,
)

from .bot_providers import BLUEPRINT_PROFILE_IDS, build_bot_provider
from .bot_runtime import BotRuntime
from .contracts import ActionTakenPayloadV1, HandCompletedPayloadV1, HoleCardsRecordedPayloadV1
from .event_store import ExpectedSequenceConflict, HandEventStore
from .observation import build_observation
from .orchestrator import GameCommandError, GameOrchestrator, OpenHandCommandV1, PlayerActionCommandV1
from .replay import replay_hand, scenario_from_events
from .session import GameSession, SessionLifecycleError, SessionSeatV1
from .table_insights import build_table_insights


class ContinuousTableError(ValueError):
    """Stable public rejection produced by the continuous-table application seam."""

    def __init__(self, code: str, message: str, *, conflict: bool = False):
        self.code = code
        self.conflict = conflict
        super().__init__(message)


class ContinuousTableService:
    """Own session lifecycle, bot turns, and safe player-facing projections.

    Poker rules are intentionally absent here.  Every action is delegated to
    ``GameOrchestrator`` and the durable event stream remains the only rule
    transition record.  This service owns only API command idempotency and
    non-secret table metadata (hero assignment and selected bot profiles).
    """

    schema_version = 1

    def __init__(
        self,
        *,
        session_store: SQLiteGameSessionStore,
        event_store: HandEventStore,
        metadata_path: str | Path,
        bot_runtime: BotRuntime | None = None,
    ):
        self.session_store = session_store
        self.event_store = event_store
        self.path = str(metadata_path)
        self._orchestrator = GameOrchestrator(event_store)
        self._bot_runtime = bot_runtime or BotRuntime()
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS continuous_table_metadata (
                session_id TEXT PRIMARY KEY,
                hero_seat INTEGER NOT NULL,
                bot_profile TEXT NOT NULL,
                rng_seed INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS continuous_table_commands (
                session_id TEXT NOT NULL,
                command_id TEXT NOT NULL,
                command_kind TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                PRIMARY KEY (session_id, command_id)
            );
            CREATE TABLE IF NOT EXISTS continuous_table_bot_decisions (
                hand_id TEXT NOT NULL,
                action_sequence INTEGER NOT NULL,
                actor_seat INTEGER NOT NULL,
                profile_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                degraded INTEGER NOT NULL,
                fallback_reason TEXT,
                PRIMARY KEY (hand_id, action_sequence)
            );
            """
        )
        self._connection.commit()

    @classmethod
    def from_sqlite_path(cls, path: str | Path) -> ContinuousTableService:
        return cls(
            session_store=SQLiteGameSessionStore(path),
            event_store=SQLiteHandEventStore(path),
            metadata_path=path,
        )

    def close(self) -> None:
        self._connection.close()
        self.session_store.close()
        close = getattr(self.event_store, "close", None)
        if close is not None:
            close()

    async def create(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
        command_id = _required_text(request, "commandId")
        seed = _non_negative_int(request.get("seed", 0), "seed")
        hero_seat = _seat(request.get("heroSeat", 0), "heroSeat")
        profile = request.get("botProfile", "balanced")
        if profile not in BLUEPRINT_PROFILE_IDS:
            raise ContinuousTableError("invalid_bot_profile", "botProfile must be cautious, balanced, or aggressive")
        session_id = request.get("sessionId") or f"table-{uuid4().hex}"
        if not isinstance(session_id, str):
            raise ContinuousTableError("invalid_payload", "sessionId must be a string")
        request_hash = _request_hash(request)
        with self._lock:
            existing = self._load_create_command(command_id)
            if existing is not None:
                existing_session_id, existing_hash = existing
                if existing_hash != request_hash:
                    raise ContinuousTableError("command_id_conflict", "commandId already identifies another create request", conflict=True)
                return self.projection(existing_session_id), True
            try:
                self.session_store.load(session_id)
            except GameSessionStoreError as exc:
                if exc.code != "session_not_found":
                    raise _storage_error(exc)
            else:
                raise ContinuousTableError("session_already_exists", "sessionId is already durable", conflict=True)
            session = GameSession.create(
                session_id=session_id,
                seats=tuple(SessionSeatV1(seat_id=seat, stack=10_000) for seat in range(6)),
                button_seat=0,
            ).start_next_hand()
            stored = self._save(session, expected_revision=0)
            self._connection.execute(
                "INSERT INTO continuous_table_metadata VALUES (?, ?, ?, ?)",
                (session_id, hero_seat, profile, seed),
            )
            self._connection.execute(
                "INSERT INTO continuous_table_commands VALUES (?, ?, 'create', ?)",
                (session_id, command_id, request_hash),
            )
            self._connection.commit()
            await self._open_and_advance(stored, command_id=f"open:{command_id}")
            return self.projection(session_id), False

    def projection(self, session_id: str) -> dict[str, object]:
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            return self._projection(stored, metadata)

    def insights(self, session_id: str) -> dict[str, object]:
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            active = stored.session.active_hand
            if active is None:
                return {"schemaVersion": 1, "available": False, "unavailableReason": "hand_not_ready"}
            events = tuple(item.event for item in self.event_store.read(active.hand_id))
            return build_table_insights(events=events, session_id=session_id, hero_seat=int(metadata["hero_seat"]), database_path=self.path)

    async def submit_hero_action(
        self, session_id: str, request: dict[str, object]
    ) -> tuple[dict[str, object], bool]:
        command_id = _required_text(request, "commandId")
        request_hash = _request_hash(request)
        with self._lock:
            if self._command_matches(session_id, command_id, "hero_action", request_hash):
                return self.projection(session_id), True
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            current = self._projection(stored, metadata)
            self._require_revision(request, current)
            active = stored.session.active_hand
            if active is None or request.get("handId") != active.hand_id:
                raise ContinuousTableError("stale_hand", "handId is not the current active hand", conflict=True)
            events = tuple(item.event for item in self.event_store.read(active.hand_id))
            replayed = replay_hand(events)
            if not replayed.state.hand_in_progress:
                raise ContinuousTableError("hand_completed", "the current hand has completed", conflict=True)
            actor = _seat(metadata["hero_seat"], "heroSeat")
            if self._actor(events) != actor:
                raise ContinuousTableError("not_hero_turn", "it is not the hero's turn", conflict=True)
            try:
                command = PlayerActionCommandV1.model_validate(
                    {
                        "schemaVersion": 1,
                        "sessionId": session_id,
                        "handId": active.hand_id,
                        "commandId": command_id,
                        "expectedSequence": replayed.state.applied_sequence,
                        "actorSeat": actor,
                        "action": request.get("action"),
                        "amount": request.get("amount"),
                        "amountSemantics": request.get("amountSemantics"),
                    }
                )
                result = self._orchestrator.execute(stored.session, command)
            except (GameCommandError, SessionLifecycleError, ExpectedSequenceConflict) as exc:
                raise _orchestrator_error(exc) from None
            stored = self._save(result.session, expected_revision=stored.revision)
            self._record_command(session_id, command_id, "hero_action", request_hash)
            await self._advance_bots(stored)
            return self.projection(session_id), result.idempotent

    async def start_next_hand(
        self, session_id: str, request: dict[str, object]
    ) -> tuple[dict[str, object], bool]:
        command_id = _required_text(request, "commandId")
        request_hash = _request_hash(request)
        with self._lock:
            if self._command_matches(session_id, command_id, "next_hand", request_hash):
                return self.projection(session_id), True
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            self._require_revision(request, self._projection(stored, metadata))
            try:
                successor = stored.session.start_next_hand()
            except SessionLifecycleError as exc:
                raise _orchestrator_error(exc) from None
            stored = self._save(successor, expected_revision=stored.revision)
            self._record_command(session_id, command_id, "next_hand", request_hash)
            await self._open_and_advance(stored, command_id=command_id)
            return self.projection(session_id), False

    async def _open_and_advance(self, stored: StoredGameSession, *, command_id: str) -> None:
        active = stored.session.active_hand
        assert active is not None
        metadata = self._metadata(stored.session.session_id)
        result = self._orchestrator.open_hand(
            stored.session,
            OpenHandCommandV1(
                session_id=stored.session.session_id,
                hand_id=active.hand_id,
                command_id=command_id,
                expected_sequence=0,
                rng_seed=int(metadata["rng_seed"]) + active.sequence - 1,
            ),
        )
        stored = self._save(result.session, expected_revision=stored.revision)
        await self._advance_bots(stored)

    async def _advance_bots(self, stored: StoredGameSession) -> None:
        """Run bots one at a time, stopping only at hero or a terminal hand."""
        while stored.session.active_hand is not None:
            active = stored.session.active_hand
            metadata = self._metadata(stored.session.session_id)
            events = tuple(item.event for item in self.event_store.read(active.hand_id))
            replayed = replay_hand(events)
            if not replayed.state.hand_in_progress:
                stored = self._save(
                    stored.session.complete_active_hand(hand_id=active.hand_id, ending_stacks=replayed.state.stacks),
                    expected_revision=stored.revision,
                )
                return
            actor = self._actor(events)
            if actor is None or actor == int(metadata["hero_seat"]):
                return
            observation = build_observation(events, observer_seat=actor, after_sequence=replayed.state.applied_sequence)
            profile = str(metadata["bot_profile"])
            decision = await self._bot_runtime.decide(
                build_bot_provider(profile), observation, time_budget_ms=50,
                rng_seed=int(metadata["rng_seed"]) + replayed.state.applied_sequence,
            )
            command_id = _bot_command_id(active.hand_id, replayed.state.applied_sequence)
            try:
                result = self._orchestrator.execute(
                    stored.session,
                    PlayerActionCommandV1(
                        session_id=stored.session.session_id, hand_id=active.hand_id,
                        command_id=command_id, expected_sequence=replayed.state.applied_sequence,
                        actor_seat=actor, action=decision.action, amount=decision.amount,
                        amount_semantics=decision.amount_semantics,
                    ),
                )
            except (GameCommandError, SessionLifecycleError, ExpectedSequenceConflict) as exc:
                raise _orchestrator_error(exc) from None
            self._record_bot_decision(active.hand_id, replayed.state.applied_sequence + 1, actor, profile, decision)
            stored = self._save(result.session, expected_revision=stored.revision)

    def _projection(self, stored: StoredGameSession, metadata: sqlite3.Row) -> dict[str, object]:
        session = stored.session
        hand_id = session.active_hand.hand_id if session.active_hand else (session.completed_hand_ids[-1] if session.completed_hand_ids else None)
        events = () if hand_id is None else tuple(item.event for item in self.event_store.read(hand_id))
        replayed = None if not events else replay_hand(events)
        hero = int(metadata["hero_seat"])
        state = None if replayed is None else replayed.state
        hero_cards = next((event.payload.cards for event in events if isinstance(event.payload, HoleCardsRecordedPayloadV1) and event.payload.seat_id == hero), ())
        actor = None if not events or state is None or not state.hand_in_progress else self._actor(events)
        legal = ()
        if actor == hero:
            legal = build_observation(events, observer_seat=hero, after_sequence=state.applied_sequence).legal_actions
        folded = set(() if state is None else state.folded_seats)
        actions = [
            {"sequence": event.sequence, "street": event.payload.street.value, "actorSeat": event.payload.actor_seat,
             "action": event.payload.action.value, "amount": event.payload.amount,
             "amountSemantics": event.payload.amount_semantics.value}
            for event in events if isinstance(event.payload, ActionTakenPayloadV1)
        ]
        bot_rows = self._connection.execute(
            "SELECT action_sequence, actor_seat, profile_id, provider, provider_version, degraded, fallback_reason "
            "FROM continuous_table_bot_decisions WHERE hand_id = ? ORDER BY action_sequence", (hand_id,),
        ).fetchall() if hand_id else ()
        revision = stored.revision * 1_000_000 + (0 if state is None else state.applied_sequence)
        safe = {
            "schemaVersion": 1, "sessionId": session.session_id, "handId": hand_id,
            "handSequence": session.hand_sequence, "buttonSeat": session.button_seat,
            "heroSeat": hero, "revision": revision,
            "board": [] if state is None else list(state.board), "pot": 0 if state is None else state.pot,
            "street": None if state is None else state.street.value,
            "seats": [{"seatId": seat.seat_id,
                       "stack": (seat.stack if state is None else state.stacks[seat.seat_id]),
                       "status": "folded" if seat.seat_id in folded else ("active" if session.active_hand else "complete"),
                       "committed": 0 if state is None else state.street_commitments.get(seat.seat_id, 0)} for seat in session.topology.seats],
            "heroHoleCards": list(hero_cards), "currentActor": actor,
            "heroLegalActions": [item.to_dict() for item in legal], "actionHistory": actions,
            "handComplete": bool(state is not None and not state.hand_in_progress),
            "result": None if state is None or state.hand_in_progress else {"winnerSeats": list(state.winner_seats), "payouts": state.payouts},
            "botDecisionProvenance": [{"sequence": row["action_sequence"], "actorSeat": row["actor_seat"], "profileId": row["profile_id"], "provider": row["provider"], "providerVersion": row["provider_version"], "degraded": bool(row["degraded"]), "fallbackReason": row["fallback_reason"]} for row in bot_rows],
        }
        safe["fingerprint"] = hashlib.sha256(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return safe

    def _recover(self, session_id: str) -> StoredGameSession:
        try:
            return self.session_store.recover(session_id, event_store=self.event_store)
        except GameSessionStoreError as exc:
            if exc.code == "session_not_found":
                raise ContinuousTableError("session_not_found", "table session was not found") from None
            raise _storage_error(exc) from None

    def _save(self, session: GameSession, *, expected_revision: int) -> StoredGameSession:
        try:
            return self.session_store.save(session, expected_revision=expected_revision)
        except SessionRevisionConflict as exc:
            raise ContinuousTableError(exc.code, str(exc), conflict=True) from None
        except GameSessionStoreError as exc:
            raise _storage_error(exc) from None

    def _metadata(self, session_id: str) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM continuous_table_metadata WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise ContinuousTableError("session_not_found", "table session metadata was not found")
        return row

    def _actor(self, events) -> int | None:
        return self._orchestrator._adapter.replay(
            scenario_from_events(events)
        ).final_state.actor_seat

    def _load_create_command(self, command_id: str):
        row = self._connection.execute("SELECT session_id, request_hash FROM continuous_table_commands WHERE command_id = ? AND command_kind = 'create'", (command_id,)).fetchone()
        return None if row is None else (str(row["session_id"]), str(row["request_hash"]))

    def _command_matches(self, session_id: str, command_id: str, kind: str, request_hash: str) -> bool:
        row = self._connection.execute("SELECT command_kind, request_hash FROM continuous_table_commands WHERE session_id = ? AND command_id = ?", (session_id, command_id)).fetchone()
        if row is None:
            return False
        if row["command_kind"] != kind or row["request_hash"] != request_hash:
            raise ContinuousTableError("command_id_conflict", "commandId already identifies another command", conflict=True)
        return True

    def _record_command(self, session_id: str, command_id: str, kind: str, request_hash: str) -> None:
        self._connection.execute("INSERT INTO continuous_table_commands VALUES (?, ?, ?, ?)", (session_id, command_id, kind, request_hash))
        self._connection.commit()

    def _record_bot_decision(self, hand_id, sequence, actor, profile, decision) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO continuous_table_bot_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hand_id, sequence, actor, profile, decision.provider, decision.provider_version, int(decision.degraded), decision.fallback_reason),
        )
        self._connection.commit()

    @staticmethod
    def _require_revision(request: dict[str, object], projection: dict[str, object]) -> None:
        if request.get("expectedRevision") != projection["revision"]:
            raise ContinuousTableError("revision_conflict", "expectedRevision does not match the authoritative table revision", conflict=True)


def _required_text(request: dict[str, object], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ContinuousTableError("invalid_payload", f"{name} must be a non-empty string up to 128 characters")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContinuousTableError("invalid_payload", f"{name} must be a non-negative integer")
    return value


def _seat(value: object, name: str) -> int:
    value = _non_negative_int(value, name)
    if value > 5:
        raise ContinuousTableError("invalid_payload", f"{name} must be between 0 and 5")
    return value


def _request_hash(request: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bot_command_id(hand_id: str, sequence: int) -> str:
    return "bot-" + hashlib.sha256(f"{hand_id}:{sequence}".encode()).hexdigest()


def _orchestrator_error(exc: Exception) -> ContinuousTableError:
    code = getattr(exc, "code", "invalid_command")
    return ContinuousTableError(code, str(exc), conflict=code in {"wrong_actor", "hand_completed", "hand_in_progress", "no_active_hand", "append_conflict"})


def _storage_error(exc: Exception) -> ContinuousTableError:
    return ContinuousTableError(getattr(exc, "code", "storage_failure"), str(exc), conflict=False)
