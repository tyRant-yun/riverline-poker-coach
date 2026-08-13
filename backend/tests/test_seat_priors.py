from decimal import Decimal

import pytest

from poker_coach.domain.models import SeatPosition
from poker_coach.ranges.seat_priors import (
    SeatPriorQueryV1,
    SeatPriorUnavailableReason,
    default_seat_prior_provider,
)


def _query(**overrides: object) -> SeatPriorQueryV1:
    values: dict[str, object] = {
        "table_size": 6,
        "active_seat_ids": (0, 1, 2, 3, 4, 5),
        "button_seat": 0,
        "small_blind": 50,
        "big_blind": 100,
        "starting_stacks": {seat: 10_000 for seat in range(6)},
    }
    values.update(overrides)
    return SeatPriorQueryV1(**values)


def test_six_max_unopened_prior_covers_every_position_and_is_normalized():
    provider = default_seat_prior_provider()
    query = _query()

    expected = (
        SeatPosition.BUTTON,
        SeatPosition.SMALL_BLIND,
        SeatPosition.BIG_BLIND,
        SeatPosition.UTG,
        SeatPosition.MP,
        SeatPosition.CUTOFF,
    )
    for seat_id, position in enumerate(expected):
        result = provider.get_prior(query, seat_id)
        assert result.available is True
        assert result.position is position
        assert result.snapshot is not None
        assert len(result.snapshot.combos) == 1326
        assert abs(sum(combo.probability for combo in result.snapshot.combos.values()) - Decimal("1")) < Decimal("1e-24")
        assert result.provenance is not None
        assert result.provenance.provider == "riverline.position_stack_heuristic"
        assert result.provenance.version == "heuristic_seed_v2"
        assert result.provenance.trust_level == "heuristic"


def test_button_rotation_and_sparse_stable_seats_never_dense_renumber():
    provider = default_seat_prior_provider()
    query = _query(active_seat_ids=(0, 2, 3, 5, 6, 7), button_seat=5, table_size=8,
                   starting_stacks={seat: 10_000 for seat in (0, 2, 3, 5, 6, 7)})

    result = provider.get_prior(query, 2)
    assert result.available is False
    assert result.unavailable_reason is SeatPriorUnavailableReason.TABLE_SIZE_UNSUPPORTED

    sparse_six = _query(active_seat_ids=(0, 2, 3, 5, 6, 7), button_seat=5, table_size=6,
                        starting_stacks={seat: 10_000 for seat in (0, 2, 3, 5, 6, 7)})
    assert provider.get_prior(sparse_six, 5).position is SeatPosition.BUTTON
    assert provider.get_prior(sparse_six, 6).position is SeatPosition.SMALL_BLIND
    assert provider.get_prior(sparse_six, 7).position is SeatPosition.BIG_BLIND
    assert provider.get_prior(sparse_six, 0).position is SeatPosition.UTG
    assert provider.get_prior(sparse_six, 2).position is SeatPosition.MP
    assert provider.get_prior(sparse_six, 3).position is SeatPosition.CUTOFF


@pytest.mark.parametrize("active", ((0, 1), (0, 1, 2), (0, 1, 2, 3), (0, 1, 2, 3, 4)))
def test_short_handed_tables_are_structured_unavailable(active: tuple[int, ...]):
    query = _query(table_size=len(active), active_seat_ids=active, button_seat=active[0],
                   starting_stacks={seat: 10_000 for seat in active})
    result = default_seat_prior_provider().get_prior(query, active[0])
    assert result.available is False
    assert result.unavailable_reason is SeatPriorUnavailableReason.TABLE_SIZE_UNSUPPORTED


def test_blockers_filter_and_normalize_without_exposing_them_in_provenance():
    result = default_seat_prior_provider().get_prior(_query(visible_blockers=("As", "Kd")), 1)
    assert result.available is True
    assert result.snapshot is not None
    assert len(result.snapshot.combos) == 1225
    assert all("As" not in key and "Kd" not in key for key in result.snapshot.combos)
    assert sum(combo.probability for combo in result.snapshot.combos.values()) == Decimal("1")
    assert "As" not in result.provenance.to_json()  # type: ignore[union-attr]


def test_deterministic_fingerprint_and_no_private_or_future_input_surface():
    provider = default_seat_prior_provider()
    first = provider.get_prior(_query(), 4)
    second = provider.get_prior(_query(), 4)
    assert first.to_json() == second.to_json()
    assert first.provenance.artifact_fingerprint == second.provenance.artifact_fingerprint  # type: ignore[union-attr]
    assert set(SeatPriorQueryV1.model_fields) == {
        "table_size", "active_seat_ids", "button_seat", "small_blind", "big_blind",
        "starting_stacks", "ante", "rake_bps", "street", "after_sequence", "visible_blockers",
    }


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"ante": 1}, SeatPriorUnavailableReason.ANTE_UNSUPPORTED),
        ({"rake_bps": 1}, SeatPriorUnavailableReason.RAKE_UNSUPPORTED),
        ({"starting_stacks": {seat: 5_000 for seat in range(6)}}, None),
        ({"after_sequence": 1}, SeatPriorUnavailableReason.NODE_UNSUPPORTED),
    ],
)
def test_coverage_boundary_is_structured_and_explicit(overrides: dict[str, object], reason: SeatPriorUnavailableReason | None):
    result = default_seat_prior_provider().get_prior(_query(**overrides), 0)
    if reason is None:
        assert result.available is True
        assert result.unavailable_reason is None
        assert result.snapshot is not None
        assert result.coverage.effective_stack_bucket == "40bb"
        assert result.coverage.approximate is True
        assert result.coverage.approximation_reason == "nearest_stack_bucket:40bb"
        return
    assert result.available is False
    assert result.unavailable_reason is reason
    assert result.snapshot is None
