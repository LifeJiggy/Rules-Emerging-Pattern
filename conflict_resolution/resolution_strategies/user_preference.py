"""User preference-based conflict resolution."""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class UserPreference:
    """User preference for rule resolution."""
    rule_id: str
    preference_score: float
    reason: Optional[str] = None


class UserPreferenceResolver:
    """Resolve conflicts based on user preferences."""
    
    def __init__(self):
        self.user_preferences: Dict[str, List[UserPreference]] = {}
        logger.info("UserPreferenceResolver initialized")
    
    def set_user_preference(
        self,
        user_id: str,
        rule_id: str,
        score: float,
        reason: Optional[str] = None
    ) -> None:
        """Set user preference for a rule."""
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = []
        
        self.user_preferences[user_id].append(
            UserPreference(rule_id=rule_id, preference_score=score, reason=reason)
        )
        logger.info(f"Set preference for user {user_id}, rule {rule_id}: {score}")
    
    def resolve(
        self,
        user_id: str,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Resolve conflict based on user preferences."""
        preferences = self.user_preferences.get(user_id, [])
        
        score_1 = 0.0
        score_2 = 0.0
        
        for pref in preferences:
            if pref.rule_id == rule_1.get("id"):
                score_1 = pref.preference_score
            elif pref.rule_id == rule_2.get("id"):
                score_2 = pref.preference_score
        
        if score_1 == 0.0 and score_2 == 0.0:
            return None  # No preference set
        
        winner = rule_1 if score_1 > score_2 else rule_2
        
        return {
            "winning_rule_id": winner.get("id"),
            "strategy": "user_preference",
            "reason": "Based on user preference settings"
        }
