"""Adaptive rule adaptation engine."""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from rules_emerging_pattern.models.rule import Rule, RuleTier

logger = logging.getLogger(__name__)


class RuleAdaptationEngine:
    """Engine for adapting rules based on feedback and usage."""
    
    def __init__(self):
        self.adaptation_history: List[Dict[str, Any]] = []
        self.context_weights: Dict[str, float] = {}
        self.feedback_scores: Dict[str, List[float]] = {}
        
    def adapt_rule_threshold(self, rule: Rule, performance_data: Dict[str, Any]) -> Optional[Rule]:
        """Adapt a rule's threshold based on performance data."""
        if rule.tier == RuleTier.SAFETY:
            logger.info(f"Skipping adaptation for safety rule {rule.id}")
            return None
        
        false_positive_rate = performance_data.get("false_positive_rate", 0)
        false_negative_rate = performance_data.get("false_negative_rate", 0)
        
        # Adapt based on error rates
        if false_positive_rate > 0.2:
            # Too strict, relax slightly
            logger.info(f"Adapting rule {rule.id}: reducing strictness")
            return self._relax_rule(rule)
        elif false_negative_rate > 0.1:
            # Too lenient, tighten
            logger.info(f"Adapting rule {rule.id}: increasing strictness")
            return self._tighten_rule(rule)
        
        return None
    
    def _relax_rule(self, rule: Rule) -> Rule:
        """Make a rule less strict."""
        # Reduce pattern confidence thresholds
        for pattern in rule.patterns:
            pattern.confidence_threshold = max(0.5, pattern.confidence_threshold - 0.1)
        
        self.adaptation_history.append({
            "rule_id": rule.id,
            "action": "relax",
            "timestamp": datetime.utcnow()
        })
        
        return rule
    
    def _tighten_rule(self, rule: Rule) -> Rule:
        """Make a rule more strict."""
        # Increase pattern confidence thresholds
        for pattern in rule.patterns:
            pattern.confidence_threshold = min(0.95, pattern.confidence_threshold + 0.05)
        
        self.adaptation_history.append({
            "rule_id": rule.id,
            "action": "tighten",
            "timestamp": datetime.utcnow()
        })
        
        return rule
    
    def process_user_feedback(self, rule_id: str, feedback: str, rating: float) -> None:
        """Process user feedback for rule improvement."""
        if rule_id not in self.feedback_scores:
            self.feedback_scores[rule_id] = []
        
        self.feedback_scores[rule_id].append(rating)
        
        logger.info(f"Received feedback for rule {rule_id}: {rating}")
        
        # If consistently poor feedback, flag for review
        if len(self.feedback_scores[rule_id]) >= 10:
            avg_rating = sum(self.feedback_scores[rule_id]) / len(self.feedback_scores[rule_id])
            if avg_rating < 0.3:
                logger.warning(f"Rule {rule_id} has poor feedback average: {avg_rating}")
    
    def get_adaptation_history(self, rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get history of rule adaptations."""
        if rule_id:
            return [h for h in self.adaptation_history if h["rule_id"] == rule_id]
        return self.adaptation_history
