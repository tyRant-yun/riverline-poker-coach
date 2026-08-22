# R9-FIX-A Benchmark/Artifact/Bot Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-A
thread_id: /root/r9_02_policy_bot
branch: codex/r9-fix-policy-benchmark
base_commit: e1c8ace8ecebf36df420fb8531aec6e765cea0f9
head_commit: c890117ac4b03822f4c1319e8680637684bfaa32
status: completed
scope:
  goal: Close the provider-backed benchmark, artifact validation/provenance, and honest Bot fallback P1 findings.
  included:
    - Live PolicyArtifact provider smoke separated from the frozen oracle fixture candidate and timed around the adapter invocation.
    - Strict canonical 169-class/1326-combo, action, sizing, B-grade generation/source/release-manifest validation.
    - C-grade fallback metadata for artifact legal/coverage misses and focused audit-regression tests.
  excluded:
    - L2 core changes, Range/recommendation/frontend/ledger/dependency changes, complete-GTO claims, and external strategy data.
changed_files:
  - backend/poker_coach/simulator/bot_providers.py
  - backend/poker_coach/theory/__main__.py
  - backend/poker_coach/theory/benchmark.py
  - backend/poker_coach/theory/policy_artifact.py
  - backend/poker_coach/theory/policy_artifact_data.py
  - backend/tests/test_policy_artifact.py
  - backend/tests/test_theory_benchmark.py
commits:
  - sha: c890117ac4b03822f4c1319e8680637684bfaa32
    subject: "fix(theory): gate verified policy provider"
quality_gates:
  - command: py -3.13 -m pytest tests/test_theory_benchmark.py tests/test_policy_artifact.py tests/test_bot_providers.py -q
    result: focused regression suite passed (exit 0); includes real-provider, mutant-fixture isolation, unsupported-policy red, canonical-class and fallback-grade cases.
    measured: true
  - command: py -3.13 -m compileall -q poker_coach/theory poker_coach/simulator
    result: exit 0.
    measured: true
  - command: py -3.13 -m poker_coach.theory --provider-smoke
    result: provider-green-6max-preflop-b gate_passed=true; real artifact adapter latency measured in result.
    measured: true
  - command: git diff --check
    result: exit 0.
    measured: true
  - command: full backend suite
    result: not run; scoped repair contract requires focused verification only.
    measured: false
artifacts:
  - path: backend/poker_coach/theory/benchmark.py
    description: provider-backed PolicyArtifact smoke evaluator that does not consume the fixture candidate.
  - path: backend/poker_coach/theory/policy_artifact.py
    description: strict canonical artifact and B-grade release-manifest validator.
risks:
  - L2's existing adapter was inspected only; R9-FIX-A did not alter L2 core or claim a new L2 provider gate.
  - The preflop artifact remains an owned B-grade blueprint with deliberately bounded tree coverage, not GTO.
decisions_needed: []
dependencies_unlocked:
  - R9-FIX-A-REVIEW
recommended_next:
  - task_id: R9-FIX-A-REVIEW
    goal: Review this repair diff with focus on provider/oracle separation and evidence downgrade semantics.
    depends_on:
      - R9-FIX-A
```
