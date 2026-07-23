"""Quality validation for generated outputs."""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QualityMetrics:
    """Metrics for content quality assessment."""
    readability_score: float = 0.0
    coherence_score: float = 0.0
    relevance_score: float = 0.0
    completeness_score: float = 0.0


class QualityValidator:
    """Validates content quality based on various metrics."""
    
    def __init__(self, min_readability: float = 0.6, min_coherence: float = 0.7):
        self.min_readability = min_readability
        self.min_coherence = min_coherence
        self.quality_thresholds = {
            "readability": min_readability,
            "coherence": min_coherence,
            "relevance": 0.5,
            "completeness": 0.6
        }
        logger.info("QualityValidator initialized with thresholds: %s", self.quality_thresholds)
    
    def validate_quality(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate content quality and return assessment."""
        logger.debug("Validating quality for content length: %d", len(content))
        
        metrics = self._calculate_metrics(content, context)
        issues = self._identify_issues(metrics)
        passed = len(issues) == 0
        
        result = {
            "passed": passed,
            "metrics": metrics,
            "issues": issues,
            "recommendations": self._generate_recommendations(issues)
        }
        
        logger.info("Quality validation completed: passed=%s, issues=%d", passed, len(issues))
        return result
    
    def _calculate_metrics(self, content: str, context: Optional[Dict[str, Any]]) -> QualityMetrics:
        """Calculate quality metrics for content."""
        readability = self._calculate_readability(content)
        coherence = self._calculate_coherence(content)
        relevance = self._calculate_relevance(content, context)
        completeness = self._calculate_completeness(content)
        
        return QualityMetrics(
            readability_score=readability,
            coherence_score=coherence,
            relevance_score=relevance,
            completeness_score=completeness
        )
    
    def _calculate_readability(self, content: str) -> float:
        """Calculate readability score."""
        sentences = content.split('.')
        words = content.split()
        
        if len(sentences) == 0 or len(words) == 0:
            return 0.0
        
        avg_words_per_sentence = len(words) / len(sentences)
        score = max(0.0, min(1.0, 1.0 - (avg_words_per_sentence - 15) / 30))
        
        return round(score, 2)
    
    def _calculate_coherence(self, content: str) -> float:
        """Calculate coherence score based on flow and structure."""
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        if len(paragraphs) <= 1:
            return 0.8
        
        transitions = self._count_transitions(content)
        score = min(1.0, 0.5 + (transitions / len(paragraphs)) * 0.5)
        
        return round(score, 2)
    
    def _calculate_relevance(self, content: str, context: Optional[Dict[str, Any]]) -> float:
        """Calculate relevance to context."""
        if not context or "topic" not in context:
            return 0.7
        
        topic = context["topic"].lower()
        content_lower = content.lower()
        
        topic_words = topic.split()
        matches = sum(1 for word in topic_words if word in content_lower)
        
        score = matches / len(topic_words) if topic_words else 0.5
        return round(min(1.0, score), 2)
    
    def _calculate_completeness(self, content: str) -> float:
        """Calculate completeness score."""
        min_length = 100
        ideal_length = 500
        
        length = len(content)
        
        if length < min_length:
            return round(length / min_length, 2)
        
        score = min(1.0, 0.7 + (length - min_length) / (ideal_length * 3))
        return round(score, 2)
    
    def _count_transitions(self, content: str) -> int:
        """Count transition words in content."""
        transitions = [
            "however", "therefore", "furthermore", "moreover",
            "consequently", "meanwhile", "additionally", "similarly"
        ]
        content_lower = content.lower()
        return sum(1 for t in transitions if t in content_lower)
    
    def _identify_issues(self, metrics: QualityMetrics) -> List[str]:
        """Identify quality issues based on metrics."""
        issues = []
        
        if metrics.readability_score < self.quality_thresholds["readability"]:
            issues.append(f"Readability too low: {metrics.readability_score}")
        
        if metrics.coherence_score < self.quality_thresholds["coherence"]:
            issues.append(f"Coherence issues detected: {metrics.coherence_score}")
        
        if metrics.relevance_score < self.quality_thresholds["relevance"]:
            issues.append(f"Content may not be relevant: {metrics.relevance_score}")
        
        if metrics.completeness_score < self.quality_thresholds["completeness"]:
            issues.append(f"Content appears incomplete: {metrics.completeness_score}")
        
        return issues
    
    def _generate_recommendations(self, issues: List[str]) -> List[str]:
        """Generate recommendations for identified issues."""
        recommendations = []
        
        for issue in issues:
            if "readability" in issue.lower():
                recommendations.append("Simplify sentence structure and vocabulary")
            elif "coherence" in issue.lower():
                recommendations.append("Add transition words and improve paragraph flow")
            elif "relevance" in issue.lower():
                recommendations.append("Focus on the main topic and remove tangential content")
            elif "completeness" in issue.lower():
                recommendations.append("Expand on key points and add supporting details")
        
        return recommendations
