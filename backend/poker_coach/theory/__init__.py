"""Offline theory benchmark contracts (not wired into production recommendations)."""

from .benchmark import FROZEN_THRESHOLD_MANIFEST, evaluate_fixture, load_corpus, run_benchmark
from .contracts import BenchmarkResult, Coverage, CoverageStatus, EvidenceGrade, LegalSizing, SpotIdentity, TheoryPolicy, TheorySource
from .policy_artifact import PolicyArtifact, PolicyArtifactError, PreflopPolicyContext, default_preflop_artifact, hand_class_from_cards
from .recommendation import (
    L2RecommendationInput,
    OracleEvLossInput,
    TheoryDecisionIdentityV1,
    TheoryEvidenceV1,
    TheoryExplainer,
    TheoryRecommendationV1,
)

__all__ = ["BenchmarkResult", "Coverage", "CoverageStatus", "EvidenceGrade", "FROZEN_THRESHOLD_MANIFEST", "L2RecommendationInput", "LegalSizing", "OracleEvLossInput", "PolicyArtifact", "PolicyArtifactError", "PreflopPolicyContext", "SpotIdentity", "TheoryDecisionIdentityV1", "TheoryEvidenceV1", "TheoryExplainer", "TheoryPolicy", "TheoryRecommendationV1", "TheorySource", "default_preflop_artifact", "evaluate_fixture", "hand_class_from_cards", "load_corpus", "run_benchmark"]
