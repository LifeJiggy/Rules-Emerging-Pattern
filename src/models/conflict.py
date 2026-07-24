"""
Conflict detection and resolution models.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, validator, root_validator

from .rule import Rule, RuleTier, RuleSeverity

logger = logging.getLogger(__name__)


class ConflictType(str, Enum):
    """Types of rule conflicts."""
    RULE_CONFLICT = "rule_conflict"
    PRIORITY_CONFLICT = "priority_conflict"
    SEMANTIC_CONFLICT = "semantic_conflict"
    CONTEXT_CONFLICT = "context_conflict"
    LOGICAL_CONTRADICTION = "logical_contradiction"
    MUTUAL_EXCLUSIVITY = "mutual_exclusivity"


class ResolutionStrategy(str, Enum):
    """Conflict resolution strategies."""
    PRIORITY_BASED = "priority_based"
    CONTEXT_AWARE = "context_aware"
    USER_PREFERENCE = "user_preference"
    FALLBACK = "fallback"
    HYBRID = "hybrid"
    HUMAN_REVIEW = "human_review"


class ConflictSeverity(str, Enum):
    """Severity levels for conflicts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleConflict(BaseModel):
    """Individual rule conflict."""

    conflict_id: str
    conflict_type: ConflictType
    severity: ConflictSeverity

    rule_1: Rule
    rule_2: Rule
    additional_rules: List[Rule] = Field(default_factory=list)

    description: str
    conflict_reason: str
    contradictory_elements: List[str] = Field(default_factory=list)
    context_triggers: List[str] = Field(default_factory=list)

    detected_at: datetime = Field(default_factory=datetime.utcnow)
    detection_method: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    resolution_strategy: Optional[ResolutionStrategy] = None
    resolved: bool = False
    resolution_applied: Optional[str] = None
    resolution_outcome: Optional[str] = None

    def is_critical(self) -> bool:
        return self.severity == ConflictSeverity.CRITICAL

    def requires_immediate_resolution(self) -> bool:
        return (
            self.is_critical() or
            any(rule.tier == RuleTier.SAFETY for rule in [self.rule_1, self.rule_2] + self.additional_rules)
        )

    def get_involved_tiers(self) -> List[str]:
        tiers = set()
        for rule in [self.rule_1, self.rule_2] + self.additional_rules:
            tiers.add(rule.tier.value)
        return list(tiers)

    def get_involved_rule_ids(self) -> List[str]:
        ids = [self.rule_1.id, self.rule_2.id]
        ids.extend(r.id for r in self.additional_rules)
        return ids

    def get_involved_severities(self) -> List[str]:
        severities = set()
        for rule in [self.rule_1, self.rule_2] + self.additional_rules:
            severities.add(rule.severity.value)
        return list(severities)

    def has_rule(self, rule_id: str) -> bool:
        if self.rule_1.id == rule_id or self.rule_2.id == rule_id:
            return True
        return any(r.id == rule_id for r in self.additional_rules)

    def get_conflict_hash(self) -> str:
        ids = sorted(self.get_involved_rule_ids())
        content = f"{self.conflict_type.value}:{':'.join(ids)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def mark_resolved(self, strategy: ResolutionStrategy, outcome: str) -> None:
        self.resolved = True
        self.resolution_strategy = strategy
        self.resolution_outcome = outcome
        self.resolution_applied = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True


class ConflictResolution(BaseModel):
    """Resolution for a rule conflict."""

    resolution_id: str
    conflict_id: str
    strategy: ResolutionStrategy

    description: str
    reasoning: str
    chosen_rule_id: Optional[str] = None
    applied_action: str

    parameters: Dict[str, Any] = Field(default_factory=dict)
    custom_logic: Optional[str] = None

    outcome: str
    effectiveness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    user_satisfaction: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    applied_at: datetime = Field(default_factory=datetime.utcnow)
    applied_by: Optional[str] = None
    verified: bool = False
    verification_details: Optional[str] = None

    feedback: Optional[str] = None
    success_indicators: Dict[str, bool] = Field(default_factory=dict)
    improvement_suggestions: List[str] = Field(default_factory=list)

    def is_effective(self, threshold: float = 0.7) -> bool:
        return self.effectiveness_score >= threshold

    def needs_followup(self) -> bool:
        return self.effectiveness_score < 0.5 or not self.verified

    def get_winning_rule_name(self) -> Optional[str]:
        return None

    def verify(self, details: str) -> None:
        self.verified = True
        self.verification_details = details

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True


class ConflictAnalysis(BaseModel):
    """Analysis of conflict patterns and trends."""

    analysis_id: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    total_conflicts: int = 0
    conflicts_by_type: Dict[str, int] = Field(default_factory=dict)
    conflicts_by_severity: Dict[str, int] = Field(default_factory=dict)
    conflicts_by_tier: Dict[str, int] = Field(default_factory=dict)

    resolved_conflicts: int = 0
    resolution_rate: float = 0.0
    average_resolution_time_ms: float = 0.0
    resolutions_by_strategy: Dict[str, int] = Field(default_factory=dict)

    strategy_effectiveness: Dict[str, float] = Field(default_factory=dict)
    user_satisfaction_average: float = 0.0
    escalation_rate: float = 0.0

    most_frequent_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    hardest_to_resolve: List[Dict[str, Any]] = Field(default_factory=list)
    critical_conflicts: List[Dict[str, Any]] = Field(default_factory=list)

    trends: Dict[str, Any] = Field(default_factory=dict)
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)

    conflict_prone_rules: List[Dict[str, Any]] = Field(default_factory=list)
    rule_pair_conflicts: Dict[str, int] = Field(default_factory=dict)

    def calculate_resolution_rate(self) -> float:
        if self.total_conflicts == 0:
            return 0.0
        return (self.resolved_conflicts / self.total_conflicts) * 100

    def get_most_effective_strategy(self) -> Optional[str]:
        if not self.strategy_effectiveness:
            return None
        return max(self.strategy_effectiveness.items(), key=lambda x: x[1])[0]

    def get_most_frequent_conflict_type(self) -> Optional[str]:
        if not self.conflicts_by_type:
            return None
        return max(self.conflicts_by_type.items(), key=lambda x: x[1])[0]

    def get_conflict_trend(self) -> str:
        if len(self.conflicts_by_type) < 2:
            return "insufficient_data"
        total_recent = sum(self.conflicts_by_type.get(t, 0) for t in list(self.conflicts_by_type.keys())[-3:])
        total_prior = sum(self.conflicts_by_type.get(t, 0) for t in list(self.conflicts_by_type.keys())[:-3])
        if total_prior == 0:
            return "increasing" if total_recent > 0 else "stable"
        ratio = total_recent / total_prior
        if ratio > 1.2:
            return "increasing"
        elif ratio < 0.8:
            return "decreasing"
        return "stable"

    def merge_analysis(self, other: 'ConflictAnalysis') -> 'ConflictAnalysis':
        merged = self.copy(deep=True)
        merged.total_conflicts += other.total_conflicts
        merged.resolved_conflicts += other.resolved_conflicts
        for key, val in other.conflicts_by_type.items():
            merged.conflicts_by_type[key] = merged.conflicts_by_type.get(key, 0) + val
        for key, val in other.conflicts_by_severity.items():
            merged.conflicts_by_severity[key] = merged.conflicts_by_severity.get(key, 0) + val
        for key, val in other.conflicts_by_tier.items():
            merged.conflicts_by_tier[key] = merged.conflicts_by_tier.get(key, 0) + val
        for key, val in other.resolutions_by_strategy.items():
            merged.resolutions_by_strategy[key] = merged.resolutions_by_strategy.get(key, 0) + val
        merged.insights.extend(other.insights)
        merged.recommendations.extend(other.recommendations)
        merged.trends.update(other.trends)
        merged.period_end = other.period_end
        merged.generated_at = datetime.utcnow()
        merged.calculate_resolution_rate()
        return merged

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictResolutionRequest(BaseModel):
    """Request for conflict resolution."""

    conflict_id: Optional[str] = None
    conflicts: List[RuleConflict] = Field(default_factory=list)

    preferred_strategy: Optional[ResolutionStrategy] = None
    allowed_strategies: List[ResolutionStrategy] = Field(default_factory=list)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)

    context: Dict[str, Any] = Field(default_factory=dict)
    business_rules: Dict[str, Any] = Field(default_factory=dict)
    legal_constraints: List[str] = Field(default_factory=list)

    auto_resolve: bool = True
    require_human_approval: bool = False
    timeout_ms: int = Field(default=5000, ge=1, le=30000)

    enable_learning: bool = True
    collect_feedback: bool = True
    track_effectiveness: bool = True

    def get_all_conflicts(self) -> List[RuleConflict]:
        result = list(self.conflicts)
        return result

    def get_conflict_ids(self) -> List[str]:
        ids = []
        if self.conflict_id:
            ids.append(self.conflict_id)
        for conflict in self.conflicts:
            if conflict.conflict_id not in ids:
                ids.append(conflict.conflict_id)
        return ids

    def is_strategy_allowed(self, strategy: ResolutionStrategy) -> bool:
        if not self.allowed_strategies:
            return True
        return strategy in self.allowed_strategies

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()


class ConflictResolutionResult(BaseModel):
    """Result of conflict resolution."""

    request_id: Optional[str] = None
    resolution_id: str

    success: bool
    strategy_used: ResolutionStrategy
    conflicts_resolved: int
    total_conflicts: int

    resolutions: List[ConflictResolution] = Field(default_factory=list)
    unresolved_conflicts: List[RuleConflict] = Field(default_factory=list)

    processing_time_ms: int = 0
    reasoning_steps: List[str] = Field(default_factory=list)
    alternative_strategies: List[str] = Field(default_factory=list)

    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)

    resolved_at: datetime = Field(default_factory=datetime.utcnow)
    requires_human_review: bool = False
    review_reason: Optional[str] = None

    def get_resolution_rate(self) -> float:
        if self.total_conflicts == 0:
            return 0.0
        return (self.conflicts_resolved / self.total_conflicts) * 100

    def has_unresolved_critical(self) -> bool:
        return any(c.is_critical() for c in self.unresolved_conflicts)

    def get_human_review_required(self) -> bool:
        return self.requires_human_review or self.has_unresolved_critical()

    def get_summary(self) -> Dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "success": self.success,
            "strategy_used": self.strategy_used.value,
            "conflicts_resolved": self.conflicts_resolved,
            "total_conflicts": self.total_conflicts,
            "resolution_rate": round(self.get_resolution_rate(), 2),
            "processing_time_ms": self.processing_time_ms,
            "confidence_score": round(self.confidence_score, 2),
            "consistency_score": round(self.consistency_score, 2),
            "requires_human_review": self.requires_human_review,
            "unresolved_count": len(self.unresolved_conflicts)
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictPattern(BaseModel):
    """Pattern of recurring conflicts."""

    pattern_id: str
    pattern_name: str
    description: str

    conflict_type: ConflictType
    rule_types_involved: List[str] = Field(default_factory=list)
    tiers_involved: List[str] = Field(default_factory=list)
    common_contexts: List[str] = Field(default_factory=list)

    occurrence_count: int = 0
    frequency_trend: str = "stable"
    average_impact_score: float = 0.0
    resolution_success_rate: float = 0.0

    trigger_conditions: List[str] = Field(default_factory=list)
    contributing_factors: List[str] = Field(default_factory=list)
    mitigation_strategies: List[str] = Field(default_factory=list)

    auto_resolvable: bool = False
    recommended_resolution: Optional[ResolutionStrategy] = None
    optimization_suggestions: List[str] = Field(default_factory=list)

    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    last_observed: Optional[datetime] = None
    verified: bool = False

    def matches_conflict(self, conflict: RuleConflict) -> bool:
        if conflict.conflict_type != self.conflict_type:
            return False
        involved_types = set()
        for rule in [conflict.rule_1, conflict.rule_2] + conflict.additional_rules:
            involved_types.add(rule.rule_type.value)
        if involved_types and self.rule_types_involved:
            if not involved_types.intersection(self.rule_types_involved):
                return False
        return True

    def record_occurrence(self, success: bool = True, impact_score: float = 0.0) -> None:
        self.occurrence_count += 1
        self.last_observed = datetime.utcnow()
        if self.occurrence_count > 5:
            self.frequency_trend = "increasing"
        total_success = int(self.resolution_success_rate * (self.occurrence_count - 1) / 100) + (1 if success else 0)
        self.resolution_success_rate = (total_success / self.occurrence_count) * 100
        self.average_impact_score = ((self.average_impact_score * (self.occurrence_count - 1)) + impact_score) / self.occurrence_count

    def get_effectiveness_score(self) -> float:
        if not self.occurrence_count:
            return 0.0
        return (self.average_impact_score * 0.4 + self.resolution_success_rate * 0.6) / 100

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictImpact(BaseModel):
    """Impact scoring for conflicts."""

    impact_id: str
    conflict_id: str
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_multiplier: float = Field(default=1.0, ge=0.5, le=3.0)

    affected_users: int = 0
    affected_rules_count: int = 0
    affected_domains: List[str] = Field(default_factory=list)
    affected_processes: List[str] = Field(default_factory=list)

    performance_impact_ms: int = 0
    accuracy_impact: float = Field(default=0.0, ge=-1.0, le=1.0)
    user_experience_impact: float = Field(default=0.0, ge=0.0, le=1.0)
    business_impact: float = Field(default=0.0, ge=0.0, le=1.0)
    security_impact: float = Field(default=0.0, ge=0.0, le=1.0)
    compliance_impact: float = Field(default=0.0, ge=0.0, le=1.0)

    cascading_risk: bool = False
    downstream_effects: List[str] = Field(default_factory=list)
    estimated_recovery_time_minutes: int = 0

    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    assessed_by: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def calculate_weighted_score(self) -> float:
        raw = (
            self.user_experience_impact * 0.15 +
            self.business_impact * 0.25 +
            self.security_impact * 0.30 +
            self.compliance_impact * 0.20 +
            self.accuracy_impact * 0.10
        )
        return min(raw * self.severity_multiplier, 1.0)

    def requires_immediate_action(self) -> bool:
        return (
            self.calculate_weighted_score() > 0.7 or
            self.security_impact > 0.8 or
            self.compliance_impact > 0.8 or
            self.cascading_risk
        )

    def get_top_impact_area(self) -> str:
        impacts = {
            "security": self.security_impact,
            "compliance": self.compliance_impact,
            "business": self.business_impact,
            "user_experience": self.user_experience_impact,
            "accuracy": self.accuracy_impact
        }
        return max(impacts, key=impacts.get)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "impact_id": self.impact_id,
            "conflict_id": self.conflict_id,
            "impact_score": round(self.impact_score, 3),
            "weighted_score": round(self.calculate_weighted_score(), 3),
            "top_impact_area": self.get_top_impact_area(),
            "requires_immediate_action": self.requires_immediate_action(),
            "affected_users": self.affected_users,
            "cascading_risk": self.cascading_risk,
            "estimated_recovery_minutes": self.estimated_recovery_time_minutes
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictNotification(BaseModel):
    """Notification configs for conflict events."""

    notification_id: str
    conflict_id: str
    notification_type: str = "email"
    recipients: List[str] = Field(default_factory=list)
    cc_recipients: List[str] = Field(default_factory=list)
    bcc_recipients: List[str] = Field(default_factory=list)
    subject: str
    message_template: str
    priority: str = "normal"
    is_pending: bool = True
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = Field(default=3, ge=0, le=10)

    include_conflict_details: bool = True
    include_resolution: bool = True
    include_impact: bool = False
    escalation_path: List[str] = Field(default_factory=list)
    require_acknowledgment: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def render_message(self, conflict: RuleConflict, resolution: Optional[ConflictResolution] = None,
                       impact: Optional[ConflictImpact] = None) -> str:
        msg = self.message_template
        msg = msg.replace("{{conflict_id}}", conflict.conflict_id)
        msg = msg.replace("{{conflict_type}}", conflict.conflict_type.value)
        msg = msg.replace("{{conflict_severity}}", conflict.severity.value)
        msg = msg.replace("{{rule_1_name}}", conflict.rule_1.name)
        msg = msg.replace("{{rule_2_name}}", conflict.rule_2.name)
        msg = msg.replace("{{description}}", conflict.description)
        if resolution:
            msg = msg.replace("{{resolution_strategy}}", resolution.strategy.value)
            msg = msg.replace("{{resolution_outcome}}", resolution.outcome)
        if impact:
            msg = msg.replace("{{impact_score}}", str(round(impact.impact_score, 2)))
        return msg

    def mark_sent(self) -> None:
        self.is_pending = False
        self.sent_at = datetime.utcnow()

    def mark_read(self) -> None:
        self.read_at = datetime.utcnow()

    def increment_retry(self) -> bool:
        self.retry_count += 1
        return self.retry_count <= self.max_retries

    def is_expired(self) -> bool:
        if not self.sent_at:
            return False
        expiry = timedelta(days=7)
        return datetime.utcnow() - self.sent_at > expiry

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictAudit(BaseModel):
    """Audit trail for conflict resolution."""

    audit_id: str
    conflict_id: str
    action: str
    actor: str
    actor_type: str = "system"

    previous_state: Optional[Dict[str, Any]] = None
    new_state: Optional[Dict[str, Any]] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)

    reasoning: Optional[str] = None
    justification: Optional[str] = None
    outcome: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None

    related_audit_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def record_change(self, field: str, old_value: Any, new_value: Any, reason: Optional[str] = None) -> None:
        self.changes.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_change_summary(self) -> str:
        if not self.changes:
            return "No changes recorded"
        changed_fields = [c["field"] for c in self.changes]
        return f"Changed {len(self.changes)} field(s): {', '.join(changed_fields)}"

    def link_audit(self, audit_id: str) -> None:
        if audit_id not in self.related_audit_ids:
            self.related_audit_ids.append(audit_id)

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConflictPreventionRule(BaseModel):
    """Rules to prevent known conflicts."""

    prevention_id: str
    name: str
    description: str
    conflict_type: ConflictType
    priority: int = Field(default=500, ge=1, le=1000)

    source_rule_patterns: List[str] = Field(default_factory=list)
    target_rule_patterns: List[str] = Field(default_factory=list)
    forbidden_combinations: List[List[str]] = Field(default_factory=list)
    allowed_combinations: List[List[str]] = Field(default_factory=list)

    precondition: Optional[str] = None
    action_on_detection: str = "warn"
    auto_prevent: bool = True
    is_active: bool = True

    effectiveness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    times_applied: int = 0
    prevented_conflicts_count: int = 0
    false_positive_count: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def would_prevent(self, rule_1: Rule, rule_2: Rule) -> Tuple[bool, Optional[str]]:
        if not self.is_active:
            return False, None
        r1_type = rule_1.rule_type.value
        r2_type = rule_2.rule_type.value
        if self.forbidden_combinations:
            for combo in self.forbidden_combinations:
                if r1_type in combo and r2_type in combo:
                    return True, f"Forbidden combination: {r1_type} + {r2_type}"
        if self.allowed_combinations:
            for combo in self.allowed_combinations:
                if r1_type in combo and r2_type in combo:
                    return False, None
            return True, f"Not in allowed combinations: {r1_type} + {r2_type}"
        return False, None

    def check_precondition(self, context: Dict[str, Any]) -> bool:
        if not self.precondition:
            return True
        import re
        parts = self.precondition.split()
        if len(parts) >= 3:
            var = parts[0]
            op = parts[1]
            val = " ".join(parts[2:])
            actual = str(context.get(var, ""))
            if op == "==":
                return actual == val
            elif op == "!=":
                return actual != val
            elif op == "in":
                return val in actual
            elif op == "not in":
                return val not in actual
        return True

    def record_application(self, prevented: bool = True) -> None:
        self.times_applied += 1
        if prevented:
            self.prevented_conflicts_count += 1
        else:
            self.false_positive_count += 1
        total = self.prevented_conflicts_count + self.false_positive_count
        self.effectiveness_score = self.prevented_conflicts_count / total if total > 0 else 0.0
        self.updated_at = datetime.utcnow()

    def get_accuracy(self) -> float:
        total = self.prevented_conflicts_count + self.false_positive_count
        if total == 0:
            return 0.0
        return self.prevented_conflicts_count / total

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }