"""Polling-friendly application service for the first continuous 6-max table."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from uuid import uuid4

from poker_coach.persistence.hand_event_store import SQLiteHandEventStore
from poker_coach.persistence.review_projection_store import SQLiteReviewProjectionStore
from poker_coach.persistence.session_store import (
    GameSessionStoreError,
    SessionRevisionConflict,
    SQLiteGameSessionStore,
    StoredGameSession,
)
from poker_coach.ranges.belief import cards_from_key
from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer
from poker_coach.theory import L2RecommendationInput, PreflopPolicyContext, TheoryDecisionIdentityV1, TheoryExplainer
from poker_coach.theory.l2_solver import L2Budget, L2Cache, L2Result, L2RiverInput, RangeCombo, RiverBetTree, solve_hu_river

from .bot_providers import BOT_PROFILE_IDS, build_bot_provider
from .bot_runtime import BotRuntime
from .auto_review import AutomaticReviewProjectionService
from .contracts import ActionTakenPayloadV1, HandCompletedPayloadV1, HoleCardsRecordedPayloadV1
from .decision_reconciliation import (
    ReconciliationIdentityV1,
    reconcile_decision,
    unavailable_simulation,
)
from .event_store import ExpectedSequenceConflict, HandEventStore
from .fast_solver import FastSolver
from .formula_advisor import FormulaAdvisorFactory
from .observation import build_observation
from .orchestrator import GameCommandError, GameOrchestrator, OpenHandCommandV1, PlayerActionCommandV1
from .replay import replay_hand, scenario_from_events
from .session import GameSession, SessionLifecycleError, SessionSeatV1
from .table_insights import _public_stream, build_table_insights
from .table_reviews import TableReviewReader, public_review


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
        seed_source: Callable[[], int] | None = None,
    ):
        self.session_store = session_store
        self.event_store = event_store
        self.path = str(metadata_path)
        self._orchestrator = GameOrchestrator(event_store)
        self._bot_runtime = bot_runtime or BotRuntime()
        self._seed_source = seed_source or (lambda: secrets.randbits(62))
        self._review_store = SQLiteReviewProjectionStore(self.path)
        self._review_service = AutomaticReviewProjectionService(event_store, self._review_store)
        self._fast_solver = FastSolver()
        self._l2_cache = L2Cache(max_entries=16)
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
        self._review_store.close()
        self._connection.close()
        self.session_store.close()
        close = getattr(self.event_store, "close", None)
        if close is not None:
            close()

    async def create(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
        command_id = _required_text(request, "commandId")
        seed = _non_negative_int(
            request["seed"] if "seed" in request else self._seed_source(), "seed"
        )
        hero_seat = _seat(request.get("heroSeat", 0), "heroSeat")
        profile = request.get("botProfile", "balanced")
        if profile not in BOT_PROFILE_IDS:
            raise ContinuousTableError("invalid_bot_profile", "botProfile is not a supported profile")
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
            current = self._projection(stored, metadata)
            hand_id = current["handId"]
            if not isinstance(hand_id, str):
                return {"schemaVersion": 1, "available": False, "unavailableReason": "hand_not_ready"}
            events = tuple(item.event for item in self.event_store.read(hand_id))
            return build_table_insights(
                events=events, session_id=session_id, hero_seat=int(metadata["hero_seat"]),
                database_path=self.path, decision_fingerprint=str(current["fingerprint"]),
            )

    def advisor(self, session_id: str, request: dict[str, object]) -> dict[str, object]:
        """Return the independent L0 result only after matching the current decision."""

        hand_id = request.get("handId")
        fingerprint = request.get("decisionFingerprint")
        if not isinstance(hand_id, str) or not isinstance(fingerprint, str):
            raise ContinuousTableError("invalid_advisor_request", "handId and decisionFingerprint are required strings")
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            current = self._projection(stored, metadata)
            if current["handId"] != hand_id:
                raise ContinuousTableError("stale_decision", "advisor request is not for the current hand", conflict=True)
            if current["fingerprint"] != fingerprint:
                raise ContinuousTableError("stale_decision", "advisor request does not match the current decision", conflict=True)
            hero = int(metadata["hero_seat"])
            events = tuple(item.event for item in self.event_store.read(hand_id))
            state = replay_hand(events).state
            if not state.hand_in_progress or self._actor(events) != hero:
                return {
                    "status": "not_ready", "recommendedAction": None,
                    "source": "deterministic_formula", "version": "formula-advisor/v1",
                    "confidence": "unavailable", "explanationKey": "advisor.not_ready.not_hero_decision",
                    "limitations": ["L0 Advisor is only applicable to an active Hero decision."],
                    "decision": {"fingerprint": fingerprint, "handId": hand_id,
                                 "sequence": events[-1].sequence, "street": state.street.value},
                }
            try:
                observation = build_observation(
                    events, observer_seat=hero, after_sequence=events[-1].sequence
                )
            except Exception:
                return _advisor_projection_fallback(
                    current=current, hand_id=hand_id, fingerprint=fingerprint,
                    sequence=events[-1].sequence, street=state.street.value,
                )
        return FormulaAdvisorFactory().create().evaluate(
            observation, decision_fingerprint=fingerprint
        ).to_dict()

    def theory_recommendation(self, session_id: str, request: dict[str, object]) -> dict[str, object]:
        """Return one current, source-prioritized theory truth plus L0 explanation.

        A supported live HU river may use a public-range L2 projection only when
        the current Hero observation carries its authorized own cards.  This
        read-only method shares the normal stale hand/fingerprint gate, so it
        cannot populate a cache across hands.
        """

        hand_id = request.get("handId")
        fingerprint = request.get("decisionFingerprint")
        if not isinstance(hand_id, str) or not isinstance(fingerprint, str):
            raise ContinuousTableError(
                "invalid_theory_recommendation_request",
                "handId and decisionFingerprint are required strings",
            )
        explainer = TheoryExplainer()
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            current = self._projection(stored, metadata)
            if current["handId"] != hand_id:
                raise ContinuousTableError("stale_decision", "theory request is not for the current hand", conflict=True)
            if current["fingerprint"] != fingerprint:
                raise ContinuousTableError("stale_decision", "theory request does not match the current decision", conflict=True)
            hero = int(metadata["hero_seat"])
            events = tuple(item.event for item in self.event_store.read(hand_id))
            state = replay_hand(events).state
            identity = TheoryDecisionIdentityV1(
                fingerprint=fingerprint, hand_id=hand_id, sequence=events[-1].sequence,
                street=state.street, observer_seat=hero,
            )
            if not state.hand_in_progress or self._actor(events) != hero:
                return explainer.unavailable(
                    decision=identity, reason="not_current_hero_decision"
                ).to_dict()
            try:
                observation = build_observation(
                    events, observer_seat=hero, after_sequence=events[-1].sequence
                )
            except Exception:
                return explainer.unavailable(
                    decision=identity, reason="hero_observation_unavailable"
                ).to_dict()
        l2 = _live_hu_river_l2(
            events=events, observation=observation, decision_fingerprint=fingerprint,
            cache=self._l2_cache,
        )
        # The continuous table is intentionally fixed at its authoritative
        # 100-chip BB/no-rake configuration.  The artifact rechecks stack,
        # position and public prefix before it can claim B coverage.
        return explainer.recommend(
            observation, decision_fingerprint=fingerprint,
            preflop_context=PreflopPolicyContext(big_blind=100),
            l2=l2,
        ).to_dict()

    def solver(self, session_id: str, request: dict[str, object]) -> dict[str, object]:
        """Take a safe decision snapshot, then solve outside the table lock.

        This separate read-only seam keeps L0 insights/action flow independent
        of bounded L1 sampling and rejects a request for an older decision.
        """

        hand_id = request.get("handId")
        fingerprint = request.get("decisionFingerprint")
        budget_tier = request.get("budgetTier", "standard")
        if not isinstance(hand_id, str) or not isinstance(fingerprint, str):
            raise ContinuousTableError("invalid_solver_request", "handId and decisionFingerprint are required strings")
        if budget_tier not in {"quick", "standard", "deep"}:
            raise ContinuousTableError(
                "invalid_solver_request", "budgetTier must be quick, standard, or deep"
            )
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            active = stored.session.active_hand
            if active is None or active.hand_id != hand_id:
                raise ContinuousTableError("stale_decision", "solver request is not for the current hand", conflict=True)
            current = self._projection(stored, metadata)
            if current["fingerprint"] != fingerprint:
                raise ContinuousTableError("stale_decision", "solver request does not match the current decision", conflict=True)
            hero = int(metadata["hero_seat"])
            events = tuple(item.event for item in self.event_store.read(active.hand_id))
            state = replay_hand(events).state
            if self._actor(events) != hero:
                observation = None
            else:
                observation = build_observation(events, observer_seat=hero, after_sequence=events[-1].sequence)
        if observation is None:
            return self._fast_solver.not_ready(
                decision_fingerprint=fingerprint,
                hand_id=hand_id,
                sequence=events[-1].sequence,
                street=state.street,
                budget_tier=budget_tier,
            ).to_dict()
        try:
            range_beliefs = PublicEventBeliefConsumer().beliefs_at(
                _public_stream(events),
                observer_visible_cards=observation.own_hole_cards,
            )
        except Exception:
            # Range V2 failure is intentionally non-blocking; FastSolver records
            # the uniform L1 fallback in source/rangeStatus/limitations.
            range_beliefs = None
        return self._fast_solver.solve(
            observation,
            decision_fingerprint=fingerprint,
            range_beliefs=range_beliefs,
            budget_tier=budget_tier,
        ).to_dict()

    def reconciliation(self, session_id: str, request: dict[str, object]) -> dict[str, object]:
        """Compare L0 and L1.5 for one frozen, current Hero decision snapshot."""

        hand_id = request.get("handId")
        fingerprint = request.get("decisionFingerprint")
        budget_tier = request.get("budgetTier", "standard")
        if not isinstance(hand_id, str) or not isinstance(fingerprint, str):
            raise ContinuousTableError("invalid_reconciliation_request", "handId and decisionFingerprint are required strings")
        if budget_tier not in {"quick", "standard", "deep"}:
            raise ContinuousTableError("invalid_reconciliation_request", "budgetTier must be quick, standard, or deep")
        with self._lock:
            stored = self._recover(session_id)
            metadata = self._metadata(session_id)
            current = self._projection(stored, metadata)
            if current["handId"] != hand_id:
                raise ContinuousTableError("stale_decision", "reconciliation request is not for the current hand", conflict=True)
            if current["fingerprint"] != fingerprint:
                raise ContinuousTableError("stale_decision", "reconciliation request does not match the current decision", conflict=True)
            hero = int(metadata["hero_seat"])
            events = tuple(item.event for item in self.event_store.read(hand_id))
            state = replay_hand(events).state
            identity = ReconciliationIdentityV1(
                fingerprint=fingerprint, hand_id=hand_id, sequence=events[-1].sequence,
                street=state.street,
            )
            if not state.hand_in_progress or self._actor(events) != hero:
                return _not_ready_reconciliation(identity).to_dict()
            try:
                observation = build_observation(
                    events, observer_seat=hero, after_sequence=events[-1].sequence
                )
            except Exception:
                # No private fallback is possible without a verified decision snapshot.
                return _not_ready_reconciliation(identity).to_dict()
        advisor = FormulaAdvisorFactory().create().evaluate(
            observation, decision_fingerprint=fingerprint
        ).to_dict()
        try:
            range_beliefs = PublicEventBeliefConsumer().beliefs_at(
                _public_stream(events), observer_visible_cards=observation.own_hole_cards,
            )
        except Exception:
            range_beliefs = None
        try:
            solver = self._fast_solver.solve(
                observation, decision_fingerprint=fingerprint,
                range_beliefs=range_beliefs, budget_tier=budget_tier,
            ).to_dict()
        except Exception:
            # L0 must remain a usable independent baseline if L1.5 fails.
            solver = unavailable_simulation(identity)
        return reconcile_decision(
            identity=identity, legal_actions=observation.legal_actions, pot=observation.pot,
            hero_stack=observation.stacks[hero],
            hero_commitment=observation.street_commitments[hero],
            advisor=advisor, solver=solver,
        ).to_dict()

    def reviews(self, session_id: str, hand_id: str | None = None) -> dict[str, object]:
        with self._lock:
            metadata = self._metadata(session_id)
            hero = int(metadata["hero_seat"])
            self._materialize_completed(session_id)
            reader = TableReviewReader(self.path)
            try:
                if hand_id is not None:
                    review = reader.get(session_id, hand_id, hero)
                    return {"available": review is not None, "unavailableReason": None if review else "review_not_ready", "review": None if review is None else public_review(review)}
                reviews = reader.list(session_id, hero)
                return {"available": bool(reviews), "unavailableReason": None if reviews else "review_not_ready", "reviews": [public_review(review) for review in reviews]}
            finally:
                reader.close()

    def _materialize_completed(self, session_id: str) -> None:
        stored = self._recover(session_id)
        hero = int(self._metadata(session_id)["hero_seat"])
        for hand_id in stored.session.completed_hand_ids:
            self._review_service.apply_hand(session_id=session_id, hand_id=hand_id, hero_seat=hero)

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
                self._review_service.apply_hand(session_id=stored.session.session_id, hand_id=active.hand_id, hero_seat=int(metadata["hero_seat"]))
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
        hole_cards_by_seat = {
            event.payload.seat_id: event.payload.cards
            for event in events
            if isinstance(event.payload, HoleCardsRecordedPayloadV1)
        }
        hero_cards = hole_cards_by_seat.get(hero, ())
        actor = None if not events or state is None or not state.hand_in_progress else self._actor(events)
        legal = ()
        if actor == hero:
            legal = build_observation(events, observer_seat=hero, after_sequence=state.applied_sequence).legal_actions
        folded = set(() if state is None else state.folded_seats)
        live_contenders = set(hole_cards_by_seat) - folded
        revealed_hole_cards = (
            {
                seat_id: cards
                for seat_id, cards in hole_cards_by_seat.items()
                if seat_id in live_contenders
            }
            if state is not None
            and not state.hand_in_progress
            and len(live_contenders) >= 2
            else {}
        )
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
            "seats": [
                {
                    "seatId": seat.seat_id,
                    "stack": (seat.stack if state is None else state.stacks[seat.seat_id]),
                    "status": "folded" if seat.seat_id in folded else ("active" if session.active_hand else "complete"),
                    "committed": 0 if state is None else state.street_commitments.get(seat.seat_id, 0),
                    **(
                        {"revealedHoleCards": list(revealed_hole_cards[seat.seat_id])}
                        if seat.seat_id in revealed_hole_cards
                        else {}
                    ),
                }
                for seat in session.topology.seats
            ],
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


def _advisor_projection_fallback(
    *, current: dict[str, object], hand_id: str, fingerprint: str, sequence: int, street: str
) -> dict[str, object]:
    """Last-resort L0 envelope derived exclusively from the projected legal actions."""

    legal = current["heroLegalActions"]
    assert isinstance(legal, list)
    preferred = next(
        (item for item in legal if isinstance(item, dict) and item.get("action") == "check"),
        next((item for item in legal if isinstance(item, dict) and item.get("action") == "call"), legal[0]),
    )
    assert isinstance(preferred, dict)
    amount = preferred.get("minAmount")
    semantics = preferred["amountSemantics"]
    return {
        "status": "degraded",
        "recommendedAction": {
            "action": preferred["action"], "amountSemantics": semantics,
            "amount": None if semantics == "none" else amount,
            "reason": "a safe legal fallback was selected from the current authoritative action set",
        },
        "source": "safe_legal_fallback", "version": "formula-advisor/v1",
        "confidence": "limited", "explanationKey": "advisor.degraded.safe_legal_action",
        "limitations": ["L0 fallback uses only current public facts, Hero visibility, and legal actions."],
        "decision": {"fingerprint": fingerprint, "handId": hand_id, "sequence": sequence, "street": street},
    }


def _live_hu_river_l2(*, events, observation, decision_fingerprint: str, cache: L2Cache) -> L2RecommendationInput | None:
    """Build a bounded L2 input from public-event posteriors only.

    This adapter deliberately never reads recorded opponent holes, terminal
    reveals, or future events.  Both seats receive the current public range
    snapshot after the Hero-visible blockers have been removed.  A small,
    deterministic top-support projection keeps a cache miss within the live
    decision budget; its exact support is part of the range fingerprint.
    """

    street = observation.street.value if hasattr(observation.street, "value") else str(observation.street)
    if street != "river" or len(observation.active_seats) != 2 or len(observation.board) != 5:
        return None
    # This is the only private value permitted across the solver boundary.  It
    # came from the acting Hero's ObservationV1; the public event stream below
    # explicitly removes every recorded hole-card and terminal event.
    hero_hole_cards = tuple(observation.own_hole_cards)
    if len(hero_hole_cards) != 2:
        return None
    legal = {item.action.value: item for item in observation.legal_actions}
    bet = legal.get("bet")
    if set(legal) != {"check", "bet"} or bet is None or bet.min_amount is None or bet.max_amount != bet.min_amount or bet.amount_semantics.value != "by":
        return None
    players = (observation.observer_seat, next(seat for seat in observation.active_seats if seat != observation.observer_seat))
    stacks = dict(observation.stacks)
    if bet.min_amount <= 0 or bet.min_amount > min(stacks[seat] for seat in players):
        return None
    try:
        beliefs = PublicEventBeliefConsumer().beliefs_at(
            _public_stream(events), observer_visible_cards=observation.own_hole_cards,
        )
        projected: list[tuple[int, tuple[RangeCombo, ...]]] = []
        material: list[object] = []
        for seat in players:
            result = beliefs.get(seat)
            snapshot = None if result is None else result.current
            if snapshot is None:
                return None
            # Range snapshots are already public-event conditioned and contain
            # Hero-visible blockers. Never substitute recorded holes here.
            ranked = sorted(snapshot.combos.items(), key=lambda item: (-item[1].probability, item[0]))[:16]
            combos = tuple(RangeCombo(cards=cards_from_key(key), weight=float(combo.probability)) for key, combo in ranked if float(combo.probability) > 0)
            if not combos:
                return None
            projected.append((seat, combos))
            material.append((seat, snapshot.snapshot_id, [(combo.cards, combo.weight) for combo in combos], result.provenance.policy_fingerprint if result.provenance else None))
    except Exception:
        return None
    tree_material = {"legal": [(name, item.min_amount, item.max_amount) for name, item in sorted(legal.items())], "bet": bet.min_amount}
    tree_fingerprint = "sha256:" + hashlib.sha256(json.dumps(tree_material, sort_keys=True).encode()).hexdigest()
    range_fingerprint = "sha256:" + hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    source = L2RiverInput(
        game_fingerprint=decision_fingerprint,
        tree_fingerprint=tree_fingerprint,
        range_fingerprint=range_fingerprint,
        solver_version="riverline-l2-cfr/v1",
        players=players,
        acting_seat=players[0], pot=observation.pot,
        stacks=tuple((seat, stacks[seat]) for seat in players), board=tuple(observation.board),
        ranges=tuple(projected), tree=RiverBetTree(bet_amount=bet.min_amount),
        seed=int(hashlib.sha256(decision_fingerprint.encode()).hexdigest()[:12], 16),
        budget=L2Budget(iterations=8, soft_timeout_ms=250, hard_timeout_ms=400),
        hero_hole_cards=hero_hole_cards,
    )
    result = solve_hu_river(source, cache=cache)
    if not isinstance(result, L2Result):
        return None
    return L2RecommendationInput(result=result, decision_fingerprint=decision_fingerprint, utility_fingerprint="chips-v1")


def _not_ready_reconciliation(identity: ReconciliationIdentityV1):
    from .decision_reconciliation import reconcile_decision

    unavailable = unavailable_simulation(identity, reason="not_hero_decision")
    return reconcile_decision(
        identity=identity, legal_actions=(), pot=0, hero_stack=0, hero_commitment=0,
        advisor={
            "status": "not_ready", "recommendedAction": None,
            "source": "deterministic_formula", "version": "formula-advisor/v1",
            "limitations": ["L0 Advisor is only applicable to an active Hero decision."],
            "decision": identity.to_dict(),
        }, solver={**unavailable, "status": "not_ready"},
    )


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
