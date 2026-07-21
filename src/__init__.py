"""
Rules-Emerging-Pattern: AI Guardrails and Consistency Framework

A comprehensive rules engine providing strict guardrails, consistency enforcement, 
and safety boundaries for AI systems through a sophisticated tiered architecture.
"""

__version__ = "1.0.0"
__author__ = "Rules Engine Team"
__email__ = "team@rules-emerging-pattern.com"

from .core.rule_engine import RuleEngine
from .core.rule_manager import RuleManager
from .models.rule import Rule, RuleTier, EnforcementLevel
from .models.validation import ValidationResult
from .models.conflict import ConflictResolution

# Convenience imports for common usage
__all__ = [
    "RuleEngine",
    "RuleManager", 
    "Rule",
    "RuleTier",
    "EnforcementLevel",
    "ValidationResult",
    "ConflictResolution",
]