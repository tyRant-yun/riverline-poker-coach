"""Machine-readable entry point for the offline theory benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import FixtureError, run_benchmark, run_provider_release_gate, run_provider_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen theory benchmark fixtures")
    parser.add_argument("--fixtures", type=Path, default=None, help="fixture directory (defaults to bundled corpus)")
    parser.add_argument("--verify-corpus", action="store_true", help="verify the intentional red/green fixture corpus; this is not the release gate")
    parser.add_argument("--provider-smoke", action="store_true", help="run the legacy single-spot PolicyArtifact smoke only")
    args = parser.parse_args()
    try:
        if args.provider_smoke:
            result = run_provider_smoke()
            print(json.dumps(result.model_dump(mode="json", by_alias=True), sort_keys=True))
            raise SystemExit(0 if result.gate_passed else 1)
        result = run_benchmark(args.fixtures) if args.verify_corpus else run_provider_release_gate()
    except FixtureError as exc:
        print(json.dumps({"gatePassed": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(2) from exc
    print(json.dumps(result.model_dump(mode="json", by_alias=True), sort_keys=True))
    raise SystemExit(0 if (result.corpus_expectations_met if args.verify_corpus else result.gate_passed) else 1)


if __name__ == "__main__":
    main()
