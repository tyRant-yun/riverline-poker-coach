"""Phase 8D: 8-max preflop knowledge — position-aware strategy matching."""

from poker_coach.domain.models import ScenarioSpec, positions_for_table
from poker_coach.strategy.catalog import StrategyCatalog
from poker_coach.strategy.features import features_for_scenario
from poker_coach.strategy.models import MatchLevel


def multiway_scenario(table_size, *, hero_seat=0, button_seat=0, **overrides):
    positions = [p.value for p in positions_for_table(table_size)]
    seats = [
        {
            "seatId": seat_id,
            "startingStack": 10_000,
            "position": positions[(seat_id - button_seat) % table_size],
        }
        for seat_id in range(table_size)
    ]
    payload = {
        "schemaVersion": 2,
        "gameVariant": "nlhe",
        "tableSize": table_size,
        "smallBlind": 50,
        "bigBlind": 100,
        "ante": 0,
        "buttonSeat": button_seat,
        "heroSeat": hero_seat,
        "seats": seats,
        "knownHoleCardsBySeat": {hero_seat: ["As", "Kd"]},
        "board": [],
        "actionHistory": [],
        "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
        "assumptions": {},
    }
    payload.update(overrides)
    return ScenarioSpec.model_validate(payload)


def action(sequence, actor_seat, action_type, street="preflop", amount=None, amount_type="none"):
    event = {
        "actionId": f"a{sequence}",
        "sequence": sequence,
        "street": street,
        "actorSeat": actor_seat,
        "actionType": action_type,
    }
    if amount is not None:
        event["amount"] = amount
        event["amountType"] = amount_type
    return event


CATALOG = StrategyCatalog()


class TestMultiwayFeatures:
    def test_villain_position_is_none_on_multiway_tables(self):
        features = features_for_scenario(multiway_scenario(6))
        assert features.villain_position is None
        assert features.hero_position.value == "button"

    def test_hu_still_derives_villain_position(self):
        features = features_for_scenario(multiway_scenario(2))
        assert features.villain_position.value == "big_blind"


class TestRfiMatching:
    def test_8max_utg_rfi_matches_utg_artifact(self):
        scenario = multiway_scenario(
            8,
            hero_seat=3,
            decisionPoint={"street": "preflop", "actorSeat": 3, "afterSequence": 0},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.8max.utg-rfi"
        assert match.level is MatchLevel.EXACT
        actions = {recommendation.action for recommendation in match.recommendations}
        assert actions == {"raise_to", "fold"}

    def test_8max_co_rfi_matches_co_artifact(self):
        scenario = multiway_scenario(
            8,
            hero_seat=7,
            decisionPoint={"street": "preflop", "actorSeat": 7, "afterSequence": 0},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.8max.co-rfi"

    def test_rfi_matching_is_position_specific(self):
        utg = CATALOG.match(
            multiway_scenario(
                8,
                hero_seat=3,
                decisionPoint={"street": "preflop", "actorSeat": 3, "afterSequence": 0},
            )
        )
        co = CATALOG.match(
            multiway_scenario(
                8,
                hero_seat=7,
                decisionPoint={"street": "preflop", "actorSeat": 7, "afterSequence": 0},
            )
        )
        assert utg.artifact_id != co.artifact_id

    def test_every_8max_seat_has_an_rfi_artifact(self):
        for hero_seat in range(8):
            scenario = multiway_scenario(
                8,
                hero_seat=hero_seat,
                decisionPoint={
                    "street": "preflop",
                    "actorSeat": hero_seat,
                    "afterSequence": 0,
                },
            )
            match = CATALOG.match(scenario)
            assert match.level is not MatchLevel.NO_MATCH
            assert match.artifact_id.endswith("-rfi")


class TestDefendAndThreeBet:
    def test_bb_defend_matches_defend_artifact(self):
        scenario = multiway_scenario(
            8,
            hero_seat=2,
            actionHistory=[action(1, 3, "raise_to", amount=300, amount_type="to")],
            decisionPoint={"street": "preflop", "actorSeat": 2, "afterSequence": 1},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.8max.bb-defend-vs-rfi"
        assert {r.action for r in match.recommendations} == {"call", "raise_to", "fold"}

    def test_sb_defend_matches_defend_artifact(self):
        scenario = multiway_scenario(
            8,
            hero_seat=1,
            actionHistory=[action(1, 3, "raise_to", amount=300, amount_type="to")],
            decisionPoint={"street": "preflop", "actorSeat": 1, "afterSequence": 1},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.8max.sb-defend-vs-rfi"

    def test_vs_three_bet_matches_three_bet_artifact(self):
        scenario = multiway_scenario(
            8,
            hero_seat=5,
            actionHistory=[
                action(1, 3, "raise_to", amount=300, amount_type="to"),
                action(2, 2, "raise_to", amount=900, amount_type="to"),
            ],
            decisionPoint={"street": "preflop", "actorSeat": 5, "afterSequence": 2},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.8max.vs-3bet"
        assert {r.action for r in match.recommendations} == {"raise_to", "call", "fold"}


class TestHuRegression:
    def test_hu_btn_open_still_matches_the_hu_artifact(self):
        scenario = multiway_scenario(
            2,
            hero_seat=0,
            decisionPoint={"street": "preflop", "actorSeat": 0, "afterSequence": 0},
        )
        match = CATALOG.match(scenario)
        assert match.artifact_id == "curated.preflop.btn-open-100bb"
        assert match.level is MatchLevel.EXACT
