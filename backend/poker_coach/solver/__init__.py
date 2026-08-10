"""Solver integration: normalized spot/result contracts, adapter, sidecar
client and cache.

The solving engine itself (postflop-solver, AGPL) runs exclusively in the
isolated sidecar container; nothing here imports or ships solver-engine
code. The contracts in ``types`` are the only boundary crossing it.
"""

from .adapter import build_spot, parse_result, range_to_string, spot_to_config_json
from .analyzer import HandAnalysis, NodeAnalysis, SolverAnalysis, analyze, classify_hand
from .artifact import hero_node_of, solve_result_to_artifact
from .cache import SolveCache, solve_hash, solve_with_cache
from .client import SidecarClient, SolverCancelled
from .evidence import solver_evidence_items
from .jobs import SolverJobQueue, SolverQueueUnavailable
from .presolver import common_spots, pre_solve
from .types import (
    SolveMetadata,
    SolverHand,
    SolverNode,
    SolverSpot,
    SolverUnsupportedError,
    SolveResult,
)
from .worker import SolverWorker

__all__ = [
    "build_spot",
    "parse_result",
    "range_to_string",
    "spot_to_config_json",
    "analyze",
    "classify_hand",
    "SolverAnalysis",
    "NodeAnalysis",
    "HandAnalysis",
    "hero_node_of",
    "solve_result_to_artifact",
    "solver_evidence_items",
    "SidecarClient",
    "SolverCancelled",
    "SolveCache",
    "solve_hash",
    "solve_with_cache",
    "SolverJobQueue",
    "SolverQueueUnavailable",
    "common_spots",
    "pre_solve",
    "SolverWorker",
    "SolverSpot",
    "SolveResult",
    "SolveMetadata",
    "SolverNode",
    "SolverHand",
    "SolverUnsupportedError",
]
