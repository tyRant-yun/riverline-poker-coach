# ADR-0004：Solver 技术评估与策略数据接入边界

状态：已接受（技术评估完成；求解服务与数据导入待后续阶段；许可路径已确认：隔离服务路径，postflop-solver sidecar）

日期：2026-08-10

## 决策 1：当前不引入求解引擎，先建立 solver 数据导入规范

### 背景

阶段 7 的策略库目前只有人工策划条目（`AnalysisLevel.CURATED`），全部假设明确标注"无 solver 频率"；数据模型已预留 `SOLVER_BACKED` 来源等级和 `can_quote_frequencies` 频率门控（ADR-0003），但没有真实求解数据或求解服务。目标文档要求先对 RoboPoker、rs-poker 与自研受控 postflop Solver 做技术评估。

### 选择

以只读方式完成对五个开源候选的评估（许可证、活跃度、算法族、输入/输出契约），结论如下：

| 候选 | 许可证 | 语言 | 活跃度（2026-08 实测） | 算法族 | 结论 |
|---|---|---|---|---|---|
| bupticybee/TexasSolver | AGPL-3.0 | C++ | 2502★，2026-07 活跃 | CFR+，按需求解 | 只读研究；禁止引入源码 |
| b-inary/postflop-solver | AGPL-3.0 | Rust | 362★，2024-07 停更（作者转商业） | CFR+（同算法族） | 只读研究；格式参考 |
| bupticybee/TexasHoldemSolverJava | MIT | Java | 911★，已停更（被 C++ 版取代） | CFR+，结果与 PioSOLVER 对齐 | **首个引擎适配候选**（许可干净） |
| elliottneilclark/rs-poker | Apache-2.0 | Rust | 173★，活跃 | 手牌评估 50M+/s + CFR 求解器 | 高性能备选 |
| krukah/robopoker | MIT | Rust | 214★，活跃 | Pluribus 式 MCTS + 引擎/API 分层 | 仅训练桌 bot 方向；不作频率来源 |

注：目标文档中的"RoboPoker"（bupticybee/RoboPoker）已不存在（GitHub 404）；上表以 krukah/robopoker（MIT，功能与其描述吻合）为替代评估对象。

关键事实（来自源码与文档的只读研究）：

- TexasSolver 输入契约：`set_pot` / `set_effective_stack` / `set_board` / `set_range_ip|oop`（记法 `AA,AK:0.75,AQs`）/ `set_bet_sizes <pos>,<street>,<bet|raise|allin>,<pct>` / `set_allin_threshold` / `build_tree` / `start_solve` / `dump_result <file>.json`。
- 输出契约：动作树嵌套 JSON，每个动作节点含 `actions`、`player`、`childrens` 与按手牌的动作频率/EV 策略表（`strategy`）；结果与 PioSOLVER 对齐。
- 求解场景（范围、有效筹码、下注树、牌面）与现有 `ScenarioSpec`（hero/villain range、起始筹码、`allowedBetSizes`、board、action history）存在自然映射。

### 替代方案

- 直接集成 TexasSolver/postflop-solver：违反工程基线"不引入 AGPL 源码"约束；
- 直接自研 postflop Solver：工作量大，且 CFR+ 的正确性验证成本高，应先以可复用的 MIT/Apache 引擎验证管线；
- 完全跳过 Solver：教学层只能保持 principle-only，无法提供精确频率教学。

### 后果

- 立即生效：`docs/solver-import-spec.md` 定义 solver 输出导入规范；任何有来源、有许可证、通过校验的求解数据可以 `solver_backed` 来源等级进入策略库，教学层自动获得频率引用许可（仅 `exact`/获批 `compatible` 匹配，ADR-0003）。
- 未来求解服务：以 `TexasHoldemSolverJava`（MIT、CFR+ 同族、命令行可调用、结果与 PioSOLVER 对齐）为首个引擎适配候选做 spike；rs-poker（Apache-2.0）为高性能备选；robopoker 仅评估用于训练桌 bot，不产生策略频率来源。
- **许可路径（用户已放宽：非商用、无收益）**：AGPL 的传染义务不以商用为前提，故 AGPL 引擎（TexasSolver/postflop-solver）只有两条引入路径——① 隔离 API 服务（AGPL 引擎独立进程，主项目保持宽松许可，推荐）；② 项目整体采用 AGPL-3.0。路径未选定前维持只读研究；solver 输出数据（JSON）不属于代码，任何路径下都可自由导入。
- AGPL 项目只产出"数据契约理解"；导入适配器与校验器为独立设计，不复制 AGPL 源码。

## 决策 2：SolveJob 作为独立异步服务（设计约束，暂不实现）

### 背景

目标文档要求 Solver 独立为异步服务：`ScenarioSpec → SolveJob → StrategyArtifact → 策略库 → Agent`，且可取消、有资源配额、结果缓存、完整记录版本、不阻塞普通 API。

### 选择

复用现有资产设计（不新增代码）：

- 队列与取消：复用 `poker_coach.jobs` 的 Redis 队列与协作式取消标志（API 容器与 worker 容器已由 docker-compose 拆分）；
- 资源配额：求解参数上限（迭代次数、树规模、线程数）写入 SolveJob 请求并强制校验；worker 单任务串行执行；
- 结果缓存：以 `scenarioHash + 求解器版本 + 求解参数哈希` 为键（现有 `scenarios.scenario_hash` 与 `strategy_artifacts` 元数据可扩展）；
- 版本记录：`StrategyArtifact` 已含 artifact 版本、求解器版本、范围、下注树、来源、许可证、可信等级字段；
- 不阻塞 API：求解由独立 worker 消费，API 只提交/轮询（现有 `/v1/analysis/jobs` 模式）。

### 后果

求解服务上线时无需改动规则核心与分析核心；只需新增求解器适配器（MIT/Apache 候选）与 SolveJob 管理，接入现有 Redis worker 与策略库注册路径。首个里程碑为"spike：MIT 候选小规模求解 → 按导入规范入库 → 验证 exact 匹配与频率引用链路"。
