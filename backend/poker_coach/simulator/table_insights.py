"""Read-only Table Insights composition; never serializes opponent hole cards."""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from threading import Lock

from poker_coach.persistence.session_stats_store import SQLiteSessionStatsStore
from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer, SeatBeliefResultV1
from poker_coach.ranges.aggregation import aggregate_belief_to_matrix169
from poker_coach.simulator.contracts import ActionTakenPayloadV1, BoardDealtPayloadV1, HandEventV1, HandStartedPayloadV1
from poker_coach.simulator.formula_advisor import FormulaAdvisorFactory
from poker_coach.simulator.observation import build_observation


_PROJECTION_CACHE_MAX = 16
_PROJECTION_CACHE: OrderedDict[
    tuple[int, int, Decimal, Decimal], tuple[object, ...]
] = OrderedDict()
_PROJECTION_CACHE_LOCK = Lock()


class _ImmutableWireDict(dict[str, object]):
    def _blocked(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("cached projection values are immutable")

    __setitem__ = _blocked
    __delitem__ = _blocked
    clear = _blocked
    pop = _blocked
    popitem = _blocked
    setdefault = _blocked
    update = _blocked
    __ior__ = _blocked


def build_table_insights(
    *, events: tuple[HandEventV1, ...], session_id: str, hero_seat: int,
    database_path: str, decision_fingerprint: str | None = None,
) -> dict[str, object]:
    """Compose L0, opponent marginals, and projected stats from safe inputs."""
    if not events:
        return {"schemaVersion": 1, "available": False, "unavailableReason": "hand_not_ready"}
    public = _public_stream(events)
    try:
        beliefs = PublicEventBeliefConsumer().beliefs_at(
            public, observer_visible_cards=_hero_cards(events, hero_seat)
        )
        opponents = [
            _compressed_belief(result, events[0].hand_id)
            for seat, result in beliefs.items() if seat != hero_seat
        ]
    except Exception:
        # Range is an independent optional consumer. Its outage must not remove L0.
        opponents = []
    advisor: dict[str, object]
    try:
        observation = build_observation(events, observer_seat=hero_seat, after_sequence=events[-1].sequence)
    except Exception:
        # This only covers terminal hands, a non-Hero turn, or a malformed/recovered
        # non-decision stream. It is never the ordinary Hero-decision support path.
        advisor = {
            "available": False,
            "status": "not_ready",
            "unavailableReason": "not_hero_decision_or_terminal",
            "decision": {"fingerprint": decision_fingerprint, "handId": events[0].hand_id,
                         "sequence": events[-1].sequence},
        }
    else:
        result = FormulaAdvisorFactory().create().evaluate(
            observation, decision_fingerprint=decision_fingerprint
        )
        advisor = {
            "available": result.status in {"ready", "degraded"},
            "status": result.status,
            "result": result.to_dict(),
            "provenance": {
                "source": result.source,
                "version": result.version,
                "degraded": result.status == "degraded",
            },
        }
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


def _compressed_belief(result: object, hand_id: str) -> dict[str, object]:
    """UI-safe 169-cell projection. Never pass combo keys or hole cards over this seam."""
    assert isinstance(result, SeatBeliefResultV1)
    base: dict[str, object] = {
        "seatId": result.seat_id, "available": result.available,
        "unavailableReason": result.unavailable_reason, "inactive": result.inactive,
        "approximate": result.approximate, "approximationReason": result.approximation_reason,
        "decision": {"handId": hand_id, "afterSequence": result.after_sequence},
    }
    if not result.available or result.current is None or result.prior is None or result.provenance is None:
        return base
    compact_matrix, top_classes, width, effective_width = _projection(result)
    change = result.current.update.action_label if result.current.update else None
    return {
        **base, "rangeWidthPct": float(width), "rangeWidthCombos": float(effective_width),
        "confidence": result.provenance.trust_level,
        "confidenceScore": float(result.provenance.confidence),
        "source": result.provenance.provider, "version": result.provenance.version,
        "evidenceGrade": result.provenance.evidence_grade,
        "coverageStatus": result.provenance.coverage_status,
        "policyFingerprint": result.provenance.policy_fingerprint,
        "fallbackReason": result.provenance.fallback_reason,
        "dataVersion": result.provenance.version,
        "changeReason": change or "初始先验", "matrix169": compact_matrix,
        "topClasses": top_classes,
        "limitations": [
            "这是由公开行动、位置、公共牌与 Hero blockers 得出的独立边际估计。",
            "不含对手私牌，不是 GTO、Solver 或联合范围。",
        ],
    }


def _projection(
    result: SeatBeliefResultV1,
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]], float, float]:
    assert result.current is not None and result.prior is not None
    cacheable = bool(
        result.current.model_config.get("frozen")
        and result.prior.model_config.get("frozen")
    )
    current_combos = result.current.combos
    prior_combos = result.prior.combos
    # The 169 projection depends on immutable combo distributions and masses,
    # not snapshot identity or per-action metadata such as the observed size.
    # Range replay intentionally reuses a normalized combo map for actions in
    # the same public likelihood bucket, so keying on snapshots would repeat
    # the full aggregation for an otherwise identical decision distribution.
    cache_key = (
        id(current_combos), id(prior_combos),
        result.current.retained_mass, result.prior.prior_mass,
    )
    cached = None
    if cacheable:
        with _PROJECTION_CACHE_LOCK:
            candidate = _PROJECTION_CACHE.get(cache_key)
            if (
                candidate is not None
                and candidate[0] is current_combos
                and candidate[1] is prior_combos
                and candidate[2] == result.current.retained_mass
                and candidate[3] == result.prior.prior_mass
            ):
                _PROJECTION_CACHE.move_to_end(cache_key)
                cached = candidate
    if cached is None:
        matrix = aggregate_belief_to_matrix169(result.current, prior=result.prior)
        immutable_matrix = _ImmutableWireDict({
            key: _ImmutableWireDict({
                "probabilityMass": str(cell.probability_mass),
                "comboCount": cell.combo_count,
            })
            for key, cell in matrix.items()
        })
        top_rows = tuple(
            (key, str(cell.probability_mass))
            for key, cell in sorted(
                matrix.items(),
                key=lambda item: (-item[1].probability_mass, item[0]),
            )[:6]
        )
        width = float(
            result.current.retained_mass / result.prior.prior_mass * 100
            if result.prior.prior_mass else 0
        )
        concentration = sum(
            combo.probability * combo.probability
            for combo in result.current.combos.values()
        )
        effective_width = float(
            Decimal("0") if not concentration else Decimal("1") / concentration
        )
        cached = (
            current_combos, prior_combos,
            result.current.retained_mass, result.prior.prior_mass,
            immutable_matrix, top_rows, width, effective_width,
        )
        if cacheable:
            with _PROJECTION_CACHE_LOCK:
                _PROJECTION_CACHE[cache_key] = cached
                _PROJECTION_CACHE.move_to_end(cache_key)
                while len(_PROJECTION_CACHE) > _PROJECTION_CACHE_MAX:
                    _PROJECTION_CACHE.popitem(last=False)
    top_rows = cached[5]
    return (
        dict(cached[4]),
        [
            {"hand": key, "probabilityMass": probability}
            for key, probability in top_rows
        ],
        cached[6],
        cached[7],
    )
