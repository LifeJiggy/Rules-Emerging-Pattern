"""Tier validator - validates cross-tier interactions, priority conflicts, and compliance."""
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TierValidationIssueType(str, Enum):
    MISSING_SAFETY_RULE = "missing_safety_rule"
    CROSS_TIER_OVERLAP = "cross_tier_overlap"
    PRIORITY_INVERSION = "priority_inversion"
    ENFORCEMENT_MISMATCH = "enforcement_mismatch"
    PREFERENCE_OVERRIDE_SAFETY = "preference_override_safety"
    DUPLICATE_RULE_ID = "duplicate_rule_id"
    MISSING_DEFAULT_RULE = "missing_default_rule"
    EMPTY_TIER = "empty_tier"


@dataclass
class TierValidationIssue:
    issue_type: TierValidationIssueType
    description: str
    tier: str
    severity: str
    affected_rules: List[str] = field(default_factory=list)
    suggestion: Optional[str] = None


@dataclass
class TierValidationResult:
    valid: bool
    issues: List[TierValidationIssue]
    total_rules: int
    rules_by_tier: Dict[str, int]
    safety_rule_count: int
    operational_rule_count: int
    preference_rule_count: int
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TierValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._min_safety_rules = self.config.get("min_safety_rules", 1)
        self._min_operational_rules = self.config.get("min_operational_rules", 0)
        self._min_preference_rules = self.config.get("min_preference_rules", 0)
        self._results: List[TierValidationResult] = []
        logger.info("TierValidator initialized (min_safety=%d, min_op=%d, min_pref=%d)",
                     self._min_safety_rules, self._min_operational_rules, self._min_preference_rules)

    def validate_rules(self, rules: Dict[str, Dict[str, Any]]) -> TierValidationResult:
        issues: List[TierValidationIssue] = []
        tiers: Dict[str, List[str]] = {"safety": [], "operational": [], "preference": []}
        rule_ids: Set[str] = set()
        duplicate_ids: List[str] = []

        for rid, rule_data in rules.items():
            tier = rule_data.get("tier", "preference")
            if tier in tiers:
                tiers[tier].append(rid)
            if rid in rule_ids:
                duplicate_ids.append(rid)
            rule_ids.add(rid)

        for rid in duplicate_ids:
            issues.append(TierValidationIssue(
                issue_type=TierValidationIssueType.DUPLICATE_RULE_ID,
                description=f"Duplicate rule ID: {rid}",
                tier="all", severity="high",
                affected_rules=[rid],
                suggestion="Ensure each rule has a unique ID",
            ))

        if len(tiers["safety"]) < self._min_safety_rules:
            issues.append(TierValidationIssue(
                issue_type=TierValidationIssueType.MISSING_SAFETY_RULE,
                description=f"Only {len(tiers['safety'])} safety rules found, minimum is {self._min_safety_rules}",
                tier="safety", severity="critical",
                suggestion="Add more safety rules to ensure adequate protection",
            ))

        if len(tiers["operational"]) < self._min_operational_rules:
            issues.append(TierValidationIssue(
                issue_type=TierValidationIssueType.MISSING_DEFAULT_RULE,
                description=f"Only {len(tiers['operational'])} operational rules found",
                tier="operational", severity="low",
                suggestion="Consider adding operational rules for completeness",
            ))

        for rid, rule_data in rules.items():
            tier = rule_data.get("tier", "preference")
            enforcement = rule_data.get("enforcement", "advisory")
            if tier == "safety" and enforcement != "strict":
                issues.append(TierValidationIssue(
                    issue_type=TierValidationIssueType.ENFORCEMENT_MISMATCH,
                    description=f"Safety rule '{rid}' has enforcement '{enforcement}' instead of 'strict'",
                    tier="safety", severity="critical",
                    affected_rules=[rid],
                    suggestion="All safety rules must use 'strict' enforcement",
                ))

            if tier == "preference" and rule_data.get("auto_block", False):
                issues.append(TierValidationIssue(
                    issue_type=TierValidationIssueType.PREFERENCE_OVERRIDE_SAFETY,
                    description=f"Preference rule '{rid}' has auto_block enabled",
                    tier="preference", severity="high",
                    affected_rules=[rid],
                    suggestion="Preference rules should never auto-block content",
                ))

        if tiers["safety"] and tiers["preference"]:
            safety_ids = set(tiers["safety"])
            preference_ids = set(tiers["preference"])
            overlap = safety_ids & preference_ids
            if overlap:
                issues.append(TierValidationIssue(
                    issue_type=TierValidationIssueType.CROSS_TIER_OVERLAP,
                    description=f"Rules exist in both safety and preference tiers: {overlap}",
                    tier="cross_tier", severity="critical",
                    affected_rules=list(overlap),
                    suggestion="Remove rules from duplicate tiers",
                ))

        if not tiers["safety"]:
            issues.append(TierValidationIssue(
                issue_type=TierValidationIssueType.EMPTY_TIER,
                description="Safety tier is empty - no safety rules configured",
                tier="safety", severity="critical",
                suggestion="Configure at least one safety rule",
            ))

        result = TierValidationResult(
            valid=len([i for i in issues if i.severity == "critical"]) == 0,
            issues=issues,
            total_rules=len(rules),
            rules_by_tier={t: len(rids) for t, rids in tiers.items()},
            safety_rule_count=len(tiers["safety"]),
            operational_rule_count=len(tiers["operational"]),
            preference_rule_count=len(tiers["preference"]),
        )

        self._results.append(result)
        logger.info("Tier validation: %s (issues=%d, critical=%d)",
                     "PASS" if result.valid else "FAIL",
                     len(issues), sum(1 for i in issues if i.severity == "critical"))
        return result

    def get_last_result(self) -> Optional[TierValidationResult]:
        return self._results[-1] if self._results else None

    def get_statistics(self) -> Dict[str, Any]:
        if not self._results:
            return {"total_validations": 0}
        return {
            "total_validations": len(self._results),
            "pass_rate": sum(1 for r in self._results if r.valid) / len(self._results),
            "last_validation": self._results[-1].valid,
        }
