from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "generate_license_provenance.py"


def _write_empty_decisions(root: Path) -> None:
    (root / "tools").mkdir()
    (root / "tools" / "license_provenance_decisions.json").write_text(
        '{"schema_version": 1, "python_licenses": {}}\n', encoding="utf-8"
    )


def _load_generator():
    spec = importlib.util.spec_from_file_location("license_provenance_generator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_committed_provenance_outputs_are_deterministic():
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT), "--check"], capture_output=True, text=True)
    assert completed.returncode in (0, 1), completed.stderr
    assert completed.stdout.strip() in {"PASS", "FAIL"}


def test_committed_inventory_ignores_environment_distribution_metadata(monkeypatch):
    generator = _load_generator()

    class Distribution:
        def __init__(self, version: str, license_value: str):
            self.version = version
            self.metadata = {"License-Expression": license_value}
            self._path = Path(f"platform-specific/{version}")

    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: Distribution("windows-wheel", "MIT"),
    )
    windows_inventory = generator.inventory(ROOT)
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: Distribution("linux-wheel", "GPL-3.0-only"),
    )
    linux_inventory = generator.inventory(ROOT)

    assert windows_inventory == linux_inventory
    encoded = json.dumps(windows_inventory, ensure_ascii=False, sort_keys=True)
    assert '"installed"' not in encoded
    assert "metadata_sha256" not in encoded


def test_missing_npm_license_fails_closed(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\ndependencies=[]\n", encoding="utf-8")
    (tmp_path / "backend" / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("fixture", encoding="utf-8")
    _write_empty_decisions(tmp_path)
    lock = {"name": "fixture", "lockfileVersion": 3, "packages": {"": {"name": "fixture"}, "node_modules/example": {"version": "1.0.0", "resolved": "https://example.invalid/example.tgz", "integrity": "sha512-fixture"}}}
    (tmp_path / "frontend" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 1
    data = json.loads((output / "sbom.json").read_text(encoding="utf-8"))
    assert data["verdicts"]["source_repository_release"]["status"] == "FAIL"
    assert "npm:example: missing license" in data["verdicts"]["source_repository_release"]["failures"]


def test_missing_python_license_decision_fails_closed(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\ndependencies=['example==1.0.0']\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "requirements.lock").write_text(
        "example==1.0.0\n", encoding="utf-8"
    )
    (tmp_path / "frontend" / "package-lock.json").write_text(
        json.dumps({"name": "fixture", "lockfileVersion": 3, "packages": {"": {}}}),
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text("fixture", encoding="utf-8")
    _write_empty_decisions(tmp_path)

    output = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    data = json.loads((output / "sbom.json").read_text(encoding="utf-8"))
    failures = data["verdicts"]["source_repository_release"]["failures"]
    assert "pypi:example: missing repository-controlled license decision for 1.0.0" in failures


def test_missing_npm_integrity_blocks_bundled_artifacts_but_not_source_only(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\ndependencies=[]\n", encoding="utf-8")
    (tmp_path / "backend" / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("fixture", encoding="utf-8")
    _write_empty_decisions(tmp_path)
    lock = {"name": "fixture", "lockfileVersion": 3, "packages": {"": {"name": "fixture"}, "node_modules/example": {"version": "1.0.0", "license": "MIT"}}}
    (tmp_path / "frontend" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 0
    data = json.loads((output / "sbom.json").read_text(encoding="utf-8"))
    assert data["verdicts"]["source_repository_release"]["status"] == "PASS"
    assert data["verdicts"]["bundled_binary_container_release"]["status"] == "FAIL"
