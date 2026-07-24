"""
Validation result models for rule evaluation.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field, validator, root_validator

from .rule import Rule, RuleTier, RuleSeverity

logger = logging.getLogger(__name__)


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

    rule_id: str
    rule_name: str
    rule_tier: RuleTier
    rule_severity: RuleSeverity
    violation_type: ViolationType

    matched_content: Optional[str] = None
    matched_patterns: List[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    position_info: Dict[str, Any] = Field(default_factory=dict)

    action_taken: ActionTaken = ActionTaken.NONE
    blocked: bool = False
    user_override_allowed: bool = False
    override_justification: Optional[str] = None

    explanation: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    educational_content: Optional[str] = None

    detected_at: datetime = Field(default_factory=datetime.utcnow)
    detection_method: str = "automatic"
    context: Dict[str, Any] = Field(default_factory=dict)

    def is_critical(self) -> bool:
        return self.rule_severity == RuleSeverity.CRITICAL

    def requires_escalation(self) -> bool:
        return (
            self.is_critical() or
            self.action_taken == ActionTaken.ESCALATE or
            self.rule_tier == RuleTier.SAFETY
        )

    def get_violation_hash(self) -> str:
        content = f"{self.rule_id}:{self.violation_type.value}:{self.matched_content}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_summary(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_tier": self.rule_tier.value,
            "rule_severity": self.rule_severity.value,
            "violation_type": self.violation_type.value,
            "action_taken": self.action_taken.value,
            "blocked": self.blocked,
            "confidence": round(self.confidence_score, 2),
            "critical": self.is_critical()
        }

    def was_blocked(self) -> bool:
        return self.blocked

    def was_overridden(self) -> bool:
        return self.override_justification is not None

    class Config:
        use_enum_values = True


class Suggestion(BaseModel):
    """Suggestion for content improvement."""

    type: str
    title: str
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    original_text: Optional[str] = None
    suggested_text: Optional[str] = None
    reasoning: Optional[str] = None

    auto_applicable: bool = False
    user_approval_required: bool = True
    implementation_steps: List[str] = Field(default_factory=list)

    source_rule: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def is_applicable(self) -> bool:
        return self.auto_applicable or not self.user_approval_required

    def apply_suggestion(self) -> Optional[str]:
        if self.auto_applicable and self.suggested_text:
            return self.suggested_text
        return None

    def get_steps_summary(self) -> str:
        if not self.implementation_steps:
            return "No implementation steps provided"
        return "; ".join(self.implementation_steps)

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationResult(BaseModel):
    """Result of rule validation."""

    valid: bool
    total_score: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    total_rules_evaluated: int = 0
    rules_triggered: int = 0
    rules_violated: int = 0

    violations: List[Violation] = Field(default_factory=list)
    critical_violations: List[Violation] = Field(default_factory=list)
    warnings: List[Violation] = Field(default_factory=list)

    suggestions: List[Suggestion] = Field(default_factory=list)

    processing_time_ms: int = 0
    rules_by_tier: Dict[str, int] = Field(default_factory=dict)
    processing_details: Dict[str, Any] = Field(default_factory=dict)

    request_id: Optional[str] = None
    content_hash: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluator_version: str = "1.0.0"

    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def has_critical_violations(self) -> bool:
        return len(self.critical_violations) > 0

    def is_blocked(self) -> bool:
        return any(violation.blocked for violation in self.violations)

    def get_violations_by_tier(self) -> Dict[str, List[Violation]]:
        violations_by_tier = {}
        for violation in self.violations:
            tier = violation.rule_tier.value
            if tier not in violations_by_tier:
                violations_by_tier[tier] = []
            violations_by_tier[tier].append(violation)
        return violations_by_tier

    def get_violations_by_severity(self) -> Dict[str, List[Violation]]:
        violations_by_severity = {}
        for violation in self.violations:
            severity = violation.rule_severity.value
            if severity not in violations_by_severity:
                violations_by_severity[severity] = []
            violations_by_severity[severity].append(violation)
        return violations_by_severity

    def get_summary(self) -> Dict[str, Any]:
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

    def get_top_violations(self, n: int = 5) -> List[Violation]:
        sorted_violations = sorted(self.violations, key=lambda v: (
            v.rule_severity.value != RuleSeverity.CRITICAL.value,
            v.confidence_score
        ), reverse=True)
        return sorted_violations[:n]

    def get_score_breakdown(self) -> Dict[str, float]:
        tier_penalties = len(self.get_violations_by_tier().get(RuleTier.SAFETY.value, [])) * 0.3
        severity_penalties = len(self.critical_violations) * 0.2 + len(self.warnings) * 0.05
        total_penalty = min(tier_penalties + severity_penalties, 1.0)
        return {
            "base_score": 1.0,
            "tier_penalty": round(tier_penalties, 3),
            "severity_penalty": round(severity_penalties, 3),
            "total_penalty": round(total_penalty, 3),
            "final_score": round(max(1.0 - total_penalty, 0.0), 3)
        }

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        merged = self.copy(deep=True)
        merged.total_rules_evaluated += other.total_rules_evaluated
        merged.rules_triggered += other.rules_triggered
        merged.rules_violated += other.rules_violated
        merged.violations.extend(other.violations)
        merged.critical_violations.extend(other.critical_violations)
        merged.warnings.extend(other.warnings)
        merged.suggestions.extend(other.suggestions)
        merged.processing_time_ms += other.processing_time_ms
        for tier_key, count in other.rules_by_tier.items():
            merged.rules_by_tier[tier_key] = merged.rules_by_tier.get(tier_key, 0) + count
        merged.valid = len(merged.critical_violations) == 0
        merged.total_score = min(merged.total_score, other.total_score)
        merged.confidence = (merged.confidence + other.confidence) / 2
        merged.processing_details.update(other.processing_details)
        return merged

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class BatchValidationRequest(BaseModel):
    """Request for batch validation."""

    requests: List[str]
    common_context: Optional[Dict[str, Any]] = None
    batch_options: Dict[str, Any] = Field(default_factory=dict)

    max_parallel: int = Field(default=10, ge=1, le=100)
    fail_fast: bool = False
    return_individual_results: bool = True
    aggregate_results: bool = True

    def get_request_count(self) -> int:
        return len(self.requests)

    def get_batch_id(self) -> str:
        content = "|".join(self.requests)
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()


class BatchValidationResult(BaseModel):
    """Result of batch validation."""

    total_items: int
    valid_items: int
    blocked_items: int
    items_with_violations: int

    individual_results: List[ValidationResult] = Field(default_factory=list)

    total_processing_time_ms: int = 0
    average_processing_time_ms: float = 0.0
    total_violations: int = 0
    total_suggestions: int = 0

    batch_id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def get_success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.valid_items / self.total_items) * 100

    def get_violation_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.items_with_violations / self.total_items) * 100

    def get_summary(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "total_items": self.total_items,
            "valid_items": self.valid_items,
            "blocked_items": self.blocked_items,
            "items_with_violations": self.items_with_violations,
            "success_rate": round(self.get_success_rate(), 2),
            "violation_rate": round(self.get_violation_rate(), 2),
            "total_violations": self.total_violations,
            "total_suggestions": self.total_suggestions,
            "avg_processing_time_ms": round(self.average_processing_time_ms, 2),
            "total_processing_time_ms": self.total_processing_time_ms
        }

    def get_merge_result(self) -> ValidationResult:
        if not self.individual_results:
            return ValidationResult(
                valid=True,
                total_rules_evaluated=0
            )
        merged = self.individual_results[0].copy(deep=True)
        for result in self.individual_results[1:]:
            merged = merged.merge(result)
        return merged

    def is_complete(self) -> bool:
        return self.completed_at is not None

    def mark_complete(self) -> None:
        self.completed_at = datetime.utcnow()
        if self.total_items > 0:
            self.average_processing_time_ms = self.total_processing_time_ms / self.total_items

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ComplianceReport(BaseModel):
    """Compliance report for rule evaluation."""

    report_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    period_start: datetime
    period_end: datetime

    total_evaluations: int = 0
    compliant_evaluations: int = 0
    non_compliant_evaluations: int = 0
    compliance_rate: float = 0.0

    violations_by_tier: Dict[str, int] = Field(default_factory=dict)
    violations_by_severity: Dict[str, int] = Field(default_factory=dict)
    violations_by_type: Dict[str, int] = Field(default_factory=dict)

    average_processing_time_ms: float = 0.0
    peak_processing_time_ms: int = 0
    total_processing_time_ms: int = 0

    trends: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)

    def calculate_compliance_rate(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return (self.compliant_evaluations / self.total_evaluations) * 100

    def get_summary(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "period": f"{self.period_start.isoformat()} to {self.period_end.isoformat()}",
            "total_evaluations": self.total_evaluations,
            "compliance_rate": round(self.calculate_compliance_rate(), 2),
            "total_violations": sum(self.violations_by_tier.values()),
            "avg_processing_time_ms": round(self.average_processing_time_ms, 2),
            "recommendations_count": len(self.recommendations)
        }

    def add_evaluation_data(self, result: ValidationResult) -> None:
        self.total_evaluations += 1
        if result.valid:
            self.compliant_evaluations += 1
        else:
            self.non_compliant_evaluations += 1
        self.total_processing_time_ms += result.processing_time_ms
        if result.processing_time_ms > self.peak_processing_time_ms:
            self.peak_processing_time_ms = result.processing_time_ms
        self.average_processing_time_ms = self.total_processing_time_ms / self.total_evaluations
        for tier_key, count in result.rules_by_tier.items():
            self.violations_by_tier[tier_key] = self.violations_by_tier.get(tier_key, 0) + count
        for violation in result.violations:
            severity_key = violation.rule_severity.value
            self.violations_by_severity[severity_key] = self.violations_by_severity.get(severity_key, 0) + 1
            type_key = violation.violation_type.value
            self.violations_by_type[type_key] = self.violations_by_type.get(type_key, 0) + 1
        self.compliance_rate = self.calculate_compliance_rate()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationProfile(BaseModel):
    """User/organization validation profiles."""

    profile_id: str
    name: str
    description: Optional[str] = None
    profile_type: str = "user"
    owner: Optional[str] = None
    organization: Optional[str] = None

    enabled_tiers: List[RuleTier] = Field(default_factory=lambda: [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE])
    enabled_rule_types: List[str] = Field(default_factory=list)
    excluded_rule_ids: List[str] = Field(default_factory=list)
    severity_overrides: Dict[str, str] = Field(default_factory=dict)
    enforcement_overrides: Dict[str, str] = Field(default_factory=dict)

    timeout_ms: int = Field(default=1000, ge=1, le=10000)
    parallel_evaluation: bool = True
    early_termination: bool = True
    max_violations: int = Field(default=100, ge=1, le=10000)

    is_default: bool = False
    is_active: bool = True
    priority: int = Field(default=500, ge=1, le=1000)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def should_evaluate_tier(self, tier: RuleTier) -> bool:
        return tier in self.enabled_tiers

    def should_evaluate_rule_type(self, rule_type: str) -> bool:
        if not self.enabled_rule_types:
            return True
        return rule_type in self.enabled_rule_types

    def should_evaluate_rule(self, rule: Rule) -> bool:
        if rule.id in self.excluded_rule_ids:
            return False
        if not self.should_evaluate_tier(rule.tier):
            return False
        if not self.should_evaluate_rule_type(rule.rule_type.value):
            return False
        return True

    def get_severity_override(self, rule_id: str) -> Optional[str]:
        return self.severity_overrides.get(rule_id)

    def get_enforcement_override(self, rule_id: str) -> Optional[str]:
        return self.enforcement_overrides.get(rule_id)

    def add_exclusion(self, rule_id: str) -> None:
        if rule_id not in self.excluded_rule_ids:
            self.excluded_rule_ids.append(rule_id)
            self.updated_at = datetime.utcnow()

    def remove_exclusion(self, rule_id: str) -> bool:
        if rule_id in self.excluded_rule_ids:
            self.excluded_rule_ids.remove(rule_id)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def clone(self, new_profile_id: str, new_name: str) -> 'ValidationProfile':
        cloned = self.copy(deep=True)
        cloned.profile_id = new_profile_id
        cloned.name = new_name
        cloned.is_default = False
        cloned.created_at = datetime.utcnow()
        cloned.updated_at = datetime.utcnow()
        return cloned

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationAudit(BaseModel):
    """Audit trail for validation events."""

    audit_id: str
    event_type: str
    request_id: Optional[str] = None
    validation_result_id: Optional[str] = None
    actor: str
    actor_type: str = "system"

    event_data: Dict[str, Any] = Field(default_factory=dict)
    previous_state: Optional[Dict[str, Any]] = None
    new_state: Optional[Dict[str, Any]] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)

    outcome: str = "success"
    reason: Optional[str] = None
    details: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    duration_ms: Optional[int] = None

    related_audit_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def record_change(self, field: str, old_value: Any, new_value: Any) -> None:
        self.changes.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_change_count(self) -> int:
        return len(self.changes)

    def link_audit(self, audit_id: str) -> None:
        if audit_id not in self.related_audit_ids:
            self.related_audit_ids.append(audit_id)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "outcome": self.outcome,
            "timestamp": self.timestamp.isoformat(),
            "change_count": self.get_change_count()
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationThreshold(BaseModel):
    """Configurable threshold sets."""

    threshold_id: str
    name: str
    description: Optional[str] = None
    threshold_type: str = "score"

    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    max_score: float = Field(default=1.0, ge=0.0, le=1.0)
    warning_score: float = Field(default=0.7, ge=0.0, le=1.0)
    critical_score: float = Field(default=0.4, ge=0.0, le=1.0)

    max_violations: int = Field(default=10, ge=0, le=1000)
    max_critical_violations: int = Field(default=0, ge=0, le=100)
    max_warnings: int = Field(default=20, ge=0, le=1000)

    max_processing_time_ms: int = Field(default=2000, ge=1, le=30000)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_suggestions: int = Field(default=50, ge=0, le=1000)

    is_strict: bool = False
    is_default: bool = False
    is_active: bool = True
    priority: int = Field(default=500, ge=1, le=1000)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_within_threshold(self, result: ValidationResult) -> Tuple[bool, List[str]]:
        violations = []
        if result.total_score < self.min_score:
            violations.append(f"Score {result.total_score} below minimum {self.min_score}")
        if result.total_score < self.critical_score:
            violations.append(f"Score {result.total_score} below critical threshold {self.critical_score}")
        if len(result.violations) > self.max_violations:
            violations.append(f"Violations {len(result.violations)} exceed max {self.max_violations}")
        if len(result.critical_violations) > self.max_critical_violations:
            violations.append(f"Critical violations {len(result.critical_violations)} exceed max {self.max_critical_violations}")
        if len(result.warnings) > self.max_warnings:
            violations.append(f"Warnings {len(result.warnings)} exceed max {self.max_warnings}")
        if result.processing_time_ms > self.max_processing_time_ms:
            violations.append(f"Processing time {result.processing_time_ms}ms exceeds max {self.max_processing_time_ms}ms")
        if result.confidence < self.min_confidence:
            violations.append(f"Confidence {result.confidence} below minimum {self.min_confidence}")
        if len(result.suggestions) > self.max_suggestions:
            violations.append(f"Suggestions {len(result.suggestions)} exceed max {self.max_suggestions}")
        return len(violations) == 0, violations

    def is_warning(self, result: ValidationResult) -> bool:
        return result.total_score < self.warning_score

    def is_critical(self, result: ValidationResult) -> bool:
        return result.total_score < self.critical_score

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationReport(BaseModel):
    """Detailed report model."""

    report_id: str
    title: str
    description: Optional[str] = None
    report_type: str = "standard"
    scope: str = "evaluation"

    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    total_evaluations: int = 0
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    pass_rate: float = 0.0

    violations_summary: Dict[str, int] = Field(default_factory=dict)
    top_violations: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions_summary: Dict[str, int] = Field(default_factory=dict)
    results: List[ValidationResult] = Field(default_factory=list)

    performance_stats: Dict[str, Any] = Field(default_factory=dict)
    trends: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    conclusion: Optional[str] = None

    generated_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def calculate_pass_rate(self) -> float:
        total = self.pass_count + self.fail_count
        if total == 0:
            return 0.0
        return (self.pass_count / total) * 100

    def add_result(self, result: ValidationResult) -> None:
        self.total_evaluations += 1
        self.results.append(result)
        if result.valid:
            self.pass_count += 1
        else:
            self.fail_count += 1
        for violation in result.violations:
            key = violation.violation_type.value
            self.violations_summary[key] = self.violations_summary.get(key, 0) + 1
        for suggestion in result.suggestions:
            key = suggestion.type
            self.suggestions_summary[key] = self.suggestions_summary.get(key, 0) + 1
        self.pass_rate = self.calculate_pass_rate()

    def get_executive_summary(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "total_evaluations": self.total_evaluations,
            "pass_rate": round(self.pass_rate, 2),
            "fail_count": self.fail_count,
            "error_count": self.error_count,
            "top_violation_types": dict(list(self.violations_summary.items())[:5]),
            "recommendations_count": len(self.recommendations)
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationFeedback(BaseModel):
    """Feedback on validation results."""

    feedback_id: str
    validation_result_id: str
    request_id: Optional[str] = None
    user_id: Optional[str] = None

    rating: int = Field(default=3, ge=1, le=5)
    was_helpful: bool = True
    was_accurate: bool = True
    was_actionable: bool = True

    comments: Optional[str] = None
    specific_feedback: Dict[str, Any] = Field(default_factory=dict)

    false_positive: bool = False
    false_negative: bool = False
    missed_violations: List[str] = Field(default_factory=list)
    incorrect_violations: List[str] = Field(default_factory=list)

    improvement_suggestions: List[str] = Field(default_factory=list)
    user_corrections: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_positive(self) -> bool:
        return self.rating >= 4 and self.was_helpful

    def is_negative(self) -> bool:
        return self.rating <= 2 or self.false_positive

    def get_satisfaction_score(self) -> float:
        score = self.rating / 5.0
        if self.was_accurate:
            score = min(score + 0.1, 1.0)
        if self.was_actionable:
            score = min(score + 0.1, 1.0)
        if self.false_positive:
            score = max(score - 0.3, 0.0)
        if self.false_negative:
            score = max(score - 0.2, 0.0)
        return score

    def to_summary(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "rating": self.rating,
            "was_helpful": self.was_helpful,
            "was_accurate": self.was_accurate,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "satisfaction_score": round(self.get_satisfaction_score(), 2),
            "is_positive": self.is_positive(),
            "has_comments": self.comments is not None
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }