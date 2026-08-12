"""Versioned project contracts exposed by rule-engine adapters."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from poker_coach.domain.models import Card, DomainModel, SeatNumber


class SeededDealV1(DomainModel):
    """Frozen deterministic deal returned by the PokerKit authority seam."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    hole_cards_by_seat: Annotated[
        dict[SeatNumber, tuple[Card, Card]], Field(min_length=2, max_length=8)
    ]
    board: Annotated[tuple[Card, ...], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def validate_unique_cards(self) -> SeededDealV1:
        cards = [
            card
            for hole_cards in self.hole_cards_by_seat.values()
            for card in hole_cards
        ]
        cards.extend(self.board)
        if len(cards) != len(set(cards)):
            raise ValueError("seeded deal cards must be unique")
        return self
