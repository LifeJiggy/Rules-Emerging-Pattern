"""Age verification and content appropriateness."""
import logging
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AgeGroup(Enum):
    """Age group classifications."""
    CHILD = 'child'  # Under 13
    TEEN = 'teen'    # 13-17
    ADULT = 'adult'  # 18+
    ALL_AGES = 'all'


@dataclass
class ContentRating:
    """Content rating result."""
    rating: str
    age_group: str
    warnings: List[str]
    is_appropriate: bool


class AgeVerifier:
    """Verify content age appropriateness."""
    
    def __init__(self):
        self.age_restricted_keywords = {
            AgeGroup.CHILD: ['violence', 'weapons', 'drugs', 'alcohol', 'gambling'],
            AgeGroup.TEEN: ['explicit', 'gambling', 'substance abuse'],
            AgeGroup.ADULT: ['explicit adult content']
        }
        self.content_indicators = {
            'mild': ['cartoon', 'educational', 'family'],
            'moderate': ['action', 'fantasy', 'adventure'],
            'mature': ['violence', 'complex themes', 'realistic']
        }
        logger.info('AgeVerifier initialized')
    
    def verify_content_age_appropriateness(
        self, 
        content: str, 
        age_group: str
    ) -> bool:
        """Verify if content is appropriate for age group."""
        content_lower = content.lower()
        
        # Get restricted keywords for age group
        restricted = self.age_restricted_keywords.get(
            AgeGroup(age_group), 
            []
        )
        
        # Check for restricted content
        for keyword in restricted:
            if keyword in content_lower:
                logger.warning(f'Age-inappropriate content detected: {keyword}')
                return False
        
        return True
    
    def detect_age_restricted_content(self, content: str) -> List[str]:
        """Detect age-restricted content keywords."""
        content_lower = content.lower()
        detected = []
        
        for age_group, keywords in self.age_restricted_keywords.items():
            for keyword in keywords:
                if keyword in content_lower:
                    detected.append(f'{age_group.value}: {keyword}')
        
        return detected
    
    def get_content_rating(self, content: str) -> str:
        """Get content rating (G, PG, PG-13, R)."""
        content_lower = content.lower()
        
        # Check for adult content
        adult_keywords = self.age_restricted_keywords[AgeGroup.ADULT]
        if any(kw in content_lower for kw in adult_keywords):
            return 'R'
        
        # Check for teen restrictions
        teen_keywords = self.age_restricted_keywords[AgeGroup.TEEN]
        if any(kw in content_lower for kw in teen_keywords):
            return 'PG-13'
        
        # Check for child restrictions
        child_keywords = self.age_restricted_keywords[AgeGroup.CHILD]
        if any(kw in content_lower for kw in child_keywords):
            return 'PG'
        
        return 'G'
    
    def comprehensive_check(self, content: str, target_age: str) -> ContentRating:
        """Perform comprehensive age appropriateness check."""
        rating = self.get_content_rating(content)
        warnings = self.detect_age_restricted_content(content)
        is_appropriate = self.verify_content_age_appropriateness(content, target_age)
        
        return ContentRating(
            rating=rating,
            age_group=target_age,
            warnings=warnings,
            is_appropriate=is_appropriate
        )
