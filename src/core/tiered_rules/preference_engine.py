"""Preference Rule Engine - Tier 3 enforcement with adaptive handling."""
import logging
from typing import List
from datetime import datetime

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest
from rules_emerging_pattern.models.validation import ValidationResult, Suggestion

logger = logging.getLogger(__name__)


class PreferenceRuleEngine:
    """Tier 3 Preference Rule Engine with adaptive enforcement."""
    
    def __init__(self):
        self.tier = RuleTier.PREFERENCE
        self.evaluation_count = 0
        self.suggestion_count = 0
        
    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        """Evaluate content against preference rules."""
        start_time = datetime.utcnow()
        
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=0.8,
            request_id=f"pref_{self.evaluation_count}",
            content_hash=str(hash(request.content))[:16]
        )
        
        preference_patterns = self._get_preference_patterns()
        content_lower = request.content.lower()
        
        for pattern_data in preference_patterns:
            pattern = pattern_data["pattern"]
            category = pattern_data["category"]
            suggestion_text = pattern_data["suggestion"]
            
            if pattern in content_lower:
                suggestion = Suggestion(
                    type="preference",
                    title=f"Preference: {category}",
                    description=suggestion_text,
                    confidence=0.75,
                    source_rule=f"preference_{category}",
                    auto_applicable=False,
                    user_approval_required=True
                )
                result.suggestions.append(suggestion)
                self.suggestion_count += 1
                logger.info(f"Preference suggestion: {category}")
                
        self.evaluation_count += 1
        result.processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.total_rules_evaluated = len(preference_patterns)
        
        return result
    
    def _get_preference_patterns(self) -> List[dict]:
        """Get preference patterns for suggestions."""
        return [
            {"pattern": "informal tone", "category": "tone", "suggestion": "Consider using a more professional tone"},
            {"pattern": "no formatting", "category": "formatting", "suggestion": "Add proper formatting for better readability"},
        ]
