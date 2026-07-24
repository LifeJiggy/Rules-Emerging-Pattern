"""
Incident manager for tracking escalated exceptions through their lifecycle.

Provides incident creation, prioritization, assignment, root cause analysis,
reporting, and config-driven incident workflows.
"""

import logging
import uuid
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class IncidentPriority(str, Enum):
    """Priority levels for incidents."""
    P1_CRITICAL = "p1_critical"
    P2_HIGH = "p2_high"
    P3_MEDIUM = "p3_medium"
    P4_LOW = "p4_low"


class IncidentStatus(str, Enum):
    """Lifecycle status of an incident."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class IncidentCategory(str, Enum):
    """Category of the incident."""
    SECURITY = "security"
    COMPLIANCE = "compliance"
    SYSTEM = "system"
    DATA = "data"
    PERFORMANCE = "performance"
    BUSINESS = "business"
    INTEGRATION = "integration"
    CONFIGURATION = "configuration"
    OTHER = "other"


class RCAStatus(str, Enum):
    """Status of root cause analysis."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEWED = "reviewed"


@dataclass
class Incident:
    """Complete incident record."""
    incident_id: str
    title: str
    description: str
    priority: IncidentPriority
    status: IncidentStatus
    category: IncidentCategory
    source: str = ""
    source_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    assigned_team: Optional[str] = None
    created_by: str = "system"
    escalation_ids: List[str] = field(default_factory=list)
    violation_ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    impact_description: str = ""
    severity: str = "medium"
    environment: str = "production"
    affected_components: List[str] = field(default_factory=list)
    related_incidents: List[str] = field(default_factory=list)
    rca: Optional["RootCauseAnalysis"] = None
    timeline: List["IncidentEvent"] = field(default_factory=list)
    notes: List["IncidentNote"] = field(default_factory=list)
    action_items: List["ActionItem"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "priority": self.priority.value,
            "status": self.status.value,
            "category": self.category.value,
            "rca": self.rca.to_dict() if self.rca else None,
            "timeline": [e.to_dict() for e in self.timeline],
            "notes": [n.to_dict() for n in self.notes],
            "action_items": [a.to_dict() for a in self.action_items],
        }

    def age_hours(self) -> float:
        end = self.closed_at or datetime.utcnow()
        return (end - self.created_at).total_seconds() / 3600


@dataclass
class IncidentEvent:
    """Timeline event for an incident."""
    event_id: str
    event_type: str
    description: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    actor: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class IncidentNote:
    """Note attached to an incident."""
    note_id: str
    content: str
    author: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_internal: bool = False
    note_type: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ActionItem:
    """Action item associated with an incident."""
    action_id: str
    description: str
    assigned_to: Optional[str] = None
    status: str = "open"
    priority: str = "medium"
    due_date: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
        }


@dataclass
class RootCauseAnalysis:
    """Root cause analysis for an incident."""
    rca_id: str
    status: RCAStatus
    root_cause: str = ""
    contributing_factors: List[str] = field(default_factory=list)
    impact_assessment: str = ""
    remediation_steps: List[str] = field(default_factory=list)
    preventive_measures: List[str] = field(default_factory=list)
    severity: str = "medium"
    detected_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    analyzed_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass
class IncidentConfig:
    """Configuration for incident management."""
    config_id: str = "default_incident_config"
    auto_create_from_escalations: bool = True
    auto_assign_enabled: bool = True
    default_team: str = "engineering"
    sla_hours: Dict[str, int] = field(default_factory=lambda: {
        "p1_critical": 1,
        "p2_high": 4,
        "p3_medium": 24,
        "p4_low": 72,
    })
    max_active_incidents: int = 100
    notify_on_create: bool = True
    notify_on_status_change: bool = True
    enable_rca: bool = True
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_sla_hours(self, priority: IncidentPriority) -> int:
        return self.sla_hours.get(priority.value, 24)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IncidentManager:
    """Incident lifecycle manager with RCA tracking, prioritization, and reporting."""

    def __init__(self, config: Optional[IncidentConfig] = None) -> None:
        self.logger = logger
        self.config = config or IncidentConfig()
        self._incidents: Dict[str, Incident] = {}
        self._handlers: Dict[str, List[Callable]] = {
            "on_create": [],
            "on_update": [],
            "on_assign": [],
            "on_status_change": [],
            "on_close": [],
            "on_rca_complete": [],
        }

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def on_create(self, handler: Callable) -> None:
        self._handlers["on_create"].append(handler)

    def on_update(self, handler: Callable) -> None:
        self._handlers["on_update"].append(handler)

    def on_assign(self, handler: Callable) -> None:
        self._handlers["on_assign"].append(handler)

    def on_status_change(self, handler: Callable) -> None:
        self._handlers["on_status_change"].append(handler)

    def on_close(self, handler: Callable) -> None:
        self._handlers["on_close"].append(handler)

    def on_rca_complete(self, handler: Callable) -> None:
        self._handlers["on_rca_complete"].append(handler)

    def _fire_event(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception as exc:
                self.logger.error("Event handler %s failed: %s", event, exc)

    # ------------------------------------------------------------------
    # Incident CRUD
    # ------------------------------------------------------------------

    def create_incident(
        self,
        title: str,
        description: str,
        priority: Union[str, IncidentPriority],
        category: Union[str, IncidentCategory],
        source: str = "system",
        source_id: str = "",
        created_by: str = "system",
        escalation_ids: Optional[List[str]] = None,
        violation_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        impact_description: str = "",
        severity: str = "medium",
        environment: str = "production",
        affected_components: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Incident:
        if isinstance(priority, str):
            priority = IncidentPriority(priority)
        if isinstance(category, str):
            category = IncidentCategory(category)

        if len(self._incidents) >= self.config.max_active_incidents:
            self.logger.warning("Max active incidents reached (%s)", self.config.max_active_incidents)
            raise RuntimeError("Max active incidents reached")

        incident_id = self._generate_incident_id()
        now = datetime.utcnow()
        incident = Incident(
            incident_id=incident_id,
            title=title,
            description=description,
            priority=priority,
            status=IncidentStatus.OPEN,
            category=category,
            source=source,
            source_id=source_id,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            escalation_ids=escalation_ids or [],
            violation_ids=violation_ids or [],
            tags=tags or [],
            impact_description=impact_description,
            severity=severity,
            environment=environment,
            affected_components=affected_components or [],
            metadata=metadata or {},
        )
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="created",
            description=f"Incident created with priority {priority.value}",
            timestamp=now,
            actor=created_by,
        ))
        self._incidents[incident_id] = incident
        self._fire_event("on_create", incident=incident)
        self.logger.info("Incident created: id=%s priority=%s category=%s", incident_id, priority.value, category.value)
        return incident

    def create_from_escalation(
        self,
        title: str,
        description: str,
        escalation_ids: List[str],
        priority: Optional[IncidentPriority] = None,
        category: Optional[IncidentCategory] = None,
        source: str = "escalation",
        source_id: str = "",
        created_by: str = "system",
        **kwargs: Any,
    ) -> Incident:
        resolved_priority = priority or IncidentPriority.P3_MEDIUM
        resolved_category = category or IncidentCategory.OTHER
        return self.create_incident(
            title=title,
            description=description,
            priority=resolved_priority,
            category=resolved_category,
            source=source,
            source_id=source_id or escalation_ids[0] if escalation_ids else "",
            created_by=created_by,
            escalation_ids=escalation_ids,
            tags=kwargs.pop("tags", None) or ["from_escalation"],
            **kwargs,
        )

    def create_from_violation(
        self,
        violation: Violation,
        priority: Optional[IncidentPriority] = None,
        category: Optional[IncidentCategory] = None,
        created_by: str = "system",
        **kwargs: Any,
    ) -> Incident:
        resolved_priority = priority or self._violation_to_priority(violation)
        resolved_category = category or self._violation_to_category(violation)
        return self.create_incident(
            title=f"Violation: {violation.rule_name}",
            description=violation.explanation or violation.matched_content or "Rule violation detected",
            priority=resolved_priority,
            category=resolved_category,
            source="violation",
            source_id=violation.rule_id,
            created_by=created_by,
            violation_ids=[violation.rule_id],
            tags=kwargs.pop("tags", None) or [f"tier:{violation.rule_tier.value}"],
            impact_description=f"Violation type: {violation.violation_type.value}",
            severity=violation.rule_severity.value,
            **kwargs,
        )

    def create_from_result(
        self,
        result: ValidationResult,
        priority: Optional[IncidentPriority] = None,
        category: Optional[IncidentCategory] = None,
        created_by: str = "system",
        **kwargs: Any,
    ) -> List[Incident]:
        incidents: List[Incident] = []
        for violation in result.violations:
            if violation.is_critical():
                incident = self.create_from_violation(violation, priority, category, created_by, **kwargs)
                incidents.append(incident)
        for warning in result.warnings:
            if warning.rule_severity in (RuleSeverity.CRITICAL, RuleSeverity.HIGH):
                incident = self.create_from_violation(warning, priority or IncidentPriority.P3_MEDIUM, category, created_by, **kwargs)
                incidents.append(incident)
        return incidents

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    def update_incident(
        self,
        incident_id: str,
        updates: Dict[str, Any],
        actor: str = "system",
    ) -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if not incident:
            self.logger.warning("Incident not found: %s", incident_id)
            return None
        allowed_fields = {
            "title", "description", "impact_description", "severity",
            "environment", "tags", "affected_components", "metadata",
        }
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(incident, key, value)
        if "priority" in updates:
            incident.priority = IncidentPriority(updates["priority"])
        if "category" in updates:
            incident.category = IncidentCategory(updates["category"])
        incident.updated_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="updated",
            description=f"Incident updated: {', '.join(updates.keys())}",
            actor=actor,
            details=updates,
        ))
        self._fire_event("on_update", incident=incident, updates=updates)
        return incident

    # ------------------------------------------------------------------
    # Status Transitions
    # ------------------------------------------------------------------

    def change_status(self, incident_id: str, new_status: Union[str, IncidentStatus],
                      actor: str = "system", reason: str = "") -> Optional[Incident]:
        if isinstance(new_status, str):
            new_status = IncidentStatus(new_status)
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        old_status = incident.status
        if old_status == new_status:
            return incident
        valid = self._is_valid_transition(old_status, new_status)
        if not valid:
            self.logger.warning("Invalid status transition: %s -> %s", old_status.value, new_status.value)
            raise ValueError(f"Invalid status transition: {old_status.value} -> {new_status.value}")

        incident.status = new_status
        incident.updated_at = datetime.utcnow()
        if new_status == IncidentStatus.CLOSED:
            incident.closed_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="status_change",
            description=f"Status changed: {old_status.value} -> {new_status.value}",
            actor=actor,
            details={"old_status": old_status.value, "new_status": new_status.value, "reason": reason},
        ))
        self._fire_event("on_status_change", incident=incident, old_status=old_status, new_status=new_status)
        self.logger.info("Incident %s status: %s -> %s", incident_id, old_status.value, new_status.value)
        return incident

    def investigate(self, incident_id: str, actor: str = "system") -> Optional[Incident]:
        return self.change_status(incident_id, IncidentStatus.INVESTIGATING, actor)

    def mitigate(self, incident_id: str, actor: str = "system") -> Optional[Incident]:
        return self.change_status(incident_id, IncidentStatus.MITIGATED, actor)

    def resolve(self, incident_id: str, actor: str = "system") -> Optional[Incident]:
        return self.change_status(incident_id, IncidentStatus.RESOLVED, actor)

    def close(self, incident_id: str, actor: str = "system") -> Optional[Incident]:
        return self.change_status(incident_id, IncidentStatus.CLOSED, actor)

    def reopen(self, incident_id: str, actor: str = "system", reason: str = "") -> Optional[Incident]:
        return self.change_status(incident_id, IncidentStatus.REOPENED, actor, reason)

    @staticmethod
    def _is_valid_transition(old: IncidentStatus, new: IncidentStatus) -> bool:
        valid_transitions: Dict[IncidentStatus, List[IncidentStatus]] = {
            IncidentStatus.OPEN: [IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED, IncidentStatus.CLOSED],
            IncidentStatus.INVESTIGATING: [IncidentStatus.MITIGATED, IncidentStatus.RESOLVED, IncidentStatus.OPEN],
            IncidentStatus.MITIGATED: [IncidentStatus.RESOLVED, IncidentStatus.INVESTIGATING, IncidentStatus.REOPENED],
            IncidentStatus.RESOLVED: [IncidentStatus.CLOSED, IncidentStatus.REOPENED],
            IncidentStatus.CLOSED: [IncidentStatus.REOPENED],
            IncidentStatus.REOPENED: [IncidentStatus.INVESTIGATING, IncidentStatus.OPEN],
        }
        return new in valid_transitions.get(old, [])

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def assign(self, incident_id: str, assignee: str, team: Optional[str] = None,
               actor: str = "system") -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        old_assignee = incident.assigned_to
        incident.assigned_to = assignee
        if team:
            incident.assigned_team = team
        incident.updated_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="assigned",
            description=f"Assigned to {assignee}",
            actor=actor,
            details={"old_assignee": old_assignee, "new_assignee": assignee, "team": team},
        ))
        self._fire_event("on_assign", incident=incident, assignee=assignee)
        self.logger.info("Incident %s assigned to %s", incident_id, assignee)
        return incident

    def assign_team(self, incident_id: str, team: str, actor: str = "system") -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        incident.assigned_team = team
        incident.updated_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="team_assigned",
            description=f"Team assigned: {team}",
            actor=actor,
        ))
        return incident

    def auto_assign(self, incident_id: str) -> Optional[Incident]:
        if not self.config.auto_assign_enabled:
            return None
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        team = self._resolve_team_for_incident(incident)
        if team:
            incident.assigned_team = team
            incident.updated_at = datetime.utcnow()
            incident.timeline.append(IncidentEvent(
                event_id=self._generate_event_id(),
                event_type="auto_assigned",
                description=f"Auto-assigned to team: {team}",
            ))
        return incident

    def _resolve_team_for_incident(self, incident: Incident) -> str:
        category_team_map: Dict[IncidentCategory, str] = {
            IncidentCategory.SECURITY: "security",
            IncidentCategory.COMPLIANCE: "compliance",
            IncidentCategory.SYSTEM: "engineering",
            IncidentCategory.DATA: "data_engineering",
            IncidentCategory.PERFORMANCE: "engineering",
            IncidentCategory.BUSINESS: "product",
            IncidentCategory.INTEGRATION: "engineering",
            IncidentCategory.CONFIGURATION: "devops",
            IncidentCategory.OTHER: self.config.default_team,
        }
        return category_team_map.get(incident.category, self.config.default_team)

    def get_assigned_incidents(self, assignee: str) -> List[Incident]:
        return [
            i for i in self._incidents.values()
            if i.assigned_to == assignee and i.status not in (IncidentStatus.CLOSED, IncidentStatus.RESOLVED)
        ]

    def get_team_incidents(self, team: str) -> List[Incident]:
        return [
            i for i in self._incidents.values()
            if i.assigned_team == team
        ]

    # ------------------------------------------------------------------
    # Timeline & Notes
    # ------------------------------------------------------------------

    def add_event(self, incident_id: str, event_type: str, description: str,
                  actor: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> Optional[IncidentEvent]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        event = IncidentEvent(
            event_id=self._generate_event_id(),
            event_type=event_type,
            description=description,
            actor=actor,
            details=details or {},
        )
        incident.timeline.append(event)
        incident.updated_at = datetime.utcnow()
        return event

    def add_note(self, incident_id: str, content: str, author: str,
                 is_internal: bool = False, note_type: str = "general") -> Optional[IncidentNote]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        note = IncidentNote(
            note_id=self._generate_note_id(),
            content=content,
            author=author,
            is_internal=is_internal,
            note_type=note_type,
        )
        incident.notes.append(note)
        incident.updated_at = datetime.utcnow()
        return note

    def get_notes(self, incident_id: str, include_internal: bool = False) -> List[IncidentNote]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        if include_internal:
            return incident.notes
        return [n for n in incident.notes if not n.is_internal]

    # ------------------------------------------------------------------
    # Action Items
    # ------------------------------------------------------------------

    def add_action_item(
        self,
        incident_id: str,
        description: str,
        assigned_to: Optional[str] = None,
        priority: str = "medium",
        due_date: Optional[datetime] = None,
    ) -> Optional[ActionItem]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        action = ActionItem(
            action_id=self._generate_action_id(),
            description=description,
            assigned_to=assigned_to,
            priority=priority,
            due_date=due_date,
        )
        incident.action_items.append(action)
        incident.updated_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="action_item_added",
            description=f"Action item added: {description[:60]}",
        ))
        return action

    def update_action_item(self, incident_id: str, action_id: str,
                           updates: Dict[str, Any]) -> bool:
        incident = self._incidents.get(incident_id)
        if not incident:
            return False
        for action in incident.action_items:
            if action.action_id == action_id:
                for key, value in updates.items():
                    if hasattr(action, key):
                        setattr(action, key, value)
                if updates.get("status") == "completed":
                    action.completed_at = datetime.utcnow()
                incident.updated_at = datetime.utcnow()
                return True
        return False

    def complete_action_item(self, incident_id: str, action_id: str) -> bool:
        return self.update_action_item(incident_id, action_id, {"status": "completed"})

    def get_open_action_items(self, incident_id: str) -> List[ActionItem]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        return [a for a in incident.action_items if a.status == "open"]

    # ------------------------------------------------------------------
    # Root Cause Analysis
    # ------------------------------------------------------------------

    def create_rca(
        self,
        incident_id: str,
        analyzed_by: Optional[str] = None,
    ) -> Optional[RootCauseAnalysis]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        if not self.config.enable_rca:
            return None
        rca = RootCauseAnalysis(
            rca_id=f"rca_{uuid.uuid4().hex[:12]}",
            status=RCAStatus.NOT_STARTED,
            analyzed_by=analyzed_by,
            detected_at=incident.created_at,
        )
        incident.rca = rca
        incident.updated_at = datetime.utcnow()
        incident.timeline.append(IncidentEvent(
            event_id=self._generate_event_id(),
            event_type="rca_created",
            description="Root cause analysis initiated",
            actor=analyzed_by,
        ))
        return rca

    def update_rca(
        self,
        incident_id: str,
        root_cause: str = "",
        contributing_factors: Optional[List[str]] = None,
        impact_assessment: str = "",
        remediation_steps: Optional[List[str]] = None,
        preventive_measures: Optional[List[str]] = None,
        status: Optional[Union[str, RCAStatus]] = None,
        reviewed_by: Optional[str] = None,
    ) -> Optional[RootCauseAnalysis]:
        incident = self._incidents.get(incident_id)
        if not incident or not incident.rca:
            return None
        rca = incident.rca
        if root_cause:
            rca.root_cause = root_cause
        if contributing_factors is not None:
            rca.contributing_factors = contributing_factors
        if impact_assessment:
            rca.impact_assessment = impact_assessment
        if remediation_steps is not None:
            rca.remediation_steps = remediation_steps
        if preventive_measures is not None:
            rca.preventive_measures = preventive_measures
        if status:
            if isinstance(status, str):
                status = RCAStatus(status)
            rca.status = status
        if reviewed_by:
            rca.reviewed_by = reviewed_by
        rca.updated_at = datetime.utcnow()
        incident.updated_at = datetime.utcnow()
        if status == RCAStatus.COMPLETED:
            rca.resolved_at = datetime.utcnow()
            self._fire_event("on_rca_complete", incident=incident, rca=rca)
            incident.timeline.append(IncidentEvent(
                event_id=self._generate_event_id(),
                event_type="rca_completed",
                description="Root cause analysis completed",
                actor=reviewed_by,
            ))
        return rca

    def complete_rca(self, incident_id: str, reviewed_by: Optional[str] = None) -> Optional[RootCauseAnalysis]:
        return self.update_rca(incident_id, status=RCAStatus.COMPLETED, reviewed_by=reviewed_by)

    def get_rca(self, incident_id: str) -> Optional[RootCauseAnalysis]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        return incident.rca

    # ------------------------------------------------------------------
    # SLA Tracking
    # ------------------------------------------------------------------

    def check_sla(self, incident_id: str) -> Dict[str, Any]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return {"incident_id": incident_id, "error": "not_found"}
        sla_hours = self.config.get_sla_hours(incident.priority)
        age_hours = incident.age_hours()
        deadline = incident.created_at + timedelta(hours=sla_hours)
        remaining_hours = sla_hours - age_hours
        status: str
        if remaining_hours <= 0:
            if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                status = "met"
            else:
                status = "breached"
        elif remaining_hours <= sla_hours * 0.2:
            status = "at_risk"
        else:
            status = "on_track"
        return {
            "incident_id": incident_id,
            "priority": incident.priority.value,
            "sla_hours": sla_hours,
            "age_hours": round(age_hours, 2),
            "remaining_hours": round(max(remaining_hours, 0), 2),
            "deadline": deadline.isoformat(),
            "sla_status": status,
            "status": incident.status.value,
        }

    def check_all_slas(self) -> Dict[str, Dict[str, Any]]:
        return {
            iid: self.check_sla(iid)
            for iid, inc in self._incidents.items()
            if inc.status not in (IncidentStatus.CLOSED, IncidentStatus.RESOLVED)
        }

    def get_sla_breaches(self) -> List[Dict[str, Any]]:
        return [
            result for result in self.check_all_slas().values()
            if result.get("sla_status") == "breached"
        ]

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def link_incidents(self, incident_id_1: str, incident_id_2: str) -> bool:
        inc1 = self._incidents.get(incident_id_1)
        inc2 = self._incidents.get(incident_id_2)
        if not inc1 or not inc2:
            return False
        if incident_id_2 not in inc1.related_incidents:
            inc1.related_incidents.append(incident_id_2)
        if incident_id_1 not in inc2.related_incidents:
            inc2.related_incidents.append(incident_id_1)
        inc1.updated_at = datetime.utcnow()
        inc2.updated_at = datetime.utcnow()
        return True

    def unlink_incidents(self, incident_id_1: str, incident_id_2: str) -> bool:
        inc1 = self._incidents.get(incident_id_1)
        inc2 = self._incidents.get(incident_id_2)
        if not inc1 or not inc2:
            return False
        if incident_id_2 in inc1.related_incidents:
            inc1.related_incidents.remove(incident_id_2)
        if incident_id_1 in inc2.related_incidents:
            inc2.related_incidents.remove(incident_id_1)
        return True

    def get_related_incidents(self, incident_id: str) -> List[Incident]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        return [
            self._incidents.get(rid) for rid in incident.related_incidents
            if rid in self._incidents
        ]

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def find_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        priority: Optional[IncidentPriority] = None,
        category: Optional[IncidentCategory] = None,
        assigned_to: Optional[str] = None,
        assigned_team: Optional[str] = None,
        source: Optional[str] = None,
        query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Incident]:
        results = list(self._incidents.values())
        if status:
            results = [i for i in results if i.status == status]
        if priority:
            results = [i for i in results if i.priority == priority]
        if category:
            results = [i for i in results if i.category == category]
        if assigned_to:
            results = [i for i in results if i.assigned_to == assigned_to]
        if assigned_team:
            results = [i for i in results if i.assigned_team == assigned_team]
        if source:
            results = [i for i in results if i.source == source]
        if query:
            q = query.lower()
            results = [
                i for i in results
                if q in i.title.lower() or q in i.description.lower() or q in i.incident_id.lower()
            ]
        if start_time:
            results = [i for i in results if i.created_at >= start_time]
        if end_time:
            results = [i for i in results if i.created_at <= end_time]
        if tags:
            results = [i for i in results if any(t in i.tags for t in tags)]
        results.sort(key=lambda i: (i.priority.value, i.created_at), reverse=False)
        return results[:limit]

    def get_open_incidents(self, limit: int = 100) -> List[Incident]:
        return self.find_incidents(
            status=IncidentStatus.OPEN,
            limit=limit,
        )

    def get_investigating_incidents(self, limit: int = 100) -> List[Incident]:
        return self.find_incidents(
            status=IncidentStatus.INVESTIGATING,
            limit=limit,
        )

    def get_recent_incidents(self, hours: int = 24, limit: int = 100) -> List[Incident]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        results = [i for i in self._incidents.values() if i.created_at >= cutoff]
        results.sort(key=lambda i: i.created_at, reverse=True)
        return results[:limit]

    def search_incidents(self, query: str, limit: int = 100) -> List[Incident]:
        return self.find_incidents(query=query, limit=limit)

    # ------------------------------------------------------------------
    # Reporting & Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._incidents)
        if total == 0:
            return {"total_incidents": 0}
        by_status: Dict[str, int] = {}
        by_priority: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        by_team: Dict[str, int] = {}
        open_count = 0
        resolved_count = 0
        breached_count = 0
        total_age_hours = 0.0
        resolution_times: List[float] = []
        for inc in self._incidents.values():
            by_status[inc.status.value] = by_status.get(inc.status.value, 0) + 1
            by_priority[inc.priority.value] = by_priority.get(inc.priority.value, 0) + 1
            by_category[inc.category.value] = by_category.get(inc.category.value, 0) + 1
            if inc.assigned_team:
                by_team[inc.assigned_team] = by_team.get(inc.assigned_team, 0) + 1
            if inc.status == IncidentStatus.OPEN:
                open_count += 1
            if inc.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                resolved_count += 1
                if inc.closed_at:
                    resolution_times.append((inc.closed_at - inc.created_at).total_seconds() / 3600)
            total_age_hours += inc.age_hours()
            sla = self.check_sla(inc.incident_id)
            if sla.get("sla_status") == "breached":
                breached_count += 1
        has_rca = sum(1 for i in self._incidents.values() if i.rca is not None)
        rca_completed = sum(1 for i in self._incidents.values() if i.rca and i.rca.status == RCAStatus.COMPLETED)
        return {
            "total_incidents": total,
            "open": open_count,
            "resolved_closed": resolved_count,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_team": by_team,
            "sla_breaches": breached_count,
            "sla_compliance_rate": round((1 - breached_count / total) * 100, 2) if total else 100.0,
            "avg_age_hours": round(total_age_hours / total, 2) if total else 0.0,
            "avg_resolution_hours": round(sum(resolution_times) / len(resolution_times), 2) if resolution_times else None,
            "resolution_rate": round(resolved_count / total * 100, 2) if total else 0.0,
            "with_rca": has_rca,
            "rca_completed": rca_completed,
            "rca_completion_rate": round(rca_completed / has_rca * 100, 2) if has_rca else 0.0,
            "total_action_items": sum(len(i.action_items) for i in self._incidents.values()),
            "open_action_items": sum(len(self.get_open_action_items(i.incident_id)) for i in self._incidents.values()),
        }

    def generate_report(self, days: int = 30) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        period_incidents = [i for i in self._incidents.values() if i.created_at >= cutoff]
        total = len(period_incidents)
        if total == 0:
            return {"period_days": days, "total": 0}
        by_priority: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        by_day: Dict[str, int] = {}
        resolved = 0
        breaches = 0
        resolution_times: List[float] = []
        for inc in period_incidents:
            by_priority[inc.priority.value] = by_priority.get(inc.priority.value, 0) + 1
            by_category[inc.category.value] = by_category.get(inc.category.value, 0) + 1
            date_key = inc.created_at.strftime("%Y-%m-%d")
            by_day[date_key] = by_day.get(date_key, 0) + 1
            if inc.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                resolved += 1
                if inc.closed_at:
                    resolution_times.append((inc.closed_at - inc.created_at).total_seconds() / 3600)
            sla = self.check_sla(inc.incident_id)
            if sla.get("sla_status") == "breached":
                breaches += 1
        priority_order = ["p1_critical", "p2_high", "p3_medium", "p4_low"]
        top_priority = None
        for p in priority_order:
            if by_priority.get(p, 0) > 0:
                top_priority = p
                break
        return {
            "period_days": days,
            "total_incidents": total,
            "resolved": resolved,
            "sla_breaches": breaches,
            "sla_compliance_rate": round((1 - breaches / total) * 100, 2) if total else 100.0,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_day": by_day,
            "avg_daily": round(total / days, 2) if days else 0.0,
            "avg_resolution_hours": round(sum(resolution_times) / len(resolution_times), 2) if resolution_times else None,
            "top_priority": top_priority,
            "resolution_rate": round(resolved / total * 100, 2) if total else 0.0,
        }

    def get_category_breakdown(self) -> Dict[str, Dict[str, int]]:
        breakdown: Dict[str, Dict[str, int]] = {}
        for inc in self._incidents.values():
            cat = inc.category.value
            if cat not in breakdown:
                breakdown[cat] = {"total": 0, "open": 0, "resolved": 0}
            breakdown[cat]["total"] += 1
            if inc.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                breakdown[cat]["resolved"] += 1
            elif inc.status not in (IncidentStatus.CLOSED,):
                breakdown[cat]["open"] += 1
        return breakdown

    def get_team_performance(self) -> Dict[str, Dict[str, Any]]:
        team_stats: Dict[str, Dict[str, Any]] = {}
        for inc in self._incidents.values():
            team = inc.assigned_team or "unassigned"
            if team not in team_stats:
                team_stats[team] = {
                    "total": 0, "open": 0, "resolved": 0,
                    "sla_breaches": 0, "resolution_times": [],
                }
            team_stats[team]["total"] += 1
            if inc.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                team_stats[team]["resolved"] += 1
                if inc.closed_at:
                    team_stats[team]["resolution_times"].append(
                        (inc.closed_at - inc.created_at).total_seconds() / 3600
                    )
            elif inc.status not in (IncidentStatus.CLOSED,):
                team_stats[team]["open"] += 1
            sla = self.check_sla(inc.incident_id)
            if sla.get("sla_status") == "breached":
                team_stats[team]["sla_breaches"] += 1
        for team, stats in team_stats.items():
            times = stats.pop("resolution_times", [])
            stats["avg_resolution_hours"] = round(sum(times) / len(times), 2) if times else None
            stats["resolution_rate"] = round(stats["resolved"] / stats["total"] * 100, 2) if stats["total"] else 0.0
            stats["sla_breach_rate"] = round(stats["sla_breaches"] / stats["total"] * 100, 2) if stats["total"] else 0.0
        return team_stats

    def get_mttr(self, days: int = 90) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        resolved_incidents = [
            i for i in self._incidents.values()
            if i.closed_at and i.created_at >= cutoff
            and i.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED)
        ]
        if not resolved_incidents:
            return {"period_days": days, "mttr_hours": None, "total_resolved": 0}
        resolution_times = [
            (i.closed_at - i.created_at).total_seconds() / 3600
            for i in resolved_incidents
        ]
        by_priority: Dict[str, List[float]] = {}
        for i in resolved_incidents:
            p = i.priority.value
            if p not in by_priority:
                by_priority[p] = []
            by_priority[p].append((i.closed_at - i.created_at).total_seconds() / 3600)
        return {
            "period_days": days,
            "total_resolved": len(resolved_incidents),
            "mttr_hours": round(sum(resolution_times) / len(resolution_times), 2),
            "mttr_by_priority": {
                p: round(sum(t) / len(t), 2) for p, t in by_priority.items()
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _violation_to_priority(violation: Violation) -> IncidentPriority:
        mapping = {
            RuleSeverity.CRITICAL: IncidentPriority.P1_CRITICAL,
            RuleSeverity.HIGH: IncidentPriority.P2_HIGH,
            RuleSeverity.MEDIUM: IncidentPriority.P3_MEDIUM,
            RuleSeverity.LOW: IncidentPriority.P4_LOW,
        }
        return mapping.get(violation.rule_severity, IncidentPriority.P3_MEDIUM)

    @staticmethod
    def _violation_to_category(violation: Violation) -> IncidentCategory:
        mapping = {
            ViolationType.COMPLIANCE_VIOLATION: IncidentCategory.COMPLIANCE,
            ViolationType.SEMANTIC_VIOLATION: IncidentCategory.BUSINESS,
            ViolationType.STRUCTURAL_VIOLATION: IncidentCategory.SYSTEM,
            ViolationType.QUALITY_VIOLATION: IncidentCategory.DATA,
        }
        return mapping.get(violation.violation_type, IncidentCategory.OTHER)

    @staticmethod
    def _generate_incident_id() -> str:
        return f"inc_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _generate_event_id() -> str:
        return f"evt_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _generate_note_id() -> str:
        return f"note_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _generate_action_id() -> str:
        return f"act_{uuid.uuid4().hex[:12]}"

    def __len__(self) -> int:
        return len(self._incidents)

    def __contains__(self, incident_id: str) -> bool:
        return incident_id in self._incidents

    def __iter__(self):
        return iter(self._incidents.values())
