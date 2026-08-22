# R9-FIX-F Product Truth Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-F
thread_id: /root/r9_fix_f_product_truth
branch: codex/r9-fix-f-product-truth
base_commit: 34c87b32da7ca576157d39f50b39a7e17c6d5e67
head_commit: 57571482306b6f8dbb55f4e67f79edeb8330ae40
status: completed
scope:
  goal: Make live theory, Artifact Bot, and UI provenance tell one honest evidence-grade story without exposing Hero private cards.
  included:
    - C Formula and unsupported theory responses omit policy action, sizing, frequencies, ranges, and policy EV fields while retaining explanatory facts.
    - Positive-mass Artifact actions that are illegal in the current authoritative action set downgrade to C instead of being re-normalized into B.
    - PolicyArtifactBot's intentional fallback is a top-level degraded BotDecision with failed-policy provenance, persisted evidence grade/coverage, and visible UI label.
    - Live HU river L2 uses only the private Hero exact infoset internally, never injects it into public Range Belief material, preserves Hero-free tree-cache identity, and only claims B for an opponent-coverable Hero jam tree.
  excluded:
    - Benchmark module or CLI changes.
    - Full 6-max GTO, turn/multiway solving, external policy artifacts, dependencies, ledger, and full test suites.
changed_files:
  - backend/poker_coach/simulator/bot_providers.py
  - backend/poker_coach/simulator/bot_runtime.py
  - backend/poker_coach/simulator/continuous_table.py
  - backend/poker_coach/simulator/contracts.py
  - backend/poker_coach/theory/l2_solver.py
  - backend/poker_coach/theory/recommendation.py
  - backend/tests/test_policy_artifact.py
  - backend/tests/test_theory_recommendation.py
  - frontend/features/table-v2/TableWorkspaceV2.test.tsx
  - frontend/features/table-v2/TableWorkspaceV2.tsx
  - frontend/types/api.ts
commits:
  - sha: 57571482306b6f8dbb55f4e67f79edeb8330ae40
    subject: fix: preserve honest theory degradation
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_theory_recommendation.py backend/tests/test_policy_artifact.py -q
    result: 28 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_theory_recommendation.py backend/tests/test_policy_artifact.py backend/tests/test_continuous_table_api.py -q
    result: 28 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_l2_solver.py -q
    result: 15 passed
    measured: true
  - command: npm run test -- --run features/table-v2/TableWorkspaceV2.test.tsx
    result: not run; frontend/node_modules lacks vitest (command reported 'vitest' is not recognized); no dependencies installed or upgraded
    measured: false
  - command: git diff --check
    result: PASS before delivery commit
    measured: true
artifacts:
  - path: backend/poker_coach/theory/recommendation.py
    description: C/unsupported theory DTOs are explanation-only and cannot masquerade as a policy recommendation.
  - path: backend/poker_coach/simulator/continuous_table.py
    description: Persistent bot provenance now carries evidence grade and coverage status; the live L2 adapter restricts B coverage to the safe jam tree.
  - path: backend/poker_coach/theory/l2_solver.py
    description: Hero-specific solver cache identity remains separate while the tree cache key remains hero-free.
  - path: frontend/features/table-v2/TableWorkspaceV2.tsx
    description: Action timeline shows B/C/unsupported grade and coverage beside Bot provenance.
risks:
  - Frontend targeted Vitest was not available in this worktree; the committed UI test is unexecuted and must run in a dependency-complete release worktree.
  - Live L2 deliberately rejects non-jam river bet trees because the bounded solver has no opponent raise branch; rejected spots fall through to C Formula.
  - C Formula is intentionally explanatory only, so it cannot provide a frequency, sizing, range, or EV comparison.
decisions_needed: []
dependencies_unlocked:
  - R9 final auditors can re-check the product truth chain with C/unsupported payloads, Artifact fallback provenance, and safe live L2 coverage.
recommended_next:
  - task_id: R9-07
    goal: Run release gates, including the unexecuted targeted frontend test in a dependency-complete worktree, after audit acceptance.
    depends_on:
      - R9-FIX-F
```
