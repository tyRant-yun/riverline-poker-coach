from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "generate_license_provenance.py"


def test_committed_provenance_outputs_are_deterministic():
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT), "--check"], capture_output=True, text=True)
    assert completed.returncode in (0, 1), completed.stderr
    assert completed.stdout.strip() in {"PASS", "FAIL"}


def test_missing_npm_license_fails_closed(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\ndependencies=[]\n", encoding="utf-8")
    (tmp_path / "backend" / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("fixture", encoding="utf-8")
    lock = {"name": "fixture", "lockfileVersion": 3, "packages": {"": {"name": "fixture"}, "node_modules/example": {"version": "1.0.0", "resolved": "https://example.invalid/example.tgz", "integrity": "sha512-fixture"}}}
    (tmp_path / "frontend" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 1
    data = json.loads((output / "sbom.json").read_text(encoding="utf-8"))
    assert data["verdicts"]["source_repository_release"]["status"] == "FAIL"
    assert "npm:example: missing license" in data["verdicts"]["source_repository_release"]["failures"]


def test_missing_npm_integrity_blocks_bundled_artifacts_but_not_source_only(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\ndependencies=[]\n", encoding="utf-8")
    (tmp_path / "backend" / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("fixture", encoding="utf-8")
    lock = {"name": "fixture", "lockfileVersion": 3, "packages": {"": {"name": "fixture"}, "node_modules/example": {"version": "1.0.0", "license": "MIT"}}}
    (tmp_path / "frontend" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 0
    data = json.loads((output / "sbom.json").read_text(encoding="utf-8"))
    assert data["verdicts"]["source_repository_release"]["status"] == "PASS"
    assert data["verdicts"]["bundled_binary_container_release"]["status"] == "FAIL"
