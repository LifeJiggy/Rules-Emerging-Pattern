"""Compare system configurations, rule sets, and resolution strategies side-by-side."""
import logging
import math
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ComparisonMetric:
    name: str
    system_a_value: float
    system_b_value: float
    delta: float
    percent_change: float
    winner: str
    significance: float = 0.0


@dataclass
class SystemComparisonResult:
    system_a_name: str
    system_b_name: str
    metrics: List[ComparisonMetric]
    overall_winner: str
    confidence: float
    compared_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SystemComparison:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._results: List[SystemComparisonResult] = []
        self._significance_threshold = self.config.get("significance_threshold", 0.05)
        logger.info("SystemComparison initialized (significance=%.2f)", self._significance_threshold)

    def compare_systems(
        self,
        system_a: Dict[str, Any],
        system_b: Dict[str, Any],
        metrics_def: Optional[Dict[str, str]] = None
    ) -> SystemComparisonResult:
        name_a = system_a.get("name", "System A")
        name_b = system_b.get("name", "System B")
        data_a = system_a.get("metrics", {})
        data_b = system_b.get("metrics", {})

        if metrics_def is None:
            metrics_def = {
                k: "higher" if data_a.get(k, 0) > data_b.get(k, 0) else "lower"
                for k in set(list(data_a.keys()) + list(data_b.keys()))
            }

        metrics: List[ComparisonMetric] = []
        wins_a = 0
        wins_b = 0
        total_comparable = 0

        for metric_name, direction in metrics_def.items():
            val_a = data_a.get(metric_name, 0)
            val_b = data_b.get(metric_name, 0)

            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                val_a_f = float(val_a)
                val_b_f = float(val_b)

                delta = val_a_f - val_b_f
                percent_change = (
                    (delta / abs(val_b_f)) * 100 if abs(val_b_f) > 1e-10
                    else float("inf") if delta != 0
                    else 0.0
                )

                if direction == "higher":
                    winner = name_a if val_a_f > val_b_f else name_b
                elif direction == "lower":
                    winner = name_a if val_a_f < val_b_f else name_b
                else:
                    winner = name_a if abs(val_a_f - val_b_f) < 1e-10 else (
                        name_a if val_a_f > val_b_f else name_b
                    )

                if winner == name_a:
                    wins_a += 1
                elif winner == name_b:
                    wins_b += 1
                total_comparable += 1

                significance = self._compute_significance(val_a_f, val_b_f, direction)

                metrics.append(ComparisonMetric(
                    name=metric_name,
                    system_a_value=val_a_f,
                    system_b_value=val_b_f,
                    delta=round(delta, 4),
                    percent_change=round(percent_change, 2),
                    winner=winner,
                    significance=significance,
                ))

        overall_winner = name_a if wins_a > wins_b else (
            name_b if wins_b > wins_a else "Tie"
        )
        confidence = (
            max(wins_a, wins_b) / max(total_comparable, 1)
            if total_comparable > 0 else 0.0
        )

        result = SystemComparisonResult(
            system_a_name=name_a,
            system_b_name=name_b,
            metrics=metrics,
            overall_winner=overall_winner,
            confidence=round(confidence, 4),
        )

        self._results.append(result)
        logger.info(
            "Comparison '%s' vs '%s': winner=%s confidence=%.2f%% (metrics=%d)",
            name_a, name_b, overall_winner, confidence * 100, len(metrics)
        )
        return result

    def compare_with_baseline(
        self,
        current: Dict[str, Any],
        baseline: Dict[str, Any],
        improvement_threshold: float = 0.1
    ) -> SystemComparisonResult:
        result = self.compare_systems(baseline, current)
        improvements = [
            m for m in result.metrics
            if m.winner == result.system_b_name and abs(m.percent_change) > improvement_threshold * 100
        ]
        regressions = [
            m for m in result.metrics
            if m.winner == result.system_a_name and abs(m.percent_change) > improvement_threshold * 100
        ]

        logger.info(
            "Baseline comparison: %d improvements, %d regressions",
            len(improvements), len(regressions)
        )
        return result

    def multi_system_comparison(
        self,
        systems: List[Dict[str, Any]],
        metrics_def: Optional[Dict[str, str]] = None
    ) -> Dict[str, SystemComparisonResult]:
        results: Dict[str, SystemComparisonResult] = {}
        for i in range(len(systems)):
            for j in range(i + 1, len(systems)):
                key = f"{systems[i].get('name', i)}_vs_{systems[j].get('name', j)}"
                results[key] = self.compare_systems(systems[i], systems[j], metrics_def)
        return results

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_comparisons": len(self._results),
            "results": [
                {
                    "systems": f"{r.system_a_name} vs {r.system_b_name}",
                    "winner": r.overall_winner,
                    "confidence": r.confidence,
                }
                for r in self._results
            ],
        }

    def _compute_significance(
        self,
        val_a: float,
        val_b: float,
        direction: str
    ) -> float:
        if abs(val_a) < 1e-10 and abs(val_b) < 1e-10:
            return 0.0

        diff = abs(val_a - val_b)
        magnitude = max(abs(val_a), abs(val_b), 1e-10)
        ratio = diff / magnitude

        if direction == "higher":
            return min(1.0, ratio * 2)
        elif direction == "lower":
            return min(1.0, ratio * 2)
        return min(1.0, ratio)
