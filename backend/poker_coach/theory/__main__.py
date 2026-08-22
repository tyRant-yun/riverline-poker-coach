"""Machine-readable entry point for the offline theory benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import FixtureError, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen theory benchmark fixtures")
    parser.add_argument("--fixtures", type=Path, default=None, help="fixture directory (defaults to bundled corpus)")
    parser.add_argument("--verify-corpus", action="store_true", help="exit zero when intentional red fixtures are rejected as declared")
    args = parser.parse_args()
    try:
        result = run_benchmark(args.fixtures)
    except FixtureError as exc:
        print(json.dumps({"gatePassed": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(2) from exc
    print(json.dumps(result.model_dump(mode="json", by_alias=True), sort_keys=True))
    raise SystemExit(0 if (result.corpus_expectations_met if args.verify_corpus else result.gate_passed) else 1)


if __name__ == "__main__":
    main()
