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
    PolicySequenceMismatchError,
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
from .providers.preflop import PREFLOP_POLICY_VERSION, PreflopPolicyProvider
from .providers.solver import SolverPolicyAdapter
from .seat_priors import (
    SeatPriorCoverageV1,
    SeatPriorProvider,
    SeatPriorProvenanceV1,
    SeatPriorQueryV1,
    SeatPriorResultV1,
    SeatPriorUnavailableReason,
    default_seat_prior_provider,
)
from .event_beliefs import PublicEventBeliefConsumer, SeatBeliefProvenanceV1, SeatBeliefResultV1, SeatBeliefUnavailableReason
from .policy_artifact import PolicyArtifactRangeAdapter, default_policy_artifact_range_adapter
from .trace import RangeBeliefTrace, board_at_sequence, build_range_trace, dead_cards_for_belief
from .update import apply_dead_cards, snapshot_from_range, update_range_belief
from .views import RangeBeliefComboView, RangeBeliefView, build_belief_view

__all__ = [
    "ActionMatch",
    "ActionMatchStatus",
    "ActionPolicyProvider",
    "FixturePolicyProvider",
    "InvalidPolicyError",
    "NoPolicyError",
    "PolicySequenceMismatchError",
    "NoPriorRangeError",
    "PolicyActionSpec",
    "PolicyArtifactRangeAdapter",
    "PolicyResult",
    "PolicySource",
    "PREFLOP_POLICY_VERSION",
    "PreflopPolicyProvider",
    "RangeBeliefCombo",
    "RangeBeliefComboView",
    "RangeBeliefError",
    "RangeBeliefSnapshot",
    "RangeBeliefTrace",
    "RangeBeliefView",
    "RangeUpdateMetadata",
    "PublicEventBeliefConsumer",
    "SeatPriorCoverageV1",
    "SeatPriorProvider",
    "SeatPriorProvenanceV1",
    "SeatPriorQueryV1",
    "SeatPriorResultV1",
    "SeatPriorUnavailableReason",
    "SeatBeliefProvenanceV1",
    "SeatBeliefResultV1",
    "SeatBeliefUnavailableReason",
    "SolverPolicyAdapter",
    "UnsupportedActionError",
    "ZeroProbabilityActionError",
    "aggregate_belief_to_matrix169",
    "apply_dead_cards",
    "build_belief_view",
    "build_range_trace",
    "board_at_sequence",
    "dead_cards_for_belief",
    "default_seat_prior_provider",
    "default_policy_artifact_range_adapter",
    "cards_from_key",
    "combo_key",
    "match_observed_action",
    "parse_policy_action",
    "resolve_action_match",
    "snapshot_from_range",
    "snapshot_id_for",
    "update_range_belief",
]
