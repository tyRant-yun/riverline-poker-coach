"""Project-owned contracts for stage 3 analysis results."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import Field, StrictInt, model_validator

from poker_coach.domain.models import (
    AnalysisLevel,
    Card,
    ChipAmount,
    DomainModel,
    EquityAlgorithm,
    EvidenceBundle,
    Weight,
)


class HandCategory(str, Enum):
    HIGH_CARD = "high_card"
    ONE_PAIR = "one_pair"
    TWO_PAIR = "two_pair"
    THREE_OF_A_KIND = "three_of_a_kind"
    STRAIGHT = "straight"
    FLUSH = "flush"
    FULL_HOUSE = "full_house"
    FOUR_OF_A_KIND = "four_of_a_kind"
    STRAIGHT_FLUSH = "straight_flush"


class DrawType(str, Enum):
    FLUSH_DRAW = "flush_draw"
    BACKDOOR_FLUSH_DRAW = "backdoor_flush_draw"
    OPEN_ENDED_STRAIGHT_DRAW = "open_ended_straight_draw"
    GUTSHOT = "gutshot"
    DOUBLE_GUTTER = "double_gutter"
    COMBO_DRAW = "combo_draw"


Ratio = Annotated[Decimal, Field(ge=0, le=1)]


class BasicMetrics(DomainModel):
    current_pot: ChipAmount
    call_cost: ChipAmount
    pot_after_call: ChipAmount
    effective_stack: ChipAmount
    pot_odds: Ratio
    required_equity: Ratio
    spr: Decimal | None = Field(default=None, ge=0)
    risk_reward_ratio: Decimal | None = Field(default=None, ge=0)
    bet_to_pot_ratio: Decimal | None = Field(default=None, ge=0)


class HandAnalysis(DomainModel):
    cards: tuple[Card, ...]
    category: HandCategory
    made_hand: str
    overcards: tuple[Card, ...] = ()
    draws: tuple[DrawType, ...] = ()
    straight_outs: tuple[Card, ...] = ()
    flush_outs: tuple[Card, ...] = ()
    out_cards: tuple[Card, ...] = ()
    out_count: StrictInt = Field(ge=0)
    counterfeit_risk_cards: tuple[Card, ...] = ()


class BoardAnalysis(DomainModel):
    board: tuple[Card, ...]
    labels: tuple[str, ...] = ()
    suit_counts: dict[str, StrictInt] = Field(default_factory=dict)
    rank_counts: dict[str, StrictInt] = Field(default_factory=dict)
    rainbow: bool = False
    two_tone: bool = False
    monotone: bool = False
    paired: bool = False
    double_paired: bool = False
    connectedness: str = "disconnected"
    high_card_ranks: tuple[str, ...] = ()
    low_card_ranks: tuple[str, ...] = ()
    static_or_dynamic: str = "static"
    next_street_change_cards: tuple[Card, ...] = ()
    possible_nut_hands: tuple[str, ...] = ()
    possible_nut_combos: tuple[tuple[Card, Card], ...] = ()
    nut_combo_count: StrictInt = Field(ge=0)


class WeightedCombo(DomainModel):
    cards: tuple[Card, Card]
    weight: Weight


class RangeAnalysis(DomainModel):
    total_combos: StrictInt = Field(ge=0)
    weighted_combos: Decimal = Field(ge=0)
    value_combos: StrictInt = Field(ge=0)
    bluff_combos: StrictInt = Field(ge=0)
    draw_combos: StrictInt = Field(ge=0)
    blocked_combos: StrictInt = Field(ge=0)
    blocked_weight: Decimal = Field(ge=0)
    blocker_cards: tuple[Card, ...] = ()
    polarity: str = "merged"
    range_advantage: Decimal | None = Field(default=None, ge=-1, le=1)
    nut_advantage: Decimal | None = Field(default=None, ge=-1, le=1)
    heuristic: bool = True


class RangeComparison(DomainModel):
    hero: RangeAnalysis
    villain: RangeAnalysis
    range_advantage: Decimal | None = Field(default=None, ge=-1, le=1)
    nut_advantage: Decimal | None = Field(default=None, ge=-1, le=1)
    equity_distribution: dict[str, Decimal] = Field(default_factory=dict)
    heuristic: bool = True


class EquityResult(DomainModel):
    algorithm: EquityAlgorithm
    source_level: AnalysisLevel
    hero_wins: StrictInt = Field(ge=0)
    villain_wins: StrictInt = Field(ge=0)
    ties: StrictInt = Field(ge=0)
    trials: StrictInt = Field(gt=0)
    hero_equity: Ratio
    villain_equity: Ratio
    tie_probability: Ratio
    random_seed: StrictInt | None = Field(default=None, ge=0)
    confidence_interval: tuple[Ratio, Ratio] | None = None
    standard_error: Decimal | None = Field(default=None, ge=0)
    weighted: bool = False

    @model_validator(mode="after")
    def validate_probabilities(self) -> EquityResult:
        if abs(
            self.hero_equity + self.villain_equity - Decimal("1")
        ) > Decimal("0.0000000001"):
            raise ValueError("hero and villain equity must sum to one")
        if self.algorithm is EquityAlgorithm.MONTE_CARLO and self.random_seed is None:
            raise ValueError("Monte Carlo results require a random_seed")
        if self.confidence_interval is not None:
            low, high = self.confidence_interval
            if low > high:
                raise ValueError("confidence interval lower bound cannot exceed upper bound")
        return self


class AnalysisResult(DomainModel):
    analysis_version: str
    scenario_hash: str
    rules_engine_version: str
    metrics: BasicMetrics
    hand: HandAnalysis
    board: BoardAnalysis
    equity: EquityResult | None = None
    range_analysis: RangeAnalysis | None = None
    range_comparison: RangeComparison | None = None
    evidence: EvidenceBundle
    warnings: tuple[str, ...] = ()


class AnalysisCancelled(RuntimeError):
    """Raised when a caller cancels a long equity calculation."""


class AnalysisTimeout(RuntimeError):
    """Raised when a calculation exceeds its caller-provided time budget."""


class InvalidAnalysisInput(ValueError):
    """Raised for empty ranges, duplicate cards, or unsupported inputs."""
