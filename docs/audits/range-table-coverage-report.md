# Range/Table capability audit — J01–J09

Date: 2026-08-11
Scope: real FastAPI/TestClient contracts and the isolated Playwright UI gate. No production module was changed. Existing ordinary E2E mocks for Range/Review/Solver were not used as evidence.

## Verdict

**Not release-ready for P0 Range/Table journeys.** The backend can construct all audited table/button/hero combinations and the narrow curated 8-max RFI policy is real. The web UI exposes only the HU construct surface, so those backend capabilities are unreachable. A normal HU open also reaches an honest `no_policy` state, not a usable Current range.

## Exact evidence and counts

`backend/audit/range_table_coverage.py` creates an in-memory app with the production routes, rules adapter, range providers, and persistence implementation. The local HTTP rate limit alone is disabled because the enumeration makes hundreds of calls in one process.

| Measurement | Result | Interpretation |
|---|---:|---|
| table/button/hero API constructions | 104/104 | 2-max 4/4, 6-max 36/36, 8-max 64/64 validate and replay |
| audit evidence rows | 25/25 constructable | every generated contract path completed |
| Range Belief rows | 20 | all received a real prior and trace |
| usable Range Belief, excluding fixture | 7/19 (36.8%) | exactly the seven 8-max 2.5BB RFI positions |
| fixture-only success | 1/1, excluded | HU 2.5BB works only when an explicit test fixture provider is supplied |
| unavailable real-policy paths | 12/19 | all stop honestly at `no_policy` |
| temporal checks | 19/19 | production `board_at_sequence` keeps future board cards hidden until `deal_*` |
| provenance checks | 19/19 | no raw/unverified solver result counted; curated/manual/fixture labels retained |
| terminal HU hand review API | pass | real `/v1/hand-reviews` returns decision reviews using bounded Monte Carlo input |
| save/update/revision API | pass | real in-memory store produces two revisions |
| isolated UI gate | 1 passed, 2 failed | one positive HU inventory/ActionBar test; two intentional P0 red tests |

The 7/19 numerator is `UTG, UTG+1, MP, HJ, CO, BTN, SB` 8-max RFI at exactly 100BB, no ante/rake, and a 2.5BB open. Its provider is `preflop_policy`, with `confidence=curated`, not solver-backed.

## Range Belief matrix

| Journey / line | Constructable / prior | Provider | Available / confidence | Stall / reason |
|---|---|---|---|---|
| J01 HU 2BB open; fold-to-RFI | yes / yes | manual | no / manual | seq 1 or 2: `no_policy` |
| J02 HU 2.2, 2.5, 3BB opens | yes / yes | manual | no / manual | seq 1: `no_policy` |
| J02 HU 2.5 fixture control | yes / yes | fixture | yes / grounded | **excluded from usable coverage** |
| J03 all 8-max button × hero combinations | 64/64 | rules | replay valid | UI cannot create them |
| J04 seven 8-max 2.5BB RFIs | 7/7 | preflop_policy | yes / curated | no stall |
| J05 limp, BB option, 3-bet, 4-bet | yes / yes | manual | no / manual | seq 1–3: `no_policy` |
| J06 valid-deal flop check/check; check/bet/call; check/bet/raise/fold | yes / yes | manual | no / manual | earliest ungrounded preflop action; no persisted solver artifact supplied |
| J07 terminal HU fold review | yes | local review | yes | API-only evidence; UI remains subject to red gate |
| J08 2/6/8-max seat, button, hero matrix | 104/104 | rules | replay valid | multiway policy/equity is not claimed by this Range audit |
| J09 save/update/revision | yes | scenario_store | yes / grounded | API evidence; UI undo/redo positive path also passed |

## UI capability inventory

The passing audit test drives the actual page: it changes a HU stack surface, confirms import/export controls exist, takes a `Raise to 200` from the backend-provided ActionBar, then verifies undo and redo return `0 events` and `1 events`.

| UI capability | Observed result |
|---|---|
| HU cards, HU stacks, import/export | present |
| HU ActionBar and undo/redo continuity | present on the driven one-action path |
| table size, button, hero seat controls | absent |
| continuous 6/8 seats and per-seat position/stack controls | absent |
| per-seat range editing | absent (HU Hero/Villain sides only) |
| 8-max curated RFI reachable from UI | no — prerequisite table construction is absent |
| HU Current after user normalizes prior and opens | unavailable; UI shows `current range unavailable` |

## P0 findings

1. **P0 — multiway capability is backend-supported but UI-unreachable.** The API validates 8-max variants, while `ScenarioEditor` renders only Hero/Villain HU fields and the red gate cannot find `桌型`, `按钮位`, or `Seat 7 … 位置`.

   Minimal repro:

   ```powershell
   cd frontend
   npx playwright test --config playwright.audit.config.ts --grep "8-max"
   ```

2. **P0 — HU normal open has no usable Current range.** After a real prior normalization and real ActionBar `Raise to 200`, the non-mocked UI still exposes `current range unavailable`. API evidence agrees: HU opens, calls, limp/BB option, 3-bet/4-bet, and the driven flop lines are `no_policy`.

   Minimal repro:

   ```powershell
   cd frontend
   npx playwright test --config playwright.audit.config.ts --grep "common HU open"
   ```

3. **P0 usability gap — unavailable does not offer an operational next step.** The backend’s `no_policy` is honest, but the audited default UI journey cannot submit a grounded artifact or choose a supported coverage path. The declared requirement is actionable degradation, not merely a reason string.

## P1 / policy-data boundaries

- **P1 data coverage:** provider coverage is deliberately only the seven 8-max 2.5BB RFI nodes. BB option, limp, non-2.5 sizes, calls, 3/4-bets, and all audited postflop lines need sourced policy data or a persisted, exact-node Solver artifact.
- **P1 J08 depth:** the rules engine accepts the 6/8-max topology matrix. This audit did not claim end-to-end UI multiway edge-pot/equity coverage because no multiway UI construction path exists.
- **P1 solver evidence:** raw solver `result` is intentionally excluded; no live solver worker/artifact was treated as a successful provider. A future audit must create and poll real grounded jobs for each selected postflop node.

## Recommended repair order

1. Add UI construction: table size, continuous seat list, derived position/button, hero selector, stacks, per-seat ranges, and import/export preservation.
2. Expose the existing 8-max curated RFI path in that UI and label it curated.
3. Add actionable `no_policy` resolution (supported policy selection or explicit grounded Solver-job flow).
4. Add sourced policy data/grounded artifacts for HU and postflop branches, then expand the red gate into those journeys.
5. Add a separate multiway all-in/side-pot/equity UI journey once constructability exists.

## Commands

```powershell
# Real backend coverage matrix (not collected by pytest)
$env:PYTHONPATH=''; $env:PYTHONHOME=''
py -3.13 backend/audit/range_table_coverage.py

# Dedicated red UI gate; intentionally outside the ordinary E2E config
cd frontend
npx playwright test --config playwright.audit.config.ts
```

Last execution: harness exited 0 with `25 constructable`, `7/19` non-fixture usable Range Belief; Playwright exited 1 with `1 passed, 2 failed` as detailed above.
