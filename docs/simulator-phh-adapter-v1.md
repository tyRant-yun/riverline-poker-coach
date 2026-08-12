# PHH adapter V1

`HandHistoryCodec` is an exchange-only adapter.  It projects a completed,
validated `HandEventV1` stream to PHH through PokerKit 0.7.4's
`HandHistory.dumps`, and imports PHH through `HandHistory.loads` plus the
existing PokerKit-backed `replay_hand` seam.  PHH is never a rules engine,
event store, or query source.

Supported input/output is NLHE cash (`NT`), 2--8 seats, blinds, uniform antes,
player actions, board deals, completion and PokerKit-derived payouts. The
default `export()` visibility is `public`: it never emits `d dh` private-card
actions. Only the explicit `visibility="authoritative_archive"` mode emits all
recorded hole cards, and callers must keep that mode behind their authorization
boundary. The adapter does not infer showdown/reveal rights from a completion
event; absent that explicit archival mode, cards are redacted.

The product default remains 6-max, 100BB, no ante and no rake.
Current authoritative replay rejects rake, so raked PHH is explicitly rejected
instead of fabricating a settlement.

PHH player numbers are dense as required by the format.  Riverline writes
explicit `riverline_*` extension fields for stable table capacity, sparse
`activeSeatIds`, button, full table stacks, seed, hand ID, event envelopes and
action amount semantics.  Those fields preserve facts PHH cannot represent;
imports without them create `source_provenance_unavailable` rather than
claiming original provenance.  A mismatch between the PHH public action and
the extension is rejected.

Import accepts only completed hands. A completed import must carry the PHH
standard `finishing_stacks` and `winnings` arrays aligned to active seats. Both
must exactly match the no-rake PokerKit replay; a total-chip reduction is
rejected as `potential_rake`, while any other difference is
`settlement_mismatch`. Missing settlement facts are rejected rather than
regenerating payout facts. PokerKit validates PHH syntax/state, then
the authoritative event replay validates actors, amounts, streets, board and
settlement.  A showdown with more than one live player requires recorded hole
cards for every live seat; it is rejected otherwise.  A terminal fold can
remain private-card sparse.

`backend/tests/test_phh_codec.py` provides executable golden fixtures for
standard 6-max, a sparse post-bust hand, all-in/side-pot settlement and fold
completion.  They assert public facts and replay fingerprint equality after
`event -> PHH -> event`, while allowing non-semantic PHH text changes.
