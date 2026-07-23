"""Conflict logging - records and analyzes rule conflicts detected during evaluation."""
import logging
import uuid
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)


class ConflictCategory(str, Enum):
    KEYWORD_OVERLAP = "keyword_overlap"
    ACTION_CLASH = "action_clash"
    TIER_MISMATCH = "tier_mismatch"
    PRIORITY_INVERSION = "priority_inversion"
    SEMANTIC = "semantic"
    ENFORCEMENT = "enforcement"
    SCOPE = "scope"
    CONDITION = "condition"


class ConflictSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ConflictEntry:
    conflict_id: str
    category: ConflictCategory
    severity: ConflictSeverity
    rule_1_id: str
    rule_2_id: Optional[str]
    description: str
    context: Dict[str, Any]
    resolution: Optional[str]
    detected_at: datetime
    resolved_at: Optional[datetime] = None


class ConflictLogger:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._conflicts: Dict[str, ConflictEntry] = {}
        self._max_conflicts = self.config.get("max_conflicts", 10000)
        self._log_count = 0
        self._resolve_count = 0
        self._categories: Dict[str, int] = defaultdict(int)
        logger.info("ConflictLogger initialized (max_conflicts=%d)", self._max_conflicts)

    def log_conflict(self, category: ConflictCategory, rule_1_id: str,
                     description: str, severity: ConflictSeverity = ConflictSeverity.MEDIUM,
                     rule_2_id: Optional[str] = None,
                     context: Optional[Dict[str, Any]] = None) -> ConflictEntry:
        if len(self._conflicts) >= self._max_conflicts:
            oldest = min(self._conflicts.keys(), key=lambda k: self._conflicts[k].detected_at)
            del self._conflicts[oldest]

        entry = ConflictEntry(
            conflict_id=str(uuid.uuid4()),
            category=category,
            severity=severity,
            rule_1_id=rule_1_id,
            rule_2_id=rule_2_id,
            description=description,
            context=context or {},
            resolution=None,
            detected_at=datetime.now(timezone.utc),
        )
        self._conflicts[entry.conflict_id] = entry
        self._log_count += 1
        self._categories[category.value] += 1
        logger.info("Conflict: %s [%s] %s vs %s: %s", category.value, severity.value,
                     rule_1_id, rule_2_id or "", description[:60])
        return entry

    def resolve(self, conflict_id: str, resolution: str) -> bool:
        entry = self._conflicts.get(conflict_id)
        if not entry:
            return False
        entry.resolution = resolution
        entry.resolved_at = datetime.now(timezone.utc)
        self._resolve_count += 1
        return True

    def resolve_batch(self, conflict_ids: List[str], resolution: str) -> int:
        count = 0
        for cid in conflict_ids:
            if self.resolve(cid, resolution):
                count += 1
        return count

    def get_conflict(self, conflict_id: str) -> Optional[ConflictEntry]:
        return self._conflicts.get(conflict_id)

    def get_conflicts_by_rule(self, rule_id: str) -> List[ConflictEntry]:
        return [
            c for c in self._conflicts.values()
            if c.rule_1_id == rule_id or c.rule_2_id == rule_id
        ]

    def get_conflicts_by_category(self, category: ConflictCategory) -> List[ConflictEntry]:
        return [c for c in self._conflicts.values() if c.category == category]

    def get_unresolved(self) -> List[ConflictEntry]:
        return [c for c in self._conflicts.values() if c.resolution is None]

    def get_statistics(self) -> Dict[str, Any]:
        sev_counts: Dict[str, int] = defaultdict(int)
        resolved = 0
        for c in self._conflicts.values():
            sev_counts[c.severity.value] += 1
            if c.resolved_at:
                resolved += 1
        return {
            "total_logged": self._log_count,
            "total_conflicts": len(self._conflicts),
            "resolved": resolved,
            "unresolved": len(self._conflicts) - resolved,
            "by_category": dict(self._categories),
            "by_severity": dict(sev_counts),
            "resolve_rate": resolved / max(len(self._conflicts), 1),
        }

    def get_top_conflicted_rules(self, n: int = 10) -> List[Tuple[str, int]]:
        rule_counts: Counter = Counter()
        for c in self._conflicts.values():
            rule_counts[c.rule_1_id] += 1
            if c.rule_2_id:
                rule_counts[c.rule_2_id] += 1
        return rule_counts.most_common(n)

    def clear(self) -> int:
        count = len(self._conflicts)
        self._conflicts.clear()
        return count
