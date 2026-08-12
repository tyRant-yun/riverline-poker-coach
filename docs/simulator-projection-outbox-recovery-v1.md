# Simulator projection and outbox recovery V1

Status: F1-04 frozen persistence/message contract

## Versioned contracts

All public recovery values are immutable project-owned V1 models. Python fields use snake_case; deterministic JSON uses camelCase and includes `schemaVersion: 1`. Compatible future fields require defaults; breaking meaning requires V2.

`ProjectionIdentityV1` is `(projection_name, projection_version)`. A checkpoint is additionally scoped by `stream_id` and stores the last successfully applied event sequence and ID. `OutboxIntentV1.for_event()` stores the bound `source_event_id`, derives `idempotency_key = "<event_id>:<purpose>"`, and derives a deterministic SHA-256-based `message_id`. This F1-04 V1 was not integrated before correction, so `source_event_id` is required rather than defaulted from an ambiguous old row.

## Projection processing

`ProjectionRunner` reads only `HandEventStore.read(stream_id)`. It skips events at or below the durable cursor, rejects gaps, calls the projector for exactly the next event, then asks the adapter to atomically write the new snapshot and checkpoint. Projector failure happens before that transaction. Adapter failure rolls both writes back. Therefore the cursor is monotonic and cannot pass a failed event.

The snapshot payload and SHA-256 fingerprint are a cache over an event prefix, not a second fact source. SQLite serializes applies with `BEGIN IMMEDIATE`; PostgreSQL takes a transaction advisory lock for the projector identity and stream before checking the cursor, including the initially absent-checkpoint case. `discard()` removes the selected projector version's snapshot and checkpoint. `rebuild()`/`run()` then starts at sequence 1 from the durable event stream. A checkpoint without its matching snapshot is rejected with `snapshot_missing` and requires rebuild; the runner never fabricates state from the cursor alone.

Projector versions coexist under separate keys. Replacing bad logic means writing a new version and rebuilding before switching readers, or explicitly discarding/rebuilding the old version. Historical `HandEventV1` bytes are never updated.

## Transactional append and outbox

The F1-02 append port has one backward-compatible optional parameter:

```python
append(hand_id=..., expected_sequence=..., events=..., outbox_intents=())
```

Before opening a transaction, both adapters require every intent's `source_event_id` to belong to an event in that exact append batch. Missing events, events from another hand, and events from an earlier append are rejected; the narrow rule prevents orphan intent creation. The outbox table also retains a foreign key to `hand_events(event_id)`.

SQLite keeps the expected-sequence check, all event inserts, and all intent inserts inside one `BEGIN IMMEDIATE` transaction. PostgreSQL keeps the per-hand advisory lock, expected-sequence check, event inserts, and intent inserts inside one transaction. Any event, sequence, `message_id`, `idempotency_key`, or source binding conflict rolls back the complete append. Empty `outbox_intents` preserves F1-02/F1-03 behavior.

## Claim, retry, and idempotent dispatch

The durable state machine is:

```text
pending --claim/attempt++--> processing --ack--> dispatched
   ^                              |
   +-------- failure/retry -------+
   +-------- expired lease -------+
```

Claims carry `claimed_by`, `lease_expires_at`, and a fresh random `claim_token`. SQLite serializes claim selection/update with `BEGIN IMMEDIATE`; PostgreSQL locks candidate rows with `FOR UPDATE SKIP LOCKED`. An expired processing lease becomes pending and may be reclaimed after restart. Acknowledge/retry must match the current processing row's owner and token and occur before lease expiry. The persistence adapter evaluates that expiry against its own current UTC clock, never against the dispatcher's earlier claim timestamp; retry availability is derived from the same storage-side time. A token is cleared on expiry, retry, or dispatch, so an old worker cannot acknowledge a later claim even when `worker_id` is reused.

`OutboxDispatcher` is deliberately at-least-once. It passes the durable `idempotency_key` to the dispatch boundary. If an external effect commits and its acknowledgement is lost, the message is delivered again. The external system/adapter must deduplicate that key; only this combined contract prevents duplicate external side effects. A consumer that ignores the key is outside the V1 guarantee.

Every persisted V1 outbox message and projection snapshot is hydrated only after reading and checking `schema_version == 1`. Unknown versions raise `unsupported_recovery_schema_version`; they are never silently interpreted as V1 and driver details are not exposed.

## Migration and evidence boundary

Alembic `0003` adds `projection_checkpoints`, `projection_snapshots`, and `outbox_messages` after `0002`. Application rollback retains these tables and disables workers; downgrade is destructive to recovery state.

SQLite behavior is exercised against real files for event-intent binding, duplicate delivery, failure before checkpoint, restart, rebuild, atomic append, concurrent claim, expired/ABA claim rejection (including dispatch that crosses lease expiry without a reclaim), unknown persisted versions, failed dispatch, and idempotent external retry. PostgreSQL has offline migration SQL and injected DB-API adapter contract tests for the same P1 contracts. Conditional live tests run only when `POKER_COACH_TEST_PG_URL` is configured; otherwise PostgreSQL remains explicitly not live-tested.

`OutboxIntentV1.payload` and `ProjectionSnapshotV1.payload` still use Pydantic-frozen models whose nested dictionaries are shallow-mutable. Deep-frozen JSON values are an explicit post-MVP backlog item; the three merge-blocking P1 persistence/recovery invariants do not depend on mutating these values after hydration.
