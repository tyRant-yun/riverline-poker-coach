"""Read-only Table Insights composition; never serializes opponent hole cards."""
from __future__ import annotations

from poker_coach.persistence.session_stats_store import SQLiteSessionStatsStore
from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer
from poker_coach.simulator.contracts import ActionTakenPayloadV1, BoardDealtPayloadV1, HandEventV1, HandStartedPayloadV1
from poker_coach.simulator.formula_advisor import FormulaAdvisorFactory
from poker_coach.simulator.observation import build_observation


def build_table_insights(*, events: tuple[HandEventV1, ...], session_id: str, hero_seat: int, database_path: str) -> dict[str, object]:
    """Compose L0, opponent marginals, and projected stats from safe inputs."""
    if not events:
        return {"schemaVersion": 1, "available": False, "unavailableReason": "hand_not_ready"}
    public = _public_stream(events)
    beliefs = PublicEventBeliefConsumer().beliefs_at(public, observer_visible_cards=_hero_cards(events, hero_seat))
    opponents = [
        {"seatId": seat, "available": result.available, "unavailableReason": result.unavailable_reason,
         "priorMass": None if result.prior is None else str(result.prior.prior_mass),
         "currentMass": None if result.current is None else str(result.current.retained_mass),
         "provenance": None if result.provenance is None else result.provenance.to_dict()}
        for seat, result in beliefs.items() if seat != hero_seat
    ]
    advisor: dict[str, object] = {"available": False, "unavailableReason": "not_hero_decision"}
    try:
        observation = build_observation(events, observer_seat=hero_seat, after_sequence=events[-1].sequence)
    except Exception:
        pass
    else:
        result = FormulaAdvisorFactory().create().evaluate(observation)
        advisor = {"available": True, "result": result.to_dict(), "provenance": {"source": result.source, "version": result.version, "degraded": False}}
    stats_store = SQLiteSessionStatsStore(database_path)
    try:
        stats = stats_store.load(session_id)
    finally:
        stats_store.close()
    stats_by_seat = [
        {"seatId": seat, "vpip": value.vpip_rate, "pfr": value.pfr_rate, "threeBet": value.three_bet_rate}
        for seat, value in stats.by_seat.items()
    ]
    return {"schemaVersion": 1, "available": True, "publicEventSequence": events[-1].sequence,
            "advisor": advisor, "seatBeliefs": opponents,
            "stats": {"available": bool(stats_by_seat), "unavailableReason": None if stats_by_seat else "stats_not_ready", "bySeat": stats_by_seat, "fingerprint": stats.fingerprint}}


def _public_stream(events: tuple[HandEventV1, ...]) -> tuple[HandEventV1, ...]:
    allowed = (HandStartedPayloadV1, ActionTakenPayloadV1, BoardDealtPayloadV1)
    return tuple(event.model_copy(update={"sequence": index}) for index, event in enumerate((event for event in events if isinstance(event.payload, allowed)), start=1))


def _hero_cards(events: tuple[HandEventV1, ...], hero_seat: int) -> tuple[str, ...]:
    from poker_coach.simulator.contracts import HoleCardsRecordedPayloadV1
    return next((payload.cards for event in events if isinstance((payload := event.payload), HoleCardsRecordedPayloadV1) and payload.seat_id == hero_seat), ())
