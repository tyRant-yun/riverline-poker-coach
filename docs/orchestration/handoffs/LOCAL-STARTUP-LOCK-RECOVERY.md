# Local startup lock recovery handoff

```yaml
contract_version: handoff/v1
task_id: LOCAL-STARTUP-LOCK-RECOVERY
thread_id: 01a01ef7-0a9c-7880-aafd-7d5f7fe89534
branch: codex/simulator-rebuild
base_commit: fa72c37ea148192b4999fbb25f14438ff74b3945
head_commit: a3ebc0db5d1c60cc5cac44b9791939db4090406a
status: completed
scope:
  goal: Make the local launcher diagnose an exited or lock-blocked Next.js frontend immediately and keep cleanup limited to its own started process trees.
  included:
    - Detect an API or frontend child process exiting during HTTP readiness polling instead of waiting for the whole timeout.
    - Safely clear an unlocked stale Next.js development lock and fail explicitly when another Next.js process holds it.
    - Preserve cleanup when child-process enumeration fails and add static launch-contract coverage.
  excluded:
    - Changes to application behavior, ports, Node dependencies, .env, or existing user-owned processes.
changed_files:
  - scripts/run-local.ps1
  - scripts/test-run-local-contract.ps1
commits:
  - sha: a3ebc0db5d1c60cc5cac44b9791939db4090406a
    subject: "fix: make local launcher fail fast on frontend errors"
quality_gates:
  - command: pwsh -NoProfile -File scripts\\test-run-local-contract.ps1
    result: run-local.ps1 contract passed
    measured: true
  - command: git diff --check
    result: exit 0 (Git emitted existing line-ending conversion warnings only)
    measured: true
  - command: .\\scripts\\run-local.ps1 -ApiPort 8200 -WebPort 3200 -StartupTimeoutSeconds 30; HTTP GET /health and /; taskkill only the two validation process trees; confirm ports released
    result: launcher reported ready; API and Web each returned HTTP 200; validation process trees were stopped and ports 8200/3200 were free
    measured: true
artifacts:
  - path: scripts/run-local.ps1
    description: Local API/Web launcher with early child-exit diagnostics and safe Next.js lock handling.
  - path: scripts/test-run-local-contract.ps1
    description: Static regression contract for early-exit and live-lock diagnostics.
risks:
  - A live Next.js development lock remains intentionally non-destructive: the launcher reports its path and asks the user to stop the owning development server.
decisions_needed: []
dependencies_unlocked:
  - Local user validation with clearer startup failure diagnostics
recommended_next:
  - task_id: LOCAL-MVP-USER-VALIDATION
    goal: Start the project from the intended user workspace and collect product feedback.
    depends_on:
      - LOCAL-STARTUP-LOCK-RECOVERY
```
