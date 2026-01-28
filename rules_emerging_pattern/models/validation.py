"""
Validation result models for rule evaluation.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from .rule import Rule, RuleTier, RuleSeverity


class ViolationType(str, Enum):
    """Types of rule violations."""
    KEYWORD_MATCH = "keyword_match"
    REGEX_MATCH = "regex_match"
    SEMANTIC_VIOLATION = "semantic_violation"
    STRUCTURAL_VIOLATION = "structural_violation"
    COMPLIANCE_VIOLATION = "compliance_violation"
    QUALITY_VIOLATION = "quality_violation"
    CUSTOM_VIOLATION = "custom_violation"


class ActionTaken(str, Enum):
    """Actions taken in response to violations."""
    NONE = "none"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    BLOCK = "block"
    REDACT = "redact"
    QUARANTINE = "quarantine"
    ESCALATE = "escalate"


class Violation(BaseModel):
    """Individual rule violation."""
    
    # Violation details
    rule_id: str
    rule_name: str
    rule_tier: RuleTier
    rule_severity: RuleSeverity
    violation_type: ViolationType
    
    # Detection details
    matched_content: Optional[str] = None
    matched_patterns: List[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    position_info: Dict[str, Any] = Field(default_factory=dict)
    
    # Action taken
    action_taken: ActionTaken = ActionTaken.NONE
    blocked: bool = False
    user_override_allowed: bool = False
    override_justification: Optional[str] = None
    
    # Context and explanation
    explanation: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    educational_content: Optional[str] = None
    
    # Metadata
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    detection_method: str = "automatic"
    context: Dict[str, Any] = Field(default_factory=dict)
    
    def is_critical(self) -> bool:
        """Check if violation is critical."""
        return self.rule_severity == RuleSeverity.CRITICAL
    
    def requires_escalation(self) -> bool:
        """Check if violation requires escalation."""
        return (
            self.is_critical() or
            self.action_taken == ActionTaken.ESCALATE or
            self.rule_tier == RuleTier.SAFETY
        )
    
    class Config:
        use_enum_values = True


class Suggestion(BaseModel):
    """Suggestion for content improvement."""
    
    type: str
    title: str
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Suggestion details
    original_text: Optional[str] = None
    suggested_text: Optional[str] = None
    reasoning: Optional[str] = None
    
    # Implementation
    auto_applicable: bool = False
    user_approval_required: bool = True
    implementation_steps: List[str] = Field(default_factory=list)
    
    # Metadata
    source_rule: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationResult(BaseModel):
    """Result of rule validation."""
    
    # Overall assessment
    valid: bool
    total_score: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    
    # Rule evaluation summary
    total_rules_evaluated: int = 0
    rules_triggered: int = 0
    rules_violated: int = 0
    
    # Violations
    violations: List[Violation] = Field(default_factory=list)
    critical_violations: List[Violation] = Field(default_factory=list)
    warnings: List[Violation] = Field(default_factory=list)
    
    # Suggestions
    suggestions: List[Suggestion] = Field(default_factory=list)
    
    # Processing details
    processing_time_ms: int = 0
    rules_by_tier: Dict[str, int] = Field(default_factory=dict)
    processing_details: Dict[str, Any] = Field(default_factory=dict)
    
    # Context and metadata
    request_id: Optional[str] = None
    content_hash: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluator_version: str = "1.0.0"
    
    def has_violations(self) -> bool:
        """Check if result has any violations."""
        return len(self.violations) > 0
    
    def has_critical_violations(self) -> bool:
        """Check if result has critical violations."""
        return len(self.critical_violations) > 0
    
    def is_blocked(self) -> bool:
        """Check if content should be blocked."""
        return any(violation.blocked for violation in self.violations)
    
    def get_violations_by_tier(self) -> Dict[str, List[Violation]]:
        """Group violations by rule tier."""
        violations_by_tier = {}
        for violation in self.violations:
            tier = violation.rule_tier.value
            if tier not in violations_by_tier:
                violations_by_tier[tier] = []
            violations_by_tier[tier].append(violation)
        return violations_by_tier
    
    def get_violations_by_severity(self) -> Dict[str, List[Violation]]:
        """Group violations by severity."""
        violations_by_severity = {}
        for violation in self.violations:
            severity = violation.rule_severity.value
            if severity not in violations_by_severity:
                violations_by_severity[severity] = []
            violations_by_severity[severity].append(violation)
        return violations_by_severity
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of validation results."""
        return {
            "valid": self.valid,
            "blocked": self.is_blocked(),
            "score": self.total_score,
            "violations_count": len(self.violations),
            "critical_violations": len(self.critical_violations),
            "warnings_count": len(self.warnings),
            "suggestions_count": len(self.suggestions),
            "rules_evaluated": self.total_rules_evaluated,
            "processing_time_ms": self.processing_time_ms,
            "violations_by_tier": self.get_violations_by_tier(),
            "violations_by_severity": self.get_violations_by_severity()
        }
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class BatchValidationRequest(BaseModel):
    """Request for batch validation."""
    
    requests: List[str]  # List of content to validate
    common_context: Optional[Dict[str, Any]] = None
    batch_options: Dict[str, Any] = Field(default_factory=dict)
    
    # Batch processing options
    max_parallel: int = Field(default=10, ge=1, le=100)
    fail_fast: bool = False  # Stop on first critical violation
    return_individual_results: bool = True
    aggregate_results: bool = True


class BatchValidationResult(BaseModel):
    """Result of batch validation."""
    
    # Overall batch results
    total_items: int
    valid_items: int
    blocked_items: int
    items_with_violations: int
    
    # Individual results
    individual_results: List[ValidationResult] = Field(default_factory=list)
    
    # Aggregated metrics
    total_processing_time_ms: int = 0
    average_processing_time_ms: float = 0.0
    total_violations: int = 0
    total_suggestions: int = 0
    
    # Batch metadata
    batch_id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def get_success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.valid_items / self.total_items) * 100
    
    def get_violation_rate(self) -> float:
        """Get violation rate as percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.items_with_violations / self.total_items) * 100
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ComplianceReport(BaseModel):
    """Compliance report for rule evaluation."""
    
    # Report metadata
    report_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    period_start: datetime
    period_end: datetime
    
    # Compliance metrics
    total_evaluations: int = 0
    compliant_evaluations: int = 0
    non_compliant_evaluations: int = 0
    compliance_rate: float = 0.0
    
    # Violations by category
    violations_by_tier: Dict[str, int] = Field(default_factory=dict)
    violations_by_severity: Dict[str, int] = Field(default_factory=dict)
    violations_by_type: Dict[str, int] = Field(default_factory=dict)
    
    # Performance metrics
    average_processing_time_ms: float = 0.0
    peak_processing_time_ms: int = 0
    total_processing_time_ms: int = 0
    
    # Trends and insights
    trends: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    
    def calculate_compliance_rate(self) -> float:
        """Calculate compliance rate."""
        if self.total_evaluations == 0:
            return 0.0
        return (self.compliant_evaluations / self.total_evaluations) * 100
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }