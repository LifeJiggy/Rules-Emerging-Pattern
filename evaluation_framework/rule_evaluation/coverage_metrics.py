"""Calculate rule coverage across content types, domains, and scenarios."""
import logging
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class CoverageDetail:
    category: str
    total_items: int
    covered_items: int
    coverage_pct: float
    uncovered_items: List[str] = field(default_factory=list)


@dataclass
class CoverageResult:
    overall_coverage_pct: float
    total_rules: int
    total_scenarios: int
    by_tier: Dict[str, CoverageDetail]
    by_domain: Dict[str, CoverageDetail]
    by_content_type: Dict[str, CoverageDetail]
    gaps: List[Dict[str, Any]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CoverageMetrics:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._min_coverage_threshold = self.config.get("min_coverage_threshold", 0.8)
        self._results: List[CoverageResult] = []
        self._coverage_data: Dict[str, Any] = {}
        logger.info("CoverageMetrics initialized (min_coverage=%.0f%%)",
                     self._min_coverage_threshold * 100)

    def calculate_coverage(
        self,
        rules: List[Dict[str, Any]],
        scenarios: List[Dict[str, Any]]
    ) -> CoverageResult:
        by_tier = self._compute_tier_coverage(rules, scenarios)
        by_domain = self._compute_domain_coverage(rules, scenarios)
        by_content_type = self._compute_content_type_coverage(rules, scenarios)

        total_items = len(scenarios)
        total_covered = sum(
            detail.covered_items
            for detail in list(by_tier.values()) + list(by_domain.values()) + list(by_content_type.values())
        )
        total_possible = sum(
            detail.total_items
            for detail in list(by_tier.values()) + list(by_domain.values()) + list(by_content_type.values())
        )
        overall = total_covered / max(total_possible, 1)

        gaps = self._identify_gaps(by_tier, by_domain, by_content_type)

        result = CoverageResult(
            overall_coverage_pct=round(overall * 100, 2),
            total_rules=len(rules),
            total_scenarios=len(scenarios),
            by_tier={k: v for k, v in sorted(by_tier.items())},
            by_domain={k: v for k, v in sorted(by_domain.items())},
            by_content_type={k: v for k, v in sorted(by_content_type.items())},
            gaps=gaps,
        )

        self._results.append(result)
        logger.info(
            "Coverage: overall=%.1f%% rules=%d scenarios=%d gaps=%d",
            overall * 100, len(rules), len(scenarios), len(gaps)
        )
        return result

    def calculate_scenario_coverage(
        self,
        rules: List[Dict[str, Any]],
        scenario: Dict[str, Any]
    ) -> float:
        matches = 0
        for rule in rules:
            if self._rule_matches_scenario(rule, scenario):
                matches += 1
        return matches / max(len(rules), 1)

    def get_statistics(self) -> Dict[str, Any]:
        if not self._results:
            return {"total_analyses": 0}

        latest = self._results[-1]
        return {
            "total_analyses": len(self._results),
            "latest_overall": latest.overall_coverage_pct,
            "lowest_tier": min(latest.by_tier.values(), key=lambda d: d.coverage_pct).category
            if latest.by_tier else None,
            "total_gaps": len(latest.gaps),
        }

    def _compute_tier_coverage(
        self,
        rules: List[Dict[str, Any]],
        scenarios: List[Dict[str, Any]]
    ) -> Dict[str, CoverageDetail]:
        tier_rules = defaultdict(list)
        for rule in rules:
            tier_rules[rule.get("tier", "unknown")].append(rule)

        result: Dict[str, CoverageDetail] = {}
        for tier, tier_rules_list in tier_rules.items():
            covered = set()
            for rule in tier_rules_list:
                for i, scenario in enumerate(scenarios):
                    if self._rule_matches_scenario(rule, scenario):
                        covered.add(i)

            uncovered = [
                s.get("name", s.get("id", f"scenario_{i}"))
                for i, s in enumerate(scenarios)
                if i not in covered
            ]

            result[tier] = CoverageDetail(
                category=tier,
                total_items=len(scenarios),
                covered_items=len(covered),
                coverage_pct=round(len(covered) / max(len(scenarios), 1) * 100, 2),
                uncovered_items=uncovered[:20],
            )
        return result

    def _compute_domain_coverage(
        self,
        rules: List[Dict[str, Any]],
        scenarios: List[Dict[str, Any]]
    ) -> Dict[str, CoverageDetail]:
        all_domains: Set[str] = set()
        for scenario in scenarios:
            for d in scenario.get("domains", []) or [scenario.get("domain", "general")]:
                all_domains.add(d)

        result: Dict[str, CoverageDetail] = {}
        for domain in sorted(all_domains):
            relevant_rules = [
                r for r in rules
                if domain in (r.get("domains", []) or [])
                or domain in (r.get("tags", []) or [])
            ]
            domain_scenarios = [
                s for s in scenarios
                if domain in (s.get("domains", []) or [])
                or s.get("domain") == domain
            ]

            covered = 0
            uncovered: List[str] = []
            for scenario in domain_scenarios:
                if any(self._rule_matches_scenario(r, scenario) for r in relevant_rules):
                    covered += 1
                else:
                    uncovered.append(scenario.get("name", scenario.get("id", "unknown")))

            result[domain] = CoverageDetail(
                category=domain,
                total_items=len(domain_scenarios),
                covered_items=covered,
                coverage_pct=round(covered / max(len(domain_scenarios), 1) * 100, 2),
                uncovered_items=uncovered[:20],
            )
        return result

    def _compute_content_type_coverage(
        self,
        rules: List[Dict[str, Any]],
        scenarios: List[Dict[str, Any]]
    ) -> Dict[str, CoverageDetail]:
        type_categories = ["content_type", "type", "category"]
        all_types: Set[str] = set()

        for scenario in scenarios:
            for key in type_categories:
                val = scenario.get(key)
                if val:
                    all_types.add(str(val))
            content_val = scenario.get("content", {})
            if isinstance(content_val, dict):
                all_types.add(content_val.get("type", "text"))
            else:
                all_types.add("text")

        result: Dict[str, CoverageDetail] = {}
        for ctype in sorted(all_types):
            type_scenarios = [
                s for s in scenarios
                if any(str(s.get(k)) == ctype for k in type_categories)
                or (isinstance(s.get("content", {}), dict) and s.get("content", {}).get("type") == ctype)
            ]

            covered = 0
            for scenario in type_scenarios:
                if any(self._rule_matches_scenario(r, scenario) for r in rules):
                    covered += 1

            result[ctype] = CoverageDetail(
                category=ctype,
                total_items=len(type_scenarios),
                covered_items=covered,
                coverage_pct=round(covered / max(len(type_scenarios), 1) * 100, 2),
            )
        return result

    def _identify_gaps(
        self,
        by_tier: Dict[str, CoverageDetail],
        by_domain: Dict[str, CoverageDetail],
        by_content_type: Dict[str, CoverageDetail]
    ) -> List[Dict[str, Any]]:
        gaps: List[Dict[str, Any]] = []

        for name, detail in by_tier.items():
            if detail.coverage_pct < self._min_coverage_threshold * 100:
                gaps.append({
                    "type": "tier",
                    "name": name,
                    "coverage_pct": detail.coverage_pct,
                    "uncovered_count": len(detail.uncovered_items),
                    "recommendation": f"Add rules for tier '{name}' to increase coverage",
                })

        for name, detail in by_domain.items():
            if detail.coverage_pct < self._min_coverage_threshold * 100:
                gaps.append({
                    "type": "domain",
                    "name": name,
                    "coverage_pct": detail.coverage_pct,
                    "uncovered_count": len(detail.uncovered_items),
                    "recommendation": f"Extend rule coverage for domain '{name}'",
                })

        return gaps

    def _rule_matches_scenario(
        self,
        rule: Dict[str, Any],
        scenario: Dict[str, Any]
    ) -> bool:
        rule_tier = rule.get("tier", "")
        scenario_tier = scenario.get("tier", scenario.get("expected_tier", ""))
        if rule_tier and scenario_tier and rule_tier != scenario_tier:
            return False

        rule_domains = set(rule.get("domains", []) or rule.get("tags", []))
        scenario_domains = set(scenario.get("domains", []) or [scenario.get("domain", "")])
        if rule_domains and scenario_domains and not (rule_domains & scenario_domains):
            return False

        rule_patterns = rule.get("patterns", []) or [rule.get("pattern", "")]
        scenario_content = str(scenario.get("content", scenario.get("text", ""))).lower()

        for pattern in rule_patterns:
            if pattern and pattern.lower() in scenario_content:
                return True

        return False
