"""Private-safe, immutable Advisor/FastSolver comparison contract.

This module only compares already-produced, Hero-visible decision results.  It
does not choose a winner, solve a hand, or infer strategic explanations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Mapping

from pydantic import ConfigDict, Field

from poker_coach.domain.models import DomainModel, Street

from .contracts import AmountSemanticsV1, LegalActionV1, SimulatorActionV1


class _ReconciliationContractV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1


class ReconciliationIdentityV1(_ReconciliationContractV1):
    fingerprint: str
    hand_id: str
    sequence: int = Field(ge=0)
    street: Street


class NormalizedDecisionActionV1(_ReconciliationContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    amount_chips: int | None = Field(default=None, ge=0)
    pot_pct: Decimal | None = None
    is_jam: bool = False


class DecisionRoleV1(_ReconciliationContractV1):
    role: Literal["rule_baseline", "simulation_estimate"]
    status: Literal["ready", "degraded", "unavailable", "not_ready"]
    action: NormalizedDecisionActionV1 | None = None
    provenance: Mapping[str, str | None]
    limitations: tuple[str, ...] = ()
    unavailable_reason: str | None = None


class ConfidenceIntervalAvailabilityV1(_ReconciliationContractV1):
    status: Literal["available", "not_available"]
    overlap: bool | None = None


class DecisionAgreementV1(_ReconciliationContractV1):
    kind: Literal[
        "exact_action", "same_action_different_sizing", "different_action", "insufficient_evidence"
    ]
    reason_codes: tuple[
        Literal[
            "advisor_degraded", "solver_degraded", "solver_unavailable",
            "sizing_set_mismatch", "range_missing", "range_coarse",
            "model_limitations", "unexplained",
        ], ...
    ]
    confidence_interval: ConfidenceIntervalAvailabilityV1


class DecisionReconciliationV1(_ReconciliationContractV1):
    """Two independent roles; deliberately no final-recommendation field."""

    status: Literal["ready", "degraded", "not_ready"]
    decision: ReconciliationIdentityV1
    rule_baseline: DecisionRoleV1
    simulation_estimate: DecisionRoleV1
    agreement: DecisionAgreementV1


def unavailable_simulation(
    identity: ReconciliationIdentityV1, *, reason: str = "solver_unavailable"
) -> dict[str, object]:
    """A deliberately small, secret-free solver failure envelope."""

    return {
        "status": "unavailable", "recommendedAction": None,
        "source": "fast-ev-solver/v1.5", "version": "fast-ev-solver/v1",
        "modelVersion": "fast-ev-solver/v1.5", "confidence": "unavailable",
        "rangeStatus": "unavailable_fallback_uniform", "limitations": [
            "Fast EV Solver L1.5 did not run; the rule baseline remains independently available."
        ], "unavailableReason": reason, "decision": identity.to_dict(),
    }


def reconcile_decision(
    *,
    identity: ReconciliationIdentityV1,
    legal_actions: tuple[LegalActionV1, ...],
    pot: int,
    hero_stack: int,
    hero_commitment: int,
    advisor: Mapping[str, object],
    solver: Mapping[str, object],
) -> DecisionReconciliationV1:
    """Compare exact-node output using only legal actions and public chip facts."""

    advisor_matches = _same_identity(advisor, identity)
    solver_matches = _same_identity(solver, identity)
    baseline = _role(
        role="rule_baseline", raw=advisor, identity_matches=advisor_matches,
        legal_actions=legal_actions, pot=pot, hero_stack=hero_stack,
        hero_commitment=hero_commitment,
    )
    estimate = _role(
        role="simulation_estimate", raw=solver, identity_matches=solver_matches,
        legal_actions=legal_actions, pot=pot, hero_stack=hero_stack,
        hero_commitment=hero_commitment,
    )
    interval = _ci_availability(solver, solver_matches)
    if baseline.action is None or estimate.action is None:
        kind = "insufficient_evidence"
    elif baseline.action.action is not estimate.action.action:
        kind = "different_action"
    elif (
        baseline.action.amount_semantics is estimate.action.amount_semantics
        and baseline.action.amount_chips == estimate.action.amount_chips
    ):
        kind = "exact_action"
    else:
        kind = "same_action_different_sizing"

    reasons: list[str] = []
    if baseline.status == "degraded":
        reasons.append("advisor_degraded")
    if estimate.status == "degraded":
        reasons.append("solver_degraded")
    if estimate.status in {"unavailable", "not_ready"}:
        reasons.append("solver_unavailable")
    if kind == "same_action_different_sizing":
        reasons.append("sizing_set_mismatch")
    if solver_matches and solver.get("rangeStatus") == "unavailable_fallback_uniform":
        reasons.append("range_missing")
    if solver_matches and solver.get("confidence") in {"coarse", "partial"}:
        reasons.append("range_coarse")
    if estimate.limitations:
        reasons.append("model_limitations")
    if kind == "different_action" and not reasons:
        reasons.append("unexplained")
    status: Literal["ready", "degraded", "not_ready"]
    if baseline.status == "not_ready" or estimate.status == "not_ready":
        status = "not_ready"
    elif baseline.status == "ready" and estimate.status == "ready":
        status = "ready"
    else:
        status = "degraded"
    return DecisionReconciliationV1(
        status=status, decision=identity, rule_baseline=baseline,
        simulation_estimate=estimate,
        agreement=DecisionAgreementV1(
            kind=kind, reason_codes=tuple(dict.fromkeys(reasons)), confidence_interval=interval
        ),
    )


def _same_identity(raw: Mapping[str, object], expected: ReconciliationIdentityV1) -> bool:
    decision = raw.get("decision")
    if not isinstance(decision, Mapping):
        return False
    return all(decision.get(key) == value for key, value in {
        "fingerprint": expected.fingerprint, "handId": expected.hand_id,
        "sequence": expected.sequence, "street": expected.street.value,
    }.items())


def _role(
    *, role: Literal["rule_baseline", "simulation_estimate"], raw: Mapping[str, object],
    identity_matches: bool, legal_actions: tuple[LegalActionV1, ...], pot: int,
    hero_stack: int, hero_commitment: int,
) -> DecisionRoleV1:
    raw_status = raw.get("status")
    status: Literal["ready", "degraded", "unavailable", "not_ready"] = (
        raw_status if raw_status in {"ready", "degraded", "unavailable", "not_ready"} and identity_matches
        else "not_ready"
    )
    candidate = raw.get("recommendedAction")
    action = _normalize_action(
        candidate, legal_actions=legal_actions, pot=pot, hero_stack=hero_stack,
        hero_commitment=hero_commitment,
    ) if status in {"ready", "degraded"} and isinstance(candidate, Mapping) else None
    if status in {"ready", "degraded"} and action is None:
        status = "not_ready"
    limitations = raw.get("limitations")
    return DecisionRoleV1(
        role=role, status=status, action=action,
        provenance={
            "source": _text(raw.get("source")), "version": _text(raw.get("version")),
            "model_version": _text(raw.get("modelVersion")),
        },
        limitations=tuple(item for item in limitations if isinstance(item, str)) if isinstance(limitations, (list, tuple)) else (),
        unavailable_reason=_text(raw.get("unavailableReason")),
    )


def _normalize_action(
    raw: Mapping[str, object], *, legal_actions: tuple[LegalActionV1, ...], pot: int,
    hero_stack: int, hero_commitment: int,
) -> NormalizedDecisionActionV1 | None:
    try:
        action = SimulatorActionV1(raw["action"])
        semantics = AmountSemanticsV1(raw["amountSemantics"])
    except (KeyError, ValueError, TypeError):
        return None
    amount = raw.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        amount = None
    legal = next((item for item in legal_actions if item.action is action), None)
    if legal is None or legal.amount_semantics is not semantics or not legal.accepts(action=action, amount=amount):
        return None
    increment = amount if semantics is not AmountSemanticsV1.TO else amount - hero_commitment
    pot_pct = None if amount is None or pot <= 0 else Decimal(increment) * 100 / Decimal(pot)
    is_jam = (
        amount is not None and action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}
        and increment == hero_stack
    )
    return NormalizedDecisionActionV1(
        action=action, amount_semantics=semantics, amount_chips=amount,
        pot_pct=pot_pct, is_jam=is_jam,
    )


def _ci_availability(raw: Mapping[str, object], identity_matches: bool) -> ConfidenceIntervalAvailabilityV1:
    if not identity_matches or not isinstance(raw.get("recommendedAction"), Mapping):
        return ConfidenceIntervalAvailabilityV1(status="not_available")
    ci = raw["recommendedAction"].get("confidenceInterval95")
    if not isinstance(ci, Mapping) or not isinstance(ci.get("lower"), (int, float, str)) or not isinstance(ci.get("upper"), (int, float, str)):
        return ConfidenceIntervalAvailabilityV1(status="not_available")
    # Advisor has no EV interval, so overlap is deliberately not invented.
    return ConfidenceIntervalAvailabilityV1(status="available", overlap=None)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
