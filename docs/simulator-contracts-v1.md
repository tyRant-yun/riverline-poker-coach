# Simulator Foundation contracts V1

Status: F0 frozen baseline
Date: 2026-08-12
Code: `backend/poker_coach/simulator/contracts.py`

These contracts belong to the simulator domain boundary. They are not frontend view models, PokerKit objects, PHH records, or replacements for the existing Hand Lab `ScenarioSpec`.

## Common wire rules

- JSON field names are camelCase; unknown fields are rejected.
- `schemaVersion` is the integer `1` for every top-level V1 contract.
- Chip values are non-negative integer smallest-chip units; floats are never accepted for rule amounts.
- JSON serialization is UTF-8-compatible, key-sorted, compact, and rejects NaN/Infinity.
- Event timestamps must include a timezone; stored event fixtures use UTC `Z` timestamps.
- Contract objects are frozen after validation. An event log appends a new envelope and never updates an earlier envelope.

## `HandEventV1`

Every envelope requires `eventId`, `handId`, contiguous per-hand `sequence`, `schemaVersion`, timezone-aware `timestamp`, `source`, and producer `provenance`. V1 payload kinds are:

| Kind | Fact recorded | Visibility note |
|---|---|---|
| `hand_started` | Ruleset, 2–8 Table Seat topology, button, blinds/ante/rake, all opening stacks, Hand Participant IDs and deterministic seed | Public configuration |
| `hole_cards_recorded` | One seat's two cards | Authoritative/private event; filtered from other observations |
| `action_taken` | Street, actor, action and amount semantics | Public action |
| `board_dealt` | Flop/turn/river cards | Public cards |
| `hand_completed` | Winner seats and PokerKit-verified payouts | Public result |

The stream validator rejects a missing/duplicate start, mixed `handId`, gaps or reordering, duplicate `eventId`, timestamp regression, repeated/overlapping known cards, invalid seat references, board street disorder, duplicate completion, events after completion, and a completion projection that disagrees with PokerKit.

`tableSize` and `startingStacks` describe the stable session Table Seats. The
optional `activeSeatIds` field identifies the Hand Participants and must be a
strictly increasing subset of those seats with at least two positive opening
stacks; the button is one of them. Every later event continues to use the
stable Table Seat ID. Missing `activeSeatIds` in legacy V1 JSON deterministically
normalizes to all contiguous `startingStacks` keys, preserving the original
all-seats-participate meaning.

## `ObservationV1`

An observation contains only information available to `observerSeat` at one event sequence:

- that seat's own hole cards;
- public board and ordered public player actions;
- public pot, Hand Participant stacks/commitments, active/folded participant
  seats, and the stable table button/street;
- current `LegalActionV1` values.

There is deliberately no field for another player's hole cards, deck order, RNG state, solver internals, advisor result, or Range Belief. Because extras are forbidden, an adapter cannot silently attach those fields. A Range Belief is an advisor/read-model estimate, not an agent observation fact.

## `LegalActionV1`

The action set is exactly `fold`, `check`, `call`, `bet`, and `raise`.

| Action | `amountSemantics` | Bounds |
|---|---|---|
| fold/check | `none` | no amount |
| call | `cost` | exact incremental call cost (`minAmount == maxAmount`) |
| bet | `by` | inclusive chips added by this action |
| raise | `to` | inclusive total street commitment after the action |

All-in is not a sixth action. It is the inclusive `maxAmount` endpoint of a legal bet or raise. A `BotDecisionV1` must match one legal action and fall within its bounds before it reaches the rule engine.

## `BotDecisionV1`

The contract records action/amount, authoritative runtime `provider` and `providerVersion`, measured `latencyMs`, optional `[0,1]` confidence, JSON metadata, whether the decision degraded, the fallback reason, and an ordered attempt trail. Attempt status is `success`, `timeout`, `exception`, or `invalid_action`, with error codes/messages for failed attempts. Provider self-reported identity or latency is not trusted by the runtime.

## Compatibility and upcasting

V1 is an exact schema, not an open-ended dictionary. Consumers:

1. read `schemaVersion` before dispatch;
2. accept only versions they explicitly implement;
3. reject unknown future versions and enum values instead of guessing;
4. retain the original append-only event bytes/envelope;
5. compatible V1 additions must have deterministic defaults and frozen legacy-fixture tests; `HandStartedPayloadV1.activeSeatIds` defaults to all `startingStacks` seats as recorded in ADR-0009;
6. when V2 is needed for a change that cannot be represented by such a default, add a pure, deterministic `V1 -> V2` upcaster at an ingress/replay boundary and never rewrite stored V1 history in place;
7. keep projections disposable and rebuildable, so projection schema migrations do not mutate event facts.

Fields cannot be removed, renamed, or have their meaning changed inside V1.
An additive field is compatible only when its default exactly preserves every
legacy payload's meaning; otherwise the change requires a new contract version.
PHH import/export adapters preserve their own format version and provenance
outside these internal contracts.
