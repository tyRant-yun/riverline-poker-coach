"""Black-box spike tests for bounded asynchronous bot execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from poker_coach.simulator import (
    BotDecisionV1,
    BotRuntime,
    HandEventV1,
    build_observation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "simulator-hand-v1.json"


def _observation():
    events = tuple(
        HandEventV1.model_validate(item)
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))
    )
    return build_observation(events, observer_seat=2, after_sequence=10)


class SuccessfulProvider:
    name = "successful-provider"
    version = "1.0.0"

    async def decide(self, observation, legal_actions, time_budget_ms, rng_seed):
        assert observation.observer_seat == 2
        assert legal_actions == observation.legal_actions
        assert time_budget_ms == 50
        assert rng_seed == 7
        return BotDecisionV1(
            action="check",
            amountSemantics="none",
            provider="untrusted-self-report",
            providerVersion="untrusted",
            latencyMs=999,
            confidence=0.8,
            metadata={"seed": rng_seed},
        )


class SlowProvider:
    name = "slow-provider"
    version = "1.0.0"

    async def decide(self, observation, legal_actions, time_budget_ms, rng_seed):
        await asyncio.sleep(0.2)
        return BotDecisionV1(
            action="check",
            amountSemantics="none",
            provider=self.name,
            providerVersion=self.version,
            latencyMs=200,
        )


class ExplodingProvider:
    name = "exploding-provider"
    version = "1.0.0"

    async def decide(self, observation, legal_actions, time_budget_ms, rng_seed):
        raise RuntimeError("provider exploded")


class IllegalProvider:
    name = "illegal-provider"
    version = "1.0.0"

    async def decide(self, observation, legal_actions, time_budget_ms, rng_seed):
        return BotDecisionV1(
            action="bet",
            amount=1,
            amountSemantics="by",
            provider=self.name,
            providerVersion=self.version,
            latencyMs=1,
        )


def test_bot_runtime_returns_valid_provider_decision_with_measured_provenance():
    decision = asyncio.run(
        BotRuntime().decide(
            SuccessfulProvider(), _observation(), time_budget_ms=50, rng_seed=7
        )
    )

    assert decision.action.value == "check"
    assert decision.provider == "successful-provider"  # runtime, not provider self-report
    assert decision.provider_version == "1.0.0"
    assert decision.latency_ms < 50
    assert decision.degraded is False
    assert [attempt.status.value for attempt in decision.attempts] == ["success"]


def test_bot_runtime_timeout_falls_back_without_blocking_the_hand():
    decision = asyncio.run(
        BotRuntime().decide(
            SlowProvider(), _observation(), time_budget_ms=10, rng_seed=7
        )
    )

    assert decision.action.value == "check"
    assert decision.provider == "fixed-policy"
    assert decision.degraded is True
    assert decision.fallback_reason == "timeout"
    assert decision.latency_ms < 150
    assert [attempt.status.value for attempt in decision.attempts] == [
        "timeout",
        "success",
    ]
    assert decision.attempts[0].error_code == "provider_timeout"


def test_bot_runtime_exception_falls_back_with_error_provenance():
    decision = asyncio.run(
        BotRuntime().decide(
            ExplodingProvider(), _observation(), time_budget_ms=50, rng_seed=7
        )
    )

    assert decision.action.value == "check"
    assert decision.fallback_reason == "exception"
    assert decision.attempts[0].status.value == "exception"
    assert decision.attempts[0].error_code == "provider_exception"
    assert "provider exploded" in decision.attempts[0].error_message


def test_bot_runtime_illegal_action_falls_back_with_validation_provenance():
    observation = _observation()
    decision = asyncio.run(
        BotRuntime().decide(
            IllegalProvider(), observation, time_budget_ms=50, rng_seed=7
        )
    )

    assert decision.action.value == "check"
    assert decision.fallback_reason == "invalid_action"
    assert decision.attempts[0].status.value == "invalid_action"
    assert decision.attempts[0].error_code == "illegal_bot_action"
    assert any(
        legal.accepts(action=decision.action, amount=decision.amount)
        for legal in observation.legal_actions
    )
