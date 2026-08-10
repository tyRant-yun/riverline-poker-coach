"""Combo-level, action-conditioned range belief engine.

The 169 matrix is a derived view; the engine's state is concrete
two-card combos updated by policy likelihoods:

    newReach(h) = oldReach(h) * P(observedAction | h)
    belief(h)   = newReach(h) / sum(newReach)
"""

from .aggregation import aggregate_belief_to_matrix169
from .belief import (
    InvalidPolicyError,
    NoPolicyError,
    NoPriorRangeError,
    PolicySource,
    RangeBeliefCombo,
    RangeBeliefError,
    RangeBeliefSnapshot,
    RangeUpdateMetadata,
    UnsupportedActionError,
    ZeroProbabilityActionError,
    cards_from_key,
    combo_key,
    snapshot_id_for,
)
from .policy import (
    ActionMatch,
    ActionMatchStatus,
    ActionPolicyProvider,
    PolicyActionSpec,
    PolicyResult,
    match_observed_action,
    parse_policy_action,
    resolve_action_match,
)
from .providers.fixture import FixturePolicyProvider
from .providers.solver import SolverPolicyAdapter
from .trace import RangeBeliefTrace, build_range_trace
from .update import apply_dead_cards, snapshot_from_range, update_range_belief
from .views import RangeBeliefComboView, RangeBeliefView, build_belief_view

__all__ = [
    "ActionMatch",
    "ActionMatchStatus",
    "ActionPolicyProvider",
    "FixturePolicyProvider",
    "InvalidPolicyError",
    "NoPolicyError",
    "NoPriorRangeError",
    "PolicyActionSpec",
    "PolicyResult",
    "PolicySource",
    "RangeBeliefCombo",
    "RangeBeliefComboView",
    "RangeBeliefError",
    "RangeBeliefSnapshot",
    "RangeBeliefTrace",
    "RangeBeliefView",
    "RangeUpdateMetadata",
    "SolverPolicyAdapter",
    "UnsupportedActionError",
    "ZeroProbabilityActionError",
    "aggregate_belief_to_matrix169",
    "apply_dead_cards",
    "build_belief_view",
    "build_range_trace",
    "cards_from_key",
    "combo_key",
    "match_observed_action",
    "parse_policy_action",
    "resolve_action_match",
    "snapshot_from_range",
    "snapshot_id_for",
    "update_range_belief",
]
