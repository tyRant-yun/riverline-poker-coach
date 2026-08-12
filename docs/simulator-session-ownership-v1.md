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
At least two seats must participate.  An `ActiveHandV1` captures only the eligible
seats and immutable opening-stack snapshots.  Its deterministic `HandId` is
`{SessionId}:hand:{sequence}`, so a hand can belong to exactly one session and a
completed session cannot reuse a hand sequence or ID.

F1-01 does not deal cards, post blinds, validate actions, calculate settlement,
write events, or update stacks.  F1-03's PokerKit-backed orchestrator must perform
those rule transitions and may only close this seam after it has accepted a hand
completion.
