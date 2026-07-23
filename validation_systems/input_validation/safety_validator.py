"""Safety validation for content."""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SafetyViolation:
    """Represents a safety violation."""
    category: str
    pattern: str
    severity: str
    message: str


class SafetyValidator:
    """Validates content for safety concerns."""
    
    def __init__(self):
        self.dangerous_patterns = {
            "child_safety": ["child exploitation", "csam", "minor abuse"],
            "weapons": ["how to make bomb", "build weapon", "explosive"],
            "self_harm": ["suicide method", "self harm", "kill yourself"],
            "violence": ["terrorist attack", "mass shooting", "violence"]
        }
        logger.info("SafetyValidator initialized")
    
    def validate(self, content: str) -> Tuple[bool, List[SafetyViolation]]:
        """Validate content for safety issues."""
        violations = []
        content_lower = content.lower()
        
        for category, patterns in self.dangerous_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    violation = SafetyViolation(
                        category=category,
                        pattern=pattern,
                        severity="critical",
                        message=f"Safety violation detected: {category}"
                    )
                    violations.append(violation)
                    logger.warning(f"Safety violation: {category} - {pattern}")
        
        return len(violations) == 0, violations
    
    def add_pattern(self, category: str, pattern: str) -> None:
        """Add a new safety pattern."""
        if category not in self.dangerous_patterns:
            self.dangerous_patterns[category] = []
        self.dangerous_patterns[category].append(pattern)
