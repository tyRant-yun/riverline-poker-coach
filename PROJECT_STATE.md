# PROJECT_STATE

> Riverline 可观测德州扑克认知模拟器状态快照
> 更新日期：2026-08-12
> 当前阶段：F0 Simulator Foundation 完成，下一入口为 F1 Authoritative Session

## 1. 产品与范围

Riverline 的产品定位已从“孤立牌局分析页”扩展为**可观测的德州扑克认知模拟器**：用户可连续打牌；系统用不可变事件记录事实，重建牌局、统计与复盘；Bot、Advisor、Range Belief 和学习闭环都必须展示来源与近似边界。

第一正式产品模式固定为：

- 6-max NLHE cash；
- 100BB 初始筹码；
- 无 ante、无 rake；
- 底层 seat/event/provider contract 保留 2–8 人通用性，但不承诺其他桌型的产品或策略覆盖。

现有 Hand Lab、场景分析、多人 PokerKit replay/equity、Range Belief、异步 solver bridge、Hand Review、教学与前端 E2E hooks 在迁移期间继续受保护；F0 未重写前端或删除这些能力。

## 2. F0 已冻结决策

| 主题 | 决策 | 权威记录 |
|---|---|---|
| 目标拓扑 | 模块化单体 + 明确端口/适配器；规则、事件、Bot、Advisor、Belief、复盘/学习和投影分离 | ADR-0005 |
| 规则与交换 | PokerKit 是唯一规则真相候选；PHH 只作为导入/导出交换格式 | ADR-0005/0006 |
| 事件与读模型 | `HandEventV1` append-only；状态、统计与复盘均为可丢弃、可重建 projection | ADR-0006 |
| Bot/Agent/Advisor | Bot 只消费权限安全 Observation；runtime 负责超时、异常、非法动作与固定降级；Advisor 不执行动作 | ADR-0007 |
| Range Belief | 有来源的可解释近似，不伪装成对手真实底牌或精确联合真值 | ADR-0005/0007 |
| 许可 | 仓库采用 AGPL-3.0-or-later；非商用不豁免 GPL/AGPL 义务 | ADR-0008、`LICENSE` |
| 第三方治理 | 依赖与 artifact 必须登记来源、版本、许可证、修改、获取方式和 fingerprint | `THIRD_PARTY_NOTICES.md` |
| Solver | AGPL solver 不进入主依赖；进程隔离是运行架构，不是自动许可结论 | ADR-0008 |

OpenSpiel、RLCard 和 PettingZoo 仅用于学习 Agent/训练 contract 与离线实验，不进入在线规则内核。

## 3. F0 代码基线

新增 `backend/poker_coach/simulator/`，冻结以下 V1 公共 contract：

- `HandEventV1`：`handId`、连续 `sequence`、`schemaVersion`、时间戳、source 和 provenance；事件 payload 为带判别字段的版本化 union；
- `ObservationV1`：只包含行动 seat 自己的底牌和公共事实，禁止其他玩家底牌与内部 belief；
- `LegalActionV1`：只使用 fold/check/call/bet/raise；金额语义为 none/cost/by/to；all-in 是 bet/raise 的最大端点；
- `BotDecisionV1`：行动、provider/version、runtime 实测 latency、confidence/metadata，以及完整错误/回退 attempt provenance。

序列化策略：领域内部使用 snake_case，JSON 边界固定 camelCase；`schemaVersion=1`；读取器拒绝未知字段与未知大版本，新增兼容字段只能有默认值，破坏性变化必须发布 V2 并在边界迁移。UI 展示结构不是领域 contract。

F0 spike 实现：

- `replay.py`：验证顺序/重复/hand 一致性并通过现有 PokerKit adapter 确定性重放，重建状态、结算、VPIP/PFR/3-bet 与 action count；
- `observation.py`：从事件前缀构建权限安全 observation，并投影 PokerKit 合法行动；
- `bot_runtime.py`：async provider contract、runtime timeout/exception/invalid-action 防线与确定性 fixed fallback；
- `evaluator_benchmark.py`：固定 seed 的 5/6/7-card oracle differential、pairwise candidate differential、p50/p95 基准和采纳门。

## 4. F0 验证证据

验证环境：WSL Ubuntu-24.04 作为命令环境，宿主 CPython 3.13.14 作为仓库要求的 Python runtime；未联网、未安装候选依赖。

| 门 | 2026-08-12 实测结果 |
|---|---|
| 完整 backend pytest | **371 passed, 8 skipped**（379 collected；skip 为既有 live-PG 条件测试） |
| F0 新增 contract/spike tests | **17 passed**，包含序列化、信息隔离、乱序/重复、确定性 replay、Bot 四类路径、evaluator oracle/candidate gate |
| `compileall` | OK |
| `pip check` | `No broken requirements found.` |
| evaluator oracle differential | 固定 seed `20260812`，5/6/7-card 共 **3,000** 样本，**0 mismatch** |
| evaluator benchmark | 15,000 次；参考运行 p50 **6,404 ns/eval**、p95 **6,544 ns/eval**、约 **155k eval/s** |
| PH Evaluator candidate | 本地未安装，未联网引入；采纳门明确为 **未通过**（准确性/打包/许可/运行时证据不足） |

Differential 在实现过程中发现并修复当前 evaluator 的 double-trips full-house 漏判（例如 `JJJKKKx` 应选 full house）。修复后专项回归和完整 pytest 均通过。

F0 未触及 `frontend/`，因此未重复执行 Vitest、tsc、build 或 Playwright。任务输入确认的继承集成基线为：Vitest **30 files / 157 tests**、tsc/build 通过、Playwright **8 E2E + 3 capability audit** 通过；这些数字不是本分支的新实测结果。

## 5. 迁移期间不可破坏的能力

- 后端仍是规则唯一权威；前端不得重算或伪造规则/solver 数值；
- `ScenarioSpec` 与 Hand Lab 仍是单手实验/复盘边界，不能升级为持续 session 的事件真相；
- 多人 `tableSize 2..8`、连续 seat ID、边池/分池、按 seat range/equity 与 temporal dead-card 语义继续有效；
- Range Belief 底层保持具体 combo 的 reach/probability，169 matrix 只是 view；无 policy、未来信息、off-tree 和 provenance mismatch 必须诚实降级；
- Solver artifact 必须绑定场景/节点 fingerprint 和精确 policy sequence；不能把 HU 翻后结果包装成 6-max 全节点真值；
- 已通过的交互文案、按钮名、aria-label、class 和 action amount 语义属于 E2E 兼容面。具体清单与历史能力证据保留在 `docs/product-remediation-execution.md`、`docs/product-full-chain-audit.md` 和既有测试中。

## 6. 当前明确风险

- F0 event store 是内存/fixture 级 contract spike；尚无 durable session aggregate、并发追加控制、幂等 command 或数据库迁移；
- `ObservationV1` 已证明不泄漏，但还没有覆盖完整 session 调度器内所有 reveal/showdown 权限；
- Bot runtime 已证明 provider 边界与降级，不含真正的进程/RPC 隔离、资源配额或长期运行 soak；
- PH Evaluator 未安装，不能声称候选准确、可打包或更快；若 F5 重新评估，必须在隔离 extras 中固定版本并核对分发许可证元数据；
- 当前 evaluator oracle spike 不是穷举证明；已有 3,000 个确定性随机样本与回归用例，F5 仍需更大 differential corpus；
- 现有 Range Belief/solver 覆盖仍是显式窄节点，不等于 6-max 完整策略；
- 本次未重新验证前端继承基线；未来任何 frontend 变更必须重新跑全部前端门。

## 7. 下一阶段入口：F1 Authoritative Session

F1 只能建立在 F0 V1 contract 与 ADR 上，建议按以下依赖顺序推进：

1. `F1-01`：定义 `GameSession`/`HandId`/`SessionId` 所有权、6-max 100BB table config 与 2–8 topology 校验；
2. `F1-02`：实现持久化 `hand_events` append port 与 PostgreSQL/SQLite adapters，加入 `(hand_id, sequence)`/`event_id` 唯一约束和 expected-sequence 乐观追加；依赖 F1-01；
3. `F1-03`：实现 command → PokerKit-backed `GameOrchestrator` reducer → atomic event append，保证筹码守恒和固定 seed fingerprint；依赖 F1-01/F1-02；
4. `F1-04`：实现 projection cursor/checkpoint、snapshot cache 与 transactional outbox，证明重复消费幂等和失败恢复；依赖 F1-02，可与 F1-03 后半并行；
5. `F1-05`：PHH import/export adapter 与 round-trip golden fixtures；依赖 F1-03；
6. `F1-06`：建立现有 `ScenarioSpec`/Hand Lab 兼容 bridge，保留当前 API/E2E hooks；依赖 F1-03；
7. `F1-07`：故障恢复、重放 fingerprint、筹码守恒、1,000-hand seeded soak 和 rollback 演练；依赖 F1-02–F1-06。

F1 出口门：固定 seed 的 6-max session 可跨进程恢复；事件连续且不可重复；每手筹码守恒、结算一致；所有投影丢弃后可重建；现有 Hand Lab/E2E 兼容面无回退。后续 F2–F6 的任务、依赖和验收门见 `docs/simulator-refactor-master-plan.md`。

## 8. 常用验证命令

```bash
# 在 WSL Ubuntu-24.04 中，从仓库根执行；需使用 Python 3.13
unset PYTHONPATH PYTHONHOME
py -3.13 -m pytest -q
py -3.13 -m compileall -q backend/poker_coach backend/tests
py -3.13 -m pip check

cd backend
py -3.13 -m poker_coach.simulator.evaluator_benchmark \
  --samples-per-size 1000 --rounds 5 --seed 20260812
```

本地服务、Range Belief、Solver 与 Hand Review 的历史运行细节仍见 `docs/使用说明.md`；F0 不改变这些入口。
