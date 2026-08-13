# PR #2 CI Recheck handoff

```yaml
contract_version: handoff/v1
task_id: PR2-CI-RECHECK
thread_id: 019ff53a-fe87-7353-b7cc-ac3288f0553e
branch: codex/pr2-ci-fix
base_commit: 8cb77c943b77e0763d802985ab82c3378c3ac288
head_commit: dfae56f0ec04fcd100f33178300b167f2d96c177
status: blocked
scope:
  goal: Recheck PR #2 CI run 31668644775 and repair only mechanical failures within the previously authorized CI/tooling/test-fixture scope.
  included:
    - Inspect the two failed GitHub Actions jobs and their failed-step logs.
    - Canonicalize repository-controlled provenance input hashes across LF and CRLF checkouts.
    - Add a focused red/green regression and regenerate the deterministic SBOM.
  excluded:
    - Product frontend/backend implementation changes.
    - Changes to multiseat product behavior or the out-of-scope Playwright spec.
    - Dependency versions, license conclusions, outbox lease semantics, central ledger, push, or PR mutation.
changed_files:
  - backend/tests/test_license_provenance.py
  - docs/provenance/sbom.json
  - tools/generate_license_provenance.py
commits:
  - sha: dfae56f0ec04fcd100f33178300b167f2d96c177
    subject: fix cross-platform provenance input hashes
quality_gates:
  - command: gh run view 31668644775 --json name,workflowName,conclusion,status,url,event,headBranch,headSha,jobs
    result: Inspected the requested failed run at head 8cb77c943b77e0763d802985ab82c3378c3ac288; backend and frontend jobs failed.
    measured: true
  - command: gh run view 31668644775 --job 94348590742 --log-failed
    result: Backend collected 552 tests; live PostgreSQL tests passed; only provenance --check failed with stale provenance outputs sbom.json.
    measured: true
  - command: gh run view 31668644775 --job 94348590769 --log-failed
    result: Node setup, npm ci, typecheck, 161 unit tests, and build passed; Playwright finished 8 passed and one multiseat scenario failed after all retries.
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_license_provenance.py::test_controlled_input_hash_normalises_checkout_line_endings -q
    result: Before fix 1 failed with different SHA-256 values for identical LF/CRLF text; after fix 1 passed.
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_license_provenance.py -q
    result: 6 passed
    measured: true
  - command: py -3.13 tools/generate_license_provenance.py --check
    result: PASS; source_repository_release remains PASS and bundled_binary_container_release remains FAIL.
    measured: true
  - command: git diff --check
    result: exit 0; only existing Git line-ending conversion warnings were emitted.
    measured: true
  - command: npx playwright test e2e/multiseat-scenario.spec.ts
    result: Not run locally; the exact Linux failure is captured in run 31668644775 and resolving it requires an independently authorized E2E/product-state task.
    measured: false
artifacts:
  - path: docs/provenance/sbom.json
    description: Regenerated SBOM whose controlled input hashes explicitly use utf-8-lf canonicalization.
  - path: https://github.com/tyRant-yun/riverline-poker-coach/actions/runs/31668644775
    description: Source CI run for the recheck evidence.
risks:
  - The Linux provenance fix requires a GitHub CI rerun for final cross-OS evidence.
  - PR #2 remains blocked by frontend/e2e/multiseat-scenario.spec.ts; logs show actor state failing to advance or reset consistently across attempts, which is outside this task's allowed files.
  - No license verdict changed; bundled binary/container distribution remains blocked as before.
decisions_needed:
  - Authorize a separate focused multiseat Playwright/product-state diagnosis if PR #2 must become fully green.
dependencies_unlocked:
  - PR2-LICENSE-CI-RERUN
recommended_next:
  - task_id: PR2-MULTISEAT-E2E-DIAGNOSIS
    goal: Reproduce and classify the multiseat actor-state failure without weakening assertions; fix only after determining whether the cause is test isolation or product state propagation.
    depends_on:
      - PR2-CI-RECHECK
```
