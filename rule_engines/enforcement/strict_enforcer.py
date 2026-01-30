"""Strict enforcement handler - automatic blocking."""
import logging
from typing import Optional

from rules_emerging_pattern.models.rule import Rule
from rules_emerging_pattern.models.validation import Violation, ActionTaken

logger = logging.getLogger(__name__)


class StrictEnforcer:
    """Strict enforcement with automatic blocking."""
    
    def __init__(self):
        self.enforcement_count = 0
        self.block_count = 0
    
    def enforce(self, rule: Rule, content: str) -> Optional[Violation]:
        """Enforce rule with strict blocking."""
        self.enforcement_count += 1
        
        # Check patterns
        for pattern in rule.patterns:
            if pattern.keywords:
                content_lower = content.lower()
                for keyword in pattern.keywords:
                    if keyword.lower() in content_lower:
                        from rules_emerging_pattern.models.rule import RuleTier
                        from rules_emerging_pattern.models.validation import ViolationType
                        from rules_emerging_pattern.models.rule import RuleSeverity
                        
                        violation = Violation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            rule_tier=rule.tier,
                            rule_severity=RuleSeverity.CRITICAL,
                            violation_type=ViolationType.KEYWORD_MATCH,
                            matched_content=keyword,
                            matched_patterns=[keyword],
                            confidence_score=0.95,
                            action_taken=ActionTaken.BLOCK,
                            blocked=True,
                            user_override_allowed=False,
                            explanation=f"Strict enforcement: {rule.description}"
                        )
                        
                        self.block_count += 1
                        logger.warning(f"Strict enforcement blocked content for rule: {rule.id}")
                        return violation
        
        return None
    
    def get_stats(self) -> dict:
        """Get enforcement statistics."""
        return {
            "total_enforcements": self.enforcement_count,
            "blocks_applied": self.block_count,
            "block_rate": self.block_count / max(self.enforcement_count, 1) * 100
        }
