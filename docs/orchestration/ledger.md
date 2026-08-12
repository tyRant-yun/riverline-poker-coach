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
| F1-04 Projection/Outbox Recovery | `019ff446-caf8-78a2-85cd-c582310780ad` | `completed` | `merged` | `codex/f1-04-projection-outbox-recovery` | `9353fcd735adf9205877b7d8070c54c99089dc30` | `efb1a5ae83b63fd52ee28845c32c56e009362ff2` | [F1-04 handoff](handoffs/F1-04.md) | Worker: backend 457 passed/10 skipped at ddbe65c；final focused 21 passed/10 skipped；independent P1 re-review PASS | F4-01 | F1-05 PHH adapter for MVP interchange |
| F1-06 Hand Lab Compatibility | `019ff498-63cb-7bf2-aedb-969e973b6926` | `completed` | `merged` | `codex/f1-06-hand-lab-compatibility` | `e70e85e80724846ec0da968010cd6f9dcc0daa4d` | `6e2e5d55098e3d1369f78e3782006d095269b80e` | [F1-06 handoff](handoffs/F1-06.md) | Worker: focused 51 passed；backend 470 passed/10 skipped；compileall/pip check；independent MVP P0/P1 review PASS | F4-03（仍依赖 F3） | F1-05 PHH adapter |
| F1-05 PHH Adapter | `019ff4c4-26dd-7020-b60c-84f097bae0ba` | `completed` | `merged` | `codex/f1-05-phh-adapter` | `0780d2d960dc2dea87220d2f9cd92205cd048e6e` | `b3bd7dc5e13a74337408af8775e715f8dcda1197` | [F1-05 handoff](handoffs/F1-05.md) | Worker: focused 7 passed；backend 477 passed/10 skipped；compileall/pip check；极窄 P1 re-review PASS | F1-07 | F1-07 recovery/seeded soak exit gate |
| F1-07 Recovery/Soak Exit Gate | `019ff4e1-9866-7f93-837e-0dfc797034a8` | `in_progress` | `in_progress` | `codex/f1-07-recovery-soak` | `8f3501c2c5ac8b35d7a45a716e6784bcdf5e8d67` | — | — | — | — | F1 exit only: restart/rebuild/fingerprint/1,000-hand soak/rollback |
| F2-01 Fixed/Blueprint Bot Providers | `019ff4e4-9f9c-7730-b987-80d498144ebc` | `completed` | `merged` | `codex/f2-01-bot-providers` | `3803ae6` | `a7e26def5fc5c05dd7bed13fadeb1d6fa834c017` | [F2-01 handoff](handoffs/F2-01.md) | Worker: bot/runtime focused 26 passed；simulator compileall；no full backend by fast-path policy | F2-02、F2-04、F2-05 | F2-04 continuous table after F1-07 |
| F3-03 Formula/L0 Advisor | `019ff500-f1ba-7af2-9663-5c4aa1826bf6` | `in_progress` | `in_progress` | `codex/f3-03-formula-advisor` | `6d94bb4` | — | — | — | — | Pot/call cost/pot odds/SPR/legal sizes; no API/UI/equity/range |

## 下一入口

`F1-07`：只做 F1 恢复/重放/筹码守恒/1,000-hand seeded soak 与 rollback 出口门；通过后立即切入可体验的 F2 连续桌纵向切片。

## MVP 执行策略

- 主控只做规划、依赖调度、handoff 验收、ledger 单写与集成；代码审查由独立任务执行，主控只消费结构化结论。
- 以尽快交付可运行 MVP 并开始用户迭代为优先级；只把阻塞 MVP、数据正确性或恢复安全的 P0/P1 作为当前合并门，P2/P3 与抽象优化进入 backlog。
- 默认最多两个互不冲突的实现任务并行，并预留一个短审查槽；同一规则/持久化依赖链串行。任务按可体验的纵向切片合并，避免过细拆分造成重复启动和 handoff。
- Worker 普通任务只运行 focused tests；完整 backend/frontend 门每 2–3 个集成交付、阶段出口或发布前运行一次。规则、持久化、恢复高风险任务仍可明确要求一次完整门；主控不重复 Worker 已实测的门。
- 独立审查只用于规则权威、私牌/权限、持久化一致性、恢复安全和发布门；只读 base..head diff、精确契约片段和 focused tests，不默认做全仓 Standards/Spec 双轴审查。
- Worker 只读 handoff contract、ledger 的本任务/直接依赖/下一入口及 prompt 点名的契约/测试；禁止默认加载全部 master plan、ADR、历史 handoff 或全量扫描仓库。
- 模型按成本选择：文档/台账用 Luna/Terra low/medium，一般实现与普通验收用 Terra medium；Sol 仅用于已点名的规则、事务、恢复 P1 或阶段发布审查。

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
- 2026-08-12：产品负责人将执行目标调整为 MVP 尽快上线并开始迭代。主控不再亲自代码审查；F1-04 修订只将 3 个 P1 作为阻塞门，P2 若不能低成本收尾则登记 backlog。后续采用单任务、聚焦验证和成本分层模型。
- 2026-08-12：F1-04 第二轮 handoff 回传 backend 457 passed/10 skipped。独立窄审查确认 event-intent 绑定和未知 schemaVersion 拒绝已关闭，但发现 dispatcher 在耗时 dispatch 后仍以 claim 时旧 `now` 做 ack/retry，可绕过实际 lease 到期；保持未集成，仅退回该单一 P1 修复。
- 2026-08-12：F1-04 最终窄修使用存储端事务内当前时间验证 ack/retry lease，独立审查结论 PASS；final focused 21 passed/10 live-PG skipped，沿用前一修订提交的完整 backend 457 passed/10 skipped。三项交付与三项 handoff 治理提交以 `ff90f30` 至 `f389027` 进入 `codex/simulator-rebuild`。P2 nested payload 深冻结进入 post-MVP backlog；live PostgreSQL 仍未实测。
- 2026-08-12：为尽快获得可体验 MVP，F1-06 先于 F1-05 启动；任务 `019ff498-63cb-7bf2-aedb-969e973b6926` 从集成提交 `e70e85e` 创建，使用 Terra/high，仅做现有 Hand Lab/API/E2E 兼容桥，F1-05 继续后置。
- 2026-08-12：F1-06 handoff 校正后与 Git 事实一致；独立窄审查仅检查规则真相、stable/sparse seats、信息隔离、authoritative all-in 与既有 API hooks，结论 PASS。Worker 实测 focused 51 passed、backend 470 passed/10 skipped；主控未重复测试。交付及 handoff 以 `cb8f68d`、`6cb9953`、`6dcd26b` 进入 `codex/simulator-rebuild`。
- 2026-08-12：F1-05 从集成提交 `0780d2d` 派发至任务 `019ff4c4-26dd-7020-b60c-84f097bae0ba`，使用 Terra/medium 单任务实现最小 PHH exchange/round-trip；不并行启动其他任务。
- 2026-08-12：F1-05 首轮 delivery/handoff 与 Git 事实及 Worker 质量证据一致（focused 5 passed；backend 475 passed/10 skipped），但独立 MVP P0/P1 审查发现普通 PHH 导出会泄漏未公开私牌，以及 import 未核对标准 `finishing_stacks`/`winnings`、可静默吞掉不一致结算或潜在 rake。交付未集成，已仅退回这两个 P1 做测试先行修复；F1-07 保持暂停。
- 2026-08-12：控制面审计确认主要吞吐损耗来自严格单任务串行、F1-03/F1-04 三轮审查返工、每任务约 5.8 万字符固定上下文和每 15 分钟心跳重复读取，而非 WSL 本身。治理切换为最多两个独立实现槽、风险型一次审查、focused-per-task/批次全量门和增量心跳；WSL 启动损耗只通过批处理命令规避。
- 2026-08-12：F1-05 两个 P1 由原 Worker 在约 4 分钟内测试先行修复，复用原审查上下文做极窄 re-review，结论 PASS；Worker 实测 focused 7 passed、backend 477 passed/10 skipped、compileall/pip check。四项交付/handoff 提交以 `76eaed9` 至 `71c8ea0` 集成，未重复运行全仓审查或主控测试。
- 2026-08-12：F1-07 从已验收基线 `8f3501c` 派发至任务 `019ff4e1-9866-7f93-837e-0dfc797034a8`；使用 Sol/high 处理窄范围恢复与规则出口门。任务采用精确文件清单与批处理命令，不加载全部规划/ADR/handoff；F2 尚不与同一规则链并发。
- 2026-08-12：启用第二实现槽，将已由 F1 Observation/BotRuntime 解锁且不触碰 F1-07 文件所有权的 F2-01 派发至任务 `019ff4e4-9f9c-7730-b987-80d498144ebc`，使用 Terra/medium、focused-only 门；这是受控并发，不提前启动 F2 session API。
- 2026-08-12：F2-01 Git/handoff 事实核对后仅修正一次错误 thread ID，未做独立代码审查或重复全量测试；Worker focused 26 passed、simulator compileall 通过。交付以 `4eb47c5`、`6c0f057`、`83a6331` 集成，解锁 F2-02/F2-04/F2-05；F2-04 等待 F1-07 出口门后启动。
- 2026-08-12：F1-07 首轮完整出口门为 backend 480 passed/10 skipped、1,000-hand soak 24.25s；独立极窄恢复审查仅发现一个 P1：`recover()` 在 terminal `hand_completed` 缺失时可能仅凭规则状态结束而提前结算/旋转按钮。交付未集成，已退回原 Worker 只补该负向测试与修复，不重跑 soak/完整门。
- 2026-08-12：为避免 F1-07 单点修复阻塞产品体验路径，第二实现槽从已稳定 Observation/LegalAction seam 派发 F3-03 至任务 `019ff500-f1ba-7af2-9663-5c4aa1826bf6`；Terra/medium、focused-only，且不触碰 session/persistence/orchestrator。

## 主控更新规则

1. 读取对应 handoff 并核对实际 branch/diff/commits。
2. 复跑或接受明确标记的质量证据；未实测项保持未实测。
3. 记录验收或阻塞结论，必要时退回 Worker 修订原 handoff。
4. 合并后更新 Controller state 和被解锁依赖；不删除历史 handoff。
5. 新任务从已验收依赖创建独立分支/线程，Worker 仍只写自己的 handoff。
