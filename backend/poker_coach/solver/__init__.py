"""Solver integration: normalized spot/result contracts, adapter, sidecar
client and cache.

The solving engine itself (postflop-solver, AGPL) runs exclusively in the
isolated sidecar container; nothing here imports or ships solver-engine
code. The contracts in ``types`` are the only boundary crossing it.
"""

from .adapter import build_spot, parse_result, range_to_string, spot_to_config_json
from .cache import SolveCache, solve_hash
from .client import SidecarClient
from .types import (
    SolveMetadata,
    SolverHand,
    SolverNode,
    SolverSpot,
    SolverUnsupportedError,
    SolveResult,
)

__all__ = [
    "build_spot",
    "parse_result",
    "range_to_string",
    "spot_to_config_json",
    "SidecarClient",
    "SolveCache",
    "solve_hash",
    "SolverSpot",
    "SolveResult",
    "SolveMetadata",
    "SolverNode",
    "SolverHand",
    "SolverUnsupportedError",
]
