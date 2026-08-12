# Riverline orchestration ledger

状态：主控任务单写

本文件是跨独立 Codex 任务的中央执行台账。Worker 读取它判断入口与依赖，但不直接修改中央状态行；Worker 只新增 `docs/orchestration/handoffs/<task-id>.md`。主控在复核 handoff、Git 事实和质量证据，并完成验收/合并后更新本台账，从而避免并行任务争用同一文件。

本文件中的 F0 行是治理机制建立时按产品负责人指令写入的 bootstrap 记录；合入中央分支后由主控继续维护。

## 状态语义

| Controller state | 含义 |
|---|---|
| `in_progress` | Worker 已派发并正在独立 worktree 执行 |
| `pending_acceptance` | Worker 已回传，主控尚未验收/合并 |
| `accepted` | 主控已复核并接受交付事实 |
| `merged` | 已进入指定集成目标，依赖可按台账解锁 |
| `blocked` | 主控确认存在未解决的外部阻塞或产品决定 |

Worker handoff 的 `completed` 不自动等于 ledger 的 `accepted` 或 `merged`。

## 执行台账

| Task | Thread | Worker status | Controller state | Branch | Base | Delivery head | Handoff | Quality evidence | Dependencies unlocked | Recommended next |
|---|---|---|---|---|---|---|---|---|---|---|
| F0 Simulator Foundation | `019ff359-28b9-7630-992f-b22c82ab1686` | `completed` | `merged` | `codex/f0-simulator-foundation` | `71acce7` | `b0f13e34c3947dd790ada996554bc7216774411e` | [F0 handoff](handoffs/F0.md) | Backend 371 passed/8 skipped；compileall/pip check；17 F0 tests；3,000 evaluator samples/0 mismatch；frontend not measured | F1-01 | F1-01 Authoritative Session ownership/config |
| F1-01 Authoritative Session | `019ff3b0-f805-7ff3-b510-ff5e778bcaf0` | `completed` | `merged` | `codex/f1-01-authoritative-session` | `8dde576a0818be554a38e0420b025d4cd3bb51a7` | `141b1c57872353a8498f3aedba021e3726318315` | [F1-01 handoff](handoffs/F1-01.md) | Worker: backend 381 passed/8 skipped、27 focused passed、compileall/pip check；Controller: 18 session/contract/replay passed | F1-02 | F1-02 durable event append |
| F1-02 Durable Event Append | `019ff3c7-554f-7c60-8b96-5e521dd617c9` | `completed` | `merged` | `codex/f1-02-durable-hand-event-append` | `6840ed5a5488b6af6681e1a9f565c49cfb7b8cbe` | `00c1fd6d019eb4a3ed285701eb560fdcc0416c59` | [F1-02 handoff](handoffs/F1-02.md) | Worker: backend 395 passed/9 skipped、14 focused passed、offline PG SQL/compileall/pip check；Controller: 14 passed/9 live-PG skipped | F1-03、F1-04 | F1-03 PokerKit orchestrator first |

## 下一入口

`F1-03`：实现 command → PokerKit-backed reducer → atomic append，保证每个已接受动作重新经规则权威校验、筹码守恒与固定 seed fingerprint。F1-04 同样已解锁，但为控制额度与集成复杂度，等待 F1-03 进入稳定实现后再启动。

## 主控验收记录

- 2026-08-12：F0 交付提交 `b0f13e3` 与治理提交 `53d99c3` 构成从基线 `71acce7` 开始的严格线性提交链；handoff 的 31 个交付文件与 Git diff 一致。
- 2026-08-12：F0 已快进进入 `codex/simulator-rebuild`。主控接受任务实测的后端、compileall、pip check 与 evaluator 证据；前端仍明确为继承基线、非 F0 实测。
- 2026-08-12：F1-01 handoff 与 4 个交付文件一致；Worker 完整后端门为 381 passed/8 skipped，主控复跑 18 个 session/contract/replay 测试通过。因中央台账提交使分支分叉，交付与 handoff 分别以 `3492a68`、`aa2afc2` 线性 cherry-pick 进入集成分支，来源交付 head 保留为 `141b1c5`。
- 2026-08-12：F1-02 handoff 与 10 个交付文件一致；Worker 完整后端门为 395 passed/9 skipped，主控复跑 SQLite/PostgreSQL 专项为 14 passed/9 live-PG skipped。交付与 handoff 以 `bd8de22`、`f94a320` 进入集成分支；live PostgreSQL 仍明确为未实测风险。

## 主控更新规则

1. 读取对应 handoff 并核对实际 branch/diff/commits。
2. 复跑或接受明确标记的质量证据；未实测项保持未实测。
3. 记录验收或阻塞结论，必要时退回 Worker 修订原 handoff。
4. 合并后更新 Controller state 和被解锁依赖；不删除历史 handoff。
5. 新任务从已验收依赖创建独立分支/线程，Worker 仍只写自己的 handoff。
