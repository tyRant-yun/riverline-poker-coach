# PR #2 CI Fix handoff

```yaml
contract_version: handoff/v1
task_id: PR2-CI-FIX
thread_id: 019ff53a-fe87-7353-b7cc-ac3288f0553e
branch: codex/pr2-ci-fix
base_commit: cc37fbc540a1ecf7f755ed00020d298ea42b1252
head_commit: c8e373540cb36ae47fdf93a977ae3efc096ee6b9
status: completed
scope:
  goal: Repair the three diagnosed PR #2 CI failures without changing product behavior or weakening outbox safety.
  included:
    - Generate committed Python provenance from exact-version repository-controlled license decisions rather than installed distribution metadata.
    - Preserve fail-closed source and bundled-artifact verdicts and regenerate the deterministic SBOM.
    - Pin the frontend CI and repository Node contract to 24.15.0 without changing dependency versions.
    - Give the live PostgreSQL outbox test one injected deterministic clock for claim and acknowledge.
  excluded:
    - Product implementation changes or dependency upgrades/downgrades.
    - Changes to outbox owner, token, status, or lease-expiry safety checks.
    - Full backend, frontend, E2E, or live-service gates.
    - Central ledger changes, push, PR mutation, main merge, or worktree cleanup.
changed_files:
  - .github/workflows/ci.yml
  - .nvmrc
  - backend/tests/test_ci_toolchain_contract.py
  - backend/tests/test_license_provenance.py
  - backend/tests/test_postgres_live.py
  - docs/dependency-inventory.md
  - docs/provenance/sbom.json
  - frontend/package-lock.json
  - frontend/package.json
  - tools/generate_license_provenance.py
  - tools/license_provenance_decisions.json
commits:
  - sha: c8e373540cb36ae47fdf93a977ae3efc096ee6b9
    subject: fix CI environment contracts
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_license_provenance.py -q
    result: 5 passed
    measured: true
  - command: py -3.13 tools/generate_license_provenance.py --check
    result: PASS; source_repository_release PASS and bundled_binary_container_release FAIL
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_ci_toolchain_contract.py -q
    result: 1 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_outbox_recovery.py::test_concurrent_claim_has_one_owner_and_expired_processing_lease_recovers backend/tests/test_outbox_recovery.py::test_expired_claim_token_cannot_ack_or_retry_a_new_claim_with_same_worker_id backend/tests/test_outbox_recovery.py::test_dispatcher_cannot_ack_or_retry_after_claim_lease_expires backend/tests/test_postgres_recovery.py::test_postgres_claim_recovers_expired_leases_and_locks_rows_without_blocking backend/tests/test_postgres_recovery.py::test_postgres_ack_and_retry_require_current_claim_token_and_store_time -q
    result: 6 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_postgres_live.py::test_live_projection_rebuild_and_transactional_outbox_dispatch -q
    result: Not run because POKER_COACH_TEST_PG_URL is not configured locally
    measured: false
  - command: node --version
    result: v24.18.0; confirms local Node 24 family only, not the exact CI 24.15.0 runtime
    measured: true
  - command: GitHub CI frontend job on Node 24.15.0
    result: Pending after integration; no local claim for the exact runtime
    measured: false
  - command: git diff --check
    result: exit 0; only existing Git line-ending conversion warnings were emitted
    measured: true
artifacts:
  - path: docs/provenance/sbom.json
    description: Deterministic schema-v2 dependency inventory generated without installed-path or distribution-metadata fields.
  - path: tools/license_provenance_decisions.json
    description: Exact-version, repository-controlled Python license decision record.
risks:
  - Exact Node 24.15.0 execution remains for GitHub CI; the available local runtime was Node 24.18.0.
  - The focused live PostgreSQL test remains unmeasured locally because no live PostgreSQL test URL was configured.
  - bundled_binary_container_release intentionally remains FAIL because Python artifact hashes and bundled sharp/libvips obligations are not closed; source_repository_release remains PASS.
decisions_needed: []
dependencies_unlocked:
  - PR2-CI-RERUN
recommended_next:
  - task_id: PR2-CI-RERUN
    goal: Integrate the delivery and use GitHub CI as the exact Node 24.15.0 and live PostgreSQL evidence.
    depends_on:
      - PR2-CI-FIX
```
