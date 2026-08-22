"""Versioned, additive contracts for the offline theory benchmark."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class EvidenceGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    UNSUPPORTED = "unsupported"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    FALLBACK = "fallback"
    UNSUPPORTED = "unsupported"


class SpotIdentity(_FrozenContract):
    """The complete compatibility key of one canonical theory decision node."""

    schema_version: Annotated[int, Field(ge=1)] = 1
    spot_id: Annotated[str, Field(min_length=1)]
    game_fingerprint: Annotated[str, Field(min_length=1)]
    tree_fingerprint: Annotated[str, Field(min_length=1)]
    range_fingerprint: Annotated[str, Field(min_length=1)]
    policy_fingerprint: Annotated[str, Field(min_length=1)]


class TheorySource(_FrozenContract):
    source_kind: Annotated[str, Field(min_length=1)]
    evidence_grade: EvidenceGrade
    version: Annotated[str, Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]
    provenance: Annotated[str, Field(min_length=1)]
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Coverage(_FrozenContract):
    status: CoverageStatus
    reason: str | None = None
    players: Annotated[int, Field(ge=2, le=9)]
    street: Annotated[str, Field(min_length=1)]


class PolicyAction(_FrozenContract):
    action: Annotated[str, Field(min_length=1)]
    frequency: Annotated[float, Field(ge=0.0, le=1.0)]
    amount: Annotated[int, Field(ge=0)] | None = None
    ev: float | None = None


class LegalSizing(_FrozenContract):
    action: Annotated[str, Field(min_length=1)]
    min_amount: Annotated[int, Field(ge=0)]
    max_amount: Annotated[int, Field(ge=0)]
    canonical_amount: Annotated[int, Field(ge=0)]


class TheoryPolicy(_FrozenContract):
    """An immutable provider payload that a later adapter can benchmark."""

    schema_version: Annotated[int, Field(ge=1)] = 1
    identity: SpotIdentity
    source: TheorySource
    coverage: Coverage
    action_frequencies: tuple[PolicyAction, ...]
    legal_sizings: tuple[LegalSizing, ...] = ()
    ev_definition: str | None = None
    range_distribution: tuple[tuple[str, float], ...] = ()


class ThresholdManifest(_FrozenContract):
    """Thresholds are owned by the harness, never by a provider or fixture."""

    manifest_id: Annotated[str, Field(min_length=1)]
    action_frequency_l1_max: Annotated[float, Field(ge=0.0)]
    sizing_distance_max: Annotated[int, Field(ge=0)]
    ev_loss_max: Annotated[float, Field(ge=0.0)]
    range_js_max: Annotated[float, Field(ge=0.0)]
    latency_ms_max: Annotated[float, Field(gt=0.0)]


class MetricResult(_FrozenContract):
    name: str
    status: str
    value: float | None = None
    threshold: float | None = None
    detail: str | None = None


class FixtureResult(_FrozenContract):
    fixture_id: str
    gate_passed: bool
    expected_gate_passed: bool
    metrics: tuple[MetricResult, ...]
    elapsed_ms: float


class BenchmarkResult(_FrozenContract):
    schema_version: Annotated[int, Field(ge=1)] = 1
    harness_version: str
    threshold_manifest_id: str
    gate_passed: bool
    corpus_expectations_met: bool
    environment: dict[str, str]
    performance_note: str
    fixtures: tuple[FixtureResult, ...]
