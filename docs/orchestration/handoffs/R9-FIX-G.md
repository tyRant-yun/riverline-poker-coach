# R9-FIX-G Test Contract Handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-G
thread_id: /root/r9_fix_f_product_truth
branch: codex/r9-fix-g-test-contract
base_commit: 87b1381478c51fc4735bbad91cb664e64cac496c
head_commit: 3b9a7ea9a38879ffdb94a3ec88309c49cd3a9e7f
status: completed
scope:
  goal: Align the stale bot-provider release test with R9's frozen honest-degradation contract.
  included:
    - Preserve the shared runtime legality assertion for every profile and legal-action shape.
    - Assert that the out-of-coverage theory profile is degraded with C evidence, fallback coverage, and multiway_or_table_size provenance.
    - Retain non-degraded expectations for fixed and lightweight blueprint profiles.
  excluded:
    - Product implementation, fixtures, other tests, full suites, ledger, dependencies, and release operations.
changed_files:
  - backend/tests/test_bot_providers.py
commits:
  - sha: 3b9a7ea9a38879ffdb94a3ec88309c49cd3a9e7f
    subject: test: align theory fallback contract
quality_gates:
  - command: py -3.13 -m pytest "backend/tests/test_bot_providers.py::test_every_profile_decision_is_runtime_accepted_and_uses_legal_amounts[theory-legal_actions0]" -q
    result: 1 passed
    measured: true
  - command: py -3.13 -m pytest backend/tests/test_bot_providers.py backend/tests/test_policy_artifact.py -q
    result: 45 passed
    measured: true
  - command: git diff --check
    result: PASS before delivery commit
    measured: true
artifacts:
  - path: backend/tests/test_bot_providers.py
    description: Release test now distinguishes legal action acceptance from honest theory evidence degradation.
risks: []
decisions_needed: []
dependencies_unlocked:
  - R9-07 release gate can rerun the backend suite without the stale theory fallback assertion.
recommended_next:
  - task_id: R9-07
    goal: Rerun the previously failing release gate at the integrated head.
    depends_on:
      - R9-FIX-G
```
