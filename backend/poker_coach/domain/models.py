"""Stable, PokerKit-independent contracts for the poker coach.

The models in this module are API/domain contracts, not poker rule logic. Rule
replay is deliberately kept for the adapter layer in a later stage.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, ClassVar, Mapping

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)


SCENARIO_SCHEMA_VERSION = 1
_CARD_PATTERN = re.compile(r"^(?:[2-9TJQKA][shdc])$")
_STARTING_HAND_PATTERN = re.compile(r"^(?:[2-9TJQKA])(?:[2-9TJQKA])(?:[so])?$")
_RANK_ORDER = {rank: index for index, rank in enumerate("23456789TJQKA")}
_SUIT_ORDER = {suit: index for index, suit in enumerate("cdhs")}


def _normalize_card(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("card must be a string such as Ah")
    card = value.strip()
    if len(card) != 2:
        raise ValueError("card must contain exactly rank and suit")
    card = card[0].upper() + card[1].lower()
    if not _CARD_PATTERN.fullmatch(card):
        raise ValueError(f"invalid card: {value!r}")
    return card


def _normalize_starting_hand(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("starting hand must be a string such as AKs or QQ")
    hand = value.strip().upper()
    if len(hand) == 3:
        hand = hand[:2] + hand[2].lower()
    if not _STARTING_HAND_PATTERN.fullmatch(hand):
        raise ValueError(f"invalid starting hand notation: {value!r}")
    first, second = hand[0], hand[1]
    if first == second:
        if len(hand) != 2:
            raise ValueError("pairs cannot have suited or offsuit suffixes")
        return hand
    if len(hand) != 3:
        raise ValueError("non-pairs must specify suited or offsuit")
    suffix = hand[2].lower()
    if _RANK_ORDER[first] < _RANK_ORDER[second]:
        first, second = second, first
    return f"{first}{second}{suffix}"


def _normalize_weight(value: Any) -> Decimal:
    if isinstance(value, float):
        raise ValueError("weights must be decimal strings, integers, or Decimal values")
    try:
        weight = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - Decimal supplies the detail
        raise ValueError("weight must be a decimal value") from exc
    if not weight.is_finite() or weight < 0 or weight > 1:
        raise ValueError("weight must be between 0 and 1")
    if abs(weight.as_tuple().exponent) > 8:
        raise ValueError("weight supports at most 8 decimal places")
    return weight


Card = Annotated[str, BeforeValidator(_normalize_card)]
StartingHand = Annotated[str, BeforeValidator(_normalize_starting_hand)]
Weight = Annotated[Decimal, BeforeValidator(_normalize_weight)]
ChipAmount = Annotated[StrictInt, Field(ge=0)]
PositiveChipAmount = Annotated[StrictInt, Field(gt=0)]
SeatNumber = Annotated[StrictInt, Field(ge=0, le=5)]
SequenceNumber = Annotated[StrictInt, Field(ge=1)]


class DomainModel(BaseModel):
    """Base model with strict fields and deterministic JSON output."""

    model_config = ConfigDict(
        alias_generator=lambda field_name: "".join(
            part if index == 0 else part[:1].upper() + part[1:]
            for index, part in enumerate(field_name.split("_"))
        ),
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=False)

    def to_json(self) -> str:
        """Return stable JSON independent of input dictionary insertion order."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


class GameVariant(str, Enum):
    NLHE = "nlhe"


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    COMPLETE = "complete"


class SeatPosition(str, Enum):
    BUTTON = "button"
    BIG_BLIND = "big_blind"


class ActionType(str, Enum):
    POST_BLIND = "post_blind"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE_TO = "raise_to"
    FOLD = "fold"
    ALL_IN = "all_in"
    DEAL_FLOP = "deal_flop"
    DEAL_TURN = "deal_turn"
    DEAL_RIVER = "deal_river"
    SHOWDOWN = "showdown"
    AWARD_POT = "award_pot"


class AmountType(str, Enum):
    NONE = "none"
    BY = "by"
    TO = "to"
    COST = "cost"
    AWARD = "award"


class RangeSource(str, Enum):
    DEFAULT_PREFLOP = "default_preflop"
    USER_DEFINED = "user_defined"
    CURATED = "curated"
    IMPORTED = "imported"


class ScenarioSource(str, Enum):
    MANUAL = "manual"
    IMPORTED = "imported"
    FUTURE_VISION = "future_vision"


class AnalysisLevel(str, Enum):
    DETERMINISTIC = "deterministic"
    ENUMERATED = "enumerated"
    SIMULATED = "simulated"
    CURATED = "curated"
    SOLVER_BACKED = "solver_backed"
    PRINCIPLE_ONLY = "principle_only"


class EquityAlgorithm(str, Enum):
    EXACT_ENUMERATION = "exact_enumeration"
    MONTE_CARLO = "monte_carlo"


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class RakeConfig(DomainModel):
    enabled: bool = False
    percent_bps: Annotated[StrictInt, Field(ge=0, le=10_000)] = 0
    cap: ChipAmount = 0

    @model_validator(mode="after")
    def validate_enabled_fields(self) -> RakeConfig:
        if not self.enabled and (self.percent_bps != 0 or self.cap != 0):
            raise ValueError("disabled rake must have zero percent_bps and cap")
        if self.enabled and self.percent_bps == 0:
            raise ValueError("enabled rake must define a positive percent_bps")
        return self


class SeatSpec(DomainModel):
    seat_id: SeatNumber
    starting_stack: PositiveChipAmount
    position: SeatPosition


class RangeCombo(DomainModel):
    cards: tuple[Card, Card]
    weight: Weight

    @field_validator("cards")
    @classmethod
    def validate_cards(cls, cards: tuple[str, str]) -> tuple[str, str]:
        if cards[0] == cards[1]:
            raise ValueError("a combo cannot contain the same card twice")
        return tuple(sorted(cards, key=_card_sort_key))  # type: ignore[return-value]


class RangeSpec(DomainModel):
    range_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    source: RangeSource
    is_default_assumption: bool = False
    matrix_169: dict[StartingHand, Weight] = Field(default_factory=dict)
    combos: tuple[RangeCombo, ...] = ()
    dead_cards: tuple[Card, ...] = ()

    @field_validator("dead_cards")
    @classmethod
    def validate_dead_cards(cls, cards: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(cards)) != len(cards):
            raise ValueError("dead_cards cannot contain duplicates")
        return tuple(sorted(cards, key=_card_sort_key))

    @model_validator(mode="after")
    def validate_range(self) -> RangeSpec:
        if not self.matrix_169 and not self.combos:
            raise ValueError("range must contain matrix_169 entries or concrete combos")
        dead = set(self.dead_cards)
        seen: set[tuple[str, str]] = set()
        for combo in self.combos:
            key = tuple(combo.cards)
            if key in seen:
                raise ValueError(f"duplicate concrete combo: {key}")
            seen.add(key)
            if dead.intersection(combo.cards):
                raise ValueError(f"combo {key} contains a dead card")
        return self


class ActionEvent(DomainModel):
    action_id: str = Field(min_length=1, max_length=128)
    sequence: SequenceNumber
    street: Street
    actor_seat: SeatNumber
    action_type: ActionType
    amount: ChipAmount | None = None
    amount_type: AmountType = AmountType.NONE
    pot_before: ChipAmount | None = None
    stack_before: ChipAmount | None = None
    timestamp: str | None = None
    source: ScenarioSource = ScenarioSource.MANUAL
    confidence: Weight | None = None
    correction_metadata: dict[str, str] = Field(default_factory=dict)

    _AMOUNT_ACTIONS: ClassVar[frozenset[ActionType]] = frozenset(
        {
            ActionType.POST_BLIND,
            ActionType.CALL,
            ActionType.BET,
            ActionType.RAISE_TO,
            ActionType.ALL_IN,
            ActionType.AWARD_POT,
        }
    )

    @model_validator(mode="after")
    def validate_amount_semantics(self) -> ActionEvent:
        if self.action_type in self._AMOUNT_ACTIONS and self.amount is None:
            raise ValueError(f"{self.action_type.value} requires amount")
        if self.action_type not in self._AMOUNT_ACTIONS and (
            self.amount is not None or self.amount_type is not AmountType.NONE
        ):
            raise ValueError(f"{self.action_type.value} cannot carry an amount")
        expected = {
            ActionType.POST_BLIND: AmountType.BY,
            ActionType.CALL: AmountType.COST,
            ActionType.BET: AmountType.BY,
            ActionType.RAISE_TO: AmountType.TO,
            ActionType.ALL_IN: AmountType.TO,
            ActionType.AWARD_POT: AmountType.AWARD,
        }
        if self.action_type in expected and self.amount_type is not expected[self.action_type]:
            raise ValueError(
                f"{self.action_type.value} requires amount_type={expected[self.action_type].value}"
            )
        return self


class DecisionPoint(DomainModel):
    street: Street
    actor_seat: SeatNumber
    after_sequence: Annotated[StrictInt, Field(ge=0)] = 0


class BetSizeSpec(DomainModel):
    label: str = Field(min_length=1, max_length=64)
    amount: ChipAmount | None = None
    pot_fraction_bps: Annotated[StrictInt, Field(ge=0, le=100_000)] | None = None

    @model_validator(mode="after")
    def validate_one_sizing(self) -> BetSizeSpec:
        if (self.amount is None) == (self.pot_fraction_bps is None):
            raise ValueError("exactly one of amount or pot_fraction_bps is required")
        return self


class AnalysisAssumptions(DomainModel):
    villain_range_source: str = "unspecified"
    rake_assumption: str = "no_rake"
    bet_sizing_assumption: str = "user_supplied"
    allow_donk: bool = True
    allow_raise: bool = True
    equity_algorithm: EquityAlgorithm = EquityAlgorithm.EXACT_ENUMERATION
    simulation_trials: Annotated[StrictInt, Field(gt=0)] | None = None
    random_seed: Annotated[StrictInt, Field(ge=0)] | None = None
    strategy_library_version: str | None = None
    solver_version: str | None = None
    similar_scenario_match: bool = False

    @model_validator(mode="after")
    def validate_equity_settings(self) -> AnalysisAssumptions:
        if self.equity_algorithm is EquityAlgorithm.MONTE_CARLO:
            if self.simulation_trials is None or self.random_seed is None:
                raise ValueError("Monte Carlo requires simulation_trials and random_seed")
        return self


class ScenarioSpec(DomainModel):
    schema_version: Annotated[StrictInt, Field(ge=1)] = SCENARIO_SCHEMA_VERSION
    game_variant: GameVariant = GameVariant.NLHE
    table_size: Annotated[StrictInt, Field(ge=2, le=6)] = 2
    small_blind: PositiveChipAmount = 50
    big_blind: PositiveChipAmount = 100
    ante: ChipAmount = 0
    rake_config: RakeConfig = Field(default_factory=RakeConfig)
    button_seat: SeatNumber = 0
    hero_seat: SeatNumber = 0
    seats: tuple[SeatSpec, ...] = Field(min_length=2, max_length=6)
    hero_hole_cards: tuple[Card, Card]
    board: tuple[Card, ...] = Field(default=(), max_length=5)
    action_history: tuple[ActionEvent, ...] = ()
    decision_point: DecisionPoint = Field(
        default_factory=lambda: DecisionPoint(street=Street.PREFLOP, actor_seat=0)
    )
    hero_range: RangeSpec | None = None
    villain_range: RangeSpec | None = None
    allowed_bet_sizes: tuple[BetSizeSpec, ...] = ()
    assumptions: AnalysisAssumptions = Field(default_factory=AnalysisAssumptions)
    source: ScenarioSource = ScenarioSource.MANUAL
    tags: tuple[str, ...] = ()

    @field_validator("hero_hole_cards")
    @classmethod
    def validate_hole_cards(cls, cards: tuple[str, str]) -> tuple[str, str]:
        if cards[0] == cards[1]:
            raise ValueError("hero_hole_cards cannot contain duplicates")
        return tuple(sorted(cards, key=_card_sort_key))  # type: ignore[return-value]

    @field_validator("board")
    @classmethod
    def validate_board_cards(cls, cards: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(cards)) != len(cards):
            raise ValueError("board cannot contain duplicate cards")
        return cards

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(tags)) != len(tags):
            raise ValueError("tags cannot contain duplicates")
        return tuple(sorted(tags))

    @model_validator(mode="after")
    def validate_scenario(self) -> ScenarioSpec:
        if self.schema_version != SCENARIO_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version={self.schema_version}; supported={SCENARIO_SCHEMA_VERSION}"
            )
        if self.game_variant is not GameVariant.NLHE:
            raise ValueError("only NLHE is supported by the MVP")
        if self.table_size != 2:
            raise ValueError("MVP currently supports table_size=2; 6-max is a future extension")
        if self.big_blind <= self.small_blind:
            raise ValueError("big_blind must be greater than small_blind")
        if len(self.seats) != self.table_size:
            raise ValueError("number of seats must equal table_size")
        seat_ids = [seat.seat_id for seat in self.seats]
        if len(set(seat_ids)) != len(seat_ids):
            raise ValueError("seat IDs must be unique")
        if self.hero_seat not in seat_ids or self.button_seat not in seat_ids:
            raise ValueError("hero_seat and button_seat must reference existing seats")
        positions = {seat.position for seat in self.seats}
        if positions != {SeatPosition.BUTTON, SeatPosition.BIG_BLIND}:
            raise ValueError("HU seats must have exactly one button and one big_blind position")
        if next(seat for seat in self.seats if seat.position is SeatPosition.BUTTON).seat_id != self.button_seat:
            raise ValueError("button_seat does not match the button-position seat")

        sequences = [event.sequence for event in self.action_history]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("action_history sequence must be contiguous and start at 1")
        if self.decision_point.after_sequence > len(self.action_history):
            raise ValueError("decision_point.after_sequence exceeds action_history")

        known_cards = set(self.hero_hole_cards).union(self.board)
        for range_name, range_spec in (
            ("hero_range", self.hero_range),
            ("villain_range", self.villain_range),
        ):
            if range_spec is None:
                continue
            for combo in range_spec.combos:
                if known_cards.intersection(combo.cards):
                    raise ValueError(f"{range_name} combo contains a known card: {combo.cards}")

        labels = [size.label for size in self.allowed_bet_sizes]
        if len(set(labels)) != len(labels):
            raise ValueError("allowed_bet_sizes labels must be unique")
        return self

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> ScenarioSpec:
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid scenario JSON: {exc.msg}") from exc
        if not isinstance(raw, Mapping):
            raise ValueError("scenario JSON must contain an object")
        version = raw.get("schemaVersion")
        if version != SCENARIO_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported or missing schemaVersion={version!r}; supported={SCENARIO_SCHEMA_VERSION}"
            )
        return cls.model_validate(raw)


class EvidenceItem(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    value: Any
    unit: str | None = None
    source_level: AnalysisLevel
    source_version: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)


class EvidenceBundle(DomainModel):
    bundle_version: str = "1"
    items: tuple[EvidenceItem, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids(self) -> EvidenceBundle:
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique within a bundle")
        return self

    def ids(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.items)


class EvidenceReference(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=128)


class TeachingText(DomainModel):
    text: str = Field(min_length=1)
    evidence_references: tuple[EvidenceReference, ...] = ()
    contains_numbers: bool = False

    @model_validator(mode="after")
    def require_references_for_numbers(self) -> TeachingText:
        if self.contains_numbers and not self.evidence_references:
            raise ValueError("numeric teaching text requires at least one evidence reference")
        return self


class RecommendedAction(DomainModel):
    action: str = Field(min_length=1, max_length=64)
    frequency: Weight | None = None
    ev: Decimal | None = None
    evidence_references: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def require_references_for_quantities(self) -> RecommendedAction:
        if (self.frequency is not None or self.ev is not None) and not self.evidence_references:
            raise ValueError("frequency and EV require evidence references")
        return self


class PracticeQuestion(DomainModel):
    prompt: TeachingText
    expected_evidence_references: tuple[EvidenceReference, ...] = ()


class TeachingResponse(DomainModel):
    response_version: str = "1"
    summary: TeachingText
    recommended_actions: tuple[RecommendedAction, ...] = ()
    recommendation_basis: tuple[TeachingText, ...] = ()
    assumptions: tuple[TeachingText, ...] = ()
    key_reasons: tuple[TeachingText, ...] = ()
    alternative_lines: tuple[TeachingText, ...] = ()
    future_street_plan: tuple[TeachingText, ...] = ()
    common_mistake: TeachingText | None = None
    concept_tags: tuple[str, ...] = ()
    uncertainty: TeachingText
    evidence_references: tuple[EvidenceReference, ...] = ()
    follow_up_question: str | None = None
    practice_question: PracticeQuestion | None = None

    def validate_evidence_references(self, bundle: EvidenceBundle) -> None:
        """Raise when a teaching response cites evidence outside its bundle."""

        references: list[EvidenceReference] = list(self.evidence_references)
        references.extend(self.summary.evidence_references)
        references.extend(self.uncertainty.evidence_references)
        for action in self.recommended_actions:
            references.extend(action.evidence_references)
        for group in (
            self.recommendation_basis,
            self.assumptions,
            self.key_reasons,
            self.alternative_lines,
            self.future_street_plan,
        ):
            for text in group:
                references.extend(text.evidence_references)
        if self.common_mistake:
            references.extend(self.common_mistake.evidence_references)
        if self.practice_question:
            references.extend(self.practice_question.expected_evidence_references)
            references.extend(self.practice_question.prompt.evidence_references)
        missing = sorted({reference.evidence_id for reference in references} - bundle.ids())
        if missing:
            raise ValueError(f"teaching response references unknown evidence: {missing}")


class LegalActions(DomainModel):
    actor_seat: SeatNumber | None = None
    actions: tuple[ActionType, ...] = ()
    call_amount: ChipAmount | None = None
    min_raise_to: ChipAmount | None = None
    max_raise_to: ChipAmount | None = None
    explanations: dict[str, str] = Field(default_factory=dict)


class StateSnapshot(DomainModel):
    street: Street
    actor_seat: SeatNumber | None = None
    pot: ChipAmount
    stacks: dict[SeatNumber, ChipAmount]
    bets: dict[SeatNumber, ChipAmount]
    hand_in_progress: bool
    legal_actions: LegalActions = Field(default_factory=LegalActions)


class ReplayResult(DomainModel):
    rules_engine: str
    rules_engine_version: str
    snapshots: tuple[StateSnapshot, ...]
    final_state: StateSnapshot


class DomainIssue(DomainModel):
    code: str
    message: str
    path: tuple[str | int, ...] = ()
    severity: IssueSeverity


class ValidationReport(DomainModel):
    valid: bool
    errors: tuple[DomainIssue, ...] = ()
    warnings: tuple[DomainIssue, ...] = ()
    normalized_scenario: ScenarioSpec | None = None

    @classmethod
    def for_payload(cls, payload: Mapping[str, Any]) -> ValidationReport:
        try:
            scenario = ScenarioSpec.model_validate(payload)
        except ValidationError as exc:
            issues = tuple(
                DomainIssue(
                    code="invalid_scenario",
                    message=error.get("msg", "invalid value"),
                    path=tuple(error.get("loc", ())),
                    severity=IssueSeverity.ERROR,
                )
                for error in exc.errors()
            )
            return cls(valid=False, errors=issues)
        return cls(valid=True, normalized_scenario=scenario)


def _card_sort_key(card: str) -> tuple[int, int]:
    return _RANK_ORDER[card[0]], _SUIT_ORDER[card[1]]
