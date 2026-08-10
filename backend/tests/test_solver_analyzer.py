"""StrategyAnalyzer, evidence and artifact tests (offline, fixture-driven)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from poker_coach.analysis import analyze_scenario
from poker_coach.coach import TeachingToolGateway
from poker_coach.domain.models import (
    AnalysisLevel,
    RangeCombo,
    RangeSource,
    RangeSpec,
    ScenarioSpec,
)
from poker_coach.persistence.sqlite_store import SQLiteStore
from poker_coach.rules.pokerkit_adapter import PokerKitAdapter
from poker_coach.solver import (
    analyze,
    build_spot,
    parse_result,
    solve_result_to_artifact,
    solver_evidence_items,
)
from poker_coach.strategy import StrategyCatalog

FIXTURE = Path(__file__).parent / "fixtures" / "solve-output-spike1.json"


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


@pytest.fixture(scope="module")
def solved():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_result(payload)


# --- analyzer ----------------------------------------------------------------


def test_analyze_root_range_facts(solved):
    analysis = analyze(solved, hero_player=0)
    assert analysis.root.primary_action == "Check"
    assert analysis.root.range_bet_frequency == pytest.approx(0.322, abs=1e-3)
    assert analysis.root.action_spread >= 2
    assert 0 <= analysis.root.mixing_degree <= 1


def test_analyze_hand_shapes(solved):
    analysis = analyze(solved, hero_player=0)
    ak = next(h for h in analysis.hero_hands if h.combo == "AcKc")
    assert ak.primary_action == "Check"
    assert ak.primary_frequency == pytest.approx(0.662, abs=1e-3)
    assert ak.shape_class == "mixed_bet"  # TP mixes check/half-pot
    qq = next(h for h in analysis.hero_hands if h.combo == "AcQc")
    assert qq.shape_class == "check"  # overpair without backdoor is a pure check
    draw = next(h for h in analysis.hero_hands if h.combo == "5h4h")
    assert draw.shape_class == "bluff_bet"  # flush draw semibluff


def test_analyze_response_node(solved):
    analysis = analyze(solved, hero_player=1)
    assert analysis.response is not None
    assert analysis.response.primary_action in {"Call", "Fold", "Raise(625)"}
    ak = next(h for h in analysis.hero_hands if h.combo == "AdKc")
    assert ak.shape_class in {"mixed_bet", "check_dominant", "check"}


# --- evidence ----------------------------------------------------------------


def test_solver_evidence_items(solved):
    analysis = analyze(solved, hero_player=0)
    items = solver_evidence_items(solved, analysis)
    ids = [item.evidence_id for item in items]
    assert all(item_id.startswith("solver.") for item_id in ids)
    assert len(ids) == len(set(ids))
    assert all(item.source_level is AnalysisLevel.SOLVER_BACKED for item in items)
    assert "solver.exploitability" in ids
    exploitability = next(item for item in items if item.evidence_id == "solver.exploitability")
    assert exploitability.value == pytest.approx(2.3484, abs=1e-3)


# --- artifact + catalog ------------------------------------------------------


def test_solver_artifact_matches_exactly_and_opens_frequency_gate(solved):
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()
    scenario = scenario.model_copy(
        update={"hero_range": hero_range, "villain_range": villain_range}
    )
    spot = build_spot(
        scenario, hero_range=hero_range, villain_range=villain_range
    )
    analysis = analyze(solved, hero_player=0)
    artifact = solve_result_to_artifact(solved, scenario, spot, analysis)

    assert artifact.source_level is AnalysisLevel.SOLVER_BACKED
    assert "AGPL" in artifact.license
    assert artifact.recommendations
    assert all(
        rec.frequency is not None and rec.source_level is AnalysisLevel.SOLVER_BACKED
        for rec in artifact.recommendations
    )
    # ADR-0003 gate: EXACT match with frequencies -> can quote
    catalog = StrategyCatalog(artifacts=(artifact,))
    match = catalog.match(scenario)
    assert match.level.value == "exact"
    assert match.can_quote_frequencies is True
    assert match.source_level is AnalysisLevel.SOLVER_BACKED


def test_solver_artifact_registers_through_store(solved):
    scenario = scenario_at_flop()
    hero_range, villain_range = ranges_for_spike()
    scenario = scenario.model_copy(
        update={"hero_range": hero_range, "villain_range": villain_range}
    )
    spot = build_spot(scenario, hero_range=hero_range, villain_range=villain_range)
    analysis = analyze(solved, hero_player=0)
    artifact = solve_result_to_artifact(solved, scenario, spot, analysis)

    store = SQLiteStore(":memory:")
    store.register_strategy_artifacts((artifact,))
    row = store._connection.execute(
        "SELECT COUNT(*) FROM strategy_artifacts WHERE artifact_id = ?",
        (artifact.artifact_id,),
    ).fetchone()
    assert row[0] == 1
    # matching works from the registered artifact contract
    match = StrategyCatalog(artifacts=(artifact,)).match(scenario)
    assert match.can_quote_frequencies is True


# --- gateway -----------------------------------------------------------------


def test_gateway_exposes_solver_analysis_and_evidence(solved):
    scenario = scenario_at_flop()
    analysis_result = analyze_scenario(scenario, adapter=PokerKitAdapter())
    gateway = TeachingToolGateway(
        scenario, analysis_result, solver_result=solved
    )
    solver_view = gateway.get_solver_analysis()
    assert solver_view is not None
    assert solver_view.root.primary_action == "Check"

    bundle = gateway.get_evidence_bundle()
    solver_ids = [item.evidence_id for item in bundle.items if item.evidence_id.startswith("solver.")]
    assert "solver.exploitability" in solver_ids
    assert all(
        item.source_level is AnalysisLevel.SOLVER_BACKED
        for item in bundle.items
        if item.evidence_id.startswith("solver.")
    )


def test_gateway_without_solver_result_returns_none():
    scenario = scenario_at_flop()
    analysis_result = analyze_scenario(scenario, adapter=PokerKitAdapter())
    gateway = TeachingToolGateway(scenario, analysis_result)
    assert gateway.get_solver_analysis() is None
    bundle = gateway.get_evidence_bundle()
    assert not any(item.evidence_id.startswith("solver.") for item in bundle.items)
