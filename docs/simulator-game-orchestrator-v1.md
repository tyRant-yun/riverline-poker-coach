# PokerKit-backed GameOrchestrator V1

Status: F1-03 authoritative single-hand command seam

`GameOrchestrator` accepts project-owned, immutable V1 commands and emits only
the frozen `HandEventV1` payload union.  PokerKit remains the sole authority for
deal order, actor order, legal actions, amount bounds, street transitions,
all-in runout, side pots, winners, and payouts.

The adapter exposes deterministic deals only through the project-owned,
frozen, versioned `SeededDealV1` JSON contract.  No PokerKit state or upstream
type crosses the adapter boundary.

## Commands

- `OpenHandCommandV1` carries `sessionId`, `handId`, `commandId`,
  `expectedSequence`, the system actor, and an explicit non-negative `rngSeed`.
  It materializes the F1-01 active-hand facts as one `hand_started` plus one
  `hole_cards_recorded` fact per seat.
- `PlayerActionCommandV1` carries `sessionId`, `handId`, `commandId`,
  `expectedSequence`, `actorSeat`, action, amount, and amount semantics.  The
  action set and `none`/`cost`/`by`/`to` meanings are exactly the frozen
  `LegalActionV1` meanings; all-in is the legal bet/raise maximum endpoint.

Before opening-command reconciliation or an action append, the orchestrator
reads the complete durable hand, checks its opening facts against the supplied
active session hand, regenerates the PokerKit seeded deal, and verifies every
recorded hole card and board prefix against `HandStarted.rng_seed`.  It then
rebuilds the PokerKit state and validates actor/action/amount.  A street-closing
action is batched with the PokerKit-requested seeded board deal.  A terminal
action is batched with exactly one PokerKit-derived `hand_completed`.  Every
batch is continuous, sourced as `game_orchestrator`, and carries producer,
correlation, and command causation provenance.

## Idempotency and conflicts

The durable event causation ID is the command ID.  Repeating the same command ID
with the same normalized intent returns the durable replay as an idempotent
result and appends nothing.  Reusing it with a different intent fails with
`command_id_conflict`.

An `expected_sequence` conflict is never handled by changing the expected head
and replaying a non-idempotent action.  The orchestrator rereads once: if the
same command is now durable, it validates and reconciles idempotently;
otherwise it returns `append_conflict`.  A reconciled opening command whose
winner already completed the hand returns the settled successor session.
Storage adapters retain responsibility for all-or-nothing batch commit.

## Recovery and current boundary

A new orchestrator instance needs only the F1-01 active-hand opening facts and
the durable `HandEventV1` stream to continue a hand.  Completed streams reject
new actions, and the final PokerKit stacks cross the explicit immutable session
settlement seam documented in `simulator-session-ownership-v1.md`.

F1-03 supports the released contiguous six-seat active topology.  A session
with sparse active seat IDs (for example, sitting-out gaps) cannot be represented
without changing the frozen V1 `table_size`/seat contract and is rejected as
`unsupported_active_topology`.  Durable session ownership, cross-hand crash
recovery, projection/outbox/cursor/snapshot work, API/frontend, bots/advisor,
PHH, and F1-04+ remain outside this seam.
