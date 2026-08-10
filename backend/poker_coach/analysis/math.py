"""Integer-chip poker math with Decimal ratios."""

from __future__ import annotations

from decimal import Decimal

from poker_coach.domain.models import SeatNumber, StateSnapshot

from .models import BasicMetrics


def calculate_metrics(
    snapshot: StateSnapshot,
    *,
    hero_seat: SeatNumber,
    villain_seat: SeatNumber | None = None,
    bet_amount: int | None = None,
) -> BasicMetrics:
    """Calculate current-node metrics without changing the replay snapshot."""

    pot = snapshot.pot
    call_cost = snapshot.legal_actions.call_amount or 0
    pot_after_call = pot + call_cost
    active_seats = [
        seat
        for seat, stack in snapshot.stacks.items()
        if seat not in snapshot.folded_seats and stack >= 0
    ]
    if villain_seat is not None:
        active_seats = [seat for seat in active_seats if seat in {hero_seat, villain_seat}]
    effective_stack = min((snapshot.stacks[seat] for seat in active_seats), default=0)
    pot_odds = (
        Decimal(call_cost) / Decimal(pot_after_call)
        if pot_after_call
        else Decimal("0")
    )
    spr = Decimal(effective_stack) / Decimal(pot) if pot else None
    risk_reward = Decimal(call_cost) / Decimal(pot) if pot else None
    bet_to_pot = Decimal(bet_amount) / Decimal(pot) if bet_amount is not None and pot else None
    return BasicMetrics(
        current_pot=pot,
        call_cost=call_cost,
        pot_after_call=pot_after_call,
        effective_stack=effective_stack,
        pot_odds=pot_odds,
        required_equity=pot_odds,
        spr=spr,
        risk_reward_ratio=risk_reward,
        bet_to_pot_ratio=bet_to_pot,
        active_player_count=len(active_seats),
    )
