# Riverline 重构：开源扑克项目复用调研

> 调研日期：2026-08-12
> 产品基线：`product-vision-instrumented-poker-simulator.md`
> 来源范围：GitHub 原仓库的 README、代码与 LICENSE，项目官方文档，以及论文项目页。本文不是法律意见。

## 结论先行

Riverline 不应寻找一个“现成扑克项目”整体替换当前代码。更合理的做法是保留现有 PokerKit 规则内核，在它之外建立服务器权威的连续牌局、不可变事件、Bot/Agent 端口、分层 Advisor、座位级 Belief 和训练调度。开源项目的最佳用途是分别补齐标准、算法试验和性能部件，而不是引入第二套牌局真相。

建议形成四档处置：

1. **直接采用或继续采用**：PokerKit、PHH 标准、py-fsrs。
2. **经基准验证后可采用**：PH Evaluator，作为 equity/evaluator 加速器，而不是规则引擎。
3. **只学习接口与算法**：PettingZoo、OpenSpiel、RLCard、pyeventsourcing/eventsourcing、PyPokerEngine、MIT Pokerbots engine、HandMatrix、WASM Postflop。
4. **不进入主产品依赖**：PokerRL、`poker_ai`、Treys/Deuces、OMPEval、TexasSolver、`postflop-solver`、openCFR，以及来源和许可证不清的公开策略表。

最重要的工程边界是：

- PokerKit 是唯一规则真相；其他环境只能通过 adapter 消费同一 observation/action schema。
- 内部事件模型服务于重放、审计、统计和投影；PHH 只做导入导出交换格式。
- Solver 输出必须是有版本、树配置、范围输入和精度信息的 artifact，不能在线同步阻塞每个 Hero 决策。
- “代码许可证宽松”不等于“仓库内策略数据有可靠来源且可复用”。本次没有找到同时具备完整 provenance、明确数据许可和 6-max 多节点覆盖的高质量公开策略数据集。

## 推荐目标架构与开源映射

```text
Authoritative GameSession
  └─ PokerKit rules adapter                         [继续采用]
       ├─ immutable hand_events + version
       ├─ deterministic replay / projections
       └─ HeroView / BotObservation（隐藏信息投影）

BotOrchestrator
  └─ BotDecisionProvider
       ├─ local blueprint / heuristic
       ├─ optional model
       ├─ external subprocess / RPC agent
       └─ timeout → legalize → fallback
          接口语义参考 PettingZoo / PyPokerEngine / MIT Pokerbots

AdvisorService
  ├─ exact Formula Engine
  ├─ equity service（PokerKit；必要时 PH Evaluator 加速）
  ├─ curated/cached policy
  └─ offline solver artifacts（OpenSpiel 研究；AGPL solver 谨慎隔离）

Learning Pipeline
  ├─ event projections → stats / review / concept mastery
  ├─ outbox → asynchronous review jobs
  ├─ PHH import/export
  └─ py-fsrs → spaced review scheduling
```

这里的“adapter/sidecar 隔离”首先是架构和故障隔离手段，不自动解决许可证兼容问题。

## 一、规则、状态与回放

### 1. PokerKit：继续作为唯一规则内核

- 项目：[uoftcprg/pokerkit](https://github.com/uoftcprg/pokerkit)
- 许可证：[MIT](https://github.com/uoftcprg/pokerkit/blob/main/LICENSE)
- 语言：Python
- 状态：活跃；GitHub 显示 52 个 release，最新 `v0.7.4` 发布于 2026-05-22。项目声明覆盖多人、多变体、细粒度状态操作、hand evaluation、测试与严格类型检查；其论文说明了设计目标和验证范围：[PokerKit paper](https://arxiv.org/abs/2308.07327)。
- Riverline 复用：继续承载合法行动、发牌、下注轮转、全下、边池、摊牌、筹码守恒；新增 `GameSession` 和 `GameOrchestrator` 只编排连续多手，不复制规则。
- 风险：PokerKit 提供的是细粒度 state machine，不等于完整的产品 session、权限投影或 durable event store。版本升级必须用 Riverline 的 golden hands 和随机长局仿真回归。

**判断：直接采用。** 这是当前重构最稳的锚点，不要再引入 RLCard、PyPokerEngine 等第二规则内核。

### 2. PHH：作为手牌交换格式，不作为内部事件模型

- 项目：[uoftcprg/phh-std](https://github.com/uoftcprg/phh-std)
- 许可证：[MIT](https://github.com/uoftcprg/phh-std/blob/main/LICENSE)
- 语言/形态：文本规范与 Python/PokerKit 工具链
- 状态：较新且与 PokerKit 同一研究组维护；规范覆盖初始参数、动作和玩家、场地、时控等上下文。官方说明和示例见 [PHH README](https://github.com/uoftcprg/phh-std#poker-hand-history-file-format-specification)，公开样本见 [phh-dataset](https://github.com/uoftcprg/phh-dataset)。
- Riverline 复用：为已完成手牌提供稳定的导入、导出和 fixture 格式；让 Hand Lab、复盘、外部数据集和回归测试共享一种可读表示。
- 风险：PHH 是一手牌的可交换记录，不表达 Riverline 特有的 `belief_updated`、advisor provenance、提示揭示层级、concept mastery 等内部事件；不能强迫内部实时事件完全等同于 PHH 字段。

**判断：直接采用为边界格式。** 内部使用版本化 append-only events，结束时投影成 PHH。

### 3. 回放设计：采用 reducer + snapshot，而不是存整页 JSON

建议每个事件包含：`event_id`、`session_id`、`hand_id`、`sequence`、`schema_version`、`event_type`、`actor_seat`、`public_payload`、受控的 private payload 引用、`occurred_at`、`causation_id`、`correlation_id`、`engine_version` 和 deterministic seed。重放器只从合法初态顺序应用事件；关键街或每 N 个事件可保存 snapshot，但 event log 仍是事实来源。

PHH 提供外部手牌表示，PokerKit 执行规则；这两个职责不要合并。

## 二、Bot/Agent 与训练环境

### 4. PettingZoo：学习 AEC 接口语义，不引入它运行产品牌局

- 项目：[Farama-Foundation/PettingZoo](https://github.com/Farama-Foundation/PettingZoo)
- 许可证：[MIT](https://github.com/Farama-Foundation/PettingZoo/blob/master/LICENSE)
- 语言：Python
- 状态：活跃；`1.26.1` 于 2026-04-27 发布。官方将环境建模为 Agent Environment Cycle（AEC），并对 environment versioning 有明确约定：[README](https://github.com/Farama-Foundation/PettingZoo#api)。
- Riverline 可学习：`agent_selection`、每个 agent 的 observation、legal/action mask、termination/truncation、seed 和环境版本；很适合塑造 `BotDecisionProvider` 契约以及离线批量自博弈 wrapper。
- 风险：内置 Texas Hold'em 环境来自 RLCard，动作空间为训练友好的抽象，不等于 Riverline 的完整 NLHE 尺度、桌规和产品事件。Windows 也不是官方支持平台。

**判断：只学习接口；以后可做 `RiverlinePettingZooEnv` adapter。**

### 5. RLCard：可做算法沙盒，不做生产规则或策略来源

- 项目：[datamllab/rlcard](https://github.com/datamllab/rlcard)
- 许可证：[MIT](https://github.com/datamllab/rlcard/blob/master/LICENSE)
- 语言：Python
- 状态：成熟但更新趋缓；PyPI 稳定版 `1.2.0` 发布于 2023-04-19，master 的最近实质变动集中在 2024。官方列出 Limit Hold'em 和抽象后的 No-limit Hold'em 环境、agent、trajectory 和 CFR 示例：[README](https://github.com/datamllab/rlcard#available-environments)。
- Riverline 可学习：统一 `Agent.step/eval_step`、trajectory、payoff、seed、批量评估，以及 Leduc/Limit 上的小规模算法回归。
- 风险：NLHE action space 明确做了抽象；环境状态、筹码与动作规则不能替代 PokerKit。模型 zoo 也不提供可直接声称为 6-max 现金桌 GTO 的策略。

**判断：只用于离线研究 harness。** 若接入，必须通过 Riverline observation adapter，不复用其 engine state。

### 6. OpenSpiel：CFR 研究基线与可解释小博弈实验室

- 项目：[google-deepmind/open_spiel](https://github.com/google-deepmind/open_spiel)
- 许可证：[Apache-2.0](https://github.com/google-deepmind/open_spiel/blob/master/LICENSE)
- 语言：C++、Python
- 状态：高度活跃；`v2.0.1` 发布于 2026-07-17。项目覆盖 n-player、零和/一般和、完美/不完美信息博弈，算法包括 CFR/CFR+、Deep CFR、NFSP 等。其游戏列表将 Hold'em 标为 2–10 人并通过 ACPC 实现：[games.md](https://github.com/google-deepmind/open_spiel/blob/master/docs/games.md)；论文为 [OpenSpiel framework](https://arxiv.org/abs/1908.09453)。
- Riverline 可学习：information state、chance nodes、policy/evaluator 分离、exploitability/best response 指标、Kuhn/Leduc 的算法正确性测试。
- 风险：通用博弈框架和 ACPC poker 并不会自动解决真实 6-max NLHE 的 action/card abstraction、实时子博弈求解与产品延迟；C++ 构建和 Python binding 会增加 Windows 部署复杂度。

**判断：建立独立 research package，暂不进入实时服务依赖。** 用小博弈验证 CFR、belief 和 policy artifact schema 很有价值。

### 7. PyPokerEngine：只学习 callback/emulator 体验

- 项目：[ishikota/PyPokerEngine](https://github.com/ishikota/PyPokerEngine)
- 许可证：[MIT](https://github.com/ishikota/PyPokerEngine/blob/master/LICENSE)
- 语言：Python
- 状态：陈旧；README 仍以 Python 2.7/3.5 和旧发行方式为主，虽有后续零星提交，不适合作为新的核心依赖。它提供 `declare_action`、回合/街/动作 callback 和 emulator：[README](https://github.com/ishikota/PyPokerEngine#ai-algorithm-api)。
- Riverline 可学习：Bot 生命周期 callback、合法行动输入、离线 emulator、比赛配置。
- 风险：规则真相双轨、旧 API/工具链、状态结构弱类型。

**判断：参考接口，不复制架构。**

### 8. MIT Pokerbots engine：子进程隔离值得学，但代码不可复制

- 项目：[mitpokerbots/engine](https://github.com/mitpokerbots/engine)
- 许可证：**仓库根目录没有 LICENSE，也没有在 README 明确授予开源许可**。
- 语言：Python、Java、C++ skeleton
- 状态：70 commits、无 release；README 将其描述为 vanilla Hold'em reference engine，并强调更安全地管理 bot subprocesses。
- Riverline 可学习：stdin/stdout 或 RPC 的 agent protocol、进程超时、资源限制、语言无关 skeleton、崩溃降级。
- 风险：“MIT Pokerbots”中的 MIT 是机构名称，不代表 MIT License。GitHub 官方也说明，没有许可证时默认版权法生效，通常不能复制、修改或再分发代码：[GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository#choosing-the-right-license)。

**判断：只阅读设计思想，Riverline 独立实现协议，禁止复制代码。**

### 9. `poker_ai` 与 PokerRL：论文工程参考，不作为依赖

| 项目 | 许可证 / 语言 | 维护状态 | 有价值部分 | 不采用原因 |
|---|---|---|---|---|
| [fedden/poker_ai](https://github.com/fedden/poker_ai) | GPL；Python | 2024-07-16 被作者 archive | Pluribus/MCCFR、可遍历 state、terminal/UI demo | copyleft、已归档、short-deck/研究代码和大量预计算流程；不适合生产基线 |
| [EricSteinberger/PokerRL](https://github.com/EricSteinberger/PokerRL) | MIT；Python/C++ | 老化；README 仍要求 Python 3.6、PyTorch 0.4.1 | worker、tournament、interactive game、BR/LBR/RL-BR 评估 | 依赖陈旧、部分算法只面向 HU、训练框架过重 |

**判断：只吸收“训练、评估、部署策略分开”的观念。**

## 三、Equity 与 Hand Evaluator

### 10. PH Evaluator：唯一值得做正式加速 spike 的候选

- 项目：[HenryRLee/PokerHandEvaluator](https://github.com/HenryRLee/PokerHandEvaluator)
- 许可证：[Apache-2.0](https://github.com/HenryRLee/PokerHandEvaluator/blob/develop/LICENSE)
- 语言：C/C++、Python
- 状态：持续维护；仓库包含 266 commits、CI、测试和 Python 包 `phevaluator`。README 声明用 perfect hash 支持 5–7 张牌与 Omaha，并公开 benchmark 和内存数据：[README](https://github.com/HenryRLee/PokerHandEvaluator#overview)。
- Riverline 复用：加速 L1 Monte Carlo、range-vs-range equity 和大批量离线标注；先放在 `EquityBackend` 端口后面，与 PokerKit evaluator 做差分测试。
- 风险：要验证 Windows wheel/编译、card encoding 转换、tie/side-pot 语义以及真实 workload 性能。它只评牌，不解决范围采样、行动策略或规则。

**判断：做 1–2 天 benchmark spike；达标后作为可选 backend。** 不要在重构第一步就替换 PokerKit evaluator。

### 11. Treys/Deuces 与 OMPEval：不推荐进入新依赖

| 项目 | 许可证 / 语言 | 维护/活跃度 | 能力 | 结论与风险 |
|---|---|---|---|---|
| [ihendley/treys](https://github.com/ihendley/treys) | MIT；Python | 47 commits、无 release，源自 Deuces | 轻量 5–7 card evaluator | 易读但组合枚举 7-card，性能和维护都不优于现有/PH Evaluator；只作算法参考 |
| [worldveil/deuces](https://github.com/worldveil/deuces) | MIT；Python | 21 commits，文档仍含 Python 2.7 测试 | 位运算与 lookup evaluator | 已被 Treys 继承，陈旧；不采用 |
| [zekyll/OMPEval](https://github.com/zekyll/OMPEval) | ISC；C++ | 老项目、100 commits、无 release | 最多 6 人 range equity、枚举/Monte Carlo、回调 | README 明示 Windows 没有 build files，示例工具链为 MSVC2013/GCC5；集成和维护成本高于 PH Evaluator |

## 四、CFR 与 Solver

### 12. `postflop-solver`：技术上最值得研究，许可证与维护风险最高

- 项目：[b-inary/postflop-solver](https://github.com/b-inary/postflop-solver)
- 许可证：[AGPL-3.0-or-later](https://github.com/b-inary/postflop-solver/blob/main/LICENSE)
- 语言：Rust
- 状态：README 明示作者自 2023-10 起暂停开源开发，且 breaking changes 可能不提升版本号：[README](https://github.com/b-inary/postflop-solver#postflop-solver)。
- 能力：Discounted CFR、多线程、SIMD、chance isomorphism、16-bit compression、树序列化；最多考虑四名已弃牌玩家的 bunching，但实际求解仍是 HU postflop。
- Riverline 可学习：solver job schema、树 fingerprint、DCFR、压缩、isomorphism、缓存 artifact，以及策略/EV/精度展示。其 [WASM Postflop](https://github.com/b-inary/wasm-postflop) 也可作为 range/tree UI 的设计参考。
- 风险：AGPL、停止维护、Rust `unsafe` 热点、巨大内存与秒/分钟级求解；不满足每个 Hero 决策 100–300ms 首层结果。

**判断：不直接链接主服务。** 可作为本地研究工具或独立、明确标识的实验 solver；若计划对外提供 Web 服务或分发组合程序，先决定 Riverline 的开源策略并做专业许可审查。

### 13. TexasSolver：不建议采用

- 项目：[bupticybee/TexasSolver](https://github.com/bupticybee/TexasSolver)
- 许可证：[AGPL-3.0](https://github.com/bupticybee/TexasSolver/blob/master/LICENSE)
- 语言：C++/Qt
- 状态：最新公开 release 仍为 `v0.2.0`，维护频率较低。
- 能力：NLHE/Short Deck 的 GUI/console 求解器。
- 风险：AGPL、C++/Qt 构建、服务化接口不自然。WASM Postflop 官方 benchmark 在其固定配置中报告 TexasSolver 更慢、内存更高且结果有差异；这不是普遍正确性证明，但足以要求 Riverline 自己做差分验证：[WASM comparison](https://github.com/b-inary/wasm-postflop#comparison)。

**判断：不采用，只保留交叉验证价值。**

### 14. openCFR：仅作教育性算法参考

- 项目：[stockhamrexa/OpenCFR](https://github.com/stockhamrexa/OpenCFR)
- 许可证：[MIT](https://github.com/stockhamrexa/OpenCFR/blob/main/LICENSE)
- 语言：Python
- 状态：小型、低活跃；PyPI `1.0.0` 发布于 2022-11-30，仓库提交很少。
- 可学习：CFR、CFR+、MCCFR 的短小实现和小博弈测试结构。
- 风险：README 明示没有针对速度或内存优化，HUNL 需要 bucketing，超过两名玩家未经充分测试；不适合作为实时或多人 Solver。

**判断：不进入依赖，只作阅读材料。** CFR 教学和正式回归仍优先用 OpenSpiel；真实 postflop 研究用隔离的 `postflop-solver` 或 Riverline 自己的 artifact pipeline。

### 15. Solver 在 Riverline 中应成为离线 artifact 工厂

Solver 的可复用单位不应是一次同步 HTTP 调用，而应是：

```text
SolverJob
  input: game rules + rake + stacks + board + ranges + action tree
  budget: algorithm + iterations/time + target exploitability
  output: immutable artifact
          ├─ node fingerprint
          ├─ policy frequencies
          ├─ EV/equity where supported
          ├─ convergence/error metadata
          └─ engine/version/license provenance
```

在线 Advisor 先返回 L0/L1 和 curated/cached L2；命中 artifact 时再补齐频率；未命中时只排入后台求解，不能把启发式包装成 Solver。

## 五、范围、策略数据与可视化

### 16. HandMatrix：现有 Riverline UI 更值得保留

- 项目：[HoldemPokerTools/HandMatrix](https://github.com/HoldemPokerTools/HandMatrix)
- 许可证：[MIT](https://github.com/HoldemPokerTools/HandMatrix/blob/master/LICENSE)
- 语言：React/JavaScript
- 状态：84 commits，但 release/维护主要停留在 2020 年代早期。
- 可学习：169 matrix 的 `comboStyle`、subtext 和 pointer-drag 回调设计。
- 风险：组件能力简单、生态较旧；Riverline 已有 combo 级 belief、prior/current/delta 和 provenance，替换会倒退。

**判断：不依赖，只参考 pointer interaction。**

### 17. 不直接复用公开 “GTO charts”

本次调研没有找到可直接作为 Riverline 生产策略源、同时满足以下条件的开放数据集：

- 明确桌型、rake、ante、有效筹码、位置和完整 action tree；
- 提供 combo 级混合频率而非只有 169 hand membership；
- 给出 Solver/算法、树配置、收敛阈值与版本；
- 策略数据本身的许可明确，而不只是展示代码的 MIT 许可；
- 覆盖 Riverline 首发 6-max 主要节点并可做回归。

[phh-dataset](https://github.com/uoftcprg/phh-dataset) 是有用的真实/研究手牌样本，但它不是均衡策略库。Riverline 应维持自己的 `PolicyArtifact`：每份 curated 表、模型或 solver export 都有 `source/version/config/license`，并允许 `unsupported`，不要用无来源图表填满覆盖率。

## 六、事件存储与学习调度

### 18. `eventsourcing`：学习其模式，第一阶段不直接引入

- 项目：[pyeventsourcing/eventsourcing](https://github.com/pyeventsourcing/eventsourcing)
- 许可证：[BSD-3-Clause](https://github.com/pyeventsourcing/eventsourcing/blob/master/LICENSE)
- 语言：Python
- 状态：成熟且活跃；稳定版 `9.5.4` 发布于 2026-03-27，`9.6.0b1` 于 2026-06-19。支持 aggregate、repository、SQLite/扩展 recorder、snapshot、notification log、projection、加密/压缩等：[README](https://github.com/pyeventsourcing/eventsourcing#event-sourcing-in-python)。官方 application 文档说明 notification log、snapshot 和 event store：[Applications](https://eventsourcing.readthedocs.io/en/stable/topics/application.html)。
- Riverline 可学习：aggregate version、optimistic concurrency、upcast、snapshot、全局 notification sequence、projection checkpoint 和 outbox/notification log。
- 不直接采用原因：Riverline 已有持久化 schema；在牌局内核重构同时引入完整 Aggregate/Application 框架会扩大迁移面，并让 GameSession 绑定第三方建模方式。产品第一阶段只需要可重放 hand events、幂等投影和后台任务，不需要一次性实现完整 CQRS 平台。

**判断：仅学习模式，先自建薄事件层。** 建议做 `hand_events` append-only 表、aggregate `version` 唯一约束、snapshot、projection cursor 和同事务 outbox；稳定后再用 spike 比较是否迁移到该库。

PostgreSQL 已提供 `jsonb`、表分区和物化视图等基础能力，分别见官方 [JSON 文档](https://www.postgresql.org/docs/current/functions-json.html)、[partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html) 和 [materialized views](https://www.postgresql.org/docs/current/rules-materializedviews.html)。首阶段没有必要再部署专用 EventStore 服务。

### 19. py-fsrs：直接用于概念与练习的间隔复习

- 项目：[open-spaced-repetition/py-fsrs](https://github.com/open-spaced-repetition/py-fsrs)
- 许可证：[MIT](https://github.com/open-spaced-repetition/py-fsrs/blob/main/LICENSE)
- 语言：Python
- 状态：活跃；当前主版本为 FSRS 6 系列。库提供 Scheduler、Card、ReviewLog、retrievability、JSON serialization 和可选参数优化：[README](https://github.com/open-spaced-repetition/py-fsrs#py-fsrs)。
- Riverline 复用：把 `concept_id + spot_family + misconception` 映射为学习卡；用户在考试模式中的真实决策和牌后练习映射为 Again/Hard/Good/Easy；存储 ReviewLog，并在数据量足够后优化参数。
- 风险：FSRS 安排“何时复习”，不决定“练什么”或判断扑克行动是否正确。评分必须来自 Review/Concept 服务，不能把单手输赢作为 rating；库使用 UTC，产品需统一时区边界。

**判断：直接引入后端，但放在 `ReviewScheduler` 端口后面。** 第一阶段使用默认参数，不急于按用户训练参数。

若未来希望前端离线预览复习队列，[ts-fsrs](https://github.com/open-spaced-repetition/ts-fsrs) 同为 MIT 且活跃，但首阶段保持后端为调度真相，避免 Python/TypeScript 双重实现漂移。

## 七、GPL/AGPL 对“非商业项目”的实际边界

“不商业化”不会自动豁免 GPL/AGPL。GNU GPL 本身允许商业使用和收费；许可证触发点主要是如何复制、修改、组合、传递/分发，而不是是否收费。GNU 官方 FAQ 说明：只在内部制作和运行、没有向他人 convey 的 GPL 组合，通常不会产生面向外部的分发义务；一旦向他人提供二进制或组合程序，则需要按相应许可证满足 source 和许可条件：[GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)。

AGPL 在 GPL 基础上增加了网络交互场景。GNU 对其目的的说明是：如果运行修改后的 AGPL 程序并允许其他用户通过服务器与其交互，服务器还必须向这些用户提供对应修改版本的源代码：[Why the Affero GPL](https://www.gnu.org/licenses/why-affero-gpl.html)。完整条款以 [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) 为准。

对 Riverline 的保守工程建议：

- 个人本地试验 AGPL solver 与“把它纳入 Riverline Web/FastAPI 产品”是两种不同风险等级。
- 不要假定 sidecar、容器、子进程或 HTTP 边界必然让两个程序成为法律上的独立作品；FSF 自身也提示组合判断取决于实际通信和集成方式，而不只看容器数量。
- 如果 Riverline 准备整体按 AGPL 兼容方式公开相应源代码，可以评估直接集成；如果希望保留其他许可或闭源可能性，则将 AGPL solver 限制为开发者手动运行的可选研究工具，并在发布前让专业人士审查。
- 保留第三方组件清单、精确 commit/tag、LICENSE、修改补丁和 artifact provenance。
- 没有 LICENSE 的仓库不能因为“公开在 GitHub”或项目名含 MIT 就复制。GitHub 官方明确说明，无许可证时默认版权法仍适用。

这些是风险识别和实施建议，不构成法律保证。

## 八、最终筛选表

| 处置 | 项目 | Riverline 用途 | 集成时机 |
|---|---|---|---|
| 继续采用 | PokerKit（MIT/Python/活跃） | 唯一规则真相、hand evaluation baseline | 重构第 0 天 |
| 直接采用 | PHH（MIT/规范+Python/活跃） | hand import/export、fixtures | 事件模型稳定后立即接 |
| 直接采用 | py-fsrs（MIT/Python/活跃） | 个性化间隔复习 | Concept/Review 最小闭环阶段 |
| 条件采用 | PH Evaluator（Apache-2.0/C++/Python） | EquityBackend 加速 | benchmark + 差分测试通过后 |
| 学习/adapter | PettingZoo（MIT/Python/活跃） | Bot observation/action contract、离线环境 | Bot 接口设计阶段 |
| 研究工具 | OpenSpiel（Apache-2.0/C++/Python/活跃） | CFR 正确性、小博弈、policy 评估 | 独立 research package |
| 研究工具 | RLCard（MIT/Python） | trajectory/agent 实验 | 非生产 |
| 学习模式 | pyeventsourcing（BSD-3/Python/活跃） | event version、projection、notification/outbox | 第一阶段后再 spike |
| 只看设计 | PyPokerEngine、MIT Pokerbots、HandMatrix | callbacks、subprocess、matrix interaction | 不复制核心代码 |
| 许可证审查后可选 | postflop-solver/WASM（AGPL/Rust） | HU postflop 离线 artifact、UI/算法参考 | 绝不阻塞实时路径 |
| 不采用 | TexasSolver、PokerRL、poker_ai、Treys/Deuces、OMPEval、openCFR | 交叉验证或历史学习 | 不进入依赖图 |

## 九、建议的三个验证 spike

### Spike A：Evaluator 可替换性（1–2 天）

- 从 PHH dataset 和 Riverline golden hands 采样；
- PokerKit 与 PH Evaluator 做 5/6/7-card rank、tie、随机 runout 差分；
- benchmark Hero-vs-range、range-vs-range 的 P50/P95、CPU、内存；
- 验证 Windows 安装、失败降级和 card encoding 成本。

通过条件：结果完全一致，目标 workload 至少有显著加速，部署复杂度可接受；否则继续 PokerKit。

### Spike B：Bot 协议与故障降级（2–3 天）

- 独立定义 `ObservationV1`、`LegalActionV1`、`BotDecisionV1`；
- 用本地函数和子进程各实现一个 dummy bot；
- 测试 hidden-card projection、timeout、进程崩溃、非法金额、确定性 seed、fallback；
- 提供 PettingZoo adapter 只验证批量 self-play，不改变生产规则。

通过条件：任意 agent 故障都不能中断牌局；100% 返回行动再次通过 PokerKit 校验。

### Spike C：事件重放与投影（2–3 天）

- 设计 10–15 个最小领域事件；
- 同一 hand 从 events 重放得到相同 PokerKit 状态和 fingerprint；
- 幂等投影 VPIP/PFR/3Bet、hand summary 和 PHH；
- 模拟投影失败后从 cursor 恢复，并验证 outbox 不丢任务；
- 用 `eventsourcing` 库另做小实验比较复杂度，但不立即迁移生产模型。

通过条件：固定 seed 可重放；重复消费不重复计数；规则、统计、复盘不会各自保存互相矛盾的事实副本。

## 总结

开源生态能显著降低 Riverline 的规则、格式、算法实验、评牌加速和学习调度成本，但没有一个项目能直接提供“6-max 连续对战 + 可解释范围信念 + 分层实时顾问 + 自动训练闭环”。最合理的重构是把 PokerKit 周围的产品内核做扎实，再用稳定端口接入外部能力：

```text
规则与事实自己掌握；
格式、算法、加速和调度择优复用；
Solver 是可替换 artifact producer；
Agent 永远处在权限、时限和规则校验之后。
```
