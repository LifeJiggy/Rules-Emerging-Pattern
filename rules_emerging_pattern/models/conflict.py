"""
Conflict detection and resolution models.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from .rule import Rule, RuleTier, RuleSeverity


class ConflictType(str, Enum):
    """Types of rule conflicts."""
    RULE_CONFLICT = "rule_conflict"  # Competing rule requirements
    PRIORITY_CONFLICT = "priority_conflict"  # Tier conflicts
    SEMANTIC_CONFLICT = "semantic_conflict"  # Meaning conflicts
    CONTEXT_CONFLICT = "context_conflict"  # Situational conflicts
    LOGICAL_CONTRADICTION = "logical_contradiction"  # Logical conflicts
    MUTUAL_EXCLUSIVITY = "mutual_exclusivity"  # Mutually exclusive outcomes


class ResolutionStrategy(str, Enum):
    """Conflict resolution strategies."""
    PRIORITY_BASED = "priority_based"  # Higher tier rules win
    CONTEXT_AWARE = "context_aware"  # Situation-based decisions
    USER_PREFERENCE = "user_preference"  # User-defined priorities
    FALLBACK = "fallback"  # Default strategies
    HYBRID = "hybrid"  # Combination strategies
    HUMAN_REVIEW = "human_review"  # Manual resolution


class ConflictSeverity(str, Enum):
    """Severity levels for conflicts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleConflict(BaseModel):
    """Individual rule conflict."""
    
    # Conflict identification
    conflict_id: str
    conflict_type: ConflictType
    severity: ConflictSeverity
    
    # Conflicting rules
    rule_1: Rule
    rule_2: Rule
    additional_rules: List[Rule] = Field(default_factory=list)  # For multi-rule conflicts
    
    # Conflict details
    description: str
    conflict_reason: str
    contradictory_elements: List[str] = Field(default_factory=list)
    context_triggers: List[str] = Field(default_factory=list)
    
    # Detection details
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    detection_method: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Resolution information
    resolution_strategy: Optional[ResolutionStrategy] = None
    resolved: bool = False
    resolution_applied: Optional[str] = None
    resolution_outcome: Optional[str] = None
    
    def is_critical(self) -> bool:
        """Check if conflict is critical."""
        return self.severity == ConflictSeverity.CRITICAL
    
    def requires_immediate_resolution(self) -> bool:
        """Check if conflict requires immediate resolution."""
        return (
            self.is_critical() or
            any(rule.tier == RuleTier.SAFETY for rule in [self.rule_1, self.rule_2] + self.additional_rules)
        )
    
    def get_involved_tiers(self) -> List[str]:
        """Get tiers involved in conflict."""
        tiers = set()
        for rule in [self.rule_1, self.rule_2] + self.additional_rules:
            tiers.add(rule.tier.value)
        return list(tiers)
    
    class Config:
        use_enum_values = True


class ConflictResolution(BaseModel):
    """Resolution for a rule conflict."""
    
    # Resolution identification
    resolution_id: str
    conflict_id: str
    strategy: ResolutionStrategy
    
    # Resolution details
    description: str
    reasoning: str
    chosen_rule_id: Optional[str] = None  # Rule that wins
    applied_action: str
    
    # Resolution configuration
    parameters: Dict[str, Any] = Field(default_factory=dict)
    custom_logic: Optional[str] = None
    
    # Outcome details
    outcome: str  # "rule_1_wins", "rule_2_wins", "compromise", "escalate"
    effectiveness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    user_satisfaction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    
    # Metadata
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    applied_by: Optional[str] = None  # System, user_id, or admin_id
    verified: bool = False
    verification_details: Optional[str] = None
    
    # Learning data
    feedback: Optional[str] = None
    success_indicators: Dict[str, bool] = Field(default_factory=dict)
    improvement_suggestions: List[str] = Field(default_factory=list)
    
    class Config:
        use_enum_values = True


class ConflictAnalysis(BaseModel):
    """Analysis of conflict patterns and trends."""
    
    # Analysis metadata
    analysis_id: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Conflict statistics
    total_conflicts: int = 0
    conflicts_by_type: Dict[str, int] = Field(default_factory=dict)
    conflicts_by_severity: Dict[str, int] = Field(default_factory=dict)
    conflicts_by_tier: Dict[str, int] = Field(default_factory=dict)
    
    # Resolution statistics
    resolved_conflicts: int = 0
    resolution_rate: float = 0.0
    average_resolution_time_ms: float = 0.0
    resolutions_by_strategy: Dict[str, int] = Field(default_factory=dict)
    
    # Effectiveness metrics
    strategy_effectiveness: Dict[str, float] = Field(default_factory=dict)
    user_satisfaction_average: float = 0.0
    escalation_rate: float = 0.0
    
    # Top conflicts
    most_frequent_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    hardest_to_resolve: List[Dict[str, Any]] = Field(default_factory=list)
    critical_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Trends and insights
    trends: Dict[str, Any] = Field(default_factory=dict)
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    
    # Rule-specific analysis
    conflict_prone_rules: List[Dict[str, Any]] = Field(default_factory=list)
    rule_pair_conflicts: Dict[str, int] = Field(default_factory=dict)
    
    def calculate_resolution_rate(self) -> float:
        """Calculate conflict resolution rate."""
        if self.total_conflicts == 0:
            return 0.0
        return (self.resolved_conflicts / self.total_conflicts) * 100
    
    def get_most_effective_strategy(self) -> Optional[str]:
        """Get the most effective resolution strategy."""
        if not self.strategy_effectiveness:
            return None
        return max(self.strategy_effectiveness.items(), key=lambda x: x[1])[0]
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictResolutionRequest(BaseModel):
    """Request for conflict resolution."""
    
    # Conflict identification
    conflict_id: Optional[str] = None
    conflicts: List[RuleConflict] = Field(default_factory=list)
    
    # Resolution preferences
    preferred_strategy: Optional[ResolutionStrategy] = None
    allowed_strategies: List[ResolutionStrategy] = Field(default_factory=list)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    
    # Context for resolution
    context: Dict[str, Any] = Field(default_factory=dict)
    business_rules: Dict[str, Any] = Field(default_factory=dict)
    legal_constraints: List[str] = Field(default_factory=list)
    
    # Resolution options
    auto_resolve: bool = True
    require_human_approval: bool = False
    timeout_ms: int = Field(default=5000, ge=1, le=30000)
    
    # Learning and feedback
    enable_learning: bool = True
    collect_feedback: bool = True
    track_effectiveness: bool = True


class ConflictResolutionResult(BaseModel):
    """Result of conflict resolution."""
    
    # Result identification
    request_id: Optional[str] = None
    resolution_id: str
    
    # Resolution summary
    success: bool
    strategy_used: ResolutionStrategy
    conflicts_resolved: int
    total_conflicts: int
    
    # Detailed resolutions
    resolutions: List[ConflictResolution] = Field(default_factory=list)
    unresolved_conflicts: List[RuleConflict] = Field(default_factory=list)
    
    # Processing details
    processing_time_ms: int = 0
    reasoning_steps: List[str] = Field(default_factory=list)
    alternative_strategies: List[str] = Field(default_factory=list)
    
    # Quality metrics
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Metadata
    resolved_at: datetime = Field(default_factory=datetime.utcnow)
    requires_human_review: bool = False
    review_reason: Optional[str] = None
    
    def get_resolution_rate(self) -> float:
        """Get resolution rate as percentage."""
        if self.total_conflicts == 0:
            return 0.0
        return (self.conflicts_resolved / self.total_conflicts) * 100
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictPattern(BaseModel):
    """Pattern of recurring conflicts."""
    
    # Pattern identification
    pattern_id: str
    pattern_name: str
    description: str
    
    # Pattern characteristics
    conflict_type: ConflictType
    rule_types_involved: List[str] = Field(default_factory=list)
    tiers_involved: List[str] = Field(default_factory=list)
    common_contexts: List[str] = Field(default_factory=list)
    
    # Frequency and impact
    occurrence_count: int = 0
    frequency_trend: str = "stable"  # increasing, decreasing, stable
    average_impact_score: float = 0.0
    resolution_success_rate: float = 0.0
    
    # Pattern details
    trigger_conditions: List[str] = Field(default_factory=list)
    contributing_factors: List[str] = Field(default_factory=list)
    mitigation_strategies: List[str] = Field(default_factory=list)
    
    # Learning and optimization
    auto_resolvable: bool = False
    recommended_resolution: Optional[ResolutionStrategy] = None
    optimization_suggestions: List[str] = Field(default_factory=list)
    
    # Metadata
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    last_observed: Optional[datetime] = None
    verified: bool = False
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }