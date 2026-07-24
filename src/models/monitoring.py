"""
Monitoring and metrics models for the Rules-Emerging-Pattern system.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field, validator, root_validator

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Severity levels for alerts."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """Status of an alert."""
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


class AlertDefinition(BaseModel):
    """Alert configuration model."""

    alert_id: str
    name: str
    description: Optional[str] = None
    alert_type: str = "threshold"
    severity: AlertSeverity = AlertSeverity.WARNING

    metric_name: str
    metric_source: str = "system"
    comparison_operator: str = "greater_than"
    threshold_value: float = 0.0
    duration_seconds: int = Field(default=60, ge=1, le=86400)

    evaluation_window_minutes: int = Field(default=5, ge=1, le=1440)
    cooldown_minutes: int = Field(default=10, ge=0, le=1440)
    max_alerts_per_hour: int = Field(default=10, ge=1, le=1000)

    notification_channels: List[str] = Field(default_factory=lambda: ["log"])
    escalation_levels: List[Dict[str, Any]] = Field(default_factory=list)
    auto_resolve_minutes: Optional[int] = None

    is_active: bool = True
    is_system_alert: bool = False
    enabled_environments: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def evaluate_condition(self, current_value: float) -> bool:
        if self.comparison_operator == "greater_than":
            return current_value > self.threshold_value
        elif self.comparison_operator == "less_than":
            return current_value < self.threshold_value
        elif self.comparison_operator == "equal_to":
            return current_value == self.threshold_value
        elif self.comparison_operator == "not_equal_to":
            return current_value != self.threshold_value
        elif self.comparison_operator == "greater_than_or_equal":
            return current_value >= self.threshold_value
        elif self.comparison_operator == "less_than_or_equal":
            return current_value <= self.threshold_value
        elif self.comparison_operator == "percentage_change":
            return abs(current_value - self.threshold_value) / max(self.threshold_value, 0.001) > 0.1
        return False

    def get_escalation_level(self, consecutive_triggers: int) -> Optional[Dict[str, Any]]:
        for level in self.escalation_levels:
            if level.get("trigger_count", 0) <= consecutive_triggers:
                return level
        return None

    def should_escalate(self, consecutive_alerts: int) -> bool:
        return consecutive_alerts >= len(self.escalation_levels)

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def is_enabled_for_environment(self, environment: str) -> bool:
        if not self.enabled_environments:
            return True
        return environment in self.enabled_environments

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AlertEvent(BaseModel):
    """Alert occurrence model."""

    event_id: str
    alert_id: str
    alert_name: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.TRIGGERED

    metric_name: str
    metric_value: float
    threshold_value: float
    comparison_operator: str

    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)

    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None

    acknowledged_by: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None

    consecutive_occurrence: int = 1
    source: str = "system"
    environment: Optional[str] = None
    host: Optional[str] = None
    service: Optional[str] = None

    related_event_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def acknowledge(self, user: str, notes: Optional[str] = None) -> None:
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = datetime.utcnow()
        self.acknowledged_by = user
        if notes:
            self.details["acknowledgment_notes"] = notes

    def resolve(self, user: str, notes: Optional[str] = None) -> None:
        self.status = AlertStatus.RESOLVED
        self.resolved_at = datetime.utcnow()
        self.resolved_by = user
        if notes:
            self.resolution_notes = notes

    def dismiss(self, reason: str) -> None:
        self.status = AlertStatus.DISMISSED
        self.dismissed_at = datetime.utcnow()
        self.details["dismiss_reason"] = reason

    def escalate(self) -> None:
        self.status = AlertStatus.ESCALATED
        self.escalated_at = datetime.utcnow()

    def get_duration_seconds(self) -> Optional[float]:
        if self.triggered_at and (self.resolved_at or self.dismissed_at):
            end = self.resolved_at or self.dismissed_at
            return (end - self.triggered_at).total_seconds()
        if self.triggered_at:
            return (datetime.utcnow() - self.triggered_at).total_seconds()
        return None

    def is_active(self) -> bool:
        return self.status in (AlertStatus.TRIGGERED, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED)

    def link_event(self, event_id: str) -> None:
        if event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "alert_id": self.alert_id,
            "alert_name": self.alert_name,
            "severity": self.severity.value,
            "status": self.status.value,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "message": self.message,
            "triggered_at": self.triggered_at.isoformat(),
            "duration_seconds": self.get_duration_seconds(),
            "is_active": self.is_active()
        }

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MonitorConfig(BaseModel):
    """Monitor configuration."""

    monitor_id: str
    name: str
    description: Optional[str] = None
    monitor_type: str = "metric"
    target: str = "system"
    interval_seconds: int = Field(default=60, ge=1, le=86400)

    metrics: List[str] = Field(default_factory=list)
    alert_definitions: List[str] = Field(default_factory=list)
    data_sources: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True
    is_system_monitor: bool = False
    log_level: str = "INFO"
    retry_on_failure: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    health_check_path: Optional[str] = None
    health_check_interval_seconds: int = Field(default=300, ge=10, le=86400)

    notification_channels: List[str] = Field(default_factory=list)
    escalation_contacts: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def get_effective_interval(self) -> int:
        return self.interval_seconds

    def should_run_now(self, last_run: Optional[datetime] = None) -> bool:
        if not self.enabled:
            return False
        if last_run is None:
            return True
        elapsed = (datetime.utcnow() - last_run).total_seconds()
        return elapsed >= self.interval_seconds

    def add_metric(self, metric_name: str) -> None:
        if metric_name not in self.metrics:
            self.metrics.append(metric_name)
            self.updated_at = datetime.utcnow()

    def remove_metric(self, metric_name: str) -> bool:
        if metric_name in self.metrics:
            self.metrics.remove(metric_name)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def add_alert_definition(self, alert_id: str) -> None:
        if alert_id not in self.alert_definitions:
            self.alert_definitions.append(alert_id)
            self.updated_at = datetime.utcnow()

    def remove_alert_definition(self, alert_id: str) -> bool:
        if alert_id in self.alert_definitions:
            self.alert_definitions.remove(alert_id)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def enable(self) -> None:
        self.enabled = True
        self.updated_at = datetime.utcnow()

    def disable(self) -> None:
        self.enabled = False
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MetricsSnapshot(BaseModel):
    """Point-in-time metrics."""

    snapshot_id: str
    source: str = "system"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    metrics: Dict[str, float] = Field(default_factory=dict)
    labels: Dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    host: Optional[str] = None
    service: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None

    cpu_usage_percent: Optional[float] = None
    memory_usage_percent: Optional[float] = None
    disk_usage_percent: Optional[float] = None
    network_in_bytes: Optional[int] = None
    network_out_bytes: Optional[int] = None
    request_count: Optional[int] = None
    error_count: Optional[int] = None
    average_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None

    rule_evaluation_count: Optional[int] = None
    violation_count: Optional[int] = None
    blocked_count: Optional[int] = None
    active_rule_count: Optional[int] = None
    conflict_count: Optional[int] = None
    unresolved_conflict_count: Optional[int] = None
    processing_queue_depth: Optional[int] = None
    cache_hit_rate: Optional[float] = None
    cache_miss_count: Optional[int] = None

    custom_metrics: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_metric(self, name: str) -> Optional[float]:
        if hasattr(self, name) and getattr(self, name) is not None:
            return float(getattr(self, name))
        return self.metrics.get(name)

    def get_all_metrics(self) -> Dict[str, float]:
        result = {}
        for field_name in [
            "cpu_usage_percent", "memory_usage_percent", "disk_usage_percent",
            "network_in_bytes", "network_out_bytes", "request_count", "error_count",
            "average_latency_ms", "p99_latency_ms", "rule_evaluation_count",
            "violation_count", "blocked_count", "active_rule_count", "conflict_count",
            "unresolved_conflict_count", "processing_queue_depth", "cache_hit_rate",
            "cache_miss_count"
        ]:
            val = getattr(self, field_name, None)
            if val is not None:
                result[field_name] = float(val)
        result.update(self.metrics)
        return result

    def get_summary(self) -> Dict[str, Any]:
        all_metrics = self.get_all_metrics()
        return {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "metric_count": len(all_metrics),
            "key_metrics": {k: v for k, v in all_metrics.items() if k in [
                "request_count", "error_count", "average_latency_ms",
                "violation_count", "blocked_count", "cache_hit_rate"
            ]},
            "host": self.host,
            "service": self.service,
            "environment": self.environment
        }

    def to_series(self) -> List[Tuple[str, float, datetime]]:
        series = []
        all_metrics = self.get_all_metrics()
        for name, value in all_metrics.items():
            series.append((name, value, self.timestamp))
        return series

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MetricsThreshold(BaseModel):
    """Threshold definitions."""

    threshold_id: str
    name: str
    description: Optional[str] = None
    metric_name: str
    metric_source: str = "system"

    warning_value: float = 0.0
    critical_value: float = 0.0
    comparison_operator: str = "greater_than"

    evaluation_window_seconds: int = Field(default=300, ge=1, le=86400)
    consecutive_hits_required: int = Field(default=1, ge=1, le=100)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)

    is_active: bool = True
    is_default: bool = False
    auto_recovery: bool = True
    recovery_value: Optional[float] = None

    severity: str = "warning"
    alert_definition_id: Optional[str] = None
    notification_channels: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def evaluate(self, current_value: float) -> Tuple[str, bool]:
        if self.comparison_operator == "greater_than":
            if current_value > self.critical_value:
                return "critical", True
            elif current_value > self.warning_value:
                return "warning", True
        elif self.comparison_operator == "less_than":
            if current_value < self.critical_value:
                return "critical", True
            elif current_value < self.warning_value:
                return "warning", True
        elif self.comparison_operator == "equal_to":
            if current_value == self.critical_value:
                return "critical", True
            elif current_value == self.warning_value:
                return "warning", True
        return "ok", False

    def is_recovered(self, current_value: float) -> bool:
        if not self.auto_recovery:
            return False
        recovery = self.recovery_value if self.recovery_value is not None else self.warning_value
        if self.comparison_operator in ("greater_than", "greater_than_or_equal"):
            return current_value <= recovery
        elif self.comparison_operator in ("less_than", "less_than_or_equal"):
            return current_value >= recovery
        return True

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


class DashboardConfig(BaseModel):
    """Dashboard configuration."""

    dashboard_id: str
    name: str
    description: Optional[str] = None
    dashboard_type: str = "monitoring"
    layout: str = "grid"
    refresh_interval_seconds: int = Field(default=30, ge=5, le=3600)
    time_range_default: str = "last_1h"

    widgets: List[Dict[str, Any]] = Field(default_factory=list)
    metric_sources: List[str] = Field(default_factory=list)
    data_filters: Dict[str, Any] = Field(default_factory=dict)
    variables: Dict[str, Any] = Field(default_factory=dict)

    is_default: bool = False
    is_public: bool = False
    is_active: bool = True
    owner: Optional[str] = None
    allowed_roles: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    theme: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def add_widget(self, widget: 'DashboardWidget') -> None:
        self.widgets.append(widget.dict())
        self.updated_at = datetime.utcnow()

    def remove_widget(self, widget_id: str) -> bool:
        original_count = len(self.widgets)
        self.widgets = [w for w in self.widgets if w.get("widget_id") != widget_id]
        if len(self.widgets) < original_count:
            self.updated_at = datetime.utcnow()
            return True
        return False

    def get_widget_count(self) -> int:
        return len(self.widgets)

    def get_widgets_by_type(self, widget_type: str) -> List[Dict[str, Any]]:
        return [w for w in self.widgets if w.get("type") == widget_type]

    def has_widget(self, widget_id: str) -> bool:
        return any(w.get("widget_id") == widget_id for w in self.widgets)

    def reorder_widgets(self, widget_ids: List[str]) -> None:
        ordered = []
        for wid in widget_ids:
            for w in self.widgets:
                if w.get("widget_id") == wid:
                    ordered.append(w)
                    break
        remaining = [w for w in self.widgets if w.get("widget_id") not in widget_ids]
        self.widgets = ordered + remaining
        self.updated_at = datetime.utcnow()

    def clone(self, new_dashboard_id: str, new_name: str) -> 'DashboardConfig':
        cloned = self.copy(deep=True)
        cloned.dashboard_id = new_dashboard_id
        cloned.name = new_name
        cloned.is_default = False
        cloned.created_at = datetime.utcnow()
        cloned.updated_at = datetime.utcnow()
        return cloned

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class DashboardWidget(BaseModel):
    """Widget definitions."""

    widget_id: str
    name: str
    description: Optional[str] = None
    widget_type: str = "chart"
    data_source: str = "metrics"
    metric_names: List[str] = Field(default_factory=list)

    width: int = Field(default=3, ge=1, le=12)
    height: int = Field(default=2, ge=1, le=12)
    position_x: int = Field(default=0, ge=0)
    position_y: int = Field(default=0, ge=0)

    chart_type: str = "line"
    aggregation: str = "avg"
    group_by: Optional[str] = None
    color_scheme: Optional[str] = None
    show_legend: bool = True
    show_thresholds: bool = False
    threshold_ids: List[str] = Field(default_factory=list)

    visual_settings: Dict[str, Any] = Field(default_factory=dict)
    query_filter: Dict[str, Any] = Field(default_factory=dict)
    time_range: Optional[str] = None

    refresh_interval_seconds: Optional[int] = None
    cache_ttl_seconds: int = Field(default=60, ge=0, le=3600)

    is_enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def get_position(self) -> Tuple[int, int]:
        return (self.position_x, self.position_y)

    def set_position(self, x: int, y: int) -> None:
        self.position_x = x
        self.position_y = y
        self.updated_at = datetime.utcnow()

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, min(width, 12))
        self.height = max(1, min(height, 12))
        self.updated_at = datetime.utcnow()

    def add_metric(self, metric_name: str) -> None:
        if metric_name not in self.metric_names:
            self.metric_names.append(metric_name)
            self.updated_at = datetime.utcnow()

    def remove_metric(self, metric_name: str) -> bool:
        if metric_name in self.metric_names:
            self.metric_names.remove(metric_name)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def enable(self) -> None:
        self.is_enabled = True
        self.updated_at = datetime.utcnow()

    def disable(self) -> None:
        self.is_enabled = False
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return self.dict()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }