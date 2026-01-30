"""Detect priority conflicts between rules."""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PriorityConflict:
    """Represents a priority conflict."""
    rule_1_id: str
    rule_2_id: str
    tier_1: str
    tier_2: str
    description: str


class PriorityConflictDetector:
    """Detect conflicts between rule priorities."""
    
    def __init__(self):
        self.tier_hierarchy = {
            "safety": 1,
            "operational": 2,
            "preference": 3
        }
        logger.info("PriorityConflictDetector initialized")
    
    def detect_priority_conflict(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[PriorityConflict]:
        """Detect priority conflicts between two rules."""
        tier_1 = rule_1.get("tier", "preference")
        tier_2 = rule_2.get("tier", "preference")
        
        # If same tier but different priorities
        if tier_1 == tier_2:
            priority_1 = rule_1.get("priority", 100)
            priority_2 = rule_2.get("priority", 100)
            
            if abs(priority_1 - priority_2) > 50:
                return PriorityConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    tier_1=tier_1,
                    tier_2=tier_2,
                    description=f"Large priority gap: {priority_1} vs {priority_2}"
                )
        
        return None
    
    def get_tier_priority(self, tier: str) -> int:
        """Get numeric priority for a tier."""
        return self.tier_hierarchy.get(tier, 999)
