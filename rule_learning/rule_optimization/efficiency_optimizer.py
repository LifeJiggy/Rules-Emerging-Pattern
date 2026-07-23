"""
Efficiency optimizer for rule evaluation.

Measures and optimizes rule evaluation efficiency including redundant
evaluation detection, pattern matching optimization, evaluation batching,
and deduplication with config-driven parameters.
"""

import hashlib
import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from rules_emerging_pattern.models.rule import Rule, RuleSet, RuleEvaluationRequest, RuleType, RuleTier

logger = logging.getLogger(__name__)


class EfficiencyMetric(str, Enum):
    """Metrics tracked by the efficiency optimizer."""
    EVALUATION_COUNT = "evaluation_count"
    REDUNDANT_EVALUATIONS = "redundant_evaluations"
    AVERAGE_EVALUATION_TIME = "average_evaluation_time_ms"
    EARLY_TERMINATION_RATE = "early_termination_rate"
    BATCH_EFFICIENCY = "batch_efficiency"
    PRE_FILTER_RATE = "pre_filter_rate"
    CACHE_HIT_RATE = "cache_hit_rate"
    DEDUPLICATION_RATE = "deduplication_rate"
    PATTERN_COMPLEXITY_SCORE = "pattern_complexity_score"
    NGRAM_FILTER_EFFICIENCY = "ngram_filter_efficiency"
    TIME_SERIES_SCORE = "time_series_score"


class EfficiencyLevel(str, Enum):
    """Efficiency classification levels."""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class PatternComplexity(str, Enum):
    """Classification of pattern matching complexity."""
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


@dataclass
class EfficiencyConfig:
    """Configuration parameters for efficiency optimization."""
    redundancy_window_seconds: int = 300
    cache_enabled: bool = True
    max_cache_size: int = 10000
    early_termination_enabled: bool = True
    batch_size: int = 50
    max_batch_wait_ms: int = 100
    pre_filter_enabled: bool = True
    min_keyword_match_ratio: float = 0.1
    ngram_filter_enabled: bool = True
    ngram_size: int = 3
    ngram_match_threshold: float = 0.05
    efficiency_decay_days: int = 30
    max_redundant_evaluations_before_warn: int = 10
    scoring_window_size: int = 100
    report_max_worst_rules: int = 20
    time_series_window_minutes: int = 60
    complexity_optimization_enabled: bool = True
    auto_tune_enabled: bool = False
    auto_tune_interval_hours: int = 24
    max_patterns_per_rule_warn: int = 20
    max_keywords_per_pattern_warn: int = 50
    efficiency_history_archive_days: int = 90


@dataclass
class EfficiencyScore:
    """Efficiency score with breakdown."""
    overall: float
    time_efficiency: float
    redundancy_ratio: float
    cache_efficiency: float
    batch_efficiency: float
    pre_filter_efficiency: float
    ngram_efficiency: float
    complexity_score: float
    level: EfficiencyLevel

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": round(self.overall, 4),
            "time_efficiency": round(self.time_efficiency, 4),
            "redundancy_ratio": round(self.redundancy_ratio, 4),
            "cache_efficiency": round(self.cache_efficiency, 4),
            "batch_efficiency": round(self.batch_efficiency, 4),
            "pre_filter_efficiency": round(self.pre_filter_efficiency, 4),
            "ngram_efficiency": round(self.ngram_efficiency, 4),
            "complexity_score": round(self.complexity_score, 4),
            "level": self.level.value,
        }


@dataclass
class EvaluationRecord:
    """Record of a single rule evaluation."""
    rule_id: str
    content_hash: str
    execution_time_ms: float
    timestamp: datetime
    was_cached: bool
    was_redundant: bool
    was_pre_filtered: bool
    ngram_match_ratio: float = 0.0
    pattern_count: int = 0
    result: Optional[Any] = None


@dataclass
class TimeSeriesPoint:
    """A single point in the efficiency time series."""
    timestamp: datetime
    evaluation_count: int
    average_time_ms: float
    redundancy_rate: float
    cache_hit_rate: float


@dataclass
class PatternComplexityInfo:
    """Complexity information for a rule's patterns."""
    rule_id: str
    complexity: PatternComplexity
    pattern_count: int
    total_keywords: int
    total_regex: int
    has_ml_model: bool
    estimated_complexity_score: float
    optimization_suggestion: Optional[str] = None


class EfficiencyOptimizer:
    """Measures and optimizes rule evaluation efficiency.

    Tracks redundant evaluations, optimizes pattern matching through
    pre-filtering and early termination, batches and deduplicates
    evaluation requests, and produces efficiency scores and reports.
    Supports n-gram based pre-filtering, pattern complexity analysis,
    time-series trend tracking, and auto-tuning of configuration.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = EfficiencyConfig(**(config or {}))
        self.redundancy_tracker: Dict[str, EvaluationRecord] = {}
        self.evaluation_cache: Dict[str, Tuple[Any, datetime]] = {}
        self.efficiency_scores: Dict[str, float] = {}
        self.evaluation_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.config.scoring_window_size)
        )
        self.time_series: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )
        self.batch_queue: deque = deque(maxlen=10000)
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.pattern_complexity_cache: Dict[str, PatternComplexityInfo] = {}
        self.total_evaluations: int = 0
        self.redundant_count: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.batch_count: int = 0
        self.pre_filter_count: int = 0
        self.ngram_filter_count: int = 0
        self.early_termination_count: int = 0
        self._last_cache_cleanup: datetime = datetime.utcnow()
        self._last_auto_tune: Optional[datetime] = None

    def detect_redundant_evaluation(self, rule: Rule, content: str) -> Tuple[bool, Optional[EvaluationRecord]]:
        """Check if evaluating this rule on this content is redundant.

        Returns (is_redundant, existing_record).
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        key = self._make_redundancy_key(rule.id, content_hash)

        record = self.redundancy_tracker.get(key)
        if record is None:
            return False, None

        elapsed = (datetime.utcnow() - record.timestamp).total_seconds()
        if elapsed < self.config.redundancy_window_seconds:
            self.redundant_count += 1
            logger.debug("Redundant evaluation detected for rule %s on content %s", rule.id, content_hash[:8])
            return True, record

        return False, None

    def record_evaluation(
        self,
        rule: Rule,
        content: str,
        execution_time_ms: float,
        result: Optional[Any] = None,
        was_cached: bool = False,
        was_pre_filtered: bool = False,
        pattern_count: int = 0,
    ) -> None:
        """Record a rule evaluation for tracking and metrics."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        key = self._make_redundancy_key(rule.id, content_hash)
        was_redundant = key in self.redundancy_tracker

        ngram_ratio = self._compute_ngram_match_ratio(rule, content) if self.config.ngram_filter_enabled else 0.0

        record = EvaluationRecord(
            rule_id=rule.id,
            content_hash=content_hash,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.utcnow(),
            was_cached=was_cached,
            was_redundant=was_redundant,
            was_pre_filtered=was_pre_filtered,
            ngram_match_ratio=ngram_ratio,
            pattern_count=pattern_count or len(rule.patterns),
            result=result,
        )

        self.redundancy_tracker[key] = record
        self.evaluation_history[rule.id].append(record)
        self.total_evaluations += 1

        if was_cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

        self.metrics[EfficiencyMetric.EVALUATION_COUNT.value].append(1.0)
        self.metrics[EfficiencyMetric.AVERAGE_EVALUATION_TIME.value].append(execution_time_ms)

        self._update_time_series(rule.id)

        if self.config.auto_tune_enabled:
            self._check_auto_tune()

    def _update_time_series(self, rule_id: str) -> None:
        """Update the efficiency time series for a rule."""
        now = datetime.utcnow()
        series = self.time_series[rule_id]
        history = list(self.evaluation_history.get(rule_id, []))

        if not history:
            return

        recent = [r for r in history if (now - r.timestamp).total_seconds() < self.config.time_series_window_minutes * 60]
        if not recent:
            return

        point = TimeSeriesPoint(
            timestamp=now,
            evaluation_count=len(recent),
            average_time_ms=sum(r.execution_time_ms for r in recent) / len(recent),
            redundancy_rate=sum(1 for r in recent if r.was_redundant) / len(recent),
            cache_hit_rate=sum(1 for r in recent if r.was_cached) / len(recent),
        )
        series.append(point)

    def _compute_ngram_match_ratio(self, rule: Rule, content: str) -> float:
        """Compute the n-gram match ratio between rule keywords and content."""
        if not rule.patterns:
            return 0.0

        content_ngrams = self._extract_ngrams(content.lower())
        if not content_ngrams:
            return 0.0

        all_keywords: List[str] = []
        for pattern in rule.patterns:
            all_keywords.extend(kw.lower() for kw in pattern.keywords)

        if not all_keywords:
            return 0.0

        matched = sum(1 for kw in all_keywords if any(kw in ngram for ngram in content_ngrams))
        return matched / len(all_keywords)

    def _extract_ngrams(self, text: str) -> Set[str]:
        """Extract character n-grams from text."""
        n = self.config.ngram_size
        return {text[i:i + n] for i in range(len(text) - n + 1)}

    def _ngram_filter_rules(self, rules: List[Rule], content: str) -> Tuple[List[Rule], int]:
        """Filter rules using n-gram overlap with content."""
        if not self.config.ngram_filter_enabled:
            return rules, 0

        content_ngrams = self._extract_ngrams(content.lower())
        if not content_ngrams:
            return rules, 0

        filtered: List[Rule] = []
        filtered_count = 0

        for rule in rules:
            rule_ngrams: Set[str] = set()
            for pattern in rule.patterns:
                for kw in pattern.keywords:
                    rule_ngrams.update(self._extract_ngrams(kw.lower()))

            if not rule_ngrams:
                filtered.append(rule)
                continue

            overlap = len(content_ngrams & rule_ngrams) / len(rule_ngrams)
            if overlap >= self.config.ngram_match_threshold:
                filtered.append(rule)
            else:
                filtered_count += 1

        self.ngram_filter_count += filtered_count
        return filtered, filtered_count

    def optimize_pattern_matching(
        self,
        rules: List[Rule],
        content: str,
    ) -> Tuple[List[Rule], Dict[str, Any]]:
        """Optimize pattern matching via pre-filtering and prioritization.

        Applies keyword pre-filtering followed by n-gram filtering,
        then prioritizes by rule priority. Returns (optimized_rules, stats).
        """
        stats = {
            "total_rules": len(rules),
            "pre_filtered": 0,
            "ngram_filtered": 0,
            "early_terminated": False,
            "pre_filter_time_ms": 0.0,
        }

        start = time.perf_counter()

        if self.config.pre_filter_enabled:
            rules, pre_filtered_count = self._pre_filter_rules(rules, content)
            stats["pre_filtered"] = pre_filtered_count

        rules, ngram_filtered_count = self._ngram_filter_rules(rules, content)
        stats["ngram_filtered"] = ngram_filtered_count

        rules = self._prioritize_rules(rules)

        stats["pre_filter_time_ms"] = (time.perf_counter() - start) * 1000

        critical_rules = [r for r in rules if r.priority >= 900]
        if critical_rules and self.config.early_termination_enabled:
            stats["early_termination_possible"] = True
            logger.debug("Early termination possible: %d critical rules found", len(critical_rules))

        return rules, stats

    def _pre_filter_rules(self, rules: List[Rule], content: str) -> Tuple[List[Rule], int]:
        """Pre-filter rules based on keyword existence in content."""
        filtered: List[Rule] = []
        content_lower = content.lower()
        pre_filtered_count = 0

        for rule in rules:
            if not rule.patterns:
                filtered.append(rule)
                continue

            should_include = False
            total_keywords = 0
            matched_keywords = 0

            for pattern in rule.patterns:
                if not pattern.keywords:
                    should_include = True
                    break
                for kw in pattern.keywords:
                    total_keywords += 1
                    if kw.lower() in content_lower:
                        matched_keywords += 1

                if total_keywords > 0:
                    match_ratio = matched_keywords / total_keywords
                    if match_ratio >= self.config.min_keyword_match_ratio:
                        should_include = True
                        break

            if should_include:
                filtered.append(rule)
            else:
                pre_filtered_count += 1

        self.pre_filter_count += pre_filtered_count
        return filtered, pre_filtered_count

    def _prioritize_rules(self, rules: List[Rule]) -> List[Rule]:
        """Sort rules by priority descending for efficient evaluation."""
        return sorted(rules, key=lambda r: (r.priority, r.severity.value), reverse=True)

    def _make_redundancy_key(self, rule_id: str, content_hash: str) -> str:
        return f"{rule_id}:{content_hash}"

    def batch_evaluations(
        self,
        requests: List[RuleEvaluationRequest],
    ) -> Tuple[List[RuleEvaluationRequest], Dict[str, Any]]:
        """Batch and deduplicate evaluation requests.

        Groups identical content-tier combinations and merges rule IDs
        and options. Returns (deduplicated_requests, stats).
        """
        batch_map: Dict[str, RuleEvaluationRequest] = {}
        dedup_count = 0

        for req in requests:
            content_hash = hashlib.sha256(req.content.encode()).hexdigest()
            rule_ids_hash = (
                hashlib.md5(str(sorted(req.rule_ids or [])).encode()).hexdigest()
                if req.rule_ids else "none"
            )
            key = f"{content_hash}:{req.tier}:{rule_ids_hash}"

            if key not in batch_map:
                batch_map[key] = req
            else:
                existing = batch_map[key]
                if req.rule_ids and existing.rule_ids:
                    existing.rule_ids = list(set(existing.rule_ids + req.rule_ids))
                if req.options:
                    existing.options.update(req.options)
                dedup_count += 1

        result = list(batch_map.values())[:self.config.batch_size]
        self.batch_count += 1

        stats = {
            "total_requests": len(requests),
            "deduplicated": dedup_count,
            "batched_count": len(result),
            "savings_pct": round((1 - len(result) / max(len(requests), 1)) * 100, 2),
        }

        logger.debug(
            "Batch evaluation: %d requests deduplicated to %d (%.1f%% savings)",
            len(requests), len(result), stats["savings_pct"],
        )

        return result, stats

    def add_to_batch_queue(self, request: RuleEvaluationRequest) -> None:
        """Add a request to the batch queue for deferred processing."""
        self.batch_queue.append(request)

    def flush_batch_queue(self) -> List[RuleEvaluationRequest]:
        """Flush the batch queue and return accumulated requests."""
        requests = list(self.batch_queue)
        self.batch_queue.clear()
        return requests

    def use_cache(self, key: str) -> Tuple[bool, Optional[Any]]:
        """Check and retrieve a cached evaluation result.

        Returns (hit, cached_result).
        """
        if not self.config.cache_enabled:
            return False, None

        cached = self.evaluation_cache.get(key)
        if cached is None:
            self.cache_misses += 1
            return False, None

        result, expiry = cached
        if datetime.utcnow() > expiry:
            del self.evaluation_cache[key]
            self.cache_misses += 1
            return False, None

        self.cache_hits += 1
        return True, result

    def set_cache(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store a result in the evaluation cache."""
        if not self.config.cache_enabled:
            return

        if len(self.evaluation_cache) >= self.config.max_cache_size:
            self._evict_cache()

        expiry = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        self.evaluation_cache[key] = (value, expiry)

    def _evict_cache(self) -> None:
        """Evict oldest entries from cache when full."""
        if not self.evaluation_cache:
            return

        sorted_items = sorted(
            self.evaluation_cache.items(),
            key=lambda x: x[1][1],
        )
        evict_count = max(1, len(sorted_items) // 10)
        for key, _ in sorted_items[:evict_count]:
            del self.evaluation_cache[key]

        logger.debug("Evicted %d entries from evaluation cache", evict_count)

    def _cleanup_expired_cache(self) -> int:
        """Remove expired entries from cache. Returns count removed."""
        now = datetime.utcnow()
        expired_keys = [
            key for key, (_, expiry) in self.evaluation_cache.items()
            if now > expiry
        ]
        for key in expired_keys:
            del self.evaluation_cache[key]
        return len(expired_keys)

    def analyze_pattern_complexity(self, rule: Rule) -> PatternComplexityInfo:
        """Analyze and classify the complexity of a rule's patterns."""
        if rule.id in self.pattern_complexity_cache:
            return self.pattern_complexity_cache[rule.id]

        pattern_count = len(rule.patterns)
        total_keywords = sum(len(p.keywords) for p in rule.patterns)
        total_regex = sum(len(p.regex_patterns) for p in rule.patterns)
        has_ml = any(p.ml_model is not None for p in rule.patterns)

        score = 0.0
        score += min(1.0, pattern_count / self.config.max_patterns_per_rule_warn) * 0.3
        score += min(1.0, total_keywords / self.config.max_keywords_per_pattern_warn) * 0.3
        score += min(1.0, total_regex / 10) * 0.2
        score += 0.2 if has_ml else 0.0

        if score < 0.2:
            complexity = PatternComplexity.TRIVIAL
            suggestion = None
        elif score < 0.4:
            complexity = PatternComplexity.SIMPLE
            suggestion = None
        elif score < 0.6:
            complexity = PatternComplexity.MODERATE
            suggestion = "Consider consolidating similar patterns"
        elif score < 0.8:
            complexity = PatternComplexity.COMPLEX
            suggestion = "High pattern count may impact evaluation time"
        else:
            complexity = PatternComplexity.CRITICAL
            suggestion = "Critical complexity: split rule or reduce pattern count"

        info = PatternComplexityInfo(
            rule_id=rule.id,
            complexity=complexity,
            pattern_count=pattern_count,
            total_keywords=total_keywords,
            total_regex=total_regex,
            has_ml_model=has_ml,
            estimated_complexity_score=round(score, 4),
            optimization_suggestion=suggestion,
        )

        self.pattern_complexity_cache[rule.id] = info
        return info

    def score_efficiency(self, rule_id: str) -> EfficiencyScore:
        """Score the evaluation efficiency of a rule from 0.0 to 1.0."""
        history = list(self.evaluation_history.get(rule_id, []))
        if not history:
            return EfficiencyScore(
                overall=1.0, time_efficiency=1.0, redundancy_ratio=0.0,
                cache_efficiency=1.0, batch_efficiency=1.0,
                pre_filter_efficiency=1.0, ngram_efficiency=1.0,
                complexity_score=0.0, level=EfficiencyLevel.EXCELLENT,
            )

        total = len(history)
        if total == 0:
            return EfficiencyScore(
                overall=1.0, time_efficiency=1.0, redundancy_ratio=0.0,
                cache_efficiency=1.0, batch_efficiency=1.0,
                pre_filter_efficiency=1.0, ngram_efficiency=1.0,
                complexity_score=0.0, level=EfficiencyLevel.EXCELLENT,
            )

        avg_time = sum(r.execution_time_ms for r in history) / total
        redundant_ratio = sum(1 for r in history if r.was_redundant) / total
        cache_ratio = sum(1 for r in history if r.was_cached) / total
        pre_filter_ratio = sum(1 for r in history if r.was_pre_filtered) / total
        ngram_ratio = (
            sum(1 for r in history if r.ngram_match_ratio > 0) / total
            if total > 0 else 0.0
        )

        time_efficiency = max(0.0, 1.0 - (avg_time / 500.0))
        redundancy_penalty = redundant_ratio * 0.4
        cache_bonus = cache_ratio * 0.3
        pre_filter_bonus = pre_filter_ratio * 0.15
        ngram_bonus = ngram_ratio * 0.1

        overall = min(
            1.0,
            max(0.0, time_efficiency - redundancy_penalty + cache_bonus + pre_filter_bonus + ngram_bonus),
        )

        level = self._classify_efficiency(overall)
        self.efficiency_scores[rule_id] = overall

        return EfficiencyScore(
            overall=overall,
            time_efficiency=round(time_efficiency, 4),
            redundancy_ratio=round(redundant_ratio, 4),
            cache_efficiency=round(cache_ratio, 4),
            batch_efficiency=round(self._calculate_batch_efficiency(rule_id), 4),
            pre_filter_efficiency=round(pre_filter_ratio, 4),
            ngram_efficiency=round(ngram_ratio, 4),
            complexity_score=self._calculate_complexity_score(rule_id),
            level=level,
        )

    def _calculate_batch_efficiency(self, rule_id: str) -> float:
        """Calculate batch efficiency contribution for a rule."""
        return min(1.0, self.batch_count / max(self.total_evaluations, 1) * 10)

    def _calculate_complexity_score(self, rule_id: str) -> float:
        """Calculate the pattern complexity score for a rule."""
        info = self.pattern_complexity_cache.get(rule_id)
        if info is None:
            return 0.0
        return info.estimated_complexity_score

    def _classify_efficiency(self, score: float) -> EfficiencyLevel:
        """Classify an efficiency score into a level."""
        if score >= 0.8:
            return EfficiencyLevel.EXCELLENT
        if score >= 0.6:
            return EfficiencyLevel.GOOD
        if score >= 0.4:
            return EfficiencyLevel.FAIR
        if score >= 0.2:
            return EfficiencyLevel.POOR
        return EfficiencyLevel.CRITICAL

    def get_cache_hit_rate(self) -> float:
        """Get the overall cache hit rate."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    def get_redundancy_rate(self) -> float:
        """Get the rate of redundant evaluations."""
        if self.total_evaluations == 0:
            return 0.0
        return self.redundant_count / self.total_evaluations

    def get_time_series_trend(self, rule_id: str) -> Dict[str, Any]:
        """Get the efficiency trend from time series data for a rule."""
        series = list(self.time_series.get(rule_id, []))
        if len(series) < 2:
            return {"trend": "insufficient_data", "direction": "stable"}

        half = len(series) // 2
        early_avg = sum(p.average_time_ms for p in series[:half]) / half
        late_avg = sum(p.average_time_ms for p in series[half:]) / (len(series) - half)

        direction = "improving" if late_avg < early_avg else "degrading"
        change_pct = ((late_avg - early_avg) / max(early_avg, 0.001)) * 100

        return {
            "rule_id": rule_id,
            "data_points": len(series),
            "direction": direction,
            "change_pct": round(change_pct, 2),
            "early_avg_ms": round(early_avg, 2),
            "late_avg_ms": round(late_avg, 2),
        }

    def detect_efficiency_regression(self) -> List[Dict[str, Any]]:
        """Detect rules with significant efficiency regression."""
        regressions: List[Dict[str, Any]] = []

        for rule_id in self.evaluation_history:
            history = list(self.evaluation_history[rule_id])
            if len(history) < 20:
                continue

            half = len(history) // 2
            early_time = sum(r.execution_time_ms for r in history[:half]) / half
            late_time = sum(r.execution_time_ms for r in history[half:]) / (len(history) - half)

            if early_time > 0 and late_time > early_time * 1.5:
                regressions.append({
                    "rule_id": rule_id,
                    "previous_avg_ms": round(early_time, 2),
                    "current_avg_ms": round(late_time, 2),
                    "increase_pct": round(((late_time - early_time) / early_time) * 100, 2),
                    "timestamp": datetime.utcnow().isoformat(),
                })

        return sorted(regressions, key=lambda x: x["increase_pct"], reverse=True)

    def get_suggestions(self, rule_id: str) -> List[str]:
        """Generate efficiency improvement suggestions for a rule."""
        suggestions: List[str] = []
        score = self.score_efficiency(rule_id)

        if score.redundancy_ratio > 0.3:
            suggestions.append(
                f"High redundancy ratio ({score.redundancy_ratio:.1%}). "
                f"Increase cache TTL or batch evaluations."
            )

        if score.time_efficiency < 0.5:
            suggestions.append(
                f"Slow evaluation time. Consider pattern simplification or indexing."
            )

        if score.cache_efficiency < 0.3:
            suggestions.append(
                f"Low cache hit rate ({score.cache_efficiency:.1%}). "
                f"Review caching strategy or increase cache size."
            )

        if score.pre_filter_efficiency < 0.2:
            suggestions.append(
                f"Pre-filter rarely passes. Consider reviewing rule keywords."
            )

        if score.ngram_efficiency < 0.1 and self.config.ngram_filter_enabled:
            suggestions.append(
                f"N-gram filter has low overlap. Consider adjusting ngram_size or ngram_match_threshold."
            )

        trend = self.get_time_series_trend(rule_id)
        if trend.get("direction") == "degrading":
            suggestions.append(
                f"Efficiency degrading: {trend['change_pct']:.1f}%% increase in evaluation time. "
                f"Review recent rule changes."
            )

        complexity_info = self.pattern_complexity_cache.get(rule_id)
        if complexity_info and complexity_info.optimization_suggestion:
            suggestions.append(
                f"Pattern complexity: {complexity_info.complexity.value}. "
                f"{complexity_info.optimization_suggestion}"
            )

        return suggestions

    def _check_auto_tune(self) -> None:
        """Auto-tune configuration parameters based on observed metrics."""
        now = datetime.utcnow()
        if self._last_auto_tune and (
            now - self._last_auto_tune
        ).total_seconds() < self.config.auto_tune_interval_hours * 3600:
            return

        self._last_auto_tune = now
        hit_rate = self.get_cache_hit_rate()
        redundancy_rate = self.get_redundancy_rate()

        if hit_rate < 0.3 and self.config.max_cache_size < 50000:
            self.config.max_cache_size = min(100000, self.config.max_cache_size * 2)
            logger.info("Auto-tune: increased max_cache_size to %d", self.config.max_cache_size)

        if redundancy_rate > 0.4:
            self.config.redundancy_window_seconds = min(
                3600, self.config.redundancy_window_seconds * 2
            )
            logger.info("Auto-tune: increased redundancy_window to %ds", self.config.redundancy_window_seconds)

        if self.total_evaluations > 10000 and self.config.batch_size < 200:
            self.config.batch_size = min(500, self.config.batch_size * 2)
            logger.info("Auto-tune: increased batch_size to %d", self.config.batch_size)

    def generate_efficiency_report(self) -> Dict[str, Any]:
        """Generate a comprehensive efficiency report."""
        self._cleanup_expired_cache()

        scores = list(self.efficiency_scores.values())
        avg_score = sum(scores) / len(scores) if scores else 0.0

        classified: Dict[str, int] = {level.value: 0 for level in EfficiencyLevel}
        for sid in self.efficiency_scores:
            score_val = self.efficiency_scores[sid]
            level = self._classify_efficiency(score_val)
            classified[level.value] += 1

        worst_rules = sorted(
            self.efficiency_scores.items(),
            key=lambda x: x[1],
        )[:self.config.report_max_worst_rules]

        regressions = self.detect_efficiency_regression()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_rules_tracked": len(self.efficiency_scores),
            "total_evaluations": self.total_evaluations,
            "redundant_evaluations": self.redundant_count,
            "redundancy_rate": round(self.get_redundancy_rate(), 4),
            "cache_hit_rate": round(self.get_cache_hit_rate(), 4),
            "cache_size": len(self.evaluation_cache),
            "cache_cleanup_count": 0,
            "batch_count": self.batch_count,
            "pre_filter_count": self.pre_filter_count,
            "ngram_filter_count": self.ngram_filter_count,
            "early_termination_count": self.early_termination_count,
            "average_efficiency_score": round(avg_score, 4),
            "efficiency_distribution": classified,
            "worst_performing_rules": [
                {"rule_id": rid, "score": round(sc, 4)}
                for rid, sc in worst_rules
            ],
            "efficiency_regressions": regressions[:10],
            "suggestions": self._generate_global_suggestions(),
        }

    def _generate_global_suggestions(self) -> List[str]:
        """Generate global efficiency improvement suggestions."""
        suggestions: List[str] = []
        redundancy_rate = self.get_redundancy_rate()
        cache_hit_rate = self.get_cache_hit_rate()

        if redundancy_rate > 0.2:
            suggestions.append(
                f"Redundancy rate is {redundancy_rate:.1%}. "
                f"Increase redundancy_window_seconds or enable batching."
            )

        if cache_hit_rate < 0.5:
            suggestions.append(
                f"Cache hit rate is {cache_hit_rate:.1%}. "
                f"Increase max_cache_size or review cache TTLs."
            )

        if self.total_evaluations > 1000 and self.batch_count == 0:
            suggestions.append(
                "Batching not utilized. Enable batch_evaluations for high-throughput scenarios."
            )

        if self.config.ngram_filter_enabled and self.ngram_filter_count == 0 and self.total_evaluations > 100:
            suggestions.append(
                "N-gram filter has not filtered any rules. Consider adjusting ngram_match_threshold."
            )

        return suggestions

    def reset_metrics(self) -> None:
        """Reset all accumulated metrics."""
        self.redundancy_tracker.clear()
        self.evaluation_cache.clear()
        self.efficiency_scores.clear()
        self.evaluation_history.clear()
        self.time_series.clear()
        self.batch_queue.clear()
        self.metrics.clear()
        self.pattern_complexity_cache.clear()
        self.total_evaluations = 0
        self.redundant_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.batch_count = 0
        self.pre_filter_count = 0
        self.ngram_filter_count = 0
        self.early_termination_count = 0
        self._last_cache_cleanup = datetime.utcnow()
        self._last_auto_tune = None
        logger.info("Efficiency optimizer metrics reset")

    def purge_rule(self, rule_id: str) -> bool:
        """Remove all tracking data for a specific rule. Returns True if found."""
        found = False
        keys_to_delete = [
            key for key in self.redundancy_tracker
            if key.startswith(f"{rule_id}:")
        ]
        for key in keys_to_delete:
            del self.redundancy_tracker[key]
            found = True

        if rule_id in self.evaluation_history:
            del self.evaluation_history[rule_id]
            found = True

        if rule_id in self.time_series:
            del self.time_series[rule_id]
            found = True

        if rule_id in self.efficiency_scores:
            del self.efficiency_scores[rule_id]
            found = True

        if rule_id in self.pattern_complexity_cache:
            del self.pattern_complexity_cache[rule_id]
            found = True

        return found
