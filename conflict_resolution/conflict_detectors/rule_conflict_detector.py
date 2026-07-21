"""Detect structural and logical conflicts between rules."""
import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ConflictType(str, Enum):
    KEYWORD_OVERLAP = "keyword_overlap"
    PATTERN_OVERLAP = "pattern_overlap"
    DOMAIN_OVERLAP = "domain_overlap"
    ENFORCEMENT_MISMATCH = "enforcement_mismatch"
    ACTION_CLASH = "action_clash"
    SCOPE_NESTING = "scope_nesting"
    CONDITION_CONTRADICTION = "condition_contradiction"


class ConflictSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class RuleConflict:
    rule_1_id: str
    rule_2_id: str
    conflict_type: ConflictType
    description: str
    severity: ConflictSeverity
    affected_fields: List[str] = field(default_factory=list)
    resolution_suggestion: Optional[str] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)


class RuleConflictDetector:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.conflicts: List[RuleConflict] = []
        self.config = config or {}
        self._overlap_threshold = self.config.get("overlap_threshold", 0.3)
        self._max_rules_per_batch = self.config.get("max_rules_per_batch", 500)
        logger.info("RuleConflictDetector initialized (threshold=%.2f, batch=%d)",
                     self._overlap_threshold, self._max_rules_per_batch)

    def detect_conflicts(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[RuleConflict]:
        candidates: List[RuleConflict] = []

        kw_conflict = self._detect_keyword_overlap(rule_1, rule_2)
        if kw_conflict:
            candidates.append(kw_conflict)

        pat_conflict = self._detect_pattern_overlap(rule_1, rule_2)
        if pat_conflict:
            candidates.append(pat_conflict)

        dom_conflict = self._detect_domain_overlap(rule_1, rule_2)
        if dom_conflict:
            candidates.append(dom_conflict)

        enf_conflict = self._detect_enforcement_mismatch(rule_1, rule_2)
        if enf_conflict:
            candidates.append(enf_conflict)

        act_conflict = self._detect_action_clash(rule_1, rule_2)
        if act_conflict:
            candidates.append(act_conflict)

        if not candidates:
            return None

        worst = max(candidates, key=lambda c: list(ConflictSeverity).index(c.severity))
        self.conflicts.append(worst)
        return worst

    def detect_all_conflicts(self, rules: List[Dict[str, Any]]) -> List[RuleConflict]:
        if len(rules) > self._max_rules_per_batch:
            logger.warning("Batch size %d exceeds limit %d, truncating",
                           len(rules), self._max_rules_per_batch)
            rules = rules[:self._max_rules_per_batch]

        seen: Set[Tuple[str, str]] = set()
        results: List[RuleConflict] = []

        for i, rule_1 in enumerate(rules):
            for rule_2 in rules[i + 1:]:
                rid1 = rule_1.get("id", "unknown")
                rid2 = rule_2.get("id", "unknown")
                pair = (min(rid1, rid2), max(rid1, rid2))
                if pair in seen:
                    continue
                seen.add(pair)

                conflict = self.detect_conflicts(rule_1, rule_2)
                if conflict:
                    results.append(conflict)

        return results

    def get_conflict_summary(self) -> Dict[str, Any]:
        by_severity: Dict[str, int] = {}
        by_type: Dict[str, int] = {}

        for c in self.conflicts:
            by_severity[c.severity.value] = by_severity.get(c.severity.value, 0) + 1
            by_type[c.conflict_type.value] = by_type.get(c.conflict_type.value, 0) + 1

        return {
            "total_conflicts": len(self.conflicts),
            "by_severity": by_severity,
            "by_type": by_type,
            "most_common_severity": max(by_severity, key=by_severity.get) if by_severity else None,
            "most_common_type": max(by_type, key=by_type.get) if by_type else None
        }

    def _detect_keyword_overlap(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> Optional[RuleConflict]:
        kw1 = set(r1.get("patterns", []) or r1.get("keywords", []))
        kw2 = set(r2.get("patterns", []) or r2.get("keywords", []))
        if not kw1 or not kw2:
            return None

        overlap = kw1 & kw2
        if not overlap:
            return None

        ratio = len(overlap) / max(len(kw1 | kw2), 1)
        if ratio < self._overlap_threshold:
            return None

        severity = ConflictSeverity.HIGH if ratio > 0.6 else (
            ConflictSeverity.MEDIUM if ratio > 0.3 else ConflictSeverity.LOW
        )

        return RuleConflict(
            rule_1_id=r1.get("id", "unknown"),
            rule_2_id=r2.get("id", "unknown"),
            conflict_type=ConflictType.KEYWORD_OVERLAP,
            description=f"Keyword overlap ({ratio:.0%}): {', '.join(sorted(overlap)[:5])}",
            severity=severity,
            affected_fields=["patterns", "keywords"],
            resolution_suggestion="Merge overlapping patterns into a combined rule"
        )

    def _detect_pattern_overlap(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> Optional[RuleConflict]:
        pat1 = r1.get("pattern", "")
        pat2 = r2.get("pattern", "")
        if not pat1 or not pat2:
            return None

        try:
            compiled_1 = re.compile(pat1)
            compiled_2 = re.compile(pat2)
        except re.error:
            return None

        test_strings = [
            "test content for rule matching",
            "sample input validation",
            "default pattern check"
        ]

        match_1 = sum(1 for t in test_strings if compiled_1.search(t))
        match_2 = sum(1 for t in test_strings if compiled_2.search(t))

        if match_1 > 0 and match_2 > 0:
            return RuleConflict(
                rule_1_id=r1.get("id", "unknown"),
                rule_2_id=r2.get("id", "unknown"),
                conflict_type=ConflictType.PATTERN_OVERLAP,
                description=f"Both patterns match {match_1}/{match_2} of test inputs",
                severity=ConflictSeverity.MEDIUM,
                affected_fields=["pattern"],
                resolution_suggestion="Narrow one pattern scope or combine into compound rule"
            )
        return None

    def _detect_domain_overlap(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> Optional[RuleConflict]:
        dom1 = set(r1.get("domains", []) or r1.get("tags", []))
        dom2 = set(r2.get("domains", []) or r2.get("tags", []))
        if not dom1 or not dom2:
            return None

        overlap = dom1 & dom2
        if not overlap:
            return None

        return RuleConflict(
            rule_1_id=r1.get("id", "unknown"),
            rule_2_id=r2.get("id", "unknown"),
            conflict_type=ConflictType.DOMAIN_OVERLAP,
            description=f"Shared domain(s): {', '.join(sorted(overlap)[:3])}",
            severity=ConflictSeverity.LOW,
            affected_fields=["domains", "tags"],
            resolution_suggestion="Assign unique domain scopes or set explicit priority"
        )

    def _detect_enforcement_mismatch(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> Optional[RuleConflict]:
        enf1 = r1.get("enforcement", "advisory")
        enf2 = r2.get("enforcement", "advisory")
        tier1 = r1.get("tier", "preference")
        tier2 = r2.get("tier", "preference")

        tier_order = {"safety": 0, "operational": 1, "preference": 2}
        enf_order = {"strict": 2, "advisory": 1, "adaptive": 0}

        order1 = tier_order.get(tier1, 2)
        order2 = tier_order.get(tier2, 2)

        if order1 < order2 and enf_order.get(enf1, 1) < enf_order.get(enf2, 1):
            return RuleConflict(
                rule_1_id=r1.get("id", "unknown"),
                rule_2_id=r2.get("id", "unknown"),
                conflict_type=ConflictType.ENFORCEMENT_MISMATCH,
                description=f"Higher-tier rule has weaker enforcement: {tier1}={enf1}, {tier2}={enf2}",
                severity=ConflictSeverity.HIGH,
                affected_fields=["tier", "enforcement"],
                resolution_suggestion=f"Set enforcement for {tier1} to 'strict'"
            )
        return None

    def _detect_action_clash(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> Optional[RuleConflict]:
        action_pairs = [("allow", "deny"), ("block", "pass"), ("log", "silent")]
        act1 = r1.get("action", "").lower()
        act2 = r2.get("action", "").lower()
        if not act1 or not act2:
            return None

        for a, b in action_pairs:
            if (act1 == a and act2 == b) or (act1 == b and act2 == a):
                return RuleConflict(
                    rule_1_id=r1.get("id", "unknown"),
                    rule_2_id=r2.get("id", "unknown"),
                    conflict_type=ConflictType.ACTION_CLASH,
                    description=f"Clashing actions: '{act1}' vs '{act2}'",
                    severity=ConflictSeverity.CRITICAL,
                    affected_fields=["action"],
                    resolution_suggestion=f"Resolve {act1}/{act2} conflict via tier priority or explicit precedence"
                )
        return None

    def clear(self) -> None:
        self.conflicts.clear()
        logger.debug("Conflict list cleared")
