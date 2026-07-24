"""
Multi-channel user notification system for exception handling.

Provides config-driven notification delivery with templates,
batching, rate limiting, delivery tracking, and retry logic.
"""

import logging
import uuid
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    """Supported notification delivery channels."""
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SMS = "sms"
    SLACK = "slack"
    TEAMS = "teams"
    PUSH = "push"
    PAGERDUTY = "pagerduty"
    CUSTOM = "custom"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(str, Enum):
    """Delivery status of a notification."""
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    DEFERRED = "deferred"
    PARTIALLY_DELIVERED = "partially_delivered"


class DeliveryMethod(str, Enum):
    """Method used for delivery."""
    SYNC = "sync"
    ASYNC = "async"
    BATCH = "batch"


@dataclass
class NotificationPreference:
    """Per-user notification preference."""
    user_id: str
    channels: Dict[str, bool] = field(default_factory=lambda: {
        NotificationChannel.EMAIL.value: True,
        NotificationChannel.IN_APP.value: True,
        NotificationChannel.WEBHOOK.value: False,
        NotificationChannel.SMS.value: False,
    })
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    max_daily_notifications: int = 100
    priority_threshold: NotificationPriority = NotificationPriority.NORMAL
    digest_frequency: Optional[str] = None
    locale: str = "en-US"
    timezone: str = "UTC"
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_channel_enabled(self, channel: NotificationChannel) -> bool:
        return self.channels.get(channel.value, False)

    def is_in_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False
        now = now or datetime.utcnow()
        current = now.hour * 60 + now.minute
        start_parts = self.quiet_hours_start.split(":")
        end_parts = self.quiet_hours_end.split(":")
        start = int(start_parts[0]) * 60 + int(start_parts[1])
        end = int(end_parts[0]) * 60 + int(end_parts[1])
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationTemplate:
    """Notification template with variable substitution."""
    template_id: str
    channel: NotificationChannel
    subject_template: str = ""
    body_template: str = ""
    html_template: Optional[str] = None
    variables: Dict[str, str] = field(default_factory=dict)
    default_variables: Dict[str, str] = field(default_factory=dict)
    required_variables: List[str] = field(default_factory=list)
    max_length: int = 0
    version: str = "1.0.0"

    def render(self, variables: Dict[str, Any]) -> "RenderedNotification":
        merged = {**self.default_variables, **variables}
        missing = [v for v in self.required_variables if v not in merged]
        if missing:
            raise ValueError(f"Missing required template variables: {missing}")
        subject = self._substitute(self.subject_template, merged)
        body = self._substitute(self.body_template, merged)
        html = self._substitute(self.html_template, merged) if self.html_template else None
        if self.max_length and len(body) > self.max_length:
            body = body[:self.max_length]
        return RenderedNotification(
            template_id=self.template_id,
            channel=self.channel,
            subject=subject,
            body=body,
            html_body=html,
            variables=merged,
        )

    @staticmethod
    def _substitute(template: str, variables: Dict[str, Any]) -> str:
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            return str(variables.get(key, match.group(0)))
        return re.sub(r'\{\{(\w+)\}\}', replacer, template)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "channel": self.channel.value,
        }


@dataclass
class RenderedNotification:
    """Rendered notification ready for delivery."""
    template_id: str
    channel: NotificationChannel
    subject: str
    body: str
    html_body: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "channel": self.channel.value,
            "subject": self.subject,
            "body": self.body,
            "html_body": self.html_body,
            "variables": self.variables,
        }


@dataclass
class DeliveryReceipt:
    """Delivery tracking receipt."""
    notification_id: str
    channel: NotificationChannel
    status: NotificationStatus
    attempted_at: datetime
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    attempts: int = 1
    provider_response: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "channel": self.channel.value,
            "status": self.status.value,
            "attempted_at": self.attempted_at.isoformat(),
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
        }


@dataclass
class NotificationRecord:
    """Complete notification record for audit."""
    notification_id: str
    user_id: str
    channels: List[NotificationChannel]
    priority: NotificationPriority
    status: NotificationStatus
    created_at: datetime
    subject: str = ""
    body: str = ""
    template_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    receipts: List[DeliveryReceipt] = field(default_factory=list)
    batch_id: Optional[str] = None
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    dedup_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "channels": [c.value for c in self.channels],
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "receipts": [r.to_dict() for r in self.receipts],
        }


@dataclass
class BatchConfig:
    """Batching configuration for notification grouping."""
    batch_id: str
    max_size: int = 100
    max_wait_seconds: int = 30
    flush_on_priority: Optional[NotificationPriority] = NotificationPriority.HIGH
    merge_similar: bool = True
    merge_key: str = "type"
    channel: NotificationChannel = NotificationChannel.IN_APP

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "channel": self.channel.value,
            "flush_on_priority": self.flush_on_priority.value if self.flush_on_priority else None,
        }


@dataclass
class RateLimiterConfig:
    """Rate limiting configuration per channel."""
    channel: NotificationChannel
    max_per_minute: int = 10
    max_per_hour: int = 100
    max_per_day: int = 1000
    burst_size: int = 5
    cooldown_seconds: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "channel": self.channel.value,
        }


class DeliveryProvider:
    """Abstract delivery provider interface."""

    def deliver(self, notification: NotificationRecord, channel: NotificationChannel,
                rendered: RenderedNotification) -> DeliveryReceipt:
        raise NotImplementedError


class ConsoleDeliveryProvider(DeliveryProvider):
    """Console-based delivery provider for development/testing."""

    def deliver(self, notification: NotificationRecord, channel: NotificationChannel,
                rendered: RenderedNotification) -> DeliveryReceipt:
        logger.info(
            "[CONSOLE] Delivering to %s via %s: subject=%s body_len=%d",
            notification.user_id, channel.value, rendered.subject, len(rendered.body),
        )
        return DeliveryReceipt(
            notification_id=notification.notification_id,
            channel=channel,
            status=NotificationStatus.DELIVERED,
            attempted_at=datetime.utcnow(),
            delivered_at=datetime.utcnow(),
            duration_ms=0,
        )


class LoggingDeliveryProvider(DeliveryProvider):
    """Logging delivery provider that records delivery intent."""

    def deliver(self, notification: NotificationRecord, channel: NotificationChannel,
                rendered: RenderedNotification) -> DeliveryReceipt:
        logger.info(
            "DELIVERY: user=%s channel=%s notification_id=%s subject=%s",
            notification.user_id, channel.value, notification.notification_id, rendered.subject,
        )
        return DeliveryReceipt(
            notification_id=notification.notification_id,
            channel=channel,
            status=NotificationStatus.DELIVERED,
            attempted_at=datetime.utcnow(),
            delivered_at=datetime.utcnow(),
            duration_ms=0,
        )


class UserNotification:
    """Multi-channel notification engine with templates, batching, and rate limiting."""

    def __init__(self) -> None:
        self.logger = logger
        self._records: Dict[str, NotificationRecord] = {}
        self._preferences: Dict[str, NotificationPreference] = {}
        self._templates: Dict[str, Dict[str, NotificationTemplate]] = {}
        self._batches: Dict[str, List[NotificationRecord]] = {}
        self._batch_configs: Dict[str, BatchConfig] = {}
        self._rate_limiters: Dict[str, RateLimiterConfig] = {}
        self._rate_windows: Dict[str, List[datetime]] = {}
        self._providers: Dict[str, DeliveryProvider] = {}
        self._daily_counts: Dict[str, int] = {}
        self._daily_reset: Optional[datetime] = None
        self._dedup_cache: Dict[str, List[str]] = {}
        self._handlers: Dict[str, List[Callable]] = {
            "before_send": [],
            "after_send": [],
            "on_failure": [],
            "on_retry": [],
            "on_batch_flush": [],
        }
        self._init_defaults()

    def _init_defaults(self) -> None:
        self.register_provider(NotificationChannel.EMAIL, ConsoleDeliveryProvider())
        self.register_provider(NotificationChannel.IN_APP, LoggingDeliveryProvider())
        self.register_provider(NotificationChannel.WEBHOOK, LoggingDeliveryProvider())
        self.register_provider(NotificationChannel.SMS, ConsoleDeliveryProvider())

        for channel in NotificationChannel:
            self._rate_limiters[channel.value] = RateLimiterConfig(channel=channel)

        self._templates["default"] = {}
        self._add_default_templates()

    def _add_default_templates(self) -> None:
        defaults = {
            NotificationChannel.EMAIL: NotificationTemplate(
                template_id="exception_alert_email",
                channel=NotificationChannel.EMAIL,
                subject_template="[{{severity|upper}}] Exception Alert: {{title}}",
                body_template=(
                    "Exception Type: {{exception_type}}\n"
                    "Severity: {{severity}}\n"
                    "Timestamp: {{timestamp}}\n"
                    "Source: {{source}}\n"
                    "Message: {{message}}\n"
                    "Rule: {{rule_name}} ({{rule_id}})\n"
                    "Action: {{action_taken}}\n"
                    "---\n"
                    "Context:\n"
                    "{{context}}\n"
                    "---\n"
                    "Please review and take appropriate action."
                ),
                html_template=(
                    "<h2>Exception Alert: {{title}}</h2>"
                    "<table>"
                    "<tr><td>Type</td><td>{{exception_type}}</td></tr>"
                    "<tr><td>Severity</td><td>{{severity}}</td></tr>"
                    "<tr><td>Timestamp</td><td>{{timestamp}}</td></tr>"
                    "<tr><td>Source</td><td>{{source}}</td></tr>"
                    "<tr><td>Rule</td><td>{{rule_name}}</td></tr>"
                    "<tr><td>Action</td><td>{{action_taken}}</td></tr>"
                    "</table>"
                    "<pre>{{message}}</pre>"
                ),
                required_variables=["title", "severity", "message"],
            ),
            NotificationChannel.IN_APP: NotificationTemplate(
                template_id="exception_alert_inapp",
                channel=NotificationChannel.IN_APP,
                subject_template="Exception: {{title}}",
                body_template="[{{severity|upper}}] {{message}}",
                required_variables=["title", "severity", "message"],
            ),
            NotificationChannel.SMS: NotificationTemplate(
                template_id="exception_alert_sms",
                channel=NotificationChannel.SMS,
                subject_template="",
                body_template="ALERT [{{severity|upper}}]: {{message[:120]}}",
                max_length=160,
                required_variables=["severity", "message"],
            ),
            NotificationChannel.WEBHOOK: NotificationTemplate(
                template_id="exception_alert_webhook",
                channel=NotificationChannel.WEBHOOK,
                subject_template="",
                body_template=json.dumps({
                    "event": "exception_alert",
                    "severity": "{{severity}}",
                    "title": "{{title}}",
                    "message": "{{message}}",
                    "timestamp": "{{timestamp}}",
                    "source": "{{source}}",
                    "rule_name": "{{rule_name}}",
                    "rule_id": "{{rule_id}}",
                    "action_taken": "{{action_taken}}",
                    "context": "{{context}}",
                }),
                required_variables=["title", "severity", "message"],
            ),
            NotificationChannel.SLACK: NotificationTemplate(
                template_id="exception_alert_slack",
                channel=NotificationChannel.SLACK,
                subject_template="",
                body_template=json.dumps({
                    "text": "*Exception Alert:* {{title}}",
                    "attachments": [{
                        "color": "{{slack_color}}",
                        "fields": [
                            {"title": "Severity", "value": "{{severity|upper}}", "short": True},
                            {"title": "Type", "value": "{{exception_type}}", "short": True},
                            {"title": "Message", "value": "{{message}}"},
                            {"title": "Rule", "value": "{{rule_name}} ({{rule_id}})"},
                            {"title": "Action", "value": "{{action_taken}}"},
                        ],
                        "footer": "Rules Emerging Pattern",
                        "ts": "{{timestamp_unix}}",
                    }],
                }),
                required_variables=["title", "severity", "message"],
            ),
            NotificationChannel.PAGERDUTY: NotificationTemplate(
                template_id="exception_alert_pagerduty",
                channel=NotificationChannel.PAGERDUTY,
                subject_template="",
                body_template=json.dumps({
                    "routing_key": "{{pagerduty_key}}",
                    "event_action": "trigger",
                    "payload": {
                        "summary": "Exception Alert: {{title}}",
                        "severity": "{{pd_severity}}",
                        "source": "{{source}}",
                        "custom_details": {
                            "exception_type": "{{exception_type}}",
                            "rule_name": "{{rule_name}}",
                            "rule_id": "{{rule_id}}",
                            "action_taken": "{{action_taken}}",
                            "message": "{{message}}",
                        },
                    },
                }),
                required_variables=["title", "severity", "message", "pagerduty_key"],
            ),
        }
        for channel, template in defaults.items():
            self.add_template(template, "default")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_provider(self, channel: NotificationChannel, provider: DeliveryProvider) -> None:
        self._providers[channel.value] = provider
        self.logger.info("Registered provider for channel %s", channel.value)

    def register_handler(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].append(handler)

    def set_preference(self, user_id: str, preference: NotificationPreference) -> None:
        self._preferences[user_id] = preference

    def get_preference(self, user_id: str) -> NotificationPreference:
        if user_id not in self._preferences:
            self._preferences[user_id] = NotificationPreference(user_id=user_id)
        return self._preferences[user_id]

    def add_template(self, template: NotificationTemplate, namespace: str = "default") -> None:
        if namespace not in self._templates:
            self._templates[namespace] = {}
        self._templates[namespace][template.template_id] = template

    def get_template(self, template_id: str, namespace: str = "default") -> Optional[NotificationTemplate]:
        return self._templates.get(namespace, {}).get(template_id)

    def set_batch_config(self, config: BatchConfig) -> None:
        self._batch_configs[config.batch_id] = config
        self._batches.setdefault(config.batch_id, [])

    def set_rate_limiter(self, config: RateLimiterConfig) -> None:
        self._rate_limiters[config.channel.value] = config

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def before_send(self, handler: Callable) -> None:
        self._handlers["before_send"].append(handler)

    def after_send(self, handler: Callable) -> None:
        self._handlers["after_send"].append(handler)

    def on_failure(self, handler: Callable) -> None:
        self._handlers["on_failure"].append(handler)

    def on_retry(self, handler: Callable) -> None:
        self._handlers["on_retry"].append(handler)

    def on_batch_flush(self, handler: Callable) -> None:
        self._handlers["on_batch_flush"].append(handler)

    def _fire_event(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception as exc:
                self.logger.error("Event handler %s failed: %s", event, exc)

    # ------------------------------------------------------------------
    # Core Notification
    # ------------------------------------------------------------------

    def send(
        self,
        user_id: str,
        message: str,
        channels: Optional[List[NotificationChannel]] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        template_id: Optional[str] = None,
        template_variables: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        source: str = "system",
        batch_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationRecord:
        pref = self.get_preference(user_id)
        if not pref.enabled:
            self.logger.info("User %s has notifications disabled", user_id)
            raise RuntimeError(f"Notifications disabled for user {user_id}")

        resolved_channels = channels or self._resolve_channels(pref, priority)
        if not resolved_channels:
            self.logger.info("No enabled channels for user %s at priority %s", user_id, priority.value)
            raise RuntimeError(f"No enabled channels for user {user_id}")

        if self._check_daily_limit(user_id, pref):
            self.logger.warning("Daily notification limit reached for user %s", user_id)
            raise RuntimeError(f"Daily notification limit reached for user {user_id}")

        notification_id = self._generate_id(user_id, message)
        dedup_key = self._compute_dedup_key(user_id, message, template_id)
        notification = NotificationRecord(
            notification_id=notification_id,
            user_id=user_id,
            channels=resolved_channels,
            priority=priority,
            status=NotificationStatus.PENDING,
            created_at=datetime.utcnow(),
            subject="",
            body=message,
            template_id=template_id,
            context=context or {},
            batch_id=batch_id,
            source=source,
            metadata=metadata or {},
            dedup_key=dedup_key,
        )
        self._records[notification_id] = notification

        if self._is_duplicate(dedup_key, notification_id):
            self.logger.info("Duplicate notification suppressed: key=%s", dedup_key)
            return notification

        self._track_dedup(dedup_key, notification_id)

        if batch_id and batch_id in self._batch_configs:
            self._add_to_batch(notification)
            return notification

        for channel in resolved_channels:
            self._dispatch(notification, channel, template_id, template_variables)

        return notification

    def send_from_violation(
        self,
        user_id: str,
        violation: Violation,
        channels: Optional[List[NotificationChannel]] = None,
        priority: Optional[NotificationPriority] = None,
        **kwargs: Any,
    ) -> NotificationRecord:
        resolved_priority = priority or self._severity_to_priority(violation.rule_severity)
        variables = {
            "title": f"Rule Violation: {violation.rule_name}",
            "severity": violation.rule_severity.value,
            "exception_type": violation.violation_type.value,
            "message": violation.explanation or violation.matched_content or "No details available",
            "rule_name": violation.rule_name,
            "rule_id": violation.rule_id,
            "action_taken": violation.action_taken.value,
            "source": violation.detection_method,
            "timestamp": violation.detected_at.isoformat(),
            "slack_color": self._severity_to_slack_color(violation.rule_severity),
            "pd_severity": self._severity_to_pd_severity(violation.rule_severity),
            "timestamp_unix": str(int(violation.detected_at.timestamp())),
            "context": json.dumps(violation.context, default=str),
        }
        return self.send(
            user_id=user_id,
            message=variables["message"],
            channels=channels,
            priority=resolved_priority,
            template_id=kwargs.pop("template_id", None),
            template_variables=variables,
            context={"violation": violation.dict(), **kwargs.pop("context", {})},
            source="violation",
            metadata={"violation_id": violation.rule_id, **kwargs.pop("metadata", {})},
            **kwargs,
        )

    def send_from_validation(
        self,
        user_id: str,
        result: ValidationResult,
        channels: Optional[List[NotificationChannel]] = None,
        **kwargs: Any,
    ) -> List[NotificationRecord]:
        records = []
        for violation in result.violations:
            rec = self.send_from_violation(user_id, violation, channels, **kwargs)
            records.append(rec)
        if not result.violations and result.warnings:
            for warning in result.warnings:
                rec = self.send_from_violation(user_id, warning, channels,
                                                priority=NotificationPriority.LOW, **kwargs)
                records.append(rec)
        return records

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        notification: NotificationRecord,
        channel: NotificationChannel,
        template_id: Optional[str] = None,
        template_variables: Optional[Dict[str, Any]] = None,
    ) -> None:
        provider = self._providers.get(channel.value)
        if not provider:
            self.logger.warning("No provider registered for channel %s", channel.value)
            return

        if not self._check_rate_limit(channel):
            self.logger.warning("Rate limit exceeded for channel %s, deferring notification", channel.value)
            notification.status = NotificationStatus.DEFERRED
            return

        notification.status = NotificationStatus.SENDING
        self._fire_event("before_send", notification=notification, channel=channel)

        rendered = self._render(notification, channel, template_id, template_variables)
        if not rendered:
            notification.status = NotificationStatus.FAILED
            self._fire_event("on_failure", notification=notification, channel=channel,
                             error="Template rendering failed")
            return

        receipt = self._deliver_with_retry(notification, channel, provider, rendered)
        notification.receipts.append(receipt)

        if receipt.status == NotificationStatus.DELIVERED:
            notification.status = NotificationStatus.DELIVERED
            self._update_daily_count(notification.user_id)
            self._fire_event("after_send", notification=notification, channel=channel, receipt=receipt)
        else:
            notification.status = NotificationStatus.FAILED
            self._fire_event("on_failure", notification=notification, channel=channel,
                             error=receipt.error_message)

    def _deliver_with_retry(
        self,
        notification: NotificationRecord,
        channel: NotificationChannel,
        provider: DeliveryProvider,
        rendered: RenderedNotification,
        max_retries: int = 3,
    ) -> DeliveryReceipt:
        attempt = 0
        last_error: Optional[str] = None
        while attempt < max_retries:
            attempt += 1
            start = datetime.utcnow()
            try:
                receipt = provider.deliver(notification, channel, rendered)
                receipt.attempted_at = start
                receipt.duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
                receipt.attempts = attempt
                if receipt.status == NotificationStatus.DELIVERED:
                    return receipt
                last_error = receipt.error_message or "Delivery returned non-success status"
                if attempt < max_retries:
                    notification.status = NotificationStatus.RETRYING
                    self._fire_event("on_retry", notification=notification, channel=channel,
                                     attempt=attempt, error=last_error)
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning("Delivery attempt %d/%d failed for %s via %s: %s",
                                    attempt, max_retries, notification.notification_id, channel.value, exc)
                if attempt < max_retries:
                    notification.status = NotificationStatus.RETRYING
                    self._fire_event("on_retry", notification=notification, channel=channel,
                                     attempt=attempt, error=last_error)
        receipt = DeliveryReceipt(
            notification_id=notification.notification_id,
            channel=channel,
            status=NotificationStatus.FAILED,
            attempted_at=datetime.utcnow(),
            failed_at=datetime.utcnow(),
            error_message=last_error or "Max retries exceeded",
            attempts=attempt,
        )
        return receipt

    def _render(
        self,
        notification: NotificationRecord,
        channel: NotificationChannel,
        template_id: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Optional[RenderedNotification]:
        tid = template_id
        if not tid:
            tid = self._resolve_template_id(channel)
        template = self.get_template(tid)
        if not template:
            self.logger.warning("Template %s not found for channel %s", tid, channel.value)
            return None
        try:
            rendered = template.render(variables or {})
            if not notification.subject:
                notification.subject = rendered.subject
            if not notification.body:
                notification.body = rendered.body
            return rendered
        except Exception as exc:
            self.logger.error("Template rendering failed for %s: %s", tid, exc)
            return None

    def _resolve_template_id(self, channel: NotificationChannel) -> str:
        mapping = {
            NotificationChannel.EMAIL: "exception_alert_email",
            NotificationChannel.IN_APP: "exception_alert_inapp",
            NotificationChannel.SMS: "exception_alert_sms",
            NotificationChannel.WEBHOOK: "exception_alert_webhook",
            NotificationChannel.SLACK: "exception_alert_slack",
            NotificationChannel.PAGERDUTY: "exception_alert_pagerduty",
        }
        return mapping.get(channel, "exception_alert_inapp")

    # ------------------------------------------------------------------
    # Batching
    # ------------------------------------------------------------------

    def _add_to_batch(self, notification: NotificationRecord) -> None:
        batch_id = notification.batch_id
        if not batch_id or batch_id not in self._batch_configs:
            return
        batch = self._batches.setdefault(batch_id, [])
        config = self._batch_configs[batch_id]
        if len(batch) >= config.max_size:
            self.flush_batch(batch_id)
            batch = self._batches[batch_id]
        batch.append(notification)
        notification.status = NotificationStatus.QUEUED
        if config.flush_on_priority and notification.priority.value <= config.flush_on_priority.value:
            self.flush_batch(batch_id)

    def flush_batch(self, batch_id: str) -> List[NotificationRecord]:
        config = self._batch_configs.get(batch_id)
        if not config:
            self.logger.warning("No batch config for %s", batch_id)
            return []
        batch = self._batches.get(batch_id, [])
        if not batch:
            return []
        self._batches[batch_id] = []
        self._fire_event("on_batch_flush", batch_id=batch_id, batch_size=len(batch))
        if config.merge_similar:
            batch = self._merge_batch(batch, config.merge_key)
        for notification in batch:
            for channel in notification.channels:
                self._dispatch(notification, channel, notification.template_id)
        return batch

    def flush_all_batches(self) -> Dict[str, List[NotificationRecord]]:
        results = {}
        for batch_id in list(self._batch_configs.keys()):
            results[batch_id] = self.flush_batch(batch_id)
        return results

    def get_batch_size(self, batch_id: str) -> int:
        return len(self._batches.get(batch_id, []))

    @staticmethod
    def _merge_batch(batch: List[NotificationRecord], merge_key: str) -> List[NotificationRecord]:
        merged_map: Dict[str, NotificationRecord] = {}
        for record in batch:
            key = record.context.get(merge_key, "default")
            if key in merged_map:
                existing = merged_map[key]
                existing.body += f"\n---\n{record.body}"
                existing.receipts.extend(record.receipts)
            else:
                merged_map[key] = record
        return list(merged_map.values())

    # ------------------------------------------------------------------
    # Channel Resolution
    # ------------------------------------------------------------------

    def _resolve_channels(
        self,
        pref: NotificationPreference,
        priority: NotificationPriority,
    ) -> List[NotificationChannel]:
        channels = []
        priority_order = [NotificationPriority.LOW, NotificationPriority.NORMAL,
                          NotificationPriority.HIGH, NotificationPriority.URGENT]
        if priority_order.index(priority) < priority_order.index(pref.priority_threshold):
            return channels
        for channel in NotificationChannel:
            if pref.is_channel_enabled(channel):
                if pref.is_in_quiet_hours() and channel in (
                    NotificationChannel.EMAIL, NotificationChannel.IN_APP
                ):
                    continue
                channels.append(channel)
        return channels

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self, channel: NotificationChannel) -> bool:
        config = self._rate_limiters.get(channel.value)
        if not config:
            return True
        now = datetime.utcnow()
        window = self._rate_windows.setdefault(channel.value, [])
        minute_cutoff = now - timedelta(minutes=1)
        hour_cutoff = now - timedelta(hours=1)
        day_cutoff = now - timedelta(days=1)
        window[:] = [t for t in window if t > day_cutoff]
        recent_minute = sum(1 for t in window if t > minute_cutoff)
        recent_hour = sum(1 for t in window if t > hour_cutoff)
        if recent_minute >= config.max_per_minute:
            return False
        if recent_hour >= config.max_per_hour:
            return False
        if len(window) >= config.max_per_day:
            return False
        if window and (now - window[-1]).total_seconds() < config.cooldown_seconds:
            return False
        window.append(now)
        return True

    def get_rate_limit_status(self, channel: NotificationChannel) -> Dict[str, Any]:
        config = self._rate_limiters.get(channel.value)
        if not config:
            return {"channel": channel.value, "configured": False}
        now = datetime.utcnow()
        window = self._rate_windows.get(channel.value, [])
        minute_cutoff = now - timedelta(minutes=1)
        hour_cutoff = now - timedelta(hours=1)
        recent_minute = sum(1 for t in window if t > minute_cutoff)
        recent_hour = sum(1 for t in window if t > hour_cutoff)
        return {
            "channel": channel.value,
            "configured": True,
            "current_1m": recent_minute,
            "limit_1m": config.max_per_minute,
            "current_1h": recent_hour,
            "limit_1h": config.max_per_hour,
            "current_1d": len(window),
            "limit_1d": config.max_per_day,
            "remaining_1m": config.max_per_minute - recent_minute,
            "remaining_1h": config.max_per_hour - recent_hour,
            "remaining_1d": config.max_per_day - len(window),
        }

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _compute_dedup_key(self, user_id: str, message: str, template_id: Optional[str] = None) -> str:
        raw = f"{user_id}:{message}:{template_id or ''}:{datetime.utcnow().strftime('%Y%m%d%H')}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _is_duplicate(self, dedup_key: str, notification_id: str) -> bool:
        existing = self._dedup_cache.get(dedup_key, [])
        return len(existing) > 0 and notification_id not in existing

    def _track_dedup(self, dedup_key: str, notification_id: str) -> None:
        if dedup_key not in self._dedup_cache:
            self._dedup_cache[dedup_key] = []
        self._dedup_cache[dedup_key].append(notification_id)
        if len(self._dedup_cache) > 10000:
            oldest_keys = sorted(self._dedup_cache.keys())[:1000]
            for k in oldest_keys:
                del self._dedup_cache[k]

    def clear_dedup_cache(self) -> None:
        self._dedup_cache.clear()

    # ------------------------------------------------------------------
    # Daily Limits
    # ------------------------------------------------------------------

    def _check_daily_limit(self, user_id: str, pref: NotificationPreference) -> bool:
        self._reset_daily_if_needed()
        return self._daily_counts.get(user_id, 0) >= pref.max_daily_notifications

    def _update_daily_count(self, user_id: str) -> None:
        self._reset_daily_if_needed()
        self._daily_counts[user_id] = self._daily_counts.get(user_id, 0) + 1

    def _reset_daily_if_needed(self) -> None:
        now = datetime.utcnow()
        if self._daily_reset is None or now.date() > self._daily_reset.date():
            self._daily_counts.clear()
            self._daily_reset = now

    def get_daily_count(self, user_id: str) -> int:
        self._reset_daily_if_needed()
        return self._daily_counts.get(user_id, 0)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_notification(self, notification_id: str) -> Optional[NotificationRecord]:
        return self._records.get(notification_id)

    def get_notifications_by_user(self, user_id: str, limit: int = 100) -> List[NotificationRecord]:
        results = [r for r in self._records.values() if r.user_id == user_id]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def get_notifications_by_status(self, status: NotificationStatus, limit: int = 100) -> List[NotificationRecord]:
        results = [r for r in self._records.values() if r.status == status]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def get_failed_notifications(self, limit: int = 100) -> List[NotificationRecord]:
        return self.get_notifications_by_status(NotificationStatus.FAILED, limit)

    def get_pending_notifications(self, limit: int = 100) -> List[NotificationRecord]:
        return self.get_notifications_by_status(NotificationStatus.PENDING, limit)

    def get_notifications_by_source(self, source: str, limit: int = 100) -> List[NotificationRecord]:
        results = [r for r in self._records.values() if r.source == source]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def search_notifications(
        self,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        channel: Optional[NotificationChannel] = None,
        priority: Optional[NotificationPriority] = None,
        status: Optional[NotificationStatus] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[NotificationRecord]:
        results = list(self._records.values())
        if query:
            q = query.lower()
            results = [r for r in results if q in r.body.lower() or q in r.subject.lower()]
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        if channel:
            results = [r for r in results if channel in r.channels]
        if priority:
            results = [r for r in results if r.priority == priority]
        if status:
            results = [r for r in results if r.status == status]
        if start_time:
            results = [r for r in results if r.created_at >= start_time]
        if end_time:
            results = [r for r in results if r.created_at <= end_time]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._records)
        delivered = sum(1 for r in self._records.values() if r.status == NotificationStatus.DELIVERED)
        failed = sum(1 for r in self._records.values() if r.status == NotificationStatus.FAILED)
        pending = sum(1 for r in self._records.values() if r.status == NotificationStatus.PENDING)
        by_channel: Dict[str, int] = {}
        by_priority: Dict[str, int] = {}
        total_attempts = 0
        total_duration_ms = 0
        for record in self._records.values():
            by_priority[record.priority.value] = by_priority.get(record.priority.value, 0) + 1
            for ch in record.channels:
                by_channel[ch.value] = by_channel.get(ch.value, 0) + 1
            for receipt in record.receipts:
                total_attempts += receipt.attempts
                total_duration_ms += receipt.duration_ms
        delivery_rate = round(delivered / total * 100, 2) if total else 0.0
        return {
            "total_notifications": total,
            "delivered": delivered,
            "failed": failed,
            "pending": pending,
            "delivery_rate": delivery_rate,
            "by_channel": by_channel,
            "by_priority": by_priority,
            "total_delivery_attempts": total_attempts,
            "avg_attempts_per_notification": round(total_attempts / total, 2) if total else 0.0,
            "avg_delivery_duration_ms": round(total_duration_ms / total, 2) if total else 0.0,
            "active_users": len(set(r.user_id for r in self._records.values())),
            "active_batches": len(self._batches),
            "batch_sizes": {bid: len(b) for bid, b in self._batches.items()},
        }

    def get_user_statistics(self, user_id: str) -> Dict[str, Any]:
        user_records = [r for r in self._records.values() if r.user_id == user_id]
        total = len(user_records)
        if total == 0:
            return {"user_id": user_id, "total": 0}
        delivered = sum(1 for r in user_records if r.status == NotificationStatus.DELIVERED)
        failed = sum(1 for r in user_records if r.status == NotificationStatus.FAILED)
        by_channel: Dict[str, int] = {}
        for record in user_records:
            for ch in record.channels:
                by_channel[ch.value] = by_channel.get(ch.value, 0) + 1
        last_24h = sum(1 for r in user_records
                       if r.created_at > datetime.utcnow() - timedelta(hours=24))
        return {
            "user_id": user_id,
            "total": total,
            "delivered": delivered,
            "failed": failed,
            "delivery_rate": round(delivered / total * 100, 2) if total else 0.0,
            "by_channel": by_channel,
            "last_24h_count": last_24h,
            "daily_limit": self.get_preference(user_id).max_daily_notifications,
            "today_count": self.get_daily_count(user_id),
            "preferences": self.get_preference(user_id).to_dict(),
        }

    def get_channel_statistics(self, channel: NotificationChannel) -> Dict[str, Any]:
        channel_records = [r for r in self._records.values() if channel in r.channels]
        total = len(channel_records)
        if total == 0:
            return {"channel": channel.value, "total": 0}
        delivered = sum(1 for r in channel_records if r.status == NotificationStatus.DELIVERED)
        failed = sum(1 for r in channel_records if r.status == NotificationStatus.FAILED)
        return {
            "channel": channel.value,
            "total": total,
            "delivered": delivered,
            "failed": failed,
            "delivery_rate": round(delivered / total * 100, 2) if total else 0.0,
            "rate_limit": self.get_rate_limit_status(channel),
        }

    # ------------------------------------------------------------------
    # Retry Failed
    # ------------------------------------------------------------------

    def retry_failed(self, max_retries: int = 3, limit: int = 50) -> List[str]:
        retried: List[str] = []
        failed = self.get_failed_notifications(limit)
        for notification in failed:
            if notification.status == NotificationStatus.FAILED:
                notification.status = NotificationStatus.RETRYING
                for channel in notification.channels:
                    provider = self._providers.get(channel.value)
                    if not provider:
                        continue
                    rendered = self._render(notification, channel, notification.template_id)
                    if rendered:
                        receipt = self._deliver_with_retry(
                            notification, channel, provider, rendered, max_retries=1,
                        )
                        notification.receipts.append(receipt)
                        if receipt.status == NotificationStatus.DELIVERED:
                            notification.status = NotificationStatus.DELIVERED
                            retried.append(notification.notification_id)
                        else:
                            notification.status = NotificationStatus.FAILED
        return retried

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id(user_id: str, message: str) -> str:
        raw = f"{user_id}:{message}:{datetime.utcnow().isoformat()}:{uuid.uuid4().hex[:8]}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"notif_{h}"

    @staticmethod
    def _severity_to_priority(severity: RuleSeverity) -> NotificationPriority:
        mapping = {
            RuleSeverity.CRITICAL: NotificationPriority.URGENT,
            RuleSeverity.HIGH: NotificationPriority.HIGH,
            RuleSeverity.MEDIUM: NotificationPriority.NORMAL,
            RuleSeverity.LOW: NotificationPriority.LOW,
        }
        return mapping.get(severity, NotificationPriority.NORMAL)

    @staticmethod
    def _severity_to_slack_color(severity: RuleSeverity) -> str:
        mapping = {
            RuleSeverity.CRITICAL: "danger",
            RuleSeverity.HIGH: "warning",
            RuleSeverity.MEDIUM: "good",
            RuleSeverity.LOW: "#808080",
        }
        return mapping.get(severity, "#808080")

    @staticmethod
    def _severity_to_pd_severity(severity: RuleSeverity) -> str:
        mapping = {
            RuleSeverity.CRITICAL: "critical",
            RuleSeverity.HIGH: "error",
            RuleSeverity.MEDIUM: "warning",
            RuleSeverity.LOW: "info",
        }
        return mapping.get(severity, "info")

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, notification_id: str) -> bool:
        return notification_id in self._records
