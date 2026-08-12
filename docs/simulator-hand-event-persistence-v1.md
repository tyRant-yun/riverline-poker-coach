# Durable Hand Event persistence V1

Status: F1-02 append/read seam

This seam persists the frozen `HandEventV1` envelope. It does not validate
PokerKit rules, run a session orchestrator, update or delete events, build a
projection/outbox/snapshot, or convert PHH.

## Port semantics

`RawHandEventV1` binds a validated `HandEventV1` to the exact JSON string seen
at ingress. The two representations must describe the same envelope. Adapters
store the exact string in `raw_event_json`; reads parse and return that same
string, so key order, whitespace, `schemaVersion`, `source`, `provenance`, and
`payload` are not reconstructed from database-specific JSON types.

`HandEventStore.append(hand_id, expected_sequence, events)` defines
`expected_sequence` as the highest sequence the caller believes is already
durable before the transaction. A new hand uses `0`. A non-empty batch must:

- contain only the supplied `hand_id`;
- have unique event IDs within the batch;
- be ordered and contiguous from `expected_sequence + 1`.

The adapter compares the durable head with `expected_sequence` inside the same
transaction that inserts every event. Any mismatch or insert failure rolls the
whole batch back. `read(hand_id)` returns the stored events in ascending
sequence order. The port intentionally exposes no update or delete operation.

## Constraints and concurrency

The minimal shared schema stores envelope identity and indexed metadata as
ordinary columns, canonical provenance/payload JSON as text, and the original
envelope JSON as text. `pk_hand_events` makes `event_id` globally unique;
`uq_hand_events_hand_sequence` makes `(hand_id, sequence)` unique and supplies
the ordered-read index.

SQLite starts append transactions with `BEGIN IMMEDIATE`. This obtains the
database write reservation before reading the hand head, so two connections
using the same expected sequence cannot both pass the check. SQLite permits one
writer for the database at a time; unrelated hands may therefore wait even
though correctness is scoped per hand. `busy_timeout` bounds that wait.

PostgreSQL assumes the normal `READ COMMITTED` isolation level. Append first
takes `pg_advisory_xact_lock(hashtextextended(hand_id, 0))`, then reads the head
in the following statement and inserts the batch. The transaction-scoped lock
serializes writers for a hand; a rare 64-bit hash collision only adds
serialization and does not weaken correctness. The named database constraints
remain the final authority for sequence and cross-hand event-ID races.

## Error and retry boundary

Invalid batches, stale expected sequences, identity conflicts, retryable lock or
serialization failures, and other storage failures are exposed as stable
project-owned errors. SQLite/psycopg exception messages and classes do not form
part of the port contract.

Adapters never retry internally. On `HandEventAppendRetryable`, the caller may
retry the complete original transaction; it must never retry individual rows.
On `ExpectedSequenceConflict`, the caller must reread/reconcile the hand and
make a new domain decision instead of blindly changing the expected sequence.
Event-ID conflicts are deterministic identity failures, not retry signals.

## Migration and rollback risk

Alembic revision `0002` adds the table without changing stored V1 contracts or
historical revision `0001`. Application rollback must disable the writer/reader
while retaining `hand_events`; it must not downgrade the database merely to
roll back application code. An explicit Alembic downgrade from `0002` drops the
event table and is therefore destructive to durable hand history. Backup and
restore exercises remain F1-07 scope.
