# 可观测德州扑克认知模拟器领域上下文

本上下文定义持续牌局、复盘、分析证据和教学之间共享的语言。它约束产品如何区分牌局事实、权限视图、估计、决策和解释。

## 持续模拟

**Game Session**：同一张牌桌上按按钮与筹码连续推进的多手牌集合。一手牌结束不会结束 Game Session。
_Avoid_：Scenario、单手牌

**Table Seat**：Game Session 中稳定编号的牌桌位置；即使暂离或筹码为零，该位置仍属于 session。
_Avoid_：player index、临时参与者编号

**Hand Participant**：某一手实际获得底牌并可按规则行动的 Table Seat；它是该手参与集合，不改变 Table Seat 的稳定编号。
_Avoid_：player index、重编号 seat

**Hand Event**：一手牌中已经发生且不可回写的有序事实。状态、统计和复盘可从 Hand Event 重建。
_Avoid_：UI event、页面状态、快照

**Hand Projection**：从 Hand Event 派生、可丢弃并重建的特定用途读模型，例如当前状态、统计或复盘摘要。
_Avoid_：牌局事实副本

**Observation**：某个正在行动的 seat 在一个决策点被允许知道的信息；它包含自己的底牌与公共事实，不包含其他玩家底牌或内部推断。
_Avoid_：完整牌局状态、omniscient state

**Legal Action**：规则权威在当前决策点允许的行动及其明确金额语义和边界。All-in 是 Bet 或 Raise 的边界情况，不是独立的第六种行动。
_Avoid_：建议行动、按钮配置

**Bot Decision**：Bot 针对一个 Observation 选择的行动，连同来源、耗时、置信度和降级来源。它不是策略真值或 Hero 建议。
_Avoid_：Advisor result、Solver answer

**Decision Advisor**：面向 Hero 分层提供数学、范围估计、候选行动比较和来源解释的能力。它不替 Hero/Bot 执行动作，也不裁决规则。
_Avoid_：万能 Solver、Bot

**Range Belief**：在一个时间点对某 seat 可能持有的具体两张牌组合所做的有来源估计。它不是该 seat 的真实底牌，也不是联合范围的精确真值。
_Avoid_：Range truth、known range

## 场景与证据

**ScenarioSpec**：Hand Lab 或复盘边界中的一个待重放/分析决策场景，包含牌局事实、行动历史、范围和分析假设。它不是持续 Game Session 或 Hand Event 日志。

**Decision Point**：行动历史之后、某位玩家拥有行动权的分析节点；它不是用户问题本身，也不是策略推荐。

**EvidenceBundle**：由规则事实、公式结果、牌力识别、范围计算和策略来源组成的可追溯事实集合。教学回答只能引用其中的证据。

**Source Level**：证据的来源等级，包括 deterministic、enumerated、simulated、curated、solver_backed 和 principle_only；来源等级描述证据如何得到，不代表策略强弱。

## 牌局分析

**Equity**：在给定双方具体牌或加权范围、已知牌和剩余牌分布下，某方赢牌或平分底池的摊牌份额。Equity 不等于 EV，也不自动等于最优行动。

**Out**：在指定当前牌面和对手假设下，能让手牌达到目标结果的一张未知牌。Out 必须说明目标和假设，不能把所有改善牌都默认为干净出路。

**Draw**：尚未完成、但存在一个或多个改进路径的牌力状态，例如 flush draw、open-ended straight draw 或 combo draw。

**Board Texture**：对公共牌结构的描述，包括花色分布、对子、连通性、高低牌和潜在坚果牌变化；它是结构标签，不是 Solver 结论。

**Combo**：一个具体的两张底牌组合。组合数先经过已知牌过滤，再根据权重参与范围和 Equity 计算。

**Range Advantage**：双方范围在给定牌面上的整体权益或强牌分布差异。除非有明确计算证据，否则只能标记为启发式。

**SPR**：有效筹码除以当前底池的比值；它是筹码结构指标，不是行动推荐。

## 策略与教学

**Principle Teaching**：只基于规则、数学或扑克概念的解释。它可以说明为什么某条线路合理，但不能声称拥有 Solver 频率或精确 GTO 结论。

**Teaching Depth**：教学输出的解释层级（beginner、intermediate、advanced）；它只改变表达和可展示的证据层次，不改变牌局事实或计算结果。

**Teaching Tool Gateway**：教学编排读取标准化场景、合法动作、EvidenceBundle、范围、策略匹配和术语的只读边界；创建练习必须重新经过验证服务。

**Strategy Artifact**：带有规则、范围、下注树、来源、许可证和版本元数据的可引用策略条目。它可以是人工策划或 Solver 产物，来源等级必须随条目保存。

**Strategy Match**：场景与 Strategy Artifact 的匹配结果，包含匹配等级、相似度和差异。`approximate` 或 `no_match` 不得继承行动频率。

**Validated Practice**：绑定到具体场景版本、EvidenceBundle 和验证答案的练习题；自由生成的题面不是事实来源。

**Learning Profile**：匿名用户在错误标签、概念进度和练习表现上的可删除学习记录，不是牌局事实或策略证据。

**Mistake Tag**：对一次练习或复盘中可复用的决策偏差分类，例如 pot odds、SPR、下注尺度或 blocker；它描述学习主题，不改写牌局事实。
