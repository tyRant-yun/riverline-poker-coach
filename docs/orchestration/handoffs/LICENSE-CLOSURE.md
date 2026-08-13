# LICENSE-CLOSURE handoff

```yaml
contract_version: handoff/v1
task_id: LICENSE-CLOSURE
thread_id: 019ff53a-fe87-7353-b7cc-ac3288f0553e
branch: codex/license-provenance-closure
base_commit: 0f4badde36499058a35c1002a31103861f5135e2
head_commit: 98e8f098f40b60fd4ee62e6138d6fad2f18c8686
status: completed
scope:
  goal: Close deterministic offline provenance for the authorized source-only GitHub merge while explicitly retaining fail-closed bundled-artifact constraints.
  included:
    - Standard-library generator for a deterministic Python/npm SBOM and human-readable notice report.
    - Source-only and bundled-artifact verdicts, unknown-field reporting, explicit copyleft decisions, focused tests, and factual notice updates.
    - Recheck of the existing MVP release handoff without rerunning functional gates.
  excluded:
    - Product implementation, dependency/version changes, network access, package installation, Docker/wheel/installer publication, central ledger edits, push, PR creation, or main merge.
changed_files:
  - tools/generate_license_provenance.py
  - backend/tests/test_license_provenance.py
  - docs/provenance/sbom.json
  - docs/provenance/THIRD_PARTY_NOTICES.md
  - THIRD_PARTY_NOTICES.md
  - docs/dependency-inventory.md
commits:
  - sha: 98e8f098f40b60fd4ee62e6138d6fad2f18c8686
    subject: "docs: add offline license provenance gate"
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_license_provenance.py -q
    result: 3 passed
    measured: true
  - command: py -3.13 tools/generate_license_provenance.py --check
    result: PASS; committed generated output is deterministic in this environment
    measured: true
  - command: git diff --check
    result: exit 0 before handoff edits
    measured: true
  - command: backend/frontend/build/E2E/service gates
    result: Not rerun by this documentation/tooling task; MVP-RELEASE-GATE records the existing measured functional evidence.
    measured: false
artifacts:
  - path: docs/provenance/sbom.json
    description: 296-component machine-readable offline inventory with ecosystem, version, direct/transitive, source, resolved, integrity, license, evidence, unknown, and scope-aware verdicts.
  - path: docs/provenance/THIRD_PARTY_NOTICES.md
    description: Deterministic human-readable report, AGPL source-access reminder, source-only PASS, bundled-artifact FAIL, and sharp/libvips obligations.
risks:
  - Python requirements.lock has versions but not distribution artifact hashes. This does not block the authorized source-only GitHub merge, but blocks binary/container publication.
  - sharp/libvips packages are not committed in source control. Any future bundled distribution must verify the actual selected platform artifact, notices, and corresponding-source handling.
decisions_needed: []
dependencies_unlocked:
  - Source-only GitHub branch/PR merge under the MVP release verdict.
recommended_next:
  - task_id: BUNDLED-ARTIFACT-PROVENANCE-GATE
    goal: Add artifact-hash and per-distribution notice/source evidence before a Docker, wheel, installer, or binary release.
    depends_on:
      - LICENSE-CLOSURE
```
