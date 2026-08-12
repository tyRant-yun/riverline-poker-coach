# Simulator → Hand Lab compatibility bridge v1

Status: F1-06 MVP contract
Date: 2026-08-12

## Purpose

`poker_coach.simulator.hand_lab_compat` is the thin migration adapter for
opening an authoritative `HandEventV1` prefix in the existing `ScenarioSpec`
and Hand Lab flows. It preserves the existing `/v1/scenarios/*` request and
response contracts; no Hand Lab button text, aria-label, CSS class, action ID,
or E2E hook is renamed.

The adapter is not a second rules engine. It maps event facts into
`ScenarioSpec`, then uses the existing PokerKit adapter to verify that the
visible projection can reproduce the authoritative public state. Legal
actions, amount bounds, chip movement, settlement, and analysis/solver values
remain outside this module.

## Public seam

```python
scenario_from_authoritative_events(
    events,
    hero_seat=<stable table seat>,
    authorized_hole_card_seat_ids={<server-authorized seats>},
    replayed_hand=<optional authoritative projection>,
) -> HandLabScenarioV1

player_action_command_from_hand_lab(
    session_id=..., hand_id=..., command_id=..., expected_sequence=...,
    action=<existing ActionEvent>,
) -> PlayerActionCommandV1
```

`HandLabScenarioV1` is versioned (`schemaVersion=1`,
`compatibilityVersion=1`) and wraps the legacy `ScenarioSpec` with facts that
`ScenarioSpec` cannot represent:

| Field | Meaning |
|---|---|
| `authoritativeTableSize` | Fixed session topology (for example, 6) |
| `activeSeatIds` | Stable table seats participating in this hand |
| `participantCount` | Number of active participants |
| `scenario.tableSize` | The legacy active-ring size, equal to `participantCount` |
| `visibleHoleCardSeatIds` | Only card seats explicitly authorized by the caller |
| `degradationReasons` | Honest missing-information state for Hand Lab/analysis |

Thus a sparse hand at a 6-max session table can have
`authoritativeTableSize=6`, `activeSeatIds=[0,3,4,5]`, and
`scenario.tableSize=4`. The adapter never treats either number as the other.

## Visibility and incomplete facts

The caller supplies server-authorized visible hole-card seats; the adapter
never derives a card from a winner, payout, or replay. Its default is no
visible hole cards. Missing hero cards yield a valid fresh/in-progress
ScenarioSpec with `hero_hole_cards_not_authorized` or
`hero_hole_cards_not_recorded`, allowing the existing Hand Lab's honest
degradation path.

Completed multi-player showdowns require recorded and authorized cards for
every non-folded participant. Otherwise the adapter raises
`HandLabCompatibilityError(code="insufficient_visible_facts")`; it does not
invent a completed ScenarioSpec. Invalid, mixed, out-of-order, or incomplete
event streams retain the stable `EventStreamError` produced by
`validate_hand_event_stream`.

## Reverse action mapping

Only current Hand Lab player actions map back to an authoritative command:

| Hand Lab `ActionType` | Command action | Amount semantics |
|---|---|---|
| `fold` | `fold` | `none` |
| `check` | `check` | `none` |
| `call` | `call` | `cost` |
| `bet` | `bet` | `by` |
| `raise_to` | `raise` | `to` |
| `all_in` | authoritative `bet` or `raise` endpoint | preserves that endpoint's `by` or `to` |

All-in needs the acting seat's authoritative `ObservationV1`; the bridge only
selects the exact published `bet`/`raise` maximum and never derives a size.
Blinds, board dealing, showdown, and award events are rejected as
`unsupported_hand_lab_action`. Translation does not make an action legal:
`GameOrchestrator.execute` always rebuilds the PokerKit state and validates the
actor, action, and bounds before appending events.

## Verification scope

`backend/tests/test_hand_lab_compat.py` proves a sparse 6-max authoritative
hand opens through the unchanged `/v1/scenarios/validate` endpoint, retains
stable seat IDs/topology metadata, does not serialize an unauthorized
opponent card, degrades missing cards honestly, rejects insufficient showdown
visibility, and preserves all six existing player-action amount semantics.
