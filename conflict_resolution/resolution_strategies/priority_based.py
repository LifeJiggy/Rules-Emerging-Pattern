"""Priority-based conflict resolution."""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Result of conflict resolution."""
    winning_rule_id: str
    losing_rule_id: str
    strategy: str
    reason: str


class PriorityBasedResolver:
    """Resolve conflicts based on rule priority and tier."""
    
    def __init__(self):
        self.tier_weights = {
            "safety": 1000,
            "operational": 500,
            "preference": 100
        }
        logger.info("PriorityBasedResolver initialized")
    
    def resolve(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> ResolutionResult:
        """Resolve conflict between two rules based on priority."""
        tier_1 = rule_1.get("tier", "preference")
        tier_2 = rule_2.get("tier", "preference")
        
        weight_1 = self.tier_weights.get(tier_1, 0)
        weight_2 = self.tier_weights.get(tier_2, 0)
        
        # Add individual rule priorities
        priority_1 = rule_1.get("priority", 100)
        priority_2 = rule_2.get("priority", 100)
        
        score_1 = weight_1 + (1000 - priority_1)
        score_2 = weight_2 + (1000 - priority_2)
        
        if score_1 > score_2:
            return ResolutionResult(
                winning_rule_id=rule_1.get("id", "unknown"),
                losing_rule_id=rule_2.get("id", "unknown"),
                strategy="priority_based",
                reason=f"Higher priority: {tier_1} tier with priority {priority_1}"
            )
        else:
            return ResolutionResult(
                winning_rule_id=rule_2.get("id", "unknown"),
                losing_rule_id=rule_1.get("id", "unknown"),
                strategy="priority_based",
                reason=f"Higher priority: {tier_2} tier with priority {priority_2}"
            )
