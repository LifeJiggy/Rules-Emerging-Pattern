"""Benchmark conflict resolution strategies for latency, throughput, and accuracy."""
import logging
import time
import statistics
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ResolutionBenchmarkResult:
    strategy_name: str
    num_conflicts: int
    total_duration_ms: float
    avg_duration_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_per_sec: float
    success_count: int
    error_count: int
    accuracy: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BenchmarkScenario:
    name: str
    rules: List[Dict[str, Any]]
    expected_winner: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ConflictResolutionBenchmark:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._results: List[ResolutionBenchmarkResult] = []
        self._warmup_iterations = self.config.get("warmup_iterations", 10)
        self._benchmark_iterations = self.config.get("benchmark_iterations", 1000)
        self._timeout_ms = self.config.get("timeout_ms", 5000)
        logger.info("ConflictResolutionBenchmark initialized (warmup=%d, iterations=%d)",
                     self._warmup_iterations, self._benchmark_iterations)

    def benchmark_resolution(
        self,
        resolver_fn: Callable,
        scenarios: List[BenchmarkScenario],
        strategy_name: str = "unknown",
    ) -> ResolutionBenchmarkResult:
        self._warmup(resolver_fn, scenarios)

        durations: List[float] = []
        success_count = 0
        error_count = 0

        for scenario in scenarios:
            for _ in range(self._benchmark_iterations // max(len(scenarios), 1)):
                try:
                    start = time.perf_counter()

                    if scenario.context is not None:
                        result = resolver_fn(
                            scenario.rules[0], scenario.rules[1], scenario.context
                        )
                    else:
                        result = resolver_fn(
                            scenario.rules[0], scenario.rules[1]
                        )

                    elapsed = (time.perf_counter() - start) * 1000
                    durations.append(elapsed)

                    if elapsed > self._timeout_ms:
                        error_count += 1
                    else:
                        success_count += 1

                except Exception as e:
                    error_count += 1
                    logger.debug("Benchmark error: %s", e)

        if not durations:
            return ResolutionBenchmarkResult(
                strategy_name=strategy_name,
                num_conflicts=0,
                total_duration_ms=0,
                avg_duration_ms=0,
                p50_ms=0,
                p95_ms=0,
                p99_ms=0,
                throughput_per_sec=0,
                success_count=0,
                error_count=error_count,
            )

        sorted_durations = sorted(durations)
        total = sum(durations)
        avg = statistics.mean(durations)
        p50 = sorted_durations[len(sorted_durations) // 2]
        p95 = sorted_durations[int(len(sorted_durations) * 0.95)]
        p99 = sorted_durations[int(len(sorted_durations) * 0.99)]
        throughput = success_count / (total / 1000) if total > 0 else 0

        result = ResolutionBenchmarkResult(
            strategy_name=strategy_name,
            num_conflicts=len(durations),
            total_duration_ms=total,
            avg_duration_ms=round(avg, 3),
            p50_ms=round(p50, 3),
            p95_ms=round(p95, 3),
            p99_ms=round(p99, 3),
            throughput_per_sec=round(throughput, 1),
            success_count=success_count,
            error_count=error_count,
            accuracy=self._calculate_accuracy(resolver_fn, scenarios),
        )

        self._results.append(result)
        logger.info(
            "Benchmark '%s': avg=%.3fms p50=%.3fms p95=%.3fms throughput=%.1f/s accuracy=%.2f%%",
            strategy_name, avg, p50, p95, throughput, result.accuracy * 100
        )
        return result

    def compare_strategies(
        self,
        strategies: Dict[str, Callable],
        scenarios: List[BenchmarkScenario]
    ) -> Dict[str, ResolutionBenchmarkResult]:
        results: Dict[str, ResolutionBenchmarkResult] = {}
        for name, fn in strategies.items():
            results[name] = self.benchmark_resolution(fn, scenarios, strategy_name=name)
        return results

    def get_best_strategy(self) -> Optional[str]:
        if not self._results:
            return None
        return max(self._results, key=lambda r: r.throughput_per_sec).strategy_name

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_benchmarks": len(self._results),
            "best_throughput": max(r.throughput_per_sec for r in self._results) if self._results else 0,
            "best_avg_latency": min(r.avg_duration_ms for r in self._results) if self._results else 0,
            "results_by_strategy": {
                r.strategy_name: {
                    "avg_ms": r.avg_duration_ms,
                    "p95_ms": r.p95_ms,
                    "throughput": r.throughput_per_sec,
                    "accuracy": r.accuracy,
                }
                for r in self._results
            },
        }

    def _warmup(self, resolver_fn: Callable, scenarios: List[BenchmarkScenario]) -> None:
        for _ in range(self._warmup_iterations):
            for scenario in scenarios[:3]:
                try:
                    if scenario.context is not None:
                        resolver_fn(scenario.rules[0], scenario.rules[1], scenario.context)
                    else:
                        resolver_fn(scenario.rules[0], scenario.rules[1])
                except Exception:
                    pass
        logger.debug("Warmup complete (%d iterations)", self._warmup_iterations)

    def _calculate_accuracy(
        self,
        resolver_fn: Callable,
        scenarios: List[BenchmarkScenario]
    ) -> float:
        correct = 0
        total = 0

        for scenario in scenarios:
            if scenario.expected_winner is None:
                continue
            total += 1
            try:
                if scenario.context is not None:
                    result = resolver_fn(
                        scenario.rules[0], scenario.rules[1], scenario.context
                    )
                else:
                    result = resolver_fn(scenario.rules[0], scenario.rules[1])

                winner_id = getattr(result, "winning_rule_id", None)
                if winner_id == scenario.expected_winner:
                    correct += 1
            except Exception:
                pass

        return correct / total if total > 0 else 0.0
