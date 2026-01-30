"""Advisory enforcement handler - warnings with user override."""
import logging
from typing import Optional

from rules_emerging_pattern.models.rule import Rule
from rules_emerging_pattern.models.validation import Violation, ActionTaken

logger = logging.getLogger(__name__)


class AdvisoryEnforcer:
    """Advisory enforcement with warnings and user override."""
    
    def __init__(self):
        self.enforcement_count = 0
        self.warning_count = 0
    
    def enforce(self, rule: Rule, content: str) -> Optional[Violation]:
        """Enforce rule with advisory warning."""
        self.enforcement_count += 1
        
        for pattern in rule.patterns:
            if pattern.keywords:
                content_lower = content.lower()
                for keyword in pattern.keywords:
                    if keyword.lower() in content_lower:
                        from rules_emerging_pattern.models.rule import RuleSeverity
                        from rules_emerging_pattern.models.validation import ViolationType
                        
                        violation = Violation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            rule_tier=rule.tier,
                            rule_severity=RuleSeverity.MEDIUM,
                            violation_type=ViolationType.KEYWORD_MATCH,
                            matched_content=keyword,
                            matched_patterns=[keyword],
                            confidence_score=0.8,
                            action_taken=ActionTaken.WARNING,
                            blocked=False,
                            user_override_allowed=True,
                            explanation=f"Advisory: {rule.description}. User can override."
                        )
                        
                        self.warning_count += 1
                        logger.info(f"Advisory warning for rule: {rule.id}")
                        return violation
        
        return None
    
    def get_stats(self) -> dict:
        """Get enforcement statistics."""
        return {
            "total_enforcements": self.enforcement_count,
            "warnings_issued": self.warning_count,
            "warning_rate": self.warning_count / max(self.enforcement_count, 1) * 100
        }
