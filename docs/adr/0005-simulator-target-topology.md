# ADR-0005：模拟器目标拓扑采用模块化单体与端口/适配器

状态：已接受
日期：2026-08-12

## 上下文

Riverline 正从以 `ScenarioSpec` 为入口的 Hand Lab 演进为持续对战、实时顾问、自动复盘和长期训练的一体化产品。连续牌局、Bot/Agent、Advisor、Range Belief、Solver artifact 和学习投影有不同故障/延迟/权限边界，但当前团队和部署规模不足以承担微服务分布式一致性；同时 PokerKit 必须继续是唯一规则真相。

## 决策

采用模块化单体：`GameSession/GameOrchestrator`、规则适配、事件追加、Bot runtime、Advisor、Range Belief、Review/Learning 和投影各自拥有明确模块边界，只通过版本化端口交换项目自有 contract。PokerKit 只在规则 adapter 内；PHH 只在 hand import/export adapter；外部 Agent、可选 evaluator 和离线 solver producer 都位于可移除 adapter 后。第一产品模式固定为 6-max、100BB、no-ante、no-rake，底层 seat/event contract 保留 2–8 人通用性。现有 Hand Lab 与已通过的 E2E hooks 作为迁移期间的受保护能力。

## 备选方案

- 立即拆分微服务：能强化部署隔离，但会过早引入网络契约、分布式事务、追踪和运维成本。
- 继续把实时桌状态扩进现有文档式页面/API：短期改动少，但会混淆牌局事实、展示状态和异步结果所有权。
- 引入 RLCard/OpenSpiel/PettingZoo 等第二规则内核：有利研究，却会产生冲突规则真相。
- 将外部 Agent/Solver 直接链接到牌局循环：接线快，但其失败、许可和延迟会成为整桌故障。

## 后果

- 模块边界先于部署边界；将来只有在负载/故障证据充分时才把 adapter/worker 拆出进程。
- 所有跨模块值必须是 Riverline 自有、版本化 contract，上游库类型不得泄漏。
- 2–8 人 contract 不等于 8-max 产品或策略覆盖；发布门只评价已声明的 6-max 模式。
- 前端迁移采用新增桌面流 + Hand Lab bridge，不进行无关重写。
