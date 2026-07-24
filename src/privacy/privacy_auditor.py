"""Privacy auditor module for compliance event tracking and reporting.

Provides the PrivacyAuditor class for logging, querying, and exporting
privacy-related events such as data access, modification, sharing, and
consent changes.  Includes Data Subject Access Request (DSAR) workflow
helpers, GDPR/CCPA compliance reporting, config-driven audit policies,
and full event trail export in JSON / CSV formats.
"""
import csv
import hashlib
import io
import json
import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Categories of privacy events that can be logged."""
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    DATA_CREATION = "data_creation"
    DATA_DELETION = "data_deletion"
    DATA_SHARING = "data_sharing"
    DATA_EXPORT = "data_export"
    CONSENT_GRANTED = "consent_granted"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    CONSENT_EXPIRED = "consent_expired"
    DSAR_REQUEST = "dsar_request"
    DSAR_FULFILLMENT = "dsar_fulfillment"
    BREACH_DETECTED = "breach_detected"
    BREACH_NOTIFIED = "breach_notified"
    POLICY_ACCEPTED = "policy_accepted"
    POLICY_DECLINED = "policy_declined"
    DATA_RETENTION_DELETED = "data_retention_deleted"
    ANONYMIZATION_APPLIED = "anonymization_applied"
    CLASSIFICATION_APPLIED = "classification_applied"
    REDACTION_APPLIED = "redaction_applied"
    THIRD_PARTY_DISCLOSURE = "third_party_disclosure"
    CROSS_BORDER_TRANSFER = "cross_border_transfer"
    USER_ACCOUNT_DELETION = "user_account_deletion"
    USER_DATA_PORTABILITY = "user_data_portability"
    SYSTEM_CONFIG_CHANGE = "system_config_change"


@dataclass
class PrivacyEvent:
    """A single privacy event entry in the audit log.

    Attributes:
        event_id: Unique identifier for the event.
        event_type: EventType value categorizing the action.
        user_id: Identifier of the data subject (if applicable).
        actor_id: Identifier of the person/system who performed the action.
        timestamp: ISO-8601 timestamp of the event.
        resource: The resource or data object involved.
        details: Free-form details about the event.
        ip_address: IP address of the actor.
        user_agent: User-agent string.
        severity: 'info', 'warning', 'error', 'critical'.
        category: Optional secondary classification (e.g. 'gdpr', 'ccpa').
        tags: Set of tags for filtering.
        metadata: Free-form extras.
    """
    event_id: str
    event_type: str
    user_id: str
    actor_id: str
    timestamp: str
    resource: str = ""
    details: str = ""
    ip_address: str = ""
    user_agent: str = ""
    severity: str = "info"
    category: str = ""
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DSARRequest:
    """Data Subject Access Request record.

    Attributes:
        dsar_id: Unique identifier.
        user_id: The data subject requesting their data.
        request_type: 'access', 'rectification', 'erasure', 'portability', 'restrict'.
        status: 'open', 'in_progress', 'fulfilled', 'denied', 'expired'.
        submitted_at: ISO-8601 submission timestamp.
        fulfilled_at: ISO-8601 fulfillment timestamp.
        requested_data_types: List of data types being requested.
        fulfillment_format: 'json', 'csv', 'pdf', 'html'.
        notes: Internal notes about the request.
        verified: Whether the data subject's identity was verified.
        regulatory_deadline: ISO-8601 deadline for response.
    """
    dsar_id: str
    user_id: str
    request_type: str
    status: str
    submitted_at: str
    fulfilled_at: str = ""
    requested_data_types: List[str] = field(default_factory=list)
    fulfillment_format: str = "json"
    notes: str = ""
    verified: bool = False
    regulatory_deadline: str = ""


@dataclass
class ComplianceReport:
    """Structured compliance report.

    Attributes:
        report_type: 'gdpr' or 'ccpa'.
        period_start: Start of the reporting period.
        period_end: End of the reporting period.
        total_events: Total privacy events in the period.
        events_by_type: Count per EventType.
        events_by_user: Count per user_id.
        dsar_summary: DSAR-related counts.
        breach_summary: Breach-related counts.
        generated_at: When the report was generated.
    """
    report_type: str
    period_start: str
    period_end: str
    total_events: int
    events_by_type: Dict[str, int]
    events_by_user: Dict[str, int]
    dsar_summary: Dict[str, Any]
    breach_summary: Dict[str, Any]
    generated_at: str


def _generate_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:16]}"


def _generate_dsar_id() -> str:
    return f"dsar-{uuid.uuid4().hex[:12]}"


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_days_utc(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class PrivacyAuditor:
    """Central audit trail for privacy-related events.

    Features:
    - Log privacy events (access, modification, sharing, consent, DSAR, etc.)
    - Query events with flexible filters (type, user, time range, severity)
    - Export events as JSON or CSV
    - Data Subject Access Request (DSAR) lifecycle management
    - GDPR / CCPA compliance reporting
    - Config-driven audit policies and retention rules
    - Real-time event streaming via iterator
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        retention_days: int = 365,
        auto_purge: bool = False,
    ) -> None:
        """Initialise the privacy auditor.

        Args:
            config_path: Optional YAML/JSON config file for audit policies.
            retention_days: Number of days to retain events before auto-purge.
            auto_purge: If True, purge expired events on every log write.
        """
        self._events: List[PrivacyEvent] = []
        self._dsar_requests: List[DSARRequest] = []
        self._index_by_type: Dict[str, List[int]] = defaultdict(list)
        self._index_by_user: Dict[str, List[int]] = defaultdict(list)
        self._index_by_severity: Dict[str, List[int]] = defaultdict(list)
        self._retention_days = retention_days
        self._auto_purge = auto_purge
        self._config_path = Path(config_path).resolve() if config_path else None

        if self._config_path and self._config_path.exists():
            self.load_config(self._config_path)

        logger.info(
            "PrivacyAuditor initialized (retention=%dd, auto_purge=%s)",
            retention_days, auto_purge,
        )

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: Union[str, EventType],
        user_id: str,
        details: str = "",
        actor_id: Optional[str] = None,
        resource: str = "",
        ip_address: str = "",
        user_agent: str = "",
        severity: str = "info",
        category: str = "",
        tags: Optional[Set[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> PrivacyEvent:
        """Log a single privacy event.

        Args:
            event_type: EventType or string representation.
            user_id: Data subject identifier.
            details: Human-readable description.
            actor_id: Who performed the action (defaults to user_id).
            resource: The resource or object acted upon.
            ip_address: Actor's IP address.
            user_agent: Actor's user-agent string.
            severity: 'info', 'warning', 'error', 'critical'.
            category: Optional compliance category.
            tags: Optional set of tags for filtering.
            metadata: Optional free-form extras.
            timestamp: Override the event timestamp (ISO-8601).

        Returns:
            The newly created PrivacyEvent.
        """
        etype = event_type.value if isinstance(event_type, EventType) else event_type
        event = PrivacyEvent(
            event_id=_generate_event_id(),
            event_type=etype,
            user_id=user_id,
            actor_id=actor_id or user_id,
            timestamp=timestamp or _utc_now_str(),
            resource=resource,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            severity=severity,
            category=category,
            tags=tags or set(),
            metadata=metadata or {},
        )

        idx = len(self._events)
        self._events.append(event)
        self._index_by_type[etype].append(idx)
        self._index_by_user[user_id].append(idx)
        self._index_by_severity[severity].append(idx)

        logger.debug("Logged event: type=%s user=%s severity=%s", etype, user_id, severity)

        if self._auto_purge:
            self.purge_expired_events()

        return event

    def log_data_access(
        self,
        user_id: str,
        resource: str,
        actor_id: Optional[str] = None,
        ip_address: str = "",
        details: str = "",
    ) -> PrivacyEvent:
        """Convenience: log a data access event."""
        return self.log_event(
            event_type=EventType.DATA_ACCESS,
            user_id=user_id,
            actor_id=actor_id,
            resource=resource,
            details=details or f"Data accessed: {resource}",
            ip_address=ip_address,
        )

    def log_data_modification(
        self,
        user_id: str,
        resource: str,
        details: str = "",
        actor_id: Optional[str] = None,
    ) -> PrivacyEvent:
        """Convenience: log a data modification event."""
        return self.log_event(
            event_type=EventType.DATA_MODIFICATION,
            user_id=user_id,
            actor_id=actor_id,
            resource=resource,
            details=details or f"Data modified: {resource}",
            severity="warning",
        )

    def log_data_sharing(
        self,
        user_id: str,
        resource: str,
        third_party: str,
        details: str = "",
    ) -> PrivacyEvent:
        """Convenience: log a data sharing event with a third party."""
        return self.log_event(
            event_type=EventType.DATA_SHARING,
            user_id=user_id,
            resource=resource,
            details=details or f"Data shared with {third_party}: {resource}",
            severity="warning",
            category="third_party",
            tags={"sharing", "third_party"},
            metadata={"third_party": third_party},
        )

    def log_breach(
        self,
        user_id: str,
        details: str,
        severity: str = "critical",
        affected_users: Optional[List[str]] = None,
    ) -> PrivacyEvent:
        """Log a data breach detection event."""
        metadata = {"affected_users": affected_users or []} if affected_users else {}
        return self.log_event(
            event_type=EventType.BREACH_DETECTED,
            user_id=user_id,
            details=details,
            severity=severity,
            category="breach",
            tags={"breach", "security"},
            metadata=metadata,
        )

    def log_consent_change(
        self,
        user_id: str,
        category: str,
        granted: bool,
        source: str = "",
    ) -> PrivacyEvent:
        """Log a consent grant or withdrawal."""
        etype = EventType.CONSENT_GRANTED if granted else EventType.CONSENT_WITHDRAWN
        return self.log_event(
            event_type=etype,
            user_id=user_id,
            details=f"Consent { 'granted' if granted else 'withdrawn' } for {category} (source={source})",
            category="consent",
            tags={"consent", category},
            metadata={"consent_category": category, "granted": granted, "source": source},
        )

    # ------------------------------------------------------------------
    # Event querying
    # ------------------------------------------------------------------

    def query_events(
        self,
        event_type: Optional[Union[str, EventType]] = None,
        user_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "timestamp",
        order_dir: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Query privacy events with flexible filters.

        Args:
            event_type: Filter by EventType.
            user_id: Filter by data subject.
            start_time: ISO-8601; only events at or after this time.
            end_time: ISO-8601; only events at or before this time.
            severity: Filter by severity level.
            category: Filter by category string.
            tag: Filter by tag (events containing this tag).
            limit: Maximum number of events to return.
            offset: Pagination offset.
            order_by: Sort field ('timestamp', 'event_type', 'severity').
            order_dir: 'asc' or 'desc'.

        Returns:
            List of matching event dicts.
        """
        candidates: List[int] = []

        if event_type:
            etype = event_type.value if isinstance(event_type, EventType) else event_type
            candidates = self._index_by_type.get(etype, [])
            if not candidates:
                return []
        elif user_id:
            candidates = self._index_by_user.get(user_id, [])
        elif severity:
            candidates = self._index_by_severity.get(severity, [])
        else:
            candidates = list(range(len(self._events)))

        results: List[PrivacyEvent] = []
        for idx in candidates:
            event = self._events[idx]

            if user_id and event.user_id != user_id:
                continue
            if severity and event.severity != severity:
                continue
            if category and event.category != category:
                continue
            if tag and tag not in event.tags:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue

            results.append(event)

        # Sort
        reverse = order_dir.lower() == "desc"
        if order_by == "event_type":
            results.sort(key=lambda e: e.event_type, reverse=reverse)
        elif order_by == "severity":
            sev_rank = {"info": 0, "warning": 1, "error": 2, "critical": 3}
            results.sort(key=lambda e: sev_rank.get(e.severity, 0), reverse=reverse)
        else:
            results.sort(key=lambda e: e.timestamp, reverse=reverse)

        # Paginate
        sliced = results[offset:offset + limit]
        return [asdict(e) for e in sliced]

    def get_events_count(
        self,
        event_type: Optional[Union[str, EventType]] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Quick count of events matching filters (no pagination)."""
        return len(self.query_events(
            event_type=event_type,
            user_id=user_id,
            limit=10 ** 9,
        ))

    def get_user_events(
        self,
        user_id: str,
        event_type: Optional[Union[str, EventType]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return events for a specific user."""
        return self.query_events(user_id=user_id, event_type=event_type, limit=limit)

    def get_recent_events(self, minutes: int = 60, limit: int = 50) -> List[Dict[str, Any]]:
        """Return events from the last N minutes."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return self.query_events(start_time=cutoff, limit=limit)

    # ------------------------------------------------------------------
    # Event export
    # ------------------------------------------------------------------

    def export_events(
        self,
        fmt: str = "json",
        path: Optional[Union[str, Path]] = None,
        event_type: Optional[Union[str, EventType]] = None,
        user_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> str:
        """Export filtered events as JSON or CSV.

        Args:
            fmt: 'json' or 'csv'.
            path: Optional file path to write to.  If not provided,
                  the string is returned.
            event_type: Optional filter.
            user_id: Optional filter.
            start_time: Optional filter.
            end_time: Optional filter.

        Returns:
            The exported string (empty string if *path* was used).
        """
        events = self.query_events(
            event_type=event_type,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=10 ** 9,
        )

        output: str

        if fmt == "csv":
            output = self._events_to_csv(events)
        else:
            output = json.dumps({"events": events, "exported_at": _utc_now_str()},
                                indent=2, default=str)

        if path:
            Path(path).resolve().write_text(output, encoding="utf-8")
            logger.info("Exported %d events to %s", len(events), path)
            return ""

        return output

    def export_user_events(
        self,
        user_id: str,
        fmt: str = "json",
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Export all events for a single user (useful for DSAR fulfillment)."""
        return self.export_events(fmt=fmt, path=path, user_id=user_id)

    # ------------------------------------------------------------------
    # DSAR management
    # ------------------------------------------------------------------

    def create_dsar(
        self,
        user_id: str,
        request_type: str = "access",
        requested_data_types: Optional[List[str]] = None,
        fulfillment_format: str = "json",
        notes: str = "",
        verified: bool = False,
    ) -> DSARRequest:
        """Create a new Data Subject Access Request.

        Args:
            user_id: The requesting data subject.
            request_type: 'access', 'rectification', 'erasure', 'portability', 'restrict'.
            requested_data_types: List of data categories requested.
            fulfillment_format: Preferred output format.
            notes: Internal notes.
            verified: Whether the subject's identity has been verified.

        Returns:
            The created DSARRequest.
        """
        dsar = DSARRequest(
            dsar_id=_generate_dsar_id(),
            user_id=user_id,
            request_type=request_type,
            status="open",
            submitted_at=_utc_now_str(),
            requested_data_types=requested_data_types or ["all"],
            fulfillment_format=fulfillment_format,
            notes=notes,
            verified=verified,
            regulatory_deadline=_add_days_utc(30),
        )
        self._dsar_requests.append(dsar)

        self.log_event(
            event_type=EventType.DSAR_REQUEST,
            user_id=user_id,
            details=f"DSAR created: type={request_type}, id={dsar.dsar_id}",
            category="dsar",
            metadata={"dsar_id": dsar.dsar_id, "request_type": request_type},
        )

        logger.info("DSAR %s created for user=%s type=%s", dsar.dsar_id, user_id, request_type)
        return dsar

    def fulfill_dsar(self, dsar_id: str, notes: str = "") -> Optional[DSARRequest]:
        """Mark a DSAR as fulfilled."""
        for dsar in self._dsar_requests:
            if dsar.dsar_id == dsar_id:
                dsar.status = "fulfilled"
                dsar.fulfilled_at = _utc_now_str()
                if notes:
                    dsar.notes = notes

                self.log_event(
                    event_type=EventType.DSAR_FULFILLMENT,
                    user_id=dsar.user_id,
                    details=f"DSAR fulfilled: {dsar_id}",
                    category="dsar",
                    metadata={"dsar_id": dsar_id, "request_type": dsar.request_type},
                )

                logger.info("DSAR %s fulfilled", dsar_id)
                return dsar
        logger.warning("DSAR %s not found", dsar_id)
        return None

    def deny_dsar(self, dsar_id: str, reason: str = "") -> Optional[DSARRequest]:
        """Deny a DSAR with a reason."""
        for dsar in self._dsar_requests:
            if dsar.dsar_id == dsar_id:
                dsar.status = "denied"
                dsar.notes = (dsar.notes + f" | Denied: {reason}").strip(" |")
                logger.info("DSAR %s denied: %s", dsar_id, reason)
                return dsar
        return None

    def get_dsar(self, dsar_id: str) -> Optional[Dict[str, Any]]:
        for dsar in self._dsar_requests:
            if dsar.dsar_id == dsar_id:
                return asdict(dsar)
        return None

    def get_dsars_for_user(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = [asdict(d) for d in self._dsar_requests if d.user_id == user_id]
        if status:
            results = [r for r in results if r["status"] == status]
        return results

    def get_open_dsars(self) -> List[Dict[str, Any]]:
        return [asdict(d) for d in self._dsar_requests if d.status == "open"]

    def get_overdue_dsars(self) -> List[Dict[str, Any]]:
        now = _utc_now_str()
        overdue = []
        for d in self._dsar_requests:
            if d.status in ("open", "in_progress") and d.regulatory_deadline < now:
                overdue.append(asdict(d))
        return overdue

    def dsar_fulfillment_package(
        self,
        user_id: str,
        include_events: bool = True,
        include_consent: bool = True,
    ) -> Dict[str, Any]:
        """Assemble a data package for DSAR fulfillment.

        Returns structured data containing:
        - user_id
        - user_events (if requested)
        - consent_info (if consent_manager is provided)
        - generated_at
        """
        package: Dict[str, Any] = {
            "user_id": user_id,
            "generated_at": _utc_now_str(),
            "package_id": f"dsar-pkg-{uuid.uuid4().hex[:12]}",
        }

        if include_events:
            package["events"] = self.get_user_events(user_id, limit=10 ** 9)

        if include_consent:
            package["consent_events"] = self.query_events(
                user_id=user_id,
                event_type=EventType.CONSENT_GRANTED,
                limit=10 ** 9,
            )

        return package

    # ------------------------------------------------------------------
    # Compliance reporting
    # ------------------------------------------------------------------

    def compliance_report(
        self,
        report_type: str = "gdpr",
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> ComplianceReport:
        """Generate a GDPR or CCPA compliance report for a time period.

        Args:
            report_type: 'gdpr' or 'ccpa'.
            period_start: ISO-8601 start (defaults to 90 days ago).
            period_end: ISO-8601 end (defaults to now).

        Returns:
            A ComplianceReport dataclass.
        """
        p_start = period_start or (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        p_end = period_end or _utc_now_str()

        events = self.query_events(
            start_time=p_start,
            end_time=p_end,
            limit=10 ** 9,
        )

        events_by_type: Counter[str] = Counter()
        events_by_user: Counter[str] = Counter()

        for evt in events:
            events_by_type[evt["event_type"]] += 1
            events_by_user[evt["user_id"]] += 1

        dsar_list = [
            asdict(d) for d in self._dsar_requests
            if p_start <= d.submitted_at <= p_end
        ]
        dsar_summary = {
            "total": len(dsar_list),
            "open": sum(1 for d in dsar_list if d["status"] == "open"),
            "fulfilled": sum(1 for d in dsar_list if d["status"] == "fulfilled"),
            "denied": sum(1 for d in dsar_list if d["status"] == "denied"),
            "overdue": len(self.get_overdue_dsars()),
        }

        breach_events = [e for e in events if e["event_type"] == EventType.BREACH_DETECTED.value]
        breach_summary = {
            "total_breaches": len(breach_events),
            "critical_breaches": sum(1 for e in breach_events if e["severity"] == "critical"),
            "breach_events": breach_events[:10],
        }

        return ComplianceReport(
            report_type=report_type.upper(),
            period_start=p_start,
            period_end=p_end,
            total_events=len(events),
            events_by_type=dict(events_by_type),
            events_by_user=dict(events_by_user),
            dsar_summary=dsar_summary,
            breach_summary=breach_summary,
            generated_at=_utc_now_str(),
        )

    # ------------------------------------------------------------------
    # Event retention & purge
    # ------------------------------------------------------------------

    def purge_expired_events(self) -> int:
        """Remove events older than the retention period.

        Returns:
            Number of events purged.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
        before = len(self._events)
        self._events = [e for e in self._events if e.timestamp >= cutoff]
        purged = before - len(self._events)

        if purged:
            # Rebuild indices
            self._rebuild_indices()
            logger.info("Purged %d events older than %s", purged, cutoff)

        return purged

    def set_retention_days(self, days: int) -> None:
        """Change the retention period."""
        self._retention_days = max(1, days)
        logger.info("Retention period set to %d days", self._retention_days)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return high-level statistics about the audit log."""
        self.purge_expired_events()

        type_counts: Dict[str, int] = {
            etype: len(indices) for etype, indices in self._index_by_type.items()
        }
        severity_counts: Dict[str, int] = {
            sev: len(indices) for sev, indices in self._index_by_severity.items()
        }

        return {
            "total_events": len(self._events),
            "total_dsars": len(self._dsar_requests),
            "events_by_type": type_counts,
            "events_by_severity": severity_counts,
            "unique_users": len(self._index_by_user),
            "retention_days": self._retention_days,
            "open_dsars": len(self.get_open_dsars()),
            "overdue_dsars": len(self.get_overdue_dsars()),
            "generated_at": _utc_now_str(),
        }

    # ------------------------------------------------------------------
    # Config-driven policies
    # ------------------------------------------------------------------

    def load_config(self, path: Union[str, Path]) -> int:
        """Load audit policies from YAML or JSON.

        Expected YAML format:
        ```yaml
        audit_policy:
          retention_days: 365
          auto_purge: false
          monitored_event_types:
            - data_access
            - data_modification
            - data_sharing
          severity_levels:
            - info
            - warning
            - error
            - critical
          notify_on:
            - critical
            - breach_detected
        ```
        Returns the number of config keys loaded (0 if file is empty).
        """
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            logger.error("Config not found: %s", path_obj)
            return 0

        raw = path_obj.read_text(encoding="utf-8")
        suffix = path_obj.suffix.lower()

        try:
            if suffix in (".yaml", ".yml"):
                data = yaml.safe_load(raw)
            elif suffix == ".json":
                data = json.loads(raw)
            else:
                raise ValueError(f"Unsupported format: {suffix}")
        except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse config: %s", exc)
            return 0

        if not isinstance(data, dict):
            return 0

        policy = data.get("audit_policy", data)
        count = 0

        if "retention_days" in policy:
            self._retention_days = int(policy["retention_days"])
            count += 1
        if "auto_purge" in policy:
            self._auto_purge = bool(policy["auto_purge"])
            count += 1

        logger.info("Loaded audit config from %s (%d keys)", path_obj, count)
        return count

    # ------------------------------------------------------------------
    # Iterator / streaming
    # ------------------------------------------------------------------

    def stream_events(
        self,
        event_type: Optional[Union[str, EventType]] = None,
        user_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield events one at a time (memory-friendly for large logs)."""
        idx = 0
        while idx < len(self._events):
            event = self._events[idx]
            idx += 1

            if event_type:
                etype = event_type.value if isinstance(event_type, EventType) else event_type
                if event.event_type != etype:
                    continue
            if user_id and event.user_id != user_id:
                continue

            yield asdict(event)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_indices(self) -> None:
        """Rebuild all indices from scratch."""
        self._index_by_type.clear()
        self._index_by_user.clear()
        self._index_by_severity.clear()

        for idx, event in enumerate(self._events):
            self._index_by_type[event.event_type].append(idx)
            self._index_by_user[event.user_id].append(idx)
            self._index_by_severity[event.severity].append(idx)

    def _events_to_csv(self, events: List[Dict[str, Any]]) -> str:
        """Convert a list of event dicts to CSV format."""
        output = io.StringIO()
        if not events:
            return ""

        fieldnames = [
            "event_id", "event_type", "user_id", "actor_id", "timestamp",
            "resource", "details", "ip_address", "user_agent",
            "severity", "category", "tags", "metadata",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for evt in events:
            row = dict(evt)
            if isinstance(row.get("tags"), set):
                row["tags"] = "|".join(sorted(row["tags"]))
            if isinstance(row.get("metadata"), dict):
                row["metadata"] = json.dumps(row["metadata"], default=str)
            writer.writerow(row)

        return output.getvalue()

    # ------------------------------------------------------------------
    # Clear / reset
    # ------------------------------------------------------------------

    def clear_events(self) -> int:
        """Remove all events and DSARs.

        Returns the number of events removed.
        """
        n = len(self._events)
        self._events.clear()
        self._dsar_requests.clear()
        self._index_by_type.clear()
        self._index_by_user.clear()
        self._index_by_severity.clear()
        logger.warning("All privacy events cleared (%d removed)", n)
        return n

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return self.stream_events()

    def __repr__(self) -> str:
        return (
            f"PrivacyAuditor(events={len(self._events)}, "
            f"dsars={len(self._dsar_requests)}, "
            f"retention={self._retention_days}d)"
        )
