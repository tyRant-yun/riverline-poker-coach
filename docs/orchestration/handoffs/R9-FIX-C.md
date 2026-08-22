# R9-FIX-C product semantics handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-C
thread_id: /root/r9_06_product_integration
branch: codex/r9-fix-product-semantics
base_commit: e1c8ace8ecebf36df420fb8531aec6e765cea0f9
head_commit: 5b7acef8b0695477a59d82ece920e401371e6092
status: completed
scope:
  goal: Close Theory coverage, Formula-frequency, training-score, and live-L2 tree-semantics P1 audit findings.
  included:
    - Additive Coverage metadata for tree, sizing abstraction, stack bucket, rake, and ante; Theory UI renders all fields with the existing source/version/fingerprint/reason facts.
    - C Formula fallback now exposes no policy frequencies or strategy recommendation; UI calls it formula tendency without a strategy frequency.
    - Training feedback is B-only and matches action, amount semantics, and exact submitted sizing before assigning a frequency.
    - Live L2 requires a HU river root with exactly legal check/bet, fixed by-amount sizing, and no legal raise; otherwise the existing C fallback remains.
  excluded:
    - L2 core, PolicyArtifact/Bot/Range core, benchmark contracts, Hero exact-infoset work, ledger, and dependencies.
changed_files:
  - backend/poker_coach/simulator/continuous_table.py
  - backend/poker_coach/theory/recommendation.py
  - backend/tests/test_theory_recommendation.py
  - frontend/features/table-v2/TableWorkspaceV2.test.tsx
  - frontend/features/table-v2/TableWorkspaceV2.tsx
  - frontend/features/table/ContinuousTablePage.tsx
  - frontend/types/api.ts
commits:
  - sha: 5b7acef8b0695477a59d82ece920e401371e6092
    subject: "fix(theory): preserve product evidence semantics"
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_theory_recommendation.py -q
    result: 8 passed.
    measured: true
  - command: npm run test -- features/table-v2/TableWorkspaceV2.test.tsx features/table/ContinuousTablePage.test.tsx
    result: 2 files / 23 tests passed.
    measured: true
  - command: npm run lint
    result: tsc --noEmit exited 0.
    measured: true
  - command: npm run test:e2e -- e2e/continuous-table.spec.ts
    result: 1 passed.
    measured: true
artifacts:
  - path: backend/poker_coach/theory/recommendation.py
    description: Additive coverage metadata and no-frequency Formula fallback contract.
  - path: frontend/features/table-v2/TableWorkspaceV2.tsx
    description: User-visible coverage facts and explicit formula-only semantics.
risks:
  - Exact Hero infoset validation is intentionally deferred to R9-FIX-B; this task does not alter L2 core or assume that contract.
decisions_needed: []
dependencies_unlocked:
  - R9-FIX-B
recommended_next:
  - task_id: R9-FIX-B
    goal: Add the separate Hero exact-infoset contract before any further L2 adapter integration.
    depends_on:
      - R9-FIX-C
```
