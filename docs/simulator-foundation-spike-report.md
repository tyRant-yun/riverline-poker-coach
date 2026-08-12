# F0 Simulator Foundation spike report

Date: 2026-08-12
Scope: bounded risk reduction, not production GameSession delivery

## Environment and reproducibility

- Shell/Git/Node environment: WSL Ubuntu-24.04 at the isolated Codex worktree.
- WSL only had Python 3.12.3; Riverline requires Python 3.13. Tests therefore invoked the already-installed host Python 3.13.14 from the WSL shell. No interpreter or package was downloaded.
- All spike fixtures use fixed timestamps and seed `20260812`.
- No network access and no new dependency were used.

## Spike 1: event replay and projections

Fixture: `backend/tests/fixtures/simulator-hand-v1.json`.

The fixture is one 6-max, 100BB, no-ante/no-rake hand: UTG/MP/CO fold, BTN raises to 2.5BB, SB folds, BB calls, then BTN/BB check down `2c 7d Jh 9s 3h`. It contains 19 versioned events, including private card facts and a final completion fact.

Verified outcomes:

- two replays produce byte-identical `ReplayedHandV1` JSON and the same SHA-256 state fingerprint;
- PokerKit rebuilds the final board, seat 2 winner and 550-chip payout from events only;
- state and per-seat VPIP/PFR/3Bet/action-count projections rebuild independently;
- stream validation detects out-of-order sequence and duplicate event identity;
- append returns a new tuple and does not replace/mutate the existing prefix;
- `build_observation(..., observer_seat=2, after_sequence=10)` contains BB's cards but not BTN's recorded cards or any belief field.

Conclusion: reducer + PokerKit adapter + disposable read projections is viable. This is an in-memory spike only. Durable uniqueness constraints, optimistic append, projection cursors/checkpoints, outbox recovery, snapshots, PHH projection and long-running session recovery remain F1 work.

## Spike 2: bounded bot runtime

The async port is `BotDecisionProvider.decide(observation, legal_actions, time_budget_ms, rng_seed)`. `BotRuntime` measures provenance itself, validates the returned action against `LegalActionV1`, and falls back to the constant-time local order `check -> call -> fold -> minimum bet/raise`.

Automated tests prove:

- a normal provider decision is returned with runtime-measured provider identity/latency;
- a provider sleeping 200ms under a 10ms budget is cancelled and returns a legal fixed-policy action in under the 150ms test ceiling;
- a raised exception records `provider_exception` then falls back;
- a syntactically valid but out-of-bounds bet records `illegal_bot_action` then falls back;
- each degraded result retains failed and successful attempt provenance.

Conclusion: the in-process async fault boundary is viable and does not block the hand for tested failure modes. F0 did not implement subprocess/RPC adapters, OS resource limits, retries/circuit breaking, bulk self-play, or PokerKit revalidation after adapter conversion; those are explicit F2 gates.

## Spike 3: evaluator differential and benchmark

Harness:

```bash
cd backend
python -m poker_coach.simulator.evaluator_benchmark \
  --samples-per-size 1000 --rounds 5 --seed 20260812
```

The first formal run found one real current-evaluator mismatch: `Js Kc Ks Jd 4d Jc Kd` was classified as trips instead of kings-full-of-jacks. A regression test was added and the direct evaluator now treats a second trip rank as the full-house pair.

Post-fix result from this worktree:

| Evidence | Result |
|---|---:|
| Current vs independent five-card subset oracle | 3,000 hands across 5/6/7 cards; **0 mismatches** |
| Current benchmark evaluations | 15,000 |
| Current p50 | 6,404 ns/evaluation |
| Current p95 | 6,544 ns/evaluation |
| Observed throughput | 155,285 evaluations/second |
| `phevaluator` import | unavailable (`ModuleNotFoundError`) |

Latency numbers are a single local microbenchmark, not a service SLO. They primarily prove the harness is runnable and establish an order-of-magnitude comparison point.

PH Evaluator adoption gate remains **not passed**:

1. zero pairwise/tie differential mismatches across representative 5/6/7-card and equity workloads;
2. at least 2× p50 improvement after card-conversion overhead on the supported runtime matrix;
3. Python 3.13 Windows and Linux/WSL wheel/build/packaging validation;
4. exact installed distribution version/hash plus local Apache-2.0 LICENSE/NOTICE verification.

The research ledger records Apache-2.0 as the candidate's upstream declaration, but F0 did not install a distribution and therefore does not claim local package-license or packaging verification. No manifest/lockfile change was made. Continue using the corrected current evaluator until a separate, approved offline dependency spike passes every gate.

## Automated spike tests

- `backend/tests/test_simulator_contracts.py`
- `backend/tests/test_simulator_replay.py`
- `backend/tests/test_bot_runtime.py`
- `backend/tests/test_evaluator_benchmark.py`

These are public-seam behavior tests; they do not mock Riverline internals.
