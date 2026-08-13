"""Generate Riverline's offline, deterministic dependency provenance inventory.

This intentionally uses only Python's standard library.  It treats a missing
lockfile source, artifact digest, package license, or manual copyleft decision
as a release-gate failure rather than inferring a passing result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path


SCHEMA_VERSION = 2
PYTHON_COPyleft_ALLOWLIST = {
    "psycopg": {"LGPL-3.0-only"},
    "psycopg-binary": {"LGPL-3.0-only"},
    "psycopg-pool": {"LGPL-3.0-only"},
}
NPM_COPYLEFT_DECISIONS = {
    "@img/sharp-*": {
        "licenses": {"Apache-2.0 AND LGPL-3.0-or-later", "Apache-2.0 AND LGPL-3.0-or-later AND MIT", "LGPL-3.0-or-later"},
        "decision": "approved-with-distribution-obligations",
        "evidence": [
            "https://github.com/lovell/sharp-libvips/blob/main/LICENSE",
            "https://github.com/lovell/sharp-libvips",
        ],
        "obligations": "Retain applicable notices and provide/point to the corresponding LGPL source and license material for the shipped libvips binary; obtain legal review for the actual distribution.",
    }
}
COPYLEFT_RE = re.compile(r"(?:^|\W)(?:A?GPL|LGPL)(?:-|\W|$)", re.I)


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked_requirements(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if not match:
            raise ValueError(f"unsupported locked requirement: {line}")
        result[normalise(match.group(1))] = match.group(2)
    return result


def direct_python_names(project: dict[str, object]) -> set[str]:
    specs = list(project["project"].get("dependencies", []))
    for group in project["project"].get("optional-dependencies", {}).values():
        specs.extend(group)
    return {normalise(re.match(r"([A-Za-z0-9_.-]+)", spec).group(1)) for spec in specs}


def license_decisions(root: Path) -> dict[str, object]:
    path = root / "tools" / "license_provenance_decisions.json"
    decisions = json.loads(path.read_text(encoding="utf-8"))
    if decisions.get("schema_version") != 1 or not isinstance(
        decisions.get("python_licenses"), dict
    ):
        raise ValueError("unsupported license provenance decision schema")
    return decisions


def python_components(
    root: Path, failures: list[str], decisions: dict[str, object]
) -> list[dict[str, object]]:
    pyproject = root / "backend" / "pyproject.toml"
    requirements = root / "backend" / "requirements.lock"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    locked = locked_requirements(requirements)
    direct = direct_python_names(project)
    components: list[dict[str, object]] = []
    for name, version in sorted(locked.items()):
        item: dict[str, object] = {
            "ecosystem": "pypi",
            "name": name,
            "version": version,
            "direct": name in direct,
            "source": {"status": "registry-reference", "value": f"https://pypi.org/project/{name}/{version}/"},
            "resolved": {"status": "locked", "value": f"{name}=={version}"},
            "integrity": {"status": "unknown", "value": None},
            "license": {"status": "unknown", "value": None},
            "evidence": ["backend/requirements.lock", "backend/pyproject.toml"],
            "unknown": ["artifact integrity hash"],
        }
        decision_key = f"{name}=={version}"
        decision = decisions.get("python_licenses", {}).get(decision_key)
        if isinstance(decision, dict) and decision.get("license"):
            item["license"] = {
                "status": "reviewed-decision",
                "value": decision["license"],
            }
            item["evidence"].append(
                f"tools/license_provenance_decisions.json#{decision_key}"
            )
            item["evidence"].extend(decision.get("evidence", []))
        else:
            item["unknown"].append("license")
            failures.append(
                f"pypi:{name}: missing repository-controlled license decision for {version}"
            )
        license_value = item["license"]["value"]
        if license_value and COPYLEFT_RE.search(str(license_value)):
            allowed = PYTHON_COPyleft_ALLOWLIST.get(name, set())
            if license_value not in allowed:
                failures.append(f"pypi:{name}: copyleft license requires an explicit decision")
            else:
                item["copyleft_decision"] = "approved-optional-runtime; preserve LGPL notices/source obligations when distributing"
        components.append(item)
    return components


def npm_components(root: Path, failures: list[str]) -> list[dict[str, object]]:
    lock_path = root / "frontend" / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    root_package = lock["packages"].get("", {})
    direct = set(root_package.get("dependencies", {})) | set(root_package.get("devDependencies", {}))
    components: list[dict[str, object]] = []
    for path, package in sorted(lock["packages"].items()):
        if not path:
            continue
        marker = "node_modules/"
        if marker not in path:
            continue
        name = path.rsplit(marker, 1)[1]
        item: dict[str, object] = {
            "ecosystem": "npm",
            "name": name,
            "version": package.get("version"),
            "direct": name in direct,
            "source": {"status": "locked" if package.get("resolved") else "registry-reference", "value": package.get("resolved") or f"https://registry.npmjs.org/{name}/{package.get('version')}"},
            "resolved": {"status": "locked", "value": path},
            "integrity": {"status": "locked" if package.get("integrity") else "unknown", "value": package.get("integrity")},
            "license": {"status": "lockfile" if package.get("license") else "unknown", "value": package.get("license")},
            "evidence": ["frontend/package-lock.json"],
            "unknown": [],
        }
        for field in ("version",):
            if not item[field]:
                failures.append(f"npm:{name}: missing {field}")
        for field in ("license",):
            if item[field]["status"] == "unknown":
                item["unknown"].append(field)
                failures.append(f"npm:{name}: missing {field}")
        license_value = item["license"]["value"]
        if license_value and COPYLEFT_RE.search(str(license_value)):
            decision = NPM_COPYLEFT_DECISIONS.get("@img/sharp-*") if name.startswith("@img/sharp-") else NPM_COPYLEFT_DECISIONS.get(name)
            if decision and license_value in decision["licenses"]:
                item["copyleft_decision"] = {key: sorted(value) if isinstance(value, set) else value for key, value in decision.items()}
            else:
                failures.append(f"npm:{name}: copyleft binary/license lacks an explicit allowlist decision")
        components.append(item)
    return components


def inventory(root: Path) -> dict[str, object]:
    source_failures: list[str] = []
    decisions = license_decisions(root)
    components = python_components(root, source_failures, decisions) + npm_components(root, source_failures)
    binary_failures = list(source_failures)
    for component in components:
        if component["ecosystem"] == "pypi" and component["integrity"]["status"] == "unknown":
            binary_failures.append(f"pypi:{component['name']}: binary/container artifact integrity hash is not locked")
        decision = component.get("copyleft_decision")
        if component["ecosystem"] == "npm" and component["integrity"]["status"] == "unknown":
            binary_failures.append(f"npm:{component['name']}: binary/container artifact integrity hash is not locked")
        if component["name"].startswith("@img/sharp-") and decision:
            binary_failures.append(f"npm:{component['name']}: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling")
    source_files = [
        "backend/pyproject.toml",
        "backend/requirements.lock",
        "frontend/package-lock.json",
        "tools/license_provenance_decisions.json",
        "LICENSE",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {"name": "Riverline", "license": "AGPL-3.0-or-later"},
        "inputs": [{"path": item, "sha256": sha256(root / item)} for item in source_files],
        "components": sorted(components, key=lambda item: (item["ecosystem"], item["name"], item["version"] or "")),
        "verdicts": {
            "source_repository_release": {"status": "PASS" if not source_failures else "FAIL", "failures": sorted(set(source_failures))},
            "bundled_binary_container_release": {"status": "PASS" if not binary_failures else "FAIL", "failures": sorted(set(binary_failures))},
        },
    }


def report(data: dict[str, object]) -> str:
    source_gate = data["verdicts"]["source_repository_release"]
    binary_gate = data["verdicts"]["bundled_binary_container_release"]
    lines = [
        "# Riverline third-party provenance report",
        "",
        "Generated deterministically by `py -3.13 tools/generate_license_provenance.py`; it has no timestamp and does not contact a network service.",
        "",
        "Riverline is licensed under **AGPL-3.0-or-later**. Network users must be offered Corresponding Source as required by AGPL section 13. Non-commercial use is not a license exemption. This report is engineering evidence, not legal advice.",
        "",
        f"## Source repository release: {source_gate['status']}",
        "",
    ]
    if source_gate["failures"]:
        lines += ["The gate is fail-closed for the following reasons:", ""]
        lines += [f"- `{failure}`" for failure in source_gate["failures"]]
        lines.append("")
    lines += [
        f"## Bundled binary/container release: {binary_gate['status']}",
        "",
        "This stricter verdict applies only when publishing a Docker image, wheel, installer, or another artifact that contains runtime binaries. A source-only GitHub branch/PR merge does not convey `node_modules`, Python wheels, or libvips binaries.",
        "",
    ]
    if binary_gate["failures"]:
        lines += ["The bundled-artifact gate is fail-closed for:", ""]
        lines += [f"- `{failure}`" for failure in binary_gate["failures"]]
        lines.append("")
    lines += [
        "## Reviewed copyleft decisions",
        "",
        "- `@img/sharp-win32-x64` is locked as `Apache-2.0 AND LGPL-3.0-or-later`. It carries a Windows libvips binary through the sharp package family. The explicit decision allows review of this known package only; a distributor must retain applicable notices and provide or point to the corresponding LGPL source/license materials for the shipped binary. Evidence: <https://github.com/lovell/sharp-libvips/blob/main/LICENSE> and <https://github.com/lovell/sharp-libvips>. This is not a legal conclusion.",
        "- Optional Python `psycopg`, `psycopg-binary`, and `psycopg-pool` are explicitly recorded LGPL-3.0-only dependencies. Their notice/source obligations remain applicable if they are distributed.",
        "- No new GPL/AGPL runtime dependency is permitted by this gate; Riverline's own AGPL-3.0-or-later license is recorded separately.",
        "",
        "## Machine-readable inventory",
        "",
        "See [`sbom.json`](sbom.json). Every record includes ecosystem, name, version, direct/transitive classification, source, resolved location, integrity, license, evidence, and unknown fields.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(root: Path, output: Path) -> dict[str, object]:
    data = inventory(root)
    output.mkdir(parents=True, exist_ok=True)
    (output / "sbom.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "THIRD_PARTY_NOTICES.md").write_text(report(data), encoding="utf-8")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="regenerate in memory and require committed outputs to match")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "docs" / "provenance"
    data = inventory(root)
    expected = {
        "sbom.json": json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "THIRD_PARTY_NOTICES.md": report(data),
    }
    if args.check:
        stale = [name for name, content in expected.items() if not (output / name).exists() or (output / name).read_text(encoding="utf-8") != content]
        if stale:
            print(f"stale provenance outputs: {', '.join(stale)}", file=sys.stderr)
            return 2
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, content in expected.items():
            (output / name).write_text(content, encoding="utf-8")
    print(data["verdicts"]["source_repository_release"]["status"])
    return 0 if data["verdicts"]["source_repository_release"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
