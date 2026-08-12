# ADR-0006：Hand Event 是事实，状态与读模型由投影重建

状态：已接受
日期：2026-08-12

## 上下文

连续牌局必须支持确定性恢复、审计、统计、复盘、belief、异步任务和迁移。只保存整页/整手快照会产生多个互相矛盾的事实副本；直接把 PHH 或 PokerKit 对象当内部存储又无法表达 Riverline provenance、Advisor 与学习事实，并把上游版本绑进持久化。

## 决策

采用版本化 append-only `HandEventV1` 作为一手牌的事实序列。每个事件有稳定 `eventId`、`handId`、连续 `sequence`、`schemaVersion`、带时区时间、source 和 provenance；持久层以 `(hand_id, sequence)` 与 `event_id` 唯一约束实现 expected-sequence append。PokerKit reducer 从合法初态顺序重放事件；规则状态、hand summary、VPIP/PFR/3Bet、review、telemetry 和 PHH 均为独立投影。快照只作可丢弃缓存，projection cursor/outbox 只作恢复机制。存储的 V1 事件不就地改写；新版本通过纯 upcaster 在读取边界转换。

## 备选方案

- 以最终状态 JSON 为事实：恢复快，但无法验证中间合法性、因果和纠错。
- 继续直接复用 `ScenarioSpec.actionHistory`：能兼容 Hand Lab，却缺少完整事件 envelope、session 生命周期和私有事实权限。
- 以 PHH 作为内部事件日志：交换性好，但无法承载 Riverline 内部 belief/advisor/learning provenance。
- 立即采用完整第三方 event-sourcing 框架：功能丰富，但在核心重构时扩大迁移和建模锁定。

## 后果

- 所有 projector 必须可幂等重放，重复消费不得重复计数；坏 projector 通过新版本重建而非改事件。
- 乱序、gap、重复 ID、completion 后事件和 PokerKit 结算不一致必须在 append/replay 边界失败。
- 私有事件可存在于权威日志，但 Observation/公开投影必须按权限过滤。
- F1 必须补持久化唯一约束、乐观追加、cursor/checkpoint、同事务 outbox、snapshot 与灾难恢复；F0 in-memory spike 不代表这些已完成。
