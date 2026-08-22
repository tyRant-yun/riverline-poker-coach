# Local service control handoff

```yaml
contract_version: handoff/v1
task_id: LOCAL-SERVICE-CONTROL
thread_id: /root
branch: codex/local-service-control
base_commit: cbbce681de58bc2096daa71e2770d3842bf6a39c
head_commit: 18afa3c1cb86b0bae6af8c13958ff7f21ef48810
status: completed
scope:
  goal: Provide safe one-command Riverline startup and shutdown for the latest local source release.
  included:
    - start-riverline.ps1 starts the existing local stack, records runtime identity, reuses an existing healthy instance, and opens the Web UI by default
    - stop-riverline.ps1 validates PID, process name, start-time ticks, and project root before stopping the recorded process trees
    - run-local.ps1 atomically records ports, URLs, logs, process identity, mode, and project root in ignored local runtime state
    - README usage and focused static/dynamic safety contracts
  excluded:
    - Windows service installation, tray application, desktop shortcuts, dependency upgrades, product behavior, ledger, and automatic Git updates
changed_files:
  - README.md
  - scripts/run-local.ps1
  - scripts/start-riverline.ps1
  - scripts/stop-riverline.ps1
  - scripts/test-run-local-contract.ps1
  - scripts/test-local-service-control-contract.ps1
  - scripts/test-stop-riverline-safety.ps1
commits:
  - sha: 18afa3c1cb86b0bae6af8c13958ff7f21ef48810
    subject: feat:local-service-control
quality_gates:
  - command: pwsh -NoProfile -File scripts/test-run-local-contract.ps1; pwsh -NoProfile -File scripts/test-local-service-control-contract.ps1; pwsh -NoProfile -File scripts/test-stop-riverline-safety.ps1
    result: all three contracts passed; identity mismatch preserved both test processes and runtime state; valid identity stopped both roots and removed state
    measured: true
  - command: npm ci
    result: 179 packages installed from the frozen lock; 0 vulnerabilities; local Node 24.18.0 emitted the declared-engine 24.15.0 warning
    measured: true
  - command: pwsh -NoProfile -File scripts/start-riverline.ps1 -ApiPort 8201 -WebPort 3201 -NoOpen -StartupTimeoutSeconds 90
    result: API PID 12824 and Web PID 15316 became ready; runtime state was written
    measured: true
  - command: repeat start-riverline.ps1; curl GET API/Web; stop-riverline.ps1 twice; inspect ports
    result: repeated start reused the same PIDs; API and Web returned HTTP 200; first stop removed both process trees/state; second stop reported not running; ports had no LISTENING sockets
    measured: true
  - command: git diff --check
    result: passed before delivery commit
    measured: true
  - command: default start-riverline.ps1 browser opening
    result: not run to avoid opening an interactive browser during automated verification; Start-Process path is covered by the static contract
    measured: false
artifacts:
  - path: scripts/start-riverline.ps1
    description: Daily one-command local start entrypoint; opens http://127.0.0.1:3000 unless -NoOpen is supplied.
  - path: scripts/stop-riverline.ps1
    description: Identity-checked shutdown entrypoint using .data/local-runtime.json.
risks:
  - If Windows denies CIM child enumeration, the script warns and stops only the identity-verified root process; ordinary host smoke successfully stopped both complete trees.
  - The local smoke used Node 24.18.0 rather than the repository-declared 24.15.0; no package or lockfile was changed.
decisions_needed: []
dependencies_unlocked: []
recommended_next: []
```
