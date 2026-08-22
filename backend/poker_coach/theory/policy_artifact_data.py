"""First-party source data for the deliberately bounded R9 preflop artifact.

This is a transparent training blueprint, not an imported chart or a GTO
claim.  It materializes every one of the 169 canonical starting-hand classes
and records the class-to-combo multiplicity (6 pairs, 4 suited, 12 offsuit),
so consumers can trace the complete 1,326-combo universe back to its class.
"""

from __future__ import annotations

from typing import Any


RANKS = "AKQJT98765432"
ARTIFACT_VERSION = "r9-02.preflop-6max-100bb-norake.v1"
TREE_VERSION = "r9-02.preflop-open-2.5bb-3bet-9bb.v1"


def build_preflop_payload() -> dict[str, Any]:
    """Return the canonical, JSON-serializable first-party artifact payload."""
    classes = tuple(_hand_classes())
    return {
        "schemaVersion": 1,
        "artifactId": "riverline-preflop-6max-100bb-no-rake",
        "artifactVersion": ARTIFACT_VERSION,
        "source": {
            "sourceKind": "policy-artifact",
            "evidenceGrade": "B",
            "license": "Riverline-first-party",
            "provenance": "Riverline-authored transparent training blueprint; no imported chart, screenshot, or third-party strategy data.",
        },
        "coverage": {
            "players": 6,
            "street": "preflop",
            "effectiveStackBb": 100,
            "rakeBps": 0,
            "anteBb": 0,
            "treeVersion": TREE_VERSION,
            "supportedActionPrefixes": ["rfi", "vs_single_rfi"],
            "excluded": ["multiway", "limps", "3bet_or_later", "non_100bb", "rake", "ante", "unknown_tree"],
        },
        "generation": {
            "generator": "poker_coach.theory.policy_artifact_data.build_preflop_payload",
            "configuration": {
                "rfiSizingBb": 2.5,
                "threeBetSizingBb": 9.0,
                "classUniverse": 169,
                "comboUniverse": 1326,
                "method": "first-party transparent hand-class buckets; B-grade approximate training policy",
            },
        },
        "nodes": [
            _rfi_node(position, classes)
            for position in ("UTG", "HJ", "CO", "BTN", "SB")
        ]
        + [
            _vs_rfi_node(position, classes)
            for position in ("HJ", "CO", "BTN", "SB", "BB")
        ],
    }


def _hand_classes() -> list[tuple[str, int, int]]:
    entries: list[tuple[str, int, int]] = []
    for high_index, high in enumerate(RANKS):
        for low_index in range(high_index, len(RANKS)):
            low = RANKS[low_index]
            if high == low:
                entries.append((f"{high}{low}", 6, 31 - high_index * 2))
            else:
                # Same ordinal is used for transparent buckets only; it is not equity.
                ordinal = 30 - high_index - low_index
                entries.append((f"{high}{low}s", 4, ordinal + 1))
                entries.append((f"{high}{low}o", 12, ordinal))
    assert len(entries) == 169
    assert sum(combo_count for _, combo_count, _ in entries) == 1326
    return entries


def _rfi_node(position: str, classes: tuple[tuple[str, int, int], ...]) -> dict[str, Any]:
    return {
        "nodeId": f"6max-100bb-norake/{position.lower()}-rfi-2.5bb",
        "actionPrefix": "rfi",
        "actorPosition": position,
        "treeFingerprint": TREE_VERSION,
        "legalSizing": {"raise_to": {"amountBb": 2.5, "semantics": "to"}},
        "classFrequencies": [
            _class_entry(hand_class, combos, _rfi_frequencies(ordinal, position))
            for hand_class, combos, ordinal in classes
        ],
    }


def _vs_rfi_node(position: str, classes: tuple[tuple[str, int, int], ...]) -> dict[str, Any]:
    return {
        "nodeId": f"6max-100bb-norake/{position.lower()}-vs-single-rfi-2.5bb",
        "actionPrefix": "vs_single_rfi",
        "actorPosition": position,
        "treeFingerprint": TREE_VERSION,
        "legalSizing": {"raise_to": {"amountBb": 9.0, "semantics": "to"}},
        "classFrequencies": [
            _class_entry(hand_class, combos, _vs_rfi_frequencies(ordinal, position))
            for hand_class, combos, ordinal in classes
        ],
    }


def _class_entry(hand_class: str, combos: int, frequencies: dict[str, float]) -> dict[str, Any]:
    return {"handClass": hand_class, "comboCount": combos, "frequencies": frequencies}


def _rfi_frequencies(ordinal: int, position: str) -> dict[str, float]:
    threshold = {"UTG": 21, "HJ": 19, "CO": 17, "BTN": 14, "SB": 16}[position]
    if ordinal >= threshold + 6:
        return {"raise_to": 1.0, "fold": 0.0}
    if ordinal >= threshold:
        return {"raise_to": 0.55, "fold": 0.45}
    return {"raise_to": 0.0, "fold": 1.0}


def _vs_rfi_frequencies(ordinal: int, position: str) -> dict[str, float]:
    shift = {"HJ": 3, "CO": 2, "BTN": 0, "SB": 1, "BB": -1}[position]
    if ordinal >= 27 + shift:
        return {"raise_to": 0.7, "call": 0.3, "fold": 0.0}
    if ordinal >= 22 + shift:
        return {"raise_to": 0.3, "call": 0.4, "fold": 0.3}
    if ordinal >= 17 + shift:
        return {"raise_to": 0.0, "call": 0.55, "fold": 0.45}
    return {"raise_to": 0.0, "call": 0.0, "fold": 1.0}
