# R9-FIX-H handoff

```yaml
contract_version: handoff/v1
task_id: R9-FIX-H
thread_id: /root/r9_fix_h_pytest_hang
branch: codex/r9-fix-h-pytest-hang
base_commit: 8485931805266401b3be923e1b2e171fdabcc54f
head_commit: 3a0cca63ea3aeb0e40fe495fb071a72b985ff3f3
status: completed
scope:
  goal: Remove the repeated asyncio event-loop lifecycle from the release-blocking seeded policy sampling test.
  included:
    - Single-loop async sampling for the existing 10,000-seed artifact-frequency contract.
    - Regression assertion that the sampling contract creates one event loop.
  excluded:
    - Production policy behavior and artifact data changes.
    - Full-suite execution and unrelated test optimization.
changed_files:
  - backend/tests/test_policy_artifact.py
commits:
  - sha: 3a0cca63ea3aeb0e40fe495fb071a72b985ff3f3
    subject: "test: reuse one event loop for policy sampling"
quality_gates:
  - command: "py -3.13 -m pytest backend/tests/test_policy_artifact.py::test_seeded_mixed_policy_is_reproducible_legal_and_tracks_artifact_frequency -q"
    result: "Pre-fix lifecycle assertion/red run exceeded 45 seconds with the owned pytest process idle and was terminated; it established the repeated-event-loop resource-lifecycle failure mode."
    measured: true
  - command: "PowerShell watchdog (12 seconds) running C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m pytest backend/tests/test_policy_artifact.py::test_seeded_mixed_policy_is_reproducible_legal_and_tracks_artifact_frequency -q"
    result: "exit 0; 1 passed within the watchdog after the single-loop repair."
    measured: true
  - command: "py -3.13 -m pytest backend/tests/test_phh_codec.py -vv -s"
    result: "7 passed in 1.05s; PHH itself did not reproduce the stall."
    measured: true
  - command: "py -3.13 -m pytest backend/tests/test_outbox_recovery.py backend/tests/test_persistence.py backend/tests/test_phh_codec.py backend/tests/test_pokerkit_adapter.py -x -vv -s"
    result: "49 passed in 2.18s; the immediate PHH neighborhood did not reproduce a cross-test leak."
    measured: true
artifacts:
  - path: backend/tests/test_policy_artifact.py
    description: "Seeded B-grade policy frequency contract now samples inside one bounded asyncio lifecycle."
risks:
  - "The original full-suite run was not repeated here by scope; R9-07 must rerun its release gate from the integrated head."
  - "The diagnosis proves and removes repeated event-loop creation in the slow test; any independent later-suite stall should be diagnosed separately."
decisions_needed: []
dependencies_unlocked:
  - R9-07
recommended_next:
  - task_id: R9-07
    goal: "Integrate this focused lifecycle repair and rerun the release gate."
    depends_on:
      - R9-FIX-H
```
