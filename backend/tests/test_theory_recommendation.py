"""R9-05 source-priority and safety contracts for unified recommendations."""

from __future__ import annotations

from types import SimpleNamespace
from time import perf_counter

from fastapi.testclient import TestClient

from poker_coach.api import AppConfig, create_app
from poker_coach.persistence import SQLiteGameSessionStore, SQLiteHandEventStore
from poker_coach.simulator.contracts import HoleCardsRecordedPayloadV1, LegalActionV1, ObservationV1
from poker_coach.simulator.continuous_table import ContinuousTableService
from poker_coach.simulator.continuous_table import _live_hu_river_l2
from poker_coach.theory import L2RecommendationInput, OracleEvLossInput, PreflopPolicyContext, TheoryExplainer
from poker_coach.theory.l2_solver import L2Budget, L2Cache, L2RiverInput, RangeCombo, RiverBetTree, solve_hu_river


def _preflop(*, actions=None) -> ObservationV1:
    return ObservationV1(
        handId="theory-hand", sequence=7, observerSeat=3, tableSize=6, buttonSeat=0,
        street="preflop", ownHoleCards=("Qs", "Jh"), board=(), pot=150,
        stacks={seat: 10_000 for seat in range(6)}, streetCommitments={seat: 0 for seat in range(6)},
        activeSeats=(0, 1, 2, 3, 4, 5), legalActions=actions or (
            LegalActionV1(action="fold", amountSemantics="none"),
            LegalActionV1(action="raise", amountSemantics="to", minAmount=200, maxAmount=10_000),
        ),
    )


def test_verified_preflop_artifact_is_the_only_b_grade_truth_and_formula_is_explanation():
    result = TheoryExplainer().recommend(
        _preflop(), decision_fingerprint="decision-1", preflop_context=PreflopPolicyContext(big_blind=100),
    )

    assert result.evidence.source_kind == "policy_artifact"
    assert result.evidence.evidence_grade == "B"
    assert result.evidence.coverage.status == "covered"
    assert result.evidence.policy_fingerprint
    assert sum(item.frequency for item in result.action_frequencies) == 1.0
    assert result.recommended_action in result.action_frequencies
    assert "second policy recommendation" in result.explanation.limitations[-1]
    assert result.same_oracle_ev_loss.chips is None
    assert result.same_oracle_ev_loss.unavailable_reason == "oracle_not_provided"


def test_illegal_positive_artifact_action_downgrades_instead_of_re_normalizing_to_b_grade():
    result = TheoryExplainer().recommend(
        _preflop(actions=(LegalActionV1(action="fold", amountSemantics="none"),)),
        decision_fingerprint="decision-2", preflop_context=PreflopPolicyContext(big_blind=100),
    )

    assert result.evidence.source_kind == "formula"
    assert result.evidence.evidence_grade == "C"
    assert result.evidence.coverage.reason == "artifact_policy_action_not_legal"
    assert result.recommended_action is None
    assert result.action_frequencies == ()


def test_artifact_miss_honestly_uses_c_formula():
    missed = TheoryExplainer().recommend(
        _preflop().model_copy(update={"table_size": 2, "active_seats": (0, 1), "stacks": {0: 10_000, 1: 10_000}, "street_commitments": {0: 0, 1: 0}, "observer_seat": 0}),
        decision_fingerprint="decision-3", preflop_context=PreflopPolicyContext(big_blind=100),
    )
    assert missed.evidence.source_kind == "formula"
    assert missed.evidence.evidence_grade == "C"
    assert missed.evidence.coverage.status == "fallback"
    assert missed.degradation[0].startswith("artifact_miss:")
    assert missed.action_frequencies == ()
    assert missed.recommended_action is None
    assert missed.legal_action_bounds == ()
    assert missed.explanation.legal_action_bounds == ()
    assert missed.explanation.break_even_fold_equity is None
    assert missed.same_oracle_ev_loss.chips is None
    assert missed.same_oracle_ev_loss.definition is None
    assert missed.same_oracle_ev_loss.unavailable_reason == "evidence_grade_has_no_policy_ev"


def test_ev_loss_never_claims_an_oracle_when_tree_or_range_identity_does_not_match():
    result = TheoryExplainer().recommend(
        _preflop(), decision_fingerprint="decision-5", preflop_context=PreflopPolicyContext(big_blind=100),
        oracle_ev_loss=OracleEvLossInput(
            tree_fingerprint="wrong-tree", range_fingerprint="wrong-range",
            utility_fingerprint="chips-v1", chips=12.5, definition="same oracle",
        ),
    )
    assert result.same_oracle_ev_loss.chips is None
    assert result.same_oracle_ev_loss.unavailable_reason == "source_has_no_same_oracle_identity"


def test_permission_safe_l2_has_priority_on_hu_river_and_ev_loss_needs_all_three_fingerprints():
    result = solve_hu_river(L2RiverInput(
        game_fingerprint="game-v1", tree_fingerprint="tree-v1", range_fingerprint="range-v1",
        solver_version="solver-v1", players=(0, 1), acting_seat=0, pot=100,
        stacks=((0, 100), (1, 100)), board=("As", "Ks", "Qs", "Js", "Ts"),
        ranges=((0, (RangeCombo(("2c", "3d"), 1),)), (1, (RangeCombo(("6c", "7d"), 1),))),
        tree=RiverBetTree(bet_amount=100), seed=7,
        budget=L2Budget(iterations=20, soft_timeout_ms=2_000, hard_timeout_ms=3_000),
        hero_hole_cards=("2c", "3d"),
    ))
    observation = ObservationV1(
        handId="river-hand", sequence=9, observerSeat=0, tableSize=2, buttonSeat=0, street="river",
        ownHoleCards=("2c", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"), pot=100,
        stacks={0: 100, 1: 100}, streetCommitments={0: 0, 1: 0}, activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"), LegalActionV1(action="bet", amountSemantics="by", minAmount=100, maxAmount=100)),
    )
    recommendation = TheoryExplainer().recommend(
        observation, decision_fingerprint="river-fingerprint",
        l2=L2RecommendationInput(result=result, decision_fingerprint="river-fingerprint", utility_fingerprint="chips-v1"),
        oracle_ev_loss=OracleEvLossInput(tree_fingerprint="tree-v1", range_fingerprint="range-v1", utility_fingerprint="wrong-utility", chips=2.0, definition="chips"),
    )
    assert recommendation.evidence.source_kind == "l2_bounded_solver"
    assert recommendation.evidence.evidence_grade == "B"
    assert sum(item.frequency for item in recommendation.action_frequencies) == 1.0
    assert recommendation.same_oracle_ev_loss.chips is None
    assert recommendation.same_oracle_ev_loss.unavailable_reason == "oracle_tree_or_range_fingerprint_mismatch"
    assert "'2c'" not in str(recommendation.to_dict()).lower()
    assert "'3d'" not in str(recommendation.to_dict()).lower()


def test_live_hu_river_adapter_binds_authorized_hero_infoset_and_cache_without_private_poison(monkeypatch):
    observation = ObservationV1(
        handId="river-live", sequence=9, observerSeat=0, tableSize=2, buttonSeat=0, street="river",
        ownHoleCards=("2c", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"), pot=100,
        stacks={0: 100, 1: 100}, streetCommitments={0: 0, 1: 0}, activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"), LegalActionV1(action="bet", amountSemantics="by", minAmount=100, maxAmount=100)),
    )
    public = {
        0: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-hero", combos={"2c3d": SimpleNamespace(probability=0.5), "4c5d": SimpleNamespace(probability=0.5)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
        1: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-villain", combos={"6c7d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
    }
    monkeypatch.setattr("poker_coach.simulator.continuous_table.PublicEventBeliefConsumer.beliefs_at", lambda *_args, **_kwargs: public)
    cache = L2Cache()
    first = _live_hu_river_l2(events=(), observation=observation, decision_fingerprint="decision-public", cache=cache)
    second = _live_hu_river_l2(events=(), observation=observation, decision_fingerprint="decision-public", cache=cache)
    assert first is not None and second is not None
    assert first.result.evidence_grade == "B"
    assert first.result.recommendation_available is True
    assert first.result.hero_decision_identity is not None
    assert second.result.cache_hit is True
    assert "'2c'" not in str(first.result).lower()
    assert "'3d'" not in str(first.result).lower()
    samples = []
    for _ in range(20):
        started = perf_counter()
        cached = _live_hu_river_l2(events=(), observation=observation, decision_fingerprint="decision-public", cache=cache)
        samples.append((perf_counter() - started) * 1_000)
        assert cached is not None and cached.result.cache_hit is True
    samples.sort()
    p95 = samples[18]
    print(f"live_l2_cache_hit_p95_ms={p95:.3f}")
    assert p95 < 500


def test_live_hu_river_adapter_isolates_hero_infosets_and_ignores_opponent_private_poison(monkeypatch):
    public = {
        0: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-hero", combos={"2c3d": SimpleNamespace(probability=0.5), "4c5d": SimpleNamespace(probability=0.5)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
        1: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-villain", combos={"6c7d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
    }
    monkeypatch.setattr("poker_coach.simulator.continuous_table.PublicEventBeliefConsumer.beliefs_at", lambda *_args, **_kwargs: public)
    base = ObservationV1(
        handId="river-live", sequence=9, observerSeat=0, tableSize=2, buttonSeat=0, street="river",
        ownHoleCards=("2c", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"), pot=100,
        stacks={0: 100, 1: 100}, streetCommitments={0: 0, 1: 0}, activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"), LegalActionV1(action="bet", amountSemantics="by", minAmount=100, maxAmount=100)),
    )
    cache = L2Cache()
    first = _live_hu_river_l2(events=(), observation=base, decision_fingerprint="decision-public", cache=cache)
    other = _live_hu_river_l2(
        events=(SimpleNamespace(payload=HoleCardsRecordedPayloadV1(seat_id=1, cards=("Qh", "Qd"))),),
        observation=base.model_copy(update={"own_hole_cards": ("4c", "5d")}),
        decision_fingerprint="decision-public", cache=cache,
    )
    repeated = _live_hu_river_l2(
        events=(SimpleNamespace(payload=HoleCardsRecordedPayloadV1(seat_id=1, cards=("Ac", "Ad"))),),
        observation=base, decision_fingerprint="decision-public", cache=cache,
    )
    next_decision = _live_hu_river_l2(
        events=(), observation=base, decision_fingerprint="decision-next", cache=cache,
    )
    assert first is not None and other is not None and repeated is not None and next_decision is not None
    assert first.result.recommendation_available is True
    assert other.result.recommendation_available is True
    assert first.result.hero_decision_identity != other.result.hero_decision_identity
    assert first.result.cache_key != other.result.cache_key
    assert first.result.tree_cache_key == other.result.tree_cache_key
    assert other.result.cache_hit is False
    assert repeated.result.cache_hit is True
    assert repeated.result.cache_key == first.result.cache_key
    assert next_decision.result.cache_hit is False
    assert next_decision.result.cache_key != first.result.cache_key
    assert "'qh'" not in str(other.result).lower()
    assert "'qd'" not in str(other.result).lower()


def test_live_l2_adapter_uses_private_hero_infoset_not_public_hero_range(monkeypatch):
    public = {
        0: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-hero", combos={"4c5d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
        1: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-villain", combos={"6c7d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
    }
    monkeypatch.setattr("poker_coach.simulator.continuous_table.PublicEventBeliefConsumer.beliefs_at", lambda *_args, **_kwargs: public)
    observation = ObservationV1(
        handId="river-live", sequence=9, observerSeat=0, tableSize=2, buttonSeat=0, street="river",
        ownHoleCards=("2c", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"), pot=100,
        stacks={0: 100, 1: 100}, streetCommitments={0: 0, 1: 0}, activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"), LegalActionV1(action="bet", amountSemantics="by", minAmount=100, maxAmount=100)),
    )
    result = _live_hu_river_l2(events=(), observation=observation, decision_fingerprint="decision-public", cache=L2Cache())
    assert result is not None
    assert result.result.recommendation_available is True
    recommendation = TheoryExplainer().recommend(observation, decision_fingerprint="decision-public", l2=result)
    assert recommendation.evidence.evidence_grade == "B"
    assert "'2c'" not in str(recommendation.to_dict()).lower()
    assert "'3d'" not in str(recommendation.to_dict()).lower()


def test_live_l2_adapter_returns_none_for_multiway_or_unsupported_tree():
    multiway = _preflop().model_copy(update={"street": "river", "table_size": 3, "active_seats": (0, 1, 2), "board": ("As", "Ks", "Qs", "Js", "Ts")})
    assert _live_hu_river_l2(events=(), observation=multiway, decision_fingerprint="multiway", cache=L2Cache()) is None


def test_live_l2_adapter_refuses_non_jam_tree_that_could_include_an_opponent_raise(monkeypatch):
    public = {
        0: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-hero", combos={"4c5d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
        1: SimpleNamespace(current=SimpleNamespace(snapshot_id="public-villain", combos={"6c7d": SimpleNamespace(probability=1)}), provenance=SimpleNamespace(policy_fingerprint="policy-public")),
    }
    monkeypatch.setattr("poker_coach.simulator.continuous_table.PublicEventBeliefConsumer.beliefs_at", lambda *_args, **_kwargs: public)
    observation = ObservationV1(
        handId="river-non-jam", sequence=9, observerSeat=0, tableSize=2, buttonSeat=0, street="river",
        ownHoleCards=("2c", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"), pot=100,
        stacks={0: 100, 1: 100}, streetCommitments={0: 0, 1: 0}, activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"), LegalActionV1(action="bet", amountSemantics="by", minAmount=50, maxAmount=50)),
    )
    assert _live_hu_river_l2(events=(), observation=observation, decision_fingerprint="non-jam", cache=L2Cache()) is None


def _client(tmp_path):
    path = tmp_path / "theory.sqlite3"
    service = ContinuousTableService(
        session_store=SQLiteGameSessionStore(path), event_store=SQLiteHandEventStore(path), metadata_path=path,
    )
    return TestClient(create_app(config=AppConfig(rate_limit_per_minute=0), table_service=service)), service


def _table(client):
    response = client.post("/v1/tables", json={"schemaVersion": 1, "commandId": "theory-table", "profileId": "balanced"})
    assert response.status_code == 200, response.text
    return response.json()["table"]


def _action(client, table):
    legal = table["heroLegalActions"][0]
    response = client.post(f"/v1/tables/{table['sessionId']}/actions", json={
        "schemaVersion": 1, "commandId": "theory-advance", "handId": table["handId"],
        "expectedRevision": table["revision"], "action": legal["action"],
        "amountSemantics": legal["amountSemantics"], **({"amount": legal["minAmount"]} if legal["amountSemantics"] != "none" else {}),
    })
    assert response.status_code == 200, response.text
    return response.json()["table"]


def test_api_rejects_stale_identity_and_never_exposes_private_poison_or_blocks_on_l2(tmp_path):
    client, service = _client(tmp_path)
    table = _table(client)
    response = client.post(f"/v1/tables/{table['sessionId']}/theory-recommendation", json={"handId": table["handId"], "decisionFingerprint": table["fingerprint"]})
    assert response.status_code == 200, response.text
    recommendation = response.json()["recommendation"]
    assert recommendation["decision"]["fingerprint"] == table["fingerprint"]
    assert "holeCards" not in str(recommendation)
    assert "rngSeed" not in str(recommendation)

    advanced = _action(client, table)
    stale = client.post(f"/v1/tables/{table['sessionId']}/theory-recommendation", json={"handId": table["handId"], "decisionFingerprint": table["fingerprint"]})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_decision"
    assert advanced["fingerprint"] != table["fingerprint"]
    service.close()
