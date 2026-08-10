"""Curated strategy catalog with explicit exact/approximate matching."""

from __future__ import annotations

from decimal import Decimal

from poker_coach.domain.models import AnalysisLevel, GameVariant, SeatPosition, Street

from .features import ScenarioFeatures, features_for_scenario
from .models import (
    MatchLevel,
    StrategyArtifact,
    StrategyDifference,
    StrategyMatch,
    StrategyRecommendation,
)


STRATEGY_LIBRARY_VERSION = "curated-strategy-0.1"


class StrategyCatalog:
    def __init__(
        self,
        artifacts: tuple[StrategyArtifact, ...] | None = None,
        *,
        version: str = STRATEGY_LIBRARY_VERSION,
    ):
        self.version = version
        self.artifacts = artifacts or default_strategy_artifacts()

    def match(self, scenario) -> StrategyMatch:
        features = features_for_scenario(scenario)
        scored = [(self._score(artifact, features), artifact) for artifact in self.artifacts]
        if not scored:
            return _no_match(self.version, "strategy catalog is empty")
        score, artifact = max(scored, key=lambda item: item[0][0])
        similarity, differences = score
        if similarity < Decimal("0.50"):
            return _no_match(
                self.version,
                "no strategy artifact is sufficiently similar",
                differences=differences,
                similarity=similarity,
            )
        level = _match_level(artifact, differences, similarity)
        can_quote = (
            level is MatchLevel.EXACT
            or (level is MatchLevel.COMPATIBLE and artifact.compatible_frequency_approved)
        ) and any(
            recommendation.frequency is not None or recommendation.ev is not None
            for recommendation in artifact.recommendations
        )
        explanation = {
            MatchLevel.EXACT: "all constrained strategy fields match",
            MatchLevel.COMPATIBLE: "the artifact is compatible with limited declared differences",
            MatchLevel.APPROXIMATE: "the artifact is a teaching reference with material differences",
        }[level]
        return StrategyMatch(
            libraryVersion=self.version,
            level=level,
            artifactId=artifact.artifact_id,
            artifactVersion=artifact.version,
            similarity=similarity,
            confidence=similarity if level is not MatchLevel.APPROXIMATE else similarity * Decimal("0.75"),
            differences=tuple(differences),
            canQuoteFrequencies=can_quote,
            sourceLevel=artifact.source_level,
            recommendations=artifact.recommendations,
            explanation=explanation,
        )

    @staticmethod
    def _score(
        artifact: StrategyArtifact,
        features: ScenarioFeatures,
    ) -> tuple[Decimal, tuple[StrategyDifference, ...]]:
        comparisons: list[tuple[str, Decimal, object, object, str]] = [
            ("game_variant", Decimal("1.0"), features.game_variant, artifact.game_variant.value, "game variant differs"),
            ("table_size", Decimal("1.0"), features.table_size, artifact.table_size, "table size differs"),
            ("hero_position", Decimal("1.0"), features.hero_position, artifact.hero_position, "hero position differs"),
            ("villain_position", Decimal("1.0"), features.villain_position, artifact.villain_position, "villain position differs"),
            ("street", Decimal("1.0"), features.street, artifact.street, "decision street differs"),
            ("rake_signature", Decimal("1.0"), features.rake_signature, artifact.rake_signature, "rake assumption differs"),
            ("stack_bb", Decimal("1.0"), features.stack_bb, (artifact.stack_min_bb, artifact.stack_max_bb), "effective stack is outside the artifact range"),
            ("action_signature", Decimal("1.5"), features.action_signature, artifact.action_signature, "action history differs"),
            ("board_labels", Decimal("1.5"), features.board_labels, artifact.board_labels, "board texture differs"),
            ("hero_range_id", Decimal("0.75"), features.hero_range_id, artifact.hero_range_id, "hero range differs"),
            ("villain_range_id", Decimal("0.75"), features.villain_range_id, artifact.villain_range_id, "villain range differs"),
            ("bet_size_signature", Decimal("0.75"), features.bet_size_signature, artifact.bet_size_signature, "bet-size assumptions differ"),
        ]
        total = sum((weight for _, weight, _, _, _ in comparisons), Decimal("0"))
        matched = Decimal("0")
        differences: list[StrategyDifference] = []
        for field, weight, requested, expected, impact in comparisons:
            if _matches(field, requested, expected):
                matched += weight
            else:
                differences.append(
                    StrategyDifference(
                        field=field,
                        requested=_json_value(requested),
                        artifact=_json_value(expected),
                        impact=impact,
                    )
                )
        similarity = (matched / total).quantize(Decimal("0.0001")) if total else Decimal("0")
        return similarity, tuple(differences)


def default_strategy_artifacts() -> tuple[StrategyArtifact, ...]:
    curated = AnalysisLevel.CURATED
    return (
        StrategyArtifact(
            artifactId="curated.preflop.btn-open-100bb",
            name="BTN open, 100BB, no rake",
            version="1",
            source="poker-coach curated teaching catalog",
            license="Original project data",
            creator="poker-coach",
            gameVariant=GameVariant.NLHE,
            tableSize=2,
            stackMinBb=Decimal("100"),
            stackMaxBb=Decimal("100"),
            rakeSignature="no_rake",
            heroPosition=SeatPosition.BUTTON,
            villainPosition=SeatPosition.BIG_BLIND,
            street=Street.PREFLOP,
            actionSignature=(),
            boardLabels=(),
            sourceLevel=curated,
            assumptions=("HU NLHE", "100BB effective", "no rake", "qualitative teaching reference"),
            recommendations=(
                StrategyRecommendation(
                    action="raise_to",
                    summary="Use a raise-first opening plan from the button; exact sizing remains a user assumption.",
                    sourceLevel=curated,
                ),
            ),
        ),
        StrategyArtifact(
            artifactId="curated.postflop.btn-bb.a-high-dry",
            name="BTN vs BB single-raised pot, A-high dry flop",
            version="1",
            source="poker-coach curated teaching catalog",
            license="Original project data",
            creator="poker-coach",
            gameVariant=GameVariant.NLHE,
            tableSize=2,
            stackMinBb=Decimal("80"),
            stackMaxBb=Decimal("120"),
            rakeSignature="no_rake",
            heroPosition=SeatPosition.BUTTON,
            villainPosition=SeatPosition.BIG_BLIND,
            street=Street.FLOP,
            actionSignature=("raise_to", "call"),
            boardLabels=("rainbow", "disconnected", "high_card_structure", "ace_high"),
            sourceLevel=curated,
            assumptions=("single-raised pot", "qualitative c-bet/check comparison", "no solver frequency"),
            recommendations=(
                StrategyRecommendation(
                    action="bet",
                    summary="A small continuation bet can be a reasonable principle line when range interaction supports it.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="check",
                    summary="Checking remains a valid alternative when the hand benefits from pot control or protection.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.k-high-dry",
            name="BTN vs BB K-high dry flop",
            board_labels=("rainbow", "disconnected", "high_card_structure", "king_high"),
            assumptions=("single-raised pot", "K-high dry texture", "qualitative small c-bet/check reference"),
            recommendations=(
                StrategyRecommendation(
                    action="bet",
                    summary="A small bet can pressure the capped defending range, while checking protects hands that prefer realization.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="check",
                    summary="Check some showdown-value and low-equity hands when the board gives the defender useful backdoor interaction.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.low-connected",
            name="BTN vs BB low connected flop",
            board_labels=("rainbow", "highly_connected", "low_card_structure"),
            assumptions=("single-raised pot", "low connected texture", "range-check and protection reference"),
            recommendations=(
                StrategyRecommendation(
                    action="check",
                    summary="Connected low boards interact more with the blind defense; checking more often can protect the opening range.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="bet",
                    summary="Bet selected strong or high-equity hands with a plan for turns rather than auto-c-betting the whole range.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.monotone",
            name="BTN vs BB monotone flop",
            board_labels=("monotone",),
            assumptions=("single-raised pot", "monotone texture", "flush-completion risk is qualitative"),
            recommendations=(
                StrategyRecommendation(
                    action="check",
                    summary="On monotone boards, account for flush interaction and avoid treating one-pair hands as automatic value bets.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="bet",
                    summary="Use selective bets with robust equity, relevant suit blockers, or credible future-street plans.",
                    sourceLevel=curated,
                ),
            ),
        ),
        StrategyArtifact(
            artifactId="curated.postflop.btn-bb.paired-board",
            name="BTN vs BB paired flop",
            version="1",
            source="poker-coach curated teaching catalog",
            license="Original project data",
            creator="poker-coach",
            gameVariant=GameVariant.NLHE,
            tableSize=2,
            stackMinBb=80,
            stackMaxBb=120,
            rakeSignature="no_rake",
            heroPosition=SeatPosition.BUTTON,
            villainPosition=SeatPosition.BIG_BLIND,
            street=Street.FLOP,
            actionSignature=("raise_to", "call"),
            boardLabels=("paired",),
            sourceLevel=curated,
            assumptions=("paired-board category", "exact ranks still matter", "qualitative reference only"),
            recommendations=(
                StrategyRecommendation(
                    action="check",
                    summary="On paired boards, compare range interaction and showdown value before choosing a high-frequency bluff line.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.turn-barrel",
            name="BTN vs BB turn barrel",
            street=Street.TURN,
            action_signature=("raise_to", "call", "bet", "call"),
            board_labels=("high_card_structure",),
            assumptions=("single-raised pot", "turn barrel node", "future river plan required"),
            recommendations=(
                StrategyRecommendation(
                    action="bet",
                    summary="Turn barrels should be selected with a clear river plan: value, equity denial, or credible bluff development.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="check",
                    summary="Check hands that cannot improve the opponent's range or continue profitably against a raise.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.river-bluff-catcher",
            name="BTN vs BB river bluff catcher",
            street=Street.RIVER,
            action_signature=("raise_to", "call", "bet", "call", "bet"),
            board_labels=("paired",),
            assumptions=("river facing a bet", "bluff-catcher decision", "value/bluff composition is not solver-precise"),
            recommendations=(
                StrategyRecommendation(
                    action="call",
                    summary="Call bluff catchers when the price and plausible missed bluffs justify it; do not use hand strength alone.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="fold",
                    summary="Fold when the line is value-heavy under the declared range and blocker assumptions.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.thin-value",
            name="BTN vs BB river thin value",
            street=Street.RIVER,
            action_signature=("raise_to", "call", "bet", "call", "check"),
            board_labels=("high_card_structure",),
            assumptions=("river checked to hero", "thin value node", "opponent calling range must be explicit"),
            recommendations=(
                StrategyRecommendation(
                    action="bet",
                    summary="Thin value depends on which worse hands can call; choose a size that keeps those calls available.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="check",
                    summary="Check when worse calls are scarce or the hand has enough showdown value without risking a raise.",
                    sourceLevel=curated,
                ),
            ),
        ),
        _curated_postflop_artifact(
            artifact_id="curated.postflop.btn-bb.blocker-bluff",
            name="BTN vs BB river blocker bluff",
            street=Street.RIVER,
            action_signature=("raise_to", "call", "bet", "call", "bet"),
            board_labels=("monotone",),
            assumptions=("river facing a bet", "blocker candidate", "unblocker and fold equity must be checked"),
            recommendations=(
                StrategyRecommendation(
                    action="raise_to",
                    summary="A blocker bluff is only credible when it blocks relevant value and the opponent can fold enough of the remaining range.",
                    sourceLevel=curated,
                ),
                StrategyRecommendation(
                    action="fold",
                    summary="Do not bluff simply because a card is a blocker; preserve the hand when the range interaction is unfavorable.",
                    sourceLevel=curated,
                ),
            ),
        ),
    )


def _curated_postflop_artifact(
    *,
    artifact_id: str,
    name: str,
    board_labels: tuple[str, ...],
    assumptions: tuple[str, ...],
    recommendations: tuple[StrategyRecommendation, ...],
    street: Street = Street.FLOP,
    action_signature: tuple[str, ...] = ("raise_to", "call"),
) -> StrategyArtifact:
    return StrategyArtifact(
        artifactId=artifact_id,
        name=name,
        version="1",
        source="poker-coach curated teaching catalog",
        license="Original project data",
        creator="poker-coach",
        gameVariant=GameVariant.NLHE,
        tableSize=2,
        stackMinBb=Decimal("80"),
        stackMaxBb=Decimal("120"),
        rakeSignature="no_rake",
        heroPosition=SeatPosition.BUTTON,
        villainPosition=SeatPosition.BIG_BLIND,
        street=street,
        actionSignature=action_signature,
        boardLabels=board_labels,
        sourceLevel=AnalysisLevel.CURATED,
        assumptions=assumptions,
        recommendations=recommendations,
    )


def _matches(field: str, requested, expected) -> bool:
    if expected is None:
        return True
    if field == "stack_bb":
        return expected[0] <= requested <= expected[1]
    if field == "board_labels":
        expected_labels = set(expected)
        return expected_labels.issubset(set(requested))
    if field in {"action_signature", "bet_size_signature"}:
        return tuple(requested) == tuple(expected)
    if field in {"hero_position", "villain_position", "street"}:
        return requested == expected
    return requested == expected


def _match_level(
    artifact: StrategyArtifact,
    differences: tuple[StrategyDifference, ...],
    similarity: Decimal,
) -> MatchLevel:
    if not differences:
        return MatchLevel.EXACT
    compatible_fields = {"stack_bb", "board_labels", "bet_size_signature"}
    if similarity >= Decimal("0.80") and {difference.field for difference in differences} <= compatible_fields:
        return MatchLevel.COMPATIBLE
    return MatchLevel.APPROXIMATE


def _no_match(
    version: str,
    explanation: str,
    *,
    differences: tuple[StrategyDifference, ...] = (),
    similarity: Decimal = Decimal("0"),
) -> StrategyMatch:
    return StrategyMatch(
        libraryVersion=version,
        level=MatchLevel.NO_MATCH,
        similarity=similarity,
        confidence=Decimal("0"),
        differences=differences,
        explanation=explanation,
    )


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value
