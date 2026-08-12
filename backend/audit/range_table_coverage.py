"""Isolated J01--J09 Range/Table capability audit.

This is intentionally a runnable measurement, not a pytest test: it uses the
real FastAPI app/TestClient and writes no fixture-backed success result into
the normal test suite.  Run from the repository root with Python 3.13.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.domain.models import ScenarioSpec
from poker_coach.persistence.sqlite_store import SQLiteStore
from poker_coach.ranges.trace import board_at_sequence


POSITIONS = {
    2: ("button", "big_blind"),
    6: ("button", "small_blind", "big_blind", "utg", "mp", "co"),
    8: ("button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co"),
}
PRIOR = {"AA": "1", "KK": "1", "AKs": "1", "76s": "0.5", "J4o": "0.2"}


@dataclass
class Evidence:
    journey: str
    case: str
    constructable: bool
    priorReady: bool
    provider: str | None
    available: bool | None
    confidence: str | None
    stalledAtSequence: int | None
    reason: str | None
    temporalCorrect: bool | None = None
    provenanceCorrect: bool | None = None


def position(table_size: int, button: int, seat: int) -> str:
    return POSITIONS[table_size][(seat - button) % table_size]


def scenario(table_size: int, button: int = 0, hero: int = 0, *, board: bool = False) -> dict[str, Any]:
    first_actor = button if table_size == 2 else (button + 3) % table_size
    return {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": table_size,
        "smallBlind": 50,
        "bigBlind": 100,
        "buttonSeat": button,
        "heroSeat": hero,
        "seats": [
            {"seatId": seat, "startingStack": 10000, "position": position(table_size, button, seat)}
            for seat in range(table_size)
        ],
        # When supplied, all five cards are available to the imported scenario;
        # deal events govern visibility. Preflop policy cases intentionally use
        # no future board because its contract rejects any board field.
        "board": ["Ah", "Kd", "7c", "2s", "3h"] if board else [],
        "actionHistory": [],
        "decisionPoint": {"street": "preflop", "actorSeat": first_actor, "afterSequence": 0},
        "assumptions": {"rakeAssumption": "no_rake"},
        "rangesBySeat": {
            str(seat): {
                "rangeId": f"audit-prior-{seat}",
                "name": f"Seat {seat} audit prior",
                "version": "1",
                "source": "user_defined",
                "matrix169": PRIOR,
            }
            for seat in range(table_size)
        },
    }


def api(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"{path} -> {response.status_code}: {response.text}")
    return response.json()


def state(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    return api(client, "/v1/scenarios/state", payload)["finalState"]


def append(client: TestClient, payload: dict[str, Any], action: str, amount: int | None = None) -> dict[str, Any]:
    current = state(client, payload)
    legal = current["legalActions"]
    is_deal = action in {"deal_flop", "deal_turn", "deal_river"}
    # Street-deal controls are a deliberate ActionBar transition, rather than
    # a member of legalActions. Its actor fallback mirrors app/page.tsx.
    if not is_deal and action not in legal["actions"]:
        raise RuntimeError(f"{action} not legal at seq {len(payload['actionHistory'])}: {legal}")
    sequence = len(payload["actionHistory"]) + 1
    event: dict[str, Any] = {
        "actionId": f"audit-{sequence}-{action}",
        "sequence": sequence,
        "street": action.replace("deal_", "") if is_deal else current["street"],
        "actorSeat": legal["actorSeat"] if legal["actorSeat"] is not None else payload["heroSeat"],
        "actionType": action,
    }
    if action == "call":
        event.update(amount=legal["callAmount"], amountType="cost")
    elif action == "bet":
        event.update(amount=amount or legal["minRaiseTo"], amountType="by")
    elif action in {"raise_to", "all_in"}:
        event.update(amount=amount or legal["minRaiseTo"], amountType="to")
    payload = {**payload, "actionHistory": [*payload["actionHistory"], event]}
    after = state(client, payload)
    payload["decisionPoint"] = {
        "street": after["street"],
        "actorSeat": after["actorSeat"] if after["actorSeat"] is not None else event["actorSeat"],
        "afterSequence": sequence,
    }
    return payload


def belief_evidence(client: TestClient, journey: str, case: str, payload: dict[str, Any], seat: int, policy: Any = None) -> Evidence:
    request: dict[str, Any] = {"scenario": payload, "seatId": seat}
    if policy is not None:
        request["policy"] = policy
    response = api(client, "/v1/ranges/belief", request)
    trace = api(client, "/v1/ranges/trace", request)
    available = response["available"]
    reason = response.get("unavailableReason")
    # Trace snapshots deliberately do not serialize their board. Verify the
    # same production function used to derive them: future imported cards are
    # invisible until their own deal event.
    parsed = ScenarioSpec.model_validate(payload)
    temporal = board_at_sequence(parsed, 0) == ()
    for event in parsed.action_history:
        if event.action_type.value == "deal_flop":
            temporal = temporal and len(board_at_sequence(parsed, event.sequence)) == 3
        elif event.action_type.value == "deal_turn":
            temporal = temporal and len(board_at_sequence(parsed, event.sequence)) == 4
        elif event.action_type.value == "deal_river":
            temporal = temporal and len(board_at_sequence(parsed, event.sequence)) == 5
    provenance = response.get("confidence") != "unverified"
    return Evidence(
        journey=journey,
        case=case,
        constructable=True,
        priorReady=response.get("combos") is not None,
        provider=response.get("source"),
        available=available,
        confidence=response.get("confidence"),
        stalledAtSequence=None if available else payload["decisionPoint"]["afterSequence"],
        reason=reason,
        temporalCorrect=temporal,
        provenanceCorrect=provenance,
    )


def main() -> int:
    # This is one local process making hundreds of read/validate calls. Disable
    # only transport throttling; all domain, replay, and provider checks remain
    # exactly those of the production app.
    client = TestClient(
        create_app(config=AppConfig(rate_limit_per_minute=0), store=SQLiteStore(":memory:"))
    )
    rows: list[Evidence] = []

    # UI-unreachable table variants are still constructable through the real API.
    for table_size in (2, 6, 8):
        total = table_size * table_size
        valid = 0
        for button in range(table_size):
            for hero in range(table_size):
                payload = scenario(table_size, button, hero)
                try:
                    api(client, "/v1/scenarios/validate", payload)
                    valid += 1
                except RuntimeError as exc:
                    rows.append(Evidence("J03" if table_size == 8 else "J08", f"{table_size}max button={button} hero={hero}", False, False, None, None, None, 0, str(exc)))
        rows.append(Evidence("J03" if table_size == 8 else "J08", f"{table_size}max all button/hero combinations ({valid}/{total})", valid == total, True, "rules", True, "grounded", None, None))

    # Real legal trajectories. These use no policy data; belief availability is
    # expected to be honestly unavailable outside the declared curated nodes.
    curated_policy = {"source": "preflop_policy"}
    for size in (200, 220, 250, 300):
        payload = append(client, scenario(2), "raise_to", size)
        rows.append(belief_evidence(client, "J01" if size == 200 else "J02", f"HU open {size / 100:g}BB", payload, 0, curated_policy))
    fold_to_rfi = append(client, append(client, scenario(2), "raise_to", 200), "fold")
    rows.append(belief_evidence(client, "J01", "HU fold-to-RFI", fold_to_rfi, 1, curated_policy))
    terminal_scenario = {
        **fold_to_rfi,
        "knownHoleCardsBySeat": {"0": ["As", "Ad"], "1": ["Kc", "Qd"]},
        # Concrete hands, not broad priors, keep deterministic review analysis
        # below the exact-enumeration safety cap.
        "rangesBySeat": {},
        "assumptions": {"rakeAssumption": "no_rake", "equityAlgorithm": "monte_carlo", "simulationTrials": 200, "randomSeed": 7},
    }
    terminal_review = api(client, "/v1/hand-reviews", {"scenario": terminal_scenario})["review"]
    rows.append(
        Evidence(
            "J07",
            "terminal HU fold hand review",
            True,
            True,
            terminal_review.get("provider", "local"),
            bool(terminal_review.get("decisionReviews")),
            None,
            None,
            None,
            temporalCorrect=True,
            provenanceCorrect=True,
        )
    )
    limp = append(client, scenario(2), "call")
    rows.append(belief_evidence(client, "J05", "HU limp", limp, 0, curated_policy))
    bb_option = append(client, limp, "check")
    rows.append(belief_evidence(client, "J05", "HU BB option after limp", bb_option, 1, curated_policy))
    three_bet = append(client, append(client, scenario(2), "raise_to", 200), "raise_to")
    rows.append(belief_evidence(client, "J05", "HU 3bet", three_bet, 1, curated_policy))
    four_bet = append(client, three_bet, "raise_to")
    rows.append(belief_evidence(client, "J05", "HU 4bet", four_bet, 0, curated_policy))
    bb_vs_four_bet = append(client, four_bet, "call")
    rows.append(belief_evidence(client, "J05", "HU BB response vs 4bet", bb_vs_four_bet, 1, curated_policy))

    # Flop lines exercise action continuity after a real deal: check/check,
    # bet/call, and bet/raise/fold.  Every action is accepted only if backend
    # legalActions advertised it.
    preflop = append(client, append(client, scenario(2, board=True), "raise_to", 200), "call")
    flop = append(client, preflop, "deal_flop")
    check_check = append(client, append(client, flop, "check"), "check")
    rows.append(belief_evidence(client, "J06", "HU flop check/check", check_check, 1, curated_policy))
    bet_call = append(client, append(client, flop, "check"), "bet", 100)
    bet_call = append(client, bet_call, "call")
    rows.append(belief_evidence(client, "J06", "HU flop check/bet/call", bet_call, 0, curated_policy))
    bet_raise_fold = append(client, append(client, flop, "check"), "bet", 100)
    bet_raise_fold = append(client, bet_raise_fold, "raise_to", 300)
    bet_raise_fold = append(client, bet_raise_fold, "fold")
    rows.append(belief_evidence(client, "J06", "HU flop check/bet/raise/fold", bet_raise_fold, 1, curated_policy))

    # Exact genuine provider coverage: seven 8-max RFI positions. No fixtures.
    for target_position in ("utg", "utg+1", "mp", "hj", "co", "button", "small_blind"):
        payload = scenario(8)
        while position(8, 0, state(client, payload)["legalActions"]["actorSeat"]) != target_position:
            payload = append(client, payload, "fold")
        payload = append(client, payload, "raise_to", 250)
        actor = payload["actionHistory"][-1]["actorSeat"]
        rows.append(belief_evidence(client, "J04", f"8max {target_position} 2.5BB RFI", payload, actor, {"source": "preflop_policy"}))

    # Explicitly measure, but do not count, a fixture-only success.
    fixture_case = append(client, scenario(2), "raise_to", 250)
    fixture = {"source": "fixture", "frequencies": {"raise_to": {"AA": {"raise": "1"}, "KK": {"raise": "1"}, "AKs": {"raise": "1"}, "76s": {"raise": "1"}}}}
    rows.append(belief_evidence(client, "J02", "HU 2.5BB fixture-only control (excluded)", fixture_case, 0, fixture))

    # /state projects to decisionPoint.afterSequence; persistence also checks
    # that actor against the full replay, so use the known next HU actor here.
    fixture_case["decisionPoint"] = {"street": "preflop", "actorSeat": 1, "afterSequence": 1}
    created = api(client, "/v1/scenarios", {"scenario": fixture_case, "title": "audit", "tags": ["audit"]})["scenario"]
    revised = fixture_case | {"heroSeat": 1}
    update = client.put(f"/v1/scenarios/{created['scenarioId']}", json={"scenario": revised, "title": "audit", "tags": ["audit"]})
    revisions = client.get(f"/v1/scenarios/{created['scenarioId']}/revisions")
    mutation_ok = update.status_code == 200 and revisions.status_code == 200 and len(revisions.json()["revisions"]) == 2
    rows.append(Evidence("J09", "save/update/revision recovery", mutation_ok, True, "scenario_store", mutation_ok, "grounded" if mutation_ok else None, None if mutation_ok else 1, None if mutation_ok else f"update={update.text}; revisions={revisions.text}", temporalCorrect=True, provenanceCorrect=True))

    belief_rows = [row for row in rows if row.journey in {"J01", "J02", "J04", "J05", "J06"}]
    non_fixture_belief = [row for row in belief_rows if "fixture-only" not in row.case]
    counts = {
        "total": len(rows),
        "constructable": sum(row.constructable for row in rows),
        "available": sum(row.available is True for row in rows),
        "unavailable": sum(row.available is False for row in rows),
        "fixtureOnly": sum("fixture-only" in row.case for row in rows),
        "rangeBeliefCases": len(belief_rows),
        "rangeBeliefAvailableExcludingFixture": sum(row.available is True for row in non_fixture_belief),
        "rangeBeliefCasesExcludingFixture": len(non_fixture_belief),
    }
    output = {"counts": counts, "rows": [asdict(row) for row in rows]}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
