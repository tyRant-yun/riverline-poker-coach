# Riverline 重构产品愿景：可观测的德州扑克认知模拟器

> 状态：产品方向共识稿
> 日期：2026-08-12
> 目的：指导 Riverline 从“场景编辑与牌谱分析工具”重构为“持续对战、实时决策辅助、自动复盘和长期训练”一体化产品。

## 1. 核心结论

Riverline 的主产品不应继续以“输入一手牌 → 点击分析”为中心，而应成为：

> 一个带完整决策仪表盘的德州扑克训练模拟器。用户正常与 AI 玩家持续对战，系统像一个透明、可解释、可降级的增强型牌手大脑，在每个决策点展示当前可以确定的事实、可以估计的范围、可比较的行动和相关理论，并把每一次决策自动转化为后续学习材料。

它更接近“飞行模拟器”，而不是单次使用的牌谱分析器。

产品的真正壁垒不只是 Solver 精度，而是把以下四层稳定连接起来：

```text
持续运行的牌局
    ↓
确定性数学 + Range/策略推断
    ↓
按当前节点选择最相关的理论和解释
    ↓
根据用户长期错误安排下一次训练
```

## 2. 产品目标

### 2.1 用户目标

帮助用户在真实决策发生时学习并逐渐内化：

- 位置、有效筹码、底池和合法行动；
- Pot Odds、SPR、Fold Equity、所需胜率等确定性数学；
- Hand vs Range、Range vs Range，而不是孤立的绝对牌力；
- 行动如何压缩或改变某一玩家的 Range；
- Fold、Call、Raise 之间的相对 EV，而不只是某个行动是否正 EV；
- Equity Realization、Implied Odds、Reverse Implied Odds 等多街因素；
- 理论基线与针对特定玩家偏差的 exploit 调整；
- 自己长期、重复出现的决策 leak。

### 2.2 产品目标

- 支持连续完成的 6–8max 人机牌局，而不是孤立场景；
- AI 玩家具有不同水平和稳定可识别的行为画像；
- 每个 Hero 决策都能快速得到至少一层可信建议；
- 每个玩家的公开 Range Belief 可追踪、可解释、有来源；
- Solver、策略表、启发式和 Agent 均可接入，但任何单一外部能力失败都不能阻塞牌局；
- 每手牌自动进入数据池，并形成即时复盘和长期能力画像；
- 现有 Hand Lab 保留为高级复盘与局面实验室，但不再承担首页主流程。

## 3. 核心用户循环

每个决策点自动执行四个阶段。

### 3.1 读取局面

- 位置、按钮位、有效筹码和底池；
- 当前街、行动顺序和合法行动；
- 跟注成本、下注/加注含义和可用尺度；
- SPR、Pot Odds、直接所需 Equity；
- 对手已经积累的 VPIP、PFR、3Bet 等画像。

### 3.2 推测未知信息

- 根据桌型、位置、筹码、ante/rake 和玩家画像建立每个座位的 Prior；
- 根据该玩家的行动及尺度，用 `P(action | combo, context)` 更新其 Range；
- 发出公共牌后，对所有活跃座位应用公开 blockers；
- 展示 Prior、Current、Delta、来源、置信度和不可用原因；
- 不把估计结果包装成已知事实。

### 3.3 辅助 Hero 决策

- 比较 Fold、Call、Bet/Raise 及候选尺度；
- 立即显示确定性数学和低延迟 baseline；
- 随后渐进补充 equity、策略频率、轻量求解或更深分析；
- 明确标识结论来自精确计算、curated baseline、缓存、轻量求解、启发式或外部 Agent；
- 不输出缺乏支撑的伪精确 EV loss。

### 3.4 沉淀学习数据

- 保存 Hero 实际行动、顾问建议及差异；
- 保存决策时可见状态、Range Belief、公式输入和策略版本；
- 一手结束后自动生成按重要性排序的复盘；
- 多手累积后识别位置、节点、尺寸、概念和玩家类型上的长期 leak；
- 从真实错误生成后续练习，并进行间隔复习。

## 4. 实时决策顾问，而不是“万能 Solver”

6–8 人完整牌局无法在产品所需延迟内对所有节点进行最高精度求解。系统应采用多层决策顾问架构。

| 层级 | 内容 | 目标延迟 | 性质 |
|---|---|---:|---|
| L0 | 底池、位置、合法行动、Pot Odds、SPR | `<20ms` | 确定性 |
| L1 | Hand/Range Equity、成牌率、blocker、范围统计 | `20–150ms` | 计算或采样 |
| L2 | 翻前策略表、缓存 policy、轻量策略模型 | `50–500ms` | 基线策略 |
| L3 | HU 翻后轻量 Solver、有限深度 rollout | `0.5–3s` | 节点近似 |
| L4 | 教学 Agent 的自然语言解释 | 异步 | 表达与组织 |

用户进入决策点后应立即得到 L0/L1；更深结果完成后渐进更新，不让 Solver 阻塞牌局。

产品统一称其为“决策顾问”或“策略引擎”，并对每项结论显示来源：

- `exact_math`
- `equity_estimate`
- `curated_baseline`
- `cached_policy`
- `lightweight_solver`
- `heuristic`
- `external_agent`
- `unsupported`

## 5. Range Belief 设计原则

### 5.1 第一阶段采用座位独立的 factorized belief

```text
位置 / 筹码 / 玩家画像
        ↓
该座位 Prior
        ↓
该玩家行动 × P(action | combo, context)
        ↓
该座位 Current
        ↓
公共牌发出后统一应用 blockers
```

- 某位玩家采取行动时，主要更新该行动者自己的 Range；
- 其他玩家不会仅因为“别人下注”就直接获得独立 Bayesian 更新，但其后续决策上下文会改变；
- 公共牌出现时，所有活跃玩家的可行 combo 会变化；
- folded seat 可保留最终信念用于复盘，但不再参与后续活跃范围展示；
- 联合范围相关性与跨座位边缘更新属于后续高级能力，不进入第一阶段。

### 5.2 AI 玩家应尽可能返回策略分布

理想的机器人输出不只有最终动作，还包含该节点的策略频率：

```json
{
  "action": "raise",
  "amount": 600,
  "policy": {
    "fold": 0.12,
    "call": 0.31,
    "raise": 0.57
  }
}
```

这样 Range Belief 可以使用真实策略似然更新。若外部 Agent 只能返回单一动作，则使用独立观察者 policy model 推断，并降低置信度，不能把推断称为 Agent 的真实混合策略。

## 6. AI 玩家与 Agent 接口

### 6.1 AI 等级不是简单随机犯错

所有等级共享规则真相和合法行动校验，通过策略覆盖、误差模型和行为画像分层：

- 初级：固定策略，具有稳定的 loose/passive、tight/passive 等明显偏差；
- 中级：完整翻前 blueprint、基础翻后规则和有限下注尺度；
- 高级：更完整的 Range policy、缓存节点、HU 翻后轻量求解；
- Agent 模式：调用外部 Agent，失败时降级到本地高级或中级策略。

除强弱等级外，还应提供可识别的玩家画像：

- 紧弱；
- 松被动；
- TAG；
- 过度激进；
- 过度 Bet/Fold；
- 过度跟注；
- 平衡型高级玩家。

### 6.2 Agent 的信息边界

机器人只能看到：

- 自己的手牌；
- 公共牌；
- 公开行动历史；
- 自己可见的筹码与位置；
- 当前合法行动。

机器人不得访问 Hero 手牌或其他隐藏牌。所有返回动作必须经过规则引擎校验、尺度归一化、超时控制和降级链处理。

### 6.3 建议的统一接口

```text
BotDecisionProvider.decide(
  observation,
  legal_actions,
  time_budget,
  rng_seed
) -> BotDecision
```

`BotDecision` 至少包含：

- action；
- amount/amountType；
- policy frequencies（如可用）；
- provider/version；
- confidence；
- elapsed time；
- degraded/fallback reason；
- 可选的内部理由，但语言理由不作为数值真相。

## 7. 学习资料如何成为产品知识层

“Poker Decision Daily”中的内容最适合转化为教学操作系统，而不是策略频率数据。

### 7.1 概念图谱

资料天然形成以下依赖关系：

```text
Pot Odds
   ↓
Equity
   ↓
EV
   ├─ Fold Equity
   ├─ Implied Odds
   └─ Equity Realization
          ↓
         SPR
          ↓
多街策略、范围构建与尺寸选择
```

建议结构化为：

```text
Concept
- id / name
- prerequisites
- applicable_spots
- exact_formulas
- simplified_models
- common_misconceptions
- examples
- exercise_generators
- source/version
```

### 7.2 确定性 Formula Engine

以下内容应由代码计算，不交给 Agent 心算：

- Pot Odds；
- Bluff break-even fold frequency；
- Call required equity；
- SPR；
- MDF；
- 简化 Semi-bluff EV；
- 不同尺度的风险回报；
- geometric sizing；
- combo 与 blocker 计数。

每次计算返回公式、输入、结果与假设。例如：

```json
{
  "formula": "risk / (risk + reward)",
  "inputs": { "risk": 100, "reward": 133 },
  "result": 0.429,
  "assumptions": [
    "被跟注后无摊牌权益",
    "忽略后续街行动"
  ]
}
```

Agent 只负责选择相关概念和解释结果，不负责生成关键数值。

### 7.3 反事实比较

产品应贯彻：

```text
Positive EV != Optimal Action
```

因此重点不是只证明一个行动盈利，而是比较：

```text
EV(Fold) vs EV(Call) vs EV(Raise)
```

高级面板应允许用户调整下注尺度、对手弃牌率、继续范围和有效筹码，观察：

- 所需 Fold% 如何变化；
- 对手 Call 所需 Equity 如何变化；
- Range 如何压缩；
- 候选行动排名是否改变；
- 哪些结论是确定性，哪些依赖模型假设。

### 7.4 从课程到动态练习

课程练习应参数化为 Exercise Generator。例如：

```text
给定 P、B、R，计算纯诈唬 Check-Raise 所需 Fold%。
```

系统可以从用户刚打过的牌中抽取真实数值并生成变体：

1. 实战中出现错误；
2. 系统关联到概念和常见误区；
3. 手牌结束后生成同结构、不同数字的练习；
4. 次日或后续牌局进行间隔复习；
5. 连续掌握后降低提示强度。

### 7.5 课程内容的边界

- 定性结论不能冒充精确策略频率；
- 教学简化公式不能冒充完整多街 EV；
- “通常”“倾向”“更适合”等规则不能直接作为精确行动似然；
- “湿润牌面提高 Check-Raise capacity”可以解释策略，但不能独立推出某 combo 应 37% Raise；
- 精确频率仍需来自策略表、缓存 artifact、轻量 Solver 或经过校准的 policy model。

## 8. 面向学习的交互模式

为了避免用户只会照着答案点击，产品提供三种揭示模式，共享同一个分析内核：

- 全辅助：行动前展示建议、范围、公式和解释；
- 提示模式：默认只展示事实与关键变量，用户主动请求后显示建议；
- 考试模式：用户先行动，系统随后展示建议和偏差。

单个决策点采用三层渐进式 UI。

### 第一层：立即结论

```text
建议：Call 为主，少量 Raise
置信度：中
```

### 第二层：关键原因

```text
直接价格需要 22.3% Equity
Hero 对 Bet Range 约有 35%
Raise 后对手继续范围更强
当前 Call 的估计价值高于 Raise
```

### 第三层：完整理论

- 公式代入；
- Prior/Current/Delta；
- combo 与 blocker；
- 候选尺度反事实；
- Solver/策略频率；
- 对应课程内容；
- 即时练习。

## 9. 数据池与长期学习画像

VPIP、PFR、3Bet 等指标必须记录，但不足以描述学习问题。每个 Hero 决策还应保存：

- hand/session/decision/action ID；
- 决策时完整公开状态及状态 fingerprint；
- Hero 实际行动与耗时；
- 顾问候选行动、频率和来源；
- Range Belief snapshot 与 policy version；
- 公式输入、结果和模型假设；
- 关联概念、误区和局面标签；
- 用户是否查看提示、查看到第几层；
- 近似 EV regret 或无 EV 时的策略偏差等级；
- 牌局结果，但不把单手输赢直接当作决策质量。

长期报告优先回答：

- 是否在 BB vs BTN 防守不足；
- 是否在多人底池高估弱 offsuit 手牌；
- 是否在有摊牌价值时过度转诈唬；
- 是否经常选择错误 Raise 尺寸；
- 是否只判断行动正 EV，而没有比较替代行动；
- 是否在面对大尺度时忽略 Range Compression；
- 哪些概念在无提示条件下仍未掌握。

建议学习指标包括：

- 无提示决策正确率；
- 策略频率偏差或 EV regret；
- 决策耗时；
- 同类错误复发率；
- 概念掌握度；
- 提示依赖度；
- 对置信度和不确定性的校准能力。

## 10. 用机器人偏差驱动针对性训练

课程中的 exploit 场景可以转化为机器人行为画像：

| 机器人偏差 | 适合训练的能力 |
|---|---|
| C-bet 过宽、面对 Raise 过度弃牌 | Check-Raise、Semi-bluff、Fold Equity |
| 3Bet 后过度跟注 | 线性价值范围、减少纯诈唬 |
| BTN 开局过宽 | BB 防守和 3Bet |
| Limp/Call 过多 | Iso、薄价值、多人底池 |
| 河牌诈唬不足 | Bluff-catcher 弃牌纪律 |
| 过度跟注多街 | Value-heavy sizing |

训练调度器可以根据用户近期弱点，安排具有相应 leak 的机器人进入牌桌，使牌局本身成为课程。

## 11. 现有能力的复用与重构边界

### 11.1 应重点复用

- PokerKit 多人规则、合法行动、边池、分池和结算；
- 2–8 人座位、按钮位与位置派生；
- combo 级 Range Belief、时间语义和 dead-card 规则；
- Policy Provider 链、provenance 和诚实降级；
- Solver job、缓存、节点 fingerprint 和 artifact grounding；
- Evidence、Teacher 和整手复盘能力；
- 现有 Hand Lab 的高级复盘和局面实验能力。

### 11.2 需要新增的产品内核

- `GameSession`：连续多手、筹码变化和桌级配置；
- `GameOrchestrator`：行动轮转、机器人调度、发牌、结算和下一手；
- `BotDecisionProvider`：本地固定策略、策略模型、Solver 和 Agent 的统一接口；
- `AdvisorService`：Hero 决策点的多层实时提示；
- `FormulaEngine`：确定性公式和假设注册；
- `ConceptGraph`：概念、误区、解释与练习的知识层；
- `Telemetry/EventStore`：不可变牌局事件和分析版本；
- `SessionStats/LearningProfile`：行为统计与概念掌握度；
- 以牌桌为中心的新前端状态架构。

### 11.3 不宜继续扩展的方向

- 不应继续把大量实时牌局状态堆入当前文档式单页状态；
- 不应把外部 Teacher Agent 直接当作数值计算器或规则权威；
- 不应把 HU 翻后 Solver 包装成全桌型、全节点 Solver；
- 不应以单一“测试通过率”代替真实对战、延迟、覆盖和学习效果验收。

## 12. 建议的第一阶段产品边界

底层规则与协议支持 2–8 人，但首个正式产品模式只完整发布一种主桌型。建议默认完成 6-max，再开放 8-max；若策略数据准备更适合 8-max，也可以反向选择，但必须坚持“一个桌型完整闭环优先于两个桌型局部可用”。

第一阶段必须做到：

- 用户可以连续完成至少数百手牌，无需手动构造场景；
- 至少三档本地 AI，外部 Agent 不可用时仍能稳定运行；
- Hero 每个决策点在 100–300ms 内得到第一层顾问结果；
- 每个活跃对手都有可查看的 Range Belief、来源和置信度；
- 每手自动入库并生成复盘；
- 支持全辅助、提示和考试三种模式；
- 能生成按最大偏差、高频错误和概念弱点排序的复盘；
- Agent、Solver 超时或不支持节点不会阻塞牌局；
- 现有 Hand Lab 可从牌局历史进入，用于进一步实验。

## 13. 第一阶段验收指标

### 对战可靠性

- 连续牌局完成率；
- 非法行动率为零；
- 机器人超时降级成功率；
- 结算、边池和筹码守恒；
- 固定 seed 下可重放。

### 实时性能

- L0/L1 首屏延迟；
- L2 建议完成延迟；
- Solver/Agent P50/P95；
- 缓存命中率；
- 超时后牌局继续率。

### 策略诚实性

- 有来源策略覆盖率；
- 启发式、curated、solver 和 agent 的正确标识率；
- Range Belief 可用率及 stalled reason 分布；
- 无未来信息泄漏；
- 无隐藏牌泄漏给机器人。

### 学习效果

- 用户在无提示模式下的策略偏差变化；
- 同类错误复发率变化；
- 提示依赖度变化；
- 概念练习掌握率；
- 从牌局错误到练习生成的覆盖率。

## 14. 需要后续确认的产品决策

- 首发主桌型选择 6-max 还是 8-max；
- 首发现金桌参数：100BB、ante、rake 和 blind 结构；
- 顾问默认采用全辅助、提示还是考试模式；
- AI 等级与玩家画像是否分为两个独立维度；
- 第一批需要完整覆盖的翻前行动树；
- 多人翻后节点中，哪些结果允许启发式，哪些必须明确 unavailable；
- 学习资料结构化的版权、来源和版本管理方式；
- 用户是否可以创建并分享机器人画像和 Agent provider。

## 15. 一句话定义

> Riverline 是一个能够观察用户决策、实时重建数学与范围依据、比较替代行动，并把每一次错误转化为后续训练任务的德州扑克认知模拟器。
