"""Immutable, verified B-grade PolicyArtifact and its bounded preflop adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from poker_coach.simulator.contracts import ObservationV1

from .policy_artifact_data import ARTIFACT_VERSION, TREE_VERSION, _hand_classes, build_preflop_payload


class PolicyArtifactError(ValueError):
    """A policy artifact is malformed, altered, or outside this loader's version."""


@dataclass(frozen=True)
class PreflopPolicyContext:
    """Public table facts required to claim the artifact's narrow coverage."""

    big_blind: int = 100
    effective_stack_bb: int = 100
    rake_bps: int = 0
    ante_bb: int = 0
    tree_fingerprint: str = TREE_VERSION


@dataclass(frozen=True)
class PolicyMatch:
    node_id: str
    hand_class: str
    frequencies: Mapping[str, float]
    raise_to: int | None


@dataclass(frozen=True)
class PolicyArtifact:
    """Read-only artifact whose digest and policy fingerprint are verified on load."""

    payload: Mapping[str, Any]
    digest: str
    fingerprint: str

    @property
    def version(self) -> str:
        return str(self.payload["artifactVersion"])

    @property
    def source(self) -> Mapping[str, Any]:
        return self.payload["source"]

    @property
    def coverage(self) -> Mapping[str, Any]:
        return self.payload["coverage"]

    def to_payload(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy for inspection or offline export."""
        return _thaw(self.payload)

    @classmethod
    def load(cls, payload: Mapping[str, Any]) -> "PolicyArtifact":
        copied = json.loads(json.dumps(payload))
        _validate_shape(copied)
        if copied["schemaVersion"] != 1 or copied["artifactVersion"] != ARTIFACT_VERSION:
            raise PolicyArtifactError("unknown policy artifact schema or version")
        integrity = copied.get("integrity")
        if not isinstance(integrity, dict):
            raise PolicyArtifactError("policy artifact integrity metadata is required")
        declared_digest = integrity.get("digest")
        declared_fingerprint = integrity.get("fingerprint")
        if declared_digest != _digest(_without_integrity(copied)):
            raise PolicyArtifactError("policy artifact digest mismatch")
        if declared_fingerprint != _fingerprint(copied):
            raise PolicyArtifactError("policy artifact fingerprint mismatch")
        _validate_nodes(copied)
        return cls(payload=_freeze(copied), digest=declared_digest, fingerprint=declared_fingerprint)

    def match(self, observation: "ObservationV1", context: PreflopPolicyContext) -> PolicyMatch | None:
        reason = _coverage_miss(observation, context, self.coverage)
        if reason is not None:
            return None
        action_prefix = _action_prefix(observation, context.big_blind)
        if action_prefix is None:
            return None
        position = _position_for(observation.observer_seat, observation.button_seat, observation.table_size)
        hand_class = hand_class_from_cards(observation.own_hole_cards)
        for node in self.payload["nodes"]:
            if node["actionPrefix"] != action_prefix or node["actorPosition"] != position:
                continue
            if node["treeFingerprint"] != context.tree_fingerprint:
                continue
            entry = next(item for item in node["classFrequencies"] if item["handClass"] == hand_class)
            amount_bb = node["legalSizing"]["raise_to"]["amountBb"]
            return PolicyMatch(
                node_id=node["nodeId"],
                hand_class=hand_class,
                frequencies=entry["frequencies"],
                raise_to=int(amount_bb * context.big_blind),
            )
        return None


def default_preflop_artifact() -> PolicyArtifact:
    payload = build_preflop_payload()
    payload["integrity"] = {
        "digest": _digest(_without_integrity(payload)),
        "fingerprint": _fingerprint(payload),
    }
    return PolicyArtifact.load(payload)


def hand_class_from_cards(cards: tuple[str, str]) -> str:
    """Map one legal private two-card holding into a canonical 169-class key."""
    ranks = "AKQJT98765432"
    first, second = cards
    first_rank, second_rank = first[0], second[0]
    if first_rank not in ranks or second_rank not in ranks or first_rank == second_rank:
        return first_rank + second_rank if first_rank == second_rank else ""
    high, low = sorted((first_rank, second_rank), key=ranks.index)
    return f"{high}{low}{'s' if first[1] == second[1] else 'o'}"


def _position_for(seat: int, button: int, table_size: int) -> str:
    if table_size != 6:
        return "UNKNOWN"
    return ("BTN", "SB", "BB", "UTG", "HJ", "CO")[(seat - button) % table_size]


def _action_prefix(observation: "ObservationV1", big_blind: int) -> str | None:
    actions = tuple(action for action in observation.public_actions if action.street.value == "preflop")
    raises = tuple(action for action in actions if action.action.value == "raise")
    calls = tuple(action for action in actions if action.action.value == "call")
    if not raises and not calls:
        return "rfi"
    if len(raises) == 1 and not calls and raises[0].amount == int(2.5 * big_blind):
        return "vs_single_rfi"
    return None


def _coverage_miss(observation: "ObservationV1", context: PreflopPolicyContext, coverage: Mapping[str, Any]) -> str | None:
    if observation.table_size != coverage["players"] or len(observation.active_seats) < 2:
        return "multiway_or_table_size"
    if observation.street.value != coverage["street"]:
        return "street"
    if context.effective_stack_bb != coverage["effectiveStackBb"]:
        return "non_100bb"
    expected_stack = context.big_blind * context.effective_stack_bb
    if any(
        observation.stacks[seat] + observation.street_commitments[seat] != expected_stack
        for seat in (*observation.active_seats, *observation.folded_seats)
    ):
        return "non_100bb"
    if context.rake_bps != coverage["rakeBps"]:
        return "rake"
    if context.ante_bb != coverage["anteBb"]:
        return "ante"
    if context.tree_fingerprint != coverage["treeVersion"]:
        return "unknown_tree"
    if context.big_blind <= 0:
        return "invalid_blind"
    return None


def policy_miss_reason(observation: "ObservationV1", context: PreflopPolicyContext, artifact: PolicyArtifact) -> str:
    return _coverage_miss(observation, context, artifact.coverage) or "tree_or_position_not_covered"


def _validate_shape(payload: Mapping[str, Any]) -> None:
    required = {"schemaVersion", "artifactId", "artifactVersion", "source", "coverage", "generation", "nodes"}
    missing = required - payload.keys()
    if missing:
        raise PolicyArtifactError(f"policy artifact missing {sorted(missing)}")
    source = payload["source"]
    if source.get("evidenceGrade") != "B" or source.get("license") != "Riverline-first-party":
        raise PolicyArtifactError("policy artifact must be a Riverline-first-party B-grade source")
    for key in ("sourceKind", "provenance", "releaseDecision", "verificationStatus"):
        if not source.get(key):
            raise PolicyArtifactError(f"B-grade artifact source.{key} is required")
    generation = payload["generation"]
    for key in ("generator", "command", "configuration", "patchState"):
        if key not in generation or generation[key] in (None, ""):
            raise PolicyArtifactError(f"B-grade artifact generation.{key} is required")


def _validate_nodes(payload: Mapping[str, Any]) -> None:
    expected_classes = {hand_class: combos for hand_class, combos, _ordinal in _hand_classes()}
    for node in payload["nodes"]:
        entries = node.get("classFrequencies", [])
        if len(entries) != 169:
            raise PolicyArtifactError("each policy node must trace 1326 combos to 169 hand classes")
        classes = [item.get("handClass") for item in entries]
        if set(classes) != set(expected_classes) or len(classes) != len(set(classes)):
            raise PolicyArtifactError("policy node must contain exactly canonical 169 hand classes")
        if any(item.get("comboCount") != expected_classes[item["handClass"]] for item in entries):
            raise PolicyArtifactError("policy node has an invalid canonical combo count")
        if sum(item.get("comboCount", 0) for item in entries) != 1326:
            raise PolicyArtifactError("each policy node must trace 1326 combos to 169 hand classes")
        allowed = {"raise_to", "fold"} if node.get("actionPrefix") == "rfi" else {"raise_to", "call", "fold"}
        sizing = node.get("legalSizing", {}).get("raise_to", {})
        if sizing.get("semantics") != "to" or not isinstance(sizing.get("amountBb"), (int, float)) or sizing["amountBb"] <= 0:
            raise PolicyArtifactError("policy node has illegal raise sizing")
        for item in entries:
            frequencies = item.get("frequencies", {})
            total = sum(float(value) for value in frequencies.values())
            if set(frequencies) != allowed or not frequencies or any(not isinstance(value, (int, float)) or float(value) < 0 for value in frequencies.values()) or abs(total - 1.0) > 1e-9:
                raise PolicyArtifactError("policy action frequencies must be non-negative and normalized")


def _without_integrity(payload: Mapping[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(payload))
    copy.pop("integrity", None)
    return copy


def _digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _fingerprint(payload: Mapping[str, Any]) -> str:
    identity = {
        "schemaVersion": payload["schemaVersion"],
        "artifactId": payload["artifactId"],
        "artifactVersion": payload["artifactVersion"],
        "coverage": payload["coverage"],
        "nodes": payload["nodes"],
    }
    return "sha256:" + hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
