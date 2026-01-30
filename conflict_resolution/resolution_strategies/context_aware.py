"""Context-aware conflict resolution."""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ContextualResolution:
    """Result of context-aware resolution."""
    winning_rule_id: str
    context_factors: Dict[str, Any]
    reason: str


class ContextAwareResolver:
    """Resolve conflicts based on context."""
    
    def __init__(self):
        self.context_weights = {
            "user_role": 10,
            "domain": 8,
            "content_type": 5
        }
        logger.info("ContextAwareResolver initialized")
    
    def resolve(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ContextualResolution:
        """Resolve conflict based on context applicability."""
        score_1 = self._calculate_context_score(rule_1, context)
        score_2 = self._calculate_context_score(rule_2, context)
        
        if score_1 > score_2:
            return ContextualResolution(
                winning_rule_id=rule_1.get("id", "unknown"),
                context_factors=context,
                reason="Better context match"
            )
        else:
            return ContextualResolution(
                winning_rule_id=rule_2.get("id", "unknown"),
                context_factors=context,
                reason="Better context match"
            )
    
    def _calculate_context_score(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> float:
        """Calculate how well a rule matches the context."""
        score = 0.0
        tags = rule.get("tags", [])
        
        for tag in tags:
            if tag.startswith("domain:"):
                domain = tag.split(":")[1]
                if context.get("domain") == domain:
                    score += self.context_weights["domain"]
            elif tag.startswith("role:"):
                role = tag.split(":")[1]
                if context.get("user_role") == role:
                    score += self.context_weights["user_role"]
        
        return score
