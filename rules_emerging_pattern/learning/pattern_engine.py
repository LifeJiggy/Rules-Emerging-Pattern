"""Pattern recognition engine for rule learning."""
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict
import re

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """Represents a recognized pattern."""
    pattern_id: str
    pattern_type: str
    confidence: float
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    metadata: Dict[str, Any]


class PatternRecognitionEngine:
    """Engine for recognizing and learning patterns from data."""
    
    def __init__(self, min_confidence: float = 0.7):
        """Initialize the pattern recognition engine.
        
        Args:
            min_confidence: Minimum confidence threshold for patterns
        """
        self.min_confidence = min_confidence
        self.patterns: Dict[str, Pattern] = {}
        self.pattern_templates: Dict[str, str] = {}
        self.observation_count = 0
        self.pattern_history: List[Dict] = []
        logger.info(f"PatternRecognitionEngine initialized (min_confidence={min_confidence})")
    
    def register_template(self, pattern_type: str, template: str) -> None:
        """Register a pattern template.
        
        Args:
            pattern_type: Type of pattern
            template: Regular expression template
        """
        try:
            re.compile(template)
            self.pattern_templates[pattern_type] = template
            logger.info(f"Registered pattern template: {pattern_type}")
        except re.error as e:
            logger.error(f"Invalid template for {pattern_type}: {e}")
    
    def analyze_data(self, data: Any, context: Optional[Dict] = None) -> List[Pattern]:
        """Analyze data and extract patterns.
        
        Args:
            data: Data to analyze
            context: Optional context information
            
        Returns:
            List of recognized patterns
        """
        found_patterns = []
        self.observation_count += 1
        
        if isinstance(data, str):
            found_patterns.extend(self._analyze_text(data, context))
        elif isinstance(data, (list, dict)):
            found_patterns.extend(self._analyze_structure(data, context))
        
        # Update pattern statistics
        for pattern in found_patterns:
            if pattern.pattern_id in self.patterns:
                existing = self.patterns[pattern.pattern_id]
                existing.occurrences += 1
                existing.last_seen = datetime.now()
                existing.confidence = min(1.0, existing.confidence + 0.05)
            else:
                self.patterns[pattern.pattern_id] = pattern
            
            self.pattern_history.append({
                'pattern_id': pattern.pattern_id,
                'timestamp': datetime.now(),
                'context': context
            })
        
        logger.info(f"Analysis found {len(found_patterns)} patterns")
        return found_patterns
    
    def _analyze_text(self, text: str, context: Optional[Dict]) -> List[Pattern]:
        """Analyze text for patterns."""
        patterns = []
        
        for pattern_type, template in self.pattern_templates.items():
            matches = re.findall(template, text)
            if matches:
                pattern_id = f"{pattern_type}_{hash(template) % 10000}"
                pattern = Pattern(
                    pattern_id=pattern_id,
                    pattern_type=pattern_type,
                    confidence=min(1.0, len(matches) * 0.1),
                    occurrences=len(matches),
                    first_seen=datetime.now(),
                    last_seen=datetime.now(),
                    metadata={'matches': matches[:10], 'context': context}
                )
                patterns.append(pattern)
        
        return patterns
    
    def _analyze_structure(self, data: Any, context: Optional[Dict]) -> List[Pattern]:
        """Analyze data structure for patterns."""
        patterns = []
        
        if isinstance(data, dict):
            # Look for common key patterns
            keys_hash = hash(tuple(sorted(data.keys())))
            pattern_id = f"structure_{keys_hash % 10000}"
            
            pattern = Pattern(
                pattern_id=pattern_id,
                pattern_type="dictionary_structure",
                confidence=0.8,
                occurrences=1,
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                metadata={'keys': list(data.keys()), 'context': context}
            )
            patterns.append(pattern)
        
        return patterns
    
    def get_patterns_by_type(self, pattern_type: str) -> List[Pattern]:
        """Get all patterns of a specific type.
        
        Args:
            pattern_type: Type of patterns to retrieve
            
        Returns:
            List of matching patterns
        """
        return [p for p in self.patterns.values() if p.pattern_type == pattern_type]
    
    def get_top_patterns(self, limit: int = 10) -> List[Pattern]:
        """Get top patterns by confidence and occurrences.
        
        Args:
            limit: Maximum number of patterns to return
            
        Returns:
            List of top patterns
        """
        sorted_patterns = sorted(
            self.patterns.values(),
            key=lambda p: (p.confidence, p.occurrences),
            reverse=True
        )
        return sorted_patterns[:limit]
    
    def generate_rules_from_patterns(self) -> List[Dict]:
        """Generate rule suggestions from learned patterns.
        
        Returns:
            List of suggested rules
        """
        suggested_rules = []
        
        for pattern in self.patterns.values():
            if pattern.confidence >= self.min_confidence and pattern.occurrences >= 3:
                rule = {
                    'rule_id': f"auto_{pattern.pattern_id}",
                    'pattern_type': pattern.pattern_type,
                    'confidence': pattern.confidence,
                    'based_on_pattern': pattern.pattern_id,
                    'suggested_action': 'review',
                    'created_at': datetime.now().isoformat()
                }
                suggested_rules.append(rule)
        
        logger.info(f"Generated {len(suggested_rules)} rule suggestions")
        return suggested_rules
    
    def get_statistics(self) -> Dict:
        """Get engine statistics.
        
        Returns:
            Dictionary with statistics
        """
        pattern_types = defaultdict(int)
        for pattern in self.patterns.values():
            pattern_types[pattern.pattern_type] += 1
        
        return {
            'total_patterns': len(self.patterns),
            'pattern_types': dict(pattern_types),
            'observations': self.observation_count,
            'templates': len(self.pattern_templates),
            'high_confidence_patterns': len([p for p in self.patterns.values() if p.confidence >= 0.9])
        }
