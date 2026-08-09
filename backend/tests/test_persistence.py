from poker_coach.analysis import analyze_scenario
from poker_coach.persistence import SQLiteStore
from poker_coach.persistence.sqlite_store import StoreNotFound
from poker_coach.domain.models import ScenarioSpec


def scenario():
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "villainHoleCards": ["Qh", "Jc"],
            "board": ["2c", "7d", "Jh"],
            "actionHistory": [
                {
                    "actionId": "call",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "flop",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 0,
                    "actionType": "deal_flop",
                },
            ],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
            "assumptions": {},
        }
    )


def test_sqlite_store_revisions_copy_search_and_analysis_history(tmp_path):
    store = SQLiteStore(tmp_path / "coach.sqlite3")
    original = scenario()

    created = store.create_scenario(original, title="First hand", tags=("review",))
    assert created["revisionNo"] == 1
    assert created["scenario"].to_json() == original.to_json()

    updated_scenario = original.model_copy(update={"tags": ("updated",)})
    updated = store.update_scenario(
        created["scenarioId"], updated_scenario, title="Updated hand", tags=("updated",)
    )
    assert updated["revisionNo"] == 2
    assert store.list_scenarios(query="Updated")[0]["scenarioId"] == created["scenarioId"]

    copied = store.copy_scenario(created["scenarioId"])
    assert copied["scenarioId"] != created["scenarioId"]
    assert copied["revisionNo"] == 1

    result = analyze_scenario(updated_scenario)
    run = store.save_analysis(
        created["scenarioId"], result, raw_scenario=updated_scenario, execution_ms=1.25
    )
    assert run["status"] == "completed"
    assert run["output"]["analysisVersion"] == "analysis-core-0.1"
    assert store.list_analyses(created["scenarioId"])[0]["analysisId"] == run["analysisId"]

    store.delete_scenario(created["scenarioId"])
    with __import__("pytest").raises(StoreNotFound):
        store.get_scenario(created["scenarioId"])
    store.close()
