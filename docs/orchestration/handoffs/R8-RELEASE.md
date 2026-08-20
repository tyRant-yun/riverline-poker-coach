# R8 source MVP release gate handoff

```yaml
contract_version: handoff/v1
task_id: R8-RELEASE
thread_id: /root/r8_release_gate
branch: codex/r8-release
base_commit: 7ccbc2d43e8f3271cfe0a3225c0bf39d6b0396b8
head_commit: 6e9322912828d0b5b35b57908947bd5028b82487
status: blocked
source_release_ready: false
binary_or_container_release_ready: false
license_source_repository_release: PASS
delivery_heads:
  production_and_e2e: 82cde45027bb4ac16457ab467afca7dfd0ae894a
  release_report: 6e9322912828d0b5b35b57908947bd5028b82487
scope:
  goal: Run the single R8 source MVP release gate from the reviewed integration base, close only release-blocking P0/P1 findings, and record honest source/binary readiness.
  included:
    - Full local-service backend, frontend, build, provenance, startup, current-product Playwright, real two-hand, viewport, privacy, and controlled 5-second interaction-proxy evidence.
    - A minimal Range Explorer overlay stacking P1 fix found by the release E2E.
    - Current-product E2E evidence for decision reconciliation, Solver ladder, Range Explorer, Bot dwell, terminal reveal, next hand, reconnect, and private-card cleanup.
    - Release report with explicit source-license, dependency-security, and binary/container boundaries.
  excluded:
    - Dependency upgrades, product features, Solver/Range/rules/settlement/persistence algorithm changes, and new dependencies.
    - Live PostgreSQL, external Redis, binary/container publication, GitHub push/PR/merge, main, and central ledger edits.
    - Human usability research; the 5-second evidence is an automated interaction proxy only.
changed_files:
  - docs/releases/r8-decision-ux.md
  - frontend/e2e/mvp-shell.spec.ts
  - frontend/e2e/r7-golden-journey.spec.ts
  - frontend/e2e/r8-release-gate.spec.ts
  - frontend/styles/table-v2.css
commits:
  - sha: 82cde45027bb4ac16457ab467afca7dfd0ae894a
    subject: "fix(release): close R8 product gate gaps"
  - sha: 6e9322912828d0b5b35b57908947bd5028b82487
    subject: "docs(release): record R8 source gate"
quality_gates:
  - command: "cd backend; py -3.13 -m pytest -q"
    result: "621 collected; 611 passed; 10 live-PostgreSQL tests skipped in the local-service scope; exit 0."
    measured: true
  - command: "py -3.13 -m compileall -q backend/poker_coach"
    result: "Exit 0."
    measured: true
  - command: "py -3.13 -m pip check"
    result: "No broken requirements found; exit 0."
    measured: true
  - command: "py -3.13 tools/generate_license_provenance.py --root . --check"
    result: "PASS; committed SBOM has 296 components; source_repository_release=PASS; bundled_binary_container_release=FAIL."
    measured: true
  - command: "cd frontend; npm test"
    result: "32 test files / 174 tests passed; exit 0."
    measured: true
  - command: "cd frontend; npm run lint"
    result: "tsc --noEmit passed; exit 0."
    measured: true
  - command: "cd frontend; npm run build"
    result: "Next 16 production build passed; generated next-env.d.ts change was restored and is absent from the delivery diff."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/r8-release-gate.spec.ts"
    result: "Iterative focused authoring: first failure found the real overlay/header stacking P1; two later failures corrected only dwell measurement and reconnect fixture setup; final run 1 passed in 4.1s. Full-suite instance also passed with automated proxy timings 84ms/56ms/14ms and Bot dwell >=700ms assertion."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test"
    result: "Single full current-product run completed exactly once: 5 passed / 2 failed. Both failures were stale E2E contracts (old Solver copy and removed skip speed), not production failures; the full suite was not repeated."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/mvp-shell.spec.ts e2e/r7-golden-journey.spec.ts"
    result: "mvp-shell passed; golden journey failed only on a second stale English Solver copy assertion."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/r7-golden-journey.spec.ts"
    result: "1 passed in 3.5s against the real SQLite/no-Redis local service; continuous two-hand, Hero action, insight visibility, next-hand, reconnect, and private-card checks passed."
    measured: true
  - command: "scripts/run-local.ps1 -ApiPort 18880 -WebPort 13880 -StartupTimeoutSeconds 120"
    result: "Default SQLite/no-Redis mode started; /health HTTP 200 and Web HTTP 200; owned root PIDs 7396/14424 and descendants were stopped; both controlled ports ended with zero listeners."
    measured: true
  - command: "cd frontend; npm audit --json"
    result: "Exit 1; 3 high / 0 critical: direct next@16.1.0 plus transitive postcss and sharp; npm fixAvailable points to next@16.3.1. This security P1 blocks source release, and dependency upgrades were forbidden by task scope."
    measured: true
  - command: "Inherited overall Standards/Spec review input"
    result: "Standards hard findings 0; Spec P0/P1 0. This was supplied upstream and does not review the new 82cde45 release diff."
    measured: false
artifacts:
  - path: docs/releases/r8-decision-ux.md
    description: Full R8 source release report with raw gate chronology, automated-proxy boundary, security blocker, and source/binary readiness.
  - path: frontend/e2e/r8-release-gate.spec.ts
    description: Controlled current-product R8 interaction proxy and deterministic behavior/privacy release evidence.
risks:
  - "BLOCKER: npm audit reports 3 high-severity vulnerable packages in the Next 16.1.0 chain; no in-scope fix exists because dependency upgrades were explicitly forbidden."
  - "The new Range Explorer z-index P1 repair and release E2E require an independent narrow P0/P1 review before merge or release."
  - "The one full Playwright run was 5/7 before stale-test repairs; final evidence combines those five passes with focused terminal passes and is not represented as a post-repair 7/7 full run."
  - "Backend local-service scope skipped 10 live PostgreSQL tests; external Redis was not exercised."
  - "Repository Node engine is exactly 24.15.0, while the measured host was Node 24.18.0."
  - "The 5-second tasks are automated interaction proxies, not human usability results."
  - "SBOM bundled_binary_container_release remains FAIL; binary/container publication is prohibited."
decisions_needed:
  - "Authorize a separate dependency-security task to upgrade Next to a release that closes the npm advisories (npm currently proposes 16.3.1), update the lockfile, and rerun affected unit/tsc/build/Playwright/provenance/audit gates."
dependencies_unlocked: []
recommended_next:
  - task_id: R8-SECURITY-DEPENDENCIES
    goal: Upgrade the vulnerable Next dependency within an explicitly authorized scope and close npm audit high/critical findings without weakening the source/binary provenance boundary.
    depends_on:
      - R8-RELEASE
  - task_id: R8-RELEASE-NARROW-REVIEW
    goal: Independently review base 7ccbc2d..82cde45 for P0/P1, limited to the Range Explorer stacking repair and release E2E contract.
    depends_on:
      - R8-RELEASE
```

The source-license verdict is PASS, but it does not override the dependency-security blocker. Source publication remains blocked until the authorized dependency repair and the narrow review both pass. Binary/container publication remains independently blocked by the committed SBOM verdict.
