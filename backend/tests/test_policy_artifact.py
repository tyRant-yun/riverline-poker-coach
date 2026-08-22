"""Focused integrity, coverage, and mixed-policy tests for R9-02."""

from __future__ import annotations

import asyncio
import json
from collections import Counter

import pytest

from poker_coach.simulator import BotRuntime, LegalActionV1, PolicyArtifactBot
from poker_coach.theory.benchmark import fixture_directory, load_fixture
from poker_coach.theory.policy_artifact import (
    PolicyArtifact,
    PolicyArtifactError,
    PreflopPolicyContext,
    default_preflop_artifact,
    hand_class_from_cards,
)


def _observation(*, public_actions: list[dict[str, object]] | None = None, legal_actions: list[dict[str, object]] | None = None):
    from poker_coach.simulator import ObservationV1

    return ObservationV1.model_validate(
        {
            "handId": "r9-02-policy",
            "sequence": 4,
            "observerSeat": 0,
            "tableSize": 6,
            "buttonSeat": 0,
            "street": "preflop",
            "ownHoleCards": ["As", "5s"],
            "board": [],
            "pot": 150,
            "stacks": {str(seat): 10000 for seat in range(6)},
            "streetCommitments": {str(seat): 0 for seat in range(6)},
            "activeSeats": list(range(6)),
            "publicActions": public_actions or [],
            "legalActions": legal_actions
            or [
                {"action": "fold", "amountSemantics": "none"},
                {"action": "call", "amountSemantics": "cost", "minAmount": 250, "maxAmount": 250},
                {"action": "raise", "amountSemantics": "to", "minAmount": 900, "maxAmount": 900},
            ],
        }
    )


def _payload(artifact: PolicyArtifact) -> dict:
    return artifact.to_payload()


def _resign(payload: dict) -> dict:
    # Test-only access to the first-party generator's declared integrity format.
    from poker_coach.theory.policy_artifact import _digest, _fingerprint, _without_integrity

    payload["integrity"] = {"digest": _digest(_without_integrity(payload)), "fingerprint": _fingerprint(payload)}
    return payload


def test_owned_artifact_is_complete_169_class_1326_combo_b_grade_data_product():
    artifact = default_preflop_artifact()

    assert artifact.source["license"] == "Riverline-first-party"
    assert artifact.source["evidenceGrade"] == "B"
    assert artifact.coverage["excluded"] == ("multiway", "limps", "3bet_or_later", "non_100bb", "rake", "ante", "unknown_tree")
    for node in artifact.payload["nodes"]:
        assert len(node["classFrequencies"]) == 169
        assert sum(entry["comboCount"] for entry in node["classFrequencies"]) == 1326
        assert all(abs(sum(entry["frequencies"].values()) - 1.0) < 1e-12 for entry in node["classFrequencies"])
    assert hand_class_from_cards(("As", "5s")) == "A5s"
    assert hand_class_from_cards(("As", "5h")) == "A5o"
    assert hand_class_from_cards(("Ah", "Ad")) == "AA"
    with pytest.raises(TypeError):
        artifact.payload["artifactVersion"] = "mutated"  # type: ignore[index]


@pytest.mark.parametrize("mutator, message", [
    (lambda payload: payload["integrity"].__setitem__("digest", "sha256:" + "0" * 64), "digest mismatch"),
    (lambda payload: payload["integrity"].__setitem__("fingerprint", "sha256:" + "0" * 64), "fingerprint mismatch"),
    (lambda payload: payload.__setitem__("artifactVersion", "unknown.v999"), "unknown policy artifact"),
])
def test_corrupted_or_unknown_artifact_is_rejected(mutator, message):
    payload = _payload(default_preflop_artifact())
    mutator(payload)
    with pytest.raises(PolicyArtifactError, match=message):
        PolicyArtifact.load(payload)


def test_intentional_illegal_frequency_red_artifact_is_rejected_even_when_resigned():
    payload = _payload(default_preflop_artifact())
    payload["nodes"][0]["classFrequencies"][0]["frequencies"] = {"raise_to": 0.7, "fold": 0.7}
    with pytest.raises(PolicyArtifactError, match="frequencies"):
        PolicyArtifact.load(_resign(payload))


def test_r9_00_fixture_gate_remains_a_b_grade_calibration_reference_for_the_adapter():
    fixture = load_fixture(fixture_directory() / "green-6max-preflop-b.json")
    assert fixture.payload["oracle"]["evidenceGrade"] == "B"
    assert fixture.payload["identity"]["gameFingerprint"] == "nlhe-6max-100bb-norake-v1"
    assert default_preflop_artifact().coverage["effectiveStackBb"] == 100


@pytest.mark.parametrize(
    "context",
    [
        PreflopPolicyContext(effective_stack_bb=80),
        PreflopPolicyContext(rake_bps=500),
        PreflopPolicyContext(ante_bb=1),
        PreflopPolicyContext(tree_fingerprint="unknown-tree"),
    ],
)
def test_noncovered_stack_rake_ante_or_tree_returns_c_grade_fallback_with_reason(context):
    decision = asyncio.run(PolicyArtifactBot(context=context).decide(_observation(), _observation().legal_actions, 20, 7))

    assert decision.metadata["evidenceGrade"] == "C"
    assert decision.metadata["coverageStatus"] == "fallback"
    assert decision.metadata["degraded"] is True
    assert decision.metadata["degradeReason"] in {"non_100bb", "rake", "ante", "unknown_tree"}
    assert decision.metadata["fallbackProvider"] == "lightweight-blueprint"


def test_observed_non_100bb_stack_cannot_be_claimed_as_covered_even_with_default_context():
    observation = _observation()
    observation = observation.model_copy(update={"stacks": {**observation.stacks, 4: 8000}})
    decision = asyncio.run(PolicyArtifactBot().decide(observation, observation.legal_actions, 20, 7))

    assert decision.metadata["coverageStatus"] == "fallback"
    assert decision.metadata["degradeReason"] == "non_100bb"


def test_seeded_mixed_policy_is_reproducible_legal_and_tracks_artifact_frequency(monkeypatch):
    loop_creations = 0
    original_new_event_loop = asyncio.events.new_event_loop

    def counted_new_event_loop():
        nonlocal loop_creations
        loop_creations += 1
        return original_new_event_loop()

    monkeypatch.setattr(asyncio.events, "new_event_loop", counted_new_event_loop)
    observation = _observation(
        public_actions=[
            {"sequence": 1, "street": "preflop", "actorSeat": 3, "action": "raise", "amount": 250, "amountSemantics": "to"}
        ]
    )
    provider = PolicyArtifactBot()

    async def decisions_for_seeds():
        first = await provider.decide(observation, observation.legal_actions, 20, 817)
        second = await provider.decide(observation, observation.legal_actions, 20, 817)
        counts = Counter()
        for seed in range(10_000):
            decision = await provider.decide(observation, observation.legal_actions, 20, seed)
            counts[decision.action.value] += 1
        return first, second, counts

    first, second, counts = asyncio.run(decisions_for_seeds())
    assert first == second
    assert first.metadata["coverageStatus"] == "covered"
    assert first.metadata["policyFingerprint"] == provider.artifact.fingerprint
    assert first.metadata["sourceLicense"] == "Riverline-first-party"
    assert any(legal.accepts(action=first.action, amount=first.amount) for legal in observation.legal_actions)

    observed = {action: counts[action] / 10_000 for action in ("fold", "call", "raise")}
    assert observed["fold"] == pytest.approx(0.3, abs=0.02)
    assert observed["call"] == pytest.approx(0.4, abs=0.02)
    assert observed["raise"] == pytest.approx(0.3, abs=0.02)
    assert loop_creations == 1


def test_theory_profile_falls_back_for_an_illegal_artifact_sizing_without_breaking_runtime_fallbacks():
    observation = _observation(
        public_actions=[
            {"sequence": 1, "street": "preflop", "actorSeat": 3, "action": "raise", "amount": 250, "amountSemantics": "to"}
        ],
        legal_actions=[
            {"action": "fold", "amountSemantics": "none"},
            {"action": "call", "amountSemantics": "cost", "minAmount": 250, "maxAmount": 250},
            {"action": "raise", "amountSemantics": "to", "minAmount": 1000, "maxAmount": 1500},
        ],
    )
    decision = asyncio.run(BotRuntime().decide(PolicyArtifactBot(), observation, time_budget_ms=20, rng_seed=4))

    assert decision.degraded is True
    assert decision.fallback_reason == "legal_sizing_miss"
    assert decision.metadata["coverageStatus"] == "fallback"
    assert decision.metadata["degradeReason"] == "legal_sizing_miss"
    assert decision.metadata["evidenceGrade"] == "C"
    assert decision.metadata["degraded"] is True
    assert any(legal.accepts(action=decision.action, amount=decision.amount) for legal in observation.legal_actions)


@pytest.mark.parametrize("field, value, message", [
    ("handClass", "ZZ", "canonical 169"),
    ("handClass", "a5s", "canonical 169"),
    ("comboCount", 99, "combo count"),
])
def test_artifact_rejects_noncanonical_classes_and_combo_counts(field, value, message):
    payload = _payload(default_preflop_artifact())
    payload["nodes"][0]["classFrequencies"][0][field] = value
    with pytest.raises(PolicyArtifactError, match=message):
        PolicyArtifact.load(_resign(payload))


def test_artifact_rejects_illegal_action_and_missing_b_grade_release_manifest():
    payload = _payload(default_preflop_artifact())
    payload["nodes"][0]["classFrequencies"][0]["frequencies"] = {"check": 1.0, "fold": 0.0}
    with pytest.raises(PolicyArtifactError, match="frequencies"):
        PolicyArtifact.load(_resign(payload))
    payload = _payload(default_preflop_artifact())
    payload["generation"].pop("command")
    with pytest.raises(PolicyArtifactError, match="generation.command"):
        PolicyArtifact.load(_resign(payload))
