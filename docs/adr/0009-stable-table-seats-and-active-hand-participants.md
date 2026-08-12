# ADR-0009：V1 显式区分稳定 Table Seat 与 Hand Participant

状态：已接受
日期：2026-08-12

`HandStartedPayloadV1` 以带默认值的 `activeSeatIds` 兼容扩展记录本手参与者；旧 V1 缺少该字段时按全部 `startingStacks` seat 参与解释。`tableSize` 与 `startingStacks` 继续描述稳定 session 拓扑，所有事件继续使用稳定 Table Seat ID，规则适配器只在内部映射到稠密 player index。该方案遵守 V1 新字段必须有默认值的冻结规则，避免重编号造成跨手身份漂移；现阶段不发布破坏性 V2，因为旧事件可无歧义 upcast。后果是 replay、observation、统计和编排都必须显式区分 table seats 与 hand participants，且 active seat 必须严格递增、至少两个、属于 table 拓扑并拥有正 opening stack。
