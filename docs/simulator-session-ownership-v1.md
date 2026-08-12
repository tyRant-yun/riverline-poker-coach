# Simulator session ownership V1

Status: F1-01 authoritative lifecycle seam

`GameSession` owns one continuous cash table: its `SessionId`, fixed first-product
configuration, seat membership, seat stacks, button, active hand and completed
hand sequence.  It is an immutable aggregate: lifecycle transitions return a new
validated `GameSession`; callers must retain that successor as authority.

The first released configuration is deliberately exact: six table seats, NLHE,
50/100 blinds, 10,000-chip (100BB) stacks, no ante and no rake.  `SeatTopologyV1`
validates contiguous seat IDs and the reusable 2--8-seat domain boundary, but it
does not publish 2--5- or 7--8-max product modes.

`SessionSeatV1.sitting_out` means the seat remains part of the table and retains
its stack, but is excluded from the next hand and skipped during button rotation.
A zero-stack seat likewise remains in the session but is not eligible for the
next hand and is skipped by the button.  Starting another hand requires at least
two funded, non-sitting-out seats and otherwise fails with
`insufficient_funded_seats`.  An `ActiveHandV1` captures only the eligible
Hand Participants and immutable opening-stack snapshots without renumbering
their stable Table Seat IDs.  Its deterministic `HandId` is
`{SessionId}:hand:{sequence}`, so a hand can belong to exactly one session and a
completed session cannot reuse a hand sequence or ID.

F1-01 does not deal cards, post blinds, validate actions, calculate settlement,
write events, or update stacks.  F1-03's PokerKit-backed orchestrator must perform
those rule transitions and may only close this seam after it has accepted a hand
completion.

## F1-03 settlement stack seam

`GameSession.complete_active_hand(..., ending_stacks=...)` accepts only the
PokerKit-replayed final stacks for exactly the active hand seats.  The transition
rejects missing/extra seats, negative stacks, or any change to the active hand's
total chips, then immutably replaces those session seat stacks while retaining
sitting-out seats unchanged.  Omitting `ending_stacks` preserves the F1-01
ownership-only behavior for backward compatibility.

When F1-03 opens that successor hand, `HandStartedPayloadV1.startingStacks`
retains all session Table Seats, including sitting-out or zero-stack seats, and
`activeSeatIds` carries only the `ActiveHandV1` participants.

This is an in-memory aggregate transition, not a durable session repository.
F1-03 therefore proves single-hand event recovery and an explicit post-settlement
handoff, but it does not claim crash-safe cross-hand session progression.
