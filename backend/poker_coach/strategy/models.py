"""Project-owned contracts for strategy provenance and matching."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field, StrictInt, model_validator

from poker_coach.domain.models import (
    AnalysisLevel,
    DomainModel,
    GameVariant,
    SeatPosition,
    Street,
    Weight,
)


class MatchLevel(str, Enum):
    EXACT = "exact"
    COMPATIBLE = "compatible"
    APPROXIMATE = "approximate"
    NO_MATCH = "no_match"


class StrategyDifference(DomainModel):
    field: str = Field(min_length=1, max_length=64)
    requested: Any = None
    artifact: Any = None
    impact: str = Field(min_length=1, max_length=256)


class StrategyRecommendation(DomainModel):
    action: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=512)
    frequency: Weight | None = None
    ev: Decimal | None = None
    source_level: AnalysisLevel
    quantitative_basis: str | None = None

    @model_validator(mode="after")
    def validate_quantitative_basis(self) -> StrategyRecommendation:
        if self.frequency is not None or self.ev is not None:
            if self.source_level not in {
                AnalysisLevel.CURATED,
                AnalysisLevel.SOLVER_BACKED,
            }:
                raise ValueError("quantitative strategy data requires curated or solver_backed source")
            if not self.quantitative_basis:
                raise ValueError("quantitative strategy data requires quantitative_basis")
        return self


class StrategyArtifact(DomainModel):
    artifact_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=256)
    license: str = Field(min_length=1, max_length=128)
    creator: str = Field(min_length=1, max_length=128)
    game_variant: GameVariant = GameVariant.NLHE
    table_size: StrictInt = Field(ge=2, le=6)
    stack_min_bb: Decimal = Field(ge=0)
    stack_max_bb: Decimal = Field(ge=0)
    rake_signature: str = Field(min_length=1, max_length=128)
    hero_position: SeatPosition | None = None
    villain_position: SeatPosition | None = None
    street: Street | None = None
    action_signature: tuple[str, ...] | None = None
    board_labels: tuple[str, ...] | None = None
    hero_range_id: str | None = None
    villain_range_id: str | None = None
    bet_size_signature: tuple[str, ...] | None = None
    source_level: AnalysisLevel
    compatible_frequency_approved: bool = False
    quantitative_basis: str | None = None
    assumptions: tuple[str, ...] = ()
    recommendations: tuple[StrategyRecommendation, ...] = ()

    @model_validator(mode="after")
    def validate_artifact(self) -> StrategyArtifact:
        if self.stack_max_bb < self.stack_min_bb:
            raise ValueError("stack_max_bb cannot be below stack_min_bb")
        actions = [recommendation.action for recommendation in self.recommendations]
        if len(actions) != len(set(actions)):
            raise ValueError("strategy recommendation actions must be unique")
        has_quantitative_data = any(
            recommendation.frequency is not None or recommendation.ev is not None
            for recommendation in self.recommendations
        )
        if has_quantitative_data and not self.quantitative_basis:
            raise ValueError("quantitative strategy artifact requires quantitative_basis")
        if self.compatible_frequency_approved and not has_quantitative_data:
            raise ValueError("compatible frequency approval requires quantitative recommendations")
        return self


class StrategyMatch(DomainModel):
    library_version: str = Field(min_length=1, max_length=64)
    level: MatchLevel
    artifact_id: str | None = None
    artifact_version: str | None = None
    similarity: Decimal = Field(ge=0, le=1)
    confidence: Decimal = Field(ge=0, le=1)
    differences: tuple[StrategyDifference, ...] = ()
    can_quote_frequencies: bool = False
    source_level: AnalysisLevel = AnalysisLevel.PRINCIPLE_ONLY
    recommendations: tuple[StrategyRecommendation, ...] = ()
    explanation: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_frequency_boundary(self) -> StrategyMatch:
        has_quantitative_data = any(
            recommendation.frequency is not None or recommendation.ev is not None
            for recommendation in self.recommendations
        )
        if self.can_quote_frequencies:
            if self.level not in {MatchLevel.EXACT, MatchLevel.COMPATIBLE}:
                raise ValueError("frequencies require exact or approved compatible match")
            if not has_quantitative_data:
                raise ValueError("frequency permission requires quantitative recommendations")
        if self.level is MatchLevel.NO_MATCH and self.artifact_id is not None:
            raise ValueError("no_match cannot identify an artifact")
        return self
