"""Analyze business and operational impact of rule enforcement - costs, benefits, risks."""
import logging
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ImpactDimension:
    name: str
    score: float
    weight: float
    description: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleImpact:
    rule_id: str
    rule_name: str
    tier: str
    overall_impact_score: float
    dimensions: List[ImpactDimension]
    risk_level: str
    cost_estimate: Dict[str, float]
    benefit_estimate: Dict[str, float]
    net_benefit: float
    recommendations: List[str]
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ImpactAnalysis:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._results: Dict[str, RuleImpact] = {}
        self._dimension_weights: Dict[str, float] = {
            "performance": self.config.get("weight_performance", 0.25),
            "user_experience": self.config.get("weight_user_experience", 0.20),
            "compliance": self.config.get("weight_compliance", 0.30),
            "operational_cost": self.config.get("weight_operational_cost", 0.15),
            "maintainability": self.config.get("weight_maintainability", 0.10),
        }
        self._risk_bounds = self.config.get("risk_bounds", {
            "low": 0.7,
            "medium": 0.4,
            "high": 0.0,
        })
        logger.info("ImpactAnalysis initialized (dimensions=%s)", list(self._dimension_weights.keys()))

    def analyze_impact(
        self,
        rule: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> RuleImpact:
        ctx = context or {}
        dimensions: List[ImpactDimension] = []

        perf_impact = self._analyze_performance_impact(rule, ctx)
        dimensions.append(perf_impact)

        ux_impact = self._analyze_user_experience_impact(rule, ctx)
        dimensions.append(ux_impact)

        compliance_impact = self._analyze_compliance_impact(rule, ctx)
        dimensions.append(compliance_impact)

        cost_impact = self._analyze_operational_cost_impact(rule, ctx)
        dimensions.append(cost_impact)

        maint_impact = self._analyze_maintainability_impact(rule, ctx)
        dimensions.append(maint_impact)

        overall = sum(d.score * d.weight for d in dimensions)
        risk_level = self._determine_risk_level(overall)

        cost_est = self._estimate_costs(rule, dimensions)
        benefit_est = self._estimate_benefits(rule, dimensions)
        net = benefit_est.get("total", 0) - cost_est.get("total", 0)

        recommendations = self._generate_recommendations(dimensions, overall, risk_level)

        result = RuleImpact(
            rule_id=rule.get("id", "unknown"),
            rule_name=rule.get("name", "unknown"),
            tier=rule.get("tier", "preference"),
            overall_impact_score=round(overall, 4),
            dimensions=dimensions,
            risk_level=risk_level,
            cost_estimate=cost_est,
            benefit_estimate=benefit_est,
            net_benefit=round(net, 2),
            recommendations=recommendations,
        )

        self._results[rule.get("id", "unknown")] = result
        logger.info(
            "Impact analysis for '%s': score=%.4f risk=%s net_benefit=%.2f",
            rule.get("name"), overall, risk_level, net
        )
        return result

    def analyze_many(
        self,
        rules: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, RuleImpact]:
        results: Dict[str, RuleImpact] = {}
        for rule in rules:
            rid = rule.get("id", "unknown")
            results[rid] = self.analyze_impact(rule, context)
        return results

    def compare_impact(
        self,
        rule_a: Dict[str, Any],
        rule_b: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        impact_a = self.analyze_impact(rule_a, context)
        impact_b = self.analyze_impact(rule_b, context)

        return {
            "better_option": rule_a.get("id") if impact_a.overall_impact_score > impact_b.overall_impact_score
                else rule_b.get("id"),
            "impact_a": impact_a.overall_impact_score,
            "impact_b": impact_b.overall_impact_score,
            "delta": round(impact_a.overall_impact_score - impact_b.overall_impact_score, 4),
            "net_benefit_a": impact_a.net_benefit,
            "net_benefit_b": impact_b.net_benefit,
        }

    def get_statistics(self) -> Dict[str, Any]:
        if not self._results:
            return {"total_analyzed": 0}

        scores = [r.overall_impact_score for r in self._results.values()]
        net_benefits = [r.net_benefit for r in self._results.values()]

        risk_counts: Dict[str, int] = defaultdict(int)
        for r in self._results.values():
            risk_counts[r.risk_level] += 1

        return {
            "total_analyzed": len(self._results),
            "avg_impact_score": sum(scores) / len(scores),
            "avg_net_benefit": sum(net_benefits) / len(net_benefits),
            "risk_distribution": dict(risk_counts),
            "highest_impact": max(self._results.values(), key=lambda r: r.overall_impact_score).rule_name,
            "lowest_impact": min(self._results.values(), key=lambda r: r.overall_impact_score).rule_name,
        }

    def _analyze_performance_impact(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ImpactDimension:
        latency = float(rule.get("avg_latency_ms", context.get("expected_latency_ms", 10)))
        frequency = float(rule.get("eval_frequency", context.get("frequency", 100)))

        if latency > 100:
            perf_score = 0.2
        elif latency > 50:
            perf_score = 0.4
        elif latency > 10:
            perf_score = 0.6
        else:
            perf_score = 0.9

        perf_score *= min(1.0, 1000.0 / max(frequency, 1))

        return ImpactDimension(
            name="performance",
            score=round(perf_score, 4),
            weight=self._dimension_weights.get("performance", 0.25),
            description=f"Performance impact: latency={latency}ms, frequency={frequency}/s",
            details={"latency_ms": latency, "frequency_per_sec": frequency},
        )

    def _analyze_user_experience_impact(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ImpactDimension:
        enforcement = rule.get("enforcement", "advisory")
        false_positive_rate = float(rule.get("false_positive_rate", context.get("expected_fp_rate", 0.05)))

        if enforcement == "strict":
            ux_score = 0.5
        elif enforcement == "advisory":
            ux_score = 0.8
        else:
            ux_score = 0.9

        ux_score *= max(0, 1.0 - false_positive_rate * 5)

        return ImpactDimension(
            name="user_experience",
            score=round(ux_score, 4),
            weight=self._dimension_weights.get("user_experience", 0.20),
            description=f"UX impact: enforcement={enforcement}, fp_rate={false_positive_rate:.2%}",
            details={"enforcement": enforcement, "false_positive_rate": false_positive_rate},
        )

    def _analyze_compliance_impact(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ImpactDimension:
        tier = rule.get("tier", "preference")
        severity = rule.get("severity", "low")

        if tier == "safety":
            comp_score = 0.95
        elif tier == "operational":
            comp_score = 0.75
        else:
            comp_score = 0.50

        if severity == "critical":
            comp_score = min(1.0, comp_score + 0.3)
        elif severity == "high":
            comp_score = min(1.0, comp_score + 0.15)

        return ImpactDimension(
            name="compliance",
            score=round(comp_score, 4),
            weight=self._dimension_weights.get("compliance", 0.30),
            description=f"Compliance impact: tier={tier}, severity={severity}",
            details={"tier": tier, "severity": severity},
        )

    def _analyze_operational_cost_impact(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ImpactDimension:
        complexity = len(rule.get("patterns", [])) + len(rule.get("conditions", []))
        eval_count = int(rule.get("eval_count", context.get("daily_evaluations", 1000)))

        cost_score = max(0, 1.0 - (complexity * 0.05) - (eval_count * 0.00001))
        cost_score = max(0.1, min(1.0, cost_score))

        return ImpactDimension(
            name="operational_cost",
            score=round(cost_score, 4),
            weight=self._dimension_weights.get("operational_cost", 0.15),
            description=f"Cost impact: complexity={complexity}, evals/day={eval_count}",
            details={"pattern_count": complexity, "daily_evals": eval_count},
        )

    def _analyze_maintainability_impact(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ImpactDimension:
        has_docs = bool(rule.get("description")) and bool(rule.get("name"))
        has_tests = bool(rule.get("test_results"))
        is_simple = len(rule.get("patterns", [])) <= 3

        maint_score = 0.3
        if has_docs:
            maint_score += 0.3
        if has_tests:
            maint_score += 0.2
        if is_simple:
            maint_score += 0.2

        return ImpactDimension(
            name="maintainability",
            score=round(maint_score, 4),
            weight=self._dimension_weights.get("maintainability", 0.10),
            description=f"Maintainability: documented={has_docs}, tested={has_tests}, simple={is_simple}",
            details={"has_documentation": has_docs, "has_tests": has_tests, "is_simple": is_simple},
        )

    def _estimate_costs(
        self,
        rule: Dict[str, Any],
        dimensions: List[ImpactDimension]
    ) -> Dict[str, float]:
        base_cost = 100.0
        perf_dim = next((d for d in dimensions if d.name == "performance"), None)
        maint_dim = next((d for d in dimensions if d.name == "maintainability"), None)

        perf_cost = base_cost * (1 - (perf_dim.score if perf_dim else 0.5))
        maint_cost = base_cost * (1 - (maint_dim.score if maint_dim else 0.5))

        return {
            "performance": round(perf_cost, 2),
            "maintenance": round(maint_cost, 2),
            "infrastructure": round(base_cost * 0.5, 2),
            "total": round(perf_cost + maint_cost + base_cost * 0.5, 2),
        }

    def _estimate_benefits(
        self,
        rule: Dict[str, Any],
        dimensions: List[ImpactDimension]
    ) -> Dict[str, float]:
        base_benefit = 100.0
        comp_dim = next((d for d in dimensions if d.name == "compliance"), None)
        ux_dim = next((d for d in dimensions if d.name == "user_experience"), None)

        comp_benefit = base_benefit * (comp_dim.score if comp_dim else 0.5) * 2
        ux_benefit = base_benefit * (ux_dim.score if ux_dim else 0.5)

        return {
            "compliance": round(comp_benefit, 2),
            "user_experience": round(ux_benefit, 2),
            "risk_mitigation": round(base_benefit * 1.5, 2),
            "total": round(comp_benefit + ux_benefit + base_benefit * 1.5, 2),
        }

    def _determine_risk_level(self, score: float) -> str:
        if score >= self._risk_bounds.get("low", 0.7):
            return "low"
        elif score >= self._risk_bounds.get("medium", 0.4):
            return "medium"
        return "high"

    def _generate_recommendations(
        self,
        dimensions: List[ImpactDimension],
        overall: float,
        risk_level: str
    ) -> List[str]:
        recommendations: List[str] = []

        if risk_level == "high":
            recommendations.append("URGENT: Review rule implementation - high risk impact detected")

        for dim in dimensions:
            if dim.score < 0.4:
                recommendations.append(
                    f"Improve {dim.name}: current score {dim.score:.2f} (weight {dim.weight:.0%})"
                )

        perf_dim = next((d for d in dimensions if d.name == "performance"), None)
        if perf_dim and perf_dim.score < 0.3:
            recommendations.append("Optimize rule evaluation - consider caching or pre-compilation")

        comp_dim = next((d for d in dimensions if d.name == "compliance"), None)
        if comp_dim and comp_dim.score < 0.6:
            recommendations.append(f"Review compliance posture - consider upgrading to stricter tier")

        if not recommendations:
            recommendations.append("Rule is well-balanced, no immediate action required")

        return recommendations
