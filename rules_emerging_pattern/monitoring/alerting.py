"""Alert management system for monitoring."""
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(Enum):
    """Alert status states."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


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


@dataclass
class AlertRule:
    """Rule for triggering alerts."""
    rule_id: str
    name: str
    condition: str
    severity: AlertSeverity
    notification_channels: List[str] = field(default_factory=list)
    enabled: bool = True


class AlertManager:
    """Manages alerts and alert rules."""
    
    def __init__(self):
        """Initialize the alert manager."""
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.alert_rules: Dict[str, AlertRule] = {}
        self.notification_handlers: Dict[str, Callable] = {}
        self.suppressed_alerts: List[str] = []
        self.alert_counter = 0
        logger.info("AlertManager initialized")
    
    def register_notification_channel(self, channel: str, handler: Callable) -> None:
        """Register a notification handler for a channel.
        
        Args:
            channel: Channel name (email, slack, webhook, etc.)
            handler: Callable that accepts an Alert
        """
        self.notification_handlers[channel] = handler
        logger.info(f"Registered notification channel: {channel}")
    
    def create_alert_rule(
        self,
        rule_id: str,
        name: str,
        condition: str,
        severity: AlertSeverity,
        notification_channels: Optional[List[str]] = None
    ) -> AlertRule:
        """Create a new alert rule.
        
        Args:
            rule_id: Unique identifier for the rule
            name: Human-readable name
            condition: Condition expression or description
            severity: Default severity when triggered
            notification_channels: List of channels to notify
            
        Returns:
            The created alert rule
        """
        rule = AlertRule(
            rule_id=rule_id,
            name=name,
            condition=condition,
            severity=severity,
            notification_channels=notification_channels or ["default"],
            enabled=True
        )
        
        self.alert_rules[rule_id] = rule
        logger.info(f"Created alert rule: {name}")
        return rule
    
    def trigger_alert(
        self,
        name: str,
        severity: AlertSeverity,
        message: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None
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
            metadata=metadata or {}
        )
        
        # Check if this alert type is suppressed
        if name in self.suppressed_alerts:
            alert.status = AlertStatus.SUPPRESSED
            logger.info(f"Alert suppressed: {name}")
            return alert
        
        self.active_alerts[alert_id] = alert
        
        # Send notifications
        self._send_notifications(alert)
        
        logger.warning(f"Alert triggered: {alert_id} - {name} ({severity.value})")
        return alert
    
    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        """Acknowledge an active alert.
        
        Args:
            alert_id: ID of the alert to acknowledge
            acknowledged_by: Person/system acknowledging
            
        Returns:
            True if successful, False otherwise
        """
        if alert_id not in self.active_alerts:
            logger.warning(f"Alert not found: {alert_id}")
            return False
        
        alert = self.active_alerts[alert_id]
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.now()
        
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
        if alert_id not in self.active_alerts:
            logger.warning(f"Alert not found: {alert_id}")
            return False
        
        alert = self.active_alerts[alert_id]
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = datetime.now()
        alert.metadata['resolution_notes'] = resolution_notes
        
        # Move to history
        self.alert_history.append(alert)
        del self.active_alerts[alert_id]
        
        logger.info(f"Alert resolved: {alert_id}")
        return True
    
    def suppress_alert_type(self, alert_name: str) -> None:
        """Suppress alerts of a specific type.
        
        Args:
            alert_name: Name of alert type to suppress
        """
        if alert_name not in self.suppressed_alerts:
            self.suppressed_alerts.append(alert_name)
            logger.info(f"Alert type suppressed: {alert_name}")
    
    def unsuppress_alert_type(self, alert_name: str) -> None:
        """Unsuppress alerts of a specific type.
        
        Args:
            alert_name: Name of alert type to unsuppress
        """
        if alert_name in self.suppressed_alerts:
            self.suppressed_alerts.remove(alert_name)
            logger.info(f"Alert type unsuppressed: {alert_name}")
    
    def _send_notifications(self, alert: Alert) -> None:
        """Send alert notifications through registered channels."""
        # Find matching rules for this alert
        matching_rules = [
            rule for rule in self.alert_rules.values()
            if rule.enabled and alert.name in rule.condition
        ]
        
        channels_to_notify = set()
        for rule in matching_rules:
            channels_to_notify.update(rule.notification_channels)
        
        # If no specific rules, use default
        if not channels_to_notify:
            channels_to_notify = {"default"}
        
        # Send notifications
        for channel in channels_to_notify:
            if channel in self.notification_handlers:
                try:
                    self.notification_handlers[channel](alert)
                    logger.info(f"Notification sent via {channel} for alert {alert.alert_id}")
                except Exception as e:
                    logger.error(f"Failed to send notification via {channel}: {e}")
    
    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        source: Optional[str] = None
    ) -> List[Alert]:
        """Get active alerts with optional filtering.
        
        Args:
            severity: Filter by severity
            source: Filter by source
            
        Returns:
            List of matching alerts
        """
        alerts = list(self.active_alerts.values())
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if source:
            alerts = [a for a in alerts if a.source == source]
        
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)
    
    def get_alert_statistics(self) -> Dict[str, Any]:
        """Get alert statistics.
        
        Returns:
            Dictionary with alert statistics
        """
        severity_counts = {severity.value: 0 for severity in AlertSeverity}
        status_counts = {status.value: 0 for status in AlertStatus}
        
        for alert in list(self.active_alerts.values()) + self.alert_history:
            severity_counts[alert.severity.value] += 1
            status_counts[alert.status.value] += 1
        
        return {
            'active_alerts': len(self.active_alerts),
            'total_alerts': len(self.alert_history) + len(self.active_alerts),
            'by_severity': severity_counts,
            'by_status': status_counts,
            'suppressed_types': len(self.suppressed_alerts),
            'alert_rules': len(self.alert_rules),
            'notification_channels': len(self.notification_handlers)
        }
