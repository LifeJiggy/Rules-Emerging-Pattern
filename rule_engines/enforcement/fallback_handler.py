"""Fallback handler for rule enforcement failures."""
import logging
from typing import Optional

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleSeverity
from rules_emerging_pattern.models.validation import Violation, ActionTaken, ViolationType

logger = logging.getLogger(__name__)


class FallbackHandler:
    """Handle enforcement failures gracefully."""
    
    def __init__(self):
        self.fallback_count = 0
    
    def handle_failure(self, rule: Rule, content: str, error: str) -> Optional[Violation]:
        """Handle rule enforcement failure."""
        self.fallback_count += 1
        
        logger.error(f"Rule enforcement failed for {rule.id}: {error}")
        
        if rule.tier == RuleTier.SAFETY:
            violation = Violation(
                rule_id=f"fallback_{rule.id}",
                rule_name=f"Fallback: {rule.name}",
                rule_tier=rule.tier,
                rule_severity=RuleSeverity.HIGH,
                violation_type=ViolationType.CUSTOM_VIOLATION,
                matched_content="",
                matched_patterns=[],
                confidence_score=0.5,
                action_taken=ActionTaken.WARNING,
                blocked=False,
                user_override_allowed=True,
                explanation=f"Rule enforcement failed. Error: {error}"
            )
            return violation
        
        return None
    
    def get_stats(self) -> dict:
        """Get fallback statistics."""
        return {
            "total_fallbacks": self.fallback_count
        }
