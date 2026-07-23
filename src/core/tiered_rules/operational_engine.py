"""Operational Rule Engine - Tier 2 enforcement with advisory handling."""
import logging
from typing import List
from datetime import datetime

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class OperationalRuleEngine:
    """Tier 2 Operational Rule Engine with advisory enforcement."""
    
    def __init__(self):
        self.tier = RuleTier.OPERATIONAL
        self.evaluation_count = 0
        self.warning_count = 0
        
    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        """Evaluate content against operational rules."""
        start_time = datetime.utcnow()
        
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=0.9,
            request_id=f"operational_{self.evaluation_count}",
            content_hash=str(hash(request.content))[:16]
        )
        
        operational_patterns = self._get_operational_patterns()
        content_lower = request.content.lower()
        
        for pattern_data in operational_patterns:
            pattern = pattern_data['pattern']
            severity = pattern_data['severity']
            category = pattern_data['category']
            action = pattern_data['action']
            
            if pattern in content_lower:
                violation = Violation(
                    rule_id=f"operational_{category}",
                    rule_name=f"Operational Rule: {category}",
                    rule_tier=RuleTier.OPERATIONAL,
                    rule_severity=severity,
                    violation_type=ViolationType.COMPLIANCE_VIOLATION,
                    matched_content=pattern,
                    matched_patterns=[pattern],
                    confidence_score=0.85,
                    action_taken=action,
                    blocked=action == ActionTaken.BLOCK,
                    user_override_allowed=True,
                    explanation=f"Operational guideline: {category}",
                    context=request.context.get_effective_context() if request.context else {}
                )
                result.violations.append(violation)
                if action == ActionTaken.WARNING:
                    result.warnings.append(violation)
                if action == ActionTaken.BLOCK:
                    result.valid = False
                self.warning_count += 1
                logger.info(f"Operational issue detected: {category}")
                
        self.evaluation_count += 1
        result.processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.total_rules_evaluated = len(operational_patterns)
        result.rules_triggered = len(result.violations)
        
        return result
    
    def _get_operational_patterns(self) -> List[dict]:
        """Get operational patterns for detection."""
        return [
            {'pattern': 'copyright violation', 'severity': RuleSeverity.MEDIUM, 'category': 'copyright', 'action': ActionTaken.WARNING},
            {'pattern': 'personal information', 'severity': RuleSeverity.HIGH, 'category': 'pii', 'action': ActionTaken.BLOCK},
            {'pattern': 'inappropriate language', 'severity': RuleSeverity.LOW, 'category': 'language', 'action': ActionTaken.WARNING},
        ]
