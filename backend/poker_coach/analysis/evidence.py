"""Stage 3 orchestration: replay a node and build traceable evidence."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from poker_coach.domain.models import (
    ActionType,
    AnalysisLevel,
    EvidenceBundle,
    EvidenceItem,
    ScenarioSpec,
)
from poker_coach.rules import PokerKitAdapter

from .board import analyze_board
from .equity import EquityEngine
from .hand import analyze_hand
from .math import calculate_metrics
from .models import AnalysisResult, EquityResult, InvalidAnalysisInput
from .range_analysis import analyze_range, compare_ranges

ANALYSIS_VERSION = "analysis-core-0.1"


class EvidenceBundleBuilder:
    """Collect unique evidence items while keeping source levels explicit."""

    def __init__(self, *, version: str = ANALYSIS_VERSION):
        self.version = version
        self._items: list[EvidenceItem] = []
        self._ids: set[str] = set()

    def add(
        self,
        evidence_id: str,
        kind: str,
        value: Any,
        *,
        unit: str | None,
        source_level: AnalysisLevel,
        description: str,
        source_version: str | None = None,
    ) -> None:
        if evidence_id in self._ids:
            raise ValueError(f"duplicate evidence_id: {evidence_id}")
        self._ids.add(evidence_id)
        self._items.append(
            EvidenceItem(
                evidenceId=evidence_id,
                kind=kind,
                value=value,
                unit=unit,
                sourceLevel=source_level,
                sourceVersion=source_version or self.version,
                description=description,
            )
        )

    def build(self) -> EvidenceBundle:
        return EvidenceBundle(bundleVersion=self.version, items=tuple(self._items))


def analyze_scenario(
    scenario: ScenarioSpec,
    *,
    adapter: PokerKitAdapter | None = None,
    equity_engine: EquityEngine | None = None,
    cancel_event=None,
    timeout_seconds: float | None = None,
) -> AnalysisResult:
    adapter = adapter or PokerKitAdapter()
    prefix_length = scenario.decision_point.after_sequence
    prefix_scenario = scenario.model_copy(
        update={"action_history": scenario.action_history[:prefix_length]}
    )
    replay = adapter.replay(prefix_scenario)
    snapshot = replay.final_state
    villain_seat = next(seat.seat_id for seat in scenario.seats if seat.seat_id != scenario.hero_seat)
    metrics = calculate_metrics(
        snapshot,
        hero_seat=scenario.hero_seat,
        villain_seat=villain_seat,
        bet_amount=_last_bet_amount(prefix_scenario),
    )
    hand = analyze_hand(scenario.hero_hole_cards, snapshot.board)
    board = analyze_board(snapshot.board)
    engine = equity_engine or EquityEngine()
    warnings: list[str] = []
    equity: EquityResult | None = None
    range_analysis = None
    range_comparison = None

    if scenario.villain_range is not None:
        range_analysis = analyze_range(
            scenario.villain_range,
            snapshot.board,
            known_cards=tuple(scenario.hero_hole_cards) + snapshot.board,
        )
    elif scenario.villain_hole_cards is None:
        warnings.append("villain hole cards and villain range are missing; equity is unavailable")

    algorithm = scenario.assumptions.equity_algorithm
    trials = scenario.assumptions.simulation_trials or 10_000
    seed = scenario.assumptions.random_seed
    try:
        if scenario.hero_range is not None and scenario.villain_range is not None:
            equity = engine.evaluate_range_vs_range(
                scenario.hero_range,
                scenario.villain_range,
                snapshot.board,
                algorithm=algorithm,
                trials=trials,
                random_seed=seed,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )
            range_comparison = compare_ranges(
                scenario.hero_range,
                scenario.villain_range,
                snapshot.board,
                hero_known_cards=tuple(scenario.hero_hole_cards),
                villain_known_cards=tuple(scenario.villain_hole_cards or ()),
                hero_equity=equity.hero_equity,
            )
        elif scenario.villain_hole_cards is not None:
            equity = engine.evaluate_hand_vs_hand(
                scenario.hero_hole_cards,
                scenario.villain_hole_cards,
                snapshot.board,
                algorithm=algorithm,
                trials=trials,
                random_seed=seed,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )
        elif scenario.villain_range is not None:
            equity = engine.evaluate_hand_vs_range(
                scenario.hero_hole_cards,
                scenario.villain_range,
                snapshot.board,
                algorithm=algorithm,
                trials=trials,
                random_seed=seed,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )
    except InvalidAnalysisInput:
        raise

    builder = EvidenceBundleBuilder()
    _add_metrics(builder, metrics, rules_version=replay.rules_engine_version)
    _add_assumption_evidence(builder, scenario)
    builder.add(
        "rules.actor_seat",
        "actor_seat",
        snapshot.actor_seat,
        unit="seat",
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Current player with action",
        source_version=replay.rules_engine_version,
    )
    builder.add(
        "rules.legal_actions",
        "legal_actions",
        [action.value for action in snapshot.legal_actions.actions],
        unit=None,
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Actions accepted by the current rules state",
        source_version=replay.rules_engine_version,
    )
    builder.add(
        "hand.category",
        "hand_category",
        hand.category.value,
        unit=None,
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Hero's current best hand category",
    )
    builder.add(
        "hand.made_hand",
        "made_hand",
        hand.made_hand,
        unit=None,
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Hero's made-hand classification",
    )
    builder.add(
        "hand.draws",
        "draws",
        [draw.value for draw in hand.draws],
        unit=None,
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Detected one-card and backdoor draw labels",
    )
    builder.add(
        "hand.out_count",
        "out_count",
        hand.out_count,
        unit="cards",
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Candidate one-card outs under the current hand model",
    )
    builder.add(
        "board.labels",
        "board_texture",
        list(board.labels),
        unit=None,
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Deterministic public-board texture labels",
    )
    builder.add(
        "board.static_or_dynamic",
        "board_dynamics",
        board.static_or_dynamic,
        unit=None,
        source_level=AnalysisLevel.PRINCIPLE_ONLY,
        description="Heuristic static/dynamic board label",
    )
    builder.add(
        "board.nut_combo_count",
        "nut_combo_count",
        board.nut_combo_count,
        unit="combos",
        source_level=AnalysisLevel.ENUMERATED,
        description="Concrete hole-card combos producing the current top made hand category and tie-break key",
    )
    builder.add(
        "board.possible_nut_hands",
        "possible_nut_hands",
        list(board.possible_nut_hands),
        unit=None,
        source_level=AnalysisLevel.ENUMERATED,
        description="Current concrete hand categories reachable as the board's best made hand",
    )
    if range_analysis is not None:
        _add_range_evidence(builder, range_analysis)
    if range_comparison is not None:
        builder.add(
            "range.range_advantage",
            "range_advantage",
            range_comparison.range_advantage,
            unit="equity_share_difference",
            source_level=equity.source_level if equity else AnalysisLevel.PRINCIPLE_ONLY,
            description="Hero-relative weighted equity difference between ranges",
        )
        builder.add(
            "range.nut_advantage",
            "nut_advantage",
            range_comparison.nut_advantage,
            unit="share_difference",
            source_level=AnalysisLevel.PRINCIPLE_ONLY,
            description="Heuristic difference in high-made-hand range share",
        )
    if equity is not None:
        _add_equity_evidence(builder, equity)
    else:
        builder.add(
            "equity.status",
            "equity_status",
            "unavailable",
            unit=None,
            source_level=AnalysisLevel.PRINCIPLE_ONLY,
            description="Equity was not calculated because a villain hand or range is missing",
        )

    return AnalysisResult(
        analysisVersion=ANALYSIS_VERSION,
        scenarioHash=hashlib.sha256(scenario.to_json().encode("utf-8")).hexdigest(),
        rulesEngineVersion=replay.rules_engine_version,
        metrics=metrics,
        hand=hand,
        board=board,
        equity=equity,
        rangeAnalysis=range_analysis,
        rangeComparison=range_comparison,
        evidence=builder.build(),
        warnings=tuple(warnings),
    )


def _add_metrics(builder: EvidenceBundleBuilder, metrics, *, rules_version: str) -> None:
    values = (
        ("rules.pot", "pot", metrics.current_pot, "chips", "Current pot"),
        ("rules.call_cost", "call_cost", metrics.call_cost, "chips", "Cost to call"),
        ("math.pot_after_call", "pot_after_call", metrics.pot_after_call, "chips", "Pot after calling"),
        ("math.effective_stack", "effective_stack", metrics.effective_stack, "chips", "Effective remaining stack"),
        ("math.pot_odds", "pot_odds", metrics.pot_odds, "ratio", "Pot odds as a ratio"),
        ("math.required_equity", "required_equity", metrics.required_equity, "ratio", "Minimum equity required to call"),
        ("math.spr", "spr", metrics.spr, "ratio", "Stack-to-pot ratio"),
        ("math.risk_reward", "risk_reward_ratio", metrics.risk_reward_ratio, "ratio", "Call cost divided by current pot"),
        ("math.bet_to_pot", "bet_to_pot_ratio", metrics.bet_to_pot_ratio, "ratio", "Last bet divided by current pot"),
    )
    for evidence_id, kind, value, unit, description in values:
        if value is not None:
            builder.add(
                evidence_id,
                kind,
                value,
                unit=unit,
                source_level=AnalysisLevel.DETERMINISTIC,
                description=description,
                source_version=rules_version if evidence_id.startswith("rules.") else None,
            )


def _add_assumption_evidence(builder: EvidenceBundleBuilder, scenario: ScenarioSpec) -> None:
    assumptions = scenario.assumptions
    values = (
        ("assumptions.equity_algorithm", "equity_algorithm", assumptions.equity_algorithm.value, "algorithm"),
        ("assumptions.villain_range_source", "villain_range_source", assumptions.villain_range_source, None),
        ("assumptions.rake", "rake_assumption", assumptions.rake_assumption, None),
        ("assumptions.bet_sizing", "bet_sizing_assumption", assumptions.bet_sizing_assumption, None),
        ("assumptions.allow_donk", "allow_donk", assumptions.allow_donk, None),
        ("assumptions.allow_raise", "allow_raise", assumptions.allow_raise, None),
    )
    for evidence_id, kind, value, unit in values:
        builder.add(
            evidence_id,
            kind,
            value,
            unit=unit,
            source_level=AnalysisLevel.DETERMINISTIC,
            description=f"Analysis assumption: {kind}",
        )
    if assumptions.simulation_trials is not None:
        builder.add(
            "assumptions.simulation_trials",
            "simulation_trials",
            assumptions.simulation_trials,
            unit="trials",
            source_level=AnalysisLevel.DETERMINISTIC,
            description="Configured Monte Carlo trial count",
        )
    if assumptions.random_seed is not None:
        builder.add(
            "assumptions.random_seed",
            "random_seed",
            assumptions.random_seed,
            unit=None,
            source_level=AnalysisLevel.DETERMINISTIC,
            description="Configured random seed",
        )


def _add_range_evidence(builder: EvidenceBundleBuilder, analysis) -> None:
    for evidence_id, kind, value, unit, description in (
        ("range.total_combos", "combo_count", analysis.total_combos, "combos", "Valid concrete combos after card removal"),
        ("range.weighted_combos", "weighted_combo_count", analysis.weighted_combos, "weighted_combos", "Total remaining range weight"),
        ("range.value_combos", "value_combo_count", analysis.value_combos, "combos", "Heuristically classified value combos"),
        ("range.bluff_combos", "bluff_combo_count", analysis.bluff_combos, "combos", "Heuristically classified bluff candidates"),
        ("range.draw_combos", "draw_combo_count", analysis.draw_combos, "combos", "Combos with a detected draw"),
        ("range.blocked_combos", "blocked_combo_count", analysis.blocked_combos, "combos", "Combos removed by known cards"),
    ):
        builder.add(
            evidence_id,
            kind,
            value,
            unit=unit,
            source_level=AnalysisLevel.ENUMERATED,
            description=description,
        )


def _add_equity_evidence(builder: EvidenceBundleBuilder, equity: EquityResult) -> None:
    source = equity.source_level
    for evidence_id, kind, value, unit, description in (
        ("equity.hero", "hero_equity", equity.hero_equity, "ratio", "Hero showdown equity"),
        ("equity.villain", "villain_equity", equity.villain_equity, "ratio", "Villain showdown equity"),
        ("equity.tie", "tie_probability", equity.tie_probability, "ratio", "Probability of a split pot"),
        ("equity.trials", "equity_trials", equity.trials, "trials", "Number of evaluated runouts or samples"),
    ):
        builder.add(
            evidence_id,
            kind,
            value,
            unit=unit,
            source_level=source,
            description=description,
        )
    if equity.random_seed is not None:
        builder.add(
            "equity.random_seed",
            "random_seed",
            equity.random_seed,
            unit=None,
            source_level=source,
            description="Monte Carlo random seed",
        )
    if equity.confidence_interval is not None:
        builder.add(
            "equity.confidence_interval",
            "confidence_interval",
            list(equity.confidence_interval),
            unit="ratio",
            source_level=source,
            description="Approximate 95% confidence interval for Hero equity",
        )


def _last_bet_amount(scenario: ScenarioSpec) -> int | None:
    if not scenario.action_history:
        return None
    event = scenario.action_history[-1]
    if event.action_type in {ActionType.BET, ActionType.RAISE_TO}:
        return event.amount
    return None
