from decimal import Decimal

from poker_coach.domain.models import AnalysisLevel, ScenarioSpec
from poker_coach.strategy.catalog import StrategyCatalog
from poker_coach.strategy.features import features_for_scenario
from poker_coach.strategy.models import MatchLevel, StrategyArtifact, StrategyRecommendation
from poker_coach.strategy.ranges import default_preflop_ranges


def scenario(*, stack=10_000, street="preflop", board=(), actions=()):
    seats = [
        {"seatId": 0, "startingStack": 10_000, "position": "button"},
        {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
    ]
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [{**seat, "startingStack": stack} for seat in seats],
            "heroHoleCards": ["As", "Kd"],
            "board": list(board),
            "actionHistory": list(actions),
            "decisionPoint": {
                "street": street,
                "actorSeat": 0,
                "afterSequence": len(actions),
            },
        }
    )


def test_default_preflop_ranges_are_versioned_and_traceable():
    ranges = default_preflop_ranges()

    assert set(ranges) == {"btn_open", "bb_defend", "bb_3bet", "btn_vs_3bet", "btn_4bet", "bb_vs_4bet"}
    assert all(item.is_default_assumption for item in ranges.values())
    assert all(item.source.value == "default_preflop" for item in ranges.values())
    assert all(item.version == "preflop-100bb-0.1" for item in ranges.values())
    assert all(item.matrix_169 for item in ranges.values())


def test_catalog_covers_the_common_postflop_teaching_topics():
    artifacts = StrategyCatalog().artifacts
    artifact_ids = {artifact.artifact_id for artifact in artifacts}

    assert {
        "curated.postflop.btn-bb.a-high-dry",
        "curated.postflop.btn-bb.k-high-dry",
        "curated.postflop.btn-bb.low-connected",
        "curated.postflop.btn-bb.paired-board",
        "curated.postflop.btn-bb.monotone",
        "curated.postflop.btn-bb.turn-barrel",
        "curated.postflop.btn-bb.river-bluff-catcher",
        "curated.postflop.btn-bb.thin-value",
        "curated.postflop.btn-bb.blocker-bluff",
    } <= artifact_ids
    assert all(
        recommendation.frequency is None and recommendation.ev is None
        for artifact in artifacts
        for recommendation in artifact.recommendations
    )


def test_board_features_distinguish_ace_high_and_king_high():
    flop_event = {
        "actionId": "flop",
        "sequence": 1,
        "street": "flop",
        "actorSeat": 0,
        "actionType": "deal_flop",
    }
    ace_high = features_for_scenario(
        scenario(board=("Ac", "7d", "2h"), street="flop", actions=(flop_event,))
    )
    king_high = features_for_scenario(
        scenario(board=("Kc", "7d", "2h"), street="flop", actions=(flop_event,))
    )

    assert "ace_high" in ace_high.board_labels
    assert "king_high" not in ace_high.board_labels
    assert "king_high" in king_high.board_labels
    assert "ace_high" not in king_high.board_labels


def test_strategy_features_ignore_future_board_cards_before_they_are_dealt():
    features = features_for_scenario(
        scenario(
            street="preflop",
            board=("Ac", "7d", "2h", "Ks", "Qc"),
            actions=(),
        )
    )

    assert features.board_labels == ()


def test_exact_match_returns_curated_qualitative_recommendations_without_fake_frequency():
    result = StrategyCatalog().match(scenario())

    assert result.level is MatchLevel.EXACT
    assert result.source_level is AnalysisLevel.CURATED
    assert result.can_quote_frequencies is False
    assert result.recommendations
    assert all(item.frequency is None for item in result.recommendations)


def test_material_difference_is_approximate_and_exposes_difference():
    artifact = StrategyCatalog().artifacts[0].model_copy(
        update={"street": "flop", "action_signature": ("all_in",), "board_labels": ("monotone",)}
    )
    result = StrategyCatalog((artifact,)).match(scenario())

    assert result.level is MatchLevel.APPROXIMATE
    assert result.can_quote_frequencies is False
    assert any(item.field in {"street", "action_signature", "board_labels"} for item in result.differences)


def test_no_match_does_not_identify_an_artifact():
    artifact = StrategyCatalog().artifacts[0].model_copy(
        update={
            "hero_position": "big_blind",
            "villain_position": "button",
            "street": "river",
            "action_signature": ("all_in",),
            "board_labels": ("monotone",),
            "rake_signature": "with_rake",
            "hero_range_id": "different.hero",
            "villain_range_id": "different.villain",
            "bet_size_signature": ("large",),
        }
    )
    result = StrategyCatalog((artifact,)).match(scenario())

    assert result.level is MatchLevel.NO_MATCH
    assert result.artifact_id is None
    assert result.can_quote_frequencies is False


def test_compatible_match_cannot_quote_frequency_without_explicit_approval():
    artifact = StrategyArtifact(
        artifactId="test.quantitative",
        name="Test quantitative artifact",
        version="1",
        source="test fixture",
        license="MIT",
        creator="tests",
        gameVariant="nlhe",
        tableSize=2,
        stackMinBb=100,
        stackMaxBb=100,
        rakeSignature="no_rake",
        heroPosition="button",
        villainPosition="big_blind",
        street="preflop",
        actionSignature=(),
        boardLabels=(),
        sourceLevel="solver_backed",
        quantitativeBasis="fixture solver export",
        recommendations=(
            StrategyRecommendation(
                action="raise_to",
                summary="fixture",
                frequency=Decimal("0.5"),
                sourceLevel="solver_backed",
                quantitativeBasis="fixture solver export",
            ),
        ),
    )
    result = StrategyCatalog((artifact,)).match(scenario(stack=12_000))

    assert result.level is MatchLevel.COMPATIBLE
    assert result.can_quote_frequencies is False


def test_exact_solver_artifact_may_quote_frequency_when_basis_is_present():
    artifact = StrategyArtifact(
        artifactId="test.exact.quantitative",
        name="Exact quantitative artifact",
        version="1",
        source="test fixture",
        license="MIT",
        creator="tests",
        gameVariant="nlhe",
        tableSize=2,
        stackMinBb=100,
        stackMaxBb=100,
        rakeSignature="no_rake",
        heroPosition="button",
        villainPosition="big_blind",
        street="preflop",
        actionSignature=(),
        boardLabels=(),
        sourceLevel="solver_backed",
        quantitativeBasis="fixture solver export",
        recommendations=(
            StrategyRecommendation(
                action="raise_to",
                summary="fixture",
                frequency=Decimal("0.5"),
                sourceLevel="solver_backed",
                quantitativeBasis="fixture solver export",
            ),
        ),
    )
    result = StrategyCatalog((artifact,)).match(scenario())

    assert result.level is MatchLevel.EXACT
    assert result.can_quote_frequencies is True
    assert result.recommendations[0].frequency == Decimal("0.5")
