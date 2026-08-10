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
from poker_coach.strategy.catalog import StrategyCatalog
from poker_coach.strategy.models import StrategyMatch

from .board import analyze_board
from .equity import EquityEngine
from .hand import analyze_hand
from .math import calculate_metrics
from .models import AnalysisResult, EquityResult, InvalidAnalysisInput, MultiwayEquityResult
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
    strategy_catalog: StrategyCatalog | None = None,
) -> AnalysisResult:
    adapter = adapter or PokerKitAdapter()
    prefix_length = scenario.decision_point.after_sequence
    prefix_scenario = scenario.model_copy(
        update={"action_history": scenario.action_history[:prefix_length]}
    )
    replay = adapter.replay_to_decision(scenario)
    snapshot = replay.final_state
    multiway = scenario.table_size > 2
    if multiway:
        villain_seat = None
    else:
        villain_seat = next(
            seat.seat_id for seat in scenario.seats if seat.seat_id != scenario.hero_seat
        )
    metrics = calculate_metrics(
        snapshot,
        hero_seat=scenario.hero_seat,
        villain_seat=villain_seat,
        bet_amount=_last_bet_amount(prefix_scenario),
    )
    strategy_match = (strategy_catalog or StrategyCatalog()).match(scenario)
    warnings: list[str] = []
    hand = analyze_hand(scenario.hero_hole_cards, snapshot.board) if scenario.hero_hole_cards else None
    board = analyze_board(snapshot.board)
    engine = equity_engine or EquityEngine()
    equity: EquityResult | None = None
    multiway_equity: MultiwayEquityResult | None = None
    range_analysis = None
    range_comparison = None

    algorithm = scenario.assumptions.equity_algorithm
    trials = scenario.assumptions.simulation_trials or 10_000
    seed = scenario.assumptions.random_seed

    if multiway:
        multiway_equity = _analyze_multiway_equity(
            scenario,
            snapshot,
            engine,
            algorithm=algorithm,
            trials=trials,
            random_seed=seed,
            cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,
        )
        if multiway_equity is None:
            warnings.append(
                "multiway equity is unavailable: every active player needs "
                "known hole cards or a range"
            )
    else:
        if scenario.hero_hole_cards is None:
            # A fresh hand (no hero cards yet) is a legitimate starting point:
            # range-vs-range equity still works, hand-based analysis degrades.
            warnings.append("hero hole cards are missing; hand analysis is unavailable")
        elif scenario.villain_range is not None:
            range_analysis = analyze_range(
                scenario.villain_range,
                snapshot.board,
                known_cards=tuple(scenario.hero_hole_cards) + snapshot.board,
            )
        elif scenario.villain_hole_cards is None:
            warnings.append(
                "villain hole cards and villain range are missing; equity is unavailable"
            )

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
                if scenario.hero_hole_cards is not None:
                    range_comparison = compare_ranges(
                        scenario.hero_range,
                        scenario.villain_range,
                        snapshot.board,
                        hero_known_cards=tuple(scenario.hero_hole_cards),
                        villain_known_cards=tuple(scenario.villain_hole_cards or ()),
                        hero_equity=equity.hero_equity,
                    )
            elif scenario.villain_hole_cards is not None and scenario.hero_hole_cards is not None:
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
            elif scenario.villain_range is not None and scenario.hero_hole_cards is not None:
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
    if hand is not None:
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
        for evidence_id, kind, value, description in (
            ("hand.overcards", "overcards", list(hand.overcards), "Hero hole cards above the current board high card"),
            ("hand.straight_outs", "straight_outs", list(hand.straight_outs), "Cards that complete a detected straight path"),
            ("hand.flush_outs", "flush_outs", list(hand.flush_outs), "Cards that complete a detected flush path"),
            ("hand.out_cards", "out_cards", list(hand.out_cards), "Union of detected straight and flush outs"),
            ("hand.counterfeit_risk", "counterfeit_risk_cards", list(hand.counterfeit_risk_cards), "Cards that may weaken or counterfeit the current made hand"),
        ):
            builder.add(
                evidence_id,
                kind,
                value,
                unit="cards",
                source_level=AnalysisLevel.DETERMINISTIC,
                description=description,
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
    builder.add(
        "board.next_street_change_cards",
        "next_street_change_cards",
        list(board.next_street_change_cards),
        unit="cards",
        source_level=AnalysisLevel.DETERMINISTIC,
        description="Turn or river cards that change the detected board texture category",
    )
    builder.add(
        "board.possible_nut_combos",
        "possible_nut_combos",
        [list(combo) for combo in board.possible_nut_combos],
        unit="combos",
        source_level=AnalysisLevel.ENUMERATED,
        description="Concrete hole-card combinations producing the current top board-relative hand key",
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
        builder.add(
            "range.equity_distribution",
            "equity_distribution",
            range_comparison.equity_distribution,
            unit="ratio",
            source_level=equity.source_level if equity else AnalysisLevel.PRINCIPLE_ONLY,
            description="Distribution of value and draw shares across the two analyzed ranges",
        )
        builder.add(
            "range.comparison_heuristic",
            "range_comparison_heuristic",
            range_comparison.heuristic,
            unit=None,
            source_level=AnalysisLevel.DETERMINISTIC,
            description="Whether range comparison uses heuristic structure labels",
        )
    if equity is not None:
        _add_equity_evidence(builder, equity)
    elif multiway_equity is not None:
        builder.add(
            "equity.multiway_by_seat",
            "multiway_equity",
            {
                str(seat): str(share)
                for seat, share in sorted(multiway_equity.equity_by_seat.items())
            },
            unit="equity_share",
            source_level=multiway_equity.source_level,
            description="Per-seat showdown equity shares across live players",
        )
    else:
        builder.add(
            "equity.status",
            "equity_status",
            "unavailable",
            unit=None,
            source_level=AnalysisLevel.PRINCIPLE_ONLY,
            description="Equity was not calculated because a villain hand or range is missing",
        )
    _add_strategy_evidence(builder, strategy_match)

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
        strategyMatch=strategy_match,
        multiwayEquity=multiway_equity,
        evidence=builder.build(),
        warnings=tuple(warnings),
    )


def _analyze_multiway_equity(
    scenario: ScenarioSpec,
    snapshot,
    engine: EquityEngine,
    *,
    algorithm,
    trials: int,
    random_seed: int | None,
    cancel_event=None,
    timeout_seconds: float | None = None,
) -> MultiwayEquityResult | None:
    """N-player equity over the live seats at the decision point.

    Every live player must contribute either known hole cards or a range;
    a live player without either makes the result misleading, so the
    calculation is skipped with a warning instead.
    """
    live = [seat for seat in snapshot.stacks if seat not in snapshot.folded_seats]
    if scenario.hero_seat not in live:
        return None
    players: list[tuple[int, object]] = []
    for seat in sorted(live):
        cards = scenario.known_hole_cards_by_seat.get(seat)
        if cards is not None and len(cards) == 2:
            players.append((seat, tuple(cards)))
            continue
        seat_range = scenario.ranges_by_seat.get(seat)
        if seat_range is not None:
            players.append((seat, seat_range))
            continue
        return None
    if len(players) < 2:
        return None
    try:
        return engine.evaluate_multiway(
            players,
            snapshot.board,
            algorithm=algorithm,
            trials=trials,
            random_seed=random_seed,
            cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,
        )
    except InvalidAnalysisInput:
        return None


def _add_metrics(builder: EvidenceBundleBuilder, metrics, *, rules_version: str) -> None:
    values = (
        ("rules.pot", "pot", metrics.current_pot, "chips", "Current pot"),
        (
            "rules.active_players",
            "active_player_count",
            metrics.active_player_count,
            "players",
            "Players still live at the decision point",
        ),
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
        ("assumptions.strategy_library_version", "strategy_library_version", assumptions.strategy_library_version, None),
        ("assumptions.solver_version", "solver_version", assumptions.solver_version, None),
        ("assumptions.similar_scenario_match", "similar_scenario_match", assumptions.similar_scenario_match, None),
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
    for side, range_spec in (("hero", scenario.hero_range), ("villain", scenario.villain_range)):
        if range_spec is None:
            continue
        builder.add(
            f"assumptions.{side}_range_id",
            "range_id",
            range_spec.range_id,
            unit=None,
            source_level=AnalysisLevel.DETERMINISTIC,
            description=f"{side.title()} range identifier",
            source_version=range_spec.version,
        )
        builder.add(
            f"assumptions.{side}_range_provenance",
            "range_source",
            range_spec.source.value,
            unit=None,
            source_level=AnalysisLevel.DETERMINISTIC,
            description=f"{side.title()} range provenance",
            source_version=range_spec.version,
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
        ("range.blocked_weight", "blocked_weight", analysis.blocked_weight, "weighted_combos", "Range weight removed by known cards"),
        ("range.blocker_cards", "blocker_cards", list(analysis.blocker_cards), "cards", "Known cards used for card-removal analysis"),
        ("range.polarity", "range_polarity", analysis.polarity, None, "Heuristic value/bluff polarity classification"),
        ("range.heuristic", "range_heuristic", analysis.heuristic, None, "Whether this range classification is heuristic"),
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


def _add_strategy_evidence(builder: EvidenceBundleBuilder, match: StrategyMatch) -> None:
    source = match.source_level
    for evidence_id, kind, value, description in (
        (
            "strategy.match_level",
            "strategy_match_level",
            match.level.value,
            "Strategy catalog match level; approximate matches are not precise strategy data",
        ),
        (
            "strategy.similarity",
            "strategy_similarity",
            match.similarity,
            "Similarity score against the selected strategy artifact",
        ),
        (
            "strategy.can_quote_frequencies",
            "strategy_frequency_permission",
            match.can_quote_frequencies,
            "Whether this match may expose quantitative strategy data",
        ),
        (
            "strategy.differences",
            "strategy_differences",
            [difference.to_dict() for difference in match.differences],
            "Differences between the scenario and selected artifact",
        ),
        (
            "strategy.recommendations",
            "strategy_recommendations",
            [recommendation.to_dict() for recommendation in match.recommendations],
            "Recommendations supplied by the matched strategy artifact",
        ),
    ):
        builder.add(
            evidence_id,
            kind,
            value,
            unit="ratio" if evidence_id == "strategy.similarity" else None,
            source_level=source,
            description=description,
            source_version=match.library_version,
        )


def _last_bet_amount(scenario: ScenarioSpec) -> int | None:
    if not scenario.action_history:
        return None
    event = scenario.action_history[-1]
    if event.action_type in {ActionType.BET, ActionType.RAISE_TO}:
        return event.amount
    return None
