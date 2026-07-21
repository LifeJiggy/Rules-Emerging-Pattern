"""Priority-based conflict resolution using tier hierarchy and rule priority scoring."""
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class PriorityResolutionOutcome(str, Enum):
    TIER_WIN = "tier_win"
    PRIORITY_WIN = "priority_win"
    COMPOSITE_WIN = "composite_win"
    UNDETERMINED = "undetermined"


@dataclass
class ResolutionResult:
    winning_rule_id: str
    losing_rule_id: str
    strategy: str
    reason: str
    outcome: PriorityResolutionOutcome = PriorityResolutionOutcome.PRIORITY_WIN
    score_winner: float = 0.0
    score_loser: float = 0.0
    resolved_at: datetime = field(default_factory=datetime.utcnow)


class PriorityBasedResolver:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.tier_weights: Dict[str, int] = {
            "safety": 1000,
            "operational": 500,
            "preference": 100
        }
        self._default_priority = self.config.get("default_priority", 100)
        self._max_priority = self.config.get("max_priority", 1000)
        logger.info("PriorityBasedResolver initialized (weights=%s)", self.tier_weights)

    def resolve(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> ResolutionResult:
        tier_1 = rule_1.get("tier", "preference")
        tier_2 = rule_2.get("tier", "preference")
        priority_1 = int(rule_1.get("priority", self._default_priority))
        priority_2 = int(rule_2.get("priority", self._default_priority))

        weight_1 = self.tier_weights.get(tier_1, 0)
        weight_2 = self.tier_weights.get(tier_2, 0)

        inverted_1 = max(0, self._max_priority - priority_1)
        inverted_2 = max(0, self._max_priority - priority_2)

        score_1 = weight_1 + inverted_1
        score_2 = weight_2 + inverted_2

        if score_1 > score_2:
            outcome_type = (
                PriorityResolutionOutcome.TIER_WIN
                if weight_1 > weight_2
                else PriorityResolutionOutcome.COMPOSITE_WIN
                if abs(weight_1 - weight_2) < 300
                else PriorityResolutionOutcome.PRIORITY_WIN
            )
            return ResolutionResult(
                winning_rule_id=rule_1.get("id", "unknown"),
                losing_rule_id=rule_2.get("id", "unknown"),
                strategy="priority_based",
                reason=f"Higher composite score: {tier_1}(w={weight_1},p={priority_1})={score_1} "
                       f"> {tier_2}(w={weight_2},p={priority_2})={score_2}",
                outcome=outcome_type,
                score_winner=score_1,
                score_loser=score_2
            )
        elif score_2 > score_1:
            outcome_type = (
                PriorityResolutionOutcome.TIER_WIN
                if weight_2 > weight_1
                else PriorityResolutionOutcome.COMPOSITE_WIN
                if abs(weight_2 - weight_1) < 300
                else PriorityResolutionOutcome.PRIORITY_WIN
            )
            return ResolutionResult(
                winning_rule_id=rule_2.get("id", "unknown"),
                losing_rule_id=rule_1.get("id", "unknown"),
                strategy="priority_based",
                reason=f"Higher composite score: {tier_2}(w={weight_2},p={priority_2})={score_2} "
                       f"> {tier_1}(w={weight_1},p={priority_1})={score_1}",
                outcome=outcome_type,
                score_winner=score_2,
                score_loser=score_1
            )
        else:
            return ResolutionResult(
                winning_rule_id=rule_1.get("id", "unknown"),
                losing_rule_id=rule_2.get("id", "unknown"),
                strategy="priority_based",
                reason=f"Equal scores ({score_1}), defaulting to rule_1",
                outcome=PriorityResolutionOutcome.UNDETERMINED,
                score_winner=score_1,
                score_loser=score_2
            )

    def resolve_chain(
        self,
        rules: List[Dict[str, Any]]
    ) -> Tuple[Optional[ResolutionResult], List[ResolutionResult]]:
        if len(rules) < 2:
            return None, []

        sorted_rules = sorted(
            rules,
            key=lambda r: (
                -self.tier_weights.get(r.get("tier", "preference"), 0),
                -int(r.get("priority", self._default_priority))
            )
        )

        chain_results: List[ResolutionResult] = []
        winner = sorted_rules[0]

        for contender in sorted_rules[1:]:
            result = self.resolve(winner, contender)
            chain_results.append(result)
            if result.winning_rule_id != winner.get("id"):
                winner = contender

        final_result = ResolutionResult(
            winning_rule_id=winner.get("id", "unknown"),
            losing_rule_id=sorted_rules[-1].get("id", "unknown"),
            strategy="priority_chain",
            reason=f"Chain winner after {len(chain_results)} rounds",
            outcome=PriorityResolutionOutcome.COMPOSITE_WIN,
            score_winner=self._composite_score(winner),
            score_loser=self._composite_score(sorted_rules[-1])
        )

        return final_result, chain_results

    def resolve_batch(
        self,
        conflict_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]]
    ) -> List[ResolutionResult]:
        return [self.resolve(r1, r2) for r1, r2 in conflict_pairs]

    def _composite_score(self, rule: Dict[str, Any]) -> float:
        tier = rule.get("tier", "preference")
        priority = int(rule.get("priority", self._default_priority))
        weight = self.tier_weights.get(tier, 0)
        inverted = max(0, self._max_priority - priority)
        return float(weight + inverted)
