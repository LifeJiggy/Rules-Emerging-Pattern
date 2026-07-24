"""
Result aggregator for combining multiple evaluation results.
"""

import asyncio
import hashlib
import json
import logging
import time
import traceback
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import (
    ActionTaken,
    Suggestion,
    ValidationResult,
    Violation,
    ViolationType,
)
from rules_emerging_pattern.models.conflict import (
    ConflictResolution,
    ConflictType,
    ResolutionStrategy,
    RuleConflict,
)

from .engine_config import EngineConfig

logger = logging.getLogger(__name__)


class AggregationStrategy(str, Enum):
    """Strategies for aggregating multiple evaluation results."""
    WEIGHTED = "weighted"
    MINIMUM = "min"
    MAXIMUM = "max"
    AVERAGE = "average"
    CONSENSUS = "consensus"
    SUM = "sum"
    MEDIAN = "median"
    CUSTOM = "custom"


class AggregationScope(str, Enum):
    """Scope of aggregation operation."""
    FULL = "full"
    VIOLATIONS_ONLY = "violations_only"
    SCORES_ONLY = "scores_only"
    METADATA_ONLY = "metadata_only"


class DeduplicationStrategy(str, Enum):
    """Strategies for deduplicating results."""
    EXACT_MATCH = "exact_match"
    CONTENT_HASH = "content_hash"
    VIOLATION_HASH = "violation_hash"
    SEMANTIC = "semantic"
    RULE_ID_ONLY = "rule_id_only"


class AggregationError(Exception):
    """Raised when aggregation fails."""
    pass


@dataclass
class AggregationConfig:
    """Configuration for aggregation behavior."""

    strategy: AggregationStrategy = AggregationStrategy.WEIGHTED
    scope: AggregationScope = AggregationScope.FULL
    deduplication: DeduplicationStrategy = DeduplicationStrategy.VIOLATION_HASH
    confidence_threshold: float = 0.5
    weight_by_confidence: bool = True
    weight_by_tier: bool = True
    max_violations: int = 1000
    include_warnings: bool = True
    include_suggestions: bool = True
    include_critical_only: bool = False
    flatten_results: bool = True
    merge_metadata: bool = True
    cache_results: bool = True
    cache_ttl: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "scope": self.scope.value,
            "deduplication": self.deduplication.value,
            "confidence_threshold": self.confidence_threshold,
            "weight_by_confidence": self.weight_by_confidence,
            "weight_by_tier": self.weight_by_tier,
            "max_violations": self.max_violations,
            "include_warnings": self.include_warnings,
            "include_suggestions": self.include_suggestions,
            "include_critical_only": self.include_critical_only,
            "flatten_results": self.flatten_results,
            "merge_metadata": self.merge_metadata,
            "cache_results": self.cache_results,
            "cache_ttl": self.cache_ttl,
        }


@dataclass
class AggregatedResult:
    """Result of aggregating multiple evaluation results."""

    valid: bool
    total_score: float
    confidence: float
    total_rules_evaluated: int = 0
    rules_triggered: int = 0
    rules_violated: int = 0
    violations: List[Violation] = field(default_factory=list)
    critical_violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)
    suggestions: List[Suggestion] = field(default_factory=list)
    processing_time_ms: int = 0
    rules_by_tier: Dict[str, int] = field(default_factory=dict)
    aggregation_details: Dict[str, Any] = field(default_factory=dict)
    source_count: int = 1
    source_results: List[ValidationResult] = field(default_factory=list)
    aggregation_id: str = ""
    aggregated_at: datetime = field(default_factory=datetime.utcnow)

    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def has_critical_violations(self) -> bool:
        return len(self.critical_violations) > 0

    def is_blocked(self) -> bool:
        return any(v.blocked for v in self.violations)

    def get_violations_by_tier(self) -> Dict[str, List[Violation]]:
        result: Dict[str, List[Violation]] = defaultdict(list)
        for v in self.violations:
            result[v.rule_tier.value if hasattr(v.rule_tier, "value") else str(v.rule_tier)].append(v)
        return dict(result)

    def get_violations_by_severity(self) -> Dict[str, List[Violation]]:
        result: Dict[str, List[Violation]] = defaultdict(list)
        for v in self.violations:
            sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
            result[sev].append(v)
        return dict(result)

    def get_summary(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "blocked": self.is_blocked(),
            "total_score": round(self.total_score, 3),
            "confidence": round(self.confidence, 3),
            "violations": len(self.violations),
            "critical_violations": len(self.critical_violations),
            "warnings": len(self.warnings),
            "suggestions": len(self.suggestions),
            "rules_evaluated": self.total_rules_evaluated,
            "rules_triggered": self.rules_triggered,
            "source_count": self.source_count,
            "processing_time_ms": self.processing_time_ms,
            "aggregation_id": self.aggregation_id,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "total_score": self.total_score,
            "confidence": self.confidence,
            "total_rules_evaluated": self.total_rules_evaluated,
            "rules_triggered": self.rules_triggered,
            "rules_violated": self.rules_violated,
            "violations": [v.to_summary() for v in self.violations],
            "critical_violations": [v.to_summary() for v in self.critical_violations],
            "warnings": [v.to_summary() for v in self.warnings],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "processing_time_ms": self.processing_time_ms,
            "rules_by_tier": self.rules_by_tier,
            "aggregation_details": self.aggregation_details,
            "source_count": self.source_count,
            "aggregation_id": self.aggregation_id,
        }


@dataclass
class AggregationMetrics:
    """Metrics for aggregation operations."""

    total_aggregations: int = 0
    total_results_processed: int = 0
    total_violations_deduped: int = 0
    total_conflicts_resolved: int = 0
    average_aggregation_time_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    start_time: float = field(default_factory=time.time)

    def record_aggregation(self, duration_ms: float, result_count: int, deduped: int = 0) -> None:
        self.total_aggregations += 1
        self.total_results_processed += result_count
        self.total_violations_deduped += deduped
        total_time = self.average_aggregation_time_ms * (self.total_aggregations - 1)
        self.average_aggregation_time_ms = (total_time + duration_ms) / self.total_aggregations

    def to_dict(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        return {
            "total_aggregations": self.total_aggregations,
            "total_results_processed": self.total_results_processed,
            "total_violations_deduped": self.total_violations_deduped,
            "total_conflicts_resolved": self.total_conflicts_resolved,
            "average_aggregation_time_ms": round(self.average_aggregation_time_ms, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "uptime_seconds": round(uptime, 1),
        }


class WeightedScorer:
    """Computes weighted scores from multiple evaluation results."""

    def __init__(self, config: Optional[AggregationConfig] = None):
        self.config = config or AggregationConfig()
        self.tier_weights: Dict[str, float] = {
            "safety": 1.0,
            "operational": 0.7,
            "preference": 0.4,
        }
        self.severity_penalties: Dict[str, float] = {
            "critical": 0.5,
            "high": 0.3,
            "medium": 0.15,
            "low": 0.05,
        }

    def set_tier_weight(self, tier: str, weight: float) -> None:
        self.tier_weights[tier] = weight

    def set_severity_penalty(self, severity: str, penalty: float) -> None:
        self.severity_penalties[severity] = penalty

    def weighted_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        total_weight = 0.0
        weighted_sum = 0.0
        for result in results:
            weight = self._compute_result_weight(result)
            weighted_sum += (result.total_score or 1.0) * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else 1.0

    def weighted_confidence(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        confidences = [r.confidence for r in results if r is not None]
        if not confidences:
            return 1.0
        return sum(confidences) / len(confidences)

    def _compute_result_weight(self, result: ValidationResult) -> float:
        weight = 1.0
        if self.config.weight_by_confidence:
            weight *= result.confidence if result.confidence else 0.5
        if self.config.weight_by_tier:
            tier_counts = result.rules_by_tier
            for tier_str, count in tier_counts.items():
                tier_weight = self.tier_weights.get(tier_str, 0.5)
                weight *= (tier_weight ** (1.0 / max(count, 1)))
        return max(weight, 0.1)

    def score_breakdown(self, results: List[ValidationResult]) -> Dict[str, Any]:
        individual_scores = []
        for i, r in enumerate(results):
            individual_scores.append({
                "index": i,
                "score": r.total_score,
                "confidence": r.confidence,
                "weight": self._compute_result_weight(r),
                "violations": len(r.violations),
                "valid": r.valid,
            })
        final_score = self.weighted_score(results)
        final_confidence = self.weighted_confidence(results)
        tier_penalties: Dict[str, float] = {}
        severity_penalties: Dict[str, float] = {}
        for result in results:
            for v in result.violations:
                tier = v.rule_tier.value if hasattr(v.rule_tier, "value") else "unknown"
                sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else "unknown"
                tier_penalties[tier] = tier_penalties.get(tier, 0) + self.tier_weights.get(tier, 0.5) * 0.1
                severity_penalties[sev] = severity_penalties.get(sev, 0) + self.severity_penalties.get(sev, 0.1)
        return {
            "strategy": self.config.strategy.value,
            "final_score": round(final_score, 3),
            "final_confidence": round(final_confidence, 3),
            "individual_scores": individual_scores,
            "tier_penalties": {k: round(v, 3) for k, v in tier_penalties.items()},
            "severity_penalties": {k: round(v, 3) for k, v in severity_penalties.items()},
        }

    def minimum_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        return min(r.total_score if r.total_score is not None else 1.0 for r in results)

    def maximum_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        return max(r.total_score if r.total_score is not None else 1.0 for r in results)

    def average_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        scores = [r.total_score if r.total_score is not None else 1.0 for r in results]
        return sum(scores) / len(scores)

    def median_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        scores = sorted(r.total_score if r.total_score is not None else 1.0 for r in results)
        n = len(scores)
        if n % 2 == 0:
            return (scores[n // 2 - 1] + scores[n // 2]) / 2
        return scores[n // 2]

    def consensus_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        valid_count = sum(1 for r in results if r.valid)
        return valid_count / len(results)

    def sum_score(self, results: List[ValidationResult]) -> float:
        if not results:
            return 1.0
        total = sum(r.total_score if r.total_score is not None else 1.0 for r in results)
        return min(total, 1.0)


class ConflictAwareMerger:
    """Merges results with conflict detection and resolution."""

    def __init__(self):
        self._conflict_handlers: Dict[str, Callable] = {}
        self._resolved_conflicts: List[Dict[str, Any]] = []

    def add_conflict_handler(self, conflict_type: str, handler: Callable) -> None:
        self._conflict_handlers[conflict_type] = handler

    def merge_violations(self, violations: List[Violation]) -> List[Violation]:
        if not violations:
            return []
        merged: Dict[str, Violation] = {}
        for v in violations:
            key = self._violation_key(v)
            if key in merged:
                existing = merged[key]
                if v.confidence_score > existing.confidence_score:
                    merged[key] = v
                elif v.blocked and not existing.blocked:
                    merged[key] = v
            else:
                merged[key] = v
        return list(merged.values())

    def resolve_tier_conflict(self, v1: Violation, v2: Violation) -> Violation:
        tier_order = {"safety": 0, "operational": 1, "preference": 2}
        t1 = v1.rule_tier.value if hasattr(v1.rule_tier, "value") else "preference"
        t2 = v2.rule_tier.value if hasattr(v2.rule_tier, "value") else "preference"
        return v1 if tier_order.get(t1, 2) <= tier_order.get(t2, 2) else v2

    def resolve_severity_conflict(self, v1: Violation, v2: Violation) -> Violation:
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        s1 = v1.rule_severity.value if hasattr(v1.rule_severity, "value") else "low"
        s2 = v2.rule_severity.value if hasattr(v2.rule_severity, "value") else "low"
        return v1 if sev_order.get(s1, 3) <= sev_order.get(s2, 3) else v2

    def get_resolved_conflicts(self) -> List[Dict[str, Any]]:
        return self._resolved_conflicts

    @staticmethod
    def _violation_key(v: Violation) -> str:
        vid = v.rule_id
        vtype = v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type)
        content = v.matched_content or ""
        return f"{vid}:{vtype}:{content}"


class ResultCache:
    """Cache for aggregated results."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, Tuple[AggregatedResult, float]] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0

    def get(self, key: str) -> Optional[AggregatedResult]:
        if key in self._cache:
            result, expiry = self._cache[key]
            if time.time() < expiry:
                self._cache.move_to_end(key)
                self._hits += 1
                return result
            else:
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, result: AggregatedResult, ttl: Optional[int] = None) -> None:
        expiry = time.time() + (ttl or self.default_ttl)
        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (result, expiry)
        self._cache.move_to_end(key)

    def invalidate(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(total, 1) * 100, 2),
            "default_ttl": self.default_ttl,
        }


class ResultAggregator:
    """Aggregates results from multiple evaluations with weighted scoring and conflict resolution."""

    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        self._aggregation_config = AggregationConfig(
            strategy=AggregationStrategy(
                self.config.get("aggregator.strategy", "weighted")
            ),
            deduplication=DeduplicationStrategy.VIOLATION_HASH,
            confidence_threshold=self.config.get_float("aggregator.confidence_threshold", 0.5),
            cache_results=self.config.get_bool("aggregator.cache_results", True),
            cache_ttl=self.config.get_int("aggregator.cache_ttl", 300),
        )
        self._scorer = WeightedScorer(self._aggregation_config)
        self._merger = ConflictAwareMerger()
        self._cache = ResultCache(
            max_size=self.config.get_int("engine.cache_size", 1000),
            default_ttl=self._aggregation_config.cache_ttl,
        )
        self._metrics = AggregationMetrics()
        self._aggregation_hooks: List[Callable] = []
        self._strategy_handlers: Dict[AggregationStrategy, Callable] = {}
        self._register_default_handlers()

        logger.info(
            f"ResultAggregator initialized with strategy={self._aggregation_config.strategy.value}"
        )

    def _register_default_handlers(self) -> None:
        self._strategy_handlers[AggregationStrategy.WEIGHTED] = self._aggregate_weighted
        self._strategy_handlers[AggregationStrategy.MINIMUM] = self._aggregate_minimum
        self._strategy_handlers[AggregationStrategy.MAXIMUM] = self._aggregate_maximum
        self._strategy_handlers[AggregationStrategy.AVERAGE] = self._aggregate_average
        self._strategy_handlers[AggregationStrategy.CONSENSUS] = self._aggregate_consensus
        self._strategy_handlers[AggregationStrategy.SUM] = self._aggregate_sum
        self._strategy_handlers[AggregationStrategy.MEDIAN] = self._aggregate_median

    def register_strategy_handler(
        self, strategy: AggregationStrategy, handler: Callable
    ) -> None:
        self._strategy_handlers[strategy] = handler

    def add_aggregation_hook(self, hook: Callable[[AggregatedResult], AggregatedResult]) -> None:
        self._aggregation_hooks.append(hook)

    def set_strategy(self, strategy: AggregationStrategy) -> None:
        self._aggregation_config.strategy = strategy
        logger.info(f"Aggregation strategy set to {strategy.value}")

    def set_confidence_threshold(self, threshold: float) -> None:
        self._aggregation_config.confidence_threshold = max(0.0, min(1.0, threshold))

    def set_tier_weight(self, tier: str, weight: float) -> None:
        self._scorer.set_tier_weight(tier, weight)

    def set_severity_penalty(self, severity: str, penalty: float) -> None:
        self._scorer.set_severity_penalty(severity, penalty)

    def aggregate(self, results: List[ValidationResult]) -> AggregatedResult:
        if not results:
            return AggregatedResult(valid=True, total_score=1.0, confidence=1.0)

        start_time = time.time()

        cache_key = self._compute_cache_key(results)
        if self._aggregation_config.cache_results and cache_key:
            cached = self._cache.get(cache_key)
            if cached:
                self._metrics.cache_hits += 1
                return cached
            self._metrics.cache_misses += 1

        filtered = self._filter_results(results)
        deduped_count = 0
        if self._aggregation_config.deduplicate:
            filtered, deduped_count = self._deduplicate_results(filtered)

        handler = self._strategy_handlers.get(self._aggregation_config.strategy)
        if handler:
            aggregated = handler(filtered)
        else:
            aggregated = self._aggregate_weighted(filtered)

        aggregated.source_count = len(filtered)
        aggregated.source_results = filtered
        aggregated.aggregation_id = self._generate_aggregation_id()

        all_violations = []
        for r in filtered:
            all_violations.extend(r.violations)
        all_violations = self._merger.merge_violations(all_violations)

        if self._aggregation_config.include_critical_only:
            all_violations = [v for v in all_violations if v.is_critical()]

        if len(all_violations) > self._aggregation_config.max_violations:
            all_violations = sorted(
                all_violations,
                key=lambda v: (
                    v.rule_severity.value if hasattr(v.rule_severity, "value") else "",
                    v.confidence_score,
                ),
                reverse=True,
            )[:self._aggregation_config.max_violations]

        aggregated.violations = all_violations
        aggregated.critical_violations = [v for v in all_violations if v.is_critical()]
        aggregated.warnings = [v for v in all_violations if v.action_taken == ActionTaken.WARNING]

        if self._aggregation_config.include_suggestions:
            all_suggestions = []
            for r in filtered:
                all_suggestions.extend(r.suggestions)
            aggregated.suggestions = all_suggestions

        aggregated.processing_time_ms = int(
            sum(r.processing_time_ms for r in filtered if r.processing_time_ms)
        )

        tier_counts: Dict[str, int] = {}
        for r in filtered:
            for tier_key, count in r.rules_by_tier.items():
                tier_counts[tier_key] = tier_counts.get(tier_key, 0) + count
        aggregated.rules_by_tier = tier_counts

        aggregated.total_rules_evaluated = max(
            r.total_rules_evaluated for r in filtered
        ) if filtered else 0
        aggregated.rules_triggered = len(all_violations)
        aggregated.rules_violated = len(
            [v for v in all_violations if v.action_taken != ActionTaken.NONE]
        )

        aggregated.aggregation_details = {
            "strategy": self._aggregation_config.strategy.value,
            "source_count": len(filtered),
            "deduped_violations": deduped_count,
            "confidence_threshold": self._aggregation_config.confidence_threshold,
        }

        for hook in self._aggregation_hooks:
            try:
                aggregated = hook(aggregated)
            except Exception as e:
                logger.error(f"Aggregation hook failed: {e}")

        duration_ms = (time.time() - start_time) * 1000
        self._metrics.record_aggregation(duration_ms, len(filtered), deduped_count)

        if self._aggregation_config.cache_results and cache_key:
            self._cache.set(cache_key, aggregated)

        return aggregated

    async def aggregate_async(self, results: List[ValidationResult]) -> AggregatedResult:
        return await asyncio.get_event_loop().run_in_executor(None, self.aggregate, results)

    def _filter_results(self, results: List[ValidationResult]) -> List[ValidationResult]:
        if not self._aggregation_config.include_critical_only:
            return results
        return [
            r for r in results
            if any(v.is_critical() for v in r.violations) or not r.valid
        ]

    def _deduplicate_results(self, results: List[ValidationResult]) -> Tuple[List[ValidationResult], int]:
        seen_hashes: Set[str] = set()
        deduped: List[ValidationResult] = []
        total_deduped = 0
        for result in results:
            result_hash = self._result_hash(result)
            if result_hash not in seen_hashes:
                seen_hashes.add(result_hash)
                deduped.append(result)
            else:
                total_deduped += 1
        return deduped, total_deduped

    def _aggregate_weighted(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.weighted_score(results)
        confidence = self._scorer.weighted_confidence(results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_minimum(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.minimum_score(results)
        confidence = min(r.confidence for r in results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_maximum(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.maximum_score(results)
        confidence = max(r.confidence for r in results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_average(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.average_score(results)
        confidence = self._scorer.weighted_confidence(results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_consensus(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.consensus_score(results)
        confidence = self._scorer.weighted_confidence(results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_sum(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.sum_score(results)
        confidence = self._scorer.weighted_confidence(results)
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def _aggregate_median(self, results: List[ValidationResult]) -> AggregatedResult:
        score = self._scorer.median_score(results)
        confidences = sorted(r.confidence for r in results)
        n = len(confidences)
        if n % 2 == 0:
            confidence = (confidences[n // 2 - 1] + confidences[n // 2]) / 2
        else:
            confidence = confidences[n // 2]
        valid = score >= self._aggregation_config.confidence_threshold
        return AggregatedResult(valid=valid, total_score=score, confidence=confidence)

    def aggregate_by_tier(self, results: List[ValidationResult]) -> Dict[str, AggregatedResult]:
        by_tier: Dict[str, List[ValidationResult]] = defaultdict(list)
        for result in results:
            tiers = result.rules_by_tier or {"unknown": len(result.violations)}
            for tier_key in tiers:
                by_tier[tier_key].append(result)
        return {
            tier: self.aggregate(tier_results)
            for tier, tier_results in by_tier.items()
        }

    def aggregate_by_severity(self, results: List[ValidationResult]) -> Dict[str, AggregatedResult]:
        by_severity: Dict[str, List[ValidationResult]] = defaultdict(list)
        for result in results:
            key = "critical" if result.has_critical_violations() else "normal"
            by_severity[key].append(result)
        return {
            key: self.aggregate(group)
            for key, group in by_severity.items()
        }

    def merge_aggregated(self, aggregated_results: List[AggregatedResult]) -> AggregatedResult:
        if not aggregated_results:
            return AggregatedResult(valid=True, total_score=1.0, confidence=1.0)
        all_violations = []
        all_suggestions = []
        total_score = 1.0
        total_confidence = 0.0
        total_rules = 0
        total_sources = 0
        for ar in aggregated_results:
            all_violations.extend(ar.violations)
            all_suggestions.extend(ar.suggestions)
            total_score = min(total_score, ar.total_score)
            total_confidence += ar.confidence
            total_rules = max(total_rules, ar.total_rules_evaluated)
            total_sources += ar.source_count
        merged = AggregatedResult(
            valid=total_score >= self._aggregation_config.confidence_threshold,
            total_score=total_score,
            confidence=total_confidence / len(aggregated_results),
            total_rules_evaluated=total_rules,
            violations=all_violations,
            critical_violations=[v for v in all_violations if v.is_critical()],
            warnings=[v for v in all_violations if v.action_taken == ActionTaken.WARNING],
            suggestions=all_suggestions,
            source_count=total_sources,
        )
        return merged

    def generate_summary(self, results: List[ValidationResult]) -> Dict[str, Any]:
        aggregated = self.aggregate(results)
        score_breakdown = self._scorer.score_breakdown(results)
        tier_distribution: Dict[str, int] = {}
        severity_distribution: Dict[str, int] = {}
        for r in results:
            for v in r.violations:
                tier = v.rule_tier.value if hasattr(v.rule_tier, "value") else "unknown"
                sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else "unknown"
                tier_distribution[tier] = tier_distribution.get(tier, 0) + 1
                severity_distribution[sev] = severity_distribution.get(sev, 0) + 1
        return {
            "aggregated": aggregated.get_summary(),
            "score_breakdown": score_breakdown,
            "tier_distribution": tier_distribution,
            "severity_distribution": severity_distribution,
            "total_results": len(results),
            "total_violations": aggregated.rules_triggered,
            "total_critical": len(aggregated.critical_violations),
            "is_blocked": aggregated.is_blocked(),
            "processing_time_ms": aggregated.processing_time_ms,
        }

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Aggregation cache cleared")

    def get_cache_info(self) -> Dict[str, Any]:
        return self._cache.get_stats()

    def get_metrics(self) -> Dict[str, Any]:
        return self._metrics.to_dict()

    def get_config(self) -> Dict[str, Any]:
        return self._aggregation_config.to_dict()

    def get_conflict_log(self) -> List[Dict[str, Any]]:
        return self._merger.get_resolved_conflicts()

    async def health_check(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "aggregator": "ResultAggregator",
            "strategy": self._aggregation_config.strategy.value,
            "cache_size": len(self._cache._cache),
            "cache_hits": self._metrics.cache_hits,
            "cache_misses": self._metrics.cache_misses,
            "total_aggregations": self._metrics.total_aggregations,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def to_prometheus(self) -> str:
        metrics = self._metrics
        lines = [
            "# HELP result_aggregator_total Total aggregations",
            "# TYPE result_aggregator_total counter",
            f"result_aggregator_total {metrics.total_aggregations}",
            "# HELP result_aggregator_results_processed Total results processed",
            "# TYPE result_aggregator_results_processed counter",
            f"result_aggregator_results_processed {metrics.total_results_processed}",
            "# HELP result_aggregator_violations_deduped Deduplicated violations",
            "# TYPE result_aggregator_violations_deduped counter",
            f"result_aggregator_violations_deduped {metrics.total_violations_deduped}",
            "# HELP result_aggregator_cache_hits Cache hits",
            "# TYPE result_aggregator_cache_hits counter",
            f"result_aggregator_cache_hits {metrics.cache_hits}",
            "# HELP result_aggregator_cache_misses Cache misses",
            "# TYPE result_aggregator_cache_misses counter",
            f"result_aggregator_cache_misses {metrics.cache_misses}",
            "# HELP result_aggregator_average_time_ms Average aggregation time",
            "# TYPE result_aggregator_average_time_ms gauge",
            f"result_aggregator_average_time_ms {metrics.average_aggregation_time_ms}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _compute_cache_key(results: List[ValidationResult]) -> str:
        if not results:
            return ""
        content = "|".join(
            f"{r.content_hash}:{r.processing_time_ms}:{len(r.violations)}"
            for r in results[:10]
        )
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    @staticmethod
    def _result_hash(result: ValidationResult) -> str:
        vhashes = "|".join(
            v.get_violation_hash() for v in result.violations[:10]
        ) if result.violations else "no_violations"
        content = f"{result.valid}:{result.total_score}:{vhashes}:{result.processing_time_ms}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    @staticmethod
    def _generate_aggregation_id() -> str:
        return f"agg_{int(time.time() * 1000)}_{hash(time.time()) % 10000}"
