"""Solver adapter tests: spot mapping, result parsing/validation, cache.

Offline and deterministic: the sidecar is never invoked — the full spike
solve output (backend/tests/fixtures/solve-output-spike1.json) drives the
parser, and an injected runner drives the client.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from poker_coach.domain.models import (
    RangeCombo,
    RangeSource,
    RangeSpec,
    ScenarioSpec,
    Street,
)
from poker_coach.solver import (
    SidecarClient,
    SolveCache,
    SolverSpot,
    SolverUnsupportedError,
    build_spot,
    parse_result,
    range_to_string,
    solve_hash,
    spot_to_config_json,
)

FIXTURE = Path(__file__).parent / "fixtures" / "solve-output-spike1.json"


@pytest.fixture(scope="module")
def spike_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spike_result(spike_payload) -> SolverSpot:
    return parse_result(spike_payload)


def scenario_at_flop() -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10000, "position": "button"},
                {"seatId": 1, "startingStack": 10000, "position": "big_blind"},
            ],
            "heroHoleCards": ["Ac", "Kc"],
            "villainHoleCards": None,
            "board": ["Ks", "7h", "2h"],
            "actionHistory": [
                {"actionId": "open", "sequence": 1, "street": "preflop", "actorSeat": 0, "actionType": "raise_to", "amount": 250, "amountType": "to"},
                {"actionId": "call", "sequence": 2, "street": "preflop", "actorSeat": 1, "actionType": "call", "amount": 150, "amountType": "cost"},
                {"actionId": "flop", "sequence": 3, "street": "flop", "actorSeat": 0, "actionType": "deal_flop"},
            ],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
            "assumptions": {},
            "source": "manual",
            "tags": ["solver-test"],
        }
    )


def ranges_for_spike() -> tuple[RangeSpec, RangeSpec]:
    hero_range = RangeSpec(
        range_id="hero-test",
        name="hero test",
        version="1",
        source=RangeSource.USER_DEFINED,
        combos=(
            RangeCombo(cards=("Ac", "Kc"), weight=Decimal("1")),
            RangeCombo(cards=("5h", "4h"), weight=Decimal("0.5")),
        ),
    )
    villain_range = RangeSpec(
        range_id="villain-test",
        name="villain test",
        version="1",
        source=RangeSource.USER_DEFINED,
        combos=(
            RangeCombo(cards=("Qh", "Qc"), weight=Decimal("1")),
            RangeCombo(cards=("Ah", "Kh"), weight=Decimal("0.75")),
        ),
    )
    return hero_range, villain_range


# --- parsing -----------------------------------------------------------------


def test_parse_full_fixture(spike_result):
    assert spike_result.metadata.solver == "postflop-solver"
    assert spike_result.metadata.exploitability_chips == pytest.approx(2.3484, abs=1e-3)
    assert spike_result.metadata.max_iterations == 400
    assert spike_result.root.actions == ("Check", "Bet(250)", "Bet(605)", "AllIn(9750)")
    assert spike_result.root.player == 0
    assert len(spike_result.root.hands) == 181
    assert spike_result.response_node is not None
    assert spike_result.response_node.actions == ("Fold", "Call", "Raise(625)")
    assert len(spike_result.response_node.hands) == 267


def test_parse_strategy_dict_matches_report(spike_result):
    ak = next(h for h in spike_result.root.hands if h.combo == "AcKc")
    assert ak.equity == pytest.approx(0.832, abs=1e-3)
    assert ak.strategy["Check"] == pytest.approx(0.662, abs=1e-3)
    assert ak.strategy["Bet(250)"] == pytest.approx(0.337, abs=1e-3)
    qq = next(h for h in spike_result.response_node.hands if h.combo == "AcQc")
    assert qq.strategy["Fold"] == pytest.approx(0.403, abs=1e-3)
    assert qq.strategy["Call"] == pytest.approx(0.552, abs=1e-3)


def test_parse_rejects_frequency_mismatch(spike_payload):
    broken = json.loads(json.dumps(spike_payload))
    hand = broken["root"]["hands"][0]
    hand["strategy"][0] = hand["strategy"][0] + 0.5  # sum != 1
    with pytest.raises(SolverUnsupportedError, match="sum"):
        parse_result(broken)


def test_parse_rejects_missing_metadata(spike_payload):
    broken = json.loads(json.dumps(spike_payload))
    del broken["metadata"]["exploitabilityChips"]
    with pytest.raises(SolverUnsupportedError, match="metadata missing"):
        parse_result(broken)


def test_parse_rejects_strategy_length_mismatch(spike_payload):
    broken = json.loads(json.dumps(spike_payload))
    broken["root"]["hands"][0]["strategy"] = [0.5, 0.5]  # 2 != 4 actions
    with pytest.raises(SolverUnsupportedError, match="length"):
        parse_result(broken)


# --- spot mapping ------------------------------------------------------------


def test_build_spot_golden_mapping():
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()

    def render(spec: RangeSpec) -> str:
        return ",".join(
            f"{c.cards[0]}{c.cards[1]}:{float(c.weight):g}"
            for c in spec.combos
            if c.weight > 0
        )

    spot = build_spot(
        scenario,
        hero_range=hero_range,
        villain_range=villain_range,
    )
    assert spot.street is Street.FLOP
    assert spot.board == ("Ks", "7h", "2h")
    assert spot.turn is None and spot.river is None
    assert spot.starting_pot == 500
    assert spot.effective_stack == 9750
    # OOP is the non-button seat (BB = villain); IP is the button (hero).
    assert spot.oop_range == render(villain_range)
    assert spot.ip_range == render(hero_range)
    assert spot.rake_rate == 0.0
    assert spot.bet_sizes == "50%, e, a"
    assert spot.max_iterations == 400


def test_build_spot_rejects_preflop():
    from poker_coach.domain.models import DecisionPoint

    scenario = scenario_at_flop().model_copy(
        update={
            "decision_point": DecisionPoint(street=Street.PREFLOP, actor_seat=0)
        }
    )
    hero_range, villain_range = ranges_for_spike()
    with pytest.raises(SolverUnsupportedError, match="postflop"):
        build_spot(scenario, hero_range=hero_range, villain_range=villain_range)


def test_build_spot_requires_ranges():
    scenario = scenario_at_flop()
    with pytest.raises(SolverUnsupportedError, match="ranges"):
        build_spot(scenario)


def test_range_to_string_uses_matrix_when_no_combos():
    spec = RangeSpec(
        range_id="m",
        name="matrix",
        version="1",
        source=RangeSource.CURATED,
        matrix_169={"AA": Decimal("1"), "AKs": Decimal("0.5"), "72o": Decimal("0")},
    )
    rendered = range_to_string(spec)
    assert "AA:1" in rendered
    assert "AKs:0.5" in rendered
    assert "72o" not in rendered


def test_spot_config_json_roundtrip():
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()
    spot = build_spot(scenario, hero_range=hero_range, villain_range=villain_range)
    config = json.loads(spot_to_config_json(spot))
    assert config["street"] == "flop"
    assert config["board"] == ["Ks", "7h", "2h"]
    assert config["starting_pot"] == 500
    assert config["effective_stack"] == 9750
    assert config["max_iterations"] == 400
    assert config["use_compression"] is False


# --- client & cache ----------------------------------------------------------


def test_client_with_injected_runner(spike_payload):
    calls: list[str] = []

    def runner(config_json: str) -> str:
        calls.append(config_json)
        return json.dumps(spike_payload)

    client = SidecarClient(runner=runner)
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()
    spot = build_spot(scenario, hero_range=hero_range, villain_range=villain_range)
    result = client.solve(spot)
    assert result.metadata.solver == "postflop-solver"
    assert "oop_range" in calls[0]
    assert spot_to_config_json(spot) == calls[0]


def test_solve_hash_deterministic_and_cache(tmp_path):
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()
    spot = build_spot(scenario, hero_range=hero_range, villain_range=villain_range)
    assert solve_hash(spot) == solve_hash(spot)

    cache = SolveCache(str(tmp_path / "solve-cache.sqlite3"))
    try:
        assert cache.get(spot) is None
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = parse_result(payload)
        cache.put(spot, result)
        cached = cache.get(spot)
        assert cached is not None
        assert cached.metadata.exploitability_chips == pytest.approx(2.3484, abs=1e-3)
        assert cached.root.actions == result.root.actions
    finally:
        cache.close()
