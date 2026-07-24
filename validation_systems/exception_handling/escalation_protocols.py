"""
Multi-level escalation protocols for exception handling.

Provides config-driven escalation definitions with SLA tracking,
routing rules, audit trail, and channel dispatch.
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


class EscalationLevel(str, Enum):
    """Escalation severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationChannel(str, Enum):
    """Channels through which escalation is dispatched."""
    INTERNAL_TEAM = "internal_team"
    ADMIN = "admin"
    LEGAL = "legal"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    EXECUTIVE = "executive"
    CUSTOM = "custom"


class EscalationTriggerType(str, Enum):
    """Types of escalation triggers."""
    THRESHOLD = "threshold"
    TIME_BASED = "time_based"
    PATTERN = "pattern"
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    COMPOUND = "compound"


class EscalationStatus(str, Enum):
    """Status of an escalation instance."""
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED_FURTHER = "escalated_further"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SLARisk(str, Enum):
    """SLA risk assessment."""
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"


@dataclass
class SLADefinition:
    """SLA definition for an escalation level."""
    level: EscalationLevel
    response_time_minutes: int
    resolution_time_minutes: int
    notification_interval_minutes: int
    auto_escalate_after_minutes: Optional[int] = None
    auto_escalate_to: Optional[EscalationLevel] = None
    business_hours_only: bool = False
    allowed_delay_minutes: int = 0
    penalty_on_breach: str = "notification"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def default_low(cls) -> "SLADefinition":
        return cls(
            level=EscalationLevel.LOW,
            response_time_minutes=240,
            resolution_time_minutes=2880,
            notification_interval_minutes=60,
            business_hours_only=True,
        )

    @classmethod
    def default_medium(cls) -> "SLADefinition":
        return cls(
            level=EscalationLevel.MEDIUM,
            response_time_minutes=120,
            resolution_time_minutes=1440,
            notification_interval_minutes=30,
            auto_escalate_after_minutes=360,
            auto_escalate_to=EscalationLevel.HIGH,
            business_hours_only=True,
        )

    @classmethod
    def default_high(cls) -> "SLADefinition":
        return cls(
            level=EscalationLevel.HIGH,
            response_time_minutes=30,
            resolution_time_minutes=480,
            notification_interval_minutes=15,
            auto_escalate_after_minutes=120,
            auto_escalate_to=EscalationLevel.CRITICAL,
        )

    @classmethod
    def default_critical(cls) -> "SLADefinition":
        return cls(
            level=EscalationLevel.CRITICAL,
            response_time_minutes=5,
            resolution_time_minutes=120,
            notification_interval_minutes=5,
            auto_escalate_after_minutes=30,
            auto_escalate_to=None,
            penalty_on_breach="executive_notification",
        )


@dataclass
class EscalationTrigger:
    """Definition of an escalation trigger."""
    trigger_id: str
    name: str
    trigger_type: EscalationTriggerType
    target_level: EscalationLevel
    conditions: Dict[str, Any] = field(default_factory=dict)
    cooldown_seconds: int = 300
    max_firings_per_hour: int = 10
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "trigger_type": self.trigger_type.value,
            "target_level": self.target_level.value,
        }


@dataclass
class EscalationRoute:
    """Routing rule for escalation dispatch."""
    route_id: str
    name: str
    source_levels: List[EscalationLevel] = field(default_factory=list)
    target_channels: List[EscalationChannel] = field(default_factory=list)
    target_roles: List[str] = field(default_factory=list)
    target_users: List[str] = field(default_factory=list)
    notify_on_start: bool = True
    notify_on_resolve: bool = True
    require_acknowledgment: bool = True
    escalation_window_seconds: int = 0

    def matches_level(self, level: EscalationLevel) -> bool:
        return level in self.source_levels or not self.source_levels

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "source_levels": [l.value for l in self.source_levels],
            "target_channels": [c.value for c in self.target_channels],
        }


@dataclass
class EscalationRecord:
    """Full audit record for a single escalation event."""
    escalation_id: str
    source: str
    level: EscalationLevel
    trigger_type: EscalationTriggerType
    channel: EscalationChannel
    status: EscalationStatus
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_by: Optional[str] = None
    target: str = ""
    message: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    sla_deadline: Optional[datetime] = None
    sla_risk: SLARisk = SLARisk.ON_TRACK
    parent_escalation_id: Optional[str] = None
    child_escalation_ids: List[str] = field(default_factory=list)
    escalation_chain: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "level": self.level.value,
            "trigger_type": self.trigger_type.value,
            "channel": self.channel.value,
            "status": self.status.value,
            "sla_risk": self.sla_risk.value,
            "created_at": self.created_at.isoformat(),
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "sla_deadline": self.sla_deadline.isoformat() if self.sla_deadline else None,
        }


@dataclass
class ProtocolConfig:
    """Config-driven protocol definition."""
    protocol_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    sla_definitions: Dict[str, SLADefinition] = field(default_factory=dict)
    triggers: List[EscalationTrigger] = field(default_factory=list)
    routes: List[EscalationRoute] = field(default_factory=list)
    global_cooldown_seconds: int = 60
    max_concurrent_escalations: int = 50
    audit_enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_sla(self, level: EscalationLevel) -> Optional[SLADefinition]:
        return self.sla_definitions.get(level.value)

    def add_sla(self, sla: SLADefinition) -> None:
        self.sla_definitions[sla.level.value] = sla

    def add_trigger(self, trigger: EscalationTrigger) -> None:
        self.triggers.append(trigger)

    def add_route(self, route: EscalationRoute) -> None:
        self.routes.append(route)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "enabled": self.enabled,
            "sla_definitions": {k: v.to_dict() for k, v in self.sla_definitions.items()},
            "triggers": [t.to_dict() for t in self.triggers],
            "routes": [r.to_dict() for r in self.routes],
            "global_cooldown_seconds": self.global_cooldown_seconds,
            "max_concurrent_escalations": self.max_concurrent_escalations,
            "audit_enabled": self.audit_enabled,
            "metadata": self.metadata,
        }


class EscalationProtocols:
    """Multi-level escalation engine with SLA tracking, routing, and audit."""

    def __init__(self, config: Optional[ProtocolConfig] = None) -> None:
        self.logger = logger
        self.config = config or self._default_config()
        self._records: Dict[str, EscalationRecord] = {}
        self._active_escalations: Dict[str, EscalationRecord] = {}
        self._firing_counts: Dict[str, int] = {}
        self._firing_window: Dict[str, List[datetime]] = {}
        self._cooldowns: Dict[str, datetime] = {}
        self._sla_checkers: Dict[str, Callable] = {}
        self._level_order: List[EscalationLevel] = [
            EscalationLevel.LOW,
            EscalationLevel.MEDIUM,
            EscalationLevel.HIGH,
            EscalationLevel.CRITICAL,
        ]
        self._handlers: Dict[str, List[Callable]] = {
            "on_escalate": [],
            "on_acknowledge": [],
            "on_resolve": [],
            "on_sla_breach": [],
            "on_auto_escalate": [],
        }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _default_config() -> ProtocolConfig:
        config = ProtocolConfig(
            protocol_id="default_escalation",
            name="Default Escalation Protocol",
            description="Default multi-level escalation protocol with standard SLAs",
        )
        config.add_sla(SLADefinition.default_low())
        config.add_sla(SLADefinition.default_medium())
        config.add_sla(SLADefinition.default_high())
        config.add_sla(SLADefinition.default_critical())

        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_threshold_low",
            name="Low Threshold Breach",
            trigger_type=EscalationTriggerType.THRESHOLD,
            target_level=EscalationLevel.LOW,
            conditions={"min_violations": 5, "window_minutes": 60},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_threshold_medium",
            name="Medium Threshold Breach",
            trigger_type=EscalationTriggerType.THRESHOLD,
            target_level=EscalationLevel.MEDIUM,
            conditions={"min_violations": 10, "window_minutes": 60},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_threshold_high",
            name="High Threshold Breach",
            trigger_type=EscalationTriggerType.THRESHOLD,
            target_level=EscalationLevel.HIGH,
            conditions={"min_violations": 3, "window_minutes": 30, "severity": "high"},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_threshold_critical",
            name="Critical Threshold Breach",
            trigger_type=EscalationTriggerType.THRESHOLD,
            target_level=EscalationLevel.CRITICAL,
            conditions={"min_violations": 1, "window_minutes": 5, "severity": "critical"},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_time_low",
            name="Low Response Time Exceeded",
            trigger_type=EscalationTriggerType.TIME_BASED,
            target_level=EscalationLevel.LOW,
            conditions={"max_unresolved_hours": 48},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_pattern_security",
            name="Security Pattern Detected",
            trigger_type=EscalationTriggerType.PATTERN,
            target_level=EscalationLevel.CRITICAL,
            conditions={"patterns": ["sql_injection", "xss", "rce", "auth_bypass"]},
        ))
        config.add_trigger(EscalationTrigger(
            trigger_id="trigger_pattern_compliance",
            name="Compliance Pattern Detected",
            trigger_type=EscalationTriggerType.PATTERN,
            target_level=EscalationLevel.HIGH,
            conditions={"patterns": ["gdpr", "hipaa", "pci", "sox"]},
        ))

        config.add_route(EscalationRoute(
            route_id="route_low",
            name="Low Escalation Route",
            source_levels=[EscalationLevel.LOW],
            target_channels=[EscalationChannel.INTERNAL_TEAM],
            target_roles=["support"],
            target_users=[],
            require_acknowledgment=False,
        ))
        config.add_route(EscalationRoute(
            route_id="route_medium",
            name="Medium Escalation Route",
            source_levels=[EscalationLevel.MEDIUM],
            target_channels=[EscalationChannel.INTERNAL_TEAM, EscalationChannel.ADMIN],
            target_roles=["support", "engineering"],
            require_acknowledgment=True,
        ))
        config.add_route(EscalationRoute(
            route_id="route_high",
            name="High Escalation Route",
            source_levels=[EscalationLevel.HIGH],
            target_channels=[EscalationChannel.ADMIN, EscalationChannel.SECURITY],
            target_roles=["engineering", "security"],
            require_acknowledgment=True,
            escalation_window_seconds=600,
        ))
        config.add_route(EscalationRoute(
            route_id="route_critical",
            name="Critical Escalation Route",
            source_levels=[EscalationLevel.CRITICAL],
            target_channels=[
                EscalationChannel.ADMIN,
                EscalationChannel.SECURITY,
                EscalationChannel.LEGAL,
                EscalationChannel.EXECUTIVE,
            ],
            target_roles=["security", "engineering", "executive"],
            require_acknowledgment=True,
            escalation_window_seconds=120,
        ))

        return config

    def load_config(self, config: ProtocolConfig) -> None:
        self.config = config

    def update_config(self, **overrides: Any) -> None:
        for key, value in overrides.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def on_escalate(self, handler: Callable) -> None:
        self._handlers["on_escalate"].append(handler)

    def on_acknowledge(self, handler: Callable) -> None:
        self._handlers["on_acknowledge"].append(handler)

    def on_resolve(self, handler: Callable) -> None:
        self._handlers["on_resolve"].append(handler)

    def on_sla_breach(self, handler: Callable) -> None:
        self._handlers["on_sla_breach"].append(handler)

    def on_auto_escalate(self, handler: Callable) -> None:
        self._handlers["on_auto_escalate"].append(handler)

    def _fire_event(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception as exc:
                self.logger.error("Event handler %s failed: %s", event, exc)

    # ------------------------------------------------------------------
    # Rate Limiting & Cooldown
    # ------------------------------------------------------------------

    def _check_cooldown(self, trigger_id: str) -> bool:
        if trigger_id in self._cooldowns:
            if datetime.utcnow() < self._cooldowns[trigger_id]:
                return False
        return True

    def _set_cooldown(self, trigger_id: str, seconds: Optional[int] = None) -> None:
        secs = seconds or self.config.global_cooldown_seconds
        self._cooldowns[trigger_id] = datetime.utcnow() + timedelta(seconds=secs)

    def _check_rate_limit(self, trigger_id: str) -> bool:
        now = datetime.utcnow()
        window = self._firing_window.setdefault(trigger_id, [])
        cutoff = now - timedelta(hours=1)
        window[:] = [t for t in window if t > cutoff]
        triggers = [t for t in self.config.triggers if t.trigger_id == trigger_id]
        max_firings = triggers[0].max_firings_per_hour if triggers else 10
        if len(window) >= max_firings:
            return False
        window.append(now)
        return True

    def _get_firing_count(self, window_minutes: int = 60) -> int:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        return sum(
            1 for r in self._records.values()
            if r.created_at > cutoff
        )

    # ------------------------------------------------------------------
    # Escalation Core
    # ------------------------------------------------------------------

    def escalate(
        self,
        issue: Dict[str, Any],
        level: Union[str, EscalationLevel],
        source: str = "system",
        channel: Optional[EscalationChannel] = None,
        context: Optional[Dict[str, Any]] = None,
        trigger_type: EscalationTriggerType = EscalationTriggerType.AUTOMATIC,
    ) -> EscalationRecord:
        if isinstance(level, str):
            level = EscalationLevel(level)
        if not self.config.enabled:
            self.logger.warning("Escalation protocol is disabled; dropping escalation")
            raise RuntimeError("Escalation protocol is disabled")
        if len(self._active_escalations) >= self.config.max_concurrent_escalations:
            self.logger.warning("Max concurrent escalations reached (%s)", self.config.max_concurrent_escalations)
            raise RuntimeError("Max concurrent escalations reached")

        sla = self.config.get_sla(level)
        sla_deadline = None
        if sla:
            sla_deadline = datetime.utcnow() + timedelta(minutes=sla.response_time_minutes)

        escalation_id = self._generate_id(issue, level)
        routes = self._resolve_routes(level)
        resolved_channel = channel or (routes[0].target_channels[0] if routes else EscalationChannel.INTERNAL_TEAM)

        record = EscalationRecord(
            escalation_id=escalation_id,
            source=source,
            level=level,
            trigger_type=trigger_type,
            channel=resolved_channel,
            status=EscalationStatus.PENDING,
            created_at=datetime.utcnow(),
            target=self._resolve_target(routes, level),
            message=issue.get("message", str(issue)),
            context=context or {},
            sla_deadline=sla_deadline,
            escalation_chain=[escalation_id],
            metadata={"issue": issue},
        )
        self._records[escalation_id] = record
        self._active_escalations[escalation_id] = record
        self._firing_counts[escalation_id] = self._firing_counts.get(escalation_id, 0) + 1
        self.logger.info(
            "Escalation created: id=%s level=%s channel=%s source=%s",
            escalation_id, level.value, resolved_channel.value, source,
        )
        self._fire_event("on_escalate", record=record, issue=issue)
        return record

    def acknowledge(self, escalation_id: str, user: str) -> Optional[EscalationRecord]:
        record = self._records.get(escalation_id)
        if not record:
            self.logger.warning("Escalation not found: %s", escalation_id)
            return None
        if record.status in (EscalationStatus.RESOLVED, EscalationStatus.CLOSED, EscalationStatus.CANCELLED):
            self.logger.warning("Cannot acknowledge %s escalation: %s", record.status.value, escalation_id)
            return None
        record.status = EscalationStatus.ACKNOWLEDGED
        record.acknowledged_at = datetime.utcnow()
        record.acknowledged_by = user
        self._fire_event("on_acknowledge", record=record, user=user)
        self.logger.info("Escalation %s acknowledged by %s", escalation_id, user)
        return record

    def resolve(
        self,
        escalation_id: str,
        user: str,
        resolution_notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[EscalationRecord]:
        record = self._records.get(escalation_id)
        if not record:
            self.logger.warning("Escalation not found: %s", escalation_id)
            return None
        if record.status == EscalationStatus.CLOSED:
            self.logger.warning("Escalation already closed: %s", escalation_id)
            return None
        record.status = EscalationStatus.RESOLVED
        record.resolved_at = datetime.utcnow()
        record.resolved_by = user
        if resolution_notes:
            record.context["resolution_notes"] = resolution_notes
        if metadata:
            record.metadata.update(metadata)
        self._active_escalations.pop(escalation_id, None)
        self._fire_event("on_resolve", record=record, user=user)
        self.logger.info("Escalation %s resolved by %s", escalation_id, user)
        return record

    def close(self, escalation_id: str, user: str, reason: Optional[str] = None) -> Optional[EscalationRecord]:
        record = self._records.get(escalation_id)
        if not record:
            self.logger.warning("Escalation not found: %s", escalation_id)
            return None
        record.status = EscalationStatus.CLOSED
        if reason:
            record.context["closure_reason"] = reason
        self._active_escalations.pop(escalation_id, None)
        self.logger.info("Escalation %s closed by %s", escalation_id, user)
        return record

    def cancel(self, escalation_id: str, user: str, reason: Optional[str] = None) -> Optional[EscalationRecord]:
        record = self._records.get(escalation_id)
        if not record:
            self.logger.warning("Escalation not found: %s", escalation_id)
            return None
        record.status = EscalationStatus.CANCELLED
        if reason:
            record.context["cancellation_reason"] = reason
        self._active_escalations.pop(escalation_id, None)
        self.logger.info("Escalation %s cancelled by %s", escalation_id, user)
        return record

    # ------------------------------------------------------------------
    # Trigger Evaluation
    # ------------------------------------------------------------------

    def evaluate_triggers(
        self,
        violations: List[Violation],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[EscalationRecord]:
        records: List[EscalationRecord] = []
        context = context or {}
        current_level = self._determine_base_level(violations)

        for trigger in self.config.triggers:
            if not trigger.enabled:
                continue
            if not self._check_cooldown(trigger.trigger_id):
                continue
            if not self._check_rate_limit(trigger.trigger_id):
                continue
            if trigger.trigger_type == EscalationTriggerType.THRESHOLD:
                if self._evaluate_threshold_trigger(trigger, violations, context):
                    record = self.escalate(
                        issue={"message": f"Threshold trigger: {trigger.name}", "violations": [v.dict() for v in violations]},
                        level=trigger.target_level,
                        source="trigger_evaluator",
                        context=context,
                        trigger_type=EscalationTriggerType.THRESHOLD,
                    )
                    records.append(record)
                    self._set_cooldown(trigger.trigger_id, trigger.cooldown_seconds)
            elif trigger.trigger_type == EscalationTriggerType.PATTERN:
                if self._evaluate_pattern_trigger(trigger, violations, context):
                    record = self.escalate(
                        issue={"message": f"Pattern trigger: {trigger.name}", "violations": [v.dict() for v in violations]},
                        level=trigger.target_level,
                        source="trigger_evaluator",
                        context=context,
                        trigger_type=EscalationTriggerType.PATTERN,
                    )
                    records.append(record)
                    self._set_cooldown(trigger.trigger_id, trigger.cooldown_seconds)
            elif trigger.trigger_type == EscalationTriggerType.TIME_BASED:
                if self._evaluate_time_trigger(trigger, violations, context):
                    record = self.escalate(
                        issue={"message": f"Time-based trigger: {trigger.name}", "violations": [v.dict() for v in violations]},
                        level=trigger.target_level,
                        source="trigger_evaluator",
                        context=context,
                        trigger_type=EscalationTriggerType.TIME_BASED,
                    )
                    records.append(record)
                    self._set_cooldown(trigger.trigger_id, trigger.cooldown_seconds)
        return records

    def _determine_base_level(self, violations: List[Violation]) -> EscalationLevel:
        if any(v.rule_severity == RuleSeverity.CRITICAL for v in violations):
            return EscalationLevel.CRITICAL
        if any(v.rule_severity == RuleSeverity.HIGH for v in violations):
            return EscalationLevel.HIGH
        if any(v.rule_severity == RuleSeverity.MEDIUM for v in violations):
            return EscalationLevel.MEDIUM
        return EscalationLevel.LOW

    def _evaluate_threshold_trigger(
        self,
        trigger: EscalationTrigger,
        violations: List[Violation],
        context: Dict[str, Any],
    ) -> bool:
        conditions = trigger.conditions
        min_violations = conditions.get("min_violations", 1)
        window_minutes = conditions.get("window_minutes", 60)
        severity_filter = conditions.get("severity")

        matched = violations
        if severity_filter:
            severity = RuleSeverity(severity_filter)
            matched = [v for v in matched if v.rule_severity == severity]

        if len(matched) < min_violations:
            return False
        recent = [
            v for v in matched
            if (datetime.utcnow() - v.detected_at).total_seconds() / 60 <= window_minutes
        ]
        return len(recent) >= min_violations

    def _evaluate_pattern_trigger(
        self,
        trigger: EscalationTrigger,
        violations: List[Violation],
        context: Dict[str, Any],
    ) -> bool:
        patterns = trigger.conditions.get("patterns", [])
        for violation in violations:
            if violation.violation_type.value in patterns:
                return True
            if any(p in (violation.matched_content or "").lower() for p in patterns):
                return True
            if any(p in (violation.explanation or "").lower() for p in patterns):
                return True
        return False

    def _evaluate_time_trigger(
        self,
        trigger: EscalationTrigger,
        violations: List[Violation],
        context: Dict[str, Any],
    ) -> bool:
        max_unresolved_hours = trigger.conditions.get("max_unresolved_hours", 24)
        cutoff = datetime.utcnow() - timedelta(hours=max_unresolved_hours)
        for rec in self._active_escalations.values():
            if rec.created_at < cutoff:
                return True
        return False

    # ------------------------------------------------------------------
    # Routing & SLA
    # ------------------------------------------------------------------

    def _resolve_routes(self, level: EscalationLevel) -> List[EscalationRoute]:
        return [r for r in self.config.routes if r.matches_level(level)]

    def _resolve_target(self, routes: List[EscalationRoute], level: EscalationLevel) -> str:
        for route in routes:
            if route.target_roles:
                return f"roles:{','.join(route.target_roles)}"
            if route.target_users:
                return f"users:{','.join(route.target_users)}"
        return f"default:{level.value}_team"

    def check_sla(self, escalation_id: str) -> SLARisk:
        record = self._records.get(escalation_id)
        if not record or not record.sla_deadline:
            return SLARisk.ON_TRACK
        now = datetime.utcnow()
        if now > record.sla_deadline:
            record.sla_risk = SLARisk.BREACHED
            self._fire_event("on_sla_breach", record=record)
            return SLARisk.BREACHED
        remaining = (record.sla_deadline - now).total_seconds()
        sla = self.config.get_sla(record.level)
        if sla and remaining < sla.response_time_minutes * 60 * 0.2:
            record.sla_risk = SLARisk.AT_RISK
            return SLARisk.AT_RISK
        record.sla_risk = SLARisk.ON_TRACK
        return SLARisk.ON_TRACK

    def check_all_slas(self) -> Dict[str, SLARisk]:
        results = {}
        for eid in list(self._active_escalations.keys()):
            results[eid] = self.check_sla(eid)
        return results

    def handle_sla_breaches(self) -> List[EscalationRecord]:
        breached: List[EscalationRecord] = []
        for eid in list(self._active_escalations.keys()):
            risk = self.check_sla(eid)
            if risk == SLARisk.BREACHED:
                record = self._records[eid]
                sla = self.config.get_sla(record.level)
                if sla and sla.auto_escalate_to and sla.auto_escalate_after_minutes:
                    new_record = self.escalate(
                        issue={"message": f"SLA breach auto-escalation from {record.level.value}",
                               "parent_escalation_id": eid},
                        level=sla.auto_escalate_to,
                        source="sla_monitor",
                        context=record.context,
                        trigger_type=EscalationTriggerType.AUTOMATIC,
                    )
                    record.child_escalation_ids.append(new_record.escalation_id)
                    new_record.parent_escalation_id = eid
                    new_record.escalation_chain = record.escalation_chain + [new_record.escalation_id]
                    record.status = EscalationStatus.ESCALATED_FURTHER
                    self._fire_event("on_auto_escalate", source_record=record, target_record=new_record)
                    breached.append(new_record)
                self.logger.warning("SLA breached for escalation %s at level %s", eid, record.level.value)
        return breached

    # ------------------------------------------------------------------
    # Query & Audit
    # ------------------------------------------------------------------

    def get_record(self, escalation_id: str) -> Optional[EscalationRecord]:
        return self._records.get(escalation_id)

    def get_active_escalations(self, level: Optional[EscalationLevel] = None) -> List[EscalationRecord]:
        if level:
            return [r for r in self._active_escalations.values() if r.level == level]
        return list(self._active_escalations.values())

    def get_escalations_by_source(self, source: str) -> List[EscalationRecord]:
        return [r for r in self._records.values() if r.source == source]

    def get_escalations_by_status(self, status: EscalationStatus) -> List[EscalationRecord]:
        return [r for r in self._records.values() if r.status == status]

    def get_escalations_by_level(self, level: EscalationLevel) -> List[EscalationRecord]:
        return [r for r in self._records.values() if r.level == level]

    def get_escalation_chain(self, escalation_id: str) -> List[EscalationRecord]:
        records = []
        current = self._records.get(escalation_id)
        while current:
            records.append(current)
            if current.parent_escalation_id:
                current = self._records.get(current.parent_escalation_id)
            else:
                break
        return records

    def search_escalations(
        self,
        query: Optional[str] = None,
        level: Optional[EscalationLevel] = None,
        status: Optional[EscalationStatus] = None,
        source: Optional[str] = None,
        channel: Optional[EscalationChannel] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[EscalationRecord]:
        results = list(self._records.values())
        if query:
            q = query.lower()
            results = [r for r in results if q in r.message.lower() or q in r.escalation_id.lower()]
        if level:
            results = [r for r in results if r.level == level]
        if status:
            results = [r for r in results if r.status == status]
        if source:
            results = [r for r in results if r.source == source]
        if channel:
            results = [r for r in results if r.channel == channel]
        if start_time:
            results = [r for r in results if r.created_at >= start_time]
        if end_time:
            results = [r for r in results if r.created_at <= end_time]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def get_audit_trail(self, escalation_id: str) -> Dict[str, Any]:
        record = self._records.get(escalation_id)
        if not record:
            return {}
        trail: Dict[str, Any] = {
            "escalation_id": escalation_id,
            "events": [],
        }
        trail["events"].append({
            "timestamp": record.created_at.isoformat(),
            "event": "created",
            "level": record.level.value,
            "channel": record.channel.value,
            "source": record.source,
            "trigger_type": record.trigger_type.value,
        })
        if record.acknowledged_at:
            trail["events"].append({
                "timestamp": record.acknowledged_at.isoformat(),
                "event": "acknowledged",
                "by": record.acknowledged_by,
            })
        if record.resolved_at:
            trail["events"].append({
                "timestamp": record.resolved_at.isoformat(),
                "event": "resolved",
                "by": record.resolved_by,
            })
        sla_checks = []
        if record.sla_deadline:
            sla_checks.append({
                "deadline": record.sla_deadline.isoformat(),
                "risk": record.sla_risk.value,
                "breached": record.sla_risk == SLARisk.BREACHED,
            })
        trail["sla_checks"] = sla_checks
        trail["child_escalations"] = record.child_escalation_ids
        trail["parent_escalation"] = record.parent_escalation_id
        trail["chain_length"] = len(record.escalation_chain)
        trail["metadata"] = record.metadata
        return trail

    def generate_audit_report(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        records = list(self._records.values())
        if start_time:
            records = [r for r in records if r.created_at >= start_time]
        if end_time:
            records = [r for r in records if r.created_at <= end_time]

        total = len(records)
        by_level: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        by_channel: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        sla_breaches = 0
        avg_resolution_seconds: Optional[float] = None
        resolution_times: List[float] = []

        for rec in records:
            by_level[rec.level.value] = by_level.get(rec.level.value, 0) + 1
            by_status[rec.status.value] = by_status.get(rec.status.value, 0) + 1
            by_channel[rec.channel.value] = by_channel.get(rec.channel.value, 0) + 1
            by_source[rec.source] = by_source.get(rec.source, 0) + 1
            if rec.sla_risk == SLARisk.BREACHED:
                sla_breaches += 1
            if rec.resolved_at and rec.created_at:
                delta = (rec.resolved_at - rec.created_at).total_seconds()
                resolution_times.append(delta)

        if resolution_times:
            avg_resolution_seconds = sum(resolution_times) / len(resolution_times)

        return {
            "report_period": {
                "start": start_time.isoformat() if start_time else None,
                "end": end_time.isoformat() if end_time else None,
            },
            "total_escalations": total,
            "active_escalations": len(self._active_escalations),
            "by_level": by_level,
            "by_status": by_status,
            "by_channel": by_channel,
            "by_source": by_source,
            "sla_breaches": sla_breaches,
            "sla_breach_rate": round(sla_breaches / total * 100, 2) if total else 0.0,
            "avg_resolution_seconds": round(avg_resolution_seconds, 2) if avg_resolution_seconds else None,
            "escalation_chain_count": sum(1 for r in records if len(r.escalation_chain) > 1),
        }

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._records)
        active = len(self._active_escalations)
        resolved = len(self.get_escalations_by_status(EscalationStatus.RESOLVED))
        breached = sum(1 for r in self._records.values() if r.sla_risk == SLARisk.BREACHED)
        levels = [r.level.value for r in self._records.values()]
        level_counts = {lvl: levels.count(lvl) for lvl in set(levels)}
        return {
            "total_escalations": total,
            "active_escalations": active,
            "resolved_escalations": resolved,
            "sla_breaches": breached,
            "sla_compliance_rate": round((1 - breached / total) * 100, 2) if total else 100.0,
            "escalations_by_level": level_counts,
            "avg_chain_length": round(
                sum(len(r.escalation_chain) for r in self._records.values()) / total, 2
            ) if total else 0.0,
            "concurrent_escalations": active,
            "max_concurrent": self.config.max_concurrent_escalations,
        }

    def get_level_statistics(self, level: EscalationLevel) -> Dict[str, Any]:
        level_records = self.get_escalations_by_level(level)
        total = len(level_records)
        if total == 0:
            return {"level": level.value, "total": 0}
        sla = self.config.get_sla(level)
        resolved = sum(1 for r in level_records if r.status == EscalationStatus.RESOLVED)
        breached = sum(1 for r in level_records if r.sla_risk == SLARisk.BREACHED)
        resolution_times = [
            (r.resolved_at - r.created_at).total_seconds()
            for r in level_records if r.resolved_at and r.created_at
        ]
        return {
            "level": level.value,
            "total": total,
            "active": sum(1 for r in level_records if r.status not in (EscalationStatus.RESOLVED, EscalationStatus.CLOSED, EscalationStatus.CANCELLED)),
            "resolved": resolved,
            "sla_breaches": breached,
            "sla_target_response_minutes": sla.response_time_minutes if sla else None,
            "sla_target_resolution_minutes": sla.resolution_time_minutes if sla else None,
            "avg_resolution_seconds": round(sum(resolution_times) / len(resolution_times), 2) if resolution_times else None,
            "resolution_rate": round(resolved / total * 100, 2) if total else 0.0,
            "sla_breach_rate": round(breached / total * 100, 2) if total else 0.0,
        }

    def get_trend_data(self, days: int = 30) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [r for r in self._records.values() if r.created_at >= cutoff]
        daily_counts: Dict[str, int] = {}
        level_trend: Dict[str, Dict[str, int]] = {}
        for rec in recent:
            date_key = rec.created_at.strftime("%Y-%m-%d")
            daily_counts[date_key] = daily_counts.get(date_key, 0) + 1
            lvl = rec.level.value
            if lvl not in level_trend:
                level_trend[lvl] = {}
            level_trend[lvl][date_key] = level_trend[lvl].get(date_key, 0) + 1
        return {
            "period_days": days,
            "total_in_period": len(recent),
            "daily_counts": daily_counts,
            "level_trend": level_trend,
            "avg_daily": round(len(recent) / days, 2) if days else 0.0,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id(issue: Dict[str, Any], level: EscalationLevel) -> str:
        raw = f"{json.dumps(issue, sort_keys=True, default=str)}:{level.value}:{datetime.utcnow().isoformat()}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:12]
        return f"esc_{h}"

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, escalation_id: str) -> bool:
        return escalation_id in self._records

    def __iter__(self):
        return iter(self._records.values())
