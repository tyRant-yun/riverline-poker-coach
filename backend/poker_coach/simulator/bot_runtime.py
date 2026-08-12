"""Bounded asynchronous bot port with deterministic legal fallback."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from .contracts import (
    BotAttemptStatusV1,
    BotAttemptV1,
    BotDecisionV1,
    LegalActionV1,
    ObservationV1,
    SimulatorActionV1,
)


class BotDecisionProvider(Protocol):
    """Provider/adapter port; implementations may be local, RPC, or subprocess."""

    name: str
    version: str

    async def decide(
        self,
        observation: ObservationV1,
        legal_actions: tuple[LegalActionV1, ...],
        time_budget_ms: int,
        rng_seed: int,
    ) -> BotDecisionV1: ...


class InvalidBotAction(ValueError):
    """A provider returned an action outside the authoritative legal set."""


class FixedPolicyProvider:
    """Constant-time fallback: check, then call, then fold, then minimum sizing."""

    name = "fixed-policy"
    version = "1.0.0"

    async def decide(
        self,
        observation: ObservationV1,
        legal_actions: tuple[LegalActionV1, ...],
        time_budget_ms: int,
        rng_seed: int,
    ) -> BotDecisionV1:
        del observation, time_budget_ms, rng_seed
        legal = _select_fixed_action(legal_actions)
        amount = None if legal.min_amount is None else legal.min_amount
        return BotDecisionV1(
            action=legal.action,
            amount=amount,
            amount_semantics=legal.amount_semantics,
            provider=self.name,
            provider_version=self.version,
            latency_ms=0,
            confidence=None,
            metadata={"strategy": "check-call-fold-minimum"},
        )


class BotRuntime:
    """Execute one provider within a deadline and always return a legal action."""

    def __init__(
        self,
        *,
        fallback: BotDecisionProvider | None = None,
        fallback_timeout_ms: int = 25,
    ):
        if fallback_timeout_ms <= 0:
            raise ValueError("fallback_timeout_ms must be positive")
        self.fallback = fallback or FixedPolicyProvider()
        self.fallback_timeout_ms = fallback_timeout_ms

    async def decide(
        self,
        provider: BotDecisionProvider,
        observation: ObservationV1,
        *,
        time_budget_ms: int,
        rng_seed: int,
    ) -> BotDecisionV1:
        if time_budget_ms <= 0:
            raise ValueError("time_budget_ms must be positive")
        started = time.perf_counter()
        attempts: list[BotAttemptV1] = []
        fallback_reason: str
        try:
            raw = await asyncio.wait_for(
                provider.decide(
                    observation,
                    observation.legal_actions,
                    time_budget_ms,
                    rng_seed,
                ),
                timeout=time_budget_ms / 1000,
            )
            elapsed = _elapsed_ms(started)
            _require_legal(raw, observation.legal_actions)
            attempts.append(
                BotAttemptV1(
                    provider=provider.name,
                    provider_version=provider.version,
                    status=BotAttemptStatusV1.SUCCESS,
                    latency_ms=elapsed,
                )
            )
            return _finalize(
                raw,
                provider_name=provider.name,
                provider_version=provider.version,
                latency_ms=elapsed,
                attempts=tuple(attempts),
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            fallback_reason = "timeout"
            attempts.append(
                BotAttemptV1(
                    provider=provider.name,
                    provider_version=provider.version,
                    status=BotAttemptStatusV1.TIMEOUT,
                    latency_ms=_elapsed_ms(started),
                    error_code="provider_timeout",
                    error_message=f"provider exceeded {time_budget_ms} ms budget",
                )
            )
        except InvalidBotAction as exc:
            fallback_reason = "invalid_action"
            attempts.append(
                BotAttemptV1(
                    provider=provider.name,
                    provider_version=provider.version,
                    status=BotAttemptStatusV1.INVALID_ACTION,
                    latency_ms=_elapsed_ms(started),
                    error_code="illegal_bot_action",
                    error_message=str(exc)[:512],
                )
            )
        except Exception as exc:
            fallback_reason = "exception"
            attempts.append(
                BotAttemptV1(
                    provider=provider.name,
                    provider_version=provider.version,
                    status=BotAttemptStatusV1.EXCEPTION,
                    latency_ms=_elapsed_ms(started),
                    error_code="provider_exception",
                    error_message=str(exc)[:512] or type(exc).__name__,
                )
            )

        fallback_started = time.perf_counter()
        try:
            raw_fallback = await asyncio.wait_for(
                self.fallback.decide(
                    observation,
                    observation.legal_actions,
                    self.fallback_timeout_ms,
                    rng_seed,
                ),
                timeout=self.fallback_timeout_ms / 1000,
            )
            fallback_elapsed = _elapsed_ms(fallback_started)
            _require_legal(raw_fallback, observation.legal_actions)
            fallback_name = self.fallback.name
            fallback_version = self.fallback.version
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: the built-in fallback is constant time
            fallback_elapsed = _elapsed_ms(fallback_started)
            attempts.append(
                BotAttemptV1(
                    provider=self.fallback.name,
                    provider_version=self.fallback.version,
                    status=BotAttemptStatusV1.EXCEPTION,
                    latency_ms=fallback_elapsed,
                    error_code="fallback_failure",
                    error_message=(str(exc) or type(exc).__name__)[:512],
                )
            )
            raw_fallback = _emergency_decision(observation.legal_actions)
            fallback_name = "emergency-fixed-policy"
            fallback_version = "1.0.0"
            fallback_elapsed = 0
        attempts.append(
            BotAttemptV1(
                provider=fallback_name,
                provider_version=fallback_version,
                status=BotAttemptStatusV1.SUCCESS,
                latency_ms=fallback_elapsed,
            )
        )
        return _finalize(
            raw_fallback,
            provider_name=fallback_name,
            provider_version=fallback_version,
            latency_ms=_elapsed_ms(started),
            degraded=True,
            fallback_reason=fallback_reason,
            attempts=tuple(attempts),
        )


def _require_legal(
    decision: BotDecisionV1, legal_actions: tuple[LegalActionV1, ...]
) -> None:
    if not any(
        legal.accepts(action=decision.action, amount=decision.amount)
        for legal in legal_actions
    ):
        raise InvalidBotAction(
            f"{decision.action.value} amount={decision.amount!r} is outside legal bounds"
        )


def _select_fixed_action(legal_actions: tuple[LegalActionV1, ...]) -> LegalActionV1:
    priority = (
        SimulatorActionV1.CHECK,
        SimulatorActionV1.CALL,
        SimulatorActionV1.FOLD,
        SimulatorActionV1.BET,
        SimulatorActionV1.RAISE,
    )
    by_action = {legal.action: legal for legal in legal_actions}
    for action in priority:
        if action in by_action:
            return by_action[action]
    raise InvalidBotAction("no legal actions are available")


def _emergency_decision(legal_actions: tuple[LegalActionV1, ...]) -> BotDecisionV1:
    legal = _select_fixed_action(legal_actions)
    return BotDecisionV1(
        action=legal.action,
        amount=legal.min_amount,
        amount_semantics=legal.amount_semantics,
        provider="emergency-fixed-policy",
        provider_version="1.0.0",
        latency_ms=0,
        metadata={"strategy": "emergency"},
    )


def _finalize(
    raw: BotDecisionV1,
    *,
    provider_name: str,
    provider_version: str,
    latency_ms: float,
    degraded: bool = False,
    fallback_reason: str | None = None,
    attempts: tuple[BotAttemptV1, ...],
) -> BotDecisionV1:
    return BotDecisionV1(
        action=raw.action,
        amount=raw.amount,
        amount_semantics=raw.amount_semantics,
        provider=provider_name,
        provider_version=provider_version,
        latency_ms=latency_ms,
        confidence=raw.confidence,
        metadata=dict(raw.metadata),
        degraded=degraded,
        fallback_reason=fallback_reason,
        attempts=attempts,
    )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)
