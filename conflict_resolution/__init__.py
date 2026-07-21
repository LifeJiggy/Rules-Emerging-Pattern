"""Conflict resolution module for detecting, logging, and resolving rule conflicts."""

from .conflict_detectors import (
    RuleConflictDetector, RuleConflict, ConflictType, ConflictSeverity,
    PriorityConflictDetector, PriorityConflict, PriorityConflictType,
    SemanticConflictDetector, SemanticConflict, SemanticConflictType,
)
from .conflict_logging import (
    ConflictRecorder, ConflictRecord, ConflictStatus,
    ResolutionTracker, TrackedResolution, ResolutionMethod, ResolutionOutcome,
    ConflictAnalysis, AnalysisReport, PatternInsight, TrendPoint,
)
from .resolution_strategies import (
    PriorityBasedResolver, ResolutionResult, PriorityResolutionOutcome,
    ContextAwareResolver, ContextualResolution, ContextFactor,
    UserPreferenceResolver, UserPreference, PreferenceResolution,
    FallbackResolver, FallbackResolution, FallbackAction, EscalationLevel,
)

__all__ = [
    # Detectors
    "RuleConflictDetector", "RuleConflict", "ConflictType", "ConflictSeverity",
    "PriorityConflictDetector", "PriorityConflict", "PriorityConflictType",
    "SemanticConflictDetector", "SemanticConflict", "SemanticConflictType",
    # Logging
    "ConflictRecorder", "ConflictRecord", "ConflictStatus",
    "ResolutionTracker", "TrackedResolution", "ResolutionMethod", "ResolutionOutcome",
    "ConflictAnalysis", "AnalysisReport", "PatternInsight", "TrendPoint",
    # Strategies
    "PriorityBasedResolver", "ResolutionResult", "PriorityResolutionOutcome",
    "ContextAwareResolver", "ContextualResolution", "ContextFactor",
    "UserPreferenceResolver", "UserPreference", "PreferenceResolution",
    "FallbackResolver", "FallbackResolution", "FallbackAction", "EscalationLevel",
]
