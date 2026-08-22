"""First-party, bounded HU-river CFR.

This module is deliberately isolated from the authoritative PokerKit replay
path.  Its input is a caller-provided *range projection*, never a live deck,
opponent hole cards, or future events.  It solves exactly one public tree:
``check -> (check | bet -> fold | call)`` and
``bet -> (fold | call)``.  It is a B-grade local approximation, not a GTO
claim and not a replacement for rules, legal-action, or settlement authority.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations
from threading import Event
from types import MappingProxyType
from typing import Callable, Literal, Mapping

from pydantic import TypeAdapter, ValidationError

from poker_coach.domain.models import Card, RangeCombo as DomainRangeCombo


ENGINE_VERSION = "riverline-l2-cfr/v1"
_ACTIONS: dict[str, tuple[str, ...]] = {
    "": ("check", "bet"),
    "c": ("check", "bet"),
    "b": ("fold", "call"),
    "cb": ("fold", "call"),
}
_CARD_ADAPTER = TypeAdapter(Card)


@dataclass(frozen=True)
class RangeCombo:
    """One weighted theoretical two-card combination in a safe range projection."""

    cards: tuple[str, str]
    weight: float

    def __post_init__(self) -> None:
        if len(self.cards) != 2:
            raise ValueError("range combo must contain exactly two cards")
        if self.weight <= 0:
            raise ValueError("range combo weight must be positive")


@dataclass(frozen=True)
class RiverBetTree:
    """The only supported no-rake river continuation, with one legal bet size."""

    bet_amount: int

    def __post_init__(self) -> None:
        if self.bet_amount <= 0:
            raise ValueError("bet_amount must be positive")


@dataclass(frozen=True)
class L2Budget:
    iterations: int
    soft_timeout_ms: int
    hard_timeout_ms: int

    def __post_init__(self) -> None:
        if self.iterations <= 0:
            raise ValueError("iterations must be positive")
        if self.soft_timeout_ms < 0 or self.hard_timeout_ms < self.soft_timeout_ms:
            raise ValueError("timeout budget must satisfy 0 <= soft <= hard")


@dataclass(frozen=True)
class L2RiverInput:
    """Immutable permission-safe local-solver input.

    ``ranges`` are projected distributions, not observed opponent cards.  The
    caller is responsible for deriving them only from actor-authorized public
    facts.  This engine never reads ObservationV1 or a PokerKit deck.
    """

    game_fingerprint: str
    tree_fingerprint: str
    range_fingerprint: str
    solver_version: str
    players: tuple[int, ...]
    acting_seat: int
    pot: int
    stacks: tuple[tuple[int, int], ...]
    board: tuple[str, ...]
    ranges: tuple[tuple[int, tuple[RangeCombo, ...]], ...]
    tree: RiverBetTree
    seed: int
    budget: L2Budget
    street: str = "river"
    projection_scope: Literal["public_range_projection"] = "public_range_projection"
    hero_hole_cards: tuple[str, str] | None = None
    solver_artifact_fingerprint: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if not all((self.game_fingerprint, self.tree_fingerprint, self.range_fingerprint, self.solver_version)):
            raise ValueError("all game/tree/range/version fingerprints are required")
        if len(self.players) != 2 or len(set(self.players)) != 2:
            # Accepted as input so callers receive a typed unsupported result.
            return
        if self.acting_seat != self.players[0]:
            raise ValueError("the root actor must be players[0]")
        if self.pot < 0:
            raise ValueError("pot cannot be negative")
        if len(self.board) != 5:
            raise ValueError("river input requires five public board cards")
        stacks = dict(self.stacks)
        projections = dict(self.ranges)
        # Incomplete public projections are a normal product-boundary miss.
        # Preserve the immutable input so ``solve_hu_river`` can return its
        # typed unsupported payload rather than throwing in a foreground path.
        if set(stacks) != set(self.players) or set(projections) != set(self.players):
            return
        if any(stack < 0 for stack in stacks.values()):
            raise ValueError("stacks cannot be negative")
        for combos in projections.values():
            if not combos:
                raise ValueError("every player needs a non-empty projected range")

    @property
    def fingerprint(self) -> str:
        material = {
            "game": self.game_fingerprint,
            "tree": self.tree_fingerprint,
            "range": self.range_fingerprint,
            "solver": self.solver_version,
            "players": self.players,
            "acting": self.acting_seat,
            "pot": self.pot,
            "stacks": self.stacks,
            "board": self.board,
            "ranges": tuple((seat, tuple((combo.cards, combo.weight) for combo in combos)) for seat, combos in self.ranges),
            "bet": self.tree.bet_amount,
            "seed": self.seed,
            "budget": asdict(self.budget),
            "street": self.street,
            "scope": self.projection_scope,
            "hero": self.hero_hole_cards,
            "solver_artifact": self.solver_artifact_fingerprint,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def tree_cache_key(self) -> str:
        """Cache identity for the whole solved tree, intentionally hero-free."""
        return replace(self, hero_hole_cards=None).fingerprint


@dataclass(frozen=True)
class L2Result:
    game_fingerprint: str
    tree_fingerprint: str
    range_fingerprint: str
    solver_version: str
    solver_artifact_fingerprint: str
    cache_key: str
    tree_cache_key: str
    players: tuple[int, int]
    street: str
    pot: int
    legal_sizes: Mapping[str, int]
    aggregate_action_frequencies: Mapping[str, float]
    action_frequencies: Mapping[str, float]
    recommendation_available: bool
    hero_decision_identity: str | None
    approximate_ev_chips: float
    ev_definition: str
    regret_bound_chips: float
    regret_definition: str
    iterations_completed: int
    iterations_requested: int
    seed: int
    elapsed_ms: float
    evidence_grade: Literal["B"]
    coverage_status: Literal["covered", "fallback"]
    source: str
    license: str
    tree_description: str
    degradation_reason: str | None = None
    cache_hit: bool = False


@dataclass(frozen=True)
class L2Unsupported:
    game_fingerprint: str
    tree_fingerprint: str
    range_fingerprint: str
    solver_version: str
    street: str
    players: tuple[int, ...]
    evidence_grade: Literal["unsupported"] = "unsupported"
    coverage_status: Literal["unsupported"] = "unsupported"
    reason: str = "unsupported"


class L2Cache:
    """Small process-local LRU cache; keys include every solver input dimension."""

    def __init__(self, *, max_entries: int = 32) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._items: OrderedDict[str, L2Result] = OrderedDict()

    def get(self, key: str) -> L2Result | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: str, value: L2Result) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


class L2SolverJobs:
    """Optional bounded background producer for cache misses.

    Callers may submit a supported L2 request and continue the live action
    path.  The configured solver budget remains the termination authority;
    this helper deliberately makes no machine-wide latency/SLA promise.
    """

    def __init__(self, *, cache: L2Cache | None = None, max_workers: int = 1) -> None:
        self._cache = cache or L2Cache()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="riverline-l2")

    def submit(self, source: L2RiverInput, *, cancel: Event | Callable[[], bool] | None = None) -> Future[L2Result | L2Unsupported]:
        return self._executor.submit(solve_hu_river, source, cache=self._cache, cancel=cancel)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)


def solve_hu_river(
    source: L2RiverInput,
    *,
    cache: L2Cache | None = None,
    cancel: Event | Callable[[], bool] | None = None,
) -> L2Result | L2Unsupported:
    """Run full-tree CFR over every compatible projected-range hand pair.

    This is not MCCFR sampling: each iteration traverses the complete finite
    chance support.  Card pairs incompatible with board or with each other are
    excluded, so blocker mass is normalized over only feasible worlds.
    """
    prepared, invalid = _prepare_input(source)
    if invalid is not None:
        return invalid
    assert prepared is not None
    source = prepared
    unsupported = _support_error(source)
    if unsupported is not None:
        return unsupported
    assert len(source.players) == 2
    if cache is not None:
        cached = cache.get(source.fingerprint)
        if cached is not None:
            return replace(cached, cache_hit=True, elapsed_ms=0.0)

    worlds = _compatible_worlds(source)
    if not worlds:
        raise ValueError("range projections have no card-unique compatible worlds")
    start = time.perf_counter()
    regrets: dict[tuple[int, tuple[str, str], str], dict[str, float]] = defaultdict(dict)
    strategy_sums: dict[tuple[int, tuple[str, str], str], dict[str, float]] = defaultdict(dict)
    completed = 0
    degradation: str | None = None
    for _ in range(source.budget.iterations):
        if _cancelled(cancel):
            degradation = "cancelled"
            break
        elapsed_ms = (time.perf_counter() - start) * 1_000
        if elapsed_ms >= source.budget.hard_timeout_ms:
            degradation = "hard_timeout"
            break
        if elapsed_ms >= source.budget.soft_timeout_ms:
            degradation = "soft_timeout"
            break
        for first, second, chance in worlds:
            _cfr(source, first, second, chance, "", 1.0, 1.0, regrets, strategy_sums)
        completed += 1

    elapsed_ms = (time.perf_counter() - start) * 1_000
    if completed == 0:
        return _fallback(source, elapsed_ms, degradation or "soft_timeout")
    aggregate_policy = _root_policy(source, worlds, regrets, strategy_sums)
    hero_policy = _hero_policy(source, strategy_sums)
    usable_policy = hero_policy or {}
    root_ev = sum(chance * _expected_value(source, first, second, "", aggregate_policy, regrets) for first, second, chance in worlds)
    max_regret = max((max(values.values(), default=0.0) for values in regrets.values()), default=0.0)
    result = L2Result(
        game_fingerprint=source.game_fingerprint,
        tree_fingerprint=source.tree_fingerprint,
        range_fingerprint=source.range_fingerprint,
        solver_version=source.solver_version,
        solver_artifact_fingerprint=source.solver_artifact_fingerprint,
        cache_key=source.fingerprint,
        tree_cache_key=source.tree_cache_key,
        players=(source.players[0], source.players[1]),
        street="river",
        pot=source.pot,
        legal_sizes=MappingProxyType({"bet": source.tree.bet_amount}),
        aggregate_action_frequencies=MappingProxyType(aggregate_policy),
        action_frequencies=MappingProxyType(usable_policy),
        recommendation_available=hero_policy is not None,
        hero_decision_identity=_hero_identity(source),
        approximate_ev_chips=root_ev,
        ev_definition="zero_sum_chips_from_root_player",
        regret_bound_chips=max_regret / completed,
        regret_definition="maximum positive counterfactual regret divided by completed iterations; a convergence signal, not exact exploitability",
        iterations_completed=completed,
        iterations_requested=source.budget.iterations,
        seed=source.seed,
        elapsed_ms=elapsed_ms,
        evidence_grade="B",
        coverage_status="covered" if degradation is None and hero_policy is not None else "fallback",
        source="Riverline first-party bounded full-tree CFR",
        license="LicenseRef-Riverline-Internal",
        tree_description="HU river: check->check|bet->fold|call; bet->fold|call",
        degradation_reason=degradation or _hero_unavailable_reason(source),
    )
    if cache is not None and degradation is None:
        cache.put(source.fingerprint, result)
    return result


def to_benchmark_candidate(
    result: L2Result,
    *,
    selected_action: str,
    public_range: Mapping[str, float],
) -> dict[str, object]:
    """Adapt the safe aggregate output to R9-00's frozen benchmark payload."""
    if not result.recommendation_available:
        raise ValueError("L2 aggregate diagnostics cannot be used as a hero recommendation")
    if selected_action not in result.action_frequencies:
        raise ValueError("selected action is not present in L2 policy")
    return {
        "fingerprints": {"spotId": "l2-exact-tied-river", "gameFingerprint": result.game_fingerprint, "treeFingerprint": result.tree_fingerprint, "rangeFingerprint": result.range_fingerprint, "policyFingerprint": result.solver_version},
        "evidenceGrade": result.evidence_grade,
        "coverageStatus": result.coverage_status,
        "actionFrequencies": dict(result.action_frequencies),
        "sizings": dict(result.legal_sizes),
        "selectedAction": selected_action,
        "evDefinition": result.ev_definition,
        "range": dict(public_range),
    }


def _support_error(source: L2RiverInput) -> L2Unsupported | None:
    common = dict(game_fingerprint=source.game_fingerprint, tree_fingerprint=source.tree_fingerprint, range_fingerprint=source.range_fingerprint, solver_version=source.solver_version, street=source.street, players=source.players)
    if len(source.players) != 2:
        return L2Unsupported(**common, reason="multiway_unsupported")
    if source.street != "river":
        return L2Unsupported(**common, reason="street_unsupported")
    if not isinstance(source.tree, RiverBetTree):
        return L2Unsupported(**common, reason="tree_or_stack_unsupported")
    stacks = dict(source.stacks)
    if set(stacks) != set(source.players) or set(dict(source.ranges)) != set(source.players):
        return L2Unsupported(**common, reason="range_unsupported")
    if source.tree.bet_amount > min(stacks.values()):
        return L2Unsupported(**common, reason="tree_or_stack_unsupported")
    return None


def _invalid(source: L2RiverInput, reason: str) -> L2Unsupported:
    return L2Unsupported(
        game_fingerprint=source.game_fingerprint,
        tree_fingerprint=source.tree_fingerprint,
        range_fingerprint=source.range_fingerprint,
        solver_version=source.solver_version,
        street=source.street,
        players=source.players,
        reason=reason,
    )


def _canonical_card(card: str) -> str:
    """Normalize through the domain's canonical deck validator."""
    try:
        canonical = _CARD_ADAPTER.validate_python(card)
    except ValidationError as exc:
        raise ValueError("card_invalid") from exc
    return canonical


def _canonical_combo(cards: tuple[str, str]) -> tuple[str, str]:
    canonical = tuple(_canonical_card(card) for card in cards)
    try:
        combo = DomainRangeCombo(cards=canonical, weight="1")
    except ValidationError as exc:
        raise ValueError("card_collision_unsupported") from exc
    if tuple(cards) != canonical:
        # Check duplication on canonical physical cards first: ``2c`` +
        # ``2C`` is a collision, not two distinct range/deck cards.
        raise ValueError("card_not_canonical")
    return combo.cards


def _prepare_input(source: L2RiverInput) -> tuple[L2RiverInput | None, L2Unsupported | None]:
    """Normalize through domain Card, then reject every physical collision."""
    try:
        board = tuple(_canonical_card(card) for card in source.board)
        if len(set(board)) != len(board):
            return None, _invalid(source, "card_collision_unsupported")
        if tuple(source.board) != board:
            return None, _invalid(source, "card_not_canonical")
        normalized_ranges: list[tuple[int, tuple[RangeCombo, ...]]] = []
        for seat, combos in source.ranges:
            normalized_combos = tuple(
                RangeCombo(cards=_canonical_combo(combo.cards), weight=combo.weight)
                for combo in combos
            )
            if any(set(board) & set(combo.cards) for combo in normalized_combos):
                return None, _invalid(source, "card_collision_unsupported")
            normalized_ranges.append((seat, normalized_combos))
        hero = None if source.hero_hole_cards is None else _canonical_combo(source.hero_hole_cards)
        if hero is not None and set(board) & set(hero):
            return None, _invalid(source, "card_collision_unsupported")
    except ValueError as exc:
        return None, _invalid(source, str(exc))
    return replace(source, board=board, ranges=tuple(normalized_ranges), hero_hole_cards=hero), None


def _compatible_worlds(source: L2RiverInput) -> tuple[tuple[RangeCombo, RangeCombo, float], ...]:
    first, second = (dict(source.ranges)[seat] for seat in source.players)
    worlds = [(a, b, a.weight * b.weight) for a in first for b in second if not (set(a.cards) & set(b.cards))]
    total = sum(weight for _, _, weight in worlds)
    return tuple((a, b, weight / total) for a, b, weight in worlds) if total else ()


def _strategy(regrets: Mapping[tuple[int, tuple[str, str], str], Mapping[str, float]], key: tuple[int, tuple[str, str], str], actions: tuple[str, ...]) -> dict[str, float]:
    positive = [max(0.0, regrets.get(key, {}).get(action, 0.0)) for action in actions]
    total = sum(positive)
    return {action: value / total if total else 1.0 / len(actions) for action, value in zip(actions, positive)}


def _cfr(source: L2RiverInput, first: RangeCombo, second: RangeCombo, chance: float, history: str, reach_first: float, reach_second: float, regrets: dict, strategy_sums: dict) -> float:
    terminal = _terminal_utility(source, first, second, history)
    if terminal is not None:
        return terminal
    actor_index = 0 if history in ("", "cb") else 1
    combo = first if actor_index == 0 else second
    key = (actor_index, combo.cards, history)
    actions = _ACTIONS[history]
    strategy = _strategy(regrets, key, actions)
    values = {action: _cfr(source, first, second, chance, history + action[0], reach_first * (strategy[action] if actor_index == 0 else 1.0), reach_second * (strategy[action] if actor_index == 1 else 1.0), regrets, strategy_sums) for action in actions}
    node_value = sum(strategy[action] * values[action] for action in actions)
    own_reach, other_reach = (reach_first, reach_second) if actor_index == 0 else (reach_second, reach_first)
    for action in actions:
        actor_value = values[action] if actor_index == 0 else -values[action]
        actor_node_value = node_value if actor_index == 0 else -node_value
        regrets[key][action] = regrets[key].get(action, 0.0) + chance * other_reach * (actor_value - actor_node_value)
        strategy_sums[key][action] = strategy_sums[key].get(action, 0.0) + chance * own_reach * strategy[action]
    return node_value


def _terminal_utility(source: L2RiverInput, first: RangeCombo, second: RangeCombo, history: str) -> float | None:
    if history == "cc":
        return _showdown_utility(source.pot, first.cards, second.cards, source.board)
    if history == "bc":
        return _showdown_utility(source.pot + 2 * source.tree.bet_amount, first.cards, second.cards, source.board)
    if history == "cbc":
        return _showdown_utility(source.pot + 2 * source.tree.bet_amount, first.cards, second.cards, source.board)
    if history == "bf":
        return float(source.pot)
    if history == "cbf":
        return float(-source.pot)
    return None


def _root_policy(source: L2RiverInput, worlds: tuple[tuple[RangeCombo, RangeCombo, float], ...], regrets: Mapping, sums: Mapping) -> dict[str, float]:
    weighted = {action: 0.0 for action in _ACTIONS[""]}
    for first, _second, chance in worlds:
        key = (0, first.cards, "")
        values = sums.get(key, {})
        total = sum(values.get(action, 0.0) for action in _ACTIONS[""])
        strategy = ({action: values.get(action, 0.0) / total for action in _ACTIONS[""]} if total else _strategy(regrets, key, _ACTIONS[""]))
        for action in weighted:
            weighted[action] += chance * strategy[action]
    total = sum(weighted.values())
    return {action: weighted[action] / total for action in weighted}


def _hero_policy(source: L2RiverInput, sums: Mapping) -> dict[str, float] | None:
    if source.hero_hole_cards is None:
        return None
    hero = source.hero_hole_cards
    root_combos = dict(source.ranges).get(source.acting_seat, ())
    if hero not in {combo.cards for combo in root_combos}:
        return None
    values = sums.get((0, hero, ""), {})
    total = sum(values.get(action, 0.0) for action in _ACTIONS[""])
    if total <= 0:
        return None
    return {action: values.get(action, 0.0) / total for action in _ACTIONS[""]}


def _hero_identity(source: L2RiverInput) -> str | None:
    if source.hero_hole_cards is None:
        return None
    # Hashing keeps decision/cache binding without exposing hero cards in any
    # output, repr, telemetry, benchmark candidate, or recommendation payload.
    material = f"{source.fingerprint}|{source.hero_hole_cards[0]}|{source.hero_hole_cards[1]}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _hero_unavailable_reason(source: L2RiverInput) -> str | None:
    if source.hero_hole_cards is None:
        return "hero_combo_required"
    if source.hero_hole_cards not in {combo.cards for combo in dict(source.ranges).get(source.acting_seat, ())}:
        return "hero_combo_outside_projection"
    return None


def _expected_value(source: L2RiverInput, first: RangeCombo, second: RangeCombo, history: str, root_policy: Mapping[str, float], regrets: Mapping) -> float:
    terminal = _terminal_utility(source, first, second, history)
    if terminal is not None:
        return terminal
    actor_index = 0 if history in ("", "cb") else 1
    actions = _ACTIONS[history]
    strategy = root_policy if history == "" else _strategy(regrets, (actor_index, (first if actor_index == 0 else second).cards, history), actions)
    return sum(strategy[action] * _expected_value(source, first, second, history + action[0], root_policy, regrets) for action in actions)


def _fallback(source: L2RiverInput, elapsed_ms: float, reason: str) -> L2Result:
    return L2Result(game_fingerprint=source.game_fingerprint, tree_fingerprint=source.tree_fingerprint, range_fingerprint=source.range_fingerprint, solver_version=source.solver_version, solver_artifact_fingerprint=source.solver_artifact_fingerprint, cache_key=source.fingerprint, tree_cache_key=source.tree_cache_key, players=(source.players[0], source.players[1]), street="river", pot=source.pot, legal_sizes=MappingProxyType({"bet": source.tree.bet_amount}), aggregate_action_frequencies=MappingProxyType({}), action_frequencies=MappingProxyType({}), recommendation_available=False, hero_decision_identity=_hero_identity(source), approximate_ev_chips=0.0, ev_definition="zero_sum_chips_from_root_player", regret_bound_chips=0.0, regret_definition="not available: no CFR iteration completed", iterations_completed=0, iterations_requested=source.budget.iterations, seed=source.seed, elapsed_ms=elapsed_ms, evidence_grade="B", coverage_status="fallback", source="Riverline first-party bounded full-tree CFR", license="LicenseRef-Riverline-Internal", tree_description="HU river: check->check|bet->fold|call; bet->fold|call", degradation_reason=reason)


def _cancelled(cancel: Event | Callable[[], bool] | None) -> bool:
    if cancel is None:
        return False
    return cancel.is_set() if isinstance(cancel, Event) else bool(cancel())


def _showdown_utility(pot: int, first: tuple[str, str], second: tuple[str, str], board: tuple[str, ...]) -> float:
    left, right = _best_hand((*first, *board)), _best_hand((*second, *board))
    return float(pot if left > right else -pot if left < right else 0)


def _best_hand(cards: tuple[str, ...]) -> tuple[int, ...]:
    return max(_five_card_value(combo) for combo in combinations((_parse_card(card) for card in cards), 5))


def _parse_card(card: str) -> tuple[int, str]:
    if len(card) != 2 or card[0].upper() not in "23456789TJQKA" or card[1].lower() not in "cdhs":
        raise ValueError(f"invalid card: {card!r}")
    return ("23456789TJQKA".index(card[0].upper()) + 2, card[1].lower())


def _five_card_value(cards: tuple[tuple[int, str], ...]) -> tuple[int, ...]:
    ranks = sorted((rank for rank, _ in cards), reverse=True)
    counts = sorted(((ranks.count(rank), rank) for rank in set(ranks)), reverse=True)
    flush = len({suit for _, suit in cards}) == 1
    unique = sorted(set(ranks), reverse=True)
    straight_high = 5 if unique == [14, 5, 4, 3, 2] else (unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4 else 0)
    if flush and straight_high:
        return (8, straight_high)
    if counts[0][0] == 4:
        return (7, counts[0][1], counts[1][1])
    if counts[0][0] == 3 and counts[1][0] == 2:
        return (6, counts[0][1], counts[1][1])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if counts[0][0] == 3:
        return (3, counts[0][1], *sorted((rank for rank in ranks if rank != counts[0][1]), reverse=True))
    pairs = sorted((rank for count, rank in counts if count == 2), reverse=True)
    if len(pairs) == 2:
        return (2, *pairs, next(rank for rank in ranks if rank not in pairs))
    if len(pairs) == 1:
        return (1, pairs[0], *sorted((rank for rank in ranks if rank != pairs[0]), reverse=True))
    return (0, *ranks)
