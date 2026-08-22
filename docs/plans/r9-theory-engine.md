# R9 Theory Engine：训练级、诚实分层策略计划

## 结论与范围

R9 的目标不是把 Riverline 宣传为“完整 6-max GTO Solver”，而是交付一个可用于训练、可测量、可追溯且在不支持局面会诚实降级的 Theory Engine。它把 R8 已完成的 Decision Cockpit 与 Range Explorer 接到有证据等级的策略来源上，使用户能在一个明确覆盖的局面中看到：推荐、混合频率、尺度、近似 EV 损失、Range 变化，以及这些数字究竟可信到什么程度。

R9 的快速纵向价值是：先冻结少量 canonical spots 并让 benchmark 真正能失败（red），然后把一份可追溯的翻前策略 artifact 接入 Bot、Range、Advisor 和 UI。L2 只扩展到受限的 heads-up river/turn；任何 multiway、超出树/stack/rake/版本 fingerprint 的节点都显示 `unsupported` 或下调为启发式，绝不伪装为 solver 结果。

首发产品规则仍为 6-max cash、100BB、无 ante、无 rake；此规则参数是 R9 基线而非“所有现金桌”的策略声明。

## 当前基线与结构性缺口

R8 已交付可用的决策驾驶舱、Range Explorer、决策对照契约和尺度校准 UI/测试门。其价值是把现有结果诚实地表达出来；它没有改变策略真相本身。R9 必须明确承接以下结构性缺口：

| 现有层 | 当前能力 | 不能诚实声称的能力 | R9 处理 |
|---|---|---|---|
| Bot | coarse、确定性规则/选择 | 混合策略或训练级 6-max 对手策略 | 以 artifact 驱动的混合策略 Bot；保留确定性 fallback |
| FastSolver | 单层 response、没有未来行动、启发式 response model | 多街 equilibrium EV、全树最优 sizing | 标为 L1/heuristic；以独立 L2 bounded solver/artifact 取代其“权威”位置 |
| FormulaAdvisor | 固定阈值与确定性公式 | range-aware 的策略频率或完整反事实 EV | 保持为 L0 数学；转为 Theory Explainer，不再仲裁策略真相 |
| Range Belief | factorized、独立 seat marginal、启发式 likelihood | 联合 range、真实 Bot policy likelihood、跨座位相关性 | prior 和 action-likelihood 取自同一 policy source；不做 joint posterior 承诺 |
| UI | 可显示 Advisor/Solver、range/provenance 和降级 | 结果天然相同、UI 视觉即可校准模型 | 显示 Theory source、证据等级、coverage 和比较语义 |

**不可变边界**：PokerKit 继续是规则、合法行动、结算、私牌权限和重放真相；Theory Engine 只能消费合法的公开 observation 与 Hero 私牌。任何 policy/solver/agent 返回均须经过现有合法行动与金额校验。无策略来源、超时、缓存失配或异常不能阻塞牌局，也不能泄露其他座位私牌。

## 训练用户任务与 UI 语义

R9 的验收以训练任务为中心，而不以“页面有更多数字”为中心：

1. 在覆盖 spot，用户能在 5 秒内判断推荐行动、是否为 mixed、主要尺度与来源等级。
2. 用户能区分“理论基线”与“公式/启发式解释”，且不会把 unsupported 当成建议。
3. 用户可从 Range Explorer 看出某行动后 range 的方向和变化来自哪份 policy，而不是把 independent marginal 当作对手真实手牌。
4. 考试模式在行动后显示相对 artifact/L2 的 action-frequency deviation；只有 oracle 支持相同定义 EV 时才显示 EV loss。
5. 不支持的 multiway 或树外节点继续可打、可查看 L0/L1，但明确写出限制和可用的较低层结果。

每个策略型 UI 结果必须包含：`source_kind`、`evidence_grade`、`coverage_status`、`policy/version fingerprint`、适用的 players/street/tree/stack/rake 与降级原因。推荐文案按如下语义冻结：

| 证据等级 | 可展示 | 不可展示/必须注明 |
|---|---|---|
| A：可信 oracle | 可称“理论基线”；展示频率、尺度、EV/EV loss（仅 oracle 有定义时） | 不外推到 fingerprint 之外；不可称完整 6-max GTO |
| B：可追溯近似 | 可称“近似策略/本地求解”；展示频率、范围、近似 EV 与误差/预算 | 不写成精确均衡或无误差 EV loss |
| C：启发式/公式 | 可称“公式基线”或“启发式倾向”；展示假设与理由 | 不显示伪精确频率、solver EV 或 range likelihood 真相 |
| unsupported | 显示不覆盖、原因及仍可用 L0/L1 | 不给理论推荐、频率或 EV loss |

`exact_math` 是数学输入/输出的精确性标签，不自动等同 A 级策略；`cached_policy` 的等级继承其 artifact；`lightweight_solver` 至少为 B，除非以可复现 oracle 证据提升；`heuristic` 永远为 C。

## Benchmark-first：理论质量门

R9-00 先建立 versioned canonical spot registry 和可独立运行的 benchmark harness。没有使测试 red 的 fixture、阈值和故意错误样本，后续任何“质量通过”都不成立。

### Canonical spots 与 oracle 层级

每个 spot 固定：规则版本、玩家数、位置、有效筹码、盲注/rake/ante、board、Hero/对手 ranges、公开 action prefix、合法 action/sizing tree、seed（若采样）、适用 policy artifact 与 fingerprint。第一批应刻意小而全：

- 6-max 100BB 无 rake 的翻前 RFI、面对 RFI 的 fold/call/3bet，以及最小 3bet/4bet 分支；
- HU river 的 value/bluff-catcher 与 bet-size 分支；
- HU turn 的受限 continuation 子树；
- multiway / 非覆盖 stack / 未定义 sizing 的明确 unsupported fixtures；
- private-card projection、非法 action、artifact miss 与 fallback fixtures。

oracle 按可追溯性从高到低选择：A 级为自有、冻结并可复现的离线 solver export 或经过双实现/已知小博弈验证的 exact enumeration，附 solver、tree、收敛、license 和 digest；B 级为有版本、参数与误差/预算元数据的局部求解或可复现近似；C 级为 FormulaAdvisor/显式规则。公开 chart、截图或无策略数据许可证的网页都不能成为 A/B oracle。外部 solver 输出只可作为独立交叉检查，不能遮蔽 provenance 缺口。

### 必测指标与 red 条件

每个 spot、provider 和 artifact version 均记录并报告以下指标；阈值由 R9-00 的受控 calibration fixture 冻结，不能在失败后静默上调：

| 指标 | 定义 | 典型 red 条件 |
|---|---|---|
| action correctness | 推荐动作集合是否与 oracle 容忍集合相交 | 不相交，或 illegal action |
| frequency error | 各 action 概率与 oracle 的 L1/absolute error | 超过 fixture 阈值，或概率不归一 |
| sizing error | 选择的 `raise_to`/pot% 与同 tree 合法 sizing 的差异 | 尺度不合法、树外或超过阈值 |
| EV loss | 在同一 oracle EV 定义下，所选/采样策略的 regret | EV 口径缺失却仍输出，或超过阈值 |
| range divergence | action 后 posterior 与 oracle/reference range 的 weighted divergence | 超阈值、dead card 未清除、质量不守恒 |
| calibration | confidence/evidence claim 与实际正确率/误差的可靠性 | 高置信误差超阈，或 C 假装 A/B |
| latency | L0/L1/L2 与 cache hit/miss 的 P50/P95 | 超预算或超时未降级 |

Harness 必须有：已知正确的 green fixture、刻意扰动 action/frequency/sizing/range 的 red fixture、版本或 fingerprint 不匹配的 red fixture，以及报告中标明是否有可用 oracle。对 C/unsupported，action/frequency/EV 不以“错误”判失败；它们的 red 条件是错误分级、越权推荐、错误 fallback 或违反安全不变量。

### 性能预算

以用户决策点为单位（不把 R8 纯前端播放延迟算入）：L0 deterministic P95 <20ms；已有 L1/缓存策略首层 P95 <300ms；A artifact lookup/混合 Bot policy P95 <100ms；L2 cache hit P95 <500ms；L2 cache miss 只入后台/异步，前台 0.5–3s 内有 B 级结果则渐进显示，超过预算立即保留低层并标降级。R9-00 还需测量 benchmark batch 的可重复性，记录硬件/运行配置，避免把开发机数字作为通用 SLA。

## 策略来源分层与许可/SaaS 边界

```text
A  immutable, versioned PolicyArtifact（优先命中）
    ↓ miss / supported bounded node
B  local bounded solver L2（缓存或异步 artifact producer）
    ↓ unsupported / timeout / invalid input
C  Formula + explicit heuristic（不冒充策略）
    ↓
unsupported（不阻塞牌局，不给伪理论答案）
```

### A. 预计算可信策略

`PolicyArtifact` 是不可变、可签名/digest 的数据产品，不是散落图表。至少包括 schema version、game/tree/range fingerprint、policy frequencies、sizing、可选同口径 EV、coverage、solver/config/convergence、生成时间、source/license、验证状态和 evidence grade。线上只读取已验证 artifact；生成、审核与发布在离线 pipeline 完成。第一版本聚焦翻前，不拿有限 chart 填充所有 6-max 分支。

### B. 局部求解

L2 是限定 tree 的 HU turn/river policy artifact 工厂和可选本地缓存填充器，不是同步全局服务。输入必须含完整 fingerprint，输出必须存 budget/convergence/error/engine/license provenance。先覆盖 heads-up river，再扩展受限 turn；multiway、深度超界、未知 range、tree/sizing 不一致一律显式降级，不能将 HU 结果投射给多人底池。

### C. 诚实启发式

FormulaAdvisor、FastSolver 当前 coarse one-response 和 teaching rules 归入 C，继续为 L0 数学与解释提供价值。C 可以排序候选或说“通常倾向”，但不能产生 A/B 的策略频率、EV loss、solver badge 或训练评分真相。其 assumptions、模型限制和 fallback reason 是 API/UI 的必填字段。

### 许可和 SaaS-ready 边界

- AGPL/GPL 的义务不因“非商业”而自动豁免；网络交互的 AGPL 风险也不因 sidecar、容器、子进程或 HTTP 边界自动消失。
- `postflop-solver` 和 TexasSolver 均为 AGPL：R9 不将其直接链接、打包、部署进 Riverline 服务或作为 SaaS 路径依赖。它们仅可在隔离的开发者研究环境作人工交叉验证，须先完成专业许可审查和来源记录。
- 无 LICENSE 的代码不可复制；公开 GTO charts 若缺少策略数据许可、tree/config 或 provenance，不可导入为 policy artifact。
- SaaS-ready 的产品路径只依赖 Riverline 自有实现或已审查的兼容许可证组件。每份 artifact 必须保留 source/version/license、生成命令/配置、修改补丁（如有）和发布判定；缺任一项则不能升级为 A/B 或进入线上默认策略。
- 本节是工程风险边界，不构成法律意见。任何改变仓库许可、对外发布策略 artifact、或拟集成 AGPL 工具的决定都需要产品/法律明确批准。

## 复用、替换与契约演进

| 复用 | R9 改造/替换 | 明确不做 |
|---|---|---|
| PokerKit 规则、合法金额、结算与 replay；session/event identity；现有 Policy Provider provenance、Solver job/cache/fingerprint；Range V2 combo/dead-card 规则；R8 cockpit/explorer；FormulaEngine | Bot coarse deterministic → seeded mixed `PolicyArtifactBot`; FastSolver 权威推荐 → C provider；FormulaAdvisor → Theory Explainer；启发式 range update → prior/action-likelihood 同源；R8 reconciliation → 单一 Theory recommendation 来源 | 替换规则引擎；联合 multi-seat posterior；让 Agent/LLM 计算数值或看到私牌；前端自行推导模型精度；同步全树 6-max solver |

新增/演进的公共 contract 必须 additive、versioned，并遵守现有私牌投影：`PolicyArtifact`、`TheoryRecommendation`、`TheoryEvidence`、`RangeLikelihood`、`BenchmarkResult` 和 `coverage_status`。冻结这些字段前由 R9-00 提供最小 schema proposal 与 consumer fixtures；若会破坏既有 API，停下请求 Controller/产品决定。

## 任务拆分、所有权与验收

| 任务 | 目标/主要文件所有权 | 依赖 | P0/P1 验收门 |
|---|---|---|---|
| R9-00 Benchmark harness | `backend/.../theory/benchmark*`、canonical fixtures、oracle manifest、benchmark report contract | R8 merged | red/green fixtures；五类策略指标 + calibration/latency；非法/私牌/fingerprint miss red；不接入生产推荐 |
| R9-01 Range visual semantics | Range DTO consumer、Range Explorer/Cockpit 视觉与 tests | R9-00 的 evidence/coverage vocabulary | UI 不将 independent marginal 表述为联合真相；显示 source/grade/coverage、unsupported 与 action-to-action semantic delta；多视口/键盘/旧响应隔离 |
| R9-02 Preflop artifact + mixed Bot | policy artifact schema/store、preflop fixtures、Bot provider 与 focused tests | R9-00 | artifact provenance/license/digest 完整；seeded frequencies 归一且行动/金额合法；benchmark 达标；miss 回退 C/unsupported；无 hidden-card access |
| R9-03 Same-source range prior/likelihood | range prior/update provider、policy likelihood contract、tests | R9-02 | Bot 实际 policy 与 belief likelihood 同 version/fingerprint；dead cards、public-event/privacy、mass invariants；不宣称 joint posterior |
| R9-04 Bounded local solver L2 | isolated L2 engine/job/artifact/cache、HU river then turn fixtures | R9-00；R9-02 schema | HU-only fingerprint/预算/误差/provenance；A/B benchmark gate；timeout/miss 不阻塞；multiway 明确降级；独立窄审 P0/P1 |
| R9-05 Theory Explainer + unified recommendation | Advisor/reconciliation API、Theory explanation UI/tests | R9-02；R9-04 可并行但 L2 integration depends R9-04 | 一个策略推荐真相来源；Formula 只作 C explanation；无 oracle 不显示 EV loss；冲突和 source 不可静默覆盖 |
| R9-06 Product integration | table/cockpit/range/review integration、telemetry/e2e | R9-01/02/03/05，L2 可选增强 | 覆盖/降级链在真实连续牌局可见；考试后比较不会泄露未来/私牌；两手 journey、reconnect、old-response/privacy 通过 |
| R9-07 Release gate | release evidence、license/provenance audit、full gates | R9-06 | 完整 backend/frontend/E2E；benchmark report；artifact license/SaaS check；P0/P1 independent narrow review；binary/container 边界仍独立判定 |

并行限制：R9-01 可在 R9-00 vocabulary 初稿冻结后与 R9-02 并行；R9-03 必须等待 R9-02；R9-04 不与同一 policy/range contract writer 并行；R9-05 先用 A/C 完成统一来源，再接 L2。每任务在独立 branch/handoff 中声明精确 baseline、changed files、实测质量门和未测项；Controller 是 ledger 的唯一写入者。

## 全程 P0/P1 与安全不变量

P0：规则/金额/结算或筹码守恒被策略层改变；Bot/solver 读到不应可见私牌；artifact/缓存跨 hand/session/fingerprint 复用；unsupported 被显示成理论推荐；AGPL/无许可策略进入 SaaS-ready 产品路径。

P1：频率不归一或不与 seeded Bot 实际选择一致；Range mass/dead-card/public-event 语义错误；EV loss 混用不同 tree/range/单位；timeout 阻塞行动；UI 把 C 级视觉伪装为 A/B；benchmark 无 red case 或阈值可被实现静默改写。

所有 policy 选择须记录 deterministic seed（适用时）、provider/version、input fingerprint、elapsed/degradation；所有 Range 更新只能依据公开事件和 actor 可见 policy；所有 E2E/telemetry 读取必须遵守 Hero/seat 的 private projection。

## R9 完成线与后续 backlog

**R9 必须完成**：R9-00 的可 red benchmark；R9-01 的 evidence/coverage 视觉语义；至少一个有完整 provenance 的 preflop artifact 并驱动混合 Bot（R9-02）；同源 range likelihood（R9-03）；HU river 的 bounded L2 或明确记录其作为未达成的 P1 release blocker；Theory Explainer 的统一来源（R9-05）；连续牌局训练闭环（R9-06）；发布门（R9-07）。R9 的产品发布不能以“未来 solver”掩盖缺失的 benchmark、provenance 或降级表达。

**R9 后 backlog**：完整 6-max postflop/多街/多方 equilibrium；joint multi-seat range inference；更大翻前 action tree 和不同 rake/stack；Deep CFR/自博弈训练；外部 Agent marketplace；实时未缓存 solver；个性化 exploit 与长期校准研究；artifact 签名/远程分发服务；binary/container release（仍受现有 SBOM 门约束）。这些工作须先有新的 benchmark/许可/性能契约，不能作为 R9 小任务顺手扩张。

## 未验证决策

- 第一批 A 级 preflop artifact 的生成器、精确 action tree、rake/stack coverage、许可与维护 owner 尚未决定；在此之前不可声称 A 级覆盖。
- L2 采用自研、经审查的 Apache/MIT 组件，还是仅以自有离线 pipeline 产出，尚需产品和许可决定；AGPL 工具不在默认候选内。
- action/frequency/EV-loss/range-divergence 的数值阈值必须由 R9-00 冻结的 baseline 和 oracle 数据确定；本计划不伪造具体精度数字。
- 默认辅助/提示/考试模式、策略 artifact 的最终产品发布许可、以及训练评分是否以频率、EV loss 或二者组合，仍需产品确认。
