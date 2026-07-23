"""Safety Rule Engine - Tier 1 enforcement with automatic blocking."""
import logging
from typing import List
from datetime import datetime

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class SafetyRuleEngine:
    """Tier 1 Safety Rule Engine with strict enforcement."""
    
    def __init__(self):
        self.tier = RuleTier.SAFETY
        self.evaluation_count = 0
        self.block_count = 0
        
    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        """Evaluate content against safety rules with strict enforcement."""
        start_time = datetime.utcnow()
        
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=f"safety_{self.evaluation_count}",
            content_hash=str(hash(request.content))[:16]
        )
        
        safety_patterns = self._get_safety_patterns()
        content_lower = request.content.lower()
        
        for pattern_data in safety_patterns:
            pattern = pattern_data['pattern']
            severity = pattern_data['severity']
            category = pattern_data['category']
            
            if pattern in content_lower:
                violation = Violation(
                    rule_id=f"safety_{category}",
                    rule_name=f"Safety Rule: {category}",
                    rule_tier=RuleTier.SAFETY,
                    rule_severity=severity,
                    violation_type=ViolationType.KEYWORD_MATCH,
                    matched_content=pattern,
                    matched_patterns=[pattern],
                    confidence_score=0.95,
                    action_taken=ActionTaken.BLOCK,
                    blocked=True,
                    user_override_allowed=False,
                    explanation=f"Safety violation detected: {category}",
                    context=request.context.get_effective_context() if request.context else {}
                )
                result.violations.append(violation)
                result.critical_violations.append(violation)
                result.valid = False
                self.block_count += 1
                logger.warning(f"Safety violation blocked: {category}")
                
        self.evaluation_count += 1
        result.processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.total_rules_evaluated = len(safety_patterns)
        result.rules_triggered = len(result.violations)
        
        return result
    
    def _get_safety_patterns(self) -> List[dict]:
        """Get safety-critical patterns for detection."""
        return [
            {'pattern': 'child exploitation', 'severity': RuleSeverity.CRITICAL, 'category': 'child_safety'},
            {'pattern': 'how to make a bomb', 'severity': RuleSeverity.CRITICAL, 'category': 'dangerous_content'},
            {'pattern': 'create weapon', 'severity': RuleSeverity.HIGH, 'category': 'weapons'},
            {'pattern': 'malware code', 'severity': RuleSeverity.HIGH, 'category': 'malicious_code'},
        ]
