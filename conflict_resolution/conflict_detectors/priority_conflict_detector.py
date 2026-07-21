"""Detect priority conflicts between rules across tiers and within same tier."""
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class PriorityConflictType(str, Enum):
    TIER_INVERSION = "tier_inversion"
    SAME_TIER_GAP = "same_tier_gap"
    DUPLICATE_PRIORITY = "duplicate_priority"
    CHAIN_INVERSION = "chain_inversion"
    NEGATIVE_PRIORITY = "negative_priority"


@dataclass
class PriorityConflict:
    rule_1_id: str
    rule_2_id: str
    tier_1: str
    tier_2: str
    priority_1: int
    priority_2: int
    conflict_type: PriorityConflictType
    description: str
    detected_at: datetime = field(default_factory=datetime.utcnow)


class PriorityConflictDetector:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.tier_hierarchy: Dict[str, int] = {
            "safety": 1,
            "operational": 2,
            "preference": 3
        }
        self._priority_gap_threshold = self.config.get("priority_gap_threshold", 50)
        self._max_chain_depth = self.config.get("max_chain_depth", 10)
        logger.info("PriorityConflictDetector initialized (gap_threshold=%d, max_depth=%d)",
                     self._priority_gap_threshold, self._max_chain_depth)

    def detect_priority_conflict(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[PriorityConflict]:
        tier_1 = rule_1.get("tier", "preference")
        tier_2 = rule_2.get("tier", "preference")
        pri_1 = int(rule_1.get("priority", 100))
        pri_2 = int(rule_2.get("priority", 100))
        rid1 = rule_1.get("id", "unknown")
        rid2 = rule_2.get("id", "unknown")

        if pri_1 < 0 or pri_2 < 0:
            return PriorityConflict(
                rule_1_id=rid1, rule_2_id=rid2,
                tier_1=tier_1, tier_2=tier_2,
                priority_1=pri_1, priority_2=pri_2,
                conflict_type=PriorityConflictType.NEGATIVE_PRIORITY,
                description=f"Negative priority value: {min(pri_1, pri_2)}"
            )

        if tier_1 == tier_2:
            gap = abs(pri_1 - pri_2)
            if gap > self._priority_gap_threshold:
                return PriorityConflict(
                    rule_1_id=rid1, rule_2_id=rid2,
                    tier_1=tier_1, tier_2=tier_2,
                    priority_1=pri_1, priority_2=pri_2,
                    conflict_type=PriorityConflictType.SAME_TIER_GAP,
                    description=f"Large priority gap in {tier_1}: {pri_1} vs {pri_2} (delta={gap})"
                )
            return None

        order_1 = self.tier_hierarchy.get(tier_1, 999)
        order_2 = self.tier_hierarchy.get(tier_2, 999)

        if order_1 < order_2 and pri_1 <= pri_2:
            return PriorityConflict(
                rule_1_id=rid1, rule_2_id=rid2,
                tier_1=tier_1, tier_2=tier_2,
                priority_1=pri_1, priority_2=pri_2,
                conflict_type=PriorityConflictType.TIER_INVERSION,
                description=f"Higher-tier rule ({tier_1}) has lower/existing priority ({pri_1}) "
                            f"than lower-tier ({tier_2}, {pri_2})"
            )

        return None

    def detect_chain_inversions(
        self,
        rules: List[Dict[str, Any]]
    ) -> List[PriorityConflict]:
        sorted_rules = sorted(
            rules,
            key=lambda r: (
                self.tier_hierarchy.get(r.get("tier", "preference"), 999),
                r.get("priority", 100)
            )
        )

        inversions: List[PriorityConflict] = []
        depth = min(len(sorted_rules), self._max_chain_depth)

        for i in range(depth - 1):
            cur = sorted_rules[i]
            nxt = sorted_rules[i + 1]

            cur_tier_order = self.tier_hierarchy.get(cur.get("tier", "preference"), 999)
            nxt_tier_order = self.tier_hierarchy.get(nxt.get("tier", "preference"), 999)
            cur_pri = int(cur.get("priority", 100))
            nxt_pri = int(nxt.get("priority", 100))

            if cur_tier_order == nxt_tier_order and cur_pri < nxt_pri:
                inversions.append(PriorityConflict(
                    rule_1_id=cur.get("id", "unknown"),
                    rule_2_id=nxt.get("id", "unknown"),
                    tier_1=cur.get("tier", "preference"),
                    tier_2=nxt.get("tier", "preference"),
                    priority_1=cur_pri,
                    priority_2=nxt_pri,
                    conflict_type=PriorityConflictType.CHAIN_INVERSION,
                    description=f"Chain inversion at position {i}: priority {cur_pri} < {nxt_pri} "
                                f"in chain order"
                ))

        return inversions

    def detect_duplicate_priorities(
        self,
        rules: List[Dict[str, Any]]
    ) -> List[PriorityConflict]:
        tier_buckets: Dict[str, Dict[int, List[str]]] = {}

        for rule in rules:
            tier = rule.get("tier", "preference")
            priority = int(rule.get("priority", 100))
            rid = rule.get("id", "unknown")

            if tier not in tier_buckets:
                tier_buckets[tier] = {}
            if priority not in tier_buckets[tier]:
                tier_buckets[tier][priority] = []
            tier_buckets[tier][priority].append(rid)

        duplicates: List[PriorityConflict] = []
        for tier, pri_map in tier_buckets.items():
            for priority, rids in pri_map.items():
                if len(rids) > 1:
                    for i in range(len(rids)):
                        for j in range(i + 1, len(rids)):
                            duplicates.append(PriorityConflict(
                                rule_1_id=rids[i],
                                rule_2_id=rids[j],
                                tier_1=tier,
                                tier_2=tier,
                                priority_1=priority,
                                priority_2=priority,
                                conflict_type=PriorityConflictType.DUPLICATE_PRIORITY,
                                description=f"Duplicate priority {priority} in tier {tier}"
                            ))
        return duplicates

    def detect_all_priority_conflicts(
        self,
        rules: List[Dict[str, Any]]
    ) -> List[PriorityConflict]:
        results: List[PriorityConflict] = []
        seen: Set[Tuple[str, str]] = set()

        for i, rule_1 in enumerate(rules):
            for rule_2 in rules[i + 1:]:
                rid1 = rule_1.get("id", "unknown")
                rid2 = rule_2.get("id", "unknown")
                pair = (min(rid1, rid2), max(rid1, rid2))
                if pair in seen:
                    continue
                seen.add(pair)

                conflict = self.detect_priority_conflict(rule_1, rule_2)
                if conflict:
                    results.append(conflict)

        results.extend(self.detect_chain_inversions(rules))
        results.extend(self.detect_duplicate_priorities(rules))

        return results

    def get_tier_priority(self, tier: str) -> int:
        return self.tier_hierarchy.get(tier, 999)

    def get_priority_summary(self, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        conflicts = self.detect_all_priority_conflicts(rules)
        by_type: Dict[str, int] = {}
        for c in conflicts:
            by_type[c.conflict_type.value] = by_type.get(c.conflict_type.value, 0) + 1

        tier_counts: Dict[str, int] = {}
        for rule in rules:
            t = rule.get("tier", "preference")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        return {
            "total_conflicts": len(conflicts),
            "by_type": by_type,
            "tier_counts": tier_counts,
            "has_inversions": any(c.conflict_type == PriorityConflictType.CHAIN_INVERSION for c in conflicts),
            "has_duplicates": any(c.conflict_type == PriorityConflictType.DUPLICATE_PRIORITY for c in conflicts)
        }
