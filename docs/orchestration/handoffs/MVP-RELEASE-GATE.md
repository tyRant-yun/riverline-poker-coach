# MVP Release Gate handoff

```yaml
contract_version: handoff/v1
task_id: MVP-RELEASE-GATE
thread_id: 019ff53a-fe87-7353-b7cc-ac3288f0553e
branch: codex/mvp-release-gate
base_commit: 96da3830aefbcd0de4289b5f565079748347bc94
head_commit: 96da3830aefbcd0de4289b5f565079748347bc94
status: completed
mvp_candidate: FAIL
scope:
  goal: Run the single MVP stage-exit backend, frontend, E2E, license, and local-service release gate and record reproducible evidence without developing features.
  included:
    - Full Python 3.13 backend test, compile, and dependency-consistency gates.
    - Offline lock-based frontend install, all Vitest tests, TypeScript, production build, and all configured Playwright E2E specs.
    - Local manifest/resolved-package license inspection and prohibited solver dependency check.
    - Isolated hidden-process HTTP smoke for health, continuous table, insights, completed review, reconnect, and public-response privacy.
  excluded:
    - New features, dependency installation from the network, solver adoption, central ledger changes, GitHub publication, main merge, release publication, worktree deletion, and live PostgreSQL infrastructure provisioning.
changed_files: []
commits: []
quality_gates:
  - command: py -3.13 -m pytest -q -ra
    result: 536 passed, 10 skipped in 71.01s; 546 collected from the completed pytest cache. All skips explicitly require absent POKER_COACH_TEST_PG_URL. Existing PokerKit warnings concern Riverline PHH extension-field naming.
    measured: true
  - command: py -3.13 -m compileall -q backend/poker_coach backend/tests
    result: exit 0 in 0.24s
    measured: true
  - command: py -3.13 -m pip check
    result: No broken requirements found in 1.45s
    measured: true
  - command: npm cache verify --offline
    result: existing npm cache verified; 1,857 content objects were available locally
    measured: true
  - command: npm ci --offline --ignore-scripts
    result: exit 0 in 15.86s; 179 packages installed from lock/cache, npm audit reported 0 vulnerabilities
    measured: true
  - command: npm test
    result: 31 test files and 161 tests passed in 19.34s
    measured: true
  - command: npx tsc --noEmit
    result: exit 0 in 3.01s
    measured: true
  - command: npm run build
    result: Next.js 16.1.0 production build passed in 18.32s; generated next-env.d.ts change was restored to the baseline content and not delivered
    measured: true
  - command: npx playwright test
    result: all 9 E2E tests passed in 19.55s, including continuous table create/legal action/completion/next/reconnect/error, review workbench, coach flow, and multiseat coverage
    measured: true
  - command: py -3.13 - <inline importlib.metadata checker for backend/pyproject.toml plus prohibited-solver manifest/lock scan>
    result: all direct and optional Python versions matched; licenses were MIT, BSD-3-Clause, or LGPL-3.0-only as recorded; postflop-solver, TexasSolver, Texas Holdem Solver, PokerRL, and openCFR were absent from runtime manifests and locks
    measured: true
  - command: node -e <inline frontend direct/resolved package license enumeration>; npm ls --all --json
    result: dependency tree resolved; direct versions/licenses matched package.json and THIRD_PARTY_NOTICES. Resolved licenses included 148 MIT, 11 Apache-2.0, and one @img/sharp-win32-x64 0.34.5 binary package declared Apache-2.0 AND LGPL-3.0-or-later
    measured: true
  - command: Start-Process -WindowStyle Hidden py -ArgumentList '-3.13','-m','uvicorn','poker_coach.api.app:app','--app-dir','backend','--host','127.0.0.1','--port','8000'; py -3.13 - <inline HTTP smoke>; Stop-Process -Id 5292
    result: exit 0 in 3.23s; health ok; created table; completed one hand with 4 hero actions; fetched active/next-hand insights; fetched completed review list/get; advanced to hand 2; reconnect fingerprint matched. Opponent hole cards were absent from table seats, and insights/reviews contained no hole-card, payout, RNG-seed, deck, or future-board fields. Only PID 5292 was stopped and port cleanup was confirmed.
    measured: true
  - command: live PostgreSQL regression via POKER_COACH_TEST_PG_URL
    result: not run because no live PostgreSQL URL/service was provided; the full backend suite reported the 10 conditional skips
    measured: false
artifacts:
  - path: docs/orchestration/handoffs/MVP-RELEASE-GATE.md
    description: Stage-exit commands, measured results, environment limits, release blocker, and candidate decision.
  - path: C:/Users/Administrator/AppData/Local/Temp/riverline-mvp-smoke-a6fba4dc919b4b7d8b0d64712820f833
    description: Retained local smoke SQLite databases and uvicorn logs; no data was deleted.
environment:
  python: 3.13.14
  node: 24.18.0
  npm: 11.16.0
  playwright: 1.62.1
  frontend_ci_reference_node: 20.x
license_findings:
  - No AGPL/GPL solver was installed or introduced into the application dependency graphs.
  - Riverline source remains AGPL-3.0-or-later and direct dependency records align with the checked manifests.
  - THIRD_PARTY_NOTICES explicitly states that a release is not provenance-complete until the fully resolved dependency graph, licenses, integrity hashes, and required NOTICE texts are exported; that automation does not exist in the repository.
  - The resolved Windows frontend graph includes @img/sharp-win32-x64 under Apache-2.0 AND LGPL-3.0-or-later, so binary distribution needs the applicable LGPL source/notice handling captured by the missing provenance output.
p0_p1:
  product: []
  release_blockers:
    - P1 license provenance is incomplete: no release SBOM/full transitive license-integrity/NOTICE export exists, and the resolved sharp Windows binary obligation is not closed by the current notice ledger.
unmeasured:
  - Live PostgreSQL tests and recovery/backup exercise.
  - CI parity on the declared Node 20 runner; local frontend gates used Node 24.18.0.
risks:
  - Functional MVP behavior is green, but publishing/distributing a candidate before closing the recorded provenance/NOTICE requirement would contradict THIRD_PARTY_NOTICES.
  - Local SQLite smoke evidence does not replace the unmeasured live PostgreSQL gate.
decisions_needed: []
dependencies_unlocked: []
recommended_next:
  - task_id: LICENSE-PROVENANCE-GATE
    goal: Generate and review the full locked Python/npm SBOM, integrity, license, source-offer, and NOTICE evidence without changing application dependencies, then re-evaluate the binary release decision.
    depends_on:
      - MVP-RELEASE-GATE
```

## Candidate decision

`FAIL` for release publication, solely because the repository's own license provenance exit criterion is not complete. Backend, frontend, production build, all configured Playwright E2E, and isolated API/privacy smoke gates passed with no product P0/P1 found. The complete functional gates were not repeated.

The service smoke used fresh SQLite files under the artifact directory. Its terminal table response intentionally contained the public settlement result; the privacy assertion applies to opponent private cards everywhere and to payout/future facts in insights and automatic-review projections, matching the focused API contracts.
