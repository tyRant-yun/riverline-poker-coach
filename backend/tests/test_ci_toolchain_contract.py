from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = "24.15.0"


def test_frontend_node_version_contract_is_consistent():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    nvm_version = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()

    assert f'node-version: "{NODE_VERSION}"' in workflow
    assert package["engines"]["node"] == NODE_VERSION
    assert nvm_version == NODE_VERSION
