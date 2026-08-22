# R9-FIX-D L2 Adapter Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-D
thread_id: /root/r9_06_product_integration
branch: codex/r9-fix-l2-adapter
base_commit: bfe9518604cd7ce2b5e20d59b5bf1e98c74caf15
head_commit: aedf71947def900b0357e611136050d2f187ba4e
status: completed
scope:
  goal: Wire R9-FIX-B's authorized Hero infoset policy into the live continuous-table HU-river L2 adapter without widening private-card access.
  included:
    - Passing only ObservationV1.own_hole_cards to L2 and retaining the public-event range projection boundary.
    - Refusing aggregate-only L2 diagnostics as a current Hero B-grade recommendation.
    - Cache/decision identity regression coverage for Hero combo, next decision, and private-opponent poison isolation.
  excluded:
    - L2 core, frontend, artifacts, Bot, Range core, benchmarks, ledger, and dependencies.
changed_files:
  - backend/poker_coach/simulator/continuous_table.py
  - backend/poker_coach/theory/recommendation.py
  - backend/tests/test_theory_recommendation.py
commits:
  - sha: aedf71947def900b0357e611136050d2f187ba4e
    subject: fix(theory): bind live l2 to hero infoset
quality_gates:
  - command: py -3.13 -m pytest backend/tests/test_theory_recommendation.py -q
    result: 10 passed
    measured: true
  - command: py -3.13 -m compileall backend/poker_coach/theory backend/poker_coach/simulator
    result: PASS
    measured: true
  - command: git diff --check
    result: PASS before delivery commit
    measured: true
artifacts:
  - path: backend/poker_coach/simulator/continuous_table.py
    description: Live river adapter passes the acting Hero's already-authorized observation cards to L2; public-event filtering remains the only range source.
  - path: backend/poker_coach/theory/recommendation.py
    description: Aggregate-only L2 diagnostics cannot be rendered as a B-grade Hero recommendation.
  - path: backend/tests/test_theory_recommendation.py
    description: Covers exact Hero infoset policies, Hero-aware cache identity with a hero-free tree key, stale decision cache separation, opponent private-card poison, multiway rejection, and aggregate fallback.
risks:
  - B coverage still requires the authorized Hero combo to be present in the validated public policy projection; otherwise the DTO honestly falls back to C formula guidance.
  - Turn, multiway, unsupported legal trees/stacks, invalid L2 cards, and terminal/non-Hero decisions remain typed fallback or unsupported paths by design.
  - No full backend suite, frontend checks, or end-to-end journey was run; this task only requested focused pytest and compileall.
decisions_needed: []
dependencies_unlocked:
  - R9 continuous-table callers can receive Hero-specific B L2 policy for a supported HU river without exposing cards in theory output.
recommended_next: []
```
