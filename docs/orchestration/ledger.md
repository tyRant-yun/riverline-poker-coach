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
| F1-03 PokerKit GameOrchestrator | `019ff3e3-bda6-7e21-903e-d4fe0611a5a9` | `completed` | `merged` | `codex/f1-03-pokerkit-game-orchestrator` | `91fb7f08d760753259f611284318b512c5f30ed4` | `e46f4df666e2513750147862674e6d9ce64634fd` | [F1-03 handoff](handoffs/F1-03.md) | Worker: backend 433 passed/9 skipped、146 relevant passed、compileall/pip check；Controller: 146 relevant passed before and after integration | F1-04、F1-05、F1-06 | F1-04 projection/checkpoint/outbox recovery |
| F1-04 Projection/Outbox Recovery | `019ff446-caf8-78a2-85cd-c582310780ad` | `completed`（首轮） | `in_progress`（审查修订） | `codex/f1-04-projection-outbox-recovery` | `9353fcd735adf9205877b7d8070c54c99089dc30` | `34828ca13056ea7defc67d7db4a1381130fc291b`（待续） | [F1-04 handoff](handoffs/F1-04.md)（待修订） | Worker: backend 447 passed/10 skipped；Controller: focused 55 passed/10 live-PG skipped；双轴审查发现 3 P1/1 P2 | — | 修复 event-intent 绑定、claim token、schemaVersion 读取与深度不可变 payload |

## 下一入口

`F1-04`：在 durable event stream 上实现 projection cursor/checkpoint、可丢弃 snapshot cache 与 transactional outbox，证明重复消费幂等、失败恢复以及投影可重建。F1-05/F1-06 已解锁，但为控制额度与集成复杂度，等待 F1-04 稳定后再启动。

## 主控验收记录

- 2026-08-12：F0 交付提交 `b0f13e3` 与治理提交 `53d99c3` 构成从基线 `71acce7` 开始的严格线性提交链；handoff 的 31 个交付文件与 Git diff 一致。
- 2026-08-12：F0 已快进进入 `codex/simulator-rebuild`。主控接受任务实测的后端、compileall、pip check 与 evaluator 证据；前端仍明确为继承基线、非 F0 实测。
- 2026-08-12：F1-01 handoff 与 4 个交付文件一致；Worker 完整后端门为 381 passed/8 skipped，主控复跑 18 个 session/contract/replay 测试通过。因中央台账提交使分支分叉，交付与 handoff 分别以 `3492a68`、`aa2afc2` 线性 cherry-pick 进入集成分支，来源交付 head 保留为 `141b1c5`。
- 2026-08-12：F1-02 handoff 与 10 个交付文件一致；Worker 完整后端门为 395 passed/9 skipped，主控复跑 SQLite/PostgreSQL 专项为 14 passed/9 live-PG skipped。交付与 handoff 以 `bd8de22`、`f94a320` 进入集成分支；live PostgreSQL 仍明确为未实测风险。
- 2026-08-12：F1-03 首轮交付的 Git/handoff/测试证据一致，但合并前双轴审查发现 bust-out 后无法继续、seed 与持久化牌面未交叉验证、sparse active seat 与 F1-01 语义冲突等硬问题；未集成，已退回原 Worker 修订。
- 2026-08-12：F1-03 修订已修复 bust-out、seed provenance、open conflict 和版本化 rules contract，确认剩余阻塞是 HandStarted 缺少参与者集合。主控授权向 V1 增加带旧流默认语义的 `activeSeatIds`，稳定 table seat ID 仅在 PokerKit adapter 内映射为 dense player index，并要求 ADR-0009 与 glossary 记录。
- 2026-08-12：F1-03 最终 handoff、三项交付提交及 20 个 changed files 已核对；`activeSeatIds` 保持旧 JSON 默认语义，sparse Hand Participant 的 stable seat ID 覆盖 adapter、replay、observation、stats、settlement 与 bust-out successor。主控在 Worker 分支及集成分支各复跑 146 项相关测试通过；完整 backend 的 Worker 实测为 433 passed/9 skipped。六项线性提交以 `acc1e88` 至 `f8b469d` 进入 `codex/simulator-rebuild`；live PostgreSQL 与 crash-safe 跨手 session repository 仍未声称完成。
- 2026-08-12：F1-04 从已验收集成基线 `9353fcd` 派发至独立任务 `019ff446-caf8-78a2-85cd-c582310780ad`，使用 Sol/high 处理事务原子性、并发 claim 与失败恢复；F1-05/F1-06 暂不并行，以控制额度和集成风险。
- 2026-08-12：F1-04 首轮 Git/handoff/16 个 changed files 与质量证据一致，主控聚焦门 55 passed/10 live-PG skipped；双轴审查发现 outbox intent 未强制绑定本批 event、过期/ABA claim 可 ack/retry、未知持久化 schemaVersion 被静默按 V1 读取，以及 public payload 仅浅冻结。交付未集成，已退回原 Worker 以测试先行做兼容范围内修订；后续任务继续暂停。

## 主控更新规则

1. 读取对应 handoff 并核对实际 branch/diff/commits。
2. 复跑或接受明确标记的质量证据；未实测项保持未实测。
3. 记录验收或阻塞结论，必要时退回 Worker 修订原 handoff。
4. 合并后更新 Controller state 和被解锁依赖；不删除历史 handoff。
5. 新任务从已验收依赖创建独立分支/线程，Worker 仍只写自己的 handoff。
