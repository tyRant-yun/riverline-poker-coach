"""Pre-solve common spots so the live product never waits on the sidecar.

Deterministic spots (board/ranges/pot/stack/tree) hash to the same
solve_hash, so pre-solving populates the cache and requests hit in
milliseconds (docs/solver-integration-design.md §7, phase 5).
"""

from __future__ import annotations

import argparse
import threading
import time

from poker_coach.domain.models import Street

from .cache import SolveCache, solve_with_cache
from .client import SidecarClient
from .types import SolverSpot


def common_spots() -> tuple[SolverSpot, ...]:
    """Curated starter set: the phase-1 spike spot plus two board variants."""
    base = dict(
        street=Street.FLOP,
        board=("Ks", "7h", "2h"),
        oop_range="66+,A8s+,A5s-A4s,AJo+,K9s+,KQo,QTs+,JTs,96s+,85s+,75s+,65s,54s",
        ip_range="QQ-22,AQs-A2s,ATo+,K5s+,KJo+,Q8s+,J8s+,T7s+,96s+,86s+,75s+,64s+,53s+",
        starting_pot=500,
        effective_stack=9750,
        max_iterations=300,
    )
    variants = [
        {**base},
        {**base, "board": ("Ks", "7h", "2s")},  # two-tone variant
        {**base, "board": ("Ad", "9d", "6c")},  # disconnected ace-high variant
    ]
    return tuple(SolverSpot(**variant) for variant in variants)


def pre_solve(
    client: SidecarClient,
    cache: SolveCache,
    spots: tuple[SolverSpot, ...],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, str]:
    """Solve every spot through the cache; return {solve_hash: status}."""
    outcomes: dict[str, str] = {}
    for spot in spots:
        from .cache import solve_hash

        try:
            solve_with_cache(client, spot, cache, cancel_event=cancel_event)
            outcomes[solve_hash(spot)] = "solved"
        except Exception as exc:
            outcomes[solve_hash(spot)] = f"failed: {exc}"
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-solve common spots into the cache.")
    parser.add_argument("--cache", default=".data/solve-cache.sqlite3", help="cache db path")
    parser.add_argument("--image", default="poker-coach-sidecar", help="sidecar docker image")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    client = SidecarClient(image=args.image, timeout_seconds=args.timeout_seconds)
    cache = SolveCache(args.cache)
    started = time.monotonic()
    outcomes = pre_solve(client, cache, common_spots())
    for spot_hash, status in outcomes.items():
        print(f"{spot_hash[:12]} {status}")
    print(f"total {len(outcomes)} spots in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
