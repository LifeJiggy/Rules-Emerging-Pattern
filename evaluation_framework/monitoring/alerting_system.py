"""Threshold-based alerting system with multi-channel delivery and escalation."""
import logging
import time
import threading
from typing import List, Dict, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertStatus(str, Enum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"


class AlertChannel(str, Enum):
    LOG = "log"
    SLACK = "slack"
    EMAIL = "email"
    PAGERDUTY = "pagerduty"
    WEBHOOK = "webhook"
    CONSOLE = "console"


@dataclass
class Alert:
    alert_id: str
    name: str
    severity: AlertSeverity
    status: AlertStatus
    condition: str
    message: str
    value: float
    threshold: float
    channels: List[AlertChannel]
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertRule:
    name: str
    condition_expr: str
    severity: AlertSeverity
    threshold: float
    channels: List[AlertChannel]
    cooldown_seconds: int = 300
    enabled: bool = True


class AlertingSystem:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._alerts: Dict[str, Alert] = {}
        self._alert_rules: Dict[str, AlertRule] = {}
        self._channel_handlers: Dict[AlertChannel, List[Callable[[Alert], None]]] = defaultdict(list)
        self._last_triggered: Dict[str, float] = {}
        self._suppressed_alerts: Set[str] = set()
        self._max_alerts = self.config.get("max_alerts", 10000)
        self._lock = threading.RLock()

        self._register_default_channels()
        self._load_default_rules()

        logger.info("AlertingSystem initialized (rules=%d)", len(self._alert_rules))

    def trigger_alert(self, condition: Dict[str, Any]) -> Optional[Alert]:
        rule_name = condition.get("rule_name", condition.get("name", "unknown"))
        value = float(condition.get("value", 0))

        rule = self._alert_rules.get(rule_name)
        if not rule or not rule.enabled:
            return None

        should_trigger = self._evaluate_condition(rule.condition_expr, value, rule.threshold)
        if not should_trigger:
            return None

        with self._lock:
            now = time.time()
            last = self._last_triggered.get(rule_name, 0)
            if now - last < rule.cooldown_seconds:
                logger.debug("Alert '%s' suppressed by cooldown", rule_name)
                return None
            self._last_triggered[rule_name] = now

            if rule_name in self._suppressed_alerts:
                return None

            alert_id = f"{rule_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

            alert = Alert(
                alert_id=alert_id,
                name=rule_name,
                severity=rule.severity,
                status=AlertStatus.TRIGGERED,
                condition=rule.condition_expr,
                message=condition.get("message", f"Alert '{rule_name}' triggered"),
                value=value,
                threshold=rule.threshold,
                channels=list(rule.channels),
                metadata=condition.get("metadata", {}),
            )

            self._alerts[alert_id] = alert
            if len(self._alerts) > self._max_alerts:
                oldest = min(self._alerts.keys(), key=lambda k: self._alerts[k].triggered_at)
                self._alerts[oldest].status = AlertStatus.EXPIRED

        self._dispatch(alert)
        logger.info("Alert '%s' triggered: value=%.4f threshold=%.4f severity=%s",
                     rule_name, value, rule.threshold, rule.severity.value)
        return alert

    def add_rule(self, rule: AlertRule) -> None:
        self._alert_rules[rule.name] = rule
        logger.info("Added alert rule: %s (threshold=%.4f, severity=%s)",
                     rule.name, rule.threshold, rule.severity.value)

    def remove_rule(self, rule_name: str) -> bool:
        if rule_name in self._alert_rules:
            del self._alert_rules[rule_name]
            return True
        return False

    def acknowledge_alert(self, alert_id: str) -> bool:
        alert = self._alerts.get(alert_id)
        if not alert or alert.status != AlertStatus.TRIGGERED:
            return False
        alert.status = AlertStatus.ACKNOWLEDGED
        logger.info("Alert %s acknowledged", alert_id[:8])
        return True

    def resolve_alert(self, alert_id: str) -> bool:
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = datetime.now(timezone.utc)
        logger.info("Alert %s resolved", alert_id[:8])
        return True

    def suppress_rule(self, rule_name: str) -> None:
        self._suppressed_alerts.add(rule_name)
        logger.info("Suppressed alert rule: %s", rule_name)

    def unsuppress_rule(self, rule_name: str) -> None:
        self._suppressed_alerts.discard(rule_name)

    def register_channel(
        self,
        channel: AlertChannel,
        handler: Callable[[Alert], None]
    ) -> None:
        self._channel_handlers[channel].append(handler)
        logger.debug("Registered channel handler: %s", channel.value)

    def get_active_alerts(self) -> List[Alert]:
        return [
            a for a in self._alerts.values()
            if a.status == AlertStatus.TRIGGERED
        ]

    def get_alert_history(
        self,
        severity: Optional[AlertSeverity] = None,
        limit: int = 100
    ) -> List[Alert]:
        results = list(self._alerts.values())
        if severity:
            results = [a for a in results if a.severity == severity]
        results.sort(key=lambda a: a.triggered_at, reverse=True)
        return results[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        severity_counts: Dict[str, int] = defaultdict(int)
        status_counts: Dict[str, int] = defaultdict(int)

        for alert in self._alerts.values():
            severity_counts[alert.severity.value] += 1
            status_counts[alert.status.value] += 1

        return {
            "total_alerts": len(self._alerts),
            "active_alerts": len(self.get_active_alerts()),
            "by_severity": dict(severity_counts),
            "by_status": dict(status_counts),
            "active_rules": len(self._alert_rules),
            "suppressed_rules": len(self._suppressed_alerts),
        }

    def _evaluate_condition(self, condition_expr: str, value: float, threshold: float) -> bool:
        condition_map = {
            ">": value > threshold,
            ">=": value >= threshold,
            "<": value < threshold,
            "<=": value <= threshold,
            "==": abs(value - threshold) < 1e-10,
            "!=": abs(value - threshold) >= 1e-10,
        }

        for op, result in condition_map.items():
            if op in condition_expr:
                return result

        return value > threshold

    def _dispatch(self, alert: Alert) -> None:
        for channel in alert.channels:
            handlers = self._channel_handlers.get(channel, [])
            for handler in handlers:
                try:
                    handler(alert)
                except Exception as e:
                    logger.error("Channel handler error [%s]: %s", channel.value, e)

    def _register_default_channels(self) -> None:
        self._channel_handlers[AlertChannel.LOG].append(
            lambda alert: logger.warning("ALERT [%s] %s: %s",
                                          alert.severity.value.upper(),
                                          alert.name, alert.message)
        )

    def _load_default_rules(self) -> None:
        defaults = self.config.get("default_rules", [
            {
                "name": "high_violation_rate",
                "condition_expr": ">",
                "severity": "critical",
                "threshold": 0.1,
                "channels": ["log"],
                "cooldown_seconds": 300,
            },
            {
                "name": "conflict_detection",
                "condition_expr": ">",
                "severity": "warning",
                "threshold": 0.05,
                "channels": ["log"],
                "cooldown_seconds": 600,
            },
            {
                "name": "performance_degradation",
                "condition_expr": ">",
                "severity": "critical",
                "threshold": 1000.0,
                "channels": ["log"],
                "cooldown_seconds": 120,
            },
            {
                "name": "error_rate_spike",
                "condition_expr": ">",
                "severity": "critical",
                "threshold": 0.05,
                "channels": ["log"],
                "cooldown_seconds": 180,
            },
        ])

        for rule_def in defaults:
            try:
                rule = AlertRule(
                    name=rule_def["name"],
                    condition_expr=rule_def["condition_expr"],
                    severity=AlertSeverity(rule_def["severity"]),
                    threshold=rule_def["threshold"],
                    channels=[AlertChannel(ch) for ch in rule_def.get("channels", ["log"])],
                    cooldown_seconds=rule_def.get("cooldown_seconds", 300),
                )
                self._alert_rules[rule.name] = rule
            except Exception as e:
                logger.warning("Failed to load default rule '%s': %s", rule_def.get("name"), e)
