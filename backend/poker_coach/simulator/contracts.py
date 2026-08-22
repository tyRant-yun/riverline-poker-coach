"""Versioned, UI-independent contracts for the simulator boundary."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StrictInt,
    model_validator,
)

from poker_coach.domain.models import Card, DomainModel, Street


SchemaVersionV1 = Literal[1]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
SeatId = Annotated[StrictInt, Field(ge=0, le=7)]


class SimulatorContractV1(DomainModel):
    """Immutable base for contracts that cross simulator ports."""

    model_config = ConfigDict(frozen=True)
    schema_version: SchemaVersionV1 = 1


class EventSourceV1(str, Enum):
    GAME_ORCHESTRATOR = "game_orchestrator"
    IMPORT = "import"
    FIXTURE = "fixture"
    MIGRATION = "migration"


class SimulatorActionV1(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


class AmountSemanticsV1(str, Enum):
    NONE = "none"
    COST = "cost"
    BY = "by"
    TO = "to"


class LegalActionV1(SimulatorContractV1):
    """One legal action and its chip-denominated inclusive bounds.

    A call amount is the incremental cost, a bet amount is chips added by the
    action, and a raise amount is the actor's total street commitment.
    """

    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    min_amount: NonNegativeInt | None = None
    max_amount: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_amount_bounds(self) -> LegalActionV1:
        expected = {
            SimulatorActionV1.FOLD: AmountSemanticsV1.NONE,
            SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
            SimulatorActionV1.CALL: AmountSemanticsV1.COST,
            SimulatorActionV1.BET: AmountSemanticsV1.BY,
            SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
        }[self.action]
        if self.amount_semantics is not expected:
            raise ValueError(
                f"{self.action.value} requires amount_semantics={expected.value}"
            )
        if expected is AmountSemanticsV1.NONE:
            if self.min_amount is not None or self.max_amount is not None:
                raise ValueError(f"{self.action.value} must not carry amount bounds")
            return self
        if self.min_amount is None or self.max_amount is None:
            raise ValueError(f"{self.action.value} requires inclusive amount bounds")
        if self.min_amount <= 0 or self.max_amount < self.min_amount:
            raise ValueError("amount bounds must satisfy 0 < min_amount <= max_amount")
        if self.action is SimulatorActionV1.CALL and self.min_amount != self.max_amount:
            raise ValueError("call requires one exact cost (min_amount == max_amount)")
        return self

    def accepts(self, *, action: SimulatorActionV1, amount: int | None) -> bool:
        if action is not self.action:
            return False
        if self.amount_semantics is AmountSemanticsV1.NONE:
            return amount is None
        if amount is None or self.min_amount is None or self.max_amount is None:
            return False
        return self.min_amount <= amount <= self.max_amount


class PublicActionV1(DomainModel):
    """A public player action included in an agent observation."""

    model_config = ConfigDict(frozen=True)
    sequence: Annotated[StrictInt, Field(ge=1)]
    street: Street
    actor_seat: SeatId
    action: SimulatorActionV1
    amount: NonNegativeInt | None = None
    amount_semantics: AmountSemanticsV1 = AmountSemanticsV1.NONE

    @model_validator(mode="after")
    def validate_amount(self) -> PublicActionV1:
        expected = {
            SimulatorActionV1.FOLD: AmountSemanticsV1.NONE,
            SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
            SimulatorActionV1.CALL: AmountSemanticsV1.COST,
            SimulatorActionV1.BET: AmountSemanticsV1.BY,
            SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
        }[self.action]
        if self.amount_semantics is not expected:
            raise ValueError(
                f"{self.action.value} requires amount_semantics={expected.value}"
            )
        if expected is AmountSemanticsV1.NONE and self.amount is not None:
            raise ValueError(f"{self.action.value} cannot carry an amount")
        if expected is not AmountSemanticsV1.NONE and (
            self.amount is None or self.amount <= 0
        ):
            raise ValueError(f"{self.action.value} requires a positive amount")
        return self


class ObservationV1(SimulatorContractV1):
    """Information available to one acting agent; no omniscient state."""

    hand_id: str = Field(min_length=1, max_length=128)
    sequence: NonNegativeInt
    observer_seat: SeatId
    table_size: Annotated[StrictInt, Field(ge=2, le=8)]
    button_seat: SeatId
    street: Street
    own_hole_cards: tuple[Card, Card]
    board: tuple[Card, ...] = Field(default=(), max_length=5)
    pot: NonNegativeInt
    stacks: dict[int, NonNegativeInt]
    street_commitments: dict[int, NonNegativeInt]
    active_seats: tuple[SeatId, ...]
    folded_seats: tuple[SeatId, ...] = ()
    public_actions: tuple[PublicActionV1, ...] = ()
    legal_actions: tuple[LegalActionV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_visibility_projection(self) -> ObservationV1:
        seats = set(range(self.table_size))
        if self.observer_seat not in seats or self.button_seat not in seats:
            raise ValueError("observer_seat and button_seat must reference occupied seats")
        active = set(self.active_seats)
        folded = set(self.folded_seats)
        participants = active | folded
        if active & folded or not participants.issubset(seats):
            raise ValueError("active_seats and folded_seats must be disjoint table seats")
        if set(self.stacks) != participants or set(self.street_commitments) != participants:
            raise ValueError("stack and commitment maps must contain every hand participant")
        if self.button_seat not in participants:
            raise ValueError("button_seat must reference a hand participant")
        if self.observer_seat not in active:
            raise ValueError("an acting observer must be active")
        visible_cards = (*self.own_hole_cards, *self.board)
        if len(visible_cards) != len(set(visible_cards)):
            raise ValueError("own hole cards and board cannot overlap")
        if any(action.actor_seat not in participants for action in self.public_actions):
            raise ValueError("public action references a non-participant seat")
        sequences = [action.sequence for action in self.public_actions]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("public actions must be uniquely ordered by sequence")
        actions = [legal.action for legal in self.legal_actions]
        if len(actions) != len(set(actions)):
            raise ValueError("legal actions must contain each action at most once")
        return self


class BotAttemptStatusV1(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    INVALID_ACTION = "invalid_action"
    POLICY_FALLBACK = "policy_fallback"


class BotAttemptV1(DomainModel):
    """One provider attempt retained as decision provenance."""

    model_config = ConfigDict(frozen=True)
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    status: BotAttemptStatusV1
    latency_ms: Annotated[FiniteFloat, Field(ge=0)]
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    error_message: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_error_provenance(self) -> BotAttemptV1:
        if self.status is BotAttemptStatusV1.SUCCESS and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("successful attempts cannot carry an error")
        if self.status is not BotAttemptStatusV1.SUCCESS and self.error_code is None:
            raise ValueError("failed attempts require error_code provenance")
        return self


class BotDecisionV1(SimulatorContractV1):
    """A provider decision after runtime validation and fallback handling."""

    action: SimulatorActionV1
    amount: NonNegativeInt | None = None
    amount_semantics: AmountSemanticsV1 = AmountSemanticsV1.NONE
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    latency_ms: Annotated[FiniteFloat, Field(ge=0)]
    confidence: Annotated[FiniteFloat, Field(ge=0, le=1)] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    degraded: bool = False
    fallback_reason: str | None = Field(default=None, min_length=1, max_length=256)
    attempts: tuple[BotAttemptV1, ...] = ()

    @model_validator(mode="after")
    def validate_decision(self) -> BotDecisionV1:
        expected = {
            SimulatorActionV1.FOLD: AmountSemanticsV1.NONE,
            SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
            SimulatorActionV1.CALL: AmountSemanticsV1.COST,
            SimulatorActionV1.BET: AmountSemanticsV1.BY,
            SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
        }[self.action]
        if self.amount_semantics is not expected:
            raise ValueError(
                f"{self.action.value} requires amount_semantics={expected.value}"
            )
        if expected is AmountSemanticsV1.NONE and self.amount is not None:
            raise ValueError(f"{self.action.value} cannot carry an amount")
        if expected is not AmountSemanticsV1.NONE and (
            self.amount is None or self.amount <= 0
        ):
            raise ValueError(f"{self.action.value} requires a positive amount")
        if self.degraded:
            if self.fallback_reason is None:
                raise ValueError("degraded decisions require fallback_reason")
            if not self.attempts or all(
                attempt.status is BotAttemptStatusV1.SUCCESS for attempt in self.attempts
            ):
                raise ValueError("degraded decisions require failed-attempt provenance")
        elif self.fallback_reason is not None:
            raise ValueError("non-degraded decisions cannot carry fallback_reason")
        return self


class ContractProvenanceV1(DomainModel):
    producer: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    causation_id: str | None = Field(default=None, min_length=1, max_length=128)


class HandStartedPayloadV1(DomainModel):
    kind: Literal["hand_started"] = "hand_started"
    ruleset: Literal["nlhe"] = "nlhe"
    table_size: Annotated[StrictInt, Field(ge=2, le=8)]
    button_seat: SeatId
    small_blind: PositiveInt
    big_blind: PositiveInt
    ante: NonNegativeInt = 0
    rake_bps: NonNegativeInt = 0
    starting_stacks: dict[int, NonNegativeInt]
    active_seat_ids: tuple[SeatId, ...] = ()
    rng_seed: NonNegativeInt

    @model_validator(mode="before")
    @classmethod
    def default_active_seats(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        if "activeSeatIds" in values or "active_seat_ids" in values:
            return values
        stacks = values.get("startingStacks", values.get("starting_stacks"))
        if not isinstance(stacks, dict):
            return values
        return {**values, "activeSeatIds": tuple(sorted(int(seat) for seat in stacks))}

    @model_validator(mode="after")
    def validate_table(self) -> HandStartedPayloadV1:
        if self.button_seat >= self.table_size:
            raise ValueError("button_seat must reference an occupied seat")
        if self.big_blind <= self.small_blind:
            raise ValueError("big_blind must be greater than small_blind")
        if sorted(self.starting_stacks) != list(range(self.table_size)):
            raise ValueError("starting_stacks must contain contiguous seats 0..table_size-1")
        if len(self.active_seat_ids) < 2:
            raise ValueError("active_seat_ids must contain at least two seats")
        if tuple(sorted(set(self.active_seat_ids))) != self.active_seat_ids:
            raise ValueError("active_seat_ids must be unique and strictly increasing")
        if not set(self.active_seat_ids).issubset(self.starting_stacks):
            raise ValueError("active_seat_ids must reference table seats")
        if self.button_seat not in self.active_seat_ids:
            raise ValueError("button_seat must reference an active seat")
        if any(self.starting_stacks[seat] <= 0 for seat in self.active_seat_ids):
            raise ValueError("active seats must have positive starting stacks")
        return self


class HoleCardsRecordedPayloadV1(DomainModel):
    kind: Literal["hole_cards_recorded"] = "hole_cards_recorded"
    seat_id: SeatId
    cards: tuple[Card, Card]

    @model_validator(mode="after")
    def validate_cards(self) -> HoleCardsRecordedPayloadV1:
        if self.cards[0] == self.cards[1]:
            raise ValueError("hole cards must be distinct")
        return self


class ActionTakenPayloadV1(DomainModel):
    kind: Literal["action_taken"] = "action_taken"
    street: Street
    actor_seat: SeatId
    action: SimulatorActionV1
    amount: NonNegativeInt | None = None
    amount_semantics: AmountSemanticsV1 = AmountSemanticsV1.NONE

    @model_validator(mode="after")
    def validate_action_amount(self) -> ActionTakenPayloadV1:
        expected = {
            SimulatorActionV1.FOLD: AmountSemanticsV1.NONE,
            SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
            SimulatorActionV1.CALL: AmountSemanticsV1.COST,
            SimulatorActionV1.BET: AmountSemanticsV1.BY,
            SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
        }[self.action]
        if self.amount_semantics is not expected:
            raise ValueError(
                f"{self.action.value} requires amount_semantics={expected.value}"
            )
        if expected is AmountSemanticsV1.NONE and self.amount is not None:
            raise ValueError(f"{self.action.value} cannot carry an amount")
        if expected is not AmountSemanticsV1.NONE and (
            self.amount is None or self.amount <= 0
        ):
            raise ValueError(f"{self.action.value} requires a positive amount")
        return self


class BoardDealtPayloadV1(DomainModel):
    kind: Literal["board_dealt"] = "board_dealt"
    street: Literal[Street.FLOP, Street.TURN, Street.RIVER]
    cards: tuple[Card, ...]

    @model_validator(mode="after")
    def validate_deal_size(self) -> BoardDealtPayloadV1:
        expected = 3 if self.street is Street.FLOP else 1
        if len(self.cards) != expected or len(self.cards) != len(set(self.cards)):
            raise ValueError(f"{self.street.value} deal requires {expected} distinct cards")
        return self


class HandCompletedPayloadV1(DomainModel):
    kind: Literal["hand_completed"] = "hand_completed"
    winner_seats: tuple[SeatId, ...] = Field(min_length=1)
    payouts: dict[int, NonNegativeInt]

    @model_validator(mode="after")
    def validate_payouts(self) -> HandCompletedPayloadV1:
        if len(self.winner_seats) != len(set(self.winner_seats)):
            raise ValueError("winner_seats must be unique")
        if set(self.payouts) != set(self.winner_seats):
            raise ValueError("payouts must contain exactly the winner seats")
        if any(amount <= 0 for amount in self.payouts.values()):
            raise ValueError("winner payouts must be positive")
        return self


HandEventPayloadV1 = Annotated[
    HandStartedPayloadV1
    | HoleCardsRecordedPayloadV1
    | ActionTakenPayloadV1
    | BoardDealtPayloadV1
    | HandCompletedPayloadV1,
    Field(discriminator="kind"),
]


class HandEventV1(SimulatorContractV1):
    """Append-only event envelope; stream ordering is validated separately."""

    event_id: str = Field(min_length=1, max_length=128)
    hand_id: str = Field(min_length=1, max_length=128)
    sequence: Annotated[StrictInt, Field(ge=1)]
    timestamp: AwareDatetime
    source: EventSourceV1
    provenance: ContractProvenanceV1
    payload: HandEventPayloadV1


class SeatStatisticsV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    vpip: bool = False
    pfr: bool = False
    three_bet: bool = False
    action_count: NonNegativeInt = 0


class HandStatisticsProjectionV1(SimulatorContractV1):
    hand_id: str = Field(min_length=1, max_length=128)
    applied_sequence: Annotated[StrictInt, Field(ge=1)]
    by_seat: dict[int, SeatStatisticsV1]


class HandStateProjectionV1(SimulatorContractV1):
    hand_id: str = Field(min_length=1, max_length=128)
    applied_sequence: Annotated[StrictInt, Field(ge=1)]
    rules_engine: str = Field(min_length=1, max_length=128)
    rules_engine_version: str = Field(min_length=1, max_length=128)
    street: Street
    board: tuple[Card, ...]
    pot: NonNegativeInt
    stacks: dict[int, NonNegativeInt]
    street_commitments: dict[int, NonNegativeInt]
    folded_seats: tuple[SeatId, ...]
    hand_in_progress: bool
    winner_seats: tuple[SeatId, ...]
    payouts: dict[int, NonNegativeInt]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReplayedHandV1(SimulatorContractV1):
    state: HandStateProjectionV1
    statistics: HandStatisticsProjectionV1
