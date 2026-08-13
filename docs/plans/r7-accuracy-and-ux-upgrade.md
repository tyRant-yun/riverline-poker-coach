# R7 决策精度与交互重构计划

## 基线与暂停条件

- 冻结产品基线：`154cbc50f333d003ae7982c587d327d62e857378`。
- R6 发布门暂停；在 Advisor 可用性、Hero 布局、Range/Solver 同屏和 Solver 精度门关闭前不合并 `main`。
- 当前事实：L1 是 uniform-opponent、one-street showdown EV 近似；Range 是首方启发式独立边际分布；两者都不能称为 GTO/Nash。

## 产品目标

R7 将“牌桌能运行”提升为“决策过程可读、建议可信、信息可比较”：

1. Hero 座位严格位于牌桌水平正中，Hero 手牌成为第一视觉焦点。
2. 提高卡牌尺寸、文字/控件对比度和状态层级。
3. Advisor 永远在 Hero 合法决策点提供即时、诚实的 L0 建议。
4. Range 与 Solver 在桌面端同时可见，无需切换 Tab。
5. Solver 从 uniform one-street 近似升级为 range-aware、多 sizing、带响应分支和置信区间的 Fast EV L1.5。
6. 对支持的 heads-up river spot 提供 CFR/DCFR L2 oracle；其余 6-max spot 明确降级而不伪装成精确 GTO。

## 新界面信息架构

### 牌桌布局

- Hero anchor 固定为桌面 `x=50%`，视觉中心误差不超过 8px。
- 1366px 及以上：Hero 卡牌建议 `72×100px`，对手公开牌 `48×68px`；用 `clamp()` 在目标分辨率间平滑调整。
- Pot 位于 Board 上方独立区域；与任意座位、卡牌、筹码保持至少 16px 间距。
- Hero 操作区放在 Hero 手牌正下方，不用全宽大容器挤压牌桌。
- 牌桌占可用宽度约 68–72%，分析区约 28–32%。

### Range 与 Solver 同屏

- 右侧改为可调整的双层分析栏，而不是互斥 Tabs：
  - 上半部：Range 概览、座位选择、169 热力图。
  - 下半部：Solver 行动 EV、equity、置信区间、耗时和限制。
- Advisor 不再占独立 Tab；常驻 Hero Action Dock 顶部，展示即时 L0 推荐和来源。
- Stats/详细 provenance 移入抽屉，不占用实时决策的主视区。
- 在 1280×720 空间不足时允许折叠详情，但 Range 摘要与 Solver 推荐仍须同时可见。

### 色彩与可访问性

- 背景：深炭黑/石墨；桌面：低饱和墨绿；牌面：暖象牙。
- 文字正文对比度目标 `≥4.5:1`；大字、边框和交互控件 `≥3:1`。
- 金色仅用于 Pot、筹码和当前行动；青蓝用于分析；珊瑚用于负 EV/风险。
- 不以颜色单独表达正负 EV、可用性或当前行动，必须同时提供图标/文字/形状。

## 决策引擎分层

### L0：Always-on Advisor

- 每个 Hero active decision 必须返回 `ready` 或明确的 `degraded` fallback；不得显示空白“不可用”。
- 输入仅为 Hero 私牌、公开牌局事实与合法行动。
- 输出：推荐行动、最小解释、pot odds/equity threshold、来源与限制。
- 目标：本地 p95 < 20ms；L1/L2 失败不能影响 L0 或出牌。
- 若 L0 与 Solver 不一致，同时显示分歧及原因，不能隐藏其中之一。

### L1.5：Range-aware Fast EV

替换当前 uniform-opponent、legal-min-only 模型：

1. 使用 R6-02 内部 1,326 combo belief，而非 UI 的 169 聚合结果进行条件采样。
2. 对每个对手按其公开前缀 range 加权采样，并执行 card removal；不读取真实对手私牌。
3. 评估所有产品允许的 sizing，而非只评估合法最小值。
4. 对 bet/raise 建立一层响应树：fold/call/raise 概率由 continuation range、位置、SPR、街道和 sizing 估计。
5. Call/check 分支模拟剩余 runout；turn/river 可做精确枚举或分层采样。
6. 输出 EV、equity、fold equity、样本数、effective sample size、置信区间和模型版本。
7. 使用 decision fingerprint 决定随机种子，保证同一节点稳定；提高预算只缩小置信区间，不导致 UI 随机跳动。

交互预算建议：

- quick：50ms，先给方向。
- standard：150ms，默认桌面体验。
- deep：500–1500ms，复盘页异步刷新。

### L2：受限 CFR/DCFR Oracle

- 第一阶段仅支持 heads-up river subgame，输入双方 range、pot、stack、board 和有限 sizing tree。
- 在线结果可缓存；不支持的 multiway/preflop/flop/turn spot 返回 `unsupported`，继续使用 L1.5。
- L2 用于：河牌建议、L1.5 校准、回归 oracle、复盘深算；不阻塞实时行动。
- 未来扩展到 HU turn/flop 前，必须先证明内存、收敛和 exploitability/benchmark 指标。

## Range V2

- 内部保留 1,326 combo 权重；UI 继续使用 169-cell 聚合。
- prior 按 position/profile/effective stack/limpers/raise sequence 版本化。
- 每次公开 action 使用似然更新：size bucket、street、position、SPR、made-hand/draw features。
- Board 和 Hero blockers 将不可能 combo 权重严格归零，然后重新归一化。
- 输出 range width、top classes、变化原因、置信度、近似标记和数据版本。
- 摊牌公开牌只用于终局展示/复盘真值对照，绝不回填此前 Hero 所见 belief。
- 性能目标：6-max 当前 decision 完整更新 median < 25ms、p95 < 50ms；当前 41.440ms median 是必须处理的性能债。

## 公开方案采用边界

| 项目 | 许可证/覆盖 | R7 用法 | 不采用方式 |
|---|---|---|---|
| [PH Evaluator](https://github.com/HenryRLee/PokerHandEvaluator) | Apache-2.0；高性能 5/6/7-card evaluator | 先做 evaluator spike；若一致性和 Windows wheel 通过，用于大规模 equity/runout 评估 | 不替代 PokerKit 规则权威 |
| [noambrown/poker_solver](https://github.com/noambrown/poker_solver) | MIT；NLHE river CFR/CFR+/MCCFR/DCFR | 作为 HU river L2 sidecar 候选和测试 oracle | 不宣称覆盖 6-max 或多街 |
| [Slumbot2019](https://github.com/ericgjackson/slumbot2019) | MIT；CFR+/MCCFR、抽象、endgame、有限 multiplayer | 离线 MCCFR/抽象研究与策略生成 spike | 不直接塞进实时 Python 请求链 |
| [OpenSpiel](https://github.com/google-deepmind/open_spiel) | Apache-2.0；2–10 player ACPC Hold'em、CFR 等研究框架 | Kuhn/Leduc/小型 Hold'em 的算法正确性、收敛和 exploitability 回归 | 不在完整 6-max NLHE 树上在线跑通用 CFR |
| [PokerRL](https://github.com/EricSteinberger/PokerRL) | MIT；Deep CFR/NFSP 研究框架 | 参考训练/评估边界与 offline agent contract | 不直接引入旧 Python/Ray/二进制栈 |
| TexasSolver | AGPL-3.0；主要为 postflop solver | 可独立研究与结果交叉验证 | 不进入未来 SaaS 核心依赖或部署镜像 |

## 质量门

### UI

- Hero 中心偏差 ≤8px；目标视口 Pot/Board/seat/dock/rail 无重叠。
- Hero 牌在 1366×768 不小于 72×100px。
- Range 摘要与 Solver 推荐在 1366×768 同时可见。
- 对比度自动检查达到 WCAG AA 目标。
- Bot 播放、摊牌、下一手和重连不出现旧状态闪回。

### Advisor

- 所有 fixture 中的 Hero legal decision 均有 ready/degraded 结果。
- 推荐 action/amount 100% 属于 legal actions。
- endpoint 异常、超时、Range unavailable 时 fallback 仍可用。

### Solver

- 卡牌唯一性、range 条件采样、decision seed 可复现、私牌 poison tests 全部通过。
- River equity 与精确枚举的 MAE 目标 <1.0 个百分点。
- 支持的 HU river spot 与 L2 oracle 最优行动一致率目标 ≥80%；不一致必须能解释为 sizing tree/迭代/抽象差异。
- Standard 模式 p50 <150ms、p95 <300ms；超时返回 partial/degraded，不阻塞操作。

### Range

- 每座位权重归一化；blocked/impossible combos 为 0。
- 改变真实对手私牌、RNG、terminal/payout 不改变同一公开前缀 belief。
- 公开行动必须产生可解释、方向正确的 change reason。
- 6-max 更新 median <25ms、p95 <50ms。

## 任务与依赖

### R7-01 UI Geometry + Contrast

- Hero 正中、放大牌面、对比度 tokens、Range/Solver 双层同屏、Advisor 常驻 Hero dock。
- 仅前端视觉/布局；不修改决策算法。
- 使用 Terra medium；截图和几何/a11y focused tests，无独立代码审查。

### R7-02 Advisor Reliability

- 修复 Advisor unavailable，建立 always-on ready/degraded contract 和 fallback。
- 后端/API 为主；只在集成阶段接 UI。
- Terra medium；focused API/合法行动测试。

### R7-03 Evaluator + Oracle Spikes

- PH Evaluator 一致性/性能/安装 spike。
- noambrown river solver 的 JSON contract、构建、收敛与许可证 spike。
- OpenSpiel 小博弈 CFR conformance harness。
- 文档/benchmark 交付，不先改变生产默认路径。

### R7-04 Range V2 Core

- 1,326 combo 内部模型、公开行动似然、缓存/向量化、性能优化。
- 依赖 R7-03 evaluator 结论；Sol high，仅做可见独立隐私审查。

### R7-05 Fast Solver L1.5

- range-aware multiway sampling、多 sizing、一层响应树、置信区间、三档预算。
- 依赖 R7-04；Sol high，需可见合法动作/金额/私牌/性能审查。

### R7-06 River CFR L2

- 先以 MIT river solver sidecar/独立进程实现 HU river；提供 unsupported/fallback。
- 不阻塞 R7 MVP，可在 L1.5 达标后并行作为精度增强。

### R7-07 Product Integration + Eval

- 把 Advisor、Range V2、L1.5/L2 接入新同屏布局。
- 完成真实两手浏览器体验、决策对比、延迟和隐私门。

### R7-08 Release Gate

- 一次完整 backend/frontend/E2E/source-license 门；更新 PR 后合并 `main`。

## 建议执行顺序

1. 并行启动 R7-01（纯前端）与 R7-02（Advisor backend）。
2. R7-02 完成后使用第二槽执行 R7-03 spikes。
3. 串行完成高风险 R7-04 → R7-05；R7-06 可在 L1.5 稳定后并行。
4. R7-07 集成并进行用户体验验证。
5. R7-08 发布。

此顺序先恢复可读性与 Advisor，再提升 Range/Solver 精度；避免在算法仍变化时反复改同一 UI 接线。
