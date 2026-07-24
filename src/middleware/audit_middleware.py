"""Audit middleware for tracking rule evaluations and operations."""

import csv
import io
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    RULE_EVALUATED = "rule_evaluated"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"
    RULE_ENABLED = "rule_enabled"
    RULE_DISABLED = "rule_disabled"
    REQUEST_PROCESSED = "request_processed"
    RESPONSE_SENT = "response_sent"
    AUTH_ATTEMPT = "auth_attempt"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    CONFIG_CHANGED = "config_changed"
    DATA_EXPORTED = "data_exported"
    DATA_IMPORTED = "data_imported"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    ERROR_OCCURRED = "error_occurred"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT_HIT = "rate_limit_hit"
    SESSION_CREATED = "session_created"
    SESSION_EXPIRED = "session_expired"
    CUSTOM = "custom"


class AuditSeverity(Enum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


@dataclass
class AuditRecord:
    id: str
    timestamp: str
    event_type: str
    actor_id: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str
    severity: str
    description: str
    changes: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    duration_ms: Optional[float] = None
    status_code: Optional[int] = None
    result: Optional[str] = None
    tags: Optional[List[str]] = None
    source: str = "rules-engine"


@dataclass
class AuditFilter:
    event_types: Optional[List[str]] = None
    actor_ids: Optional[List[str]] = None
    resource_types: Optional[List[str]] = None
    resource_ids: Optional[List[str]] = None
    severities: Optional[List[str]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    actions: Optional[List[str]] = None
    ip_addresses: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    sources: Optional[List[str]] = None
    min_duration_ms: Optional[float] = None
    max_duration_ms: Optional[float] = None
    status_codes: Optional[List[int]] = None
    results: Optional[List[str]] = None
    search_text: Optional[str] = None
    limit: Optional[int] = None
    offset: int = 0
    order_by: str = "timestamp"
    order_dir: str = "desc"


@dataclass
class AuditConfig:
    enabled: bool = True
    storage_backend: str = "memory"
    storage_path: str = "audit"
    max_records: int = 100000
    retention_days: int = 90
    archive_enabled: bool = True
    archive_path: str = "audit/archive"
    archive_interval_days: int = 30
    auto_cleanup: bool = True
    cleanup_interval: int = 3600
    track_all_events: bool = True
    tracked_event_types: List[str] = field(default_factory=lambda: [
        "rule_evaluated", "rule_created", "rule_updated", "rule_deleted",
        "auth_attempt", "auth_success", "auth_failure",
        "permission_denied", "error_occurred", "config_changed",
    ])
    tracked_resource_types: List[str] = field(default_factory=lambda: [
        "rule", "user", "config", "session", "request", "response",
    ])
    excluded_actors: List[str] = field(default_factory=lambda: [
        "system", "healthcheck",
    ])
    batch_size: int = 100
    async_writes: bool = False
    include_request_body: bool = False
    include_response_body: bool = False
    max_description_length: int = 4096
    mask_sensitive_data: bool = True
    sensitive_fields: List[str] = field(default_factory=lambda: [
        "password", "secret", "token", "authorization",
        "api_key", "access_key", "private_key",
    ])
    enable_export: bool = True
    export_max_records: int = 10000
    stats_window: int = 3600
    enable_audit_query: bool = True
    query_cache_size: int = 1000


@dataclass
class AuditStats:
    total_records: int = 0
    records_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    records_by_actor: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    records_by_severity: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    records_by_resource: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.time)
    errors_count: int = 0
    auth_failures: int = 0
    permission_denied: int = 0


class AuditStorage:
    def __init__(self, config: AuditConfig):
        self.config = config
        self._records: Dict[str, AuditRecord] = {}
        self._lock = Lock()
        self._indexes: Dict[str, Dict[str, List[str]]] = {
            "event_type": defaultdict(list),
            "actor_id": defaultdict(list),
            "resource_type": defaultdict(list),
            "severity": defaultdict(list),
            "timestamp": defaultdict(list),
        }
        logger.debug("AuditStorage initialized with backend=%s", config.storage_backend)

    def store(self, record: AuditRecord) -> bool:
        with self._lock:
            if len(self._records) >= self.config.max_records:
                self._evict_oldest()
            self._records[record.id] = record
            self._indexes["event_type"][record.event_type].append(record.id)
            self._indexes["actor_id"][record.actor_id].append(record.id)
            self._indexes["resource_type"][record.resource_type].append(record.id)
            self._indexes["severity"][record.severity].append(record.id)
            date_key = record.timestamp[:10]
            self._indexes["timestamp"][date_key].append(record.id)
            return True

    def store_batch(self, records: List[AuditRecord]) -> int:
        stored = 0
        for record in records:
            if self.store(record):
                stored += 1
        return stored

    def get(self, record_id: str) -> Optional[AuditRecord]:
        with self._lock:
            return self._records.get(record_id)

    def query(self, filter_obj: AuditFilter) -> List[AuditRecord]:
        with self._lock:
            results = list(self._records.values())
            if filter_obj.event_types:
                results = [r for r in results if r.event_type in filter_obj.event_types]
            if filter_obj.actor_ids:
                results = [r for r in results if r.actor_id in filter_obj.actor_ids]
            if filter_obj.resource_types:
                results = [r for r in results if r.resource_type in filter_obj.resource_types]
            if filter_obj.resource_ids:
                results = [r for r in results if r.resource_id in filter_obj.resource_ids]
            if filter_obj.severities:
                results = [r for r in results if r.severity in filter_obj.severities]
            if filter_obj.start_time:
                results = [r for r in results if r.timestamp >= filter_obj.start_time]
            if filter_obj.end_time:
                results = [r for r in results if r.timestamp <= filter_obj.end_time]
            if filter_obj.actions:
                results = [r for r in results if r.action in filter_obj.actions]
            if filter_obj.ip_addresses:
                results = [r for r in results if r.ip_address in filter_obj.ip_addresses]
            if filter_obj.tags:
                results = [
                    r for r in results
                    if r.tags and any(t in r.tags for t in filter_obj.tags)
                ]
            if filter_obj.sources:
                results = [r for r in results if r.source in filter_obj.sources]
            if filter_obj.min_duration_ms is not None:
                results = [
                    r for r in results
                    if r.duration_ms is not None and r.duration_ms >= filter_obj.min_duration_ms
                ]
            if filter_obj.max_duration_ms is not None:
                results = [
                    r for r in results
                    if r.duration_ms is not None and r.duration_ms <= filter_obj.max_duration_ms
                ]
            if filter_obj.status_codes:
                results = [
                    r for r in results
                    if r.status_code is not None and r.status_code in filter_obj.status_codes
                ]
            if filter_obj.results:
                results = [r for r in results if r.result in filter_obj.results]
            if filter_obj.search_text:
                text = filter_obj.search_text.lower()
                results = [
                    r for r in results
                    if text in r.description.lower()
                    or text in r.action.lower()
                    or text in r.resource_id.lower()
                ]
            if filter_obj.order_by == "timestamp":
                if filter_obj.order_dir == "asc":
                    results.sort(key=lambda r: r.timestamp)
                else:
                    results.sort(key=lambda r: r.timestamp, reverse=True)
            elif filter_obj.order_by == "severity":
                sev_order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "DEBUG": 4}
                if filter_obj.order_dir == "asc":
                    results.sort(key=lambda r: sev_order.get(r.severity, 5))
                else:
                    results.sort(key=lambda r: sev_order.get(r.severity, 5), reverse=True)
            if filter_obj.limit is not None:
                results = results[filter_obj.offset: filter_obj.offset + filter_obj.limit]
            else:
                results = results[filter_obj.offset:]
            return results

    def count(self, filter_obj: AuditFilter) -> int:
        return len(self.query(filter_obj))

    def delete_older_than(self, cutoff_timestamp: str) -> int:
        with self._lock:
            to_delete = [
                rid for rid, rec in self._records.items()
                if rec.timestamp < cutoff_timestamp
            ]
            for rid in to_delete:
                rec = self._records.pop(rid, None)
                if rec:
                    self._remove_from_indexes(rec)
            return len(to_delete)

    def get_by_date_range(self, start_date: str, end_date: str) -> List[AuditRecord]:
        with self._lock:
            return [
                r for r in self._records.values()
                if start_date <= r.timestamp[:10] <= end_date
            ]

    def get_by_actor(self, actor_id: str, limit: int = 100) -> List[AuditRecord]:
        with self._lock:
            record_ids = self._indexes["actor_id"].get(actor_id, [])
            records = [self._records[rid] for rid in record_ids if rid in self._records]
            records.sort(key=lambda r: r.timestamp, reverse=True)
            return records[:limit]

    def get_by_event_type(self, event_type: str, limit: int = 100) -> List[AuditRecord]:
        with self._lock:
            record_ids = self._indexes["event_type"].get(event_type, [])
            records = [self._records[rid] for rid in record_ids if rid in self._records]
            records.sort(key=lambda r: r.timestamp, reverse=True)
            return records[:limit]

    def get_by_resource(self, resource_type: str, resource_id: str, limit: int = 100) -> List[AuditRecord]:
        with self._lock:
            return [
                r for r in self._records.values()
                if r.resource_type == resource_type and r.resource_id == resource_id
            ][:limit]

    def count_by_event_type(self, since: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = defaultdict(int)
            for rec in self._records.values():
                if since is None or rec.timestamp >= since:
                    counts[rec.event_type] += 1
            return dict(counts)

    def count_by_actor(self, since: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = defaultdict(int)
            for rec in self._records.values():
                if since is None or rec.timestamp >= since:
                    counts[rec.actor_id] += 1
            return dict(counts)

    def count_by_severity(self, since: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = defaultdict(int)
            for rec in self._records.values():
                if since is None or rec.timestamp >= since:
                    counts[rec.severity] += 1
            return dict(counts)

    def count_by_resource(self, since: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = defaultdict(int)
            for rec in self._records.values():
                if since is None or rec.timestamp >= since:
                    counts[rec.resource_type] += 1
            return dict(counts)

    def total_count(self) -> int:
        with self._lock:
            return len(self._records)

    def get_all_records(self) -> List[AuditRecord]:
        with self._lock:
            return list(self._records.values())

    def get_recent(self, count: int = 100) -> List[AuditRecord]:
        with self._lock:
            sorted_records = sorted(
                self._records.values(),
                key=lambda r: r.timestamp,
                reverse=True,
            )
            return sorted_records[:count]

    def _evict_oldest(self) -> None:
        if not self._records:
            return
        oldest_id = min(self._records.keys(), key=lambda rid: self._records[rid].timestamp)
        oldest = self._records.pop(oldest_id, None)
        if oldest:
            self._remove_from_indexes(oldest)

    def _remove_from_indexes(self, record: AuditRecord) -> None:
        for index_name in self._indexes:
            index = self._indexes[index_name]
            key = getattr(record, index_name, None)
            if key and key in index:
                try:
                    index[key].remove(record.id)
                except ValueError:
                    pass

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records.clear()
            for index in self._indexes.values():
                index.clear()
            return count

    def size(self) -> int:
        with self._lock:
            return len(self._records)


class AuditArchiver:
    def __init__(self, config: AuditConfig):
        self.config = config
        self._last_archive: Optional[str] = None

    def archive_old_records(self, storage: AuditStorage, cutoff_timestamp: str) -> int:
        if not self.config.archive_enabled:
            return 0
        os.makedirs(self.config.archive_path, exist_ok=True)
        records = storage.get_by_date_range("0000-00-00", cutoff_timestamp[:10])
        if not records:
            return 0
        archive_file = os.path.join(
            self.config.archive_path,
            f"audit_{cutoff_timestamp[:10]}.json",
        )
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump([self._record_to_dict(r) for r in records], f, indent=2, default=str)
        self._last_archive = cutoff_timestamp
        logger.info("Archived %d audit records to %s", len(records), archive_file)
        return len(records)

    def restore_from_archive(self, archive_file: str, storage: AuditStorage) -> int:
        if not os.path.exists(archive_file):
            return 0
        with open(archive_file, "r", encoding="utf-8") as f:
            records_data = json.load(f)
        records = [self._dict_to_record(d) for d in records_data]
        stored = storage.store_batch(records)
        logger.info("Restored %d audit records from %s", stored, archive_file)
        return stored

    def list_archives(self) -> List[str]:
        if not os.path.exists(self.config.archive_path):
            return []
        return sorted([
            f for f in os.listdir(self.config.archive_path)
            if f.startswith("audit_") and f.endswith(".json")
        ])

    def _record_to_dict(self, record: AuditRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "timestamp": record.timestamp,
            "event_type": record.event_type,
            "actor_id": record.actor_id,
            "actor_name": record.actor_name,
            "action": record.action,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "severity": record.severity,
            "description": record.description,
            "changes": record.changes,
            "metadata": record.metadata,
            "ip_address": record.ip_address,
            "user_agent": record.user_agent,
            "session_id": record.session_id,
            "correlation_id": record.correlation_id,
            "request_id": record.request_id,
            "duration_ms": record.duration_ms,
            "status_code": record.status_code,
            "result": record.result,
            "tags": record.tags,
            "source": record.source,
        }

    def _dict_to_record(self, data: Dict[str, Any]) -> AuditRecord:
        return AuditRecord(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            event_type=data.get("event_type", "custom"),
            actor_id=data.get("actor_id", "unknown"),
            actor_name=data.get("actor_name", "unknown"),
            action=data.get("action", "unknown"),
            resource_type=data.get("resource_type", "unknown"),
            resource_id=data.get("resource_id", "unknown"),
            severity=data.get("severity", "INFO"),
            description=data.get("description", ""),
            changes=data.get("changes"),
            metadata=data.get("metadata"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            session_id=data.get("session_id"),
            correlation_id=data.get("correlation_id"),
            request_id=data.get("request_id"),
            duration_ms=data.get("duration_ms"),
            status_code=data.get("status_code"),
            result=data.get("result"),
            tags=data.get("tags"),
            source=data.get("source", "rules-engine"),
        )


class AuditExporter:
    def __init__(self, config: AuditConfig):
        self.config = config

    def export_json(self, records: List[AuditRecord], pretty: bool = True) -> str:
        data = [self._record_to_dict(r) for r in records]
        return json.dumps(data, indent=2 if pretty else None, default=str)

    def export_csv(self, records: List[AuditRecord]) -> str:
        output = io.StringIO()
        fieldnames = [
            "id", "timestamp", "event_type", "actor_id", "actor_name",
            "action", "resource_type", "resource_id", "severity",
            "description", "ip_address", "session_id", "correlation_id",
            "duration_ms", "status_code", "result", "source",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = self._record_to_dict(record)
            writer.writerow({k: row.get(k, "") for k in fieldnames})
        return output.getvalue()

    def export_to_file(self, records: List[AuditRecord], filepath: str, format: str = "json") -> bool:
        try:
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            if format == "json":
                content = self.export_json(records)
            elif format == "csv":
                content = self.export_csv(records)
            else:
                raise ValueError(f"Unsupported export format: {format}")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error("Audit export failed: %s", e)
            return False

    def _record_to_dict(self, record: AuditRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "timestamp": record.timestamp,
            "event_type": record.event_type,
            "actor_id": record.actor_id,
            "actor_name": record.actor_name,
            "action": record.action,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "severity": record.severity,
            "description": record.description,
            "changes": record.changes,
            "metadata": record.metadata,
            "ip_address": record.ip_address,
            "user_agent": record.user_agent,
            "session_id": record.session_id,
            "correlation_id": record.correlation_id,
            "request_id": record.request_id,
            "duration_ms": record.duration_ms,
            "status_code": record.status_code,
            "result": record.result,
            "tags": record.tags,
            "source": record.source,
        }


class AuditMiddleware:
    def __init__(self, config: Optional[AuditConfig] = None):
        self.config = config or AuditConfig()
        self.storage = AuditStorage(self.config)
        self.archiver = AuditArchiver(self.config)
        self.exporter = AuditExporter(self.config)
        self._stats = AuditStats()
        self._last_cleanup = time.time()
        self._batched_records: List[AuditRecord] = []
        self._lock = Lock()
        logger.info(
            "AuditMiddleware initialized with backend=%s, max_records=%d",
            self.config.storage_backend, self.config.max_records,
        )

    def record(
        self,
        event_type: Union[str, AuditEventType],
        actor_id: str,
        actor_name: str,
        action: str,
        resource_type: str,
        resource_id: str,
        severity: Union[str, AuditSeverity] = AuditSeverity.INFO,
        description: str = "",
        changes: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        status_code: Optional[int] = None,
        result: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = "rules-engine",
    ) -> str:
        if not self.config.enabled:
            return ""
        if isinstance(event_type, AuditEventType):
            event_type = event_type.value
        if isinstance(severity, AuditSeverity):
            severity = severity.name
        if actor_id in self.config.excluded_actors:
            return ""
        if not self._should_track(event_type, resource_type):
            return ""

        record_id = str(uuid.uuid4())
        if len(description) > self.config.max_description_length:
            description = description[: self.config.max_description_length] + "..."

        if self.config.mask_sensitive_data and metadata:
            metadata = self._mask_sensitive(metadata)
        if self.config.mask_sensitive_data and changes:
            changes = self._mask_sensitive(changes)

        record = AuditRecord(
            id=record_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=severity.upper() if isinstance(severity, str) else severity.name,
            description=description,
            changes=changes,
            metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            correlation_id=correlation_id,
            request_id=request_id,
            duration_ms=duration_ms,
            status_code=status_code,
            result=result,
            tags=tags,
            source=source,
        )

        if self.config.async_writes:
            with self._lock:
                self._batched_records.append(record)
                if len(self._batched_records) >= self.config.batch_size:
                    self._flush_batch()
        else:
            self.storage.store(record)

        self._update_stats(record)
        return record_id

    def record_rule_evaluation(
        self,
        rule_name: str,
        actor_id: str,
        result: str,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self.record(
            event_type=AuditEventType.RULE_EVALUATED,
            actor_id=actor_id,
            actor_name=actor_id,
            action="evaluate",
            resource_type="rule",
            resource_id=rule_name,
            severity=AuditSeverity.INFO,
            description=f"Rule '{rule_name}' evaluated with result: {result}",
            duration_ms=duration_ms,
            result=result,
            metadata=metadata,
            tags=["rule_evaluation"],
        )

    def record_auth_attempt(
        self,
        actor_id: str,
        success: bool,
        ip_address: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> str:
        event = AuditEventType.AUTH_SUCCESS if success else AuditEventType.AUTH_FAILURE
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING
        desc = f"Auth {'success' if success else 'failure'}"
        if failure_reason:
            desc += f": {failure_reason}"
        if not success:
            self._stats.auth_failures += 1
        return self.record(
            event_type=event,
            actor_id=actor_id,
            actor_name=actor_id,
            action="authenticate",
            resource_type="session",
            resource_id=actor_id,
            severity=severity,
            description=desc,
            ip_address=ip_address,
            result="success" if success else "failure",
            metadata={"failure_reason": failure_reason} if failure_reason else None,
            tags=["auth"],
        )

    def record_permission_denied(
        self,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        required_permission: str,
        ip_address: Optional[str] = None,
    ) -> str:
        self._stats.permission_denied += 1
        return self.record(
            event_type=AuditEventType.PERMISSION_DENIED,
            actor_id=actor_id,
            actor_name=actor_id,
            action="access",
            resource_type=resource_type,
            resource_id=resource_id,
            severity=AuditSeverity.WARNING,
            description=f"Permission denied: {actor_id} attempted {required_permission} on {resource_type}:{resource_id}",
            ip_address=ip_address,
            metadata={"required_permission": required_permission},
            result="denied",
            tags=["authorization", "denied"],
        )

    def record_error(
        self,
        actor_id: str,
        error_type: str,
        error_message: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._stats.errors_count += 1
        return self.record(
            event_type=AuditEventType.ERROR_OCCURRED,
            actor_id=actor_id,
            actor_name=actor_id,
            action="error",
            resource_type=resource_type or "system",
            resource_id=resource_id or "unknown",
            severity=AuditSeverity.ERROR,
            description=f"Error [{error_type}]: {error_message}",
            metadata=metadata,
            result="error",
            tags=["error", error_type],
        )

    def record_config_change(
        self,
        actor_id: str,
        config_section: str,
        changes: Dict[str, Any],
        description: str = "",
    ) -> str:
        return self.record(
            event_type=AuditEventType.CONFIG_CHANGED,
            actor_id=actor_id,
            actor_name=actor_id,
            action="update",
            resource_type="config",
            resource_id=config_section,
            severity=AuditSeverity.INFO,
            description=description or f"Configuration changed in {config_section}",
            changes=changes,
            tags=["config"],
        )

    def record_request(
        self,
        request: Dict[str, Any],
        actor_id: str = "system",
        actor_name: str = "system",
    ) -> str:
        metadata = None
        if self.config.include_request_body and "body" in request:
            metadata = {"body": request["body"]}
        route = request.get("route", "unknown")
        method = request.get("method", "GET")
        return self.record(
            event_type=AuditEventType.REQUEST_PROCESSED,
            actor_id=actor_id,
            actor_name=actor_name,
            action=method.lower(),
            resource_type="request",
            resource_id=route,
            severity=AuditSeverity.INFO,
            description=f"{method} {route}",
            ip_address=request.get("headers", {}).get("X-Forwarded-For"),
            user_agent=request.get("headers", {}).get("User-Agent"),
            metadata=metadata,
            tags=["request", method.lower()],
        )

    def query(
        self,
        event_types: Optional[List[str]] = None,
        actor_ids: Optional[List[str]] = None,
        resource_types: Optional[List[str]] = None,
        resource_ids: Optional[List[str]] = None,
        severities: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        actions: Optional[List[str]] = None,
        ip_addresses: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        search_text: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: str = "timestamp",
        order_dir: str = "desc",
    ) -> List[AuditRecord]:
        if not self.config.enable_audit_query:
            return []
        audit_filter = AuditFilter(
            event_types=event_types,
            actor_ids=actor_ids,
            resource_types=resource_types,
            resource_ids=resource_ids,
            severities=severities,
            start_time=start_time,
            end_time=end_time,
            actions=actions,
            ip_addresses=ip_addresses,
            tags=tags,
            search_text=search_text,
            limit=limit,
            offset=offset,
            order_by=order_by,
            order_dir=order_dir,
        )
        return self.storage.query(audit_filter)

    def query_by_user(self, actor_id: str, limit: int = 100) -> List[AuditRecord]:
        return self.storage.get_by_actor(actor_id, limit)

    def query_by_time_range(self, start: str, end: str) -> List[AuditRecord]:
        return self.storage.get_by_date_range(start, end)

    def query_by_event_type(self, event_type: str, limit: int = 100) -> List[AuditRecord]:
        return self.storage.get_by_event_type(event_type, limit)

    def query_by_resource(self, resource_type: str, resource_id: str, limit: int = 100) -> List[AuditRecord]:
        return self.storage.get_by_resource(resource_type, resource_id, limit)

    def get_record(self, record_id: str) -> Optional[AuditRecord]:
        return self.storage.get(record_id)

    def get_recent(self, count: int = 100) -> List[AuditRecord]:
        return self.storage.get_recent(count)

    def export_json(self, filter_obj: Optional[AuditFilter] = None) -> str:
        if filter_obj:
            records = self.storage.query(filter_obj)[: self.config.export_max_records]
        else:
            records = self.storage.get_all_records()[: self.config.export_max_records]
        return self.exporter.export_json(records)

    def export_csv(self, filter_obj: Optional[AuditFilter] = None) -> str:
        if filter_obj:
            records = self.storage.query(filter_obj)[: self.config.export_max_records]
        else:
            records = self.storage.get_all_records()[: self.config.export_max_records]
        return self.exporter.export_csv(records)

    def export_to_file(
        self,
        filepath: str,
        format: str = "json",
        filter_obj: Optional[AuditFilter] = None,
    ) -> bool:
        if filter_obj:
            records = self.storage.query(filter_obj)[: self.config.export_max_records]
        else:
            records = self.storage.get_all_records()[: self.config.export_max_records]
        return self.exporter.export_to_file(records, filepath, format)

    def archive_old_records(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)).isoformat()
        return self.archiver.archive_old_records(self.storage, cutoff)

    def restore_from_archive(self, archive_file: str) -> int:
        return self.archiver.restore_from_archive(archive_file, self.storage)

    def list_archives(self) -> List[str]:
        return self.archiver.list_archives()

    def cleanup(self) -> int:
        if not self.config.auto_cleanup:
            return 0
        now = time.time()
        if now - self._last_cleanup < self.config.cleanup_interval:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)).isoformat()
        count = self.storage.delete_older_than(cutoff)
        self._last_cleanup = now
        if count > 0:
            logger.info("Cleaned up %d audit records older than %s", count, cutoff)
        self._flush_batch()
        return count

    def get_stats(self) -> Dict[str, Any]:
        self.cleanup()
        since = (datetime.now(timezone.utc) - timedelta(seconds=self.config.stats_window)).isoformat()
        return {
            "total_records": self.storage.total_count(),
            "by_event_type": self.storage.count_by_event_type(since),
            "by_actor": self.storage.count_by_actor(since),
            "by_severity": self.storage.count_by_severity(since),
            "by_resource": self.storage.count_by_resource(since),
            "errors": self._stats.errors_count,
            "auth_failures": self._stats.auth_failures,
            "permission_denied": self._stats.permission_denied,
            "batched_records": len(self._batched_records),
            "archives_available": len(self.list_archives()),
            "enabled": self.config.enabled,
            "storage_backend": self.config.storage_backend,
            "retention_days": self.config.retention_days,
            "max_records": self.config.max_records,
            "uptime_seconds": round(time.time() - self._stats.start_time, 2),
        }

    def count_records(self, filter_obj: Optional[AuditFilter] = None) -> int:
        if filter_obj:
            return self.storage.count(filter_obj)
        return self.storage.total_count()

    def get_record_count_by_type(self) -> Dict[str, int]:
        return dict(self.storage.count_by_event_type())

    def get_record_count_by_actor(self) -> Dict[str, int]:
        return dict(self.storage.count_by_actor())

    def get_record_count_by_severity(self) -> Dict[str, int]:
        return dict(self.storage.count_by_severity())

    def get_record_count_by_resource(self) -> Dict[str, int]:
        return dict(self.storage.count_by_resource())

    def clear_records(self) -> int:
        count = self.storage.clear()
        logger.info("Cleared %d audit records", count)
        return count

    def flush(self) -> int:
        return self._flush_batch()

    def _flush_batch(self) -> int:
        with self._lock:
            if not self._batched_records:
                return 0
            records = self._batched_records[:]
            self._batched_records.clear()
        self.storage.store_batch(records)
        return len(records)

    def _should_track(self, event_type: str, resource_type: str) -> bool:
        if self.config.track_all_events:
            return True
        return (
            event_type in self.config.tracked_event_types
            and resource_type in self.config.tracked_resource_types
        )

    def _mask_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(data)
        for key in list(result.keys()):
            key_lower = key.lower()
            if any(s in key_lower for s in self.config.sensitive_fields):
                result[key] = "***"
            elif isinstance(result[key], dict):
                result[key] = self._mask_sensitive(result[key])
        return result

    def _update_stats(self, record: AuditRecord) -> None:
        self._stats.total_records += 1
        self._stats.records_by_type[record.event_type] += 1
        self._stats.records_by_actor[record.actor_id] += 1
        self._stats.records_by_severity[record.severity] += 1
        self._stats.records_by_resource[record.resource_type] += 1

    def add_tracked_event_type(self, event_type: str) -> None:
        if event_type not in self.config.tracked_event_types:
            self.config.tracked_event_types.append(event_type)

    def remove_tracked_event_type(self, event_type: str) -> bool:
        if event_type in self.config.tracked_event_types:
            self.config.tracked_event_types.remove(event_type)
            return True
        return False

    def add_tracked_resource_type(self, resource_type: str) -> None:
        if resource_type not in self.config.tracked_resource_types:
            self.config.tracked_resource_types.append(resource_type)

    def remove_tracked_resource_type(self, resource_type: str) -> bool:
        if resource_type in self.config.tracked_resource_types:
            self.config.tracked_resource_types.remove(resource_type)
            return True
        return False

    def add_excluded_actor(self, actor_id: str) -> None:
        if actor_id not in self.config.excluded_actors:
            self.config.excluded_actors.append(actor_id)

    def remove_excluded_actor(self, actor_id: str) -> bool:
        if actor_id in self.config.excluded_actors:
            self.config.excluded_actors.remove(actor_id)
            return True
        return False

    def update_config(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("AuditConfig.%s updated to %s", key, value)

    def reset_config(self) -> None:
        self.config = AuditConfig()
        self.storage = AuditStorage(self.config)
        self.archiver = AuditArchiver(self.config)
        self.exporter = AuditExporter(self.config)
        self._stats = AuditStats()

    def __repr__(self) -> str:
        return (
            f"AuditMiddleware(records={self.storage.total_count()}, "
            f"enabled={self.config.enabled}, "
            f"backend={self.config.storage_backend})"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.flush()
