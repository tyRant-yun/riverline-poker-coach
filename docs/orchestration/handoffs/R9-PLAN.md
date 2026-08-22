# R9-PLAN handoff

```yaml
contract_version: handoff/v1
task_id: R9-PLAN
thread_id: /root/r9_master_plan
branch: codex/r9-theory-engine
base_commit: 1dac59fb0e9e5af336d6d436f23af7a23058c03b
head_commit: f5484d9288b62cb492a3ef2882265f914ac722dd
status: completed
scope:
  goal: Produce the R9 training-grade, evidence-layered Theory Engine master plan.
  included:
    - Current R8 baseline and structural strategy/range/UI gaps.
    - Benchmark-first canonical spots, oracle hierarchy, measurable red gates and performance budgets.
    - A/B/C evidence semantics, SaaS/license boundary, layered policy architecture and bounded L2 scope.
    - Reuse/replacement map and R9-00 through R9-07 task, dependency, ownership, safety and acceptance plan.
  excluded:
    - Ledger edits, implementation code, solver integration, policy artifacts and release execution.
    - Any claim of complete 6-max GTO coverage or legal conclusion.
changed_files:
  - docs/plans/r9-theory-engine.md
commits:
  - sha: f5484d9288b62cb492a3ef2882265f914ac722dd
    subject: "docs: add R9 theory engine plan"
quality_gates:
  - command: "git diff --check"
    result: "exit 0 before delivery commit; no whitespace errors reported."
    measured: true
  - command: "Get-Content -Raw AGENTS.md; Get-Content -Raw docs/orchestration/handoff-v1.md; targeted ledger/R8/product/research reads"
    result: "Completed only the task-authorized governance and planning reads; AGENTS.md and handoff contract were read in full."
    measured: true
  - command: "Automated unit/backend/frontend/E2E tests"
    result: "Not run: documentation-only plan change; no executable behavior changed."
    measured: false
artifacts:
  - path: docs/plans/r9-theory-engine.md
    description: "R9 scope, evidence model, benchmark-first quality gates, license boundary and execution decomposition."
risks:
  - "The first A-grade preflop artifact source, exact action tree, license and owner remain unverified product decisions."
  - "The L2 engine implementation/compatibility choice remains undecided; AGPL solvers are explicitly excluded from the SaaS-ready path pending professional review."
  - "Metric thresholds require R9-00 baseline/oracle calibration and are intentionally not fabricated in this plan."
decisions_needed:
  - "Select and approve the provenance/license and coverage contract for the first preflop PolicyArtifact."
  - "Choose the approved L2 implementation path after license and operational review."
  - "Confirm default training mode and whether scoring uses frequency deviation, same-oracle EV loss, or both."
dependencies_unlocked:
  - R9-00
recommended_next:
  - task_id: R9-00
    goal: Build the canonical-spot benchmark harness with versioned oracle manifests, red fixtures, metric reports and frozen thresholds.
    depends_on:
      - R9-PLAN
```

The delivery commit deliberately contains only the master plan. This handoff is the subsequent governance commit and therefore is not included in `head_commit` or `commits`.
