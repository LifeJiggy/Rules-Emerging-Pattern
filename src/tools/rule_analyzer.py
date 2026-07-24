"""
Rule analysis tool - detect overlapping patterns, contradictions, unused rules,
and generate comprehensive analysis reports.
"""

import json
import logging
import math
import os
import re
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.conflict import ConflictType, ResolutionStrategy, RuleConflict
from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import ValidationResult, Violation

logger = logging.getLogger(__name__)


class AnalysisLevel(str, Enum):
    """Depth of analysis to perform."""
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    EXHAUSTIVE = "exhaustive"


class IssueSeverity(str, Enum):
    """Severity for analysis findings."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IssueCategory(str, Enum):
    """Categories of issues found during analysis."""
    OVERLAP = "overlap"
    CONTRADICTION = "contradiction"
    UNUSED_RULE = "unused_rule"
    INEFFECTIVE_RULE = "ineffective_rule"
    PERFORMANCE = "performance"
    MISSING_COVERAGE = "missing_coverage"
    CONFIGURATION = "configuration"
    REDUNDANCY = "redundancy"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    DEAD_RULE = "dead_rule"


@dataclass
class AnalysisConfig:
    """Configuration for the rule analyzer."""
    analysis_level: AnalysisLevel = AnalysisLevel.STANDARD
    overlap_threshold: float = 0.3
    contradiction_sensitivity: float = 0.7
    min_pattern_similarity: float = 0.4
    performance_sample_size: int = 100
    unused_days_threshold: int = 30
    max_reports_to_keep: int = 50
    include_suggestions: bool = True
    auto_remediate_low: bool = False
    output_format: str = "json"
    report_dir: Optional[str] = None
    exclude_rules: List[str] = field(default_factory=list)
    focus_tags: List[str] = field(default_factory=list)
    focus_tiers: List[RuleTier] = field(default_factory=list)
    parallel_analysis: bool = False
    max_workers: int = 4
    detailed_mode: bool = False


@dataclass
class AnalysisIssue:
    """A single issue found during analysis."""
    issue_id: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str
    affected_rule_ids: List[str]
    affected_rules: List[str]
    confidence: float
    suggestion: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution_note: Optional[str] = None


@dataclass
class AnalysisReport:
    """Complete analysis report."""
    report_id: str
    created_at: datetime
    analysis_level: AnalysisLevel
    total_rules_analyzed: int
    total_issues_found: int
    issues: List[AnalysisIssue]
    summary: Dict[str, int]
    tier_breakdown: Dict[str, Dict[str, int]]
    type_breakdown: Dict[str, Dict[str, int]]
    recommendations: List[str]
    config_used: Dict[str, Any]
    duration_seconds: float
    overlapping_groups: List[List[str]] = field(default_factory=list)
    contradiction_pairs: List[Tuple[str, str, str]] = field(default_factory=list)
    unused_rule_ids: List[str] = field(default_factory=list)
    performance_hotspots: List[Dict[str, Any]] = field(default_factory=list)
    coverage_gaps: List[str] = field(default_factory=list)


class OverlapDetector:
    """Detects overlapping patterns between rules."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.OverlapDetector")

    def detect_overlaps(self, rules: List[Rule]) -> List[AnalysisIssue]:
        issues = []
        if len(rules) < 2:
            return issues
        rule_pairs = list(combinations(rules, 2))
        if self.config.analysis_level == AnalysisLevel.QUICK:
            rule_pairs = rule_pairs[:50]
        elif self.config.analysis_level == AnalysisLevel.STANDARD:
            rule_pairs = rule_pairs[:200]
        for rule_a, rule_b in rule_pairs:
            if rule_a.id in self.config.exclude_rules or rule_b.id in self.config.exclude_rules:
                continue
            similarity = self._compute_rule_similarity(rule_a, rule_b)
            if similarity >= self.config.overlap_threshold:
                overlap_type = self._classify_overlap(rule_a, rule_b, similarity)
                issue = self._build_overlap_issue(rule_a, rule_b, similarity, overlap_type)
                issues.append(issue)
        return issues

    def _compute_rule_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        scores = []
        keyword_sim = self._keyword_similarity(rule_a, rule_b)
        scores.append(("keyword", keyword_sim, 0.3))
        regex_sim = self._regex_similarity(rule_a, rule_b)
        scores.append(("regex", regex_sim, 0.25))
        condition_sim = self._condition_similarity(rule_a, rule_b)
        scores.append(("condition", condition_sim, 0.2))
        desc_sim = self._description_similarity(rule_a, rule_b)
        scores.append(("description", desc_sim, 0.15))
        tier_sim = self._tier_similarity(rule_a, rule_b)
        scores.append(("tier", tier_sim, 0.1))
        total = sum(weight * score for _, score, weight in scores)
        return total

    def _keyword_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        keywords_a = set()
        for pattern in rule_a.patterns:
            keywords_a.update(k.lower() for k in pattern.keywords)
        keywords_b = set()
        for pattern in rule_b.patterns:
            keywords_b.update(k.lower() for k in pattern.keywords)
        if not keywords_a or not keywords_b:
            return 0.0
        intersection = keywords_a & keywords_b
        union = keywords_a | keywords_b
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def _regex_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        patterns_a = set()
        for pattern in rule_a.patterns:
            patterns_a.update(pattern.regex_patterns)
        patterns_b = set()
        for pattern in rule_b.patterns:
            patterns_b.update(pattern.regex_patterns)
        if not patterns_a or not patterns_b:
            return 0.0
        intersection = patterns_a & patterns_b
        union = patterns_a | patterns_b
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def _condition_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        conds_a = set(rule_a.conditions.keys())
        conds_b = set(rule_b.conditions.keys())
        if not conds_a or not conds_b:
            return 0.0
        intersection = conds_a & conds_b
        union = conds_a | conds_b
        if not union:
            return 0.0
        key_sim = len(intersection) / len(union)
        value_matches = 0
        for key in intersection:
            if rule_a.conditions.get(key) == rule_b.conditions.get(key):
                value_matches += 1
        val_sim = value_matches / len(intersection) if intersection else 0
        return 0.5 * key_sim + 0.5 * val_sim

    def _description_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        desc_a = rule_a.description.lower()
        desc_b = rule_b.description.lower()
        words_a = set(re.findall(r'\w+', desc_a))
        words_b = set(re.findall(r'\w+', desc_b))
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def _tier_similarity(self, rule_a: Rule, rule_b: Rule) -> float:
        return 1.0 if rule_a.tier == rule_b.tier else 0.0

    def _classify_overlap(self, rule_a: Rule, rule_b: Rule, similarity: float) -> str:
        if rule_a.rule_type == rule_b.rule_type and similarity > 0.8:
            return "exact_duplicate"
        if rule_a.rule_type == rule_b.rule_type and similarity > 0.6:
            return "near_duplicate"
        if similarity > 0.5:
            return "significant_overlap"
        if similarity > self.config.overlap_threshold:
            return "partial_overlap"
        return "minor_overlap"

    def _build_overlap_issue(self, rule_a: Rule, rule_b: Rule, similarity: float, overlap_type: str) -> AnalysisIssue:
        severity_map = {
            "exact_duplicate": IssueSeverity.ERROR,
            "near_duplicate": IssueSeverity.WARNING,
            "significant_overlap": IssueSeverity.WARNING,
            "partial_overlap": IssueSeverity.INFO,
            "minor_overlap": IssueSeverity.INFO,
        }
        severity = severity_map.get(overlap_type, IssueSeverity.INFO)
        title = f"Overlapping rules: {rule_a.name} and {rule_b.name}"
        desc = (
            f"Rules '{rule_a.name}' ({rule_a.id}) and '{rule_b.name}' ({rule_b.id}) "
            f"have {similarity:.1%} pattern similarity ({overlap_type}). "
            f"Both are in tier '{rule_a.tier.value}' with types "
            f"'{rule_a.rule_type.value}' and '{rule_b.rule_type.value}'."
        )
        suggestion = (
            f"Consider merging rules {rule_a.id} and {rule_b.id} into a single rule, "
            f"or adjusting their patterns to reduce overlap. "
            f"Review both rule definitions for potential consolidation."
        )
        return AnalysisIssue(
            issue_id=f"OVERLAP-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.OVERLAP,
            severity=severity,
            title=title,
            description=desc,
            affected_rule_ids=[rule_a.id, rule_b.id],
            affected_rules=[rule_a.name, rule_b.name],
            confidence=min(similarity, 0.95),
            suggestion=suggestion if self.config.include_suggestions else None,
            metrics={"similarity_score": similarity, "overlap_type": overlap_type},
        )


class ContradictionDetector:
    """Detects contradictory rules in the system."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.ContradictionDetector")

    def detect_contradictions(self, rules: List[Rule]) -> List[AnalysisIssue]:
        issues = []
        if len(rules) < 2:
            return issues
        rule_pairs = list(combinations(rules, 2))
        for rule_a, rule_b in rule_pairs:
            if rule_a.id in self.config.exclude_rules or rule_b.id in self.config.exclude_rules:
                continue
            contradiction_score = self._check_contradiction(rule_a, rule_b)
            if contradiction_score >= self.config.contradiction_sensitivity:
                issue = self._build_contradiction_issue(rule_a, rule_b, contradiction_score)
                issues.append(issue)
        return issues

    def _check_contradiction(self, rule_a: Rule, rule_b: Rule) -> float:
        scores = []
        action_contradiction = self._check_action_contradiction(rule_a, rule_b)
        scores.append(("action", action_contradiction, 0.35))
        pattern_contradiction = self._check_pattern_contradiction(rule_a, rule_b)
        scores.append(("pattern", pattern_contradiction, 0.30))
        tier_contradiction = self._check_tier_contradiction(rule_a, rule_b)
        scores.append(("tier", tier_contradiction, 0.15))
        condition_contradiction = self._check_condition_contradiction(rule_a, rule_b)
        scores.append(("condition", condition_contradiction, 0.20))
        total = sum(score * weight for _, score, weight in scores)
        return total

    def _check_action_contradiction(self, rule_a: Rule, rule_b: Rule) -> float:
        conflicting_actions = {
            ("allow", "block"),
            ("approve", "reject"),
            ("enable", "disable"),
            ("grant", "deny"),
            ("include", "exclude"),
            ("allow", "deny"),
            ("accept", "reject"),
        }
        actions_a = set()
        for p in rule_a.patterns:
            if p.action:
                actions_a.add(p.action.lower())
        actions_b = set()
        for p in rule_b.patterns:
            if p.action:
                actions_b.add(p.action.lower())
        if not actions_a or not actions_b:
            return 0.0
        contradictions_found = 0
        for act_a in actions_a:
            for act_b in actions_b:
                if (act_a, act_b) in conflicting_actions or (act_b, act_a) in conflicting_actions:
                    contradictions_found += 1
        total_pairs = len(actions_a) * len(actions_b)
        if total_pairs == 0:
            return 0.0
        return contradictions_found / total_pairs

    def _check_pattern_contradiction(self, rule_a: Rule, rule_b: Rule) -> float:
        shared_keywords = set()
        for p in rule_a.patterns:
            shared_keywords.update(k.lower() for k in p.keywords)
        for p in rule_b.patterns:
            shared_keywords.update(k.lower() for k in p.keywords)
        if not shared_keywords:
            return 0.0
        return 1.0 if len(shared_keywords) > 0 else 0.0

    def _check_tier_contradiction(self, rule_a: Rule, rule_b: Rule) -> float:
        tier_priority = {
            RuleTier.SAFETY: 3,
            RuleTier.OPERATIONAL: 2,
            RuleTier.PREFERENCE: 1,
        }
        priority_a = tier_priority.get(rule_a.tier, 0)
        priority_b = tier_priority.get(rule_b.tier, 0)
        if priority_a == priority_b:
            return 0.0
        if abs(priority_a - priority_b) == 2:
            return 0.8
        return 0.4

    def _check_condition_contradiction(self, rule_a: Rule, rule_b: Rule) -> float:
        shared_keys = set(rule_a.conditions.keys()) & set(rule_b.conditions.keys())
        if not shared_keys:
            return 0.0
        contradictions = 0
        for key in shared_keys:
            val_a = rule_a.conditions[key]
            val_b = rule_b.conditions[key]
            if isinstance(val_a, bool) and isinstance(val_b, bool) and val_a != val_b:
                contradictions += 1
            if isinstance(val_a, str) and isinstance(val_b, str) and val_a.lower() != val_b.lower():
                if val_a.lower() in ("true", "false") and val_b.lower() in ("true", "false"):
                    if val_a.lower() != val_b.lower():
                        contradictions += 1
        if not shared_keys:
            return 0.0
        return contradictions / len(shared_keys)

    def _build_contradiction_issue(self, rule_a: Rule, rule_b: Rule, score: float) -> AnalysisIssue:
        title = f"Contradictory rules: {rule_a.name} and {rule_b.name}"
        desc = (
            f"Rules '{rule_a.name}' ({rule_a.id}, tier={rule_a.tier.value}) and "
            f"'{rule_b.name}' ({rule_b.id}, tier={rule_b.tier.value}) "
            f"have a contradiction score of {score:.1%}. "
            f"They may produce conflicting results for the same input."
        )
        suggestion = (
            f"Review rules {rule_a.id} and {rule_b.id} for logical contradictions. "
            f"Consider adding explicit conflict resolution, "
            f"or adjusting conditions to avoid overlapping applicability."
        )
        return AnalysisIssue(
            issue_id=f"CONTRADICT-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.CONTRADICTION,
            severity=IssueSeverity.ERROR if score > 0.85 else IssueSeverity.WARNING,
            title=title,
            description=desc,
            affected_rule_ids=[rule_a.id, rule_b.id],
            affected_rules=[rule_a.name, rule_b.name],
            confidence=min(score, 0.95),
            suggestion=suggestion if self.config.include_suggestions else None,
            metrics={"contradiction_score": score},
        )


class UnusedRuleDetector:
    """Detects unused or ineffective rules."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.UnusedRuleDetector")

    def detect_unused_rules(self, rules: List[Rule], evaluation_history: Optional[List[Dict]] = None) -> List[AnalysisIssue]:
        issues = []
        if not evaluation_history:
            evaluation_history = []
        rule_usage = Counter()
        for entry in evaluation_history:
            rule_id = entry.get("rule_id")
            if rule_id:
                rule_usage[rule_id] += 1
        total_evaluations = sum(rule_usage.values()) or 1
        for rule in rules:
            if rule.id in self.config.exclude_rules:
                continue
            usage_count = rule_usage.get(rule.id, 0)
            usage_fraction = usage_count / total_evaluations
            if usage_count == 0:
                issue = self._build_unused_issue(rule, "never_evaluated", 0.0)
                issues.append(issue)
            elif usage_fraction < 0.01:
                issue = self._build_unused_issue(rule, "rarely_evaluated", usage_fraction)
                issues.append(issue)
            if rule.status == RuleStatus.INACTIVE and usage_count > 0:
                issue = self._build_inactive_but_used_issue(rule, usage_count)
                issues.append(issue)
            if rule.status == RuleStatus.DEPRECATED and usage_count > 0:
                issue = self._build_deprecated_but_used_issue(rule, usage_count)
                issues.append(issue)
        return issues

    def _build_unused_issue(self, rule: Rule, sub_type: str, usage_fraction: float) -> AnalysisIssue:
        if sub_type == "never_evaluated":
            title = f"Unused rule: {rule.name}"
            desc = f"Rule '{rule.name}' ({rule.id}) has never been evaluated. It may be dead code."
            suggestion = (
                f"Review rule {rule.id} - if no longer needed, mark as deprecated. "
                f"If it should be used, check its conditions and pattern applicability."
            )
            severity = IssueSeverity.WARNING
        else:
            title = f"Rarely used rule: {rule.name}"
            desc = f"Rule '{rule.name}' ({rule.id}) accounts for only {usage_fraction:.2%} of evaluations."
            suggestion = (
                f"Review whether rule {rule.id} is still needed, or if its conditions "
                f"are too restrictive."
            )
            severity = IssueSeverity.INFO
        return AnalysisIssue(
            issue_id=f"UNUSED-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.UNUSED_RULE,
            severity=severity,
            title=title,
            description=desc,
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.9 if sub_type == "never_evaluated" else 0.6,
            suggestion=suggestion if self.config.include_suggestions else None,
            metrics={"usage_count": 0, "usage_fraction": usage_fraction, "sub_type": sub_type},
        )

    def _build_inactive_but_used_issue(self, rule: Rule, usage_count: int) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"INACTIVE-USED-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.CONFIGURATION,
            severity=IssueSeverity.WARNING,
            title=f"Inactive but evaluated rule: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) is marked as INACTIVE "
                f"but was evaluated {usage_count} times. This may indicate "
                f"a configuration discrepancy."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.8,
            suggestion="Check if the rule should be ACTIVE or if the evaluation pipeline is incorrectly including inactive rules.",
            metrics={"usage_count": usage_count},
        )

    def _build_deprecated_but_used_issue(self, rule: Rule, usage_count: int) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"DEPRECATED-USED-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.CONFIGURATION,
            severity=IssueSeverity.WARNING,
            title=f"Deprecated but evaluated rule: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) is marked as DEPRECATED "
                f"but was evaluated {usage_count} times. "
                f"Deprecated rules should not be actively evaluated."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.85,
            suggestion="Remove the deprecated rule from the active evaluation pipeline.",
            metrics={"usage_count": usage_count},
        )

    def detect_ineffective_rules(self, rules: List[Rule], evaluation_results: Optional[List[Dict]] = None) -> List[AnalysisIssue]:
        issues = []
        if not evaluation_results:
            return issues
        rule_stats = defaultdict(lambda: {"matched": 0, "total": 0, "actions_taken": Counter()})
        for result in evaluation_results:
            rule_id = result.get("rule_id")
            if not rule_id:
                continue
            rule_stats[rule_id]["total"] += 1
            if result.get("matched", False):
                rule_stats[rule_id]["matched"] += 1
            action = result.get("action_taken", "none")
            rule_stats[rule_id]["actions_taken"][action] += 1
        for rule in rules:
            if rule.id in self.config.exclude_rules:
                continue
            stats = rule_stats.get(rule.id)
            if not stats or stats["total"] < 10:
                continue
            match_rate = stats["matched"] / stats["total"]
            if match_rate < 0.05:
                issue = self._build_low_match_issue(rule, match_rate, stats)
                issues.append(issue)
            if stats["actions_taken"]["none"] > stats["matched"] * 0.8 and stats["matched"] > 0:
                issue = self._build_no_action_issue(rule, stats)
                issues.append(issue)
        return issues

    def _build_low_match_issue(self, rule: Rule, match_rate: float, stats: Dict) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"LOW-MATCH-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.INEFFECTIVE_RULE,
            severity=IssueSeverity.WARNING,
            title=f"Low match rate rule: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) has a match rate of {match_rate:.2%} "
                f"({stats['matched']}/{stats['total']} evaluations). "
                f"This rule rarely triggers and may be ineffective."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.7,
            suggestion="Review the rule's patterns and conditions to improve its match rate, or consider deprecation.",
            metrics={
                "match_rate": match_rate,
                "total_evaluations": stats["total"],
                "matched_count": stats["matched"],
            },
        )

    def _build_no_action_issue(self, rule: Rule, stats: Dict) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"NO-ACTION-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.INEFFECTIVE_RULE,
            severity=IssueSeverity.INFO,
            title=f"Rule matches but takes no action: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) matched {stats['matched']} times "
                f"but took no action in {stats['actions_taken']['none']} cases. "
                f"The rule may be configured incorrectly."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.5,
            suggestion="Check if the rule's action configuration is correct and if enforcement level is appropriate.",
            metrics={"matched_count": stats["matched"], "no_action_count": stats["actions_taken"]["none"]},
        )


class PerformanceAnalyzer:
    """Analyzes rule performance data."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.PerformanceAnalyzer")

    def analyze_performance(self, rules: List[Rule], performance_data: Optional[List[Dict]] = None) -> List[AnalysisIssue]:
        issues = []
        if not performance_data:
            return issues
        rule_perf = defaultdict(lambda: {"times": [], "memory_bytes": [], "cache_hits": 0, "cache_misses": 0})
        for entry in performance_data:
            rule_id = entry.get("rule_id")
            if not rule_id:
                continue
            if "duration_ms" in entry:
                rule_perf[rule_id]["times"].append(entry["duration_ms"])
            if "memory_bytes" in entry:
                rule_perf[rule_id]["memory_bytes"].append(entry["memory_bytes"])
            if entry.get("cache_hit", False):
                rule_perf[rule_id]["cache_hits"] += 1
            else:
                rule_perf[rule_id]["cache_misses"] += 1
        for rule in rules:
            if rule.id in self.config.exclude_rules:
                continue
            perf = rule_perf.get(rule.id)
            if not perf or not perf["times"]:
                continue
            avg_time = sum(perf["times"]) / len(perf["times"])
            max_time = max(perf["times"])
            timeout_ms = rule.timeout_ms
            if max_time > timeout_ms * 0.8:
                issue = self._build_slow_rule_issue(rule, avg_time, max_time, timeout_ms)
                issues.append(issue)
            if perf["times"] and avg_time > timeout_ms * 0.5:
                issue = self._build_approaching_timeout_issue(rule, avg_time, max_time, timeout_ms)
                issues.append(issue)
            total_cache = perf["cache_hits"] + perf["cache_misses"]
            if total_cache > 10:
                hit_rate = perf["cache_hits"] / total_cache
                if hit_rate < 0.3:
                    issue = self._build_cache_inefficiency_issue(rule, hit_rate, perf)
                    issues.append(issue)
            if perf["memory_bytes"]:
                avg_mem = sum(perf["memory_bytes"]) / len(perf["memory_bytes"])
                if avg_mem > 10 * 1024 * 1024:
                    issue = self._build_high_memory_issue(rule, avg_mem, perf)
                    issues.append(issue)
        return issues

    def _build_slow_rule_issue(self, rule: Rule, avg_time: float, max_time: float, timeout: int) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"SLOW-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.PERFORMANCE,
            severity=IssueSeverity.WARNING,
            title=f"Slow rule execution: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) has max execution time {max_time:.1f}ms "
                f"(avg {avg_time:.1f}ms) approaching the {timeout}ms timeout. "
                f"This may cause evaluation failures under load."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.8,
            suggestion="Optimize rule patterns, reduce regex complexity, or increase the timeout_ms value.",
            metrics={
                "avg_duration_ms": avg_time,
                "max_duration_ms": max_time,
                "timeout_ms": timeout,
                "samples": len(rule.patterns),
            },
        )

    def _build_approaching_timeout_issue(self, rule: Rule, avg_time: float, max_time: float, timeout: int) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"TIMEOUT-RISK-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.PERFORMANCE,
            severity=IssueSeverity.INFO,
            title=f"Timeout risk for rule: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) averages {avg_time:.1f}ms "
                f"with max {max_time:.1f}ms (timeout={timeout}ms). "
                f"Consider performance optimization."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.6,
            suggestion="Review the rule for optimization opportunities.",
            metrics={"avg_duration_ms": avg_time, "max_duration_ms": max_time, "timeout_ms": timeout},
        )

    def _build_cache_inefficiency_issue(self, rule: Rule, hit_rate: float, perf: Dict) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"CACHE-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.PERFORMANCE,
            severity=IssueSeverity.INFO,
            title=f"Low cache hit rate: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) has a cache hit rate of {hit_rate:.1%} "
                f"({perf['cache_hits']} hits, {perf['cache_misses']} misses). "
                f"Low cache efficiency may impact performance."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.5,
            suggestion="Consider increasing cache_ttl_seconds or adjusting the input variability.",
            metrics={"cache_hit_rate": hit_rate, "cache_hits": perf["cache_hits"], "cache_misses": perf["cache_misses"]},
        )

    def _build_high_memory_issue(self, rule: Rule, avg_mem: float, perf: Dict) -> AnalysisIssue:
        return AnalysisIssue(
            issue_id=f"MEMORY-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.PERFORMANCE,
            severity=IssueSeverity.WARNING,
            title=f"High memory usage: {rule.name}",
            description=(
                f"Rule '{rule.name}' ({rule.id}) uses an average of {avg_mem / (1024*1024):.1f}MB "
                f"per evaluation. This may indicate a memory leak or inefficient pattern matching."
            ),
            affected_rule_ids=[rule.id],
            affected_rules=[rule.name],
            confidence=0.6,
            suggestion="Investigate memory usage patterns and optimize data structures.",
            metrics={"avg_memory_bytes": avg_mem, "sample_count": len(perf["memory_bytes"])},
        )


class CircularDependencyDetector:
    """Detects circular dependencies between rules."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.CircularDependencyDetector")

    def detect_circular_dependencies(self, rules: List[Rule]) -> List[AnalysisIssue]:
        issues = []
        adj_list = defaultdict(list)
        for rule in rules:
            for dep_id in rule.conditions.get("depends_on", []):
                adj_list[rule.id].append(dep_id)
        visited = set()
        rec_stack = set()
        parent = {}

        def dfs(node: str, path: List[str]) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in adj_list.get(node, []):
                if neighbor not in visited:
                    parent[neighbor] = node
                    result = dfs(neighbor, path)
                    if result:
                        return result
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
            path.pop()
            rec_stack.discard(node)
            return None

        for rule in rules:
            if rule.id not in visited:
                cycle = dfs(rule.id, [])
                if cycle:
                    cycle_rules = [r for r in rules if r.id in cycle]
                    issue = self._build_circular_dep_issue(cycle, cycle_rules)
                    issues.append(issue)
        return issues

    def _build_circular_dep_issue(self, cycle: List[str], cycle_rules: List[Rule]) -> AnalysisIssue:
        rule_names = {r.id: r.name for r in cycle_rules}
        cycle_desc = " -> ".join(f"{r_id}({rule_names.get(r_id, r_id)})" for r_id in cycle)
        return AnalysisIssue(
            issue_id=f"CIRCULAR-{uuid.uuid4().hex[:8]}",
            category=IssueCategory.CIRCULAR_DEPENDENCY,
            severity=IssueSeverity.CRITICAL,
            title=f"Circular dependency detected across {len(cycle)} rules",
            description=f"Circular dependency chain: {cycle_desc}",
            affected_rule_ids=list(cycle),
            affected_rules=[rule_names.get(rid, rid) for rid in cycle],
            confidence=0.95,
            suggestion="Break the circular dependency by removing or redirecting one of the dependency links.",
            metrics={"cycle_length": len(cycle), "cycle": cycle},
        )


class RuleAnalyzer:
    """
    Comprehensive rule analysis tool.

    Analyzes rule definitions for issues, detects overlapping and contradictory patterns,
    identifies unused or ineffective rules, analyzes performance data, and generates
    detailed analysis reports.
    """

    def __init__(self, config: Optional[AnalysisConfig] = None):
        self.config = config or AnalysisConfig()
        self._overlap_detector = OverlapDetector(self.config)
        self._contradiction_detector = ContradictionDetector(self.config)
        self._unused_detector = UnusedRuleDetector(self.config)
        self._perf_analyzer = PerformanceAnalyzer(self.config)
        self._circular_dep_detector = CircularDependencyDetector(self.config)
        self.logger = logging.getLogger(f"{__name__}.RuleAnalyzer")

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._overlap_detector = OverlapDetector(self.config)
        self._contradiction_detector = ContradictionDetector(self.config)
        self._unused_detector = UnusedRuleDetector(self.config)
        self._perf_analyzer = PerformanceAnalyzer(self.config)
        self._circular_dep_detector = CircularDependencyDetector(self.config)
        self.logger.info("Analysis config updated with %d changes", len(config_updates))

    def analyze_rules(
        self,
        rules: List[Rule],
        evaluation_history: Optional[List[Dict]] = None,
        performance_data: Optional[List[Dict]] = None,
        evaluation_results: Optional[List[Dict]] = None,
    ) -> AnalysisReport:
        start_time = time.time()
        report_id = f"ANALYSIS-{uuid.uuid4().hex[:12]}"
        self.logger.info(
            "Starting rule analysis (level=%s, rules=%d)",
            self.config.analysis_level.value,
            len(rules),
        )
        filtered_rules = self._filter_rules(rules)
        all_issues = []
        overlap_issues = self._overlap_detector.detect_overlaps(filtered_rules)
        all_issues.extend(overlap_issues)
        self.logger.info("Found %d overlap issues", len(overlap_issues))
        contradiction_issues = self._contradiction_detector.detect_contradictions(filtered_rules)
        all_issues.extend(contradiction_issues)
        self.logger.info("Found %d contradiction issues", len(contradiction_issues))
        unused_issues = self._unused_detector.detect_unused_rules(filtered_rules, evaluation_history)
        all_issues.extend(unused_issues)
        self.logger.info("Found %d unused rule issues", len(unused_issues))
        ineffective_issues = self._unused_detector.detect_ineffective_rules(filtered_rules, evaluation_results)
        all_issues.extend(ineffective_issues)
        self.logger.info("Found %d ineffective rule issues", len(ineffective_issues))
        perf_issues = self._perf_analyzer.analyze_performance(filtered_rules, performance_data)
        all_issues.extend(perf_issues)
        self.logger.info("Found %d performance issues", len(perf_issues))
        if self.config.analysis_level in (AnalysisLevel.DEEP, AnalysisLevel.EXHAUSTIVE):
            circular_issues = self._circular_dep_detector.detect_circular_dependencies(filtered_rules)
            all_issues.extend(circular_issues)
            self.logger.info("Found %d circular dependency issues", len(circular_issues))
        report = self._build_report(report_id, filtered_rules, all_issues, start_time)
        self.logger.info(
            "Analysis complete: %d issues found in %.2f seconds",
            len(all_issues),
            report.duration_seconds,
        )
        return report

    def analyze_single_rule(self, rule: Rule, all_rules: List[Rule]) -> List[AnalysisIssue]:
        issues = []
        for other in all_rules:
            if other.id == rule.id:
                continue
            overlap_sim = self._overlap_detector._compute_rule_similarity(rule, other)
            if overlap_sim >= self.config.overlap_threshold:
                issues.append(
                    self._overlap_detector._build_overlap_issue(
                        rule, other, overlap_sim,
                        self._overlap_detector._classify_overlap(rule, other, overlap_sim),
                    )
                )
            contradiction_score = self._contradiction_detector._check_contradiction(rule, other)
            if contradiction_score >= self.config.contradiction_sensitivity:
                issues.append(
                    self._contradiction_detector._build_contradiction_issue(rule, other, contradiction_score)
                )
        return issues

    def _filter_rules(self, rules: List[Rule]) -> List[Rule]:
        filtered = rules
        if self.config.exclude_rules:
            filtered = [r for r in filtered if r.id not in self.config.exclude_rules]
        if self.config.focus_tags:
            filtered = [
                r for r in filtered
                if any(tag in r.tags for tag in self.config.focus_tags)
            ]
        if self.config.focus_tiers:
            filtered = [
                r for r in filtered
                if r.tier in self.config.focus_tiers
            ]
        return filtered

    def _build_report(
        self,
        report_id: str,
        rules: List[Rule],
        issues: List[AnalysisIssue],
        start_time: float,
    ) -> AnalysisReport:
        duration = time.time() - start_time
        summary = Counter(issue.severity.value for issue in issues)
        tier_breakdown = self._build_tier_breakdown(rules, issues)
        type_breakdown = self._build_type_breakdown(rules, issues)
        recommendations = self._generate_recommendations(issues)
        overlapping_groups = self._extract_overlapping_groups(issues)
        contradiction_pairs = self._extract_contradiction_pairs(issues)
        unused_ids = [i.affected_rule_ids[0] for i in issues if i.category == IssueCategory.UNUSED_RULE]
        perf_hotspots = [
            i.metrics for i in issues
            if i.category == IssueCategory.PERFORMANCE and i.severity == IssueSeverity.WARNING
        ]
        return AnalysisReport(
            report_id=report_id,
            created_at=datetime.utcnow(),
            analysis_level=self.config.analysis_level,
            total_rules_analyzed=len(rules),
            total_issues_found=len(issues),
            issues=issues,
            summary=dict(summary),
            tier_breakdown=tier_breakdown,
            type_breakdown=type_breakdown,
            recommendations=recommendations,
            config_used=self._config_to_dict(),
            duration_seconds=duration,
            overlapping_groups=overlapping_groups,
            contradiction_pairs=contradiction_pairs,
            unused_rule_ids=unused_ids,
            performance_hotspots=perf_hotspots,
            coverage_gaps=[],
        )

    def _build_tier_breakdown(self, rules: List[Rule], issues: List[AnalysisIssue]) -> Dict[str, Dict[str, int]]:
        breakdown = {}
        for tier in RuleTier:
            tier_rules = [r for r in rules if r.tier == tier]
            tier_issues = [
                i for i in issues
                if any(r.id in i.affected_rule_ids for r in tier_rules)
            ]
            if not tier_rules and not tier_issues:
                continue
            breakdown[tier.value] = {
                "rule_count": len(tier_rules),
                "issue_count": len(tier_issues),
            }
        return breakdown

    def _build_type_breakdown(self, rules: List[Rule], issues: List[AnalysisIssue]) -> Dict[str, Dict[str, int]]:
        breakdown = {}
        for rtype in RuleType:
            type_rules = [r for r in rules if r.rule_type == rtype]
            type_issues = [
                i for i in issues
                if any(r.id in i.affected_rule_ids for r in type_rules)
            ]
            if not type_rules and not type_issues:
                continue
            breakdown[rtype.value] = {
                "rule_count": len(type_rules),
                "issue_count": len(type_issues),
            }
        return breakdown

    def _generate_recommendations(self, issues: List[AnalysisIssue]) -> List[str]:
        recs = []
        critical_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
        error_count = sum(1 for i in issues if i.severity == IssueSeverity.ERROR)
        warning_count = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
        if critical_count > 0:
            recs.append(f"Address {critical_count} critical issue(s) immediately.")
        if error_count > 0:
            recs.append(f"Resolve {error_count} error-level issue(s) in the next maintenance window.")
        if warning_count > 5:
            recs.append(f"Review {warning_count} warning-level issues during regular maintenance.")
        overlap_count = sum(1 for i in issues if i.category == IssueCategory.OVERLAP)
        if overlap_count > 3:
            recs.append(f"Consolidate {overlap_count} overlapping rule pairs to reduce redundancy.")
        unused_count = sum(1 for i in issues if i.category == IssueCategory.UNUSED_RULE)
        if unused_count > 2:
            recs.append(f"Review and deprecate {unused_count} unused rules.")
        circular_count = sum(1 for i in issues if i.category == IssueCategory.CIRCULAR_DEPENDENCY)
        if circular_count > 0:
            recs.append(f"Resolve {circular_count} circular dependenc(ies) to prevent evaluation deadlocks.")
        if not recs:
            recs.append("No critical issues found. Continue monitoring rule health.")
        return recs

    def _extract_overlapping_groups(self, issues: List[AnalysisIssue]) -> List[List[str]]:
        groups = []
        for issue in issues:
            if issue.category == IssueCategory.OVERLAP and len(issue.affected_rule_ids) >= 2:
                groups.append(issue.affected_rule_ids)
        return groups

    def _extract_contradiction_pairs(self, issues: List[AnalysisIssue]) -> List[Tuple[str, str, str]]:
        pairs = []
        for issue in issues:
            if issue.category == IssueCategory.CONTRADICTION and len(issue.affected_rule_ids) >= 2:
                pairs.append((issue.affected_rule_ids[0], issue.affected_rule_ids[1], issue.issue_id))
        return pairs

    def _config_to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_level": self.config.analysis_level.value,
            "overlap_threshold": self.config.overlap_threshold,
            "contradiction_sensitivity": self.config.contradiction_sensitivity,
            "include_suggestions": self.config.include_suggestions,
            "focus_tiers": [t.value for t in self.config.focus_tiers],
            "focus_tags": self.config.focus_tags,
            "detailed_mode": self.config.detailed_mode,
        }

    def export_report_json(self, report: AnalysisReport, filepath: Optional[str] = None) -> str:
        data = {
            "report_id": report.report_id,
            "created_at": report.created_at.isoformat(),
            "analysis_level": report.analysis_level.value,
            "total_rules_analyzed": report.total_rules_analyzed,
            "total_issues_found": report.total_issues_found,
            "summary": report.summary,
            "tier_breakdown": report.tier_breakdown,
            "type_breakdown": report.type_breakdown,
            "recommendations": report.recommendations,
            "config_used": report.config_used,
            "duration_seconds": report.duration_seconds,
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "category": i.category.value,
                    "severity": i.severity.value,
                    "title": i.title,
                    "description": i.description,
                    "affected_rule_ids": i.affected_rule_ids,
                    "affected_rules": i.affected_rules,
                    "confidence": i.confidence,
                    "suggestion": i.suggestion,
                    "metrics": i.metrics,
                }
                for i in report.issues
            ],
        }
        json_str = json.dumps(data, indent=2, default=str)
        if filepath:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json_str, encoding="utf-8")
            self.logger.info("Report exported to %s", filepath)
        return json_str

    def export_report_yaml(self, report: AnalysisReport, filepath: Optional[str] = None) -> str:
        data = {
            "report_id": report.report_id,
            "created_at": report.created_at.isoformat(),
            "analysis_level": report.analysis_level.value,
            "total_rules_analyzed": report.total_rules_analyzed,
            "total_issues_found": report.total_issues_found,
            "summary": dict(report.summary),
            "recommendations": report.recommendations,
            "duration_seconds": report.duration_seconds,
            "issues_count_by_category": dict(Counter(i.category.value for i in report.issues)),
        }
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
        if filepath:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml_str, encoding="utf-8")
            self.logger.info("YAML report exported to %s", filepath)
        return yaml_str

    def get_issue_summary_text(self, report: AnalysisReport) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(f"RULE ANALYSIS REPORT: {report.report_id}")
        lines.append("=" * 60)
        lines.append(f"Created: {report.created_at.isoformat()}")
        lines.append(f"Level: {report.analysis_level.value}")
        lines.append(f"Rules analyzed: {report.total_rules_analyzed}")
        lines.append(f"Total issues: {report.total_issues_found}")
        lines.append(f"Duration: {report.duration_seconds:.2f}s")
        lines.append("")
        lines.append("--- Summary ---")
        for severity, count in sorted(report.summary.items()):
            lines.append(f"  {severity}: {count}")
        lines.append("")
        lines.append("--- Recommendations ---")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"  {i}. {rec}")
        lines.append("")
        lines.append("--- Issues ---")
        for i, issue in enumerate(report.issues, 1):
            lines.append(f"  [{issue.severity.value.upper()}] {issue.title}")
            lines.append(f"    {issue.description[:120]}...")
            if issue.suggestion:
                lines.append(f"    Suggestion: {issue.suggestion[:120]}...")
            lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def load_config_from_file(self, filepath: str) -> None:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")
        content = path.read_text(encoding="utf-8")
        if filepath.endswith(".yaml") or filepath.endswith(".yml"):
            data = yaml.safe_load(content)
        elif filepath.endswith(".json"):
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported config file format: {filepath}")
        if data:
            self.update_config(data)
        self.logger.info("Config loaded from %s", filepath)

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "analysis_level": {
                "type": "string",
                "enum": [e.value for e in AnalysisLevel],
                "default": "standard",
                "description": "Depth of analysis to perform",
            },
            "overlap_threshold": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.3,
                "description": "Similarity threshold for overlap detection",
            },
            "contradiction_sensitivity": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.7,
                "description": "Sensitivity for contradiction detection",
            },
            "min_pattern_similarity": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.4,
            },
            "performance_sample_size": {
                "type": "integer",
                "minimum": 1,
                "default": 100,
            },
            "unused_days_threshold": {
                "type": "integer",
                "minimum": 1,
                "default": 30,
            },
            "include_suggestions": {
                "type": "boolean",
                "default": True,
            },
            "auto_remediate_low": {
                "type": "boolean",
                "default": False,
            },
            "output_format": {
                "type": "string",
                "enum": ["json", "yaml", "text"],
                "default": "json",
            },
            "focus_tiers": {
                "type": "array",
                "items": {"type": "string", "enum": [t.value for t in RuleTier]},
            },
            "focus_tags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "exclude_rules": {
                "type": "array",
                "items": {"type": "string"},
            },
        }

    def get_analysis_stats(self, report: AnalysisReport) -> Dict[str, Any]:
        return {
            "report_id": report.report_id,
            "duration": report.duration_seconds,
            "rules_per_second": report.total_rules_analyzed / report.duration_seconds if report.duration_seconds > 0 else 0,
            "issues_per_rule": report.total_issues_found / report.total_rules_analyzed if report.total_rules_analyzed > 0 else 0,
            "most_common_category": Counter(i.category.value for i in report.issues).most_common(1)[0][0] if report.issues else "none",
            "most_common_severity": Counter(i.severity.value for i in report.issues).most_common(1)[0][0] if report.issues else "none",
            "avg_confidence": sum(i.confidence for i in report.issues) / len(report.issues) if report.issues else 0.0,
            "issues_with_suggestions": sum(1 for i in report.issues if i.suggestion is not None),
            "coverage_pct": (
                (report.total_rules_analyzed - len(report.unused_rule_ids)) / report.total_rules_analyzed * 100
                if report.total_rules_analyzed > 0
                else 0
            ),
        }
