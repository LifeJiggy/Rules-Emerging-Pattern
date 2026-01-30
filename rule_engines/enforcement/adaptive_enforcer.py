"""Adaptive enforcement handler - context-aware."""
import logging
from typing import Optional, Dict, Any

from rules_emerging_pattern.models.rule import Rule, RuleContext
from rules_emerging_pattern.models.validation import Violation, ActionTaken, Suggestion

logger = logging.getLogger(__name__)


class AdaptiveEnforcer:
    """Adaptive enforcement based on context."""
    
    def __init__(self):
        self.enforcement_count = 0
        self.suggestion_count = 0
    
    def enforce(self, rule: Rule, content: str, context: Optional[RuleContext] = None) -> Optional[Violation]:
        """Enforce rule with adaptive behavior based on context."""
        self.enforcement_count += 1
        
        # Adapt based on context
        if context:
            ctx = context.get_effective_context()
            user_role = ctx.get("user_role", "")
            
            # Skip for admin users
            if user_role == "admin":
                logger.debug(f"Skipping rule {rule.id} for admin user")
                return None
        
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
                            rule_severity=RuleSeverity.LOW,
                            violation_type=ViolationType.KEYWORD_MATCH,
                            matched_content=keyword,
                            matched_patterns=[keyword],
                            confidence_score=0.7,
                            action_taken=ActionTaken.SUGGESTION,
                            blocked=False,
                            user_override_allowed=True,
                            explanation=f"Suggestion: {rule.description}"
                        )
                        
                        self.suggestion_count += 1
                        logger.info(f"Adaptive suggestion for rule: {rule.id}")
                        return violation
        
        return None
    
    def get_stats(self) -> dict:
        """Get enforcement statistics."""
        return {
            "total_enforcements": self.enforcement_count,
            "suggestions_made": self.suggestion_count,
            "suggestion_rate": self.suggestion_count / max(self.enforcement_count, 1) * 100
        }
