import json
import sqlite3

from poker_coach.analysis import analyze_scenario
from poker_coach.learning import LearningService
from poker_coach.learning.models import LearningProfile
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
    raw_scenario = json.loads(original.to_json())
    raw_scenario["heroHoleCards"] = ["kd", "as"]
    raw_scenario_json = json.dumps(raw_scenario, ensure_ascii=False, separators=(",", ":"))

    created = store.create_scenario(
        original,
        title="First hand",
        tags=("review",),
        raw_scenario_json=raw_scenario_json,
    )
    assert created["revisionNo"] == 1
    assert created["scenario"].to_json() == original.to_json()
    assert created["rawScenario"]["heroHoleCards"] == ["kd", "as"]

    updated_scenario = original.model_copy(update={"tags": ("updated",)})
    updated = store.update_scenario(
        created["scenarioId"],
        updated_scenario,
        title="Updated hand",
        tags=("updated",),
        raw_scenario_json=raw_scenario_json,
    )
    assert updated["revisionNo"] == 2
    assert store.list_scenarios(query="Updated")[0]["scenarioId"] == created["scenarioId"]
    revisions = store.list_scenario_revisions(created["scenarioId"])
    assert [item["revisionNo"] for item in revisions] == [2, 1]
    assert revisions[-1]["rawScenario"]["heroHoleCards"] == ["kd", "as"]
    assert store.get_scenario_revision(created["scenarioId"], 1)["scenario"].to_json() == original.to_json()

    copied = store.copy_scenario(created["scenarioId"])
    assert copied["scenarioId"] != created["scenarioId"]
    assert copied["revisionNo"] == 1

    result = analyze_scenario(updated_scenario)
    run = store.save_analysis(
        created["scenarioId"], result, raw_scenario=updated_scenario, execution_ms=1.25
    )
    assert run["status"] == "completed"
    assert run["output"]["analysisVersion"] == "analysis-core-0.1"
    assert run["rawScenario"]["schemaVersion"] == 1
    assert run["normalizedScenario"]["schemaVersion"] == 1
    assert run["rawScenario"]["heroHoleCards"] == ["kd", "as"]
    assert run["normalizedScenario"]["heroHoleCards"] == ["Kd", "As"]
    assert store.list_analyses(created["scenarioId"])[0]["analysisId"] == run["analysisId"]
    historical = store.get_scenario_revision(created["scenarioId"], 1)
    historical_run = store.save_analysis(
        created["scenarioId"],
        analyze_scenario(historical["scenario"]),
        raw_scenario=historical["scenario"],
        revision_no=1,
        execution_ms=1.0,
    )
    assert historical_run["revisionNo"] == 1
    assert historical_run["normalizedScenario"]["tags"] == []
    assert {item["analysisId"] for item in store.list_analyses(created["scenarioId"])} == {
        run["analysisId"],
        historical_run["analysisId"],
    }
    assert store._connection.execute(
        "SELECT COUNT(*) FROM evidence_items WHERE analysis_id = ?", (run["analysisId"],)
    ).fetchone()[0] > 0
    store.delete_scenario(created["scenarioId"])
    with __import__("pytest").raises(StoreNotFound):
        store.get_scenario(created["scenarioId"])
    store.close()


def test_sqlite_store_migrates_legacy_strategy_artifact_primary_key(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE strategy_artifacts (
            artifact_id TEXT PRIMARY KEY,
            artifact_version TEXT NOT NULL,
            artifact_json TEXT NOT NULL,
            source_level TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (artifact_id, artifact_version)
        );
        INSERT INTO strategy_artifacts VALUES ('artifact', '1', '{}', 'curated', 'now');
        INSERT INTO strategy_artifacts VALUES ('artifact-2', '1', '{}', 'curated', 'now');
        """
    )
    connection.commit()
    connection.close()

    store = SQLiteStore(path)
    rows = store._connection.execute(
        "SELECT artifact_id, artifact_version FROM strategy_artifacts ORDER BY artifact_id"
    ).fetchall()

    assert [(row[0], row[1]) for row in rows] == [("artifact", "1"), ("artifact-2", "1")]
    store.close()


def test_sqlite_store_migrates_legacy_scenario_snapshots(tmp_path):
    path = tmp_path / "legacy-scenarios.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE scenarios (
            scenario_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            scenario_json TEXT NOT NULL,
            scenario_hash TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE scenario_revisions (
            revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            scenario_json TEXT NOT NULL,
            scenario_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO scenarios VALUES ('scenario-1', 'legacy', '{"schemaVersion":1}', 'hash', '[]', 0, 'now', 'now');
        INSERT INTO scenario_revisions (scenario_id, revision_no, scenario_json, scenario_hash, created_at)
        VALUES ('scenario-1', 1, '{"schemaVersion":1}', 'hash', 'now');
        """
    )
    connection.commit()
    connection.close()

    store = SQLiteStore(path)
    scenario_columns = {
        row[1] for row in store._connection.execute("PRAGMA table_info(scenarios)").fetchall()
    }
    revision_columns = {
        row[1]
        for row in store._connection.execute("PRAGMA table_info(scenario_revisions)").fetchall()
    }
    assert "raw_scenario_json" in scenario_columns
    assert "raw_scenario_json" in revision_columns
    assert store._connection.execute(
        "SELECT raw_scenario_json FROM scenarios WHERE scenario_id = 'scenario-1'"
    ).fetchone()[0] == '{"schemaVersion":1}'
    store.close()


def test_sqlite_store_persists_learning_profile_practice_and_teaching_session(tmp_path):
    store = SQLiteStore(tmp_path / "learning.sqlite3")
    original = scenario()
    saved = store.create_scenario(original, title="Practice source")
    profile = store.get_or_create_profile("profile-1")
    question = LearningService().generate_practice(
        original,
        profile_id=profile.profile_id,
        source_scenario_id=saved["scenarioId"],
        mistake_tag="pot_odds",
    )
    public_question = store.save_practice_question(question)
    loaded = store.get_practice_question(question.question_id)
    assert public_question["questionId"] == question.question_id
    assert loaded.to_json() == question.to_json()

    outcome = LearningService().grade(
        loaded,
        selected_action=loaded.expected_action,
        profile=profile,
    )
    stored_outcome = store.save_practice_outcome(loaded, outcome)
    assert stored_outcome["attempt"]["correct"] is True
    assert stored_outcome["profile"]["profileId"] == "profile-1"

    session = store.save_teaching_session(
        {"responseVersion": "1", "summary": {"text": "ok"}},
        teacher_version="teaching-core-0.1",
        depth="beginner",
        profile_id="profile-1",
        scenario_id=saved["scenarioId"],
    )
    assert session["sessionId"]
    store.close()
