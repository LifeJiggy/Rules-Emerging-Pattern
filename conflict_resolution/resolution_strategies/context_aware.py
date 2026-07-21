"""Context-aware conflict resolution based on domain, role, content type, and audience."""
import logging
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextFactor(str, Enum):
    USER_ROLE = "user_role"
    DOMAIN = "domain"
    CONTENT_TYPE = "content_type"
    AUDIENCE = "audience"
    LOCALE = "locale"
    PLATFORM = "platform"
    INTENT = "intent"


@dataclass
class ContextualResolution:
    winning_rule_id: str
    losing_rule_id: str
    context_factors: Dict[str, Any]
    reason: str
    score_winner: float = 0.0
    score_loser: float = 0.0
    matched_factors: List[str] = field(default_factory=list)
    resolved_at: datetime = field(default_factory=datetime.utcnow)


DEFAULT_CONTEXT_WEIGHTS: Dict[str, float] = {
    "user_role": 10.0,
    "domain": 8.0,
    "content_type": 6.0,
    "audience": 5.0,
    "locale": 4.0,
    "platform": 3.0,
    "intent": 9.0,
}


class ContextAwareResolver:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.context_weights: Dict[str, float] = dict(
            DEFAULT_CONTEXT_WEIGHTS,
            **self.config.get("context_weights", {})
        )
        self._match_exact = self.config.get("match_exact", True)
        self._min_score_ratio = self.config.get("min_score_ratio", 0.1)
        logger.info("ContextAwareResolver initialized (factors=%s)", list(self.context_weights.keys()))

    def resolve(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ContextualResolution:
        score_1, matches_1 = self._calculate_context_score(rule_1, context)
        score_2, matches_2 = self._calculate_context_score(rule_2, context)

        if score_1 > score_2:
            return ContextualResolution(
                winning_rule_id=rule_1.get("id", "unknown"),
                losing_rule_id=rule_2.get("id", "unknown"),
                context_factors=context,
                reason=f"Better context match (score={score_1:.1f} vs {score_2:.1f})",
                score_winner=score_1,
                score_loser=score_2,
                matched_factors=matches_1,
            )
        elif score_2 > score_1:
            return ContextualResolution(
                winning_rule_id=rule_2.get("id", "unknown"),
                losing_rule_id=rule_1.get("id", "unknown"),
                context_factors=context,
                reason=f"Better context match (score={score_2:.1f} vs {score_1:.1f})",
                score_winner=score_2,
                score_loser=score_1,
                matched_factors=matches_2,
            )
        else:
            return ContextualResolution(
                winning_rule_id=rule_1.get("id", "unknown"),
                losing_rule_id=rule_2.get("id", "unknown"),
                context_factors=context,
                reason=f"Equal context scores ({score_1:.1f}), defaulting to rule_1",
                score_winner=score_1,
                score_loser=score_2,
                matched_factors=matches_1,
            )

    def resolve_multi(
        self,
        rules: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> ContextualResolution:
        if len(rules) == 1:
            score, matches = self._calculate_context_score(rules[0], context)
            return ContextualResolution(
                winning_rule_id=rules[0].get("id", "unknown"),
                losing_rule_id="",
                context_factors=context,
                reason="Single rule, no conflict",
                score_winner=score,
                matched_factors=matches,
            )

        best_rule = rules[0]
        best_score, best_matches = self._calculate_context_score(best_rule, context)
        runner_up_score = 0.0

        for rule in rules[1:]:
            score, matches = self._calculate_context_score(rule, context)
            if score > best_score:
                runner_up_score = best_score
                best_rule, best_score, best_matches = rule, score, matches
            elif score > runner_up_score:
                runner_up_score = score

        return ContextualResolution(
            winning_rule_id=best_rule.get("id", "unknown"),
            losing_rule_id="multiple",
            context_factors=context,
            reason=f"Best contextual match across {len(rules)} rules",
            score_winner=best_score,
            score_loser=runner_up_score,
            matched_factors=best_matches,
        )

    def _calculate_context_score(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> tuple[float, List[str]]:
        score = 0.0
        matched_factors: List[str] = []
        tags: List[str] = rule.get("tags", []) or []
        domains: List[str] = rule.get("domains", []) or []
        search_space: Set[str] = set(tags + domains + [str(v) for v in rule.values()])

        for factor, weight in self.context_weights.items():
            context_value = context.get(factor)
            if context_value is None:
                continue

            context_str = str(context_value).lower()

            if self._match_exact:
                tag_key = f"{factor}:{context_str}"
                if tag_key in tags or context_str in domains or context_str in search_space:
                    score += weight
                    matched_factors.append(f"{factor}={context_str}")
            else:
                if context_str in search_space or any(
                    context_str in str(item).lower() for item in search_space
                ):
                    score += weight * 0.8
                    matched_factors.append(f"{factor}={context_str} (fuzzy)")

        if rule.get("context_relevance") is not None:
            score *= float(rule.get("context_relevance", 1.0))

        return score, matched_factors
