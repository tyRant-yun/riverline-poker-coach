"""First-party, versioned default preflop range catalog."""

from __future__ import annotations

from poker_coach.analysis.range_analysis import range_spec_from_notation
from poker_coach.domain.models import RangeSpec, RangeSource


DEFAULT_PREFLOP_VERSION = "preflop-100bb-0.1"


def default_preflop_ranges() -> dict[str, RangeSpec]:
    common = {
        "version": DEFAULT_PREFLOP_VERSION,
        "source": RangeSource.DEFAULT_PREFLOP,
    }
    return {
        "btn_open": range_spec_from_notation(
            "22+ A2s+ K7s+ Q8s+ J8s+ T8s+ 98s 87s 76s 65s ATo+ KTo+ QTo+ JTo+",
            range_id="default.btn_open.100bb",
            name="BTN open 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
        "bb_defend": range_spec_from_notation(
            "22+ A2s+ K2s+ Q4s+ J6s+ T6s+ 98s 87s 76s 65s 54s A2o+ K8o+ Q9o+ J9o+ T9o",
            range_id="default.bb_defend.100bb",
            name="BB defend vs BTN open 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
        "bb_3bet": range_spec_from_notation(
            "QQ+ AKs AKo A5s-A2s",
            range_id="default.bb_3bet.100bb",
            name="BB 3-bet vs BTN open 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
        "btn_vs_3bet": range_spec_from_notation(
            "QQ+ AQs+ AKo KQs A5s-A2s",
            range_id="default.btn_vs_3bet.100bb",
            name="BTN vs 3-bet 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
        "btn_4bet": range_spec_from_notation(
            "QQ+ AKs AKo A5s-A4s",
            range_id="default.btn_4bet.100bb",
            name="BTN 4-bet 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
        "bb_vs_4bet": range_spec_from_notation(
            "QQ+ AKs AKo",
            range_id="default.bb-vs-4bet.100bb",
            name="BB vs BTN 4-bet 100BB",
            **common,
        ).model_copy(update={"is_default_assumption": True}),
    }
