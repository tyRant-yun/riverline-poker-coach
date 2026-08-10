"""Solver sidecar client: runs the isolated solver container (or a test runner)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Callable

from .adapter import parse_result, spot_to_config_json
from .types import SolverSpot, SolveResult, SolverUnsupportedError

Runner = Callable[[str], str]  # config_json -> raw solver stdout


class SidecarClient:
    """Submit a SolverSpot to the postflop-solver sidecar and parse the result.

    The default transport runs ``docker run --rm`` against the
    ``poker-coach-sidecar`` image (built outside this repository, AGPL
    isolation). An injected ``runner`` keeps tests offline and deterministic.
    """

    def __init__(
        self,
        *,
        image: str = "poker-coach-sidecar",
        timeout_seconds: int = 900,
        runner: Runner | None = None,
    ):
        self._image = image
        self._timeout_seconds = timeout_seconds
        self._runner = runner

    def solve(self, spot: SolverSpot) -> SolveResult:
        config_json = spot_to_config_json(spot)
        if self._runner is not None:
            raw_output = self._runner(config_json)
        else:
            raw_output = self._run_docker(config_json)
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise SolverUnsupportedError(f"sidecar returned invalid JSON: {exc}") from exc
        return parse_result(payload)

    def _run_docker(self, config_json: str) -> str:
        with tempfile.TemporaryDirectory(prefix="poker-coach-solve-") as tmp_dir:
            config_path = os.path.join(tmp_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(config_json)
            host_dir = os.path.abspath(tmp_dir)
            command = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{host_dir}:/work:ro",
                self._image,
                "/work/config.json",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise SolverUnsupportedError(
                    f"sidecar timed out after {self._timeout_seconds}s"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[-500:]
                raise SolverUnsupportedError(
                    f"sidecar failed (rc={completed.returncode}): {detail}"
                )
            return completed.stdout
