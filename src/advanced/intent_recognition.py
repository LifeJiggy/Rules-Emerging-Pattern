"""Intent recognition for content analysis."""
import logging
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class IntentAnalysis:
    """Result of intent analysis."""
    primary_intent: str
    confidence: float
    secondary_intents: Dict[str, float]
    is_harmful: bool


class IntentAnalyzer:
    """Analyze user intent in content."""
    
    def __init__(self):
        self.harmful_intents = [
            'harm', 'attack', 'exploit', 'manipulate', 'deceive',
            'steal', 'destroy', 'weapon', 'dangerous'
        ]
        self.intent_patterns = {
            'information_seeking': [
                'how to', 'what is', 'explain', 'tell me', 'help me understand'
            ],
            'creative': [
                'write', 'create', 'generate', 'design', 'compose'
            ],
            'harmful': [
                'how to make', 'build a', 'create weapon', 'hack', 'exploit'
            ],
            'educational': [
                'learn', 'teach', 'study', 'educate', 'understand'
            ]
        }
        logger.info('IntentAnalyzer initialized')
    
    def analyze_intent(self, content: str) -> Dict[str, float]:
        """Analyze user intent in content."""
        content_lower = content.lower()
        scores = defaultdict(float)
        
        for intent_type, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    scores[intent_type] += 0.25
        
        # Normalize scores
        total = sum(scores.values())
        if total > 0:
            scores = {k: min(v / total, 1.0) for k, v in scores.items()}
        
        logger.debug(f'Intent analysis for content: {dict(scores)}')
        return dict(scores)
    
    def detect_harmful_intent(self, content: str) -> bool:
        """Detect if content has harmful intentions."""
        content_lower = content.lower()
        
        for harmful_word in self.harmful_intents:
            if harmful_word in content_lower:
                logger.warning(f'Harmful intent detected: {harmful_word}')
                return True
        
        # Check intent patterns
        intents = self.analyze_intent(content)
        if intents.get('harmful', 0) > 0.5:
            return True
        
        return False
    
    def get_intent_confidence(self, content: str, intent_type: str) -> float:
        """Get confidence score for specific intent type."""
        intents = self.analyze_intent(content)
        return intents.get(intent_type, 0.0)
    
    def comprehensive_analysis(self, content: str) -> IntentAnalysis:
        """Perform comprehensive intent analysis."""
        intents = self.analyze_intent(content)
        
        # Find primary intent
        primary_intent = max(intents, key=intents.get) if intents else 'unknown'
        confidence = intents.get(primary_intent, 0.0)
        
        # Check if harmful
        is_harmful = self.detect_harmful_intent(content)
        
        # Get secondary intents
        secondary = {k: v for k, v in intents.items() if k != primary_intent}
        
        return IntentAnalysis(
            primary_intent=primary_intent,
            confidence=confidence,
            secondary_intents=secondary,
            is_harmful=is_harmful
        )
