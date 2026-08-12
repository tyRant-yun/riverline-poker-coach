# ADR-0010：Projection recovery 与 transactional outbox 共用权威数据库边界

状态：已接受
日期：2026-08-12

## 上下文

`HandEventV1` 已是不可变事实，但异步 projection 和外部任务会在事件提交、读模型写入、checkpoint 推进、外部副作用确认之间失败。若 snapshot 被当成事实，或 event 与任务 intent 分别提交，重启后会出现不可重建读模型、丢任务或重复副作用。仅用进程内 offset 也无法证明失败事件不会被跳过。

## 决策

- Projection identity 固定为 `(projection_name, projection_version)`；每个 event stream 维护独立 durable checkpoint。
- 一次 projection apply 在同一数据库事务中先写可丢弃 snapshot/read model，再推进 checkpoint。失败不推进 cursor；坏版本使用新 identity 或清空旧版本后仅从 `HandEventV1` 重建。
- `HandEventStore.append(..., outbox_intents=())` 是 F1-02 port 的兼容扩展。每个 V1 intent 必须用 `source_event_id` 绑定本次 append batch 内的事实事件；outbox row 以外键保留该关联。非空 intent 与整批 events 在 SQLite/PostgreSQL 的同一 append 事务提交，原有调用默认不写 outbox。
- Outbox 使用 deterministic `message_id` 与 `idempotency_key`、`pending -> processing -> dispatched` 状态、租约、不可复用 `claim_token`、attempt count 和失败后 `available_at` 重试。ack/retry 必须同时匹配 processing 状态、owner、token 和未过期 lease；lease 是否仍有效以及 retry 的下一次可用时间都以 persistence adapter 的当前 UTC 时钟为准，不能复用 dispatcher 在 claim 时传入的旧时间。PostgreSQL claim 使用 `FOR UPDATE SKIP LOCKED`，SQLite 使用 `BEGIN IMMEDIATE`。
- 持久化 outbox message 与 projection snapshot 的 V1 reader 必须先校验 `schema_version`；未知版本以项目领域错误拒绝，不能默认为 V1。
- Dispatch 是 at-least-once。外部 consumer 必须以同一个 `idempotency_key` 去重；数据库不能在外部副作用已发生但确认未写回时单独承诺 exactly-once。

## 后果

- Snapshot/cache 与 checkpoint 都不是事实源，删除后仍必须仅靠 durable events 得到相同 fingerprint/read model。
- Projection schema 或逻辑变化发布新 projector version，不回写历史事件。
- Event uniqueness、expected-sequence 和 outbox uniqueness 仍由同一事务内的数据库约束裁决；adapter 不绕开冲突。
- F1-04 V1 尚未集成，因此直接修正错误的 intent/claim seam，不为缺少 `source_event_id` 或 `claim_token` 的未发布形态保留兼容读取。
- 应用回滚保留 `hand_events`、projection 与 outbox 表。Alembic downgrade 会删 recovery 数据，只允许在明确的数据销毁流程中使用。
- Live PostgreSQL 证据必须来自真实 URL；fake DB-API/离线 SQL 只能称 adapter/SQL 契约证据。
