"""Simulator foundation contracts and ports."""

from .contracts import (
    AmountSemanticsV1,
    BotAttemptStatusV1,
    BotAttemptV1,
    BotDecisionV1,
    HandEventV1,
    HandStateProjectionV1,
    HandStatisticsProjectionV1,
    LegalActionV1,
    ObservationV1,
    PublicActionV1,
    ReplayedHandV1,
    SeatStatisticsV1,
    SimulatorActionV1,
)
from .replay import (
    EventStreamError,
    append_hand_event,
    replay_hand,
    scenario_from_events,
    validate_hand_event_stream,
)
from .observation import build_observation
from .bot_runtime import (
    BotDecisionProvider,
    BotRuntime,
    FixedPolicyProvider,
    InvalidBotAction,
)

__all__ = [
    "AmountSemanticsV1",
    "BotAttemptStatusV1",
    "BotAttemptV1",
    "BotDecisionV1",
    "HandEventV1",
    "HandStateProjectionV1",
    "HandStatisticsProjectionV1",
    "LegalActionV1",
    "ObservationV1",
    "PublicActionV1",
    "ReplayedHandV1",
    "SeatStatisticsV1",
    "SimulatorActionV1",
    "EventStreamError",
    "append_hand_event",
    "replay_hand",
    "scenario_from_events",
    "validate_hand_event_stream",
    "build_observation",
    "BotDecisionProvider",
    "BotRuntime",
    "FixedPolicyProvider",
    "InvalidBotAction",
]
