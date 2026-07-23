"""Adaptive rule adaptation engine with threshold, pattern, and scheduling logic."""

import copy
import csv
import io
import json
import logging
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from rules_emerging_pattern.models.rule import (
    Rule,
    RulePattern,
    RuleSeverity,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType

logger = logging.getLogger(__name__)


class AdaptationType(str, Enum):
    """Types of rule adaptations."""
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    KEYWORD = "keyword"
    REGEX = "regex"
    PRIORITY = "priority"
    SEVERITY = "severity"
    TIER = "tier"
    ENFORCEMENT = "enforcement"
    DEACTIVATION = "deactivation"
    REACTIVATION = "reactivation"


class AdaptationStatus(str, Enum):
    """Status of an adaptation event."""
    PENDING = "pending"
    APPLIED = "applied"
    REVERTED = "reverted"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AdaptationRecord:
    """Record of a single adaptation event."""
    adaptation_id: str
    rule_id: str
    adaptation_type: AdaptationType
    status: AdaptationStatus = AdaptationStatus.PENDING
    previous_state: Dict[str, Any] = field(default_factory=dict)
    new_state: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    metrics_before: Dict[str, float] = field(default_factory=dict)
    metrics_after: Dict[str, float] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None
    applied_at: Optional[datetime] = None
    reverted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single rule."""
    rule_id: str
    total_evaluations: int = 0
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    avg_response_time_ms: float = 0.0
    total_response_time_ms: float = 0.0
    cache_hit_rate: float = 0.0
    override_count: int = 0
    user_satisfaction: float = 0.0
    window_start: datetime = field(default_factory=datetime.utcnow)
    window_end: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(days=1))

    @property
    def false_positive_rate(self) -> float:
        """False positive rate from total negatives."""
        total_neg = self.false_positives + self.true_negatives
        return self.false_positives / max(total_neg, 1)

    @property
    def false_negative_rate(self) -> float:
        """False negative rate from total positives."""
        total_pos = self.true_positives + self.false_negatives
        return self.false_negatives / max(total_pos, 1)

    @property
    def accuracy(self) -> float:
        """Overall accuracy."""
        correct = self.true_positives + self.true_negatives
        total = correct + self.false_positives + self.false_negatives
        return correct / max(total, 1)

    @property
    def precision(self) -> float:
        """Precision score."""
        denom = self.true_positives + self.false_positives
        return self.true_positives / max(denom, 1)

    @property
    def recall(self) -> float:
        """Recall score."""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / max(denom, 1)

    @property
    def f1_score(self) -> float:
        """F1 score (harmonic mean of precision and recall)."""
        p = self.precision
        r = self.recall
        denom = p + r
        return 2.0 * p * r / max(denom, 1e-10)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "total_evaluations": self.total_evaluations,
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "override_count": self.override_count,
            "user_satisfaction": round(self.user_satisfaction, 4),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
        }


@dataclass
class AdaptationStatistics:
    """Aggregated statistics for the adaptation engine."""
    total_adaptations: int = 0
    successful_adaptations: int = 0
    failed_adaptations: int = 0
    reverted_adaptations: int = 0
    adaptations_by_type: Dict[str, int] = field(default_factory=dict)
    adaptations_by_rule: Dict[str, int] = field(default_factory=dict)
    avg_improvement_f1: float = 0.0
    avg_improvement_accuracy: float = 0.0
    total_metrics_collected: int = 0
    rules_being_adapted: int = 0
    last_adaptation_time: Optional[datetime] = None
    uptime_hours: float = 0.0


class ThresholdAdapter:
    """Handles threshold-based parameter adaptation for rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._min_threshold = self.config.get("min_threshold", 0.3)
        self._max_threshold = self.config.get("max_threshold", 0.99)
        self._step_size = self.config.get("step_size", 0.05)
        logger.info(
            "ThresholdAdapter initialized (min=%.2f, max=%.2f, step=%.2f)",
            self._min_threshold, self._max_threshold, self._step_size,
        )

    def adapt_confidence_threshold(
        self,
        rule: Rule,
        metrics: PerformanceMetrics,
    ) -> Optional[float]:
        """Adapt the confidence threshold based on performance metrics.

        Returns the new threshold value, or None if no adaptation is needed.
        """
        if not rule.patterns:
            return None

        current = rule.patterns[0].confidence_threshold
        fpr = metrics.false_positive_rate
        fnr = metrics.false_negative_rate

        if fpr > self.config.get("fpr_target", 0.15):
            new_threshold = current + self._step_size
            logger.debug(
                "Increasing threshold %.3f -> %.3f (fpr=%.3f)",
                current, new_threshold, fpr,
            )
        elif fnr > self.config.get("fnr_target", 0.10):
            new_threshold = current - self._step_size
            logger.debug(
                "Decreasing threshold %.3f -> %.3f (fnr=%.3f)",
                current, new_threshold, fnr,
            )
        else:
            return None

        new_threshold = max(self._min_threshold, min(self._max_threshold, new_threshold))

        if abs(new_threshold - current) < 0.001:
            return None

        return new_threshold

    def adapt_priority(
        self,
        rule: Rule,
        metrics: PerformanceMetrics,
    ) -> Optional[int]:
        """Adapt rule priority based on performance."""
        current = rule.priority

        if metrics.accuracy < self.config.get("accuracy_min", 0.6):
            new_priority = min(1000, current + 50)
        elif metrics.accuracy > self.config.get("accuracy_max", 0.95):
            new_priority = max(1, current - 50)
        else:
            return None

        if new_priority != current:
            return new_priority
        return None


class PatternAdapter:
    """Handles pattern-level adaptations (keywords, regex)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._keyword_addition_threshold = self.config.get("keyword_addition_threshold", 0.8)
        self._keyword_removal_threshold = self.config.get("keyword_removal_threshold", 0.1)
        logger.info("PatternAdapter initialized")

    def suggest_keyword_additions(
        self,
        rule: Rule,
        metrics: PerformanceMetrics,
        frequent_terms: List[str],
    ) -> List[str]:
        """Suggest keywords to add based on frequent false-negative terms."""
        suggestions: List[str] = []
        if metrics.false_negative_rate > self.config.get("fnr_keyword_threshold", 0.15):
            for term in frequent_terms:
                term_lower = term.lower()
                existing_keywords = set(k.lower() for k in self._get_all_keywords(rule))
                if term_lower not in existing_keywords:
                    suggestions.append(term_lower)
                    if len(suggestions) >= self.config.get("max_additions", 3):
                        break
        return suggestions

    def suggest_keyword_removals(
        self,
        rule: Rule,
        metrics: PerformanceMetrics,
        false_positive_terms: List[str],
    ) -> List[str]:
        """Suggest keywords to remove based on false-positive terms."""
        removals: List[str] = []
        if metrics.false_positive_rate > self.config.get("fpr_keyword_threshold", 0.2):
            for term in false_positive_terms:
                term_lower = term.lower()
                all_keywords = set(k.lower() for k in self._get_all_keywords(rule))
                if term_lower in all_keywords:
                    removals.append(term_lower)
                    if len(removals) >= self.config.get("max_removals", 2):
                        break
        return removals

    def adapt_pattern(
        self,
        rule: Rule,
        keywords_to_add: List[str],
        keywords_to_remove: List[str],
    ) -> Rule:
        """Apply keyword additions and removals to rule patterns."""
        rule = copy.deepcopy(rule)

        for pattern in rule.patterns:
            pattern.keywords = [
                kw for kw in pattern.keywords
                if kw.lower() not in keywords_to_remove
            ]
            for kw in keywords_to_add:
                if kw not in pattern.keywords:
                    pattern.keywords.append(kw)

        if keywords_to_add or keywords_to_remove:
            rule.updated_at = datetime.utcnow()

        return rule

    def _get_all_keywords(self, rule: Rule) -> List[str]:
        """Get all keywords across all patterns in a rule."""
        keywords: List[str] = []
        for pattern in rule.patterns:
            keywords.extend(pattern.keywords)
        return keywords


class RuleAdaptationEngine:
    """Engine for adapting rules based on performance metrics and feedback.

    Supports threshold adaptation, pattern adjustment, batch operations,
    rollback, history management, and config-driven thresholds.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._threshold_adapter = ThresholdAdapter(self.config.get("threshold_adapter", {}))
        self._pattern_adapter = PatternAdapter(self.config.get("pattern_adapter", {}))
        self._adaptation_history: deque = deque(
            maxlen=self.config.get("max_history", 5000)
        )
        self._metrics_store: Dict[str, PerformanceMetrics] = {}
        self._current_adaptations: Dict[str, AdaptationRecord] = {}
        self._snapshots: Dict[str, Rule] = {}
        self._rollback_stack: List[AdaptationRecord] = []
        self._frequency_tracker: Dict[str, List[datetime]] = defaultdict(list)
        self._start_time: datetime = datetime.utcnow()

        logger.info(
            "RuleAdaptationEngine initialized (max_history=%d)",
            self.config.get("max_history", 5000),
        )

    def adapt_rule(
        self,
        rule: Rule,
        performance_data: Optional[Dict[str, Any]] = None,
        metrics: Optional[PerformanceMetrics] = None,
    ) -> Optional[Rule]:
        """Adapt a single rule based on performance data.

        Args:
            rule: The rule to adapt.
            performance_data: Raw performance dictionary (optional).
            metrics: Pre-computed PerformanceMetrics (optional).

        Returns:
            Adapted Rule if changes were applied, None otherwise.
        """
        if rule.tier == RuleTier.SAFETY:
            logger.info("Skipping adaptation for safety rule %s", rule.id)
            return None

        if not self._can_adapt_rule(rule.id):
            logger.debug("Adaptation frequency-capped for rule %s", rule.id)
            return None

        if metrics is None and performance_data:
            metrics = self._build_metrics(rule.id, performance_data)
        elif metrics is None:
            metrics = self._metrics_store.get(rule.id)
            if metrics is None:
                logger.debug("No metrics available for rule %s, skipping", rule.id)
                return None

        try:
            adapted_rule = copy.deepcopy(rule)
            changes: Dict[str, Any] = {}

            new_threshold = self._threshold_adapter.adapt_confidence_threshold(adapted_rule, metrics)
            if new_threshold is not None:
                for pattern in adapted_rule.patterns:
                    pattern.confidence_threshold = new_threshold
                changes["confidence_threshold"] = new_threshold

            new_priority = self._threshold_adapter.adapt_priority(adapted_rule, metrics)
            if new_priority is not None:
                adapted_rule.priority = new_priority
                changes["priority"] = new_priority

            if not changes:
                return None

            self._record_adaptation(
                rule=rule,
                adapted_rule=adapted_rule,
                adaptation_type=AdaptationType.THRESHOLD,
                reason=self._build_reason(metrics, changes),
                metrics_before=metrics.to_dict(),
                changes=changes,
            )

            self._frequency_tracker[rule.id].append(datetime.utcnow())
            adapted_rule.updated_at = datetime.utcnow()

            logger.info(
                "Adapted rule %s (threshold=%.3f, priority=%d)",
                rule.id,
                adapted_rule.patterns[0].confidence_threshold if adapted_rule.patterns else -1,
                adapted_rule.priority,
            )

            return adapted_rule

        except Exception as exc:
            logger.error("Adaptation failed for rule %s: %s", rule.id, exc, exc_info=True)
            return None

    def adapt_patterns(
        self,
        rule: Rule,
        false_positive_terms: Optional[List[str]] = None,
        frequent_terms: Optional[List[str]] = None,
        metrics: Optional[PerformanceMetrics] = None,
    ) -> Optional[Rule]:
        """Adapt a rule's patterns (keywords/regex) based on term frequency.

        Args:
            rule: The rule to adapt.
            false_positive_terms: Terms causing false positives.
            frequent_terms: Terms that should trigger the rule.
            metrics: Performance metrics for the rule.

        Returns:
            Adapted Rule or None.
        """
        if rule.tier == RuleTier.SAFETY:
            return None

        if metrics is None:
            metrics = self._metrics_store.get(rule.id)
        if metrics is None:
            return None

        try:
            keywords_to_add: List[str] = []
            keywords_to_remove: List[str] = []

            if frequent_terms:
                keywords_to_add = self._pattern_adapter.suggest_keyword_additions(
                    rule, metrics, frequent_terms,
                )
            if false_positive_terms:
                keywords_to_remove = self._pattern_adapter.suggest_keyword_removals(
                    rule, metrics, false_positive_terms,
                )

            if not keywords_to_add and not keywords_to_remove:
                return None

            adapted_rule = self._pattern_adapter.adapt_pattern(
                rule, keywords_to_add, keywords_to_remove,
            )

            changes: Dict[str, Any] = {}
            if keywords_to_add:
                changes["keywords_added"] = keywords_to_add
            if keywords_to_remove:
                changes["keywords_removed"] = keywords_to_remove

            self._record_adaptation(
                rule=rule,
                adapted_rule=adapted_rule,
                adaptation_type=AdaptationType.PATTERN,
                reason=f"Pattern adaptation: +{len(keywords_to_add)} keywords, -{len(keywords_to_remove)} keywords",
                metrics_before=metrics.to_dict(),
                changes=changes,
            )

            logger.info(
                "Adapted patterns for rule %s: +%d keywords, -%d keywords",
                rule.id, len(keywords_to_add), len(keywords_to_remove),
            )

            return adapted_rule

        except Exception as exc:
            logger.error("Pattern adaptation failed for rule %s: %s", rule.id, exc, exc_info=True)
            return None

    def batch_adapt(
        self,
        rules: List[Rule],
        metrics_map: Optional[Dict[str, PerformanceMetrics]] = None,
    ) -> List[Tuple[str, Optional[Rule]]]:
        """Adapt multiple rules in batch.

        Args:
            rules: List of rules to potentially adapt.
            metrics_map: Optional mapping of rule_id to PerformanceMetrics.

        Returns:
            List of (rule_id, adapted_rule_or_None) tuples.
        """
        results: List[Tuple[str, Optional[Rule]]] = []
        logger.info("Starting batch adaptation for %d rules", len(rules))

        for rule in rules:
            metrics = None
            if metrics_map:
                metrics = metrics_map.get(rule.id)

            adapted = self.adapt_rule(rule, metrics=metrics)
            results.append((rule.id, adapted))

            if adapted is None:
                adapted = self.adapt_patterns(rule, metrics=metrics)
                results.append((rule.id, adapted))

        success_count = sum(1 for _, r in results if r is not None)
        logger.info(
            "Batch adaptation complete: %d/%d rules adapted",
            success_count, len(rules),
        )

        return results

    def rollback(self, adaptation_id: str) -> Optional[Rule]:
        """Rollback a specific adaptation.

        Args:
            adaptation_id: ID of the adaptation to revert.

        Returns:
            The reverted Rule, or None if rollback failed.
        """
        try:
            record = self._current_adaptations.get(adaptation_id)
            if record is None:
                for rec in self._adaptation_history:
                    if rec.adaptation_id == adaptation_id:
                        record = rec
                        break

            if record is None:
                logger.warning("Adaptation %s not found for rollback", adaptation_id)
                return None

            previous = record.previous_state
            rule_id = record.rule_id

            restored_rule = Rule(**previous)
            restored_rule.updated_at = datetime.utcnow()

            record.status = AdaptationStatus.REVERTED
            record.reverted_at = datetime.utcnow()
            record.success = False

            self._rollback_stack.append(record)
            self._snapshots[rule_id] = restored_rule

            logger.info(
                "Rolled back adaptation %s for rule %s",
                adaptation_id, rule_id,
            )

            return restored_rule

        except Exception as exc:
            logger.error(
                "Rollback failed for adaptation %s: %s",
                adaptation_id, exc, exc_info=True,
            )
            return None

    def batch_rollback(
        self,
        rule_ids: Optional[List[str]] = None,
        adaptation_type: Optional[AdaptationType] = None,
        since: Optional[datetime] = None,
    ) -> int:
        """Rollback multiple adaptations matching criteria.

        Args:
            rule_ids: Optional list of rule IDs to rollback.
            adaptation_type: Optional type filter.
            since: Optional datetime threshold.

        Returns:
            Number of successful rollbacks.
        """
        targets: List[AdaptationRecord] = []
        for record in self._adaptation_history:
            if record.status != AdaptationStatus.APPLIED:
                continue
            if rule_ids and record.rule_id not in rule_ids:
                continue
            if adaptation_type and record.adaptation_type != adaptation_type:
                continue
            if since and record.applied_at and record.applied_at < since:
                continue
            targets.append(record)

        count = 0
        for record in targets:
            result = self.rollback(record.adaptation_id)
            if result is not None:
                count += 1

        logger.info("Batch rollback: %d/%d adaptations reverted", count, len(targets))
        return count

    def record_metrics(self, rule_id: str, metrics: Dict[str, Any]) -> PerformanceMetrics:
        """Record and update performance metrics for a rule.

        Args:
            rule_id: The rule identifier.
            metrics: Dictionary of metric values.

        Returns:
            Updated PerformanceMetrics instance.
        """
        if rule_id not in self._metrics_store:
            self._metrics_store[rule_id] = PerformanceMetrics(rule_id=rule_id)

        current = self._metrics_store[rule_id]
        current.total_evaluations += metrics.get("evaluations", 0)
        current.true_positives += metrics.get("true_positives", 0)
        current.true_negatives += metrics.get("true_negatives", 0)
        current.false_positives += metrics.get("false_positives", 0)
        current.false_negatives += metrics.get("false_negatives", 0)
        current.total_response_time_ms += metrics.get("response_time_ms", 0)
        current.avg_response_time_ms = (
            current.total_response_time_ms / max(current.total_evaluations, 1)
        )
        current.override_count += metrics.get("overrides", 0)
        current.cache_hit_rate = metrics.get("cache_hit_rate", current.cache_hit_rate)

        satisfaction = metrics.get("user_satisfaction")
        if satisfaction is not None:
            alpha = self.config.get("satisfaction_alpha", 0.3)
            current.user_satisfaction = (
                (1.0 - alpha) * current.user_satisfaction + alpha * satisfaction
            )

        return current

    def get_metrics(self, rule_id: str) -> Optional[PerformanceMetrics]:
        """Get stored performance metrics for a rule."""
        return self._metrics_store.get(rule_id)

    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """Get all stored performance metrics."""
        return dict(self._metrics_store)

    def get_adaptation_history(
        self,
        rule_id: Optional[str] = None,
        adaptation_type: Optional[AdaptationType] = None,
        status: Optional[AdaptationStatus] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        sort_by: str = "created_at",
        ascending: bool = False,
    ) -> List[AdaptationRecord]:
        """Query adaptation history with filters and pagination.

        Args:
            rule_id: Filter by rule ID.
            adaptation_type: Filter by adaptation type.
            status: Filter by adaptation status.
            limit: Max results to return.
            offset: Number of records to skip.
            since: Only records after this datetime.
            until: Only records before this datetime.
            sort_by: Field to sort by.
            ascending: Sort ascending (default descending).

        Returns:
            Filtered and sorted list of AdaptationRecord.
        """
        records = list(self._adaptation_history)

        if rule_id:
            records = [r for r in records if r.rule_id == rule_id]
        if adaptation_type:
            records = [r for r in records if r.adaptation_type == adaptation_type]
        if status:
            records = [r for r in records if r.status == status]
        if since:
            records = [r for r in records if r.created_at >= since]
        if until:
            records = [r for r in records if r.created_at <= until]

        if sort_by == "created_at":
            records.sort(key=lambda r: r.created_at, reverse=not ascending)
        elif sort_by == "rule_id":
            records.sort(key=lambda r: r.rule_id, reverse=not ascending)
        elif sort_by == "adaptation_type":
            records.sort(key=lambda r: r.adaptation_type.value, reverse=not ascending)

        records = records[offset:]
        if limit:
            records = records[:limit]

        return records

    def export_history(
        self,
        format: str = "json",
        **filters: Any,
    ) -> str:
        """Export adaptation history as JSON or CSV string.

        Args:
            format: Output format ("json" or "csv").
            **filters: Same filter kwargs as get_adaptation_history.

        Returns:
            Formatted string of adaptation history.
        """
        records = self.get_adaptation_history(**filters)

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "adaptation_id", "rule_id", "adaptation_type", "status",
                "reason", "success", "applied_at", "created_at",
            ])
            for r in records:
                writer.writerow([
                    r.adaptation_id, r.rule_id, r.adaptation_type.value,
                    r.status.value, r.reason, r.success,
                    r.applied_at.isoformat() if r.applied_at else "",
                    r.created_at.isoformat(),
                ])
            return output.getvalue()

        data = [
            {
                "adaptation_id": r.adaptation_id,
                "rule_id": r.rule_id,
                "adaptation_type": r.adaptation_type.value,
                "status": r.status.value,
                "reason": r.reason,
                "success": r.success,
                "error_message": r.error_message,
                "metrics_before": r.metrics_before,
                "metrics_after": r.metrics_after,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "reverted_at": r.reverted_at.isoformat() if r.reverted_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
        return json.dumps(data, indent=2, default=str)

    def clear_metrics(self, rule_id: Optional[str] = None) -> int:
        """Clear performance metrics.

        Args:
            rule_id: If set, clear only for this rule.

        Returns:
            Number of metric entries cleared.
        """
        if rule_id:
            count = 1 if rule_id in self._metrics_store else 0
            self._metrics_store.pop(rule_id, None)
        else:
            count = len(self._metrics_store)
            self._metrics_store.clear()
        logger.info("Cleared %d metric entries", count)
        return count

    def get_statistics(self) -> AdaptationStatistics:
        """Get aggregated adaptation statistics."""
        total = len(self._adaptation_history)
        successful = sum(1 for r in self._adaptation_history if r.success)
        failed = sum(1 for r in self._adaptation_history if not r.success)
        reverted = sum(1 for r in self._adaptation_history if r.status == AdaptationStatus.REVERTED)

        by_type: Dict[str, int] = defaultdict(int)
        by_rule: Dict[str, int] = defaultdict(int)
        f1_improvements: List[float] = []
        accuracy_improvements: List[float] = []

        for record in self._adaptation_history:
            by_type[record.adaptation_type.value] += 1
            by_rule[record.rule_id] += 1
            if record.metrics_before and record.metrics_after:
                f1_before = record.metrics_before.get("f1_score", 0.0)
                f1_after = record.metrics_after.get("f1_score", 0.0)
                f1_improvements.append(f1_after - f1_before)
                acc_before = record.metrics_before.get("accuracy", 0.0)
                acc_after = record.metrics_after.get("accuracy", 0.0)
                accuracy_improvements.append(acc_after - acc_before)

        uptime = (datetime.utcnow() - self._start_time).total_seconds() / 3600.0

        return AdaptationStatistics(
            total_adaptations=total,
            successful_adaptations=successful,
            failed_adaptations=failed,
            reverted_adaptations=reverted,
            adaptations_by_type=dict(by_type),
            adaptations_by_rule=dict(by_rule),
            avg_improvement_f1=sum(f1_improvements) / max(len(f1_improvements), 1),
            avg_improvement_accuracy=sum(accuracy_improvements) / max(len(accuracy_improvements), 1),
            total_metrics_collected=len(self._metrics_store),
            rules_being_adapted=len(by_rule),
            last_adaptation_time=self._last_adaptation_time(),
            uptime_hours=round(uptime, 2),
        )

    def get_adaptation_summary(self, rule_id: str) -> Dict[str, Any]:
        """Get a summary of adaptations for a specific rule."""
        records = self.get_adaptation_history(rule_id=rule_id)
        by_type: Dict[str, int] = defaultdict(int)
        statuses: Dict[str, int] = defaultdict(int)
        total_improvement = 0.0

        for r in records:
            by_type[r.adaptation_type.value] += 1
            statuses[r.status.value] += 1
            if r.metrics_before and r.metrics_after:
                f1_before = r.metrics_before.get("f1_score", 0.0)
                f1_after = r.metrics_after.get("f1_score", 0.0)
                total_improvement += f1_after - f1_before

        return {
            "rule_id": rule_id,
            "total_adaptations": len(records),
            "adaptations_by_type": dict(by_type),
            "status_breakdown": dict(statuses),
            "total_f1_improvement": round(total_improvement, 4),
            "current_metrics": self._metrics_store.get(rule_id).to_dict() if rule_id in self._metrics_store else None,
        }

    def _can_adapt_rule(self, rule_id: str) -> bool:
        """Check if a rule can be adapted based on frequency capping."""
        max_frequency = self.config.get("max_adaptations_per_hour", 6)
        window = timedelta(hours=1)

        timestamps = self._frequency_tracker.get(rule_id, [])
        timestamps = [t for t in timestamps if datetime.utcnow() - t < window]

        if len(timestamps) >= max_frequency:
            return False

        return True

    def _build_metrics(self, rule_id: str, data: Dict[str, Any]) -> PerformanceMetrics:
        """Build PerformanceMetrics from raw data dict."""
        return PerformanceMetrics(
            rule_id=rule_id,
            total_evaluations=data.get("total_evaluations", 0),
            true_positives=data.get("true_positives", 0),
            true_negatives=data.get("true_negatives", 0),
            false_positives=data.get("false_positives", 0),
            false_negatives=data.get("false_negatives", 0),
            avg_response_time_ms=data.get("avg_response_time_ms", 0.0),
            total_response_time_ms=data.get("total_response_time_ms", 0.0),
            cache_hit_rate=data.get("cache_hit_rate", 0.0),
            override_count=data.get("override_count", 0),
            user_satisfaction=data.get("user_satisfaction", 0.0),
        )

    def _record_adaptation(
        self,
        rule: Rule,
        adapted_rule: Rule,
        adaptation_type: AdaptationType,
        reason: str,
        metrics_before: Dict[str, Any],
        changes: Dict[str, Any],
    ) -> AdaptationRecord:
        """Record an adaptation event in history."""
        record = AdaptationRecord(
            adaptation_id=str(uuid.uuid4()),
            rule_id=rule.id,
            adaptation_type=adaptation_type,
            status=AdaptationStatus.APPLIED,
            previous_state=rule.model_dump() if hasattr(rule, "model_dump") else rule.dict(),
            new_state=adapted_rule.model_dump() if hasattr(adapted_rule, "model_dump") else adapted_rule.dict(),
            reason=reason,
            metrics_before=metrics_before,
            applied_at=datetime.utcnow(),
        )

        self._adaptation_history.append(record)
        self._current_adaptations[record.adaptation_id] = record
        self._snapshots[rule.id] = copy.deepcopy(rule)

        return record

    def _build_reason(self, metrics: PerformanceMetrics, changes: Dict[str, Any]) -> str:
        """Build a human-readable reason string for an adaptation."""
        parts: List[str] = []
        if "confidence_threshold" in changes:
            parts.append(f"threshold adjusted to {changes['confidence_threshold']:.2f}")
        if "priority" in changes:
            parts.append(f"priority adjusted to {changes['priority']}")
        parts.append(f"fpr={metrics.false_positive_rate:.3f}")
        parts.append(f"fnr={metrics.false_negative_rate:.3f}")
        return "; ".join(parts)

    def _last_adaptation_time(self) -> Optional[datetime]:
        """Get the timestamp of the most recent adaptation."""
        if not self._adaptation_history:
            return None
        return max(r.applied_at or r.created_at for r in self._adaptation_history)
