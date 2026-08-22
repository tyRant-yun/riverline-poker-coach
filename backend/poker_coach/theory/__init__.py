"""Offline theory benchmark contracts (not wired into production recommendations)."""

from .benchmark import FROZEN_THRESHOLD_MANIFEST, evaluate_fixture, load_corpus, run_benchmark
from .contracts import BenchmarkResult, Coverage, CoverageStatus, EvidenceGrade, LegalSizing, SpotIdentity, TheoryPolicy, TheorySource

__all__ = ["BenchmarkResult", "Coverage", "CoverageStatus", "EvidenceGrade", "FROZEN_THRESHOLD_MANIFEST", "LegalSizing", "SpotIdentity", "TheoryPolicy", "TheorySource", "evaluate_fixture", "load_corpus", "run_benchmark"]
