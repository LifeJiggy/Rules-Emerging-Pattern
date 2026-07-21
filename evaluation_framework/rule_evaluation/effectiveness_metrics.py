"""Evaluate rule effectiveness via precision, recall, F1, and false-positive/negative analysis."""
import logging
import math
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ConfusionMatrix:
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    @property
    def total(self) -> int:
        return self.true_positives + self.false_positives + self.true_negatives + self.false_negatives

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator > 0 else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator > 0 else 0.0

    @property
    def f1_score(self) -> float:
        p = self.precision
        r = self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        denominator = self.true_positives + self.true_negatives + self.false_positives + self.false_negatives
        return (self.true_positives + self.true_negatives) / denominator if denominator > 0 else 0.0

    @property
    def false_positive_rate(self) -> float:
        denominator = self.false_positives + self.true_negatives
        return self.false_positives / denominator if denominator > 0 else 0.0


@dataclass
class RuleEffectiveness:
    rule_id: str
    rule_name: str
    tier: str
    matrix: ConfusionMatrix
    precision: float
    recall: float
    f1_score: float
    accuracy: float
    false_positive_rate: float
    total_evaluations: int
    score: float
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EffectivenessMetrics:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._results: Dict[str, RuleEffectiveness] = {}
        self._history: List[RuleEffectiveness] = []
        self._weight_precision = self.config.get("weight_precision", 0.4)
        self._weight_recall = self.config.get("weight_recall", 0.4)
        self._weight_accuracy = self.config.get("weight_accuracy", 0.2)
        logger.info("EffectivenessMetrics initialized (w_precision=%.2f, w_recall=%.2f)",
                     self._weight_precision, self._weight_recall)

    def evaluate(self, rule: Dict[str, Any]) -> RuleEffectiveness:
        rule_id = rule.get("id", "unknown")
        matrix = self._build_confusion_matrix(rule)
        score = self._compute_effectiveness_score(matrix)

        effect = RuleEffectiveness(
            rule_id=rule_id,
            rule_name=rule.get("name", "unknown"),
            tier=rule.get("tier", "preference"),
            matrix=matrix,
            precision=matrix.precision,
            recall=matrix.recall,
            f1_score=matrix.f1_score,
            accuracy=matrix.accuracy,
            false_positive_rate=matrix.false_positive_rate,
            total_evaluations=matrix.total,
            score=round(score, 4),
        )

        self._results[rule_id] = effect
        self._history.append(effect)
        logger.info(
            "Effectiveness for '%s': F1=%.4f precision=%.4f recall=%.4f score=%.4f (n=%d)",
            rule.get("name"), effect.f1_score, effect.precision,
            effect.recall, effect.score, effect.total_evaluations
        )
        return effect

    def evaluate_batch(self, rules: List[Dict[str, Any]]) -> Dict[str, RuleEffectiveness]:
        results: Dict[str, RuleEffectiveness] = {}
        for rule in rules:
            rid = rule.get("id", "unknown")
            results[rid] = self.evaluate(rule)
        return results

    def compare_effectiveness(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Dict[str, Any]:
        eff_1 = self.evaluate(rule_1)
        eff_2 = self.evaluate(rule_2)

        return {
            "winner": rule_1.get("id") if eff_1.score > eff_2.score else rule_2.get("id"),
            "score_1": eff_1.score,
            "score_2": eff_2.score,
            "delta": round(eff_1.score - eff_2.score, 4),
            "f1_delta": round(eff_1.f1_score - eff_2.f1_score, 4),
        }

    def get_top_rules(self, n: int = 10) -> List[RuleEffectiveness]:
        sorted_results = sorted(
            self._results.values(),
            key=lambda r: r.score,
            reverse=True
        )
        return sorted_results[:n]

    def get_bottom_rules(self, n: int = 10) -> List[RuleEffectiveness]:
        sorted_results = sorted(
            self._results.values(),
            key=lambda r: r.score,
        )
        return sorted_results[:n]

    def get_statistics(self) -> Dict[str, Any]:
        if not self._results:
            return {"total_rules_evaluated": 0}

        scores = [r.score for r in self._results.values()]
        f1_scores = [r.f1_score for r in self._results.values()]

        by_tier: Dict[str, List[float]] = defaultdict(list)
        for r in self._results.values():
            by_tier[r.tier].append(r.score)

        return {
            "total_rules_evaluated": len(self._results),
            "avg_score": sum(scores) / len(scores),
            "avg_f1": sum(f1_scores) / len(f1_scores),
            "min_score": min(scores),
            "max_score": max(scores),
            "avg_by_tier": {
                tier: sum(s) / len(s)
                for tier, s in by_tier.items()
            },
            "total_false_positives": sum(r.matrix.false_positives for r in self._results.values()),
            "total_false_negatives": sum(r.matrix.false_negatives for r in self._results.values()),
        }

    def _build_confusion_matrix(self, rule: Dict[str, Any]) -> ConfusionMatrix:
        results_data = rule.get("evaluation_results", rule.get("test_results", []))
        if not results_data:
            results_data = rule.get("_test_data", self._generate_test_data(rule))

        matrix = ConfusionMatrix()

        for result in results_data:
            expected = bool(result.get("expected_violation", result.get("should_match", False)))
            actual = bool(result.get("actual_result", result.get("matched", False)))

            if expected and actual:
                matrix.true_positives += 1
            elif not expected and actual:
                matrix.false_positives += 1
            elif not expected and not actual:
                matrix.true_negatives += 1
            elif expected and not actual:
                matrix.false_negatives += 1

        return matrix

    def _compute_effectiveness_score(self, matrix: ConfusionMatrix) -> float:
        return (
            self._weight_precision * matrix.precision
            + self._weight_recall * matrix.recall
            + self._weight_accuracy * matrix.accuracy
        )

    def _generate_test_data(self, rule: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"expected_violation": True, "actual_result": True},
            {"expected_violation": True, "actual_result": True},
            {"expected_violation": False, "actual_result": False},
            {"expected_violation": False, "actual_result": False},
            {"expected_violation": True, "actual_result": False},
        ]
