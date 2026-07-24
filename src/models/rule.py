"""
Core data models for the Rules-Emerging-Pattern system.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field, validator, root_validator

logger = logging.getLogger(__name__)


class RuleTier(str, Enum):
    """Rule tier levels in the three-tier architecture."""
    SAFETY = "safety"
    OPERATIONAL = "operational"
    PREFERENCE = "preference"


class EnforcementLevel(str, Enum):
    """Levels of rule enforcement."""
    STRICT = "strict"
    ADVISORY = "advisory"
    ADAPTIVE = "adaptive"
    FALLBACK = "fallback"


class RuleType(str, Enum):
    """Types of rules in the system."""
    CONTENT_FILTERING = "content_filtering"
    PATTERN_MATCHING = "pattern_matching"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    STRUCTURAL_VALIDATION = "structural_validation"
    COMPLIANCE_CHECK = "compliance_check"
    QUALITY_ASSESSMENT = "quality_assessment"
    CUSTOM = "custom"


class RuleSeverity(str, Enum):
    """Severity levels for rule violations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleStatus(str, Enum):
    """Status of a rule in the system."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    TESTING = "testing"


class RulePattern(BaseModel):
    """Pattern definition for rule matching."""
    type: RuleType
    keywords: List[str] = Field(default_factory=list)
    regex_patterns: List[str] = Field(default_factory=list)
    ml_model: Optional[str] = None
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    action: str = Field(default="warn")

    class Config:
        use_enum_values = True


class Rule(BaseModel):
    """Core rule definition."""

    id: str
    name: str
    description: str
    tier: RuleTier
    rule_type: RuleType
    severity: RuleSeverity
    status: RuleStatus = RuleStatus.ACTIVE

    patterns: List[RulePattern] = Field(default_factory=list)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    exceptions: List[str] = Field(default_factory=list)

    enforcement_level: EnforcementLevel
    auto_block: bool = False
    user_override: bool = True
    override_justification_required: bool = False

    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    priority: int = Field(default=100, ge=1, le=1000)
    timeout_ms: int = Field(default=1000, ge=1, le=10000)
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)

    @validator('id')
    def validate_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Rule ID cannot be empty")
        return v.strip()

    def get_content_hash(self) -> str:
        content = f"{self.name}:{self.description}:{self.tier}:{self.version}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def is_applicable_to_context(self, context: Dict[str, Any]) -> bool:
        if not context:
            return True
        if 'domain' in context:
            rule_domains = [tag for tag in self.tags if tag.startswith('domain:')]
            if rule_domains and not any(tag.split(':', 1)[1] == context['domain'] for tag in rule_domains):
                return False
        if 'user_role' in context:
            rule_roles = [tag for tag in self.tags if tag.startswith('role:')]
            if rule_roles and not any(tag.split(':', 1)[1] in context['user_role'] for tag in rule_roles):
                return False
        return True

    def matches_exception(self, content: str) -> bool:
        for exception in self.exceptions:
            if exception in content or hashlib.md5(exception.encode()).hexdigest() == hashlib.md5(content.encode()).hexdigest():
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    def is_deprecated(self) -> bool:
        return self.status == RuleStatus.DEPRECATED

    def is_testing(self) -> bool:
        return self.status == RuleStatus.TESTING

    def is_active(self) -> bool:
        return self.status == RuleStatus.ACTIVE

    def activate(self) -> None:
        self.status = RuleStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.status = RuleStatus.INACTIVE
        self.updated_at = datetime.utcnow()

    def get_tags_by_prefix(self, prefix: str) -> List[str]:
        return [tag for tag in self.tags if tag.startswith(prefix)]

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def add_tag(self, tag: str) -> None:
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.utcnow()

    def remove_tag(self, tag: str) -> bool:
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.utcnow()
            return True
        return False

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleSet(BaseModel):
    """Collection of related rules."""

    id: str
    name: str
    description: str
    rules: List[Rule] = Field(default_factory=list)
    tier: RuleTier
    status: RuleStatus = RuleStatus.ACTIVE

    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None

    auto_discovery: bool = True
    conflict_resolution: str = "priority_based"
    evaluation_order: str = "priority_desc"

    def add_rule(self, rule: Rule) -> None:
        if rule not in self.rules:
            self.rules.append(rule)
            self.updated_at = datetime.utcnow()

    def remove_rule(self, rule_id: str) -> bool:
        original_count = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.id != rule_id]
        if len(self.rules) < original_count:
            self.updated_at = datetime.utcnow()
            return True
        return False

    def get_rule_by_id(self, rule_id: str) -> Optional[Rule]:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def get_rules_by_type(self, rule_type: RuleType) -> List[Rule]:
        return [rule for rule in self.rules if rule.rule_type == rule_type]

    def get_active_rules(self) -> List[Rule]:
        return [rule for rule in self.rules if rule.status == RuleStatus.ACTIVE]

    def get_rules_by_priority(self, ascending: bool = False) -> List[Rule]:
        return sorted(self.rules, key=lambda r: r.priority, reverse=not ascending)

    def get_rules_by_severity(self, severity: RuleSeverity) -> List[Rule]:
        return [rule for rule in self.rules if rule.severity == severity]

    def get_rules_by_enforcement(self, level: EnforcementLevel) -> List[Rule]:
        return [rule for rule in self.rules if rule.enforcement_level == level]

    def get_rule_count(self) -> int:
        return len(self.rules)

    def get_active_rule_count(self) -> int:
        return len(self.get_active_rules())

    def has_rule(self, rule_id: str) -> bool:
        return any(rule.id == rule_id for rule in self.rules)

    def merge_ruleset(self, other: 'RuleSet') -> int:
        added = 0
        for rule in other.rules:
            if not self.has_rule(rule.id):
                self.rules.append(rule)
                added += 1
        if added > 0:
            self.updated_at = datetime.utcnow()
        return added

    def sort_rules(self, key: str = "priority", reverse: bool = False) -> None:
        self.rules = sorted(self.rules, key=lambda r: getattr(r, key, 0), reverse=reverse)
        self.updated_at = datetime.utcnow()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleContext(BaseModel):
    """Context information for rule evaluation."""

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    domain: Optional[str] = None
    user_role: Optional[str] = None

    content_type: Optional[str] = None
    content_length: Optional[int] = None
    language: Optional[str] = None

    organization: Optional[str] = None
    project: Optional[str] = None
    business_process: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    time_zone: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_effective_context(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "domain": self.domain,
            "user_role": self.user_role,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "language": self.language,
            "organization": self.organization,
            "project": self.project,
            "business_process": self.business_process,
            "timestamp": self.timestamp,
            "time_zone": self.time_zone,
            **self.metadata
        }

    def merge(self, other: 'RuleContext') -> 'RuleContext':
        merged = self.copy(deep=True)
        if other.user_id:
            merged.user_id = other.user_id
        if other.session_id:
            merged.session_id = other.session_id
        if other.domain:
            merged.domain = other.domain
        if other.user_role:
            merged.user_role = other.user_role
        if other.content_type:
            merged.content_type = other.content_type
        if other.language:
            merged.language = other.language
        if other.organization:
            merged.organization = other.organization
        if other.project:
            merged.project = other.project
        if other.business_process:
            merged.business_process = other.business_process
        if other.time_zone:
            merged.time_zone = other.time_zone
        merged.metadata.update(other.metadata)
        return merged

    def is_empty(self) -> bool:
        return all(
            getattr(self, field) is None
            for field in ['user_id', 'session_id', 'domain', 'user_role',
                          'content_type', 'content_length', 'language',
                          'organization', 'project', 'business_process', 'time_zone']
        ) and not self.metadata

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleEvaluationRequest(BaseModel):
    """Request for rule evaluation."""

    content: str
    context: Optional[RuleContext] = None
    rule_ids: Optional[List[str]] = None
    tier: Optional[RuleTier] = None
    rule_types: Optional[List[RuleType]] = None
    options: Dict[str, Any] = Field(default_factory=dict)

    timeout_ms: int = Field(default=1000, ge=1, le=10000)
    parallel_evaluation: bool = True
    early_termination: bool = True

    def get_context(self) -> RuleContext:
        return self.context or RuleContext()

    def should_evaluate_rule(self, rule: Rule) -> bool:
        if self.rule_ids and rule.id not in self.rule_ids:
            return False
        if self.tier and rule.tier != self.tier:
            return False
        if self.rule_types and rule.rule_type not in self.rule_types:
            return False
        return True

    def with_content(self, content: str) -> 'RuleEvaluationRequest':
        return RuleEvaluationRequest(
            content=content,
            context=self.context,
            rule_ids=self.rule_ids,
            tier=self.tier,
            rule_types=self.rule_types,
            options=self.options,
            timeout_ms=self.timeout_ms,
            parallel_evaluation=self.parallel_evaluation,
            early_termination=self.early_termination
        )

    class Config:
        use_enum_values = True


class RuleTemplate(BaseModel):
    """Template for creating rules with variable substitution."""

    template_id: str
    name: str
    description: str
    template_content: str
    variables: Dict[str, str] = Field(default_factory=dict)
    default_values: Dict[str, str] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    rule_type: RuleType
    tier: RuleTier
    severity: RuleSeverity
    enforcement_level: EnforcementLevel
    category: str = "general"
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    usage_count: int = 0
    is_deprecated: bool = False

    @validator('template_id')
    def validate_template_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Template ID cannot be empty")
        return v.strip()

    def get_required_variables(self) -> List[str]:
        import re
        return list(set(re.findall(r'\{\{(\w+)\}\}', self.template_content)))

    def get_missing_variables(self, provided: Dict[str, str]) -> List[str]:
        required = self.get_required_variables()
        return [v for v in required if v not in provided and v not in self.default_values]

    def validate_variables(self, variables: Dict[str, str]) -> Tuple[bool, List[str]]:
        errors = []
        for key, value in variables.items():
            if key in self.constraints:
                constraint = self.constraints[key]
                if 'max_length' in constraint and len(value) > constraint['max_length']:
                    errors.append(f"Variable '{key}' exceeds max length of {constraint['max_length']}")
                if 'pattern' in constraint:
                    import re
                    if not re.match(constraint['pattern'], value):
                        errors.append(f"Variable '{key}' does not match pattern {constraint['pattern']}")
        return len(errors) == 0, errors

    def instantiate(self, variables: Dict[str, str], rule_id: Optional[str] = None) -> Rule:
        merged_vars = {**self.default_values, **variables}
        missing = self.get_missing_variables(merged_vars)
        if missing:
            raise ValueError(f"Missing required variables: {missing}")

        valid, errors = self.validate_variables(merged_vars)
        if not valid:
            raise ValueError(f"Variable validation failed: {errors}")

        content = self.template_content
        for key, value in merged_vars.items():
            content = content.replace(f"{{{{{key}}}}}", value)

        return Rule(
            id=rule_id or f"rule_template_{self.template_id}_{datetime.utcnow().timestamp()}",
            name=merged_vars.get('rule_name', f"Rule from {self.name}"),
            description=merged_vars.get('description', self.description),
            tier=self.tier,
            rule_type=self.rule_type,
            severity=self.severity,
            enforcement_level=self.enforcement_level,
            conditions={"template_content": content},
            tags=self.tags.copy(),
            created_by=self.created_by
        )

    def increment_usage(self) -> None:
        self.usage_count += 1
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleGroup(BaseModel):
    """Grouping of rules with metadata."""

    group_id: str
    name: str
    description: str
    rule_ids: List[str] = Field(default_factory=list)
    rules: List[Rule] = Field(default_factory=list)
    parent_group_id: Optional[str] = None
    child_group_ids: List[str] = Field(default_factory=list)
    group_type: str = "custom"
    category: str = "general"
    priority: int = Field(default=500, ge=1, le=1000)
    is_system_group: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def add_rule_by_id(self, rule_id: str) -> None:
        if rule_id not in self.rule_ids:
            self.rule_ids.append(rule_id)
            self.updated_at = datetime.utcnow()

    def add_rule(self, rule: Rule) -> None:
        if rule not in self.rules:
            self.rules.append(rule)
            self.updated_at = datetime.utcnow()

    def remove_rule_by_id(self, rule_id: str) -> bool:
        if rule_id in self.rule_ids:
            self.rule_ids.remove(rule_id)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def remove_rule(self, rule_id: str) -> bool:
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        if len(self.rules) < original_count:
            self.updated_at = datetime.utcnow()
            return True
        return False

    def get_all_rule_ids(self) -> List[str]:
        ids = set(self.rule_ids)
        ids.update(r.id for r in self.rules)
        return list(ids)

    def has_rule(self, rule_id: str) -> bool:
        return rule_id in self.rule_ids or any(r.id == rule_id for r in self.rules)

    def add_child_group(self, group_id: str) -> None:
        if group_id not in self.child_group_ids:
            self.child_group_ids.append(group_id)
            self.updated_at = datetime.utcnow()

    def remove_child_group(self, group_id: str) -> bool:
        if group_id in self.child_group_ids:
            self.child_group_ids.remove(group_id)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def get_rule_count(self) -> int:
        return len(self.rule_ids) + len(self.rules)

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleSchedule(BaseModel):
    """Time-based rule activation schedules."""

    schedule_id: str
    rule_id: str
    name: str
    description: Optional[str] = None

    schedule_type: str = "recurring"
    cron_expression: Optional[str] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None

    days_of_week: List[int] = Field(default_factory=list)
    days_of_month: List[int] = Field(default_factory=list)
    months: List[int] = Field(default_factory=list)
    time_of_day_start: Optional[str] = None
    time_of_day_end: Optional[str] = None

    timezone: str = "UTC"
    is_active: bool = True
    is_recurring: bool = True
    max_activations: Optional[int] = None
    activation_count: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_due_now(self, reference_time: Optional[datetime] = None) -> bool:
        now = reference_time or datetime.utcnow()
        if not self.is_active:
            return False
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        if self.max_activations and self.activation_count >= self.max_activations:
            return False
        if self.days_of_week and now.weekday() not in self.days_of_week:
            return False
        if self.days_of_month and now.day not in self.days_of_month:
            return False
        if self.months and now.month not in self.months:
            return False
        if self.duration_minutes and self.start_time:
            elapsed = (now - self.start_time).total_seconds() / 60
            if elapsed > self.duration_minutes:
                return False
        return True

    def get_next_activation(self, from_time: Optional[datetime] = None) -> Optional[datetime]:
        if not self.is_active or not self.is_recurring:
            return None
        if self.max_activations and self.activation_count >= self.max_activations:
            return None
        start = from_time or datetime.utcnow()
        if self.start_time and start < self.start_time:
            start = self.start_time
        return start

    def record_activation(self) -> None:
        self.activation_count += 1
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def is_expired(self) -> bool:
        if self.end_time and datetime.utcnow() > self.end_time:
            return True
        if self.max_activations and self.activation_count >= self.max_activations:
            return True
        return False

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleDependency(BaseModel):
    """Dependencies between rules."""

    dependency_id: str
    source_rule_id: str
    target_rule_id: str
    dependency_type: str = "requires"
    condition: Optional[str] = None
    description: Optional[str] = None

    is_optional: bool = False
    is_circular: bool = False
    is_hard_dependency: bool = True
    priority: int = Field(default=500, ge=1, le=1000)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_key(self) -> str:
        return f"{self.source_rule_id}:{self.target_rule_id}:{self.dependency_type}"

    def is_satisfied(self, context: Dict[str, Any]) -> bool:
        if self.is_optional:
            return True
        if self.condition:
            import re
            parts = self.condition.split()
            if len(parts) == 3:
                var, op, val = parts
                actual = context.get(var)
                if op == "==":
                    return str(actual) == val
                elif op == "!=":
                    return str(actual) != val
                elif op == ">":
                    return float(actual) > float(val)
                elif op == "<":
                    return float(actual) < float(val)
                elif op == ">=":
                    return float(actual) >= float(val)
                elif op == "<=":
                    return float(actual) <= float(val)
                elif op == "in":
                    return actual in val.split(",")
        return True

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleStats(BaseModel):
    """Statistical tracking for a rule."""

    rule_id: str

    evaluation_count: int = 0
    violation_count: int = 0
    override_count: int = 0
    block_count: int = 0
    suggestion_count: int = 0
    escalation_count: int = 0

    total_processing_time_ms: int = 0
    average_processing_time_ms: float = 0.0
    min_processing_time_ms: int = 0
    max_processing_time_ms: int = 0

    last_evaluated_at: Optional[datetime] = None
    first_evaluated_at: Optional[datetime] = None

    violation_rate: float = 0.0
    override_rate: float = 0.0
    block_rate: float = 0.0

    daily_counts: Dict[str, int] = Field(default_factory=dict)
    weekly_counts: Dict[str, int] = Field(default_factory=dict)
    monthly_counts: Dict[str, int] = Field(default_factory=dict)

    violation_types: Dict[str, int] = Field(default_factory=dict)
    top_contexts: List[Dict[str, Any]] = Field(default_factory=list)
    peak_hours: Dict[int, int] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def record_evaluation(self, processing_time_ms: int, violated: bool = False, blocked: bool = False,
                          overridden: bool = False, suggested: bool = False,
                          escalated: bool = False, violation_type: Optional[str] = None) -> None:
        self.evaluation_count += 1
        self.total_processing_time_ms += processing_time_ms
        self.average_processing_time_ms = self.total_processing_time_ms / self.evaluation_count

        if self.min_processing_time_ms == 0 or processing_time_ms < self.min_processing_time_ms:
            self.min_processing_time_ms = processing_time_ms
        if processing_time_ms > self.max_processing_time_ms:
            self.max_processing_time_ms = processing_time_ms

        now = datetime.utcnow()
        self.last_evaluated_at = now
        if self.first_evaluated_at is None:
            self.first_evaluated_at = now

        if violated:
            self.violation_count += 1
            hour_key = now.hour
            self.peak_hours[hour_key] = self.peak_hours.get(hour_key, 0) + 1
            if violation_type:
                self.violation_types[violation_type] = self.violation_types.get(violation_type, 0) + 1

        if blocked:
            self.block_count += 1
        if overridden:
            self.override_count += 1
        if suggested:
            self.suggestion_count += 1
        if escalated:
            self.escalation_count += 1

        date_key = now.strftime("%Y-%m-%d")
        self.daily_counts[date_key] = self.daily_counts.get(date_key, 0) + 1

        week_key = now.strftime("%Y-W%W")
        self.weekly_counts[week_key] = self.weekly_counts.get(week_key, 0) + 1

        month_key = now.strftime("%Y-%m")
        self.monthly_counts[month_key] = self.monthly_counts.get(month_key, 0) + 1

        self.violation_rate = (self.violation_count / self.evaluation_count * 100) if self.evaluation_count > 0 else 0.0
        self.override_rate = (self.override_count / self.evaluation_count * 100) if self.evaluation_count > 0 else 0.0
        self.block_rate = (self.block_count / self.evaluation_count * 100) if self.evaluation_count > 0 else 0.0

        self.updated_at = now

    def get_violation_trend(self, window_days: int = 7) -> float:
        recent = sum(
            count for date_key, count in self.daily_counts.items()
            if date_key >= (datetime.utcnow() - timedelta(days=window_days)).strftime("%Y-%m-%d")
        )
        prior = sum(
            count for date_key, count in self.daily_counts.items()
            if date_key < (datetime.utcnow() - timedelta(days=window_days)).strftime("%Y-%m-%d")
            and date_key >= (datetime.utcnow() - timedelta(days=window_days * 2)).strftime("%Y-%m-%d")
        )
        if prior == 0:
            return float(recent > 0)
        return (recent - prior) / prior

    def get_peak_hour(self) -> Optional[int]:
        if not self.peak_hours:
            return None
        return max(self.peak_hours, key=self.peak_hours.get)

    def reset(self) -> None:
        self.evaluation_count = 0
        self.violation_count = 0
        self.override_count = 0
        self.block_count = 0
        self.suggestion_count = 0
        self.escalation_count = 0
        self.total_processing_time_ms = 0
        self.average_processing_time_ms = 0.0
        self.min_processing_time_ms = 0
        self.max_processing_time_ms = 0
        self.last_evaluated_at = None
        self.violation_rate = 0.0
        self.override_rate = 0.0
        self.block_rate = 0.0
        self.daily_counts = {}
        self.weekly_counts = {}
        self.monthly_counts = {}
        self.violation_types = {}
        self.top_contexts = []
        self.peak_hours = {}
        self.updated_at = datetime.utcnow()

    def to_summary(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "evaluation_count": self.evaluation_count,
            "violation_count": self.violation_count,
            "override_count": self.override_count,
            "block_count": self.block_count,
            "violation_rate": round(self.violation_rate, 2),
            "override_rate": round(self.override_rate, 2),
            "block_rate": round(self.block_rate, 2),
            "avg_processing_ms": round(self.average_processing_time_ms, 2),
            "peak_hour": self.get_peak_hour(),
            "last_evaluated": self.last_evaluated_at.isoformat() if self.last_evaluated_at else None
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }