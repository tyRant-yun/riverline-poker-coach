```yaml
contract_version: handoff/v1
task_id: R9-FIX-E
thread_id: /root/r9_fix_e_benchmark
branch: codex/r9-fix-e-benchmark
base_commit: 34c87b32da7ca576157d39f50b39a7e17c6d5e67
head_commit: 679051b6118c0d624ebf037bf381d20f21955b06
status: completed
scope:
  goal: Replace the R9 release benchmark's fixture-candidate self-check with a live provider-backed release gate.
  included:
    - Default theory CLI now runs the live provider release gate; --verify-corpus retains the intentional fixture mutant corpus.
    - Frozen references cover all ten declared preflop artifact nodes and the declared bounded HU-river L2 root spot.
    - Release results report the exact provider/spot that fails and compare identity, grade, action set, frequency tolerance, sizing, provider identity, and latency.
    - Focused regressions prove mutating a fixture candidate cannot certify the release gate.
  excluded:
    - Recommendation DTO semantics, continuous-table live-tree validation, API/UI, ledger, full-suite gates, and external downloads.
changed_files:
  - backend/poker_coach/theory/__main__.py
  - backend/poker_coach/theory/benchmark.py
  - backend/tests/test_theory_benchmark.py
commits:
  - sha: 679051b6118c0d624ebf037bf381d20f21955b06
    subject: fix: gate theory release through live providers
quality_gates:
  - command: $env:PYTHONPATH='backend'; py -3.13 -m pytest -q backend/tests/test_theory_benchmark.py; py -3.13 -m poker_coach.theory; py -3.13 -m poker_coach.theory --verify-corpus
    result: 13 passed; default live-provider release gate exited 0 with 11/11 provider spots passing; fixture corpus verification exited 0 with intentional red fixtures rejected as declared.
    measured: true
  - command: git diff --check
    result: passed (no whitespace errors)
    measured: true
artifacts:
  - path: backend/poker_coach/theory/benchmark.py
    description: Provider-backed release benchmark registry and frozen comparisons for declared R9 theory providers/spots.
  - path: backend/poker_coach/theory/__main__.py
    description: Default CLI release-gate entry point; fixture corpus is explicitly non-release verification.
risks:
  - The frozen references intentionally cover only the R9 declared B-grade preflop nodes and bounded HU-river root; unsupported postflop/multiway/turn spots remain outside the product's claimed coverage.
  - L2 reference is deterministic for its fixed seed/iteration budget; changing that solver contract intentionally requires a reference/version decision.
decisions_needed: []
dependencies_unlocked:
  - R9-07
recommended_next:
  - task_id: R9-07
    goal: Integrate accepted repairs and run the final release gates, including the default provider-backed theory benchmark.
    depends_on:
      - R9-FIX-E
```
