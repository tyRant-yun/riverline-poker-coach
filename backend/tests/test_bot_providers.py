"""Focused public-seam tests for deterministic in-process bot profiles."""

from __future__ import annotations

import asyncio

import pytest

from poker_coach.simulator import (
    BotRuntime,
    LegalActionV1,
    LightweightBlueprintProvider,
    build_bot_provider,
)


def _observation(
    legal_actions: list[dict[str, object]],
    *,
    own_hole_cards: tuple[str, str] = ("As", "Kd"),
    board: tuple[str, ...] = (),
    street: str = "flop",
    button_seat: int = 0,
    pot: int = 300,
):
    from poker_coach.simulator import ObservationV1

    return ObservationV1.model_validate(
        {
            "handId": "provider-test",
            "sequence": 4,
            "observerSeat": 0,
            "tableSize": 2,
            "buttonSeat": button_seat,
            "street": street,
            "ownHoleCards": own_hole_cards,
            "board": board,
            "pot": pot,
            "stacks": {"0": 9700, "1": 9700},
            "streetCommitments": {"0": 0, "1": 0},
            "activeSeats": [0, 1],
            "legalActions": legal_actions,
        }
    )


def _legal(action: str, minimum: int | None = None, maximum: int | None = None):
    semantics = {"fold": "none", "check": "none", "call": "cost", "bet": "by", "raise": "to"}[action]
    value: dict[str, object] = {"action": action, "amountSemantics": semantics}
    if minimum is not None:
        value["minAmount"] = minimum
        value["maxAmount"] = maximum
    return value


@pytest.mark.parametrize("profile_id", ["cautious", "balanced", "aggressive"])
def test_blueprint_profiles_are_deterministic_for_same_visible_inputs(profile_id):
    provider = build_bot_provider(profile_id)
    observation = _observation([_legal("fold"), _legal("call", 125, 125), _legal("raise", 400, 1500)])

    first = asyncio.run(provider.decide(observation, observation.legal_actions, 20, 817))
    second = asyncio.run(provider.decide(observation, observation.legal_actions, 20, 817))

    assert first == second
    assert first.metadata["kind"] == "lightweight-heuristic"
    assert first.metadata["profileId"] == profile_id


def test_blueprint_profiles_have_explainable_distinct_facing_wager_behavior():
    observation = _observation([_legal("fold"), _legal("call", 125, 125), _legal("raise", 400, 1500)])

    decisions = {
        profile: asyncio.run(
            build_bot_provider(profile).decide(observation, observation.legal_actions, 20, 7)
        )
        for profile in ("cautious", "balanced", "aggressive")
    }

    assert (decisions["cautious"].action.value, decisions["cautious"].amount) == ("fold", None)
    assert (decisions["balanced"].action.value, decisions["balanced"].amount) == ("call", 125)
    assert (decisions["aggressive"].action.value, decisions["aggressive"].amount) == ("raise", 1500)


@pytest.mark.parametrize(
    "legal_actions",
    [
        [_legal("fold")],
        [_legal("check"), _legal("bet", 100, 9750)],
        [_legal("fold"), _legal("call", 125, 125)],
        [_legal("fold"), _legal("call", 125, 125), _legal("raise", 400, 1500)],
    ],
)
@pytest.mark.parametrize("profile_id", ["fixed", "cautious", "balanced", "aggressive"])
def test_every_profile_decision_is_runtime_accepted_and_uses_legal_amounts(legal_actions, profile_id):
    observation = _observation(legal_actions)
    decision = asyncio.run(
        BotRuntime().decide(build_bot_provider(profile_id), observation, time_budget_ms=20, rng_seed=99)
    )

    assert decision.degraded is False
    assert any(item.accepts(action=decision.action, amount=decision.amount) for item in observation.legal_actions)


def test_blueprint_sizing_respects_minimum_midpoint_and_maximum_boundaries():
    bet = LegalActionV1(action="bet", amountSemantics="by", minAmount=100, maxAmount=901)
    raise_to = LegalActionV1(action="raise", amountSemantics="to", minAmount=400, maxAmount=1500)
    observation = _observation([_legal("bet", 100, 901)])

    cautious = asyncio.run(LightweightBlueprintProvider("cautious").decide(observation, (bet,), 20, 1))
    balanced = asyncio.run(LightweightBlueprintProvider("balanced").decide(observation, (bet,), 20, 1))
    aggressive = asyncio.run(LightweightBlueprintProvider("aggressive").decide(observation, (raise_to,), 20, 1))

    assert cautious.amount == 100
    assert balanced.amount == 500
    assert aggressive.amount == 1500


def test_factory_rejects_unknown_profile_id():
    with pytest.raises(ValueError, match="unknown bot profile"):
        build_bot_provider("solver-gto")


def test_balanced_blueprint_has_deterministic_passive_fold_bet_and_raise_spots():
    provider = LightweightBlueprintProvider("balanced")
    spots = {
        "passive": _observation([_legal("check"), _legal("bet", 100, 900)]),
        "fold": _observation(
            [_legal("fold"), _legal("call", 900, 900), _legal("raise", 1800, 3000)],
            own_hole_cards=("7c", "2d"),
            pot=100,
        ),
        "bet": _observation(
            [_legal("check"), _legal("bet", 100, 900)],
            own_hole_cards=("Ah", "Ad"),
            board=("Ac", "7d", "2h"),
        ),
        "raise": _observation(
            [_legal("fold"), _legal("call", 150, 150), _legal("raise", 400, 1500)],
            own_hole_cards=("Ah", "Ad"),
            board=("Ac", "7d", "2h"),
        ),
        "call": _observation(
            [_legal("fold"), _legal("call", 50, 50), _legal("raise", 200, 800)],
            own_hole_cards=("Ks", "Qd"),
            pot=400,
        ),
    }

    decisions = {
        name: asyncio.run(provider.decide(spot, spot.legal_actions, 20, 123))
        for name, spot in spots.items()
    }

    assert {name: decision.action.value for name, decision in decisions.items()} == {
        "passive": "check",
        "fold": "fold",
        "bet": "bet",
        "raise": "raise",
        "call": "call",
    }
    assert decisions["raise"].amount == 950
    assert all(
        any(legal.accepts(action=decision.action, amount=decision.amount) for legal in spots[name].legal_actions)
        for name, decision in decisions.items()
    )
