# R8 决策驾驶舱与 Range Explorer 重构计划

## 结论

当前 R7 已经证明 Advisor、Range V2 与 Solver L1.5 能在真实牌局中稳定返回，但还没有达到“用户能据此做决定”的产品标准。下一阶段不应继续把更多原始数字塞进右栏，而应先建立统一的决策叙事：**现在该做什么、两个模型是否一致、差异有多大、为什么、结论有多可靠**。

本计划先约束视觉和交互，不在本阶段假装解决 Solver 模型精度。算法与视觉拆开验收：前端必须诚实呈现已有结果；Advisor/Solver 一致性和 sizing 质量另设后端评估门。

## 待办分析

### P1：Advisor 与 Solver EV 背离

现象：Advisor 给出规则/公式建议，Solver 给出另一行动或尺度，但界面同时将两者表现为“推荐”，没有解释各自目标、置信度及冲突原因。

风险：用户无法判断应该相信哪一个；即使两个模块单独计算正确，组合后的产品表达仍然是错误的。

分析待办：

- 建立同一决策节点的 Advisor/Solver 对照数据集，记录 action、amount、EV、CI、输入 fingerprint 与降级状态。
- 将分歧分类为：阈值附近、sizing 集不同、fold-equity 假设、range 输入、multiway 近似、预算不足或实现错误。
- 冻结冲突展示规则：不得静默覆盖其中一个结果，也不得在没有证据时自动声称某方更准确。
- 后续定义产品级“最终建议”仲裁契约；在此之前 UI 使用“规则基线”和“模拟估计”，不使用两个并列的“推荐”。

### P1：Solver 尺度极端且难以解释

现象：界面直接展示原始筹码值、过多小数和极端 bet/jam 候选。用户看不到尺度相对底池、SPR、EV 优势是否稳健，也无法区分明显最优和置信区间重叠。

风险：合法尺度不等于合理尺度；粗粒度响应模型可能把极端下注高估，视觉上的高精度数字会放大错误信心。

分析待办：

- 建立 sizing 回归集，覆盖 33/50/66/75/100% pot、overbet、jam 与不同 SPR。
- 检查 EV 的筹码口径、RAISE TO/增量成本、fold/call/raise response mix 和 all-in 边界。
- 对比相邻尺度的 `ΔEV` 与 CI；极端尺度只有在优势超过不确定性时才允许成为强推荐。
- 评估 Advisor/Solver 在同一合法 sizing 集上运行，避免“Advisor 比动作、Solver 比另一组尺度”的伪冲突。

### P1：Range 表无法辅助决策

现象：169 格被压缩为小字墙，单元格权重、颜色图例、变化方向和座位身份不可快速读取；原始 provenance 字符串占据视觉空间，并出现横向与纵向嵌套滚动。

风险：Range 虽然有数据，但用户无法回答“对手现在偏强还是偏弱、哪些牌增加了、为何变化、我该如何利用”。

分析待办：

- 用用户任务验证 Range：5 秒内能否判断宽/窄、价值/听牌/空气构成、最近行动造成的主要变化。
- 评估 169 聚合对 postflop draw/blocker 表达的损失；需要时增加后端派生的 hand-class breakdown，不能由前端伪造 suit-level 结论。
- 冻结颜色比例、绝对权重/相对热度口径、空格/blocked 状态和变化图例。
- 增加 seat、street、action-prefix identity，避免用户误读上一决策或其他座位的 Range。

### P1：Bot 行动缺少座位级反馈与可感知节奏

现象：虽然系统存在 Bot playback，用户仍难以感知“哪个 Bot 正在行动、思考多久、最终做了什么”。动作历史与顶部状态离牌桌座位过远，多个 Bot 连续行动时容易被视觉上压缩成一次桌面跳变。

风险：用户无法阅读行动顺序，也无法把下注、位置和 Range 变化建立联系；过快的动作还会使 Solver/Range 更新看起来像随机跳动。

分析待办：

- 核对从 Hero 动作到下一 Hero decision 的公开事件序列，确认 playback 没有被最终 snapshot 一次性覆盖。
- 测量每个 Bot 动作的实际屏幕停留时间，而不是只检查代码中是否存在 timeout。
- 将动作反馈绑定 seat ID、hand ID、decision fingerprint 与事件序号；重连、下一手或旧请求返回时必须取消旧播放。
- 冻结三档节奏：舒适、快速、即时；默认应让普通用户无需查看历史即可复述行动顺序。
- 延迟只存在于前端展示队列，不在规则引擎、Bot provider、API 或持久化链加入 `sleep`。

## 新的信息架构：Decision Cockpit

桌面端改为 `牌桌 + 决策驾驶舱`，而不是“牌桌旁堆两个调试面板”。

### 1. 顶部：Decision Summary

始终位于 Hero 操作区上方，回答四个问题：

1. 当前动作：`轮到 Hero · Flop · Pot 850 · SPR 11.2`。
2. 规则基线：`Advisor：过牌`。
3. 模拟估计：`Solver：下注 66% pot（560）`。
4. 一致性：`存在分歧`，并显示已知原因或“原因尚未确定”。

禁止显示十几位小数、内部枚举名和未经本地化的 provenance。数值默认规则：筹码取整数、pot 比例取整数百分比、EV/ΔEV 最多一位小数、equity/CI 最多一位百分比。

### 2. 牌桌座位：Bot Action Narrative

每个 Bot 的公开行为直接显示在其座位附近，而不是只写入页面底部历史：

- 思考阶段：座位边框轻微呼吸，并显示 `Bot 3 思考中…`；不使用不断旋转的高干扰 loading。
- 动作阶段：座位上方显示动作胶囊，例如 `过牌`、`跟注 100`、`下注 66% · 560`、`加注至 1,800`、`全压`、`弃牌`。
- 当前行动座位使用清晰高亮；动作完成后胶囊保持一段可读时间，再淡出为该街最近动作的小标签。
- 金额变化、筹码移动和 Pot 更新应与该动作同一节拍发生；若现有 DTO 不支持可信的中间筹码状态，只动画公开动作胶囊，不伪造 stack/pot 过渡。
- Range 更新在对应动作胶囊出现后发生，并短暂标记 `Range 已根据该动作更新`，让用户建立因果关系。
- 行动历史保留为辅助时间线，但不再承担“当前发生了什么”的主要职责。

建议默认节奏：

| 阶段 | 舒适（默认） | 快速 | 即时 |
|---|---:|---:|---:|
| 首个 Bot 思考提示 | 450–650ms | 200–300ms | 0ms |
| 动作胶囊最短可读时间 | 750–950ms | 350–500ms | 0ms |
| 座位间过渡 | 150–250ms | 80–120ms | 0ms |
| 连续链最大等待 | 5s | 2.5s | 0s |

默认单个 Bot 动作约 1.0–1.4 秒。连续行动时提供 `跳过播放`，但不能跳过或改写权威事件；切回浏览器后台后可以安全快进到最新决策。`prefers-reduced-motion` 关闭位移/呼吸动画，但仍保留动作文字和最短阅读时间。

### 3. 中部：Solver Action Ladder

每个候选动作使用一行可比较卡片：

```text
下注 66% pot · 560     ΔEV 0.0     EV +1.8 BB     置信度：中
过牌                   ΔEV -0.2    EV +1.6 BB     与最佳接近
全压 · 1,118% pot      ΔEV -4.7    EV -2.9 BB     高风险尺度
```

表现规则：

- 默认按 `ΔEV` 排序，不按原始 action 顺序。
- 使用共同零点的 EV 条带；颜色之外同时显示正负符号、标签和排序。
- CI 重叠时标记“接近”，不得制造唯一精确最优的假象。
- `jam` 显示为“全压”，同时显示 pot% 和有效筹码；不把 `10350` 作为主要标签。
- 极端尺度增加 `高风险尺度` 标识，并展开显示 SPR、fold/call/raise mix 和模型限制。
- 首屏只显示前三个候选；其余进入“全部尺度”。
- 执行下注的 Action Dock 与分析卡保持视觉分离，避免误点击。

### 4. 下部：Why / Reliability

使用短句解释，而不是日志：

- `Hero equity 60.9%，高于当前跟注阈值。`
- `模型估计该尺度获得约 23.8% fold。`
- `多方底池、单层响应树；结果为 coarse。`
- `256 samples · ESS 256 · 199ms` 放入次级元数据行。

若 Advisor 与 Solver 冲突，展开卡按证据列出：输入 Range 是否可用、Solver 是否 degraded、CI 是否重叠、两者是否比较相同动作/尺度。没有结构化原因时显示“尚不能解释”，不能由前端猜测。

## Range Explorer

### 默认摘要，而非默认矩阵

驾驶舱首屏显示当前座位的 Range Summary：

- 座位与位置：`Bot 3 · UTG`。
- 宽度：`21.3% · 约 283 weighted combos`，避免把 1,025 个非零 combo 误当成有效宽度。
- 置信度与来源：`低/中/高 · 公开行动启发式`。
- 最近变化：本地化为 `Flop 过牌后，中等强度牌与听牌权重上升`。
- Top classes 与 Top movers：显示增加/减少最大的 3–5 类，并给出 delta。

只有用户点击“展开矩阵”时显示完整 13×13 Explorer。

### 169 矩阵规范

- 展开宽度至少 520px；桌面单元格建议 `28–34px`，禁止横向滚动。
- 对角线为对子、右上为同花、左下为非同花；固定轴标签和清晰图例。
- 单元格主视觉为权重强度，文字只显示牌类；hover/focus 才显示精确权重、combo 数、delta、blocked 数与变化原因。
- 提供 `当前权重 / 相对上一行动变化` 两种模式；变化模式用增减符号和发散色阶。
- 支持快速过滤：Pairs、Suited、Offsuit、Top range、增加、减少、Blocked。
- 颜色必须有感知均匀的 5–7 档，并通过文本/纹理表达 blocked、unknown、low-confidence，不能只靠绿色深浅。
- 切换座位时立即清空旧矩阵并显示 skeleton；响应必须匹配 session/hand/decision fingerprint/seat。

### Postflop 决策摘要

169 格不足以直接解释 postflop。后续数据契约应由后端提供经过 1,326 combo 计算的聚合，而不是前端从 169 格猜测：

- Made hand：strong / medium / weak。
- Draw：flush draw / OESD / gutshot / combo draw。
- Overcards / air。
- Equity buckets 与 blocker effect。
- 每个 bucket 的当前权重和相对上一公开行动的变化。

首阶段若后端未提供这些字段，UI 明确显示“构成分析尚不可用”，不使用模拟数据填充。

## 视觉系统调整

- 驾驶舱宽度使用 `clamp(440px, 30vw, 600px)`；牌桌保留剩余空间，1366px 以下切为底部抽屉。
- 页面只允许一个纵向主滚动；驾驶舱和矩阵不得同时出现横向/纵向嵌套滚动条。
- 牌桌继续使用低饱和墨绿；分析面板改为中性石墨/深蓝灰，避免 Range 与桌布融为一体。
- 主正文最小 14px，关键动作 20–24px，辅助元数据最小 12px；牌类矩阵使用高可读窄体但不小于 11px。
- 金色只表示筹码/Pot/Hero 焦点；青色表示模型信息；绿色表示正向证据；珊瑚表示负 EV/风险；任何状态都附带文字或图标。
- 删除面向开发者的内部字符串、超长浮点数和未本地化枚举；详细 provenance 放入可复制的“模型详情”抽屉。

## 数据契约边界

### 前端可立即从现有数据计算

- amount chips → pot% / BB / jam 标签。
- 候选 EV → `ΔEV`、排序和接近区间。
- response mix → fold/call/raise 简图。
- Range 169 权重 → 热力图、宽度、top classes 和 seat 切换。
- status/provenance → ready/degraded/coarse 的本地化标签。

### 需要后端新增或校准

- Advisor/Solver disagreement reason codes。
- 稳健推荐所需的 candidate CI/overlap 与 sizing robustness。
- Range action-to-action delta 的稳定 identity。
- 由 1,326 combo 推导的 postflop hand/draw/equity buckets。
- 极端 sizing 的产品约束和校准结果。

在这些字段到位前，前端只展示可验证事实，不自行推导模型原因。

## 分阶段实施

### R8-01 Decision Cockpit Shell

- 重排右栏、Summary、Solver Action Ladder、数字格式与单滚动容器。
- 增加座位级 Bot 思考/动作胶囊、三档节奏、跳过播放和 reduced-motion 模式。
- 只使用现有 DTO；不修改 Solver/Range 算法。
- 产出 1920×1080、1440×900、1366×768、1280×720 四视口截图与几何测试。

### R8-02 Range Explorer

- 座位选择、摘要、可展开 169 矩阵、图例、tooltip、当前/变化模式。
- 先支持已有权重；缺少 delta/bucket 时诚实降级。
- 验证 blocked、低置信度、切换座位和旧响应隔离。

### R8-03 Decision Reconciliation Contract

- 后端建立 Advisor/Solver 对照、分歧分类、CI overlap 和 sizing robustness。
- 前端接入分歧说明与“接近最优”表达。
- 这是解决建议背离的产品门，不得由纯样式任务代替。

### R8-04 Solver Sizing Calibration

- 使用冻结 spot 集校准极端尺度、response mix、SPR 与相邻 sizing EV。
- 只有通过金额、oracle、单调性与稳定性测试的尺度才能获得“推荐”视觉等级。

### R8-05 Product Evaluation

- 完成真实两手体验、旧异步响应、隐私、键盘操作和四视口门。
- 邀请用户完成三个 5 秒任务：找到推荐动作、识别模型分歧、解释某座位 Range 的主要变化。

## MVP 验收标准

- 1366×768 无水平滚动；Hero 操作、Decision Summary、Solver 前三候选与 Range Summary 同屏可见。
- 用户在 5 秒内可以回答：Advisor 建议、Solver 最优候选、两者是否冲突。
- Solver 不显示超过一位小数的 EV/概率；所有下注同时显示动作名、pot% 与筹码。
- CI 重叠的候选显示“接近”，极端尺度显示风险标签和模型限制。
- 用户无需阅读 169 格即可理解 Range 宽度、置信度、主要构成与最近变化。
- 展开矩阵无横向滚动，具备图例、tooltip、当前/变化模式和完整键盘焦点。
- 页面不显示内部枚举、原始 provenance token 或超长浮点数。
- Advisor、Range 或 Solver 任一 degraded/unavailable 时，其余模块仍可独立使用，且旧决策结果不会残留。
- 每个 Bot 的 actor、action 与 amount 在对应座位附近至少保持默认 750ms；用户不查看历史也能复述连续行动顺序。
- Bot playback 严格按公开事件序号播放；下一手、重连、跳过或浏览器后台快进不会留下旧动作胶囊。
- 最后一个 Bot 动作结束后 200ms 内恢复 Hero 控件；播放延迟不进入 API、规则、持久化或 Solver 请求耗时。

## 明确排除

- 本计划不把 Solver L1.5 宣称为 GTO/Nash/CFR。
- 不在纯前端任务中修改 EV、response model、range likelihood 或最终推荐仲裁。
- 不为改善截图伪造 Range bucket、置信度、分歧原因或 Solver 精度。
- 不恢复已删除的旧 Scenario Builder/Workbench 产品表面。
