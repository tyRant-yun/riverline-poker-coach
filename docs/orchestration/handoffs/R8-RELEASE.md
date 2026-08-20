# R8 source MVP release gate handoff

```yaml
contract_version: handoff/v1
task_id: R8-RELEASE
thread_id: /root/r8_release_gate
branch: codex/r8-release
base_commit: 7ccbc2d43e8f3271cfe0a3225c0bf39d6b0396b8
head_commit: 593294b0a5ad10235e34a61c739bccb36dae61c1
status: completed
source_release_ready: pending_independent_review_and_ci
binary_or_container_release_ready: false
license_source_repository_release: PASS
delivery_heads:
  production_and_e2e: 82cde45027bb4ac16457ab467afca7dfd0ae894a
  original_release_report: 6e9322912828d0b5b35b57908947bd5028b82487
  dependency_security: 1e6dee37e59d9b72f7098939508f4e259dbeb326
  updated_release_report: 593294b0a5ad10235e34a61c739bccb36dae61c1
scope:
  goal: Run the R8 source MVP release gate, close only release-blocking P0/P1 findings, apply the separately authorized minimal Next security upgrade, and record honest source/binary readiness.
  included:
    - Full local-service backend, frontend, build, provenance, startup, current-product Playwright, real two-hand, viewport, privacy, and controlled 5-second interaction-proxy evidence.
    - A minimal Range Explorer overlay stacking P1 fix found by the release E2E.
    - Exact Next 16.1.0 to 16.3.1 security upgrade with lockfile-resolved PostCSS/Sharp, unchanged React 19.2.0, and regenerated repository provenance.
    - Narrow-review E2E evidence for honest Top-mover unavailability and all four viewport acceptance requirements.
    - Release report with explicit dependency-security, source-license, exact-environment CI, and binary/container boundaries.
  excluded:
    - New product features; Solver, Range, rules, settlement, persistence, or public-contract algorithm changes; unrelated dependency upgrades; and new dependencies.
    - Live PostgreSQL, external Redis, binary/container publication, GitHub push/PR/merge, main, and central ledger edits.
    - Human usability research; the 5-second evidence is an automated interaction proxy only.
changed_files:
  - docs/provenance/THIRD_PARTY_NOTICES.md
  - docs/provenance/sbom.json
  - docs/releases/r8-decision-ux.md
  - frontend/e2e/mvp-shell.spec.ts
  - frontend/e2e/r7-golden-journey.spec.ts
  - frontend/e2e/r8-release-gate.spec.ts
  - frontend/package-lock.json
  - frontend/package.json
  - frontend/styles/table-v2.css
commits:
  - sha: 82cde45027bb4ac16457ab467afca7dfd0ae894a
    subject: "fix(release): close R8 product gate gaps"
  - sha: 6e9322912828d0b5b35b57908947bd5028b82487
    subject: "docs(release): record R8 source gate"
  - sha: 1e6dee37e59d9b72f7098939508f4e259dbeb326
    subject: "fix(deps): upgrade Next security baseline"
  - sha: 593294b0a5ad10235e34a61c739bccb36dae61c1
    subject: "docs(release): record R8 security follow-up"
quality_gates:
  - command: "cd backend; py -3.13 -m pytest -q"
    result: "621 collected; 611 passed; 10 live-PostgreSQL tests skipped in the local-service scope; exit 0. Frontend-only security follow-up did not repeat backend."
    measured: true
  - command: "py -3.13 -m compileall -q backend/poker_coach"
    result: "Exit 0."
    measured: true
  - command: "py -3.13 -m pip check"
    result: "No broken requirements found; exit 0."
    measured: true
  - command: "cd frontend; npm audit --audit-level=high --json"
    result: "Pre-upgrade baseline at 27f7e6ad: exit 1; 3 high / 0 critical: direct next@16.1.0 plus transitive postcss and sharp; fixAvailable next@16.3.1."
    measured: true
  - command: "cd frontend; npm ls next postcss sharp react react-dom --depth=1"
    result: "Exit 0; Next 16.3.1, PostCSS 8.5.23, Sharp 0.35.3, React/React DOM unchanged at 19.2.0."
    measured: true
  - command: "cd frontend; npm audit --audit-level=high"
    result: "Exit 0; found 0 vulnerabilities."
    measured: true
  - command: "py -3.13 tools/generate_license_provenance.py --root ."
    result: "PASS; generated SBOM and THIRD_PARTY_NOTICES only through the repository generator; 298 components."
    measured: true
  - command: "py -3.13 tools/generate_license_provenance.py --root . --check"
    result: "PASS; source_repository_release=PASS; bundled_binary_container_release=FAIL."
    measured: true
  - command: "cd frontend; npm test"
    result: "Post-upgrade full unit gate: 32 test files / 174 tests passed; exit 0."
    measured: true
  - command: "cd frontend; npm run lint"
    result: "Post-upgrade tsc --noEmit passed; exit 0."
    measured: true
  - command: "cd frontend; npm run build"
    result: "Next 16.3.1 production build passed; compiled in 2.1s, typecheck in 2.1s, 3 static pages; generated next-env.d.ts change is absent from delivery."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test"
    result: "Initial release-gate full run before test-contract repair: 5 passed / 2 failed on stale Solver copy and removed skip-speed assertions; it was not represented as green."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/mvp-shell.spec.ts e2e/r7-golden-journey.spec.ts"
    result: "Focused contract repair: mvp-shell passed; golden journey exposed a second stale English Solver assertion."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/r7-golden-journey.spec.ts"
    result: "Terminal focused real-service run: 1 passed in 3.5s; continuous two-hand, Hero action, insights, next hand, reconnect, and private-card checks passed."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test e2e/r8-release-gate.spec.ts"
    result: "Post-upgrade first run failed before product assertions because Next dev was still downloading the Windows SWC optional package (page.goto 35s ERR_ABORTED/frame detached); after the lockfile-matched SWC 16.3.1 package was present, 1 passed in 4.8s with enhanced Top-mover and four-viewport evidence; proxy timings 54ms/42ms/10ms."
    measured: true
  - command: "cd frontend; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:13880'; npx playwright test"
    result: "Post-upgrade current-product full run: 7/7 passed in 10.4s; real two-hand journey 2.7s; R8 proxy 58ms/37ms/9ms."
    measured: true
  - command: "scripts/run-local.ps1 -ApiPort 18880 -WebPort 13880 -StartupTimeoutSeconds 120"
    result: "Post-upgrade default SQLite/no-Redis mode started; /health HTTP 200 and Web HTTP 200; owned root PIDs 27716/16372 and descendants were stopped; both controlled ports ended with zero listeners."
    measured: true
  - command: "R8 automated interaction proxy assertions"
    result: "Range task includes visible identification of the honest unavailable Top-mover explanation before opening Explorer; Solver task identifies the preferred action and expands all five scales; reconciliation task identifies agreement/divergence reason; all are <=5s. This is not human usability research."
    measured: true
  - command: "R8 viewport assertions at 1366x768, 1440x900, 1920x1080, and 1280x720"
    result: "Each viewport asserts centered/visible Hero, reachable Hero actions, Decision Summary, exactly three default Solver candidate rows, Range Summary, and no horizontal scroll."
    measured: true
  - command: "Inherited overall Standards/Spec review input"
    result: "Standards hard findings 0; Spec P0/P1 0. This was supplied upstream and does not review the 82cde45 or 1e6dee3 release-only increments."
    measured: false
artifacts:
  - path: docs/releases/r8-decision-ux.md
    description: Updated R8 source release report with full gate chronology, audit closure, automated-proxy boundary, and pending review/CI readiness.
  - path: frontend/e2e/r8-release-gate.spec.ts
    description: Controlled current-product R8 interaction proxy, four-viewport acceptance, and deterministic behavior/privacy evidence.
  - path: docs/provenance/sbom.json
    description: Repository-generator SBOM for the post-upgrade dependency graph; source PASS and bundled binary/container FAIL.
  - path: docs/provenance/THIRD_PARTY_NOTICES.md
    description: Repository-generator third-party notices for the post-upgrade dependency graph.
risks:
  - "The 82cde45 UI repair and 1e6dee3 dependency/E2E delivery require an independent narrow P0/P1 review before Controller release acceptance."
  - "Repository Node engine is exactly 24.15.0, while the measured host was Node 24.18.0; GitHub CI in the exact environment is the final clean-install gate."
  - "Online npm package and Windows SWC downloads were extremely slow and interrupted; offline cache completion and all local runtime gates passed, but clean-network CI evidence is still required."
  - "Backend local-service scope skipped 10 live PostgreSQL tests; external Redis was not exercised, and frontend-only follow-up did not repeat backend."
  - "The 5-second tasks are automated interaction proxies, not human usability results."
  - "SBOM bundled_binary_container_release remains FAIL; binary/container publication is prohibited."
decisions_needed: []
dependencies_unlocked:
  - R8-RELEASE-NARROW-REVIEW
  - R8-GITHUB-CI
recommended_next:
  - task_id: R8-RELEASE-NARROW-REVIEW
    goal: Independently review release-only increments 7ccbc2d..1e6dee3 for P0/P1, limited to the Range overlay repair, dependency upgrade, provenance, and E2E evidence contract.
    depends_on:
      - R8-RELEASE
  - task_id: R8-GITHUB-CI
    goal: Run a clean install and affected audit/unit/tsc/build/current-product Playwright gates on the repository-exact Node 24.15.0 environment.
    depends_on:
      - R8-RELEASE
```

The Worker scope is complete, but this is not a final source-release declaration. Source readiness remains pending independent narrow review and exact-environment GitHub CI. Binary/container publication remains prohibited by the committed SBOM verdict.
