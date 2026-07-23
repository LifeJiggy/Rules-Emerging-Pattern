"""Track rule usage patterns, frequency, and identify under/over-utilized rules."""
import logging
from typing import List, Dict, Any, Optional, Tuple, Counter as CounterType
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter, deque

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    rule_id: str
    rule_name: str
    tier: str
    timestamp: datetime
    user_id: Optional[str]
    context: Dict[str, Any]
    duration_ms: float
    triggered: bool
    blocked: bool
    overridden: bool


@dataclass
class UsageStats:
    rule_id: str
    rule_name: str
    tier: str
    total_uses: int
    trigger_count: int
    block_count: int
    override_count: int
    frequency_per_day: float
    avg_duration_ms: float
    top_contexts: Dict[str, int]
    trend: str


class RuleUsageTracker:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._records: Dict[str, List[UsageRecord]] = defaultdict(
            lambda: deque(maxlen=self.config.get("max_records_per_rule", 10000))
        )
        self._tracked_rules: Dict[str, Dict[str, Any]] = {}
        self._user_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._daily_counts: Dict[str, int] = defaultdict(int)
        self._total_records = 0
        self._underutilized_threshold = self.config.get("underutilized_threshold", 10)
        self._overutilized_threshold = self.config.get("overutilized_threshold", 10000)
        self._tracking_window_days = self.config.get("tracking_window_days", 30)
        logger.info("RuleUsageTracker initialized (thresholds: under=%d, over=%d)",
                     self._underutilized_threshold, self._overutilized_threshold)

    def track_usage(self, rule_id: str, user_id: Optional[str] = None,
                    context: Optional[Dict[str, Any]] = None,
                    triggered: bool = False, blocked: bool = False,
                    overridden: bool = False, duration_ms: float = 0.0) -> UsageRecord:
        rule = self._tracked_rules.get(rule_id, {"id": rule_id, "name": rule_id, "tier": "unknown"})
        record = UsageRecord(
            rule_id=rule_id,
            rule_name=rule.get("name", rule_id),
            tier=rule.get("tier", "unknown"),
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            context=context or {},
            duration_ms=duration_ms,
            triggered=triggered,
            blocked=blocked,
            overridden=overridden,
        )
        records = self._records[rule_id]
        records.append(record)
        self._total_records += 1

        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_counts[day_key] += 1
        if user_id:
            self._user_counts[user_id][rule_id] += 1
        return record

    def register_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> None:
        self._tracked_rules[rule_id] = rule_data
        logger.debug("Registered rule %s for usage tracking", rule_id)

    def get_usage_stats(self, rule_id: str) -> Optional[UsageStats]:
        records = list(self._records.get(rule_id, []))
        if not records:
            return None
        rule = self._tracked_rules.get(rule_id, {"id": rule_id, "name": rule_id, "tier": "unknown"})
        window = timedelta(days=self._tracking_window_days)
        recent = [r for r in records if r.timestamp >= datetime.now(timezone.utc) - window]
        trigger_count = sum(1 for r in recent if r.triggered)
        block_count = sum(1 for r in recent if r.blocked)
        override_count = sum(1 for r in recent if r.overridden)
        days = max(1, self._tracking_window_days)
        freq = len(recent) / days
        avg_dur = sum(r.duration_ms for r in recent) / max(len(recent), 1)
        top_ctx: Dict[str, int] = Counter(
            str(r.context.get("domain", r.context.get("source", "unknown")))
            for r in recent
        )
        if len(recent) >= 5:
            first_half = recent[:len(recent)//2]
            second_half = recent[len(recent)//2:]
            trend = "increasing" if len(second_half) > len(first_half) * 1.2 else (
                "decreasing" if len(second_half) < len(first_half) * 0.8 else "stable"
            )
        else:
            trend = "insufficient_data"
        return UsageStats(
            rule_id=rule_id, rule_name=rule.get("name", rule_id),
            tier=rule.get("tier", "unknown"),
            total_uses=len(records), trigger_count=trigger_count,
            block_count=block_count, override_count=override_count,
            frequency_per_day=round(freq, 2),
            avg_duration_ms=round(avg_dur, 2),
            top_contexts=dict(top_ctx.most_common(5)),
            trend=trend,
        )

    def get_underutilized_rules(self) -> List[str]:
        return [
            rid for rid in self._tracked_rules
            if len(self._records.get(rid, [])) < self._underutilized_threshold
        ]

    def get_overutilized_rules(self) -> List[str]:
        return [
            rid for rid in self._tracked_rules
            if len(self._records.get(rid, [])) > self._overutilized_threshold
        ]

    def get_user_usage(self, user_id: str) -> Dict[str, int]:
        return dict(self._user_counts.get(user_id, {}))

    def get_most_used_rules(self, n: int = 10) -> List[Tuple[str, int]]:
        counts: CounterType = Counter()
        for rid, records in self._records.items():
            counts[rid] = len(records)
        return counts.most_common(n)

    def get_usage_trend(self, days: int = 7) -> Dict[str, int]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        trend: Dict[str, int] = defaultdict(int)
        for records in self._records.values():
            for r in records:
                if r.timestamp >= cutoff:
                    trend[r.rule_id] += 1
        return dict(trend)

    def get_statistics(self) -> Dict[str, Any]:
        total = sum(len(v) for v in self._records.values())
        return {
            "total_records": self._total_records,
            "tracked_rules": len(self._tracked_rules),
            "rules_with_usage": len([r for r in self._records.values() if r]),
            "underutilized": len(self.get_underutilized_rules()),
            "overutilized": len(self.get_overutilized_rules()),
            "active_users": len(self._user_counts),
            "trending_rules": self.get_usage_trend(7),
        }
