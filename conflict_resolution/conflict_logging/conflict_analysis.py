"""Analyze conflict patterns, trends, and generate actionable recommendations."""
import logging
import math
from typing import List, Dict, Any, Optional, Tuple, Counter as CounterType
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from .conflict_recorder import ConflictRecorder, ConflictRecord, ConflictStatus
from .resolution_tracker import ResolutionTracker, TrackedResolution, ResolutionOutcome

logger = logging.getLogger(__name__)


@dataclass
class PatternInsight:
    pattern_id: str
    description: str
    frequency: int
    severity_distribution: Dict[str, int]
    affected_rules: List[str]
    recommendation: str
    confidence: float = 0.0


@dataclass
class TrendPoint:
    period: str
    count: int
    severity_breakdown: Dict[str, int]


@dataclass
class AnalysisReport:
    analysis_id: str
    generated_at: datetime
    total_conflicts: int
    patterns: List[PatternInsight]
    trends: List[TrendPoint]
    hotspots: Dict[str, Any]
    recommendations: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConflictAnalysis:
    def __init__(
        self,
        recorder: Optional[ConflictRecorder] = None,
        tracker: Optional[ResolutionTracker] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> None:
        self.config = config or {}
        self._recorder = recorder
        self._tracker = tracker
        self._analysis_results: List[AnalysisReport] = []
        self._min_pattern_frequency = self.config.get("min_pattern_frequency", 2)
        self._trend_window_days = self.config.get("trend_window_days", 30)
        logger.info("ConflictAnalysis initialized (min_freq=%d, trend_window=%dd)",
                     self._min_pattern_frequency, self._trend_window_days)

    def analyze(self, conflict_history: Optional[List[Dict[str, Any]]] = None) -> AnalysisReport:
        records = self._get_records(conflict_history)
        if not records:
            return self._empty_report()

        patterns = self._mine_patterns(records)
        trends = self._compute_trends(records)
        hotspots = self._find_hotspots(records, patterns)
        recommendations = self._generate_recommendations(patterns, trends, hotspots)

        report = AnalysisReport(
            analysis_id=f"analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            generated_at=datetime.now(timezone.utc),
            total_conflicts=len(records),
            patterns=patterns,
            trends=trends,
            hotspots=hotspots,
            recommendations=recommendations,
        )

        self._analysis_results.append(report)
        logger.info("Analysis complete: %d conflicts, %d patterns, %d recommendations",
                     len(records), len(patterns), len(recommendations))
        return report

    def _mine_patterns(
        self,
        records: List[ConflictRecord]
    ) -> List[PatternInsight]:
        type_groups: Dict[str, List[ConflictRecord]] = defaultdict(list)
        for r in records:
            type_groups[r.conflict_type].append(r)

        insights: List[PatternInsight] = []
        for conflict_type, group in type_groups.items():
            if len(group) < self._min_pattern_frequency:
                continue

            sev_dist: Dict[str, int] = Counter(r.severity for r in group)
            affected: List[str] = list(set(
                r.rule_1_id for r in group
            ) | set(r.rule_2_id for r in group))

            recommendation = self._recommendation_for_type(conflict_type, len(group))
            confidence = min(1.0, len(group) / (self._min_pattern_frequency * 5))

            insights.append(PatternInsight(
                pattern_id=f"pattern_{conflict_type}",
                description=f"Recurring {conflict_type} conflicts ({len(group)} occurrences)",
                frequency=len(group),
                severity_distribution=dict(sev_dist),
                affected_rules=sorted(affected)[:20],
                recommendation=recommendation,
                confidence=confidence
            ))

        insights.sort(key=lambda p: p.frequency, reverse=True)
        return insights

    def _compute_trends(self, records: List[ConflictRecord]) -> List[TrendPoint]:
        if not records:
            return []

        time_min = min(r.timestamp for r in records)
        time_max = max(r.timestamp for r in records)
        span = (time_max - time_min).total_seconds()
        if span < 1:
            return []

        num_buckets = min(10, max(3, int(span / 86400) + 1))
        bucket_seconds = span / num_buckets
        buckets: List[List[ConflictRecord]] = [[] for _ in range(num_buckets)]

        for r in records:
            idx = min(num_buckets - 1,
                     int((r.timestamp - time_min).total_seconds() / bucket_seconds))
            buckets[idx].append(r)

        trends: List[TrendPoint] = []
        for i, bucket in enumerate(buckets):
            period_start = time_min + timedelta(seconds=i * bucket_seconds)
            period_label = period_start.strftime("%Y-%m-%d")
            sev_break: Dict[str, int] = Counter(r.severity for r in bucket)
            trends.append(TrendPoint(
                period=period_label,
                count=len(bucket),
                severity_breakdown=dict(sev_break)
            ))

        return trends

    def _find_hotspots(
        self,
        records: List[ConflictRecord],
        patterns: List[PatternInsight]
    ) -> Dict[str, Any]:
        rule_pairs: CounterType[Tuple[str, str]] = Counter()
        for r in records:
            pair = (min(r.rule_1_id, r.rule_2_id), max(r.rule_1_id, r.rule_2_id))
            rule_pairs[pair] += 1

        top_pairs = rule_pairs.most_common(5)
        resolution_stats = self._get_resolution_stats()

        return {
            "most_conflicted_rules": [
                {"rule_1": p[0][0], "rule_2": p[0][1], "count": p[1]}
                for p in top_pairs
            ],
            "peak_conflict_period": max(
                (t for t in self._compute_trends(records)),
                key=lambda t: t.count
            ).period if patterns else None,
            "resolution_success_rate": resolution_stats.get("success_rate", 0.0),
        }

    def _get_resolution_stats(self) -> Dict[str, float]:
        if not self._tracker:
            return {"success_rate": 0.0, "total": 0}
        stats = self._tracker.get_statistics()
        return {
            "success_rate": stats.get("overall_success_rate", 0.0),
            "total": stats.get("total_resolutions", 0),
        }

    def _generate_recommendations(
        self,
        patterns: List[PatternInsight],
        trends: List[TrendPoint],
        hotspots: Dict[str, Any]
    ) -> List[str]:
        recommendations: List[str] = []

        for pattern in patterns[:3]:
            recommendations.append(
                f"[{pattern.pattern_id}] {pattern.recommendation} "
                f"(frequency: {pattern.frequency}, confidence: {pattern.confidence:.0%})"
            )

        if trends and len(trends) >= 2:
            midpoint = len(trends) // 2
            first_half = sum(t.count for t in trends[:midpoint])
            second_half = sum(t.count for t in trends[midpoint:])
            if second_half > first_half * 1.5:
                recommendations.append(
                    "TREND: Conflict rate is increasing significantly. "
                    "Review recent rule additions for quality issues."
                )
            elif first_half > second_half * 1.5 and first_half > 5:
                recommendations.append(
                    "TREND: Conflict rate is decreasing. "
                    "Current resolution strategies are effective."
                )

        if hotspots.get("resolution_success_rate", 1.0) < 0.7:
            recommendations.append(
                "ALERT: Resolution success rate is below 70%. "
                "Review resolution strategies and consider manual intervention for persistent conflicts."
            )

        return recommendations

    def _recommendation_for_type(self, conflict_type: str, frequency: int) -> str:
        recommendations = {
            "keyword_overlap": "Merge overlapping patterns into compound rules.",
            "pattern_overlap": "Narrow regex patterns or add negative lookaheads.",
            "domain_overlap": "Assign exclusive domain scopes to rules.",
            "enforcement_mismatch": "Align enforcement levels with tier hierarchy (safety=strict).",
            "action_clash": "Resolve conflicting actions via explicit precedence rules.",
            "scope_nesting": "Restructure rule scopes to avoid nesting conflicts.",
            "condition_contradiction": "Rewrite conditions to remove logical contradictions.",
            "contradictory_terms": "Standardize terminology across rule descriptions.",
            "opposing_actions": "Define clear action precedence for opposing pairs.",
            "condition_inverse": "Merge inverse conditions into single compound rule.",
            "scope_mismatch": "Align scope granularity between related rules.",
            "tier_inversion": "Reassign priorities so higher tiers have higher priority values.",
            "same_tier_gap": "Normalize priority values within each tier to avoid large gaps.",
            "duplicate_priority": "Assign unique priority values within each tier.",
            "chain_inversion": "Reorder priority chain to maintain ascending order.",
            "negative_priority": "Replace negative priorities with positive values (default 100).",
        }
        return recommendations.get(conflict_type,
                                  f"Review and consolidate rules involved in {conflict_type} conflicts.")

    def _get_records(
        self,
        conflict_history: Optional[List[Dict[str, Any]]]
    ) -> List[ConflictRecord]:
        if conflict_history is not None:
            return [
                ConflictRecord(
                    conflict_id=c.get("id", "unknown"),
                    rule_1_id=c.get("rule_1_id", "unknown"),
                    rule_2_id=c.get("rule_2_id", "unknown"),
                    conflict_type=c.get("conflict_type", "unknown"),
                    severity=c.get("severity", "low"),
                    description=c.get("description", ""),
                    context=c.get("context", {}),
                    status=ConflictStatus(c.get("status", ConflictStatus.RECORDED.value)),
                    timestamp=c.get("timestamp", datetime.now(timezone.utc)),
                )
                for c in conflict_history
            ]
        if self._recorder:
            return list(self._recorder._records.values())  # type: ignore
        return []

    def _empty_report(self) -> AnalysisReport:
        return AnalysisReport(
            analysis_id=f"analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            generated_at=datetime.now(timezone.utc),
            total_conflicts=0,
            patterns=[],
            trends=[],
            hotspots={},
            recommendations=["No conflicts detected. System is operating normally."]
        )

    def get_latest_report(self) -> Optional[AnalysisReport]:
        return self._analysis_results[-1] if self._analysis_results else None
