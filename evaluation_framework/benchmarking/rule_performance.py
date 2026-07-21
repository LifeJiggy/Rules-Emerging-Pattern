"""Benchmark individual rule evaluation performance - latency, memory, cache metrics."""
import logging
import time
import statistics
import tracemalloc
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class RulePerformanceResult:
    rule_id: str
    rule_name: str
    tier: str
    avg_eval_time_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_per_sec: float
    memory_peak_bytes: int
    memory_avg_bytes: int
    cache_hit_rate: float
    batch_throughput: float
    error_rate: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RulePerformance:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._results: Dict[str, RulePerformanceResult] = {}
        self._benchmark_iterations = self.config.get("benchmark_iterations", 500)
        self._warmup_iterations = self.config.get("warmup_iterations", 5)
        self._batch_sizes = self.config.get("batch_sizes", [1, 10, 50, 100])
        self._memory_tracking = self.config.get("memory_tracking", True)
        logger.info("RulePerformance initialized (iterations=%d, memory=%s)",
                     self._benchmark_iterations, self._memory_tracking)

    def benchmark_rule(
        self,
        rule: Dict[str, Any],
        eval_fn: Callable[[Dict[str, Any]], Any],
        content_samples: List[str],
    ) -> RulePerformanceResult:
        self._warmup(eval_fn, content_samples)

        durations: List[float] = []
        errors = 0

        for content in content_samples:
            for _ in range(self._benchmark_iterations // max(len(content_samples), 1)):
                try:
                    start = time.perf_counter()
                    eval_fn({"content": content, "rule": rule})
                    elapsed = (time.perf_counter() - start) * 1000
                    durations.append(elapsed)
                except Exception as e:
                    errors += 1
                    logger.debug("Eval error for rule %s: %s", rule.get("id"), e)

        if not durations:
            return self._empty_result(rule)

        sorted_durations = sorted(durations)
        avg = statistics.mean(durations)
        p50 = sorted_durations[len(sorted_durations) // 2]
        p95 = sorted_durations[int(len(sorted_durations) * 0.95)]
        p99 = sorted_durations[int(len(sorted_durations) * 0.99)]
        total_sec = sum(durations) / 1000
        throughput = len(durations) / total_sec if total_sec > 0 else 0

        mem_peak, mem_avg = self._measure_memory(eval_fn, content_samples)

        batch_tp = self._measure_batch_throughput(eval_fn, content_samples)
        cache_rate = self._measure_cache_hit_rate(eval_fn, content_samples)

        result = RulePerformanceResult(
            rule_id=rule.get("id", "unknown"),
            rule_name=rule.get("name", "unknown"),
            tier=rule.get("tier", "preference"),
            avg_eval_time_ms=round(avg, 4),
            p50_ms=round(p50, 4),
            p95_ms=round(p95, 4),
            p99_ms=round(p99, 4),
            throughput_per_sec=round(throughput, 1),
            memory_peak_bytes=mem_peak,
            memory_avg_bytes=mem_avg,
            cache_hit_rate=cache_rate,
            batch_throughput=round(batch_tp, 1),
            error_rate=errors / max(len(durations), 1),
        )

        self._results[rule.get("id", "unknown")] = result
        logger.info(
            "Rule %s [%s]: avg=%.4fms p95=%.4fms throughput=%.1f/s mem_peak=%d cache=%.1f%%",
            rule.get("name"), rule.get("tier"), avg, p95, throughput, mem_peak, cache_rate * 100
        )
        return result

    def benchmark_rules_batch(
        self,
        rules: List[Dict[str, Any]],
        eval_fn: Callable[[Dict[str, Any]], Any],
        content_samples: List[str]
    ) -> Dict[str, RulePerformanceResult]:
        results: Dict[str, RulePerformanceResult] = {}
        for rule in rules:
            rid = rule.get("id", "unknown")
            results[rid] = self.benchmark_rule(rule, eval_fn, content_samples)
        return results

    def get_summary(self) -> Dict[str, Any]:
        if not self._results:
            return {"total_rules": 0}

        by_tier: Dict[str, List[float]] = {}
        for r in self._results.values():
            by_tier.setdefault(r.tier, []).append(r.avg_eval_time_ms)

        results_list = list(self._results.values())
        avg_all = statistics.mean([r.avg_eval_time_ms for r in results_list])

        return {
            "total_rules": len(self._results),
            "overall_avg_ms": round(avg_all, 4),
            "avg_by_tier": {
                tier: round(statistics.mean(times), 4)
                for tier, times in by_tier.items()
            },
            "fastest_rule": min(results_list, key=lambda r: r.avg_eval_time_ms).rule_name,
            "slowest_rule": max(results_list, key=lambda r: r.avg_eval_time_ms).rule_name,
            "total_throughput": sum(r.throughput_per_sec for r in results_list),
        }

    def _warmup(self, eval_fn: Callable, samples: List[str]) -> None:
        for content in samples[:self._warmup_iterations]:
            try:
                eval_fn({"content": content, "rule": {}})
            except Exception:
                pass

    def _measure_memory(
        self,
        eval_fn: Callable,
        samples: List[str]
    ) -> tuple[int, int]:
        if not self._memory_tracking:
            return 0, 0

        tracemalloc.start()
        peaks: List[int] = []

        for content in samples[:50]:
            before = tracemalloc.get_traced_memory()
            try:
                eval_fn({"content": content, "rule": {}})
            except Exception:
                pass
            after = tracemalloc.get_traced_memory()
            peaks.append(after[0] - before[0])

        tracemalloc.stop()

        if not peaks:
            return 0, 0
        return max(peaks), int(statistics.mean(peaks))

    def _measure_batch_throughput(
        self,
        eval_fn: Callable,
        samples: List[str]
    ) -> float:
        batch_size = max(self._batch_sizes)
        batch = samples[:batch_size]

        start = time.perf_counter()
        for content in batch:
            try:
                eval_fn({"content": content, "rule": {}})
            except Exception:
                pass
        elapsed = time.perf_counter() - start

        return len(batch) / elapsed if elapsed > 0 else 0

    def _measure_cache_hit_rate(
        self,
        eval_fn: Callable,
        samples: List[str]
    ) -> float:
        if len(samples) < 2:
            return 0.0

        repeats = min(10, len(samples))
        hits = 0
        total = 0

        for content in samples[:repeats]:
            try:
                eval_fn({"content": content, "rule": {}})
                total += 1
                eval_fn({"content": content, "rule": {}})
                hits += 1
            except Exception:
                pass

        return hits / max(total, 1) if total > 0 else 0.0

    def _empty_result(self, rule: Dict[str, Any]) -> RulePerformanceResult:
        return RulePerformanceResult(
            rule_id=rule.get("id", "unknown"),
            rule_name=rule.get("name", "unknown"),
            tier=rule.get("tier", "preference"),
            avg_eval_time_ms=0,
            p50_ms=0, p95_ms=0, p99_ms=0,
            throughput_per_sec=0,
            memory_peak_bytes=0,
            memory_avg_bytes=0,
            cache_hit_rate=0,
            batch_throughput=0,
            error_rate=1.0,
        )
