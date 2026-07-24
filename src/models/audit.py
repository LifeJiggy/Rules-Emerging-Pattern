"""
Audit event and trail models for the Rules-Emerging-Pattern system.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field, validator, root_validator

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Actions that can be audited."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    EVALUATE = "evaluate"
    RESOLVE = "resolve"
    ESCALATE = "escalate"
    OVERRIDE = "override"
    EXPORT = "export"
    IMPORT = "import"
    CONFIGURE = "configure"
    VALIDATE = "validate"
    APPROVE = "approve"
    REJECT = "reject"
    SYSTEM = "system"


class AuditCategory(str, Enum):
    """Categories for audit events."""
    RULE = "rule"
    CONFLICT = "conflict"
    VIOLATION = "violation"
    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    SYSTEM = "system"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    USER = "user"


class AuditSeverity(str, Enum):
    """Severity for audit events."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEvent(BaseModel):
    """Base audit event."""

    event_id: str
    event_type: str
    category: AuditCategory
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO

    actor: str
    actor_type: str = "user"
    actor_id: Optional[str] = None

    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None

    summary: str
    description: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    previous_value: Optional[Any] = None
    new_value: Optional[Any] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)

    outcome: str = "success"
    reason: Optional[str] = None
    error_message: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    source: str = "system"
    environment: Optional[str] = None
    host: Optional[str] = None
    service: Optional[str] = None

    related_event_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator('event_id')
    def validate_event_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Event ID cannot be empty")
        return v.strip()

    def record_change(self, field: str, old_value: Any, new_value: Any) -> None:
        self.changes.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_change_count(self) -> int:
        return len(self.changes)

    def get_duration_ms(self, other_event: Optional['AuditEvent'] = None) -> Optional[float]:
        if other_event:
            return (other_event.timestamp - self.timestamp).total_seconds() * 1000
        return None

    def link_event(self, event_id: str) -> None:
        if event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)

    def is_success(self) -> bool:
        return self.outcome == "success"

    def is_failure(self) -> bool:
        return self.outcome == "failure"

    def to_summary(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category.value,
            "action": self.action.value,
            "severity": self.severity.value,
            "actor": self.actor,
            "resource": f"{self.resource_type}/{self.resource_id}" if self.resource_type else None,
            "summary": self.summary,
            "outcome": self.outcome,
            "timestamp": self.timestamp.isoformat(),
            "change_count": self.get_change_count()
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleAuditEvent(BaseModel):
    """Rule-specific audit events."""

    event_id: str
    rule_id: str
    rule_name: str
    rule_tier: Optional[str] = None
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO

    actor: str
    actor_type: str = "user"
    actor_id: Optional[str] = None

    summary: str
    description: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    previous_rule_state: Optional[Dict[str, Any]] = None
    new_rule_state: Optional[Dict[str, Any]] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)
    changed_fields: List[str] = Field(default_factory=list)

    outcome: str = "success"
    reason: Optional[str] = None
    error_message: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    related_event_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def record_change(self, field: str, old_value: Any, new_value: Any) -> None:
        self.changes.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.utcnow().isoformat()
        })
        if field not in self.changed_fields:
            self.changed_fields.append(field)

    def get_change_summary(self) -> str:
        if not self.changed_fields:
            return "No changes recorded"
        return f"Changed {len(self.changed_fields)} field(s): {', '.join(self.changed_fields)}"

    def is_state_change(self) -> bool:
        return self.action in (AuditAction.UPDATE, AuditAction.ACTIVATE, AuditAction.DEACTIVATE, AuditAction.CONFIGURE)

    def link_event(self, event_id: str) -> None:
        if event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "action": self.action.value,
            "actor": self.actor,
            "summary": self.summary,
            "outcome": self.outcome,
            "changed_fields": self.changed_fields,
            "timestamp": self.timestamp.isoformat()
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ViolationAuditEvent(BaseModel):
    """Violation audit trail."""

    event_id: str
    violation_id: str
    rule_id: str
    rule_name: str
    violation_type: str
    severity: str

    actor: str = "system"
    actor_type: str = "system"
    action: AuditAction = AuditAction.EVALUATE

    matched_content_preview: Optional[str] = None
    matched_patterns: List[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)

    action_taken: Optional[str] = None
    was_blocked: bool = False
    was_overridden: bool = False
    override_justification: Optional[str] = None
    overridden_by: Optional[str] = None

    original_content_hash: Optional[str] = None
    content_context: Dict[str, Any] = Field(default_factory=dict)

    summary: str
    description: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    outcome: str = "success"
    reason: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    related_event_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_blocked(self) -> bool:
        return self.was_blocked

    def is_overridden(self) -> bool:
        return self.was_overridden

    def record_override(self, user: str, justification: str) -> None:
        self.was_overridden = True
        self.overridden_by = user
        self.override_justification = justification
        self.action = AuditAction.OVERRIDE
        self.changes.append({
            "field": "action_taken",
            "old_value": self.action_taken,
            "new_value": "overridden",
            "timestamp": datetime.utcnow().isoformat()
        })

    changes: List[Dict[str, Any]] = Field(default_factory=list)

    def get_content_preview(self, max_length: int = 200) -> Optional[str]:
        if self.matched_content_preview and len(self.matched_content_preview) > max_length:
            return self.matched_content_preview[:max_length] + "..."
        return self.matched_content_preview

    def link_event(self, event_id: str) -> None:
        if event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "violation_id": self.violation_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "violation_type": self.violation_type,
            "action_taken": self.action_taken,
            "was_blocked": self.was_blocked,
            "was_overridden": self.was_overridden,
            "timestamp": self.timestamp.isoformat()
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConfigAuditEvent(BaseModel):
    """Configuration change audit."""

    event_id: str
    config_section: str
    config_key: str
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO

    actor: str
    actor_type: str = "user"
    actor_id: Optional[str] = None

    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    value_type: Optional[str] = None
    config_version: Optional[str] = None
    previous_config_version: Optional[str] = None

    summary: str
    description: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    changes: List[Dict[str, Any]] = Field(default_factory=list)

    is_rollback: bool = False
    is_restore: bool = False
    is_breaking_change: bool = False
    requires_restart: bool = False

    outcome: str = "success"
    reason: Optional[str] = None
    error_message: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    related_event_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_value_changed(self) -> bool:
        return str(self.old_value) != str(self.new_value)

    def get_diff(self) -> Dict[str, Any]:
        return {
            "config_section": self.config_section,
            "config_key": self.config_key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "is_breaking_change": self.is_breaking_change,
            "requires_restart": self.requires_restart
        }

    def record_change(self, field: str, old_value: Any, new_value: Any) -> None:
        self.changes.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.utcnow().isoformat()
        })

    def link_event(self, event_id: str) -> None:
        if event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "config_section": self.config_section,
            "config_key": self.config_key,
            "action": self.action.value,
            "actor": self.actor,
            "value_changed": self.is_value_changed(),
            "is_breaking_change": self.is_breaking_change,
            "requires_restart": self.requires_restart,
            "outcome": self.outcome,
            "timestamp": self.timestamp.isoformat()
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AuditTrail(BaseModel):
    """Complete audit trail."""

    trail_id: str
    name: str
    description: Optional[str] = None
    trail_type: str = "continuous"

    events: List[AuditEvent] = Field(default_factory=list)
    rule_events: List[RuleAuditEvent] = Field(default_factory=list)
    violation_events: List[ViolationAuditEvent] = Field(default_factory=list)
    config_events: List[ConfigAuditEvent] = Field(default_factory=list)

    event_count: int = 0
    unique_actors: Set[str] = set()
    unique_resources: Set[str] = set()
    categories: Dict[str, int] = Field(default_factory=dict)
    actions: Dict[str, int] = Field(default_factory=dict)

    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    is_active: bool = True
    is_immutable: bool = False
    retention_days: int = Field(default=90, ge=1, le=3650)
    size_bytes: int = 0

    source: str = "system"
    environment: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_event(self, event: AuditEvent) -> None:
        self.events.append(event)
        self.event_count += 1
        self.unique_actors.add(event.actor)
        if event.resource_id:
            self.unique_resources.add(f"{event.resource_type}/{event.resource_id}")
        cat_key = event.category.value
        self.categories[cat_key] = self.categories.get(cat_key, 0) + 1
        act_key = event.action.value
        self.actions[act_key] = self.actions.get(act_key, 0) + 1
        if self.period_start is None or event.timestamp < self.period_start:
            self.period_start = event.timestamp
        if self.period_end is None or event.timestamp > self.period_end:
            self.period_end = event.timestamp
        self.updated_at = datetime.utcnow()

    def add_rule_event(self, event: RuleAuditEvent) -> None:
        self.rule_events.append(event)
        self.event_count += 1
        self.unique_actors.add(event.actor)
        self.unique_resources.add(f"rule/{event.rule_id}")
        cat_key = AuditCategory.RULE.value
        self.categories[cat_key] = self.categories.get(cat_key, 0) + 1
        act_key = event.action.value
        self.actions[act_key] = self.actions.get(act_key, 0) + 1
        if self.period_start is None or event.timestamp < self.period_start:
            self.period_start = event.timestamp
        if self.period_end is None or event.timestamp > self.period_end:
            self.period_end = event.timestamp
        self.updated_at = datetime.utcnow()

    def add_violation_event(self, event: ViolationAuditEvent) -> None:
        self.violation_events.append(event)
        self.event_count += 1
        self.unique_actors.add(event.actor)
        self.unique_resources.add(f"violation/{event.violation_id}")
        cat_key = AuditCategory.VIOLATION.value
        self.categories[cat_key] = self.categories.get(cat_key, 0) + 1
        act_key = event.action.value
        self.actions[act_key] = self.actions.get(act_key, 0) + 1
        if self.period_start is None or event.timestamp < self.period_start:
            self.period_start = event.timestamp
        if self.period_end is None or event.timestamp > self.period_end:
            self.period_end = event.timestamp
        self.updated_at = datetime.utcnow()

    def add_config_event(self, event: ConfigAuditEvent) -> None:
        self.config_events.append(event)
        self.event_count += 1
        self.unique_actors.add(event.actor)
        self.unique_resources.add(f"config/{event.config_section}/{event.config_key}")
        cat_key = AuditCategory.CONFIGURATION.value
        self.categories[cat_key] = self.categories.get(cat_key, 0) + 1
        act_key = event.action.value
        self.actions[act_key] = self.actions.get(act_key, 0) + 1
        if self.period_start is None or event.timestamp < self.period_start:
            self.period_start = event.timestamp
        if self.period_end is None or event.timestamp > event.timestamp:
            self.period_end = event.timestamp
        self.updated_at = datetime.utcnow()

    def get_events_by_category(self, category: AuditCategory) -> List[AuditEvent]:
        return [e for e in self.events if e.category == category]

    def get_events_by_action(self, action: AuditAction) -> List[AuditEvent]:
        return [e for e in self.events if e.action == action]

    def get_events_by_actor(self, actor: str) -> List[AuditEvent]:
        return [e for e in self.events if e.actor == actor]

    def get_events_by_severity(self, severity: AuditSeverity) -> List[AuditEvent]:
        return [e for e in self.events if e.severity == severity]

    def get_events_by_resource(self, resource_type: str, resource_id: str) -> List[AuditEvent]:
        return [e for e in self.events if e.resource_type == resource_type and e.resource_id == resource_id]

    def get_events_in_range(self, start: datetime, end: datetime) -> List[AuditEvent]:
        return [e for e in self.events if start <= e.timestamp <= end]

    def find_related_events(self, event_id: str) -> List[AuditEvent]:
        target = next((e for e in self.events if e.event_id == event_id), None)
        if not target:
            return []
        related_ids = set(target.related_event_ids)
        related = [e for e in self.events if e.event_id in related_ids]
        for e in self.events:
            if event_id in e.related_event_ids and e.event_id not in related_ids:
                related.append(e)
                related_ids.add(e.event_id)
        return related

    def get_failure_events(self) -> List[AuditEvent]:
        return [e for e in self.events if e.is_failure()]

    def get_success_rate(self) -> float:
        if not self.events:
            return 1.0
        success_count = sum(1 for e in self.events if e.is_success())
        return success_count / len(self.events)

    def get_actor_count(self) -> int:
        return len(self.unique_actors)

    def get_resource_count(self) -> int:
        return len(self.unique_resources)

    def clear_events(self) -> None:
        self.events.clear()
        self.rule_events.clear()
        self.violation_events.clear()
        self.config_events.clear()
        self.event_count = 0
        self.unique_actors.clear()
        self.unique_resources.clear()
        self.categories.clear()
        self.actions.clear()
        self.period_start = None
        self.period_end = None
        self.updated_at = datetime.utcnow()

    def to_summary(self) -> Dict[str, Any]:
        return {
            "trail_id": self.trail_id,
            "name": self.name,
            "event_count": self.event_count,
            "unique_actors": self.get_actor_count(),
            "unique_resources": self.get_resource_count(),
            "categories": dict(self.categories),
            "actions": dict(self.actions),
            "success_rate": round(self.get_success_rate(), 3),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "retention_days": self.retention_days,
            "is_active": self.is_active
        }

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Set: lambda v: list(v)
        }


class AuditQuery(BaseModel):
    """Audit search/filter model."""

    query_id: str
    name: str
    description: Optional[str] = None

    categories: List[AuditCategory] = Field(default_factory=list)
    actions: List[AuditAction] = Field(default_factory=list)
    severities: List[AuditSeverity] = Field(default_factory=list)
    outcomes: List[str] = Field(default_factory=list)

    actors: List[str] = Field(default_factory=list)
    resource_types: List[str] = Field(default_factory=list)
    resource_ids: List[str] = Field(default_factory=list)

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    search_text: Optional[str] = None
    search_fields: List[str] = Field(default_factory=lambda: ["summary", "description"])

    tags: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    environments: List[str] = Field(default_factory=list)

    sort_by: str = "timestamp"
    sort_order: str = "desc"
    max_results: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)

    include_rule_events: bool = True
    include_violation_events: bool = True
    include_config_events: bool = True

    return_total_count: bool = True
    group_by: Optional[str] = None
    aggregate: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def matches_event(self, event: AuditEvent) -> bool:
        if self.categories and event.category not in self.categories:
            return False
        if self.actions and event.action not in self.actions:
            return False
        if self.severities and event.severity not in self.severities:
            return False
        if self.outcomes and event.outcome not in self.outcomes:
            return False
        if self.actors and event.actor not in self.actors:
            return False
        if self.resource_types and event.resource_type not in self.resource_types:
            return False
        if self.resource_ids and event.resource_id not in self.resource_ids:
            return False
        if self.date_from and event.timestamp < self.date_from:
            return False
        if self.date_to and event.timestamp > self.date_to:
            return False
        if self.search_text:
            found = False
            for field in self.search_fields:
                val = getattr(event, field, None)
                if val and self.search_text.lower() in str(val).lower():
                    found = True
                    break
            if not found:
                return False
        if self.tags and not any(tag in event.tags for tag in self.tags):
            return False
        if self.sources and event.source not in self.sources:
            return False
        if self.environments and event.environment not in self.environments:
            return False
        return True

    def apply_pagination(self, events: List[AuditEvent]) -> List[AuditEvent]:
        if self.sort_by == "timestamp" and self.sort_order == "desc":
            events = sorted(events, key=lambda e: e.timestamp, reverse=True)
        elif self.sort_by == "timestamp" and self.sort_order == "asc":
            events = sorted(events, key=lambda e: e.timestamp)
        elif self.sort_by == "severity":
            order = {s.value: i for i, s in enumerate(AuditSeverity)}
            events = sorted(events, key=lambda e: order.get(e.severity.value, 0), reverse=(self.sort_order == "desc"))
        return events[self.offset:self.offset + self.max_results]

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AuditExport(BaseModel):
    """Export configuration for audit data."""

    export_id: str
    name: str
    description: Optional[str] = None
    format: str = "json"
    compression: Optional[str] = None

    query: Optional[AuditQuery] = None
    include_events: bool = True
    include_rule_events: bool = True
    include_violation_events: bool = True
    include_config_events: bool = True
    include_metadata: bool = True
    include_changes: bool = True

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    max_events: int = Field(default=10000, ge=1, le=1000000)

    output_path: Optional[str] = None
    filename_pattern: Optional[str] = None
    split_by: Optional[str] = None
    max_file_size_mb: int = Field(default=100, ge=1, le=1000)

    encrypt: bool = False
    encryption_key: Optional[str] = None
    sign: bool = False
    signature_algorithm: Optional[str] = None

    notify_on_complete: bool = False
    notification_recipients: List[str] = Field(default_factory=list)
    retention_days: int = Field(default=30, ge=1, le=365)

    status: str = "pending"
    progress_percent: float = 0.0
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_filename(self, extension: str = ".json") -> str:
        pattern = self.filename_pattern or f"audit_export_{self.export_id}"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{pattern}_{timestamp}{extension}"

    def get_total_estimate(self, total_events: int) -> int:
        return min(total_events, self.max_events)

    def is_complete(self) -> bool:
        return self.status == "completed"

    def has_errors(self) -> bool:
        return self.status == "failed"

    def mark_complete(self) -> None:
        self.status = "completed"
        self.progress_percent = 100.0
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error_message = error

    def update_progress(self, percent: float) -> None:
        self.progress_percent = max(0.0, min(percent, 100.0))

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AuditPolicy(BaseModel):
    """Retention and archival policies."""

    policy_id: str
    name: str
    description: Optional[str] = None
    policy_type: str = "retention"

    retention_days: int = Field(default=90, ge=1, le=3650)
    archive_after_days: int = Field(default=30, ge=1, le=365)
    delete_after_days: Optional[int] = None

    max_storage_gb: int = Field(default=10, ge=1, le=10000)
    max_events_per_trail: int = Field(default=100000, ge=1000, le=10000000)
    max_event_size_bytes: int = Field(default=1048576, ge=1024, le=10485760)

    allowed_categories: List[AuditCategory] = Field(default_factory=list)
    excluded_categories: List[AuditCategory] = Field(default_factory=list)
    min_severity: AuditSeverity = AuditSeverity.DEBUG

    compress_archives: bool = True
    encrypt_archives: bool = False
    archive_format: str = "json"

    auto_purge: bool = True
    purge_interval_days: int = Field(default=7, ge=1, le=365)
    last_purge_at: Optional[datetime] = None

    notification_on_purge: bool = False
    purge_notification_recipients: List[str] = Field(default_factory=list)

    compliance_mode: bool = False
    legal_hold: bool = False
    legal_hold_reason: Optional[str] = None
    legal_hold_until: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def should_archive_event(self, event: AuditEvent) -> bool:
        if self.allowed_categories and event.category not in self.allowed_categories:
            return False
        if event.category in self.excluded_categories:
            return False
        severity_order = {s.value: i for i, s in enumerate(AuditSeverity)}
        if severity_order.get(event.severity.value, 0) < severity_order.get(self.min_severity.value, 0):
            return False
        return True

    def is_event_expired(self, event_timestamp: datetime) -> bool:
        age = datetime.utcnow() - event_timestamp
        if self.retention_days and age.days > self.retention_days:
            return True
        return False

    def should_archive(self, event_timestamp: datetime) -> bool:
        age = datetime.utcnow() - event_timestamp
        return age.days > self.archive_after_days

    def should_delete(self, event_timestamp: datetime) -> bool:
        if self.legal_hold:
            return False
        if not self.delete_after_days:
            return False
        age = datetime.utcnow() - event_timestamp
        return age.days > self.delete_after_days

    def get_storage_status(self, current_storage_gb: float, current_event_count: int) -> Dict[str, Any]:
        return {
            "current_storage_gb": current_storage_gb,
            "max_storage_gb": self.max_storage_gb,
            "storage_usage_percent": round((current_storage_gb / self.max_storage_gb) * 100, 2) if self.max_storage_gb > 0 else 0,
            "current_event_count": current_event_count,
            "max_events_per_trail": self.max_events_per_trail,
            "event_usage_percent": round((current_event_count / self.max_events_per_trail) * 100, 2) if self.max_events_per_trail > 0 else 0,
            "needs_purge": current_storage_gb > self.max_storage_gb * 0.9 or current_event_count > self.max_events_per_trail * 0.9,
            "legal_hold_active": self.legal_hold
        }

    def record_purge(self) -> None:
        self.last_purge_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def enable_legal_hold(self, reason: str, until: Optional[datetime] = None) -> None:
        self.legal_hold = True
        self.legal_hold_reason = reason
        self.legal_hold_until = until
        self.updated_at = datetime.utcnow()

    def disable_legal_hold(self) -> None:
        self.legal_hold = False
        self.legal_hold_reason = None
        self.legal_hold_until = None
        self.updated_at = datetime.utcnow()

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