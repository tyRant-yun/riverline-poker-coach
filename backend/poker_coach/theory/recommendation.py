"""One permission-safe, versioned theory recommendation for a Hero decision.

This is deliberately an adapter, not another solver.  It picks exactly one
strategy source in priority order (verified artifact, supplied bounded L2
result, then an explicitly limited formula heuristic) and keeps L0 math in
the explanation section.  Callers must provide an ``ObservationV1``: this
module never accepts a deck, opponent hole cards, terminal results, or future
actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from pydantic import ConfigDict, Field

from poker_coach.domain.models import DomainModel, Street
from poker_coach.simulator.contracts import AmountSemanticsV1, LegalActionV1, ObservationV1, SimulatorActionV1
from poker_coach.simulator.formula_advisor import FormulaAdvisor, FormulaAdvisorResultV1, LegalActionBoundV1

from .l2_solver import L2Result
from .policy_artifact import PolicyArtifact, PreflopPolicyContext, default_preflop_artifact, policy_miss_reason


class _TheoryContractV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1


class TheoryDecisionIdentityV1(_TheoryContractV1):
    fingerprint: str
    hand_id: str
    sequence: int = Field(ge=0)
    street: Street
    observer_seat: int = Field(ge=0, le=7)


class TheoryCoverageV1(_TheoryContractV1):
    status: Literal["covered", "fallback", "unsupported"]
    reason: str | None = None
    players: int = Field(ge=2, le=8)
    street: Street
    tree_id: str | None = None
    sizing_abstraction: str | None = None
    effective_stack_bucket: str | None = None
    rake: str | None = None
    ante: int | None = None


class TheoryEvidenceV1(_TheoryContractV1):
    """Provenance for the sole strategy truth, never Formula math evidence."""

    source_kind: Literal["policy_artifact", "l2_bounded_solver", "formula", "unsupported"]
    evidence_grade: Literal["B", "C", "unsupported"]
    version: str
    policy_fingerprint: str | None = None
    source_license: str | None = None
    provenance: str
    coverage: TheoryCoverageV1
    degradation_reason: str | None = None


class TheoryFrequencyV1(_TheoryContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    amount: int | None = Field(default=None, ge=0)
    frequency: float = Field(ge=0.0, le=1.0)


class TheoryEvLossV1(_TheoryContractV1):
    """Only present when an oracle has the exact same tree/range/utility key."""

    chips: float | None = None
    definition: str | None = None
    unavailable_reason: str | None = None


class TheoryExplanationV1(_TheoryContractV1):
    """Auditable L0 facts; these do not independently arbitrate an action."""

    formula_version: str
    pot: int = Field(ge=0)
    call_cost: int = Field(ge=0)
    pot_odds: str
    pot_odds_basis: str
    spr: str | None = None
    spr_basis: str
    legal_action_bounds: tuple[LegalActionBoundV1, ...]
    break_even_fold_equity: str | None = None
    break_even_fold_equity_basis: str | None = None
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


class TheoryRecommendationV1(_TheoryContractV1):
    """Immutable, additive public DTO with one and only one policy source."""

    status: Literal["ready", "degraded", "not_ready"]
    available: bool
    decision: TheoryDecisionIdentityV1
    evidence: TheoryEvidenceV1
    recommended_action: TheoryFrequencyV1 | None = None
    action_frequencies: tuple[TheoryFrequencyV1, ...] = ()
    legal_action_bounds: tuple[LegalActionBoundV1, ...] = ()
    same_oracle_ev_loss: TheoryEvLossV1
    explanation: TheoryExplanationV1
    assumptions: tuple[str, ...]
    degradation: tuple[str, ...] = ()


@dataclass(frozen=True)
class OracleEvLossInput:
    """An optional offline oracle comparison, safe only under an exact identity."""

    tree_fingerprint: str
    range_fingerprint: str
    utility_fingerprint: str
    chips: float
    definition: str


@dataclass(frozen=True)
class L2RecommendationInput:
    """Metadata-only L2 handoff; projected ranges never leave the solver boundary."""

    result: L2Result
    decision_fingerprint: str
    utility_fingerprint: str
    # This explicit proof prevents a caller from treating live private data as a range.
    projection_scope: Literal["public_range_projection"] = "public_range_projection"


class TheoryExplainer:
    """Select a single source without blocking the game or exposing private data."""

    version = "theory-recommendation/v1"

    def __init__(self, *, artifact: PolicyArtifact | None = None, formula: FormulaAdvisor | None = None) -> None:
        self._artifact = artifact or default_preflop_artifact()
        self._formula = formula or FormulaAdvisor()

    def recommend(
        self,
        observation: ObservationV1,
        *,
        decision_fingerprint: str,
        preflop_context: PreflopPolicyContext | None = None,
        l2: L2RecommendationInput | None = None,
        oracle_ev_loss: OracleEvLossInput | None = None,
    ) -> TheoryRecommendationV1:
        formula = self._formula.evaluate(observation, decision_fingerprint=decision_fingerprint)
        identity = TheoryDecisionIdentityV1(
            fingerprint=decision_fingerprint, hand_id=observation.hand_id,
            sequence=observation.sequence, street=observation.street,
            observer_seat=observation.observer_seat,
        )
        explanation = _explanation(formula)

        # A verified preflop artifact is the authoritative source whenever it covers
        # this exact Hero hand / position / public action prefix.
        if observation.street is Street.PREFLOP:
            context = preflop_context or PreflopPolicyContext()
            match = self._artifact.match(observation, context)
            if match is not None:
                frequencies, filtered = _artifact_frequencies(match.frequencies, match.raise_to, observation.legal_actions)
                if frequencies:
                    return _result(
                        identity, formula, explanation, source_kind="policy_artifact", grade="B",
                        version=self._artifact.version, policy_fingerprint=self._artifact.fingerprint,
                        source_license=str(self._artifact.source["license"]),
                        provenance=str(self._artifact.source["provenance"]), status="ready",
                        coverage=TheoryCoverageV1(status="covered", players=observation.table_size, street=observation.street, tree_id=context.tree_fingerprint, sizing_abstraction="artifact_legal_sizings", effective_stack_bucket="100bb", rake="no_rake", ante=0),
                        frequencies=frequencies, oracle=oracle_ev_loss,
                        expected_tree=context.tree_fingerprint, expected_range=None, expected_utility=None,
                        degradation=("artifact_illegal_action_filtered",) if filtered else (),
                    )
                return self._formula_fallback(identity, formula, explanation, "artifact_no_legal_policy_action", oracle_ev_loss)
            return self._formula_fallback(
                identity, formula, explanation,
                "artifact_miss:" + policy_miss_reason(observation, context, self._artifact), oracle_ev_loss,
            )

        l2_result = _usable_l2(l2, observation, decision_fingerprint)
        if l2_result is not None:
            frequencies, filtered = _l2_frequencies(l2_result, observation.legal_actions)
            if frequencies:
                return _result(
                    identity, formula, explanation, source_kind="l2_bounded_solver", grade="B",
                    version=l2_result.solver_version, policy_fingerprint=l2_result.cache_key,
                    source_license=l2_result.license, provenance=l2_result.source,
                    status="ready" if l2_result.coverage_status == "covered" else "degraded",
                    coverage=TheoryCoverageV1(status=l2_result.coverage_status, reason=l2_result.degradation_reason, players=2, street=observation.street, tree_id=l2_result.tree_fingerprint, sizing_abstraction=l2_result.tree_description, effective_stack_bucket="validated_hu_stack", rake="no_rake", ante=0),
                    frequencies=frequencies, oracle=oracle_ev_loss,
                    expected_tree=l2_result.tree_fingerprint, expected_range=l2_result.range_fingerprint,
                    expected_utility=l2.utility_fingerprint,
                    degradation=("l2_illegal_action_filtered",) if filtered else (),
                )
        l2_reason = "l2_not_supplied_permission_safe_projection" if l2 is None else "l2_identity_or_coverage_mismatch"
        return self._formula_fallback(identity, formula, explanation, l2_reason, oracle_ev_loss)

    def unavailable(
        self, *, decision: TheoryDecisionIdentityV1, legal_actions: tuple[LegalActionV1, ...] = (), reason: str
    ) -> TheoryRecommendationV1:
        blank = TheoryExplanationV1(
            formula_version=FormulaAdvisor.version, pot=0, call_cost=0, pot_odds="0",
            pot_odds_basis="not_available", spr=None, spr_basis="not_available",
            legal_action_bounds=tuple(), assumptions=("No verified Hero decision snapshot was available.",),
            limitations=("No strategy source was evaluated.",),
        )
        return TheoryRecommendationV1(
            status="not_ready", available=False, decision=decision,
            evidence=TheoryEvidenceV1(source_kind="unsupported", evidence_grade="unsupported", version=self.version,
                provenance="No eligible strategy source", coverage=TheoryCoverageV1(status="unsupported", reason=reason, players=2, street=decision.street), degradation_reason=reason),
            legal_action_bounds=tuple(), same_oracle_ev_loss=TheoryEvLossV1(unavailable_reason="oracle_not_applicable"),
            explanation=blank, assumptions=blank.assumptions, degradation=(reason,),
        )

    def _formula_fallback(self, identity, formula, explanation, reason: str, oracle: OracleEvLossInput | None) -> TheoryRecommendationV1:
        frequencies: tuple[TheoryFrequencyV1, ...] = ()
        return _result(
            identity, formula, explanation, source_kind="formula", grade="C", version=formula.version,
            policy_fingerprint=None, source_license=None,
            provenance="Deterministic formula heuristic; not GTO or a complete game-tree policy.", status="degraded" if formula.status != "ready" else "ready",
            coverage=TheoryCoverageV1(status="fallback", reason=reason, players=2, street=identity.street, tree_id=None, sizing_abstraction="formula_only", effective_stack_bucket=None, rake="unknown", ante=None),
            frequencies=frequencies, oracle=oracle, expected_tree=None, expected_range=None, expected_utility=None,
            degradation=(reason,),
        )


def _result(identity, formula, explanation, *, source_kind, grade, version, policy_fingerprint, source_license, provenance, status, coverage, frequencies, oracle, expected_tree, expected_range, expected_utility, degradation):
    return TheoryRecommendationV1(
        status=status, available=True, decision=identity,
        evidence=TheoryEvidenceV1(source_kind=source_kind, evidence_grade=grade, version=version,
            policy_fingerprint=policy_fingerprint, source_license=source_license, provenance=provenance,
            coverage=coverage, degradation_reason=coverage.reason),
        recommended_action=max(frequencies, key=lambda item: item.frequency) if frequencies else None, action_frequencies=frequencies,
        legal_action_bounds=formula.legal_action_bounds,
        same_oracle_ev_loss=_ev_loss(oracle, expected_tree, expected_range, expected_utility), explanation=explanation,
        assumptions=explanation.assumptions, degradation=degradation,
    )


def _ev_loss(oracle: OracleEvLossInput | None, expected_tree: str | None, expected_range: str | None, expected_utility: str | None) -> TheoryEvLossV1:
    if oracle is None:
        return TheoryEvLossV1(unavailable_reason="oracle_not_provided")
    if expected_tree is None or expected_range is None or expected_utility is None:
        return TheoryEvLossV1(unavailable_reason="source_has_no_same_oracle_identity")
    if (oracle.tree_fingerprint != expected_tree or oracle.range_fingerprint != expected_range
            or oracle.utility_fingerprint != expected_utility):
        return TheoryEvLossV1(unavailable_reason="oracle_tree_or_range_fingerprint_mismatch")
    if not oracle.utility_fingerprint:
        return TheoryEvLossV1(unavailable_reason="oracle_utility_fingerprint_missing")
    return TheoryEvLossV1(chips=oracle.chips, definition=oracle.definition)


def _explanation(formula: FormulaAdvisorResultV1) -> TheoryExplanationV1:
    # Fold-equity is meaningful only for a legal bet/raise, and assumes the pot
    # is won immediately; it is intentionally absent for calls/checks.
    aggressor = next((item for item in formula.legal_action_bounds if item.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE} and item.minimum), None)
    fold_equity = None
    fold_basis = None
    if aggressor is not None and aggressor.minimum is not None and formula.pot + aggressor.minimum > 0:
        fold_equity = str(aggressor.minimum / (formula.pot + aggressor.minimum))
        fold_basis = "minimum_aggressive_amount_over_current_pot_plus_that_amount; immediate-fold-only assumption"
    return TheoryExplanationV1(
        formula_version=formula.version, pot=formula.pot, call_cost=formula.call_cost,
        pot_odds=str(formula.pot_odds), pot_odds_basis=formula.pot_odds_basis,
        spr=None if formula.spr is None else str(formula.spr), spr_basis=formula.spr_basis,
        legal_action_bounds=formula.legal_action_bounds, break_even_fold_equity=fold_equity,
        break_even_fold_equity_basis=fold_basis, assumptions=formula.assumptions,
        limitations=(*formula.limitations, "Formula math explains the selected source; it is not a second policy recommendation."),
    )


def _artifact_frequencies(raw: Mapping[str, float], raise_to: int | None, legal: tuple[LegalActionV1, ...]) -> tuple[tuple[TheoryFrequencyV1, ...], bool]:
    translated = {"raise_to": SimulatorActionV1.RAISE, "fold": SimulatorActionV1.FOLD, "call": SimulatorActionV1.CALL}
    candidates: list[TheoryFrequencyV1] = []
    filtered = False
    for name, weight in raw.items():
        action = translated.get(name)
        legal_action = next((item for item in legal if item.action is action), None)
        amount = raise_to if action is SimulatorActionV1.RAISE else (legal_action.min_amount if legal_action and legal_action.amount_semantics is not AmountSemanticsV1.NONE else None)
        if action is None or legal_action is None or not legal_action.accepts(action=action, amount=amount):
            filtered = filtered or weight > 0
            continue
        candidates.append(TheoryFrequencyV1(action=action, amount_semantics=legal_action.amount_semantics, amount=amount, frequency=float(weight)))
    return _normalize(candidates), filtered


def _l2_frequencies(result: L2Result, legal: tuple[LegalActionV1, ...]) -> tuple[tuple[TheoryFrequencyV1, ...], bool]:
    candidates: list[TheoryFrequencyV1] = []
    filtered = False
    for name, weight in result.action_frequencies.items():
        try:
            action = SimulatorActionV1(name)
        except ValueError:
            filtered = filtered or weight > 0
            continue
        legal_action = next((item for item in legal if item.action is action), None)
        amount = result.legal_sizes.get(name) if action is SimulatorActionV1.BET else (legal_action.min_amount if legal_action and legal_action.amount_semantics is not AmountSemanticsV1.NONE else None)
        if legal_action is None or not legal_action.accepts(action=action, amount=amount):
            filtered = filtered or weight > 0
            continue
        candidates.append(TheoryFrequencyV1(action=action, amount_semantics=legal_action.amount_semantics, amount=amount, frequency=float(weight)))
    return _normalize(candidates), filtered


def _normalize(candidates: list[TheoryFrequencyV1]) -> tuple[TheoryFrequencyV1, ...]:
    total = sum(item.frequency for item in candidates)
    if total <= 0:
        return ()
    return tuple(item.model_copy(update={"frequency": item.frequency / total}) for item in candidates)


def _usable_l2(l2: L2RecommendationInput | None, observation: ObservationV1, decision_fingerprint: str) -> L2Result | None:
    if l2 is None or l2.projection_scope != "public_range_projection" or l2.decision_fingerprint != decision_fingerprint:
        return None
    result = l2.result
    legal = {item.action.value: item for item in observation.legal_actions}
    if observation.street is not Street.RIVER or len(observation.active_seats) != 2 or result.coverage_status not in {"covered", "fallback"} or set(legal) != {"check", "bet"}:
        return None
    if result.players[0] != observation.observer_seat or result.street != observation.street.value:
        return None
    # R9-FIX-B deliberately returns aggregate diagnostics when no authorized
    # Hero combo was supplied.  Those aggregate numbers are not a policy for
    # the current Hero decision and must stay on the C/unsupported path.
    if not result.recommendation_available or result.hero_decision_identity is None or not result.action_frequencies:
        return None
    return result
