"""Persistent recording of conflict events with query, filter, and batch operations."""
import logging
import uuid
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ConflictStatus(str, Enum):
    RECORDED = "recorded"
    ANALYZING = "analyzing"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    DISMISSED = "dismissed"
    ARCHIVED = "archived"


@dataclass
class ConflictRecord:
    conflict_id: str
    rule_1_id: str
    rule_2_id: str
    conflict_type: str
    severity: str
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    status: ConflictStatus = ConflictStatus.RECORDED
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolution_strategy: Optional[str] = None
    resolution_result: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConflictRecorder:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._records: Dict[str, ConflictRecord] = {}
        self._max_records = self.config.get("max_records", 10000)
        self._auto_archive = self.config.get("auto_archive", True)
        logger.info("ConflictRecorder initialized (max_records=%d, auto_archive=%s)",
                     self._max_records, self._auto_archive)

    def record(
        self,
        conflict_data: Dict[str, Any]
    ) -> ConflictRecord:
        if len(self._records) >= self._max_records:
            if self._auto_archive:
                self._archive_oldest()
            else:
                raise RuntimeError(f"Record limit reached ({self._max_records})")

        record = ConflictRecord(
            conflict_id=conflict_data.get("id") or str(uuid.uuid4()),
            rule_1_id=conflict_data.get("rule_1_id", "unknown"),
            rule_2_id=conflict_data.get("rule_2_id", "unknown"),
            conflict_type=conflict_data.get("conflict_type", "unknown"),
            severity=conflict_data.get("severity", "low"),
            description=conflict_data.get("description", ""),
            context=conflict_data.get("context", {}),
            status=ConflictStatus(conflict_data.get("status", ConflictStatus.RECORDED.value)),
            metadata=conflict_data.get("metadata", {}),
        )
        self._records[record.conflict_id] = record
        logger.info("Recorded conflict %s: %s vs %s [%s]",
                     record.conflict_id[:8], record.rule_1_id, record.rule_2_id,
                     record.conflict_type)
        return record

    def record_many(self, conflicts: List[Dict[str, Any]]) -> List[ConflictRecord]:
        return [self.record(c) for c in conflicts]

    def get(self, conflict_id: str) -> Optional[ConflictRecord]:
        return self._records.get(conflict_id)

    def query(
        self,
        rule_id: Optional[str] = None,
        conflict_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[ConflictStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100
    ) -> List[ConflictRecord]:
        results = list(self._records.values())

        if rule_id:
            results = [r for r in results if r.rule_1_id == rule_id or r.rule_2_id == rule_id]
        if conflict_type:
            results = [r for r in results if r.conflict_type == conflict_type]
        if severity:
            results = [r for r in results if r.severity == severity]
        if status:
            results = [r for r in results if r.status == status]
        if since:
            results = [r for r in results if r.timestamp >= since]
        if until:
            results = [r for r in results if r.timestamp <= until]

        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def update_status(
        self,
        conflict_id: str,
        status: ConflictStatus,
        resolution_strategy: Optional[str] = None,
        resolution_result: Optional[str] = None
    ) -> bool:
        record = self._records.get(conflict_id)
        if not record:
            logger.warning("Conflict %s not found for status update", conflict_id)
            return False

        record.status = status
        if status == ConflictStatus.RESOLVED:
            record.resolved_at = datetime.now(timezone.utc)
            record.resolution_strategy = resolution_strategy
            record.resolution_result = resolution_result

        logger.info("Updated conflict %s status to %s", conflict_id[:8], status.value)
        return True

    def update_status_many(
        self,
        conflict_ids: List[str],
        status: ConflictStatus,
        batch_size: int = 100
    ) -> int:
        updated = 0
        for i in range(0, len(conflict_ids), batch_size):
            batch = conflict_ids[i:i + batch_size]
            for cid in batch:
                if self.update_status(cid, status):
                    updated += 1
        return updated

    def filter_by(
        self,
        predicate: Callable[[ConflictRecord], bool]
    ) -> List[ConflictRecord]:
        return [r for r in self._records.values() if predicate(r)]

    def count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self._records.values():
            counts[r.conflict_type] = counts.get(r.conflict_type, 0) + 1
        return counts

    def count_by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self._records.values():
            counts[r.severity] = counts.get(r.severity, 0) + 1
        return counts

    def count_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self._records.values():
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        return counts

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_records": len(self._records),
            "by_type": self.count_by_type(),
            "by_severity": self.count_by_severity(),
            "by_status": self.count_by_status(),
            "resolution_rate": self._resolution_rate()
        }

    def _resolution_rate(self) -> float:
        total = len(self._records)
        if total == 0:
            return 0.0
        resolved = sum(1 for r in self._records.values()
                       if r.status in (ConflictStatus.RESOLVED, ConflictStatus.ARCHIVED))
        return resolved / total

    def _archive_oldest(self) -> None:
        sorted_ids = sorted(self._records.keys(),
                           key=lambda k: self._records[k].timestamp)
        to_remove = sorted_ids[:max(1, len(self._records) // 10)]
        for rid in to_remove:
            self._records[rid].status = ConflictStatus.ARCHIVED
        logger.info("Archived %d oldest conflict records", len(to_remove))

    def clear(self, status: Optional[ConflictStatus] = None) -> int:
        if status:
            to_remove = [k for k, v in self._records.items() if v.status == status]
            for k in to_remove:
                del self._records[k]
            return len(to_remove)
        count = len(self._records)
        self._records.clear()
        return count
