"""Standalone solver worker entry point: ``python -m poker_coach.solver``."""

import argparse

from poker_coach.solver import SidecarClient, SolverJobQueue, SolverWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume solver solve jobs from Redis.")
    parser.add_argument("--redis-url", required=True, help="Redis URL (e.g. redis://127.0.0.1:6379/0)")
    parser.add_argument("--image", default="poker-coach-sidecar", help="sidecar docker image")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="per-solve timeout")
    args = parser.parse_args()

    queue = SolverJobQueue(args.redis_url)
    client = SidecarClient(image=args.image, timeout_seconds=args.timeout_seconds)
    SolverWorker(queue, client=client).run_forever()


if __name__ == "__main__":
    main()
