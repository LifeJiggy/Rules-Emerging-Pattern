"""Alert management system for monitoring."""
import csv
import io
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    def __ge__(self, other) -> bool:
        levels = list(AlertSeverity)
        return levels.index(self) >= levels.index(other)

    def __le__(self, other) -> bool:
        levels = list(AlertSeverity)
        return levels.index(self) <= levels.index(other)


class AlertStatus(Enum):
    """Alert status states."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    ESCALATED = "escalated"


@dataclass
class Alert:
    """Represents a monitoring alert."""
    alert_id: str
    name: str
    severity: AlertSeverity
    status: AlertStatus
    message: str
    timestamp: datetime
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    escalation_level: int = 0
    group_id: Optional[str] = None
    retry_count: int = 0


@dataclass
class AlertRule:
    """Rule for triggering alerts."""
    rule_id: str
    name: str
    condition: str
    severity: AlertSeverity
    notification_channels: List[str] = field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: int = 0
    group_window_seconds: int = 0
    escalation_policy: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EscalationStep:
    """A single step in an escalation policy."""
    level: int
    notify_after_minutes: int
    channels: List[str]
    notify_roles: List[str] = field(default_factory=list)
    message_template: Optional[str] = None


@dataclass
class EscalationPolicy:
    """Policy defining how alerts escalate over time."""
    policy_id: str
    name: str
    steps: List[EscalationStep] = field(default_factory=list)
    max_escalation_level: int = 5
    auto_resolve_after_minutes: Optional[int] = None


@dataclass
class AlertGroup:
    """Group of related alerts."""
    group_id: str
    alert_name: str
    alerts: List[Alert] = field(default_factory=list)
    first_alert_at: Optional[datetime] = None
    last_alert_at: Optional[datetime] = None
    count: int = 0
    acknowledged: bool = False
    resolved: bool = False


@dataclass
class NotificationTemplate:
    """Template for alert notifications."""
    template_id: str
    channel: str
    subject_template: str
    body_template: str
    variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class TimeSeriesPoint:
    """Single data point in alert time-series statistics."""
    timestamp: datetime
    total_active: int
    total_acknowledged: int
    total_resolved: int
    new_alerts: int
    by_severity: Dict[str, int] = field(default_factory=dict)


class AlertManager:
    """Manages alerts and alert rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the alert manager.

        Args:
            config: Optional configuration dictionary
        """
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.alert_rules: Dict[str, AlertRule] = {}
        self.notification_handlers: Dict[str, Callable] = {}
        self.suppressed_alerts: List[str] = []
        self.alert_counter = 0
        self._lock = threading.RLock()

        self.escalation_policies: Dict[str, EscalationPolicy] = {}
        self.alert_groups: Dict[str, AlertGroup] = {}
        self.notification_templates: Dict[str, NotificationTemplate] = {}
        self.time_series_data: List[TimeSeriesPoint] = []
        self._escalation_thread: Optional[threading.Thread] = None
        self._escalation_running = False
        self._config = config or {}

        self.max_history_size = self._config.get("max_history_size", 10000)
        self.default_cooldown = self._config.get("default_cooldown_seconds", 300)
        self.group_window = self._config.get("default_group_window_seconds", 60)
        self.time_series_interval = self._config.get("time_series_interval_seconds", 60)

        if self._config.get("alert_rules"):
            self._load_rules_from_config(self._config["alert_rules"])

        if self._config.get("escalation_policies"):
            self._load_escalation_policies_from_config(self._config["escalation_policies"])

        logger.info("AlertManager initialized")

    def _load_rules_from_config(self, rules_config: List[Dict[str, Any]]) -> None:
        """Load alert rules from configuration.

        Args:
            rules_config: List of rule configuration dictionaries
        """
        for rule_cfg in rules_config:
            try:
                severity = AlertSeverity(rule_cfg.get("severity", "warning"))
                rule = AlertRule(
                    rule_id=rule_cfg.get("rule_id", f"rule_{len(self.alert_rules)}"),
                    name=rule_cfg["name"],
                    condition=rule_cfg["condition"],
                    severity=severity,
                    notification_channels=rule_cfg.get("notification_channels", ["default"]),
                    enabled=rule_cfg.get("enabled", True),
                    cooldown_seconds=rule_cfg.get("cooldown_seconds", 0),
                    group_window_seconds=rule_cfg.get("group_window_seconds", 0),
                    escalation_policy=rule_cfg.get("escalation_policy"),
                    metadata=rule_cfg.get("metadata", {}),
                )
                self.alert_rules[rule.rule_id] = rule
                logger.info(f"Loaded alert rule from config: {rule.name}")
            except Exception as e:
                logger.error(f"Failed to load alert rule from config: {e}")

    def _load_escalation_policies_from_config(self, policies_config: List[Dict[str, Any]]) -> None:
        """Load escalation policies from configuration.

        Args:
            policies_config: List of policy configuration dictionaries
        """
        for pol_cfg in policies_config:
            try:
                steps = []
                for step_cfg in pol_cfg.get("steps", []):
                    step = EscalationStep(
                        level=step_cfg["level"],
                        notify_after_minutes=step_cfg["notify_after_minutes"],
                        channels=step_cfg.get("channels", []),
                        notify_roles=step_cfg.get("notify_roles", []),
                        message_template=step_cfg.get("message_template"),
                    )
                    steps.append(step)
                policy = EscalationPolicy(
                    policy_id=pol_cfg.get("policy_id", f"pol_{len(self.escalation_policies)}"),
                    name=pol_cfg["name"],
                    steps=steps,
                    max_escalation_level=pol_cfg.get("max_escalation_level", 5),
                    auto_resolve_after_minutes=pol_cfg.get("auto_resolve_after_minutes"),
                )
                self.escalation_policies[policy.policy_id] = policy
                logger.info(f"Loaded escalation policy: {policy.name}")
            except Exception as e:
                logger.error(f"Failed to load escalation policy: {e}")

    def register_notification_channel(self, channel: str, handler: Callable) -> None:
        """Register a notification handler for a channel.

        Args:
            channel: Channel name (email, slack, webhook, etc.)
            handler: Callable that accepts an Alert
        """
        with self._lock:
            self.notification_handlers[channel] = handler
        logger.info(f"Registered notification channel: {channel}")

    def create_alert_rule(
        self,
        rule_id: str,
        name: str,
        condition: str,
        severity: AlertSeverity,
        notification_channels: Optional[List[str]] = None,
        cooldown_seconds: int = 0,
        group_window_seconds: int = 0,
        escalation_policy: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertRule:
        """Create a new alert rule.

        Args:
            rule_id: Unique identifier for the rule
            name: Human-readable name
            condition: Condition expression or description
            severity: Default severity when triggered
            notification_channels: List of channels to notify
            cooldown_seconds: Minimum seconds between duplicate alerts
            group_window_seconds: Window for grouping duplicate alerts
            escalation_policy: ID of escalation policy to use
            metadata: Additional rule metadata

        Returns:
            The created alert rule
        """
        rule = AlertRule(
            rule_id=rule_id,
            name=name,
            condition=condition,
            severity=severity,
            notification_channels=notification_channels or ["default"],
            enabled=True,
            cooldown_seconds=cooldown_seconds,
            group_window_seconds=group_window_seconds,
            escalation_policy=escalation_policy,
            metadata=metadata or {},
        )

        with self._lock:
            self.alert_rules[rule_id] = rule
        logger.info(f"Created alert rule: {name}")
        return rule

    def update_alert_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing alert rule.

        Args:
            rule_id: ID of the rule to update
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if rule_id not in self.alert_rules:
                logger.warning(f"Alert rule not found: {rule_id}")
                return False
            rule = self.alert_rules[rule_id]
            for key, value in updates.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)
            logger.info(f"Updated alert rule: {rule_id}")
            return True

    def delete_alert_rule(self, rule_id: str) -> bool:
        """Delete an alert rule.

        Args:
            rule_id: ID of the rule to delete

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if rule_id not in self.alert_rules:
                return False
            del self.alert_rules[rule_id]
            logger.info(f"Deleted alert rule: {rule_id}")
            return True

    def create_escalation_policy(
        self,
        policy_id: str,
        name: str,
        steps: Optional[List[EscalationStep]] = None,
        max_escalation_level: int = 5,
        auto_resolve_after_minutes: Optional[int] = None,
    ) -> EscalationPolicy:
        """Create a new escalation policy.

        Args:
            policy_id: Unique identifier
            name: Human-readable name
            steps: List of escalation steps
            max_escalation_level: Maximum escalation level
            auto_resolve_after_minutes: Auto-resolve timeout

        Returns:
            The created escalation policy
        """
        policy = EscalationPolicy(
            policy_id=policy_id,
            name=name,
            steps=steps or [],
            max_escalation_level=max_escalation_level,
            auto_resolve_after_minutes=auto_resolve_after_minutes,
        )
        with self._lock:
            self.escalation_policies[policy_id] = policy
        logger.info(f"Created escalation policy: {name}")
        return policy

    def create_notification_template(
        self,
        template_id: str,
        channel: str,
        subject_template: str,
        body_template: str,
        variables: Optional[Dict[str, str]] = None,
    ) -> NotificationTemplate:
        """Create a notification template.

        Args:
            template_id: Unique identifier
            channel: Target channel
            subject_template: Subject line template
            body_template: Body template
            variables: Variable mappings

        Returns:
            The created template
        """
        template = NotificationTemplate(
            template_id=template_id,
            channel=channel,
            subject_template=subject_template,
            body_template=body_template,
            variables=variables or {},
        )
        with self._lock:
            self.notification_templates[template_id] = template
        logger.info(f"Created notification template: {template_id}")
        return template

    def render_template(self, template: NotificationTemplate, alert: Alert) -> Dict[str, str]:
        """Render a notification template with alert data.

        Args:
            template: The template to render
            alert: The alert to use for variable substitution

        Returns:
            Dictionary with 'subject' and 'body' keys
        """
        variables = {
            "alert_id": alert.alert_id,
            "alert_name": alert.name,
            "severity": alert.severity.value,
            "status": alert.status.value,
            "message": alert.message,
            "source": alert.source,
            "timestamp": alert.timestamp.isoformat(),
            "escalation_level": str(alert.escalation_level),
        }
        variables.update(template.variables)
        variables.update({k: str(v) for k, v in alert.metadata.items()})

        try:
            subject = template.subject_template
            body = template.body_template
            for key, value in variables.items():
                placeholder = "{" + key + "}"
                subject = subject.replace(placeholder, value)
                body = body.replace(placeholder, value)
            return {"subject": subject, "body": body}
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            return {"subject": template.subject_template, "body": template.body_template}

    def _is_in_cooldown(self, alert_name: str) -> bool:
        """Check if an alert type is in cooldown period.

        Args:
            alert_name: Name of the alert type

        Returns:
            True if in cooldown
        """
        now = datetime.now()
        for alert in list(self.active_alerts.values()) + self.alert_history[-100:]:
            if alert.name == alert_name:
                if now - alert.timestamp < timedelta(seconds=self.default_cooldown):
                    return True
        return False

    def _find_or_create_group(self, alert: Alert, window_seconds: int) -> str:
        """Find existing alert group or create a new one.

        Args:
            alert: The alert to group
            window_seconds: Grouping time window

        Returns:
            Group ID
        """
        now = datetime.now()
        window = timedelta(seconds=window_seconds)

        for group_id, group in self.alert_groups.items():
            if group.alert_name == alert.name and not group.resolved:
                if group.last_alert_at and (now - group.last_alert_at) <= window:
                    group.alerts.append(alert)
                    group.last_alert_at = now
                    group.count += 1
                    return group_id

        group_id = f"group_{alert.name}_{now.strftime('%Y%m%d_%H%M%S')}"
        group = AlertGroup(
            group_id=group_id,
            alert_name=alert.name,
            alerts=[alert],
            first_alert_at=now,
            last_alert_at=now,
            count=1,
        )
        self.alert_groups[group_id] = group
        return group_id

    def trigger_alert(
        self,
        name: str,
        severity: AlertSeverity,
        message: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Alert:
        """Trigger a new alert.

        Args:
            name: Alert name
            severity: Alert severity
            message: Alert message
            source: Source system/component
            metadata: Optional additional data

        Returns:
            The created alert
        """
        with self._lock:
            self.alert_counter += 1
            alert_id = f"ALERT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.alert_counter}"

            alert = Alert(
                alert_id=alert_id,
                name=name,
                severity=severity,
                status=AlertStatus.ACTIVE,
                message=message,
                timestamp=datetime.now(),
                source=source,
                metadata=metadata or {},
            )

            if name in self.suppressed_alerts:
                alert.status = AlertStatus.SUPPRESSED
                logger.info(f"Alert suppressed: {name}")
                return alert

            if self._is_in_cooldown(name):
                logger.debug(f"Alert in cooldown: {name}")
                alert.status = AlertStatus.SUPPRESSED
                return alert

            rule = self._find_matching_rule(alert)
            if rule:
                alert.metadata["rule_id"] = rule.rule_id
                if rule.group_window_seconds > 0:
                    group_id = self._find_or_create_group(alert, rule.group_window_seconds)
                    alert.group_id = group_id
                    group_alert_count = self.alert_groups[group_id].count
                    alert.message = f"{message} (occurrence #{group_alert_count})"

            self.active_alerts[alert_id] = alert
            self._send_notifications(alert)
            self._check_escalation(alert)

            logger.warning(f"Alert triggered: {alert_id} - {name} ({severity.value})")
            return alert

    def _find_matching_rule(self, alert: Alert) -> Optional[AlertRule]:
        """Find the first matching rule for an alert.

        Args:
            alert: The alert to match

        Returns:
            Matching rule or None
        """
        for rule in self.alert_rules.values():
            if rule.enabled and (alert.name in rule.condition or rule.condition in alert.name):
                return rule
        return None

    def _check_escalation(self, alert: Alert) -> None:
        """Check if alert needs escalation and apply policy.

        Args:
            alert: The alert to check
        """
        rule = self._find_matching_rule(alert)
        if rule and rule.escalation_policy:
            policy = self.escalation_policies.get(rule.escalation_policy)
            if policy:
                alert.metadata["escalation_policy"] = policy.policy_id

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        """Acknowledge an active alert.

        Args:
            alert_id: ID of the alert to acknowledge
            acknowledged_by: Person/system acknowledging

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if alert_id not in self.active_alerts:
                logger.warning(f"Alert not found: {alert_id}")
                return False

            alert = self.active_alerts[alert_id]
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_by = acknowledged_by
            alert.acknowledged_at = datetime.now()

            if alert.group_id and alert.group_id in self.alert_groups:
                self.alert_groups[alert.group_id].acknowledged = True

            logger.info(f"Alert acknowledged: {alert_id} by {acknowledged_by}")
            return True

    def resolve_alert(self, alert_id: str, resolution_notes: str) -> bool:
        """Resolve an active alert.

        Args:
            alert_id: ID of the alert to resolve
            resolution_notes: Notes about the resolution

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if alert_id not in self.active_alerts:
                logger.warning(f"Alert not found: {alert_id}")
                return False

            alert = self.active_alerts[alert_id]
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.now()
            alert.metadata['resolution_notes'] = resolution_notes

            if alert.group_id and alert.group_id in self.alert_groups:
                self.alert_groups[alert.group_id].resolved = True

            self.alert_history.append(alert)
            del self.active_alerts[alert_id]

            self._prune_history()
            logger.info(f"Alert resolved: {alert_id}")
            return True

    def _prune_history(self) -> None:
        """Prune alert history to max size."""
        if len(self.alert_history) > self.max_history_size:
            self.alert_history = self.alert_history[-self.max_history_size:]

    def _process_escalations(self) -> None:
        """Background thread: check and process escalations."""
        while self._escalation_running:
            try:
                now = datetime.now()
                with self._lock:
                    to_escalate = []
                    for alert in self.active_alerts.values():
                        if alert.status in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED):
                            if alert.escalation_level >= 5:
                                continue
                            policy_id = alert.metadata.get("escalation_policy")
                            if not policy_id:
                                continue
                            policy = self.escalation_policies.get(policy_id)
                            if not policy:
                                continue
                            alert_age_minutes = (now - alert.timestamp).total_seconds() / 60.0
                            next_level = alert.escalation_level + 1
                            for step in policy.steps:
                                if step.level == next_level:
                                    if alert_age_minutes >= step.notify_after_minutes:
                                        to_escalate.append((alert, step, policy))

                    for alert, step, policy in to_escalate:
                        alert.escalation_level = step.level
                        alert.status = AlertStatus.ESCALATED
                        alert.escalated_at = now
                        for channel in step.channels:
                            if channel in self.notification_handlers:
                                try:
                                    self.notification_handlers[channel](alert)
                                except Exception as e:
                                    logger.error(f"Escalation notification failed: {e}")
                        logger.info(
                            f"Alert escalated: {alert.alert_id} to level {step.level}"
                        )

                        if policy.auto_resolve_after_minutes:
                            age_minutes = (now - alert.timestamp).total_seconds() / 60.0
                            if age_minutes >= policy.auto_resolve_after_minutes:
                                self.resolve_alert(
                                    alert.alert_id,
                                    "Auto-resolved by escalation policy timeout",
                                )

                time.sleep(15)
            except Exception as e:
                logger.error(f"Escalation processing error: {e}")
                time.sleep(30)

    def start_escalation_processing(self) -> None:
        """Start background escalation processing thread."""
        if self._escalation_thread and self._escalation_thread.is_alive():
            logger.warning("Escalation processing already running")
            return
        self._escalation_running = True
        self._escalation_thread = threading.Thread(
            target=self._process_escalations,
            daemon=True,
            name="alert-escalation",
        )
        self._escalation_thread.start()
        logger.info("Escalation processing started")

    def stop_escalation_processing(self) -> None:
        """Stop background escalation processing thread."""
        self._escalation_running = False
        if self._escalation_thread:
            self._escalation_thread.join(timeout=10)
            logger.info("Escalation processing stopped")

    def suppress_alert_type(self, alert_name: str) -> None:
        """Suppress alerts of a specific type.

        Args:
            alert_name: Name of alert type to suppress
        """
        with self._lock:
            if alert_name not in self.suppressed_alerts:
                self.suppressed_alerts.append(alert_name)
                logger.info(f"Alert type suppressed: {alert_name}")

    def unsuppress_alert_type(self, alert_name: str) -> None:
        """Unsuppress alerts of a specific type.

        Args:
            alert_name: Name of alert type to unsuppress
        """
        with self._lock:
            if alert_name in self.suppressed_alerts:
                self.suppressed_alerts.remove(alert_name)
                logger.info(f"Alert type unsuppressed: {alert_name}")

    def _send_notifications(self, alert: Alert) -> None:
        """Send alert notifications through registered channels."""
        matching_rules = [
            rule for rule in self.alert_rules.values()
            if rule.enabled and (alert.name in rule.condition or rule.condition in alert.name)
        ]

        channels_to_notify: Set[str] = set()
        for rule in matching_rules:
            channels_to_notify.update(rule.notification_channels)

        if not channels_to_notify:
            channels_to_notify = {"default"}

        for channel in channels_to_notify:
            if channel in self.notification_handlers:
                try:
                    template_id = f"default_{channel}"
                    if template_id in self.notification_templates:
                        template = self.notification_templates[template_id]
                        rendered = self.render_template(template, alert)
                        alert.metadata["rendered_subject"] = rendered["subject"]
                        alert.metadata["rendered_body"] = rendered["body"]

                    self.notification_handlers[channel](alert)
                    logger.info(f"Notification sent via {channel} for alert {alert.alert_id}")
                except Exception as e:
                    logger.error(f"Failed to send notification via {channel}: {e}")

    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        source: Optional[str] = None,
        status: Optional[AlertStatus] = None,
    ) -> List[Alert]:
        """Get active alerts with optional filtering.

        Args:
            severity: Filter by severity
            source: Filter by source
            status: Filter by status

        Returns:
            List of matching alerts
        """
        with self._lock:
            alerts = list(self.active_alerts.values())

            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            if source:
                alerts = [a for a in alerts if a.source == source]
            if status:
                alerts = [a for a in alerts if a.status == status]

            return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def get_alert_history(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        severity: Optional[AlertSeverity] = None,
        source: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Alert]:
        """Get historical alerts with filtering.

        Args:
            start_time: Filter by start time
            end_time: Filter by end time
            severity: Filter by severity
            source: Filter by source
            limit: Maximum number of results

        Returns:
            List of matching alerts
        """
        with self._lock:
            alerts = list(self.alert_history)

            if start_time:
                alerts = [a for a in alerts if a.timestamp >= start_time]
            if end_time:
                alerts = [a for a in alerts if a.timestamp <= end_time]
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            if source:
                alerts = [a for a in alerts if a.source == source]

            return sorted(alerts, key=lambda a: a.timestamp, reverse=True)[:limit]

    def get_alert_groups(self) -> Dict[str, AlertGroup]:
        """Get all alert groups.

        Returns:
            Dictionary of group ID to AlertGroup
        """
        with self._lock:
            return dict(self.alert_groups)

    def get_alert_by_id(self, alert_id: str) -> Optional[Alert]:
        """Get a specific alert by ID.

        Args:
            alert_id: The alert ID to find

        Returns:
            Alert if found, None otherwise
        """
        with self._lock:
            if alert_id in self.active_alerts:
                return self.active_alerts[alert_id]
            for alert in self.alert_history:
                if alert.alert_id == alert_id:
                    return alert
            return None

    def get_escalation_policies(self) -> Dict[str, EscalationPolicy]:
        """Get all escalation policies.

        Returns:
            Dictionary of policy ID to EscalationPolicy
        """
        with self._lock:
            return dict(self.escalation_policies)

    def _record_time_series(self) -> None:
        """Record current alert state as a time-series data point."""
        now = datetime.now()
        severity_counts = {s.value: 0 for s in AlertSeverity}
        active_count = 0
        acknowledged_count = 0
        resolved_count = 0

        for alert in list(self.active_alerts.values()):
            severity_counts[alert.severity.value] += 1
            if alert.status == AlertStatus.ACTIVE:
                active_count += 1
            elif alert.status == AlertStatus.ACKNOWLEDGED:
                acknowledged_count += 1
            elif alert.status == AlertStatus.RESOLVED:
                resolved_count += 1

        point = TimeSeriesPoint(
            timestamp=now,
            total_active=active_count,
            total_acknowledged=acknowledged_count,
            total_resolved=resolved_count,
            new_alerts=0,
            by_severity=severity_counts,
        )
        self.time_series_data.append(point)

        if len(self.time_series_data) > 10000:
            self.time_series_data = self.time_series_data[-10000:]

    def get_time_series(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[TimeSeriesPoint]:
        """Get time-series alert statistics.

        Args:
            start_time: Optional start filter
            end_time: Optional end filter

        Returns:
            List of time series data points
        """
        with self._lock:
            data = self.time_series_data
            if start_time:
                data = [p for p in data if p.timestamp >= start_time]
            if end_time:
                data = [p for p in data if p.timestamp <= end_time]
            return data

    def get_alert_statistics(self) -> Dict[str, Any]:
        """Get alert statistics.

        Returns:
            Dictionary with alert statistics
        """
        with self._lock:
            severity_counts = {severity.value: 0 for severity in AlertSeverity}
            status_counts = {status.value: 0 for status in AlertStatus}
            source_counts: Dict[str, int] = defaultdict(int)
            escalation_counts: Dict[int, int] = defaultdict(int)

            all_alerts = list(self.active_alerts.values()) + self.alert_history

            for alert in all_alerts:
                severity_counts[alert.severity.value] += 1
                status_counts[alert.status.value] += 1
                source_counts[alert.source] += 1
                escalation_counts[alert.escalation_level] += 1

            active_by_severity = {s.value: 0 for s in AlertSeverity}
            for alert in self.active_alerts.values():
                active_by_severity[alert.severity.value] += 1

            avg_resolution_time = None
            resolved_times = []
            for alert in self.alert_history:
                if alert.resolved_at and alert.timestamp:
                    delta = (alert.resolved_at - alert.timestamp).total_seconds()
                    resolved_times.append(delta)
            if resolved_times:
                avg_resolution_time = sum(resolved_times) / len(resolved_times)

            return {
                'active_alerts': len(self.active_alerts),
                'total_alerts': len(self.alert_history) + len(self.active_alerts),
                'by_severity': severity_counts,
                'by_status': status_counts,
                'by_source': dict(source_counts),
                'by_escalation_level': dict(escalation_counts),
                'active_by_severity': active_by_severity,
                'suppressed_types': len(self.suppressed_alerts),
                'alert_rules': len(self.alert_rules),
                'notification_channels': len(self.notification_handlers),
                'escalation_policies': len(self.escalation_policies),
                'alert_groups': len(self.alert_groups),
                'time_series_points': len(self.time_series_data),
                'avg_resolution_time_seconds': avg_resolution_time,
                'avg_alerts_per_group': (
                    sum(g.count for g in self.alert_groups.values()) / len(self.alert_groups)
                    if self.alert_groups else 0
                ),
            }

    def export_history_json(self, filepath: str) -> bool:
        """Export alert history to a JSON file.

        Args:
            filepath: Path for the output file

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                data = []
                for alert in self.alert_history:
                    data.append(self._alert_to_dict(alert))
                for alert in self.active_alerts.values():
                    data.append(self._alert_to_dict(alert))

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)

            logger.info(f"Exported {len(data)} alerts to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export alerts to JSON: {e}")
            return False

    def export_history_csv(self, filepath: str) -> bool:
        """Export alert history to a CSV file.

        Args:
            filepath: Path for the output file

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                data = []
                for alert in self.alert_history:
                    data.append(self._alert_to_dict(alert))
                for alert in self.active_alerts.values():
                    data.append(self._alert_to_dict(alert))

            if not data:
                logger.warning("No alert data to export")
                return False

            fieldnames = [
                "alert_id", "name", "severity", "status", "message",
                "timestamp", "source", "acknowledged_by", "acknowledged_at",
                "resolved_at", "escalation_level", "group_id",
            ]

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(data)

            logger.info(f"Exported {len(data)} alerts to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export alerts to CSV: {e}")
            return False

    def export_history_json_string(self) -> Optional[str]:
        """Export alert history as a JSON string.

        Returns:
            JSON string or None on failure
        """
        try:
            with self._lock:
                data = []
                for alert in self.alert_history:
                    data.append(self._alert_to_dict(alert))
                for alert in self.active_alerts.values():
                    data.append(self._alert_to_dict(alert))
            return json.dumps(data, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to export alerts to JSON string: {e}")
            return None

    def export_history_csv_string(self) -> Optional[str]:
        """Export alert history as a CSV string.

        Returns:
            CSV string or None on failure
        """
        try:
            with self._lock:
                data = []
                for alert in self.alert_history:
                    data.append(self._alert_to_dict(alert))
                for alert in self.active_alerts.values():
                    data.append(self._alert_to_dict(alert))

            if not data:
                return ""

            fieldnames = [
                "alert_id", "name", "severity", "status", "message",
                "timestamp", "source", "acknowledged_by", "acknowledged_at",
                "resolved_at", "escalation_level", "group_id",
            ]

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(data)
            return output.getvalue()
        except Exception as e:
            logger.error(f"Failed to export alerts to CSV string: {e}")
            return None

    @staticmethod
    def _alert_to_dict(alert: Alert) -> Dict[str, Any]:
        """Convert an Alert to a dictionary for export.

        Args:
            alert: The alert to convert

        Returns:
            Dictionary representation
        """
        return {
            "alert_id": alert.alert_id,
            "name": alert.name,
            "severity": alert.severity.value,
            "status": alert.status.value,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "source": alert.source,
            "metadata": alert.metadata,
            "acknowledged_by": alert.acknowledged_by,
            "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            "escalated_at": alert.escalated_at.isoformat() if alert.escalated_at else None,
            "escalation_level": alert.escalation_level,
            "group_id": alert.group_id,
            "retry_count": alert.retry_count,
        }

    def bulk_acknowledge(self, alert_ids: List[str], acknowledged_by: str) -> int:
        """Acknowledge multiple alerts at once.

        Args:
            alert_ids: List of alert IDs to acknowledge
            acknowledged_by: Person/system acknowledging

        Returns:
            Number of successfully acknowledged alerts
        """
        count = 0
        for alert_id in alert_ids:
            if self.acknowledge_alert(alert_id, acknowledged_by):
                count += 1
        logger.info(f"Bulk acknowledged {count}/{len(alert_ids)} alerts")
        return count

    def bulk_resolve(self, alert_ids: List[str], resolution_notes: str) -> int:
        """Resolve multiple alerts at once.

        Args:
            alert_ids: List of alert IDs to resolve
            resolution_notes: Resolution notes

        Returns:
            Number of successfully resolved alerts
        """
        count = 0
        for alert_id in alert_ids:
            if self.resolve_alert(alert_id, resolution_notes):
                count += 1
        logger.info(f"Bulk resolved {count}/{len(alert_ids)} alerts")
        return count

    def resolve_all_of_source(self, source: str, resolution_notes: str) -> int:
        """Resolve all active alerts from a given source.

        Args:
            source: Source to resolve alerts for
            resolution_notes: Resolution notes

        Returns:
            Number of resolved alerts
        """
        with self._lock:
            to_resolve = [
                alert_id for alert_id, alert in self.active_alerts.items()
                if alert.source == source
            ]
        count = 0
        for alert_id in to_resolve:
            if self.resolve_alert(alert_id, resolution_notes):
                count += 1
        logger.info(f"Resolved {count} alerts from source: {source}")
        return count

    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[Alert]:
        """Get all active alerts of a specific severity.

        Args:
            severity: Severity level to filter by

        Returns:
            List of matching alerts
        """
        return self.get_active_alerts(severity=severity)

    def get_critical_alerts(self) -> List[Alert]:
        """Get all active critical alerts.

        Returns:
            List of critical alerts
        """
        return self.get_active_alerts(severity=AlertSeverity.CRITICAL)

    def get_unacknowledged_alerts(self) -> List[Alert]:
        """Get all active unacknowledged alerts.

        Returns:
            List of unacknowledged alerts
        """
        return self.get_active_alerts(status=AlertStatus.ACTIVE)

    def cleanup_stale_alerts(self, max_age_minutes: int = 1440) -> int:
        """Auto-resolve alerts that have been active too long.

        Args:
            max_age_minutes: Maximum age before auto-resolution

        Returns:
            Number of alerts cleaned up
        """
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        with self._lock:
            stale = [
                alert_id for alert_id, alert in self.active_alerts.items()
                if alert.timestamp < cutoff
            ]
        count = 0
        for alert_id in stale:
            if self.resolve_alert(alert_id, "Auto-resolved: stale alert"):
                count += 1
        logger.info(f"Cleaned up {count} stale alerts")
        return count

    def get_config(self) -> Dict[str, Any]:
        """Get the current alert manager configuration.

        Returns:
            Configuration dictionary
        """
        return {
            "max_history_size": self.max_history_size,
            "default_cooldown_seconds": self.default_cooldown,
            "default_group_window_seconds": self.group_window,
            "time_series_interval_seconds": self.time_series_interval,
            "alert_rules_count": len(self.alert_rules),
            "escalation_policies_count": len(self.escalation_policies),
            "notification_templates_count": len(self.notification_templates),
        }

    def clear_history(self) -> int:
        """Clear all alert history.

        Returns:
            Number of history entries cleared
        """
        with self._lock:
            count = len(self.alert_history)
            self.alert_history.clear()
            self.time_series_data.clear()
            logger.info(f"Cleared {count} history entries")
            return count
