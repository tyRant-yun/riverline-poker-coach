# R9-FIX-B L2 Security Repair Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-B
thread_id: /root/r9_04_solver_l2
branch: codex/r9-fix-l2
base_commit: e1c8ace8ecebf36df420fb8531aec6e765cea0f9
head_commit: 7fe31888cb163b3e442aab689492e5535c247e41
status: completed
scope:
  goal: Close L2 canonical-card and cross-Hero aggregate-policy P1 findings without expanding production integration scope.
  included:
    - Domain Card/RangeCombo-based canonical deck preparation with typed invalid/unsupported results for aliases, unknown cards, board collisions, and canonical physical duplicates.
    - Immutable Hero-own-hole-card input, hashed decision identity, Hero-specific CFR root infoset selection, and explicit unavailable/fallback status when Hero cards are absent or outside the projected range.
    - Separate diagnostic aggregate frequencies from recommendation frequencies; the benchmark adapter refuses aggregate-only output as a Hero recommendation.
    - Decision cache keys bind Hero, game/tree/range, solver configuration and artifact fingerprint; tree cache identity remains Hero-free and is exposed only as provenance.
    - Focused regression coverage for aliases, `2c` plus `2C`, unknown cards, infoset-vs-aggregate behavior, Hero/artifact cache isolation, and existing oracle/regret gates.
  excluded:
    - continuous-table, recommendation, UI, Range, Artifact, benchmark-contract, dependency and ledger changes.
changed_files:
  - backend/poker_coach/theory/l2_solver.py
  - backend/tests/test_l2_solver.py
commits:
  - sha: 7fe31888cb163b3e442aab689492e5535c247e41
    subject: fix(theory): bind L2 policy to hero infoset
quality_gates:
  - command: py -3.13 -m pytest tests/test_l2_solver.py tests/test_theory_benchmark.py -q
    result: 24 passed
    measured: true
  - command: py -3.13 -m compileall poker_coach/theory
    result: PASS
    measured: true
  - command: py -3.13 -m poker_coach.theory --verify-corpus
    result: PASS; corpus_expectations_met=true; intentional red fixtures remain red.
    measured: true
  - command: git diff --cached --check
    result: PASS before delivery commit
    measured: true
artifacts:
  - path: backend/poker_coach/theory/l2_solver.py
    description: Bounded L2 input/output and cache boundary that rejects noncanonical cards and exposes a policy only for the requesting Hero's exact projected combo.
  - path: backend/tests/test_l2_solver.py
    description: Focused P1 regression suite covering card identity, typed invalid paths, Hero policy selection, aggregate denial, cache isolation, oracle and regret behavior.
risks:
  - Existing callers that omit hero_hole_cards now receive aggregate diagnostics only, with no L2 recommendation. A separately authorized integration change must pass only the acting Hero's already-authorized exact cards to regain L2 recommendation coverage.
  - Turn/multiway and unsupported tree/range/stack inputs remain explicitly unsupported; this repair does not enlarge solver coverage.
  - No full backend/integration suite was run; only the scoped L2 and frozen corpus gates were measured.
decisions_needed: []
dependencies_unlocked:
  - R9-05
  - R9-06
recommended_next:
  - task_id: R9-FIX-C
    goal: Update authorized L2 integration callers to supply the acting Hero's existing private projection and preserve aggregate-only fallback when it is unavailable.
    depends_on:
      - R9-FIX-B
```
