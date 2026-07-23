"""Audit logging for rule engine with queryable trail, export, and retention policies."""
import logging
import json
import uuid
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    RULE_EVALUATED = "rule_evaluated"
    RULE_ADDED = "rule_added"
    RULE_REMOVED = "rule_removed"
    RULE_MODIFIED = "rule_modified"
    ENFORCEMENT_BLOCKED = "enforcement_blocked"
    ENFORCEMENT_WARNED = "enforcement_warned"
    USER_OVERRIDE = "user_override"
    CONFIG_CHANGED = "config_changed"
    ERROR = "error"
    FALLBACK_TRIGGERED = "fallback_triggered"


@dataclass
class AuditEntry:
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    source: str
    user_id: Optional[str]
    rule_id: Optional[str]
    details: Dict[str, Any]
    severity: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._trail: deque = deque(maxlen=self.config.get("max_entries", 100000))
        self._listeners: List[Callable[[AuditEntry], None]] = []
        self._log_count = 0
        self._export_format = self.config.get("export_format", "json")
        self._retention_days = self.config.get("retention_days", 90)
        self._batch_size = self.config.get("batch_size", 100)
        logger.info("AuditLogger initialized (max_entries=%d, retention=%dd)",
                     self._trail.maxlen, self._retention_days)

    def log_event(self, event_type: AuditEventType, source: str,
                  details: Dict[str, Any], user_id: Optional[str] = None,
                  rule_id: Optional[str] = None,
                  severity: str = "info") -> AuditEntry:
        entry = AuditEntry(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source=source,
            user_id=user_id,
            rule_id=rule_id,
            details=details,
            severity=severity,
        )
        self._trail.append(entry)
        self._log_count += 1
        self._enforce_retention()

        for listener in self._listeners:
            try:
                listener(entry)
            except Exception as e:
                logger.error("Audit listener error: %s", e)

        logger.debug("Audit: %s [%s] user=%s rule=%s", event_type.value, severity, user_id, rule_id)
        return entry

    def log_batch(self, entries: List[Dict[str, Any]]) -> List[AuditEntry]:
        results = []
        for e in entries:
            et = e.get("event_type", e.get("type", "error"))
            event_type = AuditEventType(et) if et in [t.value for t in AuditEventType] else AuditEventType.ERROR
            results.append(self.log_event(
                event_type=event_type,
                source=e.get("source", "unknown"),
                details=e.get("details", {}),
                user_id=e.get("user_id"),
                rule_id=e.get("rule_id"),
                severity=e.get("severity", "info"),
            ))
        return results

    def register_listener(self, listener: Callable[[AuditEntry], None]) -> None:
        self._listeners.append(listener)
        logger.debug("Registered audit listener (%d total)", len(self._listeners))

    def query(self, event_type: Optional[AuditEventType] = None,
              rule_id: Optional[str] = None, user_id: Optional[str] = None,
              since: Optional[datetime] = None, until: Optional[datetime] = None,
              severity: Optional[str] = None, limit: int = 100) -> List[AuditEntry]:
        results = list(self._trail)
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if rule_id:
            results = [e for e in results if e.rule_id == rule_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]
        if severity:
            results = [e for e in results if e.severity == severity]
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    def export(self, format: str = "json", limit: int = 1000) -> str:
        entries = list(self._trail)[-limit:]
        if format == "json":
            return json.dumps([asdict(e) for e in entries], default=str, indent=2)
        elif format == "csv":
            lines = ["event_id,event_type,timestamp,source,user_id,rule_id,severity"]
            for e in entries:
                lines.append(
                    f"{e.event_id},{e.event_type.value},{e.timestamp.isoformat()},"
                    f"{e.source},{e.user_id or ''},{e.rule_id or ''},{e.severity}"
                )
            return "\n".join(lines)
        raise ValueError(f"Unsupported export format: {format}")

    def count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for e in self._trail:
            counts[e.event_type.value] += 1
        return dict(counts)

    def count_by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for e in self._trail:
            counts[e.severity] += 1
        return dict(counts)

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_events": self._log_count,
            "trail_size": len(self._trail),
            "by_type": self.count_by_type(),
            "by_severity": self.count_by_severity(),
            "retention_days": self._retention_days,
            "listeners": len(self._listeners),
        }

    def clear(self) -> int:
        count = len(self._trail)
        self._trail.clear()
        return count

    def _enforce_retention(self) -> None:
        if len(self._trail) < self._trail.maxlen * 0.9:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        while self._trail and self._trail[0].timestamp < cutoff:
            self._trail.popleft()
