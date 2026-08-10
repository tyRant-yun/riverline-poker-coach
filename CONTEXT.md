# 德州扑克策略教学领域上下文

本上下文定义牌局重放、分析证据和教学之间共享的语言。它约束产品如何描述事实、计算结果和不确定性。

## 场景与证据

**ScenarioSpec**：一个待重放或分析的 HU NLHE 决策场景，包含牌局事实、行动历史、范围和分析假设。

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
