"""
Profanity filter - comprehensive profanity detection with Levenshtein-based fuzzy
matching, leetspeak/substitution detection, multi-language support, context-aware
filtering, and statistical tracking.
"""

import copy
import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType

logger = logging.getLogger(__name__)


class ProfanityTier(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    EXTREME = "extreme"


class ProfanityCategory(str, Enum):
    GENERAL = "general"
    SLUR = "slur"
    SEXUAL = "sexual"
    VIOLENT = "violent"
    INSULT = "insult"
    DISCRIMINATORY = "discriminatory"
    BLASPHEMY = "blasphemy"
    HARASSMENT = "harassment"
    CUSTOM = "custom"


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    LEETSPEAK = "leetspeak"
    SUBSTITUTION = "substitution"
    PARTIAL = "partial"
    COMPOUND = "compound"


@dataclass
class ProfanityEntry:
    word: str
    tier: ProfanityTier = ProfanityTier.MODERATE
    category: ProfanityCategory = ProfanityCategory.GENERAL
    languages: List[str] = field(default_factory=lambda: ["en"])
    weight: float = 1.0
    allow_substitutions: bool = True
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AllowlistEntry:
    word: str
    reason: str = ""
    created_by: str = "system"
    expires_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class ProfanityMatch:
    word: str
    matched: str
    tier: ProfanityTier
    category: ProfanityCategory
    match_type: MatchType
    confidence: float
    score: float
    start_pos: int
    end_pos: int
    distance: float = 0.0
    language: str = "en"
    context_before: str = ""
    context_after: str = ""


@dataclass
class ProfanityStats:
    total_evaluations: int = 0
    total_matches: int = 0
    total_blocks: int = 0
    total_warnings: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    match_rate: float = 0.0
    false_positive_rate: float = 0.0
    avg_confidence: float = 0.0
    tier_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    category_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    match_type_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    language_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    peak_hours: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    total_processing_time_ms: int = 0
    avg_processing_time_ms: float = 0.0
    last_evaluated: Optional[datetime] = None
    first_evaluated: Optional[datetime] = None
    top_matched_words: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_evaluation(self, processing_time_ms: int, matches: List[ProfanityMatch],
                          blocked: bool = False, warned: bool = False) -> None:
        self.total_evaluations += 1
        self.total_processing_time_ms += processing_time_ms
        self.avg_processing_time_ms = self.total_processing_time_ms / self.total_evaluations
        now = datetime.utcnow()
        self.last_evaluated = now
        if self.first_evaluated is None:
            self.first_evaluated = now
        if matches:
            self.total_matches += len(matches)
            for m in matches:
                self.tier_counts[m.tier.value] += 1
                self.category_counts[m.category.value] += 1
                self.match_type_counts[m.match_type.value] += 1
                self.language_counts[m.language] += 1
                self.top_matched_words[m.word] += 1
        date_key = now.strftime("%Y-%m-%d")
        self.daily_counts[date_key] += 1
        hour_key = now.hour
        self.peak_hours[hour_key] += 1
        if blocked:
            self.total_blocks += 1
        if warned:
            self.total_warnings += 1
        if self.total_evaluations > 0:
            self.match_rate = self.total_matches / self.total_evaluations
        total_detections = self.total_matches + self.false_positives
        if total_detections > 0:
            self.false_positive_rate = self.false_positives / total_detections

    def record_false_positive(self) -> None:
        self.false_positives += 1

    def record_false_negative(self) -> None:
        self.false_negatives += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_matches": self.total_matches,
            "total_blocks": self.total_blocks,
            "total_warnings": self.total_warnings,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "match_rate": round(self.match_rate, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "tier_counts": dict(self.tier_counts),
            "category_counts": dict(self.category_counts),
            "match_type_counts": dict(self.match_type_counts),
            "language_counts": dict(self.language_counts),
            "peak_hours": dict(self.peak_hours),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
            "top_matched": dict(sorted(self.top_matched_words.items(), key=lambda x: -x[1])[:20]),
        }

    def reset(self) -> None:
        self.total_evaluations = 0
        self.total_matches = 0
        self.total_blocks = 0
        self.total_warnings = 0
        self.false_positives = 0
        self.false_negatives = 0
        self.match_rate = 0.0
        self.false_positive_rate = 0.0
        self.avg_confidence = 0.0
        self.tier_counts.clear()
        self.category_counts.clear()
        self.match_type_counts.clear()
        self.daily_counts.clear()
        self.language_counts.clear()
        self.peak_hours.clear()
        self.total_processing_time_ms = 0
        self.avg_processing_time_ms = 0.0
        self.last_evaluated = None
        self.first_evaluated = None
        self.top_matched_words.clear()


PROFANITY_TIER_SCORES = {
    ProfanityTier.MILD: 5,
    ProfanityTier.MODERATE: 15,
    ProfanityTier.SEVERE: 30,
    ProfanityTier.EXTREME: 60,
}

SUBSTITUTION_MAP: Dict[str, str] = {
    "0": "o",
    "1": "i",
    "2": "z",
    "3": "e",
    "4": "a",
    "5": "s",
    "6": "g",
    "7": "t",
    "8": "b",
    "9": "p",
    "@": "a",
    "$": "s",
    "!": "i",
    "+": "t",
    "#": "h",
    "*": "a",
    "%": "o",
    "&": "e",
    "(": "c",
    ")": "c",
    "<": "l",
    ">": "l",
    "_": "",
    "-": "",
    ".": "",
    ",": "",
    "'": "",
    '"': "",
    "|": "i",
    "{": "c",
    "}": "c",
    "[": "c",
    "]": "c",
    "\\": "",
    "/": "",
    ":": "",
    ";": "",
    "~": "",
    "`": "",
}

DEFAULT_PROFANITY_WORD_LIST: Dict[ProfanityCategory, List[Dict[str, Any]]] = {
    ProfanityCategory.GENERAL: [
        {"word": "damn", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "hell", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "crap", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "shit", "tier": ProfanityTier.MODERATE, "weight": 1.0},
        {"word": "fuck", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "ass", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "bitch", "tier": ProfanityTier.SEVERE, "weight": 1.2},
        {"word": "bastard", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "bullshit", "tier": ProfanityTier.MODERATE, "weight": 1.0},
        {"word": "dick", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "piss", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "suck", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "cock", "tier": ProfanityTier.SEVERE, "weight": 1.0},
        {"word": "douche", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "twat", "tier": ProfanityTier.SEVERE, "weight": 1.0},
        {"word": "wanker", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "arse", "tier": ProfanityTier.MILD, "weight": 0.5, "languages": ["en-gb"]},
        {"word": "bloody", "tier": ProfanityTier.MILD, "weight": 0.5, "languages": ["en-gb"]},
        {"word": "bugger", "tier": ProfanityTier.MODERATE, "weight": 0.8, "languages": ["en-gb"]},
        {"word": "cunt", "tier": ProfanityTier.EXTREME, "weight": 2.0},
        {"word": "motherfucker", "tier": ProfanityTier.EXTREME, "weight": 2.0},
    ],
    ProfanityCategory.SLUR: [
        {"word": "nigger", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "faggot", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "kike", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "spic", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "chink", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "wetback", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "tranny", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "dyke", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "gook", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "raghead", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "cameljockey", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "sandnigger", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "paki", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "abo", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "redskin", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "squaw", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "towelhead", "tier": ProfanityTier.EXTREME, "weight": 3.0},
        {"word": "zipperhead", "tier": ProfanityTier.EXTREME, "weight": 3.0},
    ],
    ProfanityCategory.SEXUAL: [
        {"word": "whore", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "slut", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "porn", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "rape", "tier": ProfanityTier.EXTREME, "weight": 2.5},
        {"word": "molest", "tier": ProfanityTier.EXTREME, "weight": 2.5},
        {"word": "incest", "tier": ProfanityTier.EXTREME, "weight": 2.5},
        {"word": "pedophile", "tier": ProfanityTier.EXTREME, "weight": 2.5},
        {"word": "prostitute", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "orgasm", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "masturbate", "tier": ProfanityTier.MODERATE, "weight": 0.8},
    ],
    ProfanityCategory.VIOLENT: [
        {"word": "kill", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "murder", "tier": ProfanityTier.EXTREME, "weight": 2.0},
        {"word": "slaughter", "tier": ProfanityTier.EXTREME, "weight": 2.0},
        {"word": "torture", "tier": ProfanityTier.EXTREME, "weight": 2.0},
        {"word": "execute", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "massacre", "tier": ProfanityTier.EXTREME, "weight": 2.0},
    ],
    ProfanityCategory.INSULT: [
        {"word": "idiot", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "moron", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "retard", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "imbecile", "tier": ProfanityTier.MODERATE, "weight": 0.8},
        {"word": "loser", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "stupid", "tier": ProfanityTier.MILD, "weight": 0.4},
        {"word": "dumb", "tier": ProfanityTier.MILD, "weight": 0.4},
        {"word": "ugly", "tier": ProfanityTier.MILD, "weight": 0.4},
        {"word": "fat", "tier": ProfanityTier.MILD, "weight": 0.4},
        {"word": "pathetic", "tier": ProfanityTier.MILD, "weight": 0.5},
        {"word": "worthless", "tier": ProfanityTier.MODERATE, "weight": 0.8},
    ],
    ProfanityCategory.DISCRIMINATORY: [
        {"word": "racist", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "sexist", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "homophobic", "tier": ProfanityTier.SEVERE, "weight": 1.5},
        {"word": "transphobic", "tier": ProfanityTier.SEVERE, "weight": 1.5},
    ],
}


class ProfanityFilter:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.filter_id = str(uuid.uuid4())[:8]
        self._profanity_list: Dict[str, ProfanityEntry] = {}
        self._allowlist: Dict[str, AllowlistEntry] = {}
        self._categories: Dict[ProfanityCategory, List[str]] = defaultdict(list)
        self._stats = ProfanityStats()
        self._enable_fuzzy = self.config.get("enable_fuzzy", True)
        self._fuzzy_threshold = self.config.get("fuzzy_threshold", 0.8)
        self._enable_substitution = self.config.get("enable_substitution", True)
        self._enable_context_analysis = self.config.get("enable_context_analysis", True)
        self._block_threshold = self.config.get("block_threshold", 50)
        self._warn_threshold = self.config.get("warn_threshold", 15)
        self._max_distance = self.config.get("max_distance", 2)
        self._context_window = self.config.get("context_window", 50)
        self._version = "2.0.0"

        self._init_default_word_list()
        self.logger.info("ProfanityFilter initialized (id=%s, version=%s, words=%d)",
                         self.filter_id, self._version, len(self._profanity_list))

    def _init_default_word_list(self) -> None:
        for category, words in DEFAULT_PROFANITY_WORD_LIST.items():
            for entry in words:
                word_key = entry["word"].lower()
                pe = ProfanityEntry(
                    word=word_key,
                    tier=entry.get("tier", ProfanityTier.MODERATE),
                    category=category,
                    languages=entry.get("languages", ["en"]),
                    weight=entry.get("weight", 1.0),
                    allow_substitutions=entry.get("allow_substitutions", True),
                )
                if word_key not in self._profanity_list:
                    self._profanity_list[word_key] = pe
                    self._categories[category].append(word_key)

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            s1, s2 = s2, s1
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr_row.append(min(
                    curr_row[j] + 1,
                    prev_row[j + 1] + 1,
                    prev_row[j] + cost,
                ))
            prev_row = curr_row
        return prev_row[-1]

    def _fuzzy_similarity(self, word: str, target: str) -> float:
        if not word or not target:
            return 0.0
        if word == target:
            return 1.0
        distance = self._levenshtein_distance(word, target)
        max_len = max(len(word), len(target))
        if max_len == 0:
            return 1.0
        return 1.0 - (distance / max_len)

    def _normalize_substitutions(self, word: str) -> str:
        normalized = []
        for ch in word.lower():
            if ch in SUBSTITUTION_MAP:
                replacement = SUBSTITUTION_MAP[ch]
                if replacement:
                    normalized.append(replacement)
            else:
                normalized.append(ch)
        raw = "".join(normalized)
        result = []
        for ch in raw:
            if ch.isalpha():
                result.append(ch)
        return "".join(result)

    def _check_fuzzy_match(self, word: str, target: str) -> Tuple[bool, float]:
        similarity = self._fuzzy_similarity(word, target)
        if similarity >= self._fuzzy_threshold:
            return True, similarity
        return False, 0.0

    def _check_substitution_match(self, word: str, target: str) -> Tuple[bool, float]:
        normalized = self._normalize_substitutions(word)
        if normalized == target:
            return True, 1.0
        if self._enable_fuzzy:
            similarity = self._fuzzy_similarity(normalized, target)
            if similarity >= self._fuzzy_threshold:
                return True, similarity * 0.9
        return False, 0.0

    def _check_compound_match(self, word: str, target: str) -> Tuple[bool, float]:
        stripped = re.sub(r'[^a-zA-Z0-9]', '', word).lower()
        target_clean = re.sub(r'[^a-zA-Z0-9]', '', target).lower()
        if stripped == target_clean:
            return True, 1.0
        if target_clean in stripped or stripped in target_clean:
            if min(len(stripped), len(target_clean)) / max(len(stripped), len(target_clean), 1) > 0.6:
                return True, 0.7
        return False, 0.0

    def _is_allowlisted(self, word: str, context: Optional[str] = None) -> bool:
        normalized = word.lower().strip()
        now = datetime.utcnow()
        for entry in self._allowlist.values():
            if not entry.is_active:
                continue
            if entry.expires_at and now > entry.expires_at:
                continue
            if entry.word.lower() == normalized:
                return True
            if context and entry.word.lower() in context.lower():
                return True
        return False

    def _extract_context(self, content: str, pos: int, length: int) -> Tuple[str, str]:
        start = max(0, pos - self._context_window)
        end = min(len(content), pos + length + self._context_window)
        before = content[start:pos]
        after = content[pos + length:end]
        return before.strip(), after.strip()

    def _detect_language(self, content: str) -> str:
        if not content.strip():
            return "en"
        sample = content[:300].lower()
        lang_scores: Dict[str, int] = defaultdict(int)
        for lang, pattern in LANGUAGE_PATTERNS.items():
            matches = len(pattern.findall(sample))
            if matches > 0:
                lang_scores[lang] = matches
        if not lang_scores:
            return "en"
        return max(lang_scores, key=lang_scores.get)

    def add_word(self, word: str, tier: ProfanityTier = ProfanityTier.MODERATE,
                 category: ProfanityCategory = ProfanityCategory.GENERAL,
                 languages: Optional[List[str]] = None,
                 weight: float = 1.0,
                 allow_substitutions: bool = True) -> ProfanityEntry:
        word_key = word.lower().strip()
        if not word_key:
            raise ValueError("Word cannot be empty")
        pe = ProfanityEntry(
            word=word_key,
            tier=tier,
            category=category,
            languages=languages or ["en"],
            weight=weight,
            allow_substitutions=allow_substitutions,
        )
        self._profanity_list[word_key] = pe
        self._categories[category].append(word_key)
        self.logger.info("Added profanity word '%s' (tier=%s, category=%s)", word_key, tier.value, category.value)
        return pe

    def remove_word(self, word: str) -> bool:
        word_key = word.lower().strip()
        if word_key not in self._profanity_list:
            return False
        entry = self._profanity_list.pop(word_key)
        cat = entry.category
        if word_key in self._categories[cat]:
            self._categories[cat].remove(word_key)
        self.logger.info("Removed profanity word '%s'", word_key)
        return True

    def update_word(self, word: str, **updates) -> Optional[ProfanityEntry]:
        word_key = word.lower().strip()
        if word_key not in self._profanity_list:
            return None
        pe = self._profanity_list[word_key]
        for key, value in updates.items():
            if hasattr(pe, key) and key != "word":
                setattr(pe, key, value)
        pe.metadata["updated_at"] = datetime.utcnow().isoformat()
        return pe

    def get_word(self, word: str) -> Optional[ProfanityEntry]:
        return self._profanity_list.get(word.lower().strip())

    def list_words(self, category: Optional[ProfanityCategory] = None,
                   tier: Optional[ProfanityTier] = None,
                   active_only: bool = False) -> List[ProfanityEntry]:
        words = list(self._profanity_list.values())
        if category:
            words = [w for w in words if w.category == category]
        if tier:
            words = [w for w in words if w.tier == tier]
        if active_only:
            words = [w for w in words if w.is_active]
        return words

    def add_allowlist(self, word: str, reason: str = "",
                      created_by: str = "system",
                      expires_in_hours: Optional[int] = None) -> AllowlistEntry:
        word_key = word.lower().strip()
        expires_at = None
        if expires_in_hours:
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        entry = AllowlistEntry(
            word=word_key,
            reason=reason,
            created_by=created_by,
            expires_at=expires_at,
        )
        self._allowlist[word_key] = entry
        return entry

    def remove_allowlist(self, word: str) -> bool:
        word_key = word.lower().strip()
        if word_key in self._allowlist:
            self._allowlist.pop(word_key)
            return True
        return False

    def list_allowlist(self) -> List[AllowlistEntry]:
        return list(self._allowlist.values())

    def set_block_threshold(self, threshold: int) -> None:
        self._block_threshold = max(1, min(threshold, 1000))

    def set_warn_threshold(self, threshold: int) -> None:
        self._warn_threshold = max(1, min(threshold, 1000))

    def filter(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        ctx = context or {}
        language = self._detect_language(content)
        all_matches: List[ProfanityMatch] = []
        words = re.findall(r'\b\w+\b', content.lower())
        now = datetime.utcnow()

        for word_key, entry in self._profanity_list.items():
            if not entry.is_active:
                continue
            if entry.languages and language not in entry.languages:
                continue
            target = word_key

            for i, token in enumerate(words):
                token_lower = token.lower().strip()
                if not token_lower or len(token_lower) < 2:
                    continue
                if self._is_allowlisted(token_lower, content):
                    continue
                match_found = False
                match_type = MatchType.EXACT
                confidence = 0.0

                if token_lower == target:
                    match_found = True
                    match_type = MatchType.EXACT
                    confidence = 1.0
                elif self._enable_substitution and entry.allow_substitutions:
                    sub_match, sub_conf = self._check_substitution_match(token_lower, target)
                    if sub_match:
                        match_found = True
                        match_type = MatchType.SUBSTITUTION
                        confidence = sub_conf
                if not match_found and self._enable_fuzzy:
                    fuzzy_match, fuzzy_conf = self._check_fuzzy_match(token_lower, target)
                    if fuzzy_match:
                        match_found = True
                        match_type = MatchType.FUZZY
                        confidence = fuzzy_conf
                if not match_found:
                    compound_match, compound_conf = self._check_compound_match(token_lower, target)
                    if compound_match:
                        match_found = True
                        match_type = MatchType.COMPOUND
                        confidence = compound_conf

                if match_found and confidence > 0:
                    token_pos = content.lower().find(token_lower)
                    if token_pos == -1:
                        token_pos = 0
                    context_before, context_after = self._extract_context(
                        content, token_pos, len(token_lower)
                    )
                    tier_score = PROFANITY_TIER_SCORES.get(entry.tier, 10)
                    score = tier_score * entry.weight * confidence
                    if match_type != MatchType.EXACT:
                        score *= 0.85
                    pm = ProfanityMatch(
                        word=target,
                        matched=token_lower,
                        tier=entry.tier,
                        category=entry.category,
                        match_type=match_type,
                        confidence=confidence,
                        score=score,
                        start_pos=token_pos,
                        end_pos=token_pos + len(token_lower),
                        distance=1.0 - confidence,
                        language=language,
                        context_before=context_before,
                        context_after=context_after,
                    )
                    all_matches.append(pm)

        if self._enable_context_analysis:
            all_matches = self._apply_context_analysis(all_matches, ctx)

        all_matches.sort(key=lambda m: m.score, reverse=True)
        unique_matches = self._deduplicate_matches(all_matches)
        total_score = sum(m.score for m in unique_matches)
        blocked = total_score >= self._block_threshold
        warned = total_score >= self._warn_threshold and not blocked

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        self._stats.record_evaluation(processing_time_ms, unique_matches, blocked=blocked, warned=warned)

        violations = []
        for m in unique_matches[:30]:
            severity = RuleSeverity.MEDIUM
            if m.tier == ProfanityTier.MILD:
                severity = RuleSeverity.LOW
            elif m.tier == ProfanityTier.SEVERE:
                severity = RuleSeverity.HIGH
            elif m.tier == ProfanityTier.EXTREME:
                severity = RuleSeverity.CRITICAL
            action = ActionTaken.WARNING
            if blocked:
                action = ActionTaken.BLOCK
            elif m.tier == ProfanityTier.EXTREME:
                action = ActionTaken.ESCALATE
            v = Violation(
                rule_id=f"profanity_{m.category.value}_{m.word}",
                rule_name=f"Profanity - {m.category.value}",
                rule_tier=RuleTier.SAFETY,
                rule_severity=severity,
                violation_type=ViolationType.REGEX_MATCH if m.match_type == MatchType.EXACT else ViolationType.KEYWORD_MATCH,
                matched_content=m.matched,
                matched_patterns=[m.word],
                confidence_score=m.confidence,
                position_info={"start": m.start_pos, "end": m.end_pos},
                action_taken=action,
                blocked=blocked,
                explanation=f"Profanity detected ({m.tier.value}): '{m.matched}' matched '{m.word}' via {m.match_type.value}",
                detected_at=now,
            )
            violations.append(v)

        result = {
            "clean": len(unique_matches) == 0,
            "blocked": blocked,
            "warned": warned,
            "total_score": round(total_score, 2),
            "total_matches": len(unique_matches),
            "language": language,
            "matches": [
                {
                    "word": m.word,
                    "matched": m.matched,
                    "tier": m.tier.value,
                    "category": m.category.value,
                    "match_type": m.match_type.value,
                    "confidence": round(m.confidence, 3),
                    "score": round(m.score, 2),
                    "distance": round(m.distance, 3),
                }
                for m in unique_matches[:50]
            ],
            "summary": {
                "highest_tier": max((m.tier for m in unique_matches), key=lambda t: PROFANITY_TIER_SCORES.get(t, 0)).value if unique_matches else None,
                "categories": list(set(m.category.value for m in unique_matches)),
                "match_types": list(set(m.match_type.value for m in unique_matches)),
            },
            "processing_time_ms": processing_time_ms,
            "filter_id": self.filter_id,
            "version": self._version,
            "violations": violations,
        }
        return result

    def _deduplicate_matches(self, matches: List[ProfanityMatch]) -> List[ProfanityMatch]:
        seen: Set[Tuple[int, int, str]] = set()
        unique: List[ProfanityMatch] = []
        for m in matches:
            key = (m.start_pos, m.end_pos, m.word)
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique

    def _apply_context_analysis(self, matches: List[ProfanityMatch],
                                 context: Dict[str, Any]) -> List[ProfanityMatch]:
        if not matches:
            return matches
        filtered: List[ProfanityMatch] = []
        for m in matches:
            ctx_lower = (m.context_before + " " + m.context_after).lower()
            educational_indicators = [
                "example", "for example", "such as", "including",
                "educational", "academic", "research", "study",
                "definition", "term", "meaning", "refers to",
                "discussion", "analysis", "context", "quote",
                "hypothetical", "illustration", "demonstration",
            ]
            if any(ind in ctx_lower for ind in educational_indicators):
                m.score *= 0.4
                m.confidence *= 0.4
            quotation_indicators = ['"', "'", "“", "”", "quot", "citation", "source"]
            if any(ind in ctx_lower for ind in quotation_indicators):
                m.score *= 0.6
                m.confidence *= 0.6
            negation_indicators = [
                "not ", "no ", "never ", "without ", "isn't", "aren't",
                "wasn't", "weren't", "don't", "doesn't", "didn't",
                "hasn't", "haven't", "hadn't", "won't", "wouldn't",
                "shouldn't", "couldn't", "mustn't", "can't", "cannot",
            ]
            if any(ind in ctx_lower for ind in negation_indicators):
                m.score *= 0.3
                m.confidence *= 0.3
            if m.confidence > 0.15 and m.score > 1.0:
                filtered.append(m)
        return filtered

    def get_stats(self) -> Dict[str, Any]:
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        self._stats.reset()
        self.logger.info("Statistics reset for filter %s", self.filter_id)

    def generate_report(self, include_top_words: bool = False) -> Dict[str, Any]:
        report = {
            "filter_id": self.filter_id,
            "version": self._version,
            "generated_at": datetime.utcnow().isoformat(),
            "stats": self._stats.to_dict(),
            "configuration": {
                "fuzzy": self._enable_fuzzy,
                "fuzzy_threshold": self._fuzzy_threshold,
                "substitution": self._enable_substitution,
                "context_analysis": self._enable_context_analysis,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "max_distance": self._max_distance,
            },
            "word_list": {
                cat.value: {
                    "count": len([w for w in self._profanity_list.values() if w.category == cat]),
                    "words": [w.word for w in self._profanity_list.values()
                              if w.category == cat and w.is_active],
                }
                for cat in ProfanityCategory
            },
            "total_words": len(self._profanity_list),
            "total_allowlisted": len(self._allowlist),
            "categories": {
                cat.value: len(self._categories.get(cat, []))
                for cat in self._categories
            },
            "tier_distribution": {
                tier.value: len([w for w in self._profanity_list.values() if w.tier == tier])
                for tier in ProfanityTier
            },
        }
        if include_top_words:
            report["top_matched"] = dict(
                sorted(self._stats.top_matched_words.items(), key=lambda x: -x[1])[:30]
            )
        return report

    def export_config(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "configuration": {
                "enable_fuzzy": self._enable_fuzzy,
                "fuzzy_threshold": self._fuzzy_threshold,
                "enable_substitution": self._enable_substitution,
                "enable_context_analysis": self._enable_context_analysis,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "max_distance": self._max_distance,
                "context_window": self._context_window,
            },
            "word_list": [
                {
                    "word": pe.word,
                    "tier": pe.tier.value,
                    "category": pe.category.value,
                    "languages": pe.languages,
                    "weight": pe.weight,
                    "allow_substitutions": pe.allow_substitutions,
                    "is_active": pe.is_active,
                }
                for pe in self._profanity_list.values()
            ],
            "allowlist": [
                {
                    "word": e.word,
                    "reason": e.reason,
                    "created_by": e.created_by,
                    "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                }
                for e in self._allowlist.values()
            ],
        }

    def import_config(self, config: Dict[str, Any]) -> int:
        imported = 0
        if "configuration" in config:
            cfg = config["configuration"]
            self._enable_fuzzy = cfg.get("enable_fuzzy", self._enable_fuzzy)
            self._fuzzy_threshold = cfg.get("fuzzy_threshold", self._fuzzy_threshold)
            self._enable_substitution = cfg.get("enable_substitution", self._enable_substitution)
            self._enable_context_analysis = cfg.get("enable_context_analysis", self._enable_context_analysis)
            self._block_threshold = cfg.get("block_threshold", self._block_threshold)
            self._warn_threshold = cfg.get("warn_threshold", self._warn_threshold)
            self._max_distance = cfg.get("max_distance", self._max_distance)
            self._context_window = cfg.get("context_window", self._context_window)
        if "word_list" in config:
            for w in config["word_list"]:
                try:
                    tier = ProfanityTier(w.get("tier", "moderate"))
                except ValueError:
                    tier = ProfanityTier.MODERATE
                try:
                    category = ProfanityCategory(w.get("category", "general"))
                except ValueError:
                    category = ProfanityCategory.GENERAL
                self.add_word(
                    word=w["word"],
                    tier=tier,
                    category=category,
                    languages=w.get("languages"),
                    weight=w.get("weight", 1.0),
                    allow_substitutions=w.get("allow_substitutions", True),
                )
                imported += 1
        if "allowlist" in config:
            for e in config["allowlist"]:
                self.add_allowlist(
                    word=e["word"],
                    reason=e.get("reason", ""),
                    created_by=e.get("created_by", "import"),
                )
        self.logger.info("Imported %d profanity words", imported)
        return imported

    def to_validation_result(self, filter_result: Dict[str, Any]) -> ValidationResult:
        violations = filter_result.get("violations", [])
        score = filter_result.get("total_score", 0)
        max_possible = self._block_threshold * 2
        clean_score = max(0.0, 1.0 - (score / max_possible))
        return ValidationResult(
            valid=filter_result.get("clean", True),
            total_score=clean_score,
            confidence=1.0 - min(0.5, len(violations) / 50.0),
            total_rules_evaluated=len(self._profanity_list),
            rules_triggered=len(violations),
            rules_violated=len(violations),
            violations=violations,
            critical_violations=[v for v in violations if v.is_critical()],
            warnings=[v for v in violations if v.action_taken == ActionTaken.WARNING],
            processing_time_ms=filter_result.get("processing_time_ms", 0),
            evaluator_version=self._version,
        )
