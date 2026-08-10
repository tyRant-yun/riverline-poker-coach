"""Standalone worker entry point: ``python -m poker_coach.jobs``."""

import argparse

from poker_coach.jobs import AnalysisWorker, RedisJobQueue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    queue = RedisJobQueue(args.redis_url)
    worker = AnalysisWorker(queue, default_timeout=args.timeout)
    worker.run_forever()


if __name__ == "__main__":
    main()
