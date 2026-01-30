"""Detect semantic conflicts between rules."""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SemanticConflict:
    """Represents a semantic conflict."""
    rule_1_id: str
    rule_2_id: str
    conflict_type: str
    description: str


class SemanticConflictDetector:
    """Detect semantic contradictions between rules."""
    
    def __init__(self):
        self.contradiction_patterns = [
            ("allow", "deny"),
            ("enable", "disable"),
            ("require", "forbid"),
            ("must", "must_not")
        ]
        logger.info("SemanticConflictDetector initialized")
    
    def detect_semantic_conflict(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        """Detect semantic conflicts between two rules."""
        desc_1 = rule_1.get("description", "").lower()
        desc_2 = rule_2.get("description", "").lower()
        
        # Check for contradiction patterns
        for pos, neg in self.contradiction_patterns:
            if (pos in desc_1 and neg in desc_2) or (neg in desc_1 and pos in desc_2):
                return SemanticConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    conflict_type="semantic_contradiction",
                    description=f"Contradictory terms: {pos} vs {neg}"
                )
        
        return None
