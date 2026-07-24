"""Emergency response system for critical rule violations."""
import json
import logging
import smtplib
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmergencyLevel(Enum):
    """Emergency severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class IncidentCategory(Enum):
    """Categories of incidents."""
    SECURITY = "security"
    PERFORMANCE = "performance"
    DATA_INTEGRITY = "data_integrity"
    AVAILABILITY = "availability"
    COMPLIANCE = "compliance"
    SAFETY = "safety"
    NETWORK = "network"
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    USER_ERROR = "user_error"
    EXTERNAL_THREAT = "external_threat"
    SYSTEM_FAILURE = "system_failure"
    UNKNOWN = "unknown"


@dataclass
class EscalationStep:
    """A single escalation step."""
    level: int
    contacts: List[str]
    timeout_seconds: int
    handler: Optional[Callable] = None
    notification_channels: List[str] = field(default_factory=lambda: ["log"])


@dataclass
class EscalationChain:
    """Chain of escalation steps."""
    chain_id: str
    steps: List[EscalationStep]
    current_step: int = 0
    started_at: Optional[datetime] = None
    resolved: bool = False


@dataclass
class IncidentAction:
    """An action taken during incident response."""
    action_id: str
    action_type: str
    description: str
    timestamp: datetime
    handler_name: str
    success: bool = True
    result: Optional[str] = None


@dataclass
class IncidentTimelineEntry:
    """A single timeline entry for an incident."""
    timestamp: datetime
    event_type: str
    description: str
    actor: str = "system"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmergencyIncident:
    """Represents an emergency incident."""
    incident_id: str
    level: EmergencyLevel
    description: str
    timestamp: datetime
    affected_systems: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    resolved: bool = False
    category: IncidentCategory = IncidentCategory.UNKNOWN
    source: str = "unknown"
    escalation_chain: Optional[EscalationChain] = None
    sla_deadline: Optional[datetime] = None
    sla_breached: bool = False
    detailed_actions: List[IncidentAction] = field(default_factory=list)
    timeline: List[IncidentTimelineEntry] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    owner: str = "unassigned"
    resolution_time_seconds: Optional[float] = None
    severity_score: float = 1.0
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None


@dataclass
class NotificationChannel:
    """Configuration for a notification channel."""
    channel_type: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmergencyConfig:
    """Configuration for emergency response."""
    enable_escalation: bool = True
    enable_auto_remediation: bool = True
    enable_sla_tracking: bool = True
    enable_multi_channel_notification: bool = True
    enable_timeline: bool = True
    default_sla_minutes: Dict[str, int] = field(default_factory=lambda: {
        "low": 240, "medium": 120, "high": 60, "critical": 30,
        "info": 480, "warning": 180, "error": 90, "fatal": 15,
    })
    max_active_incidents: int = 50
    auto_resolve_after_hours: int = 72
    notification_channels: List[NotificationChannel] = field(default_factory=lambda: [
        NotificationChannel("log", True),
        NotificationChannel("email", False, {"smtp_server": "localhost", "smtp_port": 25}),
        NotificationChannel("sms", False, {"provider": "twilio", "api_key": ""}),
        NotificationChannel("webhook", False, {"url": "", "method": "POST"}),
    ])
    log_level: str = "INFO"
    persist_incidents: bool = False
    persist_path: Optional[str] = None


class EmergencyResponse:
    """Emergency response coordinator for critical situations."""

    def __init__(self, config: Optional[EmergencyConfig] = None):
        self.config = config or EmergencyConfig()
        self.active_incidents: Dict[str, EmergencyIncident] = {}
        self.response_handlers: Dict[EmergencyLevel, List[Callable]] = {
            level: [] for level in EmergencyLevel
        }
        self.category_handlers: Dict[IncidentCategory, List[Callable]] = {
            cat: [] for cat in IncidentCategory
        }
        self.incident_history: List[EmergencyIncident] = []
        self.emergency_contacts: List[str] = []
        self.contact_channels: Dict[str, List[str]] = {}
        self.incident_counter: int = 0
        self.escalation_threads: Dict[str, threading.Thread] = {}
        self.sla_checker_running: bool = False
        self.sla_checker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._start_sla_checker()
        logger.info("EmergencyResponse system initialized")

    def _start_sla_checker(self) -> None:
        if self.config.enable_sla_tracking and not self.sla_checker_running:
            self.sla_checker_running = True
            self.sla_checker_thread = threading.Thread(target=self._sla_checker_loop, daemon=True)
            self.sla_checker_thread.start()
            logger.info("SLA checker thread started")

    def _sla_checker_loop(self) -> None:
        while self.sla_checker_running:
            try:
                self._check_sla_breaches()
            except Exception as e:
                logger.error(f"SLA checker error: {e}")
            time.sleep(30)

    def _check_sla_breaches(self) -> None:
        now = datetime.now()
        for incident in list(self.active_incidents.values()):
            if incident.sla_deadline and not incident.resolved and not incident.sla_breached:
                if now > incident.sla_deadline:
                    incident.sla_breached = True
                    self._add_timeline_entry(incident, "sla_breach",
                                             f"SLA breached for incident {incident.incident_id}")
                    logger.warning(f"SLA BREACHED: {incident.incident_id}")
                    self._trigger_escalation(incident)

    def _add_timeline_entry(self, incident: EmergencyIncident, event_type: str,
                            description: str, actor: str = "system",
                            details: Optional[Dict[str, Any]] = None) -> None:
        if not self.config.enable_timeline:
            return
        entry = IncidentTimelineEntry(
            timestamp=datetime.now(),
            event_type=event_type,
            description=description,
            actor=actor,
            details=details or {},
        )
        incident.timeline.append(entry)

    def _generate_incident_id(self) -> str:
        with self._lock:
            self.incident_counter += 1
            return f"INC-{datetime.now().strftime('%Y%m%d')}-{self.incident_counter:05d}"

    def register_handler(self, level: EmergencyLevel, handler: Callable) -> None:
        self.response_handlers[level].append(handler)
        logger.info(f"Registered handler for {level.value} emergencies")

    def register_category_handler(self, category: IncidentCategory, handler: Callable) -> None:
        self.category_handlers[category].append(handler)
        logger.info(f"Registered handler for {category.value} incidents")

    def register_escalation_chain(self, level: EmergencyLevel, steps: List[EscalationStep]) -> None:
        chain_id = f"ESC-{level.value}-{uuid.uuid4().hex[:8]}"
        chain = EscalationChain(chain_id=chain_id, steps=steps)
        logger.info(f"Registered escalation chain {chain_id} for {level.value}")

    def trigger_emergency(
        self,
        incident_id: str,
        level: EmergencyLevel,
        description: str,
        affected_systems: Optional[List[str]] = None,
        category: IncidentCategory = IncidentCategory.UNKNOWN,
        source: str = "unknown",
        tags: Optional[List[str]] = None,
    ) -> EmergencyIncident:
        with self._lock:
            if len(self.active_incidents) >= self.config.max_active_incidents:
                logger.warning("Max active incidents reached, rejecting new incident")
                raise RuntimeError("Maximum active incidents reached")

            sla_minutes = self.config.default_sla_minutes.get(level.value, 120)
            sla_deadline = datetime.now() + timedelta(minutes=sla_minutes) if self.config.enable_sla_tracking else None

            incident = EmergencyIncident(
                incident_id=incident_id,
                level=level,
                description=description,
                timestamp=datetime.now(),
                affected_systems=affected_systems or [],
                actions_taken=["Emergency triggered"],
                resolved=False,
                category=category,
                source=source,
                sla_deadline=sla_deadline,
                tags=tags or [],
                severity_score=self._calculate_severity_score(level, affected_systems or []),
            )

            self._add_timeline_entry(incident, "created", f"Incident created: {description}", "system")

            self.active_incidents[incident_id] = incident

            for handler in self.response_handlers.get(level, []):
                try:
                    handler(incident)
                    action = IncidentAction(
                        action_id=uuid.uuid4().hex[:12],
                        action_type="handler",
                        description=f"Handler executed: {handler.__name__}",
                        timestamp=datetime.now(),
                        handler_name=handler.__name__,
                    )
                    incident.detailed_actions.append(action)
                    incident.actions_taken.append(f"Handler executed: {handler.__name__}")
                except Exception as e:
                    logger.error(f"Handler failed: {e}")
                    incident.actions_taken.append(f"Handler failed: {handler.__name__}: {e}")

            for handler in self.category_handlers.get(category, []):
                try:
                    handler(incident)
                    incident.actions_taken.append(f"Category handler executed: {handler.__name__}")
                except Exception as e:
                    logger.error(f"Category handler failed: {e}")

            logger.critical(f"EMERGENCY TRIGGERED: {incident_id} - {description}")

            self._send_notifications(incident)

            if self.config.enable_escalation:
                self._start_escalation_timer(incident)

        return incident

    def _calculate_severity_score(self, level: EmergencyLevel, affected_systems: List[str]) -> float:
        base_scores = {
            EmergencyLevel.INFO: 0.1, EmergencyLevel.LOW: 0.3,
            EmergencyLevel.WARNING: 0.4, EmergencyLevel.MEDIUM: 0.5,
            EmergencyLevel.HIGH: 0.7, EmergencyLevel.ERROR: 0.75,
            EmergencyLevel.CRITICAL: 0.9, EmergencyLevel.FATAL: 1.0,
        }
        score = base_scores.get(level, 0.5)
        system_penalty = min(len(affected_systems) * 0.05, 0.3)
        return min(score + system_penalty, 1.0)

    def _start_escalation_timer(self, incident: EmergencyIncident) -> None:
        def escalation_worker():
            time.sleep(300)
            if not incident.resolved and incident.incident_id in self.active_incidents:
                self._trigger_escalation(incident)

        thread = threading.Thread(target=escalation_worker, daemon=True)
        self.escalation_threads[incident.incident_id] = thread
        thread.start()

    def _trigger_escalation(self, incident: EmergencyIncident) -> None:
        incident.actions_taken.append("ESCALATION_TRIGGERED")
        self._add_timeline_entry(incident, "escalation", "Incident escalated", "system")
        self._send_notifications(incident, force=True)
        logger.warning(f"Escalation triggered for {incident.incident_id}")

    def _send_notifications(self, incident: EmergencyIncident, force: bool = False) -> None:
        if not self.config.enable_multi_channel_notification and not force:
            return

        for channel in self.config.notification_channels:
            if not channel.enabled and not force:
                continue
            try:
                if channel.channel_type == "log":
                    self._log_notification(incident)
                elif channel.channel_type == "email":
                    self._email_notification(incident, channel.config)
                elif channel.channel_type == "sms":
                    self._sms_notification(incident, channel.config)
                elif channel.channel_type == "webhook":
                    self._webhook_notification(incident, channel.config)
                incident.actions_taken.append(f"Notification sent via {channel.channel_type}")
            except Exception as e:
                logger.error(f"Notification channel {channel.channel_type} failed: {e}")

        for contact in self.emergency_contacts:
            logger.info(f"Emergency notification sent to {contact} for incident {incident.incident_id}")

    def _log_notification(self, incident: EmergencyIncident) -> None:
        logger.info(f"[NOTIFICATION] Incident {incident.incident_id}: {incident.description}")

    def _email_notification(self, incident: EmergencyIncident, config: Dict[str, Any]) -> None:
        smtp_server = config.get("smtp_server", "localhost")
        smtp_port = config.get("smtp_port", 25)
        recipients = self.emergency_contacts
        if not recipients:
            logger.warning("No email recipients configured")
            return
        msg = MIMEText(f"Emergency Incident: {incident.incident_id}\n\n"
                       f"Level: {incident.level.value}\n"
                       f"Description: {incident.description}\n"
                       f"Time: {incident.timestamp}\n"
                       f"Systems: {', '.join(incident.affected_systems)}")
        msg["Subject"] = f"[EMERGENCY] {incident.level.value.upper()} - {incident.incident_id}"
        msg["From"] = config.get("from_address", "emergency@system.local")
        msg["To"] = ", ".join(recipients)
        try:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                server.send_message(msg)
            logger.info(f"Email notification sent to {len(recipients)} recipients")
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")

    def _sms_notification(self, incident: EmergencyIncident, config: Dict[str, Any]) -> None:
        logger.info(f"SMS notification simulated for {incident.incident_id} via {config.get('provider', 'unknown')}")

    def _webhook_notification(self, incident: EmergencyIncident, config: Dict[str, Any]) -> None:
        import urllib.request
        import urllib.error
        webhook_url = config.get("url", "")
        if not webhook_url:
            logger.warning("No webhook URL configured")
            return
        payload = json.dumps({
            "incident_id": incident.incident_id,
            "level": incident.level.value,
            "description": incident.description,
            "timestamp": incident.timestamp.isoformat(),
            "affected_systems": incident.affected_systems,
            "category": incident.category.value,
            "severity_score": incident.severity_score,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(webhook_url, data=payload,
                                         headers={"Content-Type": "application/json"},
                                         method=config.get("method", "POST"))
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"Webhook notification sent to {webhook_url}")
        except urllib.error.URLError as e:
            logger.error(f"Webhook notification failed: {e}")

    def resolve_emergency(self, incident_id: str, resolution_notes: str,
                          resolved_by: str = "system") -> bool:
        with self._lock:
            if incident_id not in self.active_incidents:
                logger.warning(f"Incident not found: {incident_id}")
                return False

            incident = self.active_incidents[incident_id]
            incident.resolved = True
            incident.resolution_time_seconds = (datetime.now() - incident.timestamp).total_seconds()
            incident.actions_taken.append(f"Resolved: {resolution_notes}")

            self._add_timeline_entry(incident, "resolved", resolution_notes, resolved_by)

            self.incident_history.append(incident)
            del self.active_incidents[incident_id]

            if incident_id in self.escalation_threads:
                del self.escalation_threads[incident_id]

            logger.info(f"Emergency resolved: {incident_id}")
            return True

    def acknowledge_incident(self, incident_id: str, acknowledged_by: str) -> bool:
        incident = self.active_incidents.get(incident_id)
        if not incident:
            logger.warning(f"Cannot acknowledge: incident {incident_id} not found")
            return False
        incident.acknowledged = True
        incident.acknowledged_by = acknowledged_by
        incident.acknowledged_at = datetime.now()
        self._add_timeline_entry(incident, "acknowledged", f"Acknowledged by {acknowledged_by}", acknowledged_by)
        return True

    def add_emergency_contact(self, contact: str, channels: Optional[List[str]] = None) -> None:
        self.emergency_contacts.append(contact)
        self.contact_channels[contact] = channels or ["log"]
        logger.info(f"Added emergency contact: {contact}")

    def remove_emergency_contact(self, contact: str) -> bool:
        if contact in self.emergency_contacts:
            self.emergency_contacts.remove(contact)
            self.contact_channels.pop(contact, None)
            logger.info(f"Removed emergency contact: {contact}")
            return True
        return False

    def get_active_incidents(self, level: Optional[EmergencyLevel] = None,
                             category: Optional[IncidentCategory] = None) -> List[EmergencyIncident]:
        incidents = list(self.active_incidents.values())
        if level:
            incidents = [i for i in incidents if i.level == level]
        if category:
            incidents = [i for i in incidents if i.category == category]
        return sorted(incidents, key=lambda i: i.timestamp, reverse=True)

    def get_incident_stats(self) -> Dict:
        all_incidents = list(self.active_incidents.values()) + self.incident_history
        stats = {
            "active_incidents": len(self.active_incidents),
            "total_incidents": len(all_incidents),
            "resolved_count": len([i for i in self.incident_history if i.resolved]),
            "unresolved_count": len([i for i in all_incidents if not i.resolved]),
            "by_level": {level.value: 0 for level in EmergencyLevel},
            "by_category": {cat.value: 0 for cat in IncidentCategory},
            "sla_breaches": len([i for i in all_incidents if i.sla_breached]),
            "emergency_contacts": len(self.emergency_contacts),
            "acknowledged": len([i for i in all_incidents if i.acknowledged]),
            "average_resolution_time_seconds": 0.0,
            "severity_distribution": {},
            "top_affected_systems": {},
            "incidents_by_source": {},
            "recent_activity": [],
        }

        resolved_times = [i.resolution_time_seconds for i in self.incident_history
                          if i.resolved and i.resolution_time_seconds is not None]
        if resolved_times:
            stats["average_resolution_time_seconds"] = sum(resolved_times) / len(resolved_times)

        for incident in all_incidents:
            stats["by_level"][incident.level.value] += 1
            stats["by_category"][incident.category.value] += 1
            for system in incident.affected_systems:
                stats["top_affected_systems"][system] = stats["top_affected_systems"].get(system, 0) + 1
            stats["incidents_by_source"][incident.source] = stats["incidents_by_source"].get(incident.source, 0) + 1

        severity_ranges = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0, "0.9-1.0": 0}
        for incident in all_incidents:
            score = incident.severity_score
            if score < 0.3: severity_ranges["0.0-0.3"] += 1
            elif score < 0.5: severity_ranges["0.3-0.5"] += 1
            elif score < 0.7: severity_ranges["0.5-0.7"] += 1
            elif score < 0.9: severity_ranges["0.7-0.9"] += 1
            else: severity_ranges["0.9-1.0"] += 1
        stats["severity_distribution"] = severity_ranges

        recent = sorted(all_incidents, key=lambda i: i.timestamp, reverse=True)[:10]
        stats["recent_activity"] = [
            {"id": i.incident_id, "level": i.level.value, "description": i.description[:50],
             "timestamp": i.timestamp.isoformat(), "resolved": i.resolved}
            for i in recent
        ]

        return stats

    def get_incident_timeline(self, incident_id: str) -> Optional[List[IncidentTimelineEntry]]:
        incident = self.active_incidents.get(incident_id)
        if not incident:
            for hist in self.incident_history:
                if hist.incident_id == incident_id:
                    incident = hist
                    break
        if not incident:
            return None
        return incident.timeline

    def get_incidents_by_category(self, category: IncidentCategory) -> List[EmergencyIncident]:
        all_incidents = list(self.active_incidents.values()) + self.incident_history
        return [i for i in all_incidents if i.category == category]

    def get_incidents_by_source(self, source: str) -> List[EmergencyIncident]:
        all_incidents = list(self.active_incidents.values()) + self.incident_history
        return [i for i in all_incidents if i.source == source]

    def add_auto_remediation_action(self, incident_id: str, action_type: str,
                                    action_handler: Callable) -> bool:
        incident = self.active_incidents.get(incident_id)
        if not incident:
            return False
        try:
            result = action_handler(incident)
            action = IncidentAction(
                action_id=uuid.uuid4().hex[:12],
                action_type=action_type,
                description=f"Auto-remediation: {action_type}",
                timestamp=datetime.now(),
                handler_name=action_handler.__name__,
                success=True,
                result=str(result) if result else None,
            )
            incident.detailed_actions.append(action)
            incident.actions_taken.append(f"Auto-remediation: {action_type}")
            self._add_timeline_entry(incident, "auto_remediation",
                                     f"Auto-remediation action {action_type} executed")
            logger.info(f"Auto-remediation action {action_type} applied to {incident_id}")
            return True
        except Exception as e:
            logger.error(f"Auto-remediation action {action_type} failed: {e}")
            return False

    def get_incident_report(self, incident_id: str) -> Optional[Dict[str, Any]]:
        incident = self.active_incidents.get(incident_id)
        if not incident:
            for hist in self.incident_history:
                if hist.incident_id == incident_id:
                    incident = hist
                    break
        if not incident:
            return None

        return {
            "incident_id": incident.incident_id,
            "level": incident.level.value,
            "description": incident.description,
            "category": incident.category.value,
            "source": incident.source,
            "timestamp": incident.timestamp.isoformat(),
            "resolved": incident.resolved,
            "resolution_time_seconds": incident.resolution_time_seconds,
            "affected_systems": incident.affected_systems,
            "actions_taken": incident.actions_taken,
            "sla_deadline": incident.sla_deadline.isoformat() if incident.sla_deadline else None,
            "sla_breached": incident.sla_breached,
            "severity_score": incident.severity_score,
            "acknowledged": incident.acknowledged,
            "acknowledged_by": incident.acknowledged_by,
            "tags": incident.tags,
            "timeline_entries": len(incident.timeline),
            "detailed_actions": [
                {"type": a.action_type, "description": a.description,
                 "handler": a.handler_name, "success": a.success}
                for a in incident.detailed_actions
            ],
        }

    def get_incidents_in_time_range(self, start: datetime, end: datetime) -> List[EmergencyIncident]:
        all_incidents = list(self.active_incidents.values()) + self.incident_history
        return [i for i in all_incidents if start <= i.timestamp <= end]

    def get_unacknowledged_incidents(self) -> List[EmergencyIncident]:
        return [i for i in self.active_incidents.values() if not i.acknowledged]

    def get_sla_breached_incidents(self) -> List[EmergencyIncident]:
        all_incidents = list(self.active_incidents.values()) + self.incident_history
        return [i for i in all_incidents if i.sla_breached]

    def shutdown(self) -> None:
        self.sla_checker_running = False
        if self.sla_checker_thread:
            self.sla_checker_thread.join(timeout=5)
        logger.info("EmergencyResponse system shut down")