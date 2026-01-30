"""Detect conflicts between rules."""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RuleConflict:
    """Represents a conflict between rules."""
    rule_1_id: str
    rule_2_id: str
    conflict_type: str
    description: str
    severity: str


class RuleConflictDetector:
    """Detect conflicts between rules."""
    
    def __init__(self):
        self.conflicts: List[RuleConflict] = []
        logger.info("RuleConflictDetector initialized")
    
    def detect_conflicts(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[RuleConflict]:
        """Detect conflicts between two rules."""
        # Check for keyword conflicts
        keywords_1 = set(rule_1.get("patterns", []))
        keywords_2 = set(rule_2.get("patterns", []))
        
        if keywords_1 & keywords_2:  # Intersection
            conflict = RuleConflict(
                rule_1_id=rule_1.get("id", "unknown"),
                rule_2_id=rule_2.get("id", "unknown"),
                conflict_type="keyword_overlap",
                description="Rules have overlapping keywords",
                severity="medium"
            )
            self.conflicts.append(conflict)
            return conflict
        
        return None
    
    def detect_all_conflicts(
        self,
        rules: List[Dict[str, Any]]
    ) -> List[RuleConflict]:
        """Detect all conflicts in a rule set."""
        conflicts = []
        
        for i, rule_1 in enumerate(rules):
            for rule_2 in rules[i+1:]:
                conflict = self.detect_conflicts(rule_1, rule_2)
                if conflict:
                    conflicts.append(conflict)
        
        return conflicts
    
    def get_conflict_summary(self) -> Dict[str, Any]:
        """Get summary of detected conflicts."""
        return {
            "total_conflicts": len(self.conflicts),
            "by_severity": {
                "critical": len([c for c in self.conflicts if c.severity == "critical"]),
                "high": len([c for c in self.conflicts if c.severity == "high"]),
                "medium": len([c for c in self.conflicts if c.severity == "medium"]),
                "low": len([c for c in self.conflicts if c.severity == "low"])
            }
        }
