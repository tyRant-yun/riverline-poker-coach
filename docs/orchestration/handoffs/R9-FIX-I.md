# R9-FIX-I E2E Contract Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-I
thread_id: /root/r9_fix_f_product_truth
branch: codex/r9-fix-i-e2e-contract
base_commit: 12c3dba66f2bade339f3a5cadadc5c189962f3da
head_commit: 9842bd9cf6637602098a2f187e2cb00d30f37765
status: completed
scope:
  goal: Align two stale Playwright assertions with R9's frozen Truth Source UI contract.
  included:
    - Local-experience assertions target the Decision Summary, Theory, Solver, and Range semantic roles instead of legacy English section copy.
    - Controlled R8 journey asserts the explicit unavailable Truth Source state, supplementary simulation role, C-grade Range fallback, and non-GTO evidence boundary.
    - Retain the existing interaction, viewport, Bot dwell, showdown, next-hand, and reconnect journey coverage.
  excluded:
    - Production UI, API fixtures, other tests, dependencies, ledger, release operations, and wording changes outside the two failing specs.
changed_files:
  - frontend/e2e/local-experience.spec.ts
  - frontend/e2e/r8-release-gate.spec.ts
commits:
  - sha: 9842bd9cf6637602098a2f187e2cb00d30f37765
    subject: test: align e2e truth-source assertions
quality_gates:
  - command: "$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:3000'; npm run test:e2e -- e2e/local-experience.spec.ts e2e/r8-release-gate.spec.ts --workers=1"
    result: baseline reproduced 2 failed; local-experience expected stale 'Solver' copy and r8-release-gate expected stale '规则基线' Decision Summary copy
    measured: true
  - command: "$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:3000'; npm run test:e2e -- e2e/local-experience.spec.ts e2e/r8-release-gate.spec.ts --workers=1"
    result: 2 passed after contract alignment
    measured: true
  - command: "$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:3000'; npm run test:e2e -- --workers=1"
    result: 7 passed
    measured: true
  - command: git diff --check
    result: PASS before delivery commit
    measured: true
artifacts:
  - path: frontend/e2e/local-experience.spec.ts
    description: Live local journey now checks B-grade covered policy truth, supplementary non-GTO simulation, and public-only Range semantics by accessible role.
  - path: frontend/e2e/r8-release-gate.spec.ts
    description: Controlled journey now verifies unavailable unified theory truth and C-grade Range fallback without reviving legacy Advisor/Solver arbitration in Decision Summary.
risks: []
decisions_needed: []
dependencies_unlocked:
  - R9-07 can rerun the release Playwright gate with all seven current scenarios aligned to the Truth Source contract.
recommended_next:
  - task_id: R9-07
    goal: Rerun the integrated release gate.
    depends_on:
      - R9-FIX-I
```

The task reused an existing dependency installation through a temporary junction and ran the isolated frontend with webpack mode. No package was installed or upgraded; the junction, `.next`, and `test-results` were removed before commit, and `frontend/next-env.d.ts` matches the baseline blob.
