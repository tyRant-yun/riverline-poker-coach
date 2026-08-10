"""Solver boundary models: normalized request/result contracts.

These types are the ONLY contract between the Poker Coach domain and the
external solver sidecar. Solver-engine types never cross this module
(postflop-solver / TexasSolver types are confined to the sidecar process).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from poker_coach.domain.models import Card, DomainModel, Street


class SolverUnsupportedError(ValueError):
    """Raised when a scenario cannot be expressed as a solver spot."""


class SolverSpot(DomainModel):
    """Normalized postflop solving request (mirrors the sidecar config)."""

    schema_version: Annotated[int, Field(ge=1)] = 1
    street: Street
    board: tuple[Card, Card, Card]
    turn: Card | None = None
    river: Card | None = None
    oop_range: str = Field(min_length=1)
    ip_range: str = Field(min_length=1)
    starting_pot: Annotated[int, Field(ge=1)]
    effective_stack: Annotated[int, Field(ge=1)]
    rake_rate: float = 0.0
    rake_cap: float = 0.0
    bet_sizes: str = "50%, e, a"
    raise_sizes: str = "2.5x"
    add_allin_threshold: float = 1.5
    force_allin_threshold: float = 0.15
    merging_threshold: float = 0.1
    max_iterations: Annotated[int, Field(ge=1, le=50_000)] = 400
    target_exploitability_frac: Annotated[float, Field(gt=0.0, le=1.0)] = 0.005
    dump_response_to_action: Annotated[int, Field(ge=0)] = 1


class SolveMetadata(DomainModel):
    solver: str
    version: str
    street: str
    max_iterations: int
    exploitability_chips: float
    target_exploitability_chips: float
    solve_time_ms: int = 0
    memory_usage_gb: float = 0.0
    memory_usage_compressed_gb: float = 0.0
    compressed: bool = False


class SolverHand(DomainModel):
    combo: str = Field(min_length=4, max_length=4)
    weight: float
    equity: float
    ev: float
    strategy: dict[str, float]


class SolverNode(DomainModel):
    actions: tuple[str, ...]
    player: Annotated[int, Field(ge=0, le=1)]
    hands: tuple[SolverHand, ...]


class SolveResult(DomainModel):
    """Normalized solver output: metadata + root node (+ optional response node)."""

    metadata: SolveMetadata
    root: SolverNode
    response_node: SolverNode | None = None
