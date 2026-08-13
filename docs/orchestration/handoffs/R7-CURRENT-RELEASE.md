# R7 Current Snapshot Release handoff

```yaml
contract_version: handoff/v1
task_id: R7 Current Snapshot Release
thread_id: 019ff53a-fe87-7353-b7cc-ac3288f0553e
branch: codex/r7-current-snapshot-release
base_commit: e7ae8e83aa8392085465d71fa89c980d31ab40ae
delivery_head: 76e2dcca9337a2c56e11b8c68b26c426cbc3553c
governance_head: 6eeafd68095464bd02e2ae2ecf6bcfef36992222
status: completed
release_verdict: PASS
scope:
  goal: Validate and document the current R7 source snapshot without launching R7-03 or changing Range V2/Solver L1.5/L2 product scope.
  included:
    - Full backend/frontend release gates and focused isolated local-experience Playwright smoke.
    - Current-contract test alignment for stale R6 Range-prior and retired route assertions.
    - A local-runner CORS fix for explicitly configured alternative web ports.
    - Source-release documentation.
  excluded:
    - R7-03 Range V2, Solver L1.5/L2, GitHub push/PR creation, merge to main, GitHub Release, binary/container artifact publication, and central ledger changes.
commits:
  - sha: 76e2dcca9337a2c56e11b8c68b26c426cbc3553c
    subject: "chore(release): align current snapshot gates"
changed_files:
  - README.md
  - backend/tests/test_seat_priors.py
  - docs/releases/r7-current-snapshot.md
  - frontend/e2e/local-experience.spec.ts
  - frontend/features/table/ContinuousTablePage.test.tsx
  - frontend/features/workspace/SelectedDecisionWorkspace.test.tsx (deleted; unreachable retired route)
  - frontend/features/workspace/WholeHandReviewPage.test.tsx (deleted; unreachable retired route)
  - scripts/run-local.ps1
  - scripts/test-run-local-contract.ps1
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_seat_priors.py backend/tests/test_event_beliefs.py -q
    result: 19 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests -q
    result: passed; passed count not captured in the retained test output; 10 existing environment/live-service skips
    measured: true
  - command: py -3.13 -m compileall -q backend
    result: exit 0
    measured: true
  - command: py -3.13 -m pip check
    result: No broken requirements found
    measured: true
  - command: npm test -- --run features/table/ContinuousTablePage.test.tsx
    result: 1 file / 7 tests passed
    measured: true
  - command: npm test; npx tsc --noEmit; npm run build
    result: 32 files / 165 tests passed; TypeScript and production build exit 0
    measured: true
  - command: py -3.13 tools/generate_license_provenance.py --check
    result: PASS
    measured: true
  - command: scripts/test-run-local-contract.ps1
    result: passed
    measured: true
  - command: PLAYWRIGHT_BASE_URL=http://127.0.0.1:3103 npx playwright test e2e/continuous-table.spec.ts e2e/local-experience.spec.ts
    result: 2 passed against run-local SQLite/no-Redis services on 8103/3103
    measured: true
risks:
  - Range remains the current V1 first-party position/stack heuristic with public-event updates, not GTO, player profiling, or a joint opponent range.
  - Fast Solver remains current L1 approximate EV, not GTO/Nash; its displayed limitations remain binding.
  - source provenance check passed; this task did not build bundled native artifacts. Binary/container distribution remains separately blocked pending LGPL artifact-obligation verification.
  - Live PostgreSQL/Redis tests were not provisioned and remained correctly skipped.
unmeasured:
  - GitHub PR/check state was not queried by this task.
  - No GitHub push, PR creation, merge, release, Docker image, wheel, installer, or bundled binary was performed.
decisions_needed: []
dependencies_unlocked:
  - Controller may evaluate this source-only release candidate for its authorized GitHub workflow.
recommended_next:
  - task_id: controller
    goal: Review this handoff and perform any separately authorized remote GitHub source-branch/PR action.
```
