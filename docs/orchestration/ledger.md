# Riverline orchestration ledger

状态：主控任务单写

本文件是跨独立 Codex 任务的中央执行台账。Worker 读取它判断入口与依赖，但不直接修改中央状态行；Worker 只新增 `docs/orchestration/handoffs/<task-id>.md`。主控在复核 handoff、Git 事实和质量证据，并完成验收/合并后更新本台账，从而避免并行任务争用同一文件。

本文件中的 F0 行是治理机制建立时按产品负责人指令写入的 bootstrap 记录；合入中央分支后由主控继续维护。

## 状态语义

| Controller state | 含义 |
|---|---|
| `pending_acceptance` | Worker 已回传，主控尚未验收/合并 |
| `accepted` | 主控已复核并接受交付事实 |
| `merged` | 已进入指定集成目标，依赖可按台账解锁 |
| `blocked` | 主控确认存在未解决的外部阻塞或产品决定 |

Worker handoff 的 `completed` 不自动等于 ledger 的 `accepted` 或 `merged`。

## 执行台账

| Task | Worker status | Controller state | Branch | Base | Delivery head | Handoff | Quality evidence | Dependencies unlocked | Recommended next |
|---|---|---|---|---|---|---|---|---|---|
| F0 Simulator Foundation | `completed` | `merged` | `codex/f0-simulator-foundation` | `71acce7` | `b0f13e34c3947dd790ada996554bc7216774411e` | [F0 handoff](handoffs/F0.md) | Backend 371 passed/8 skipped；compileall/pip check；17 F0 tests；3,000 evaluator samples/0 mismatch；frontend not measured | F1-01 | F1-01 Authoritative Session ownership/config |

## 下一入口

`F1-01`：定义 `GameSession`、`HandId`、`SessionId` 所有权，冻结 6-max 100BB no-ante/no-rake table configuration，并验证底层 2–8 seat topology。F0 contracts/ADRs/handoff 已由主控验收并快进至 `codex/simulator-rebuild@53d99c3`；它不授权提前启动 F1-02 或其他并行阶段。

## 主控验收记录

- 2026-08-12：F0 交付提交 `b0f13e3` 与治理提交 `53d99c3` 构成从基线 `71acce7` 开始的严格线性提交链；handoff 的 31 个交付文件与 Git diff 一致。
- 2026-08-12：F0 已快进进入 `codex/simulator-rebuild`。主控接受任务实测的后端、compileall、pip check 与 evaluator 证据；前端仍明确为继承基线、非 F0 实测。

## 主控更新规则

1. 读取对应 handoff 并核对实际 branch/diff/commits。
2. 复跑或接受明确标记的质量证据；未实测项保持未实测。
3. 记录验收或阻塞结论，必要时退回 Worker 修订原 handoff。
4. 合并后更新 Controller state 和被解锁依赖；不删除历史 handoff。
5. 新任务从已验收依赖创建独立分支/线程，Worker 仍只写自己的 handoff。
