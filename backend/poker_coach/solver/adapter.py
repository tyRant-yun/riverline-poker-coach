"""Solver adapter: ScenarioSpec <-> SolverSpot and solver output -> SolveResult.

The adapter owns every mapping between the Poker Coach domain and the
normalized solver contract. It performs no solving itself; the sidecar is
reached through ``SidecarClient`` (or a cache / job worker).

Validation performed here mirrors the import spec (docs/solver-import-spec.md):
frequency normalization, action legality at the dumped nodes, dead-card
filtering and finite numbers.
"""

from __future__ import annotations

import json
import math
from typing import Any

from poker_coach.domain.models import (
    Card,
    RangeCombo,
    RangeSpec,
    ScenarioSpec,
    Street,
)
from poker_coach.rules.pokerkit_adapter import PokerKitAdapter

from .types import (
    SolveMetadata,
    SolverNode,
    SolverSpot,
    SolverUnsupportedError,
    SolverHand,
    SolveResult,
)

_FREQUENCY_TOLERANCE = 1e-6


def range_to_string(range_spec: RangeSpec) -> str:
    """Render a RangeSpec as the solver range notation (combo:weight list).

    Explicit combos win; the 169 matrix is used when no combos are set.
    Dead cards are excluded defensively.
    """
    dead = set(range_spec.dead_cards)
    entries: list[str] = []
    if range_spec.combos:
        for combo in range_spec.combos:
            if any(card in dead for card in combo.cards):
                continue
            if combo.weight <= 0:
                continue
            entries.append(f"{combo.cards[0]}{combo.cards[1]}:{_format_weight(combo.weight)}")
    else:
        for hand, weight in range_spec.matrix_169.items():
            if weight <= 0:
                continue
            entries.append(f"{hand}:{_format_weight(weight)}")
    if not entries:
        raise SolverUnsupportedError("range has no playable combos")
    return ",".join(entries)


def _format_weight(weight: Any) -> str:
    value = float(weight)
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def build_spot(
    scenario: ScenarioSpec,
    *,
    hero_range: RangeSpec | None = None,
    villain_range: RangeSpec | None = None,
    replay: Any | None = None,
    bet_sizes: str | None = None,
    raise_sizes: str = "2.5x",
    max_iterations: int = 400,
    target_exploitability_frac: float = 0.005,
) -> SolverSpot:
    """Map a postflop ScenarioSpec (plus ranges) to a normalized solver spot."""
    if scenario.decision_point.street not in (Street.FLOP, Street.TURN, Street.RIVER):
        raise SolverUnsupportedError(
            f"solver supports postflop only; got {scenario.decision_point.street.value}"
        )
    if scenario.table_size != 2:
        # The sidecar is a heads-up postflop solver. A decision point with
        # more than two active players is out of scope (multiway analysis is
        # available, solver is not) — see Phase 8E for the HU bridge.
        raise SolverUnsupportedError(
            "solver supports heads-up decision points only; multiway spots are not solvable"
        )
    adapter = PokerKitAdapter()
    replay = replay or adapter.replay_to_decision(scenario)
    state = replay.final_state
    if len(state.board) < 3:
        raise SolverUnsupportedError("solver requires at least a flop board")

    oop_seat = 1 - scenario.button_seat if scenario.table_size == 2 else None
    hero_seat = scenario.hero_seat
    villain_seat = 1 - hero_seat if scenario.table_size == 2 else None

    hero_range = hero_range or scenario.hero_range
    villain_range = villain_range or scenario.villain_range
    if hero_range is None or villain_range is None:
        raise SolverUnsupportedError("solver requires both hero and villain ranges")

    oop_range_spec = hero_range if hero_seat == oop_seat else villain_range
    ip_range_spec = villain_range if hero_seat == oop_seat else hero_range

    board = tuple(state.board[:3])
    turn = state.board[3] if len(state.board) > 3 else None
    river = state.board[4] if len(state.board) > 4 else None

    rake_rate, rake_cap = 0.0, 0.0
    if scenario.rake_config.enabled:
        rake_rate = scenario.rake_config.percent_bps / 10_000.0
        rake_cap = float(scenario.rake_config.cap)

    effective_stack = min(state.stacks.values())

    return SolverSpot(
        street=scenario.decision_point.street,
        board=(board[0], board[1], board[2]),
        turn=turn,
        river=river,
        oop_range=range_to_string(oop_range_spec),
        ip_range=range_to_string(ip_range_spec),
        starting_pot=int(state.pot),
        effective_stack=int(effective_stack),
        rake_rate=rake_rate,
        rake_cap=rake_cap,
        bet_sizes=bet_sizes or _bet_sizes_from_scenario(scenario, int(state.pot)),
        raise_sizes=raise_sizes,
        max_iterations=max_iterations,
        target_exploitability_frac=target_exploitability_frac,
    )


def _bet_sizes_from_scenario(scenario: ScenarioSpec, pot: int) -> str:
    fractions: list[str] = []
    for size in scenario.allowed_bet_sizes:
        if size.pot_fraction_bps is not None and size.pot_fraction_bps > 0:
            fractions.append(f"{size.pot_fraction_bps / 100:.0f}%")
    if not fractions:
        return "50%, e, a"
    return ",".join(sorted(set(fractions), key=_pct_key)) + ", a"


def _pct_key(value: str) -> float:
    return float(value.rstrip("%"))


def parse_result(raw: dict[str, Any]) -> SolveResult:
    """Parse and validate the sidecar's normalized output JSON."""
    metadata = _parse_metadata(raw.get("metadata", {}))
    root = _parse_node(raw["root"])
    response_node = _parse_node(raw["response_node"]) if raw.get("response_node") else None
    return SolveResult(metadata=metadata, root=root, response_node=response_node)


def _parse_metadata(raw: dict[str, Any]) -> SolveMetadata:
    required = ("solver", "version", "street", "exploitabilityChips", "targetExploitabilityChips")
    missing = [name for name in required if name not in raw]
    if missing:
        raise SolverUnsupportedError(f"solve metadata missing: {', '.join(missing)}")
    if not math.isfinite(float(raw["exploitabilityChips"])):
        raise SolverUnsupportedError("exploitability must be finite")
    return SolveMetadata(
        solver=str(raw["solver"]),
        version=str(raw["version"]),
        street=str(raw["street"]),
        max_iterations=int(raw.get("maxIterations", 0)),
        exploitability_chips=float(raw["exploitabilityChips"]),
        target_exploitability_chips=float(raw["targetExploitabilityChips"]),
        solve_time_ms=int(raw.get("solveTimeMs", 0)),
        memory_usage_gb=float(raw.get("memoryUsageGb", 0.0)),
        memory_usage_compressed_gb=float(raw.get("memoryUsageCompressedGb", 0.0)),
        compressed=bool(raw.get("compressed", False)),
    )


def _parse_node(raw: dict[str, Any]) -> SolverNode:
    actions = tuple(str(action) for action in raw["actions"])
    if not actions:
        raise SolverUnsupportedError("solver node has no actions")
    hands = tuple(_parse_hand(hand, actions) for hand in raw["hands"])
    if not hands:
        raise SolverUnsupportedError("solver node has no hands")
    return SolverNode(
        actions=actions,
        player=int(raw["player"]),
        hands=hands,
    )


def _parse_hand(raw: dict[str, Any], actions: tuple[str, ...]) -> SolverHand:
    strategy_raw = raw["strategy"]
    if isinstance(strategy_raw, list):
        if len(strategy_raw) != len(actions):
            raise SolverUnsupportedError(
                f"strategy array length {len(strategy_raw)} != actions {len(actions)}"
            )
        strategy = {action: float(freq) for action, freq in zip(actions, strategy_raw)}
    elif isinstance(strategy_raw, dict):
        strategy = {action: float(freq) for action, freq in strategy_raw.items()}
    else:
        raise SolverUnsupportedError("strategy must be a list or dict")

    total = sum(strategy.values())
    if abs(total - 1.0) > _FREQUENCY_TOLERANCE:
        raise SolverUnsupportedError(
            f"strategy frequencies sum to {total:.6f} (expected 1.0) for {raw.get('combo')}"
        )
    for action, freq in strategy.items():
        if freq < -_FREQUENCY_TOLERANCE or freq > 1.0 + _FREQUENCY_TOLERANCE:
            raise SolverUnsupportedError(f"frequency {freq} out of range for {raw.get('combo')}")
    weight = float(raw["weight"])
    if weight < 0:
        raise SolverUnsupportedError("negative combo weight")
    return SolverHand(
        combo=str(raw["combo"]),
        weight=weight,
        equity=float(raw["equity"]),
        ev=float(raw["ev"]),
        strategy=strategy,
    )


def spot_to_config_json(spot: SolverSpot) -> str:
    """Serialize a SolverSpot to the sidecar's config file format."""
    payload = {
        "street": spot.street.value,
        "board": list(spot.board),
        "turn": spot.turn,
        "river": spot.river,
        "oop_range": spot.oop_range,
        "ip_range": spot.ip_range,
        "starting_pot": spot.starting_pot,
        "effective_stack": spot.effective_stack,
        "rake_rate": spot.rake_rate,
        "rake_cap": spot.rake_cap,
        "bet_sizes": spot.bet_sizes,
        "raise_sizes": spot.raise_sizes,
        "add_allin_threshold": spot.add_allin_threshold,
        "force_allin_threshold": spot.force_allin_threshold,
        "merging_threshold": spot.merging_threshold,
        "max_iterations": spot.max_iterations,
        "target_exploitability_frac": spot.target_exploitability_frac,
        "use_compression": False,
        "dump_response_to_action": spot.dump_response_to_action,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
