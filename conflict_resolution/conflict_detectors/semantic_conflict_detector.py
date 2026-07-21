"""Detect semantic contradictions between rules using lexical and structural analysis."""
import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class SemanticConflictType(str, Enum):
    CONTRADICTORY_TERMS = "contradictory_terms"
    OPPOSING_ACTIONS = "opposing_actions"
    CONDITION_INVERSE = "condition_inverse"
    SCOPE_MISMATCH = "scope_mismatch"
    TEMPORAL_CONTRADICTION = "temporal_contradiction"


@dataclass
class SemanticConflict:
    rule_1_id: str
    rule_2_id: str
    conflict_type: SemanticConflictType
    description: str
    matched_terms: List[str] = field(default_factory=list)
    confidence: float = 0.0
    detected_at: datetime = field(default_factory=datetime.utcnow)


class SemanticConflictDetector:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._confidence_threshold = self.config.get("confidence_threshold", 0.4)

        self.contradiction_pairs: List[Tuple[str, str]] = [
            ("allow", "deny"), ("enable", "disable"),
            ("require", "forbid"), ("must", "must_not"),
            ("include", "exclude"), ("permit", "prohibit"),
            ("grant", "revoke"), ("approve", "reject"),
            ("allowlist", "blocklist"), ("whitelist", "blacklist"),
            ("pass", "block"), ("accept", "reject"),
        ]

        self.opposing_actions: List[Tuple[str, str, float]] = [
            ("read", "write", 0.5),
            ("create", "delete", 1.0),
            ("publish", "archive", 0.7),
            ("open", "close", 0.8),
            ("start", "stop", 0.9),
            ("enable", "disable", 1.0),
            ("lock", "unlock", 0.6),
            ("encrypt", "decrypt", 0.7),
        ]

        self.inverse_condition_patterns: List[Tuple[str, str, float]] = [
            (r"if\s+(not\s+)?(\w+)", r"if\s+(not\s+)?(\w+)", 0.8),
            (r"when\s+(\w+)", r"unless\s+(\w+)", 0.85),
        ]

        self._stop_words: Set[str] = {
            "the", "a", "an", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "shall",
            "should", "may", "might", "can", "could", "to",
            "of", "in", "for", "on", "with", "at", "by", "from"
        }

        logger.info("SemanticConflictDetector initialized (confidence=%.2f)",
                     self._confidence_threshold)

    def detect_semantic_conflict(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        candidates: List[SemanticConflict] = []

        term_conflict = self._detect_contradictory_terms(rule_1, rule_2)
        if term_conflict:
            candidates.append(term_conflict)

        action_conflict = self._detect_opposing_actions(rule_1, rule_2)
        if action_conflict:
            candidates.append(action_conflict)

        cond_conflict = self._detect_condition_inverse(rule_1, rule_2)
        if cond_conflict:
            candidates.append(cond_conflict)

        scope_conflict = self._detect_scope_mismatch(rule_1, rule_2)
        if scope_conflict:
            candidates.append(scope_conflict)

        if not candidates:
            return None

        return max(candidates, key=lambda c: c.confidence)

    def detect_all_semantic_conflicts(
        self,
        rules: List[Dict[str, Any]]
    ) -> List[SemanticConflict]:
        results: List[SemanticConflict] = []
        seen: Set[Tuple[str, str]] = set()

        for i, rule_1 in enumerate(rules):
            for rule_2 in rules[i + 1:]:
                rid1 = rule_1.get("id", "unknown")
                rid2 = rule_2.get("id", "unknown")
                pair = (min(rid1, rid2), max(rid1, rid2))
                if pair in seen:
                    continue
                seen.add(pair)

                conflict = self.detect_semantic_conflict(rule_1, rule_2)
                if conflict and conflict.confidence >= self._confidence_threshold:
                    results.append(conflict)

        return results

    def _normalize_text(self, text: str) -> Set[str]:
        tokens = re.findall(r"[a-zA-Z_]\w*", text.lower())
        return {t for t in tokens if t not in self._stop_words and len(t) > 2}

    def _detect_contradictory_terms(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        text_1 = self._extract_text(rule_1)
        text_2 = self._extract_text(rule_2)
        tokens_1 = self._normalize_text(text_1)
        tokens_2 = self._normalize_text(text_2)

        for pos_term, neg_term in self.contradiction_pairs:
            pos_in_1 = pos_term in tokens_1
            pos_in_2 = pos_term in tokens_2
            neg_in_1 = neg_term in tokens_1
            neg_in_2 = neg_term in tokens_2

            if (pos_in_1 and neg_in_2) or (neg_in_1 and pos_in_2):
                matched = [pos_term, neg_term]
                return SemanticConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    conflict_type=SemanticConflictType.CONTRADICTORY_TERMS,
                    description=f"Contradictory terms: '{pos_term}' vs '{neg_term}'",
                    matched_terms=matched,
                    confidence=0.9
                )
        return None

    def _detect_opposing_actions(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        action_1 = rule_1.get("action", "").lower()
        action_2 = rule_2.get("action", "").lower()
        if not action_1 or not action_2:
            return None

        for act_a, act_b, base_conf in self.opposing_actions:
            if (action_1 == act_a and action_2 == act_b) or \
               (action_1 == act_b and action_2 == act_a):
                return SemanticConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    conflict_type=SemanticConflictType.OPPOSING_ACTIONS,
                    description=f"Opposing actions: '{action_1}' vs '{action_2}'",
                    matched_terms=[action_1, action_2],
                    confidence=base_conf
                )
        return None

    def _detect_condition_inverse(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        cond_1 = rule_1.get("condition", "")
        cond_2 = rule_2.get("condition", "")
        if not cond_1 or not cond_2:
            return None

        cond_1_lower = cond_1.lower()
        cond_2_lower = cond_2.lower()

        for pat_a, pat_b, conf in self.inverse_condition_patterns:
            match_a = re.search(pat_a, cond_1_lower)
            match_b = re.search(pat_b, cond_2_lower)
            match_c = re.search(pat_b, cond_1_lower)
            match_d = re.search(pat_a, cond_2_lower)

            if (match_a and match_b) or (match_c and match_d):
                return SemanticConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    conflict_type=SemanticConflictType.CONDITION_INVERSE,
                    description=f"Inverse conditions detected between rules",
                    matched_terms=[cond_1[:50], cond_2[:50]],
                    confidence=conf
                )
        return None

    def _detect_scope_mismatch(
        self,
        rule_1: Dict[str, Any],
        rule_2: Dict[str, Any]
    ) -> Optional[SemanticConflict]:
        scope_1 = rule_1.get("scope", "").lower()
        scope_2 = rule_2.get("scope", "").lower()
        if not scope_1 or not scope_2:
            return None

        scope_pairs: List[Tuple[str, str, float]] = [
            ("global", "local", 0.6),
            ("all", "specific", 0.5),
            ("broad", "narrow", 0.5),
            ("public", "private", 0.7),
        ]

        for s_a, s_b, conf in scope_pairs:
            if (s_a in scope_1 and s_b in scope_2) or \
               (s_b in scope_1 and s_a in scope_2):
                return SemanticConflict(
                    rule_1_id=rule_1.get("id", "unknown"),
                    rule_2_id=rule_2.get("id", "unknown"),
                    conflict_type=SemanticConflictType.SCOPE_MISMATCH,
                    description=f"Scope mismatch: '{scope_1}' vs '{scope_2}'",
                    matched_terms=[scope_1, scope_2],
                    confidence=conf
                )
        return None

    def _extract_text(self, rule: Dict[str, Any]) -> str:
        parts = [
            rule.get("description", ""),
            rule.get("name", ""),
            rule.get("pattern", ""),
            rule.get("condition", ""),
            rule.get("action", ""),
            *(rule.get("tags", [])),
        ]
        return " ".join(str(p) for p in parts if p)
