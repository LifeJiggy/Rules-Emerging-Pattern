"""
Toxicity filter - multi-dimensional toxicity detection with sentiment-weighted
scoring, context-aware escalation, per-user tracking with decay, harassment/
hate speech/bullying/threat pattern recognition, and config-driven thresholds.
"""

import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class ToxicityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToxicityCategory(str, Enum):
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    BULLYING = "bullying"
    THREATENING = "threatening"
    DISCRIMINATORY = "discriminatory"
    PERSONAL_ATTACK = "personal_attack"
    INCITEMENT = "incitement"
    CYBERBULLYING = "cyberbullying"
    DOXXING = "doxxing"
    GASLIGHTING = "gaslighting"
    MANIPULATION = "manipulation"
    GENERAL_TOXICITY = "general_toxicity"


class EscalationReason(str, Enum):
    HIGH_SEVERITY = "high_severity"
    REPEATED_VIOLATIONS = "repeated_violations"
    CROSS_CATEGORY = "cross_category"
    TARGETED_HARASSMENT = "targeted_harassment"
    THREAT_IMMINENT = "threat_imminent"
    DOXXING_ATTEMPT = "doxxing_attempt"
    USER_TREND_UP = "user_trend_up"
    MANUAL_ESCALATION = "manual_escalation"


class SentimentLabel(str, Enum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class DecayStrategy(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    STEP = "step"


@dataclass
class ToxicityPattern:
    category: ToxicityCategory
    patterns: List[str] = field(default_factory=list)
    weight: float = 1.0
    negating_prefixes: List[str] = field(default_factory=list)
    intensifiers: List[str] = field(default_factory=list)
    context_words: List[str] = field(default_factory=list)
    min_match_length: int = 3
    require_boundary: bool = True
    case_sensitive: bool = False
    is_active: bool = True


@dataclass
class ToxicityMatch:
    category: ToxicityCategory
    pattern: str
    matched_text: str
    start_pos: int
    end_pos: int
    confidence: float
    raw_score: float
    weighted_score: float
    sentiment_delta: float = 0.0
    context_window: str = ""
    is_negated: bool = False
    is_intensified: bool = False
    language: str = "en"


@dataclass
class UserToxicityRecord:
    user_id: str
    total_score: float = 0.0
    match_count: int = 0
    category_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    level_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    recent_scores: List[Tuple[datetime, float]] = field(default_factory=list)
    escalation_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    is_tracked: bool = True
    flags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def apply_decay(self, decay_rate: float = 0.95, strategy: DecayStrategy = DecayStrategy.EXPONENTIAL) -> None:
        if not self.recent_scores:
            return
        now = datetime.utcnow()
        weights: List[float] = []
        for ts, score in self.recent_scores:
            age_hours = (now - ts).total_seconds() / 3600.0
            if strategy == DecayStrategy.LINEAR:
                w = max(0.0, 1.0 - age_hours * decay_rate)
            elif strategy == DecayStrategy.EXPONENTIAL:
                w = math.exp(-age_hours * decay_rate)
            elif strategy == DecayStrategy.STEP:
                w = 1.0 if age_hours < 24 else 0.5 if age_hours < 72 else 0.1
            else:
                w = 1.0
            weights.append(w)
        if not weights or sum(weights) == 0:
            return
        self.total_score = sum(
            s * w for (_, s), w in zip(self.recent_scores, weights)
        ) / sum(weights)

    def add_match(self, score: float, category: ToxicityCategory, level: ToxicityLevel) -> None:
        now = datetime.utcnow()
        self.recent_scores.append((now, score))
        if len(self.recent_scores) > 1000:
            self.recent_scores = self.recent_scores[-500:]
        self.total_score += score
        self.match_count += 1
        self.category_counts[category.value] += 1
        self.level_counts[level.value] += 1
        self.last_updated = now

    def get_level(self, thresholds: Dict[str, float]) -> ToxicityLevel:
        if self.total_score >= thresholds.get("critical", 50.0):
            return ToxicityLevel.CRITICAL
        if self.total_score >= thresholds.get("high", 25.0):
            return ToxicityLevel.HIGH
        if self.total_score >= thresholds.get("medium", 10.0):
            return ToxicityLevel.MEDIUM
        return ToxicityLevel.LOW

    def get_category_breakdown(self) -> Dict[str, float]:
        total = sum(self.category_counts.values()) or 1
        return {k: round(v / total * 100, 2) for k, v in self.category_counts.items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "total_score": round(self.total_score, 4),
            "match_count": self.match_count,
            "category_counts": dict(self.category_counts),
            "level_counts": dict(self.level_counts),
            "escalation_count": self.escalation_count,
            "last_updated": self.last_updated.isoformat(),
            "first_seen": self.first_seen.isoformat(),
            "is_tracked": self.is_tracked,
            "flags": self.flags,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "total_score": round(self.total_score, 2),
            "match_count": self.match_count,
            "active_categories": sorted(
                [k for k, v in self.category_counts.items() if v > 0]
            ),
            "escalation_count": self.escalation_count,
            "is_tracked": self.is_tracked,
            "days_active": (datetime.utcnow() - self.first_seen).days,
        }


@dataclass
class ToxicityReport:
    report_id: str
    generated_at: datetime = field(default_factory=datetime.utcnow)
    period_start: datetime
    period_end: datetime
    total_evaluations: int = 0
    total_violations: int = 0
    total_blocks: int = 0
    total_escalations: int = 0
    unique_users: int = 0
    top_categories: Dict[str, int] = field(default_factory=dict)
    level_distribution: Dict[str, int] = field(default_factory=dict)
    users_at_risk: List[str] = field(default_factory=list)
    user_summaries: List[Dict[str, Any]] = field(default_factory=list)
    trend_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_evaluations": self.total_evaluations,
            "total_violations": self.total_violations,
            "total_blocks": self.total_blocks,
            "total_escalations": self.total_escalations,
            "unique_users": self.unique_users,
            "top_categories": self.top_categories,
            "level_distribution": self.level_distribution,
            "users_at_risk": self.users_at_risk,
            "trend_score": round(self.trend_score, 4),
            "recommendations": self.recommendations,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


class ToxicityFilterConfig:
    DEFAULT_THRESHOLDS = {
        "low_max": 0.15,
        "medium_max": 0.40,
        "high_max": 0.70,
        "critical_min": 0.70,
        "user_low": 5.0,
        "user_medium": 10.0,
        "user_high": 25.0,
        "user_critical": 50.0,
    }

    DEFAULT_SENTIMENT_WEIGHTS = {
        SentimentLabel.VERY_NEGATIVE: 1.8,
        SentimentLabel.NEGATIVE: 1.3,
        SentimentLabel.NEUTRAL: 1.0,
        SentimentLabel.POSITIVE: 0.6,
        SentimentLabel.VERY_POSITIVE: 0.3,
    }

    DEFAULT_CATEGORY_WEIGHTS = {
        ToxicityCategory.HARASSMENT: 1.2,
        ToxicityCategory.HATE_SPEECH: 1.5,
        ToxicityCategory.BULLYING: 1.1,
        ToxicityCategory.THREATENING: 1.7,
        ToxicityCategory.DISCRIMINATORY: 1.4,
        ToxicityCategory.PERSONAL_ATTACK: 1.0,
        ToxicityCategory.INCITEMENT: 1.6,
        ToxicityCategory.CYBERBULLYING: 1.3,
        ToxicityCategory.DOXXING: 2.0,
        ToxicityCategory.GASLIGHTING: 1.1,
        ToxicityCategory.MANIPULATION: 0.9,
        ToxicityCategory.GENERAL_TOXICITY: 0.8,
    }

    DEFAULT_INTENSIFIERS = {
        "very", "really", "extremely", "incredibly", "absolutely",
        "completely", "totally", "utterly", "highly", "deeply",
        "seriously", "genuinely", "horribly", "terribly", "awfully",
    }

    DEFAULT_NEGATORS = {
        "not", "no", "never", "neither", "nor", "nothing",
        "nobody", "nowhere", "cannot", "can't", "don't", "doesn't",
        "didn't", "won't", "wouldn't", "shouldn't", "isn't", "aren't",
        "wasn't", "weren't", "haven't", "hasn't", "hadn't",
    }

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        sentiment_weights: Optional[Dict[SentimentLabel, float]] = None,
        category_weights: Optional[Dict[ToxicityCategory, float]] = None,
        intensifiers: Optional[Set[str]] = None,
        negators: Optional[Set[str]] = None,
        decay_rate: float = 0.05,
        decay_strategy: DecayStrategy = DecayStrategy.EXPONENTIAL,
        context_window: int = 50,
        min_confidence: float = 0.5,
        require_bulk_match: bool = True,
        escalation_threshold: int = 3,
        max_tracked_users: int = 10000,
        enable_sentiment_weighting: bool = True,
        enable_context_analysis: bool = True,
        enable_user_tracking: bool = True,
        enable_auto_escalation: bool = True,
        report_max_users: int = 100,
        metric_window_days: int = 30,
    ):
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.sentiment_weights = {**self.DEFAULT_SENTIMENT_WEIGHTS, **(sentiment_weights or {})}
        self.category_weights = {**self.DEFAULT_CATEGORY_WEIGHTS, **(category_weights or {})}
        self.intensifiers = intensifiers or self.DEFAULT_INTENSIFIERS
        self.negators = negators or self.DEFAULT_NEGATORS
        self.decay_rate = decay_rate
        self.decay_strategy = decay_strategy
        self.context_window = context_window
        self.min_confidence = min_confidence
        self.require_bulk_match = require_bulk_match
        self.escalation_threshold = escalation_threshold
        self.max_tracked_users = max_tracked_users
        self.enable_sentiment_weighting = enable_sentiment_weighting
        self.enable_context_analysis = enable_context_analysis
        self.enable_user_tracking = enable_user_tracking
        self.enable_auto_escalation = enable_auto_escalation
        self.report_max_users = report_max_users
        self.metric_window_days = metric_window_days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thresholds": self.thresholds,
            "decay_rate": self.decay_rate,
            "decay_strategy": self.decay_strategy.value,
            "context_window": self.context_window,
            "min_confidence": self.min_confidence,
            "require_bulk_match": self.require_bulk_match,
            "escalation_threshold": self.escalation_threshold,
            "max_tracked_users": self.max_tracked_users,
            "enable_sentiment_weighting": self.enable_sentiment_weighting,
            "enable_context_analysis": self.enable_context_analysis,
            "enable_user_tracking": self.enable_user_tracking,
            "enable_auto_escalation": self.enable_auto_escalation,
            "metric_window_days": self.metric_window_days,
        }


class ToxicityFilter:
    DEFAULT_PATTERNS: List[ToxicityPattern] = [
        ToxicityPattern(
            category=ToxicityCategory.HARASSMENT,
            patterns=[
                r'\b(?:shut\s*up|leave\s*me\s*alone|back\s*off|get\s*lost)\b',
                r'\b(?:stop\s+harassing|quit\s+bothering)\b',
                r'\b(?:creep|stalker|pervert|weirdo)\b',
            ],
            weight=1.2,
            negating_prefixes=["don't", "stop", "quit"],
            intensifiers=["constant", "relentless", "endless"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.HATE_SPEECH,
            patterns=[
                r'\b(?:hate\s+(?:speech|crime|group|monger))\b',
                r'\b(?:supremac(?:ist|y)|white\s+supremacy)\b',
                r'\b(?:racial\s+(?:slur|epithet|abuse|attack))\b',
            ],
            weight=1.5,
            negating_prefixes=["not", "against"],
            intensifiers=["blatant", "vicious", "overt"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.BULLYING,
            patterns=[
                r'\b(?:loser|failure|worthless|pathetic|nobody)\b',
                r'\b(?:nobody\s+(?:likes|loves|wants)\s+you)\b',
                r'\b(?:give\s+up|kill\s+yourself|go\s+die)\b',
            ],
            weight=1.1,
            negating_prefixes=["not", "you're not", "you are not"],
            intensifiers=["total", "complete", "absolute"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.THREATENING,
            patterns=[
                r'\b(?:i\s+will\s+(?:kill|hurt|destroy|end)\s+(?:you|your))\b',
                r"\b(?:you(?:'re|'ll| are| will)\s+(?:be\s+sorry|regret|pay))\b",
                r'\b(?:come\s+(?:after|for)\s+you|going\s+to\s+get\s+you)\b',
            ],
            weight=1.7,
            negating_prefixes=["i won't", "i will not", "not going to"],
            intensifiers=["definitely", "absolutely", "swear"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.DISCRIMINATORY,
            patterns=[
                r'\b(?:sexist|racist|homophobic|transphobic|xenophobic)\b',
                r'\b(?:all\s+(?:you|those)\s+\w+\s+(?:are|should))\b',
                r'\b(?:go\s+back\s+to\s+(?:your|where))\b',
            ],
            weight=1.4,
            negating_prefixes=["not", "isn't", "aren't"],
            intensifiers=["blatantly", "overtly", "disgustingly"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.PERSONAL_ATTACK,
            patterns=[
                r'\b(?:stupid|idiot|moron|imbecile|dunce)\b',
                r'\b(?:you\s+(?:are\s+)?(?:so\s+)?(?:dumb|ugly|fat|stupid))\b',
                r'\b(?:what\s+is\s+wrong\s+with\s+you|are\s+you\s+(?:crazy|insane))\b',
            ],
            weight=1.0,
        ),
        ToxicityPattern(
            category=ToxicityCategory.INCITEMENT,
            patterns=[
                r'\b(?:everyone\s+(?:attack|go\s+after|report))\b',
                r'\b(?:let\'?s\s+all\s+(?:go|hate|target))\b',
                r'\b(?:who\s+else\s+(?:thinks|agrees|believes))\b',
            ],
            weight=1.6,
            intensifiers=["right now", "immediately", "today"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.CYBERBULLYING,
            patterns=[
                r'\b(?:you\s+should\s+(?:delete|quit|leave))\b',
                r'\b(?:no\s+one\s+(?:cares|likes|wants))\b',
                r'\b(?:just\s+(?:stop|quit|give\s+up))\b',
            ],
            weight=1.3,
        ),
        ToxicityPattern(
            category=ToxicityCategory.DOXXING,
            patterns=[
                r'\b(?:dox|doxx|drop\s+(?:location|address))\b',
                r'\b(?:find\s+(?:their|his|her)\s+(?:address|phone|location))\b',
                r'\b(?:leak\s+(?:their|his|her)\s+(?:info|data|details))\b',
            ],
            weight=2.0,
            intensifiers=["exact", "full", "complete"],
        ),
        ToxicityPattern(
            category=ToxicityCategory.GASLIGHTING,
            patterns=[
                r'\b(?:you\s+(?:are\s+)?(?:crazy|insane|paranoid|overreacting))\b',
                r'\b(?:that\s+(?:never|didn\'?t)\s+happen|you\s+imagined)\b',
                r'\b(?:you\s+(?:are|being)\s+too\s+sensitive)\b',
            ],
            weight=1.1,
        ),
        ToxicityPattern(
            category=ToxicityCategory.MANIPULATION,
            patterns=[
                r'\b(?:if\s+you\s+(?:really|cared|loved))\b',
                r'\b(?:you\s+(?:owe|must|have\s+to|need\s+to))\b',
                r'\b(?:after\s+everything\s+i\s+(?:did|have\s+done))\b',
            ],
            weight=0.9,
        ),
        ToxicityPattern(
            category=ToxicityCategory.GENERAL_TOXICITY,
            patterns=[
                r'\b(?:toxic|poisonous|venomous)\b',
                r'\b(?:negative\s+(?:energy|vibes|attitude))\b',
                r'\b(?:drama|dramatic|attention\s+seeking)\b',
            ],
            weight=0.8,
        ),
    ]

    def __init__(
        self,
        config: Optional[ToxicityFilterConfig] = None,
        patterns: Optional[List[ToxicityPattern]] = None,
    ):
        self.config = config or ToxicityFilterConfig()
        self.patterns = patterns or [p for p in self.DEFAULT_PATTERNS]
        self._compiled: Dict[str, re.Pattern] = {}
        self._user_records: Dict[str, UserToxicityRecord] = {}
        self._rules: List[Rule] = []
        self._evaluation_count: int = 0
        self._violation_count: int = 0
        self._block_count: int = 0
        self._escalation_count: int = 0
        self._match_log: List[ToxicityMatch] = []
        self._total_processing_ms: int = 0
        self._category_total_counts: Dict[str, int] = defaultdict(int)
        self._level_total_counts: Dict[str, int] = defaultdict(int)
        self._feedback_loop: List[Dict[str, Any]] = []
        self._initialize_compiled_patterns()

    def _initialize_compiled_patterns(self) -> None:
        for pattern_def in self.patterns:
            if not pattern_def.is_active:
                continue
            for raw_pattern in pattern_def.patterns:
                flags = 0 if pattern_def.case_sensitive else re.IGNORECASE
                try:
                    compiled = re.compile(raw_pattern, flags)
                    key = self._pattern_key(raw_pattern, pattern_def.category)
                    self._compiled[key] = compiled
                except re.error as e:
                    logger.warning("Failed to compile pattern %r: %s", raw_pattern, e)

    def _pattern_key(self, pattern: str, category: ToxicityCategory) -> str:
        raw = f"{category.value}::{pattern}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_category_for_pattern(self, pattern_key: str) -> Optional[ToxicityCategory]:
        for pattern_def in self.patterns:
            for raw_pattern in pattern_def.patterns:
                if self._pattern_key(raw_pattern, pattern_def.category) == pattern_key:
                    return pattern_def.category
        return None

    def _get_pattern_def(self, category: ToxicityCategory) -> Optional[ToxicityPattern]:
        for p in self.patterns:
            if p.category == category:
                return p
        return None

    @staticmethod
    def _extract_context(text: str, pos: int, window: int) -> str:
        start = max(0, pos - window)
        end = min(len(text), pos + window)
        return text[start:end]

    def _analyze_sentiment(self, text: str) -> Tuple[SentimentLabel, float]:
        positive_words = {
            "good", "great", "excellent", "amazing", "wonderful", "fantastic",
            "happy", "love", "beautiful", "kind", "helpful", "thank",
            "appreciate", "respect", "admire", "support", "agree",
        }
        negative_words = {
            "bad", "terrible", "awful", "horrible", "hate", "disgusting",
            "disrespectful", "abusive", "cruel", "vile", "contempt",
            "despise", "detest", "loathsome", "repulsive",
        }
        intensity_words = {
            "absolutely", "completely", "totally", "utterly", "extremely",
            "incredibly", "very", "really", "deeply", "intensely",
        }
        tokens = re.findall(r'\b\w+\b', text.lower())
        if not tokens:
            return SentimentLabel.NEUTRAL, 0.0
        neg_count = 0
        pos_count = 0
        intensity = 1.0
        for token in tokens:
            if token in negative_words:
                neg_count += 1
            if token in positive_words:
                pos_count += 1
            if token in intensity_words:
                intensity += 0.2
        net = pos_count - neg_count
        magnitude = abs(net) * intensity
        if net > 2:
            return SentimentLabel.VERY_POSITIVE, magnitude
        if net > 0:
            return SentimentLabel.POSITIVE, magnitude
        if net == 0 or magnitude < 0.5:
            return SentimentLabel.NEUTRAL, magnitude
        if net > -2:
            return SentimentLabel.NEGATIVE, magnitude
        return SentimentLabel.VERY_NEGATIVE, magnitude

    def _compute_sentiment_delta(
        self,
        sentiment: SentimentLabel,
        category: ToxicityCategory,
    ) -> float:
        if not self.config.enable_sentiment_weighting:
            return 0.0
        base = self.config.sentiment_weights.get(sentiment, 1.0)
        cat_weight = self.config.category_weights.get(category, 1.0)
        return (base - 1.0) * cat_weight * 0.3

    def _check_negation(self, text: str, match_start: int, pattern_def: ToxicityPattern) -> bool:
        if not pattern_def.negating_prefixes:
            return False
        before = text[max(0, match_start - 60):match_start].lower()
        for prefix in pattern_def.negating_prefixes:
            if prefix.lower() in before:
                tokens = before.split()
                prefix_tokens = prefix.lower().split()
                if any(prefix_tokens == tokens[max(0, i - len(prefix_tokens)):i] for i in range(len(tokens) + 1)):
                    return True
        return False

    def _check_intensification(self, text: str, match_start: int, pattern_def: ToxicityPattern) -> bool:
        if not pattern_def.intensifiers:
            return False
        before = text[max(0, match_start - 40):match_start].lower()
        for intensifier in pattern_def.intensifiers:
            if intensifier.lower() in before:
                return True
        return False

    def _score_from_level(self, level: ToxicityLevel) -> float:
        mapper = {
            ToxicityLevel.LOW: 0.1,
            ToxicityLevel.MEDIUM: 0.35,
            ToxicityLevel.HIGH: 0.6,
            ToxicityLevel.CRITICAL: 0.85,
        }
        return mapper.get(level, 0.0)

    def classify_level(self, score: float) -> ToxicityLevel:
        t = self.config.thresholds
        if score >= t.get("critical_min", 0.70):
            return ToxicityLevel.CRITICAL
        if score >= t.get("high_max", 0.70) * 0.6:
            return ToxicityLevel.HIGH
        if score >= t.get("medium_max", 0.40) * 0.5:
            return ToxicityLevel.MEDIUM
        return ToxicityLevel.LOW

    def evaluate_toxicity(
        self,
        text: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToxicityLevel:
        result = self.evaluate(text, user_id=user_id, context=context)
        return result["level"]

    def evaluate(
        self,
        text: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start_time = time.perf_counter()
        context = context or {}
        matches: List[ToxicityMatch] = []
        category_scores: Dict[ToxicityCategory, float] = defaultdict(float)
        raw_scores: List[float] = []

        sentiment, sentiment_magnitude = self._analyze_sentiment(text)

        for pattern_def in self.patterns:
            if not pattern_def.is_active:
                continue
            for raw_pattern in pattern_def.patterns:
                key = self._pattern_key(raw_pattern, pattern_def.category)
                compiled = self._compiled.get(key)
                if compiled is None:
                    continue
                for match in compiled.finditer(text):
                    matched_text = match.group(0)
                    if pattern_def.require_boundary:
                        start = match.start()
                        end = match.end()
                        if start > 0 and text[start - 1].isalnum():
                            continue
                        if end < len(text) and text[end].isalnum():
                            continue
                    if len(matched_text) < pattern_def.min_match_length:
                        continue
                    is_negated = self._check_negation(text, match.start(), pattern_def)
                    is_intensified = self._check_intensification(text, match.start(), pattern_def)
                    confidence = 0.85 if not is_negated else 0.25
                    if is_intensified:
                        confidence = min(confidence + 0.12, 0.98)
                    if confidence < self.config.min_confidence:
                        continue
                    cat_weight = self.config.category_weights.get(pattern_def.category, 1.0)
                    base_score = pattern_def.weight * cat_weight
                    if is_negated:
                        base_score *= 0.3
                    if is_intensified:
                        base_score *= 1.4
                    sentiment_delta = self._compute_sentiment_delta(sentiment, pattern_def.category)
                    weighted = base_score * confidence + sentiment_delta
                    weighted = max(0.0, min(1.0, weighted))
                    context_window = self._extract_context(text, match.start(), self.config.context_window)
                    tm = ToxicityMatch(
                        category=pattern_def.category,
                        pattern=raw_pattern,
                        matched_text=matched_text,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=confidence,
                        raw_score=base_score,
                        weighted_score=weighted,
                        sentiment_delta=sentiment_delta,
                        context_window=context_window,
                        is_negated=is_negated,
                        is_intensified=is_intensified,
                    )
                    matches.append(tm)
                    category_scores[pattern_def.category] = max(
                        category_scores[pattern_def.category], weighted
                    )
                    raw_scores.append(weighted)

        combined_score = 0.0
        if raw_scores:
            combined_score = sum(raw_scores) / len(raw_scores)
            category_penalty = sum(category_scores.values()) * 0.05
            combined_score = min(1.0, combined_score + category_penalty)

        level = self.classify_level(combined_score)
        escalation_reasons: List[str] = []

        if self.config.enable_context_analysis and context:
            if context.get("targeted_user") and level in (ToxicityLevel.HIGH, ToxicityLevel.CRITICAL):
                escalation_reasons.append(EscalationReason.TARGETED_HARASSMENT.value)
            if len(category_scores) >= 3:
                escalation_reasons.append(EscalationReason.CROSS_CATEGORY.value)
            if ToxicityCategory.THREATENING in category_scores and combined_score > 0.5:
                escalation_reasons.append(EscalationReason.THREAT_IMMINENT.value)
            if ToxicityCategory.DOXXING in category_scores:
                escalation_reasons.append(EscalationReason.DOXXING_ATTEMPT.value)

        user_record: Optional[UserToxicityRecord] = None
        if user_id and self.config.enable_user_tracking:
            user_record = self._track_user(user_id, combined_score, level, matches, category_scores)
            if user_record:
                user_level = user_record.get_level(self.config.thresholds)
                if user_level in (ToxicityLevel.HIGH, ToxicityLevel.CRITICAL):
                    if len(user_record.recent_scores) >= self.config.escalation_threshold:
                        escalation_reasons.append(EscalationReason.REPEATED_VIOLATIONS.value)
                    if len(user_record.recent_scores) >= 5:
                        trend = self._compute_user_trend(user_record)
                        if trend > 0.3:
                            escalation_reasons.append(EscalationReason.USER_TREND_UP.value)

        should_escalate = (
            self.config.enable_auto_escalation
            and len(escalation_reasons) > 0
            and level in (ToxicityLevel.HIGH, ToxicityLevel.CRITICAL)
        )
        if should_escalate:
            self._escalation_count += 1

        action = ActionTaken.NONE
        blocked = False
        if level == ToxicityLevel.CRITICAL:
            action = ActionTaken.BLOCK
            blocked = True
            self._block_count += 1
        elif level == ToxicityLevel.HIGH:
            action = ActionTaken.WARNING
        elif level == ToxicityLevel.MEDIUM:
            action = ActionTaken.SUGGESTION

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        self._evaluation_count += 1
        self._total_processing_ms += elapsed_ms
        if matches:
            self._violation_count += 1
            self._match_log.extend(matches[-20:])
            if len(self._match_log) > 10000:
                self._match_log = self._match_log[-5000:]
        for cat in category_scores:
            self._category_total_counts[cat.value] += 1
        self._level_total_counts[level.value] += 1

        result = {
            "level": level,
            "score": round(combined_score, 4),
            "matches": [
                {
                    "category": m.category.value,
                    "pattern": m.pattern,
                    "matched_text": m.matched_text,
                    "confidence": round(m.confidence, 3),
                    "weighted_score": round(m.weighted_score, 3),
                    "is_negated": m.is_negated,
                    "is_intensified": m.is_intensified,
                    "position": {"start": m.start_pos, "end": m.end_pos},
                }
                for m in matches
            ],
            "category_scores": {
                k.value: round(v, 4) for k, v in sorted(
                    category_scores.items(), key=lambda x: x[1], reverse=True
                )
            },
            "sentiment": sentiment.value,
            "sentiment_magnitude": round(sentiment_magnitude, 4),
            "escalation": should_escalate,
            "escalation_reasons": escalation_reasons,
            "action_taken": action.value,
            "blocked": blocked,
            "processing_ms": elapsed_ms,
            "user_id": user_id,
            "match_count": len(matches),
        }
        if user_record:
            result["user_total_score"] = round(user_record.total_score, 4)
            result["user_level"] = user_record.get_level(self.config.thresholds).value
        return result

    def _track_user(
        self,
        user_id: str,
        score: float,
        level: ToxicityLevel,
        matches: List[ToxicityMatch],
        category_scores: Dict[ToxicityCategory, float],
    ) -> UserToxicityRecord:
        if user_id not in self._user_records:
            if len(self._user_records) >= self.config.max_tracked_users:
                self._evict_oldest_user()
            self._user_records[user_id] = UserToxicityRecord(user_id=user_id)
        record = self._user_records[user_id]
        record.apply_decay(
            decay_rate=self.config.decay_rate,
            strategy=self.config.decay_strategy,
        )
        for match in matches:
            record.add_match(match.weighted_score, match.category, level)
        return record

    def _evict_oldest_user(self) -> None:
        if not self._user_records:
            return
        oldest_id = min(self._user_records, key=lambda uid: self._user_records[uid].last_updated)
        del self._user_records[oldest_id]
        logger.info("Evicted oldest user record: %s", oldest_id)

    def _compute_user_trend(self, record: UserToxicityRecord) -> float:
        scores = record.recent_scores
        if len(scores) < 3:
            return 0.0
        recent = [s for _, s in scores[-3:]]
        older = [s for _, s in scores[:3]]
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        if avg_older == 0:
            return float(avg_recent > 0)
        return (avg_recent - avg_older) / max(avg_older, 0.001)

    def get_user_record(self, user_id: str) -> Optional[UserToxicityRecord]:
        return self._user_records.get(user_id)

    def get_user_level(self, user_id: str) -> Optional[ToxicityLevel]:
        record = self._user_records.get(user_id)
        if record is None:
            return None
        return record.get_level(self.config.thresholds)

    def reset_user(self, user_id: str) -> bool:
        if user_id in self._user_records:
            del self._user_records[user_id]
            logger.info("Reset toxicity tracking for user: %s", user_id)
            return True
        return False

    def flag_user(self, user_id: str, flag: str) -> bool:
        record = self._user_records.get(user_id)
        if record is None:
            return False
        if flag not in record.flags:
            record.flags.append(flag)
        return True

    def get_users_at_risk(self, min_score: float = 10.0) -> List[Tuple[str, UserToxicityRecord]]:
        return [
            (uid, rec) for uid, rec in self._user_records.items()
            if rec.total_score >= min_score
        ]

    def register_rule(self, rule: Rule) -> None:
        if rule.id not in {r.id for r in self._rules}:
            self._rules.append(rule)

    def get_rules(self) -> List[Rule]:
        return self._rules.copy()

    def filter_violations(
        self, text: str, user_id: Optional[str] = None
    ) -> ValidationResult:
        eval_result = self.evaluate(text, user_id=user_id)
        violations: List[Violation] = []
        for m in eval_result.get("matches", []):
            rule_severity = RuleSeverity.LOW
            level_str = eval_result["level"]
            if level_str == ToxicityLevel.CRITICAL.value:
                rule_severity = RuleSeverity.CRITICAL
            elif level_str == ToxicityLevel.HIGH.value:
                rule_severity = RuleSeverity.HIGH
            elif level_str == ToxicityLevel.MEDIUM.value:
                rule_severity = RuleSeverity.MEDIUM
            violation = Violation(
                rule_id=f"toxicity_{m['category']}",
                rule_name=f"Toxicity - {m['category'].replace('_', ' ').title()}",
                rule_tier=RuleTier.SAFETY,
                rule_severity=rule_severity,
                violation_type=ViolationType.SEMANTIC_VIOLATION,
                matched_content=m["matched_text"],
                matched_patterns=[m["pattern"]],
                confidence_score=m["confidence"],
                position_info={
                    "start": m["position"]["start"],
                    "end": m["position"]["end"],
                },
                action_taken=ActionTaken(eval_result["action_taken"]),
                blocked=eval_result["blocked"],
                explanation=f"Detected {m['category']} toxicity pattern "
                            f"(confidence: {m['confidence']:.2f})",
            )
            violations.append(violation)
        total_score = 1.0 - eval_result["score"]
        result = ValidationResult(
            valid=not eval_result["blocked"],
            total_score=max(0.0, total_score),
            confidence=1.0 - eval_result["score"],
            total_rules_evaluated=len(self._compiled),
            rules_triggered=eval_result["match_count"],
            rules_violated=len(violations),
            violations=violations,
            critical_violations=[
                v for v in violations if v.rule_severity == RuleSeverity.CRITICAL
            ],
            warnings=[
                v for v in violations
                if v.action_taken in (ActionTaken.WARNING, ActionTaken.SUGGESTION)
            ],
            processing_time_ms=eval_result["processing_ms"],
        )
        return result

    def bulk_evaluate(
        self,
        texts: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return [
            self.evaluate(text, user_id=user_id, context=context)
            for text in texts
        ]

    def bulk_filter_violations(
        self,
        texts: List[str],
        user_id: Optional[str] = None,
    ) -> List[ValidationResult]:
        return [
            self.filter_violations(text, user_id=user_id)
            for text in texts
        ]

    def generate_report(
        self,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> ToxicityReport:
        now = datetime.utcnow()
        period_start = period_start or (now - timedelta(days=self.config.metric_window_days))
        period_end = period_end or now
        report = ToxicityReport(
            report_id=f"toxicity_report_{uuid.uuid4().hex[:12]}",
            period_start=period_start,
            period_end=period_end,
            total_evaluations=self._evaluation_count,
            total_violations=self._violation_count,
            total_blocks=self._block_count,
            total_escalations=self._escalation_count,
            unique_users=len(self._user_records),
            top_categories=dict(sorted(
                self._category_total_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]),
            level_distribution=dict(self._level_total_counts),
            users_at_risk=[uid for uid, _ in self.get_users_at_risk()][:self.config.report_max_users],
        )
        for uid, rec in self.get_users_at_risk():
            if len(report.user_summaries) >= self.config.report_max_users:
                break
            report.user_summaries.append(rec.to_summary())
        if self._evaluation_count > 0:
            recent_vals = [
                m.weighted_score for m in self._match_log[-100:]
            ]
            report.trend_score = (
                (sum(recent_vals) / len(recent_vals))
                if recent_vals else 0.0
            )
        report.recommendations = self._generate_recommendations(report)
        return report

    def _generate_recommendations(self, report: ToxicityReport) -> List[str]:
        recs: List[str] = []
        if report.total_violations > 100:
            recs.append("High volume of toxicity violations detected; review filter thresholds.")
        if report.total_escalations > 10:
            recs.append("Frequent escalations indicate need for human moderator intervention.")
        if report.trend_score > 0.2:
            recs.append("Toxicity trend score is elevated; consider stricter enforcement.")
        if len(report.users_at_risk) > 5:
            recs.append(f"{len(report.users_at_risk)} users at risk level; review per-user tracking.")
        top_cat = report.top_categories
        if top_cat:
            worst = max(top_cat, key=top_cat.get)
            recs.append(f"Most prevalent category: {worst}; consider targeted pattern updates.")
        if self._violation_count > 0 and self._evaluation_count > 0:
            rate = self._violation_count / self._evaluation_count * 100
            if rate > 10:
                recs.append(f"Violation rate at {rate:.1f}%; evaluate whether thresholds are too sensitive.")
        return recs

    def export_user_records(self, min_score: float = 0.0) -> List[Dict[str, Any]]:
        return [
            rec.to_dict() for rec in self._user_records.values()
            if rec.total_score >= min_score
        ]

    def export_summary(self) -> Dict[str, Any]:
        total_processed_ms = self._total_processing_ms
        avg_ms = (
            total_processed_ms / self._evaluation_count
            if self._evaluation_count > 0 else 0.0
        )
        return {
            "filter": "ToxicityFilter",
            "version": "1.0.0",
            "evaluation_count": self._evaluation_count,
            "violation_count": self._violation_count,
            "block_count": self._block_count,
            "escalation_count": self._escalation_count,
            "average_processing_ms": round(avg_ms, 2),
            "total_processing_ms": total_processed_ms,
            "compiled_patterns": len(self._compiled),
            "tracked_users": len(self._user_records),
            "category_distribution": dict(self._category_total_counts),
            "level_distribution": dict(self._level_total_counts),
            "config": self.config.to_dict(),
        }

    def export_json(self, indent: int = 2) -> str:
        return json.dumps(self.export_summary(), indent=indent, default=str)

    def reset_stats(self) -> None:
        self._evaluation_count = 0
        self._violation_count = 0
        self._block_count = 0
        self._escalation_count = 0
        self._match_log.clear()
        self._total_processing_ms = 0
        self._category_total_counts.clear()
        self._level_total_counts.clear()
        self._feedback_loop.clear()
        logger.info("ToxicityFilter stats reset")

    def reload_patterns(self, patterns: Optional[List[ToxicityPattern]] = None) -> None:
        if patterns is not None:
            self.patterns = patterns
        self._compiled.clear()
        self._initialize_compiled_patterns()
        logger.info("Reloaded %d toxicity patterns", len(self._compiled))

    def add_pattern(self, pattern: ToxicityPattern) -> None:
        if pattern not in self.patterns:
            self.patterns.append(pattern)
            for raw_pattern in pattern.patterns:
                flags = 0 if pattern.case_sensitive else re.IGNORECASE
                try:
                    compiled = re.compile(raw_pattern, flags)
                    key = self._pattern_key(raw_pattern, pattern.category)
                    self._compiled[key] = compiled
                except re.error as e:
                    logger.warning("Failed to compile added pattern: %s", e)

    def remove_pattern(self, category: ToxicityCategory, pattern_str: str) -> bool:
        key = self._pattern_key(pattern_str, category)
        if key in self._compiled:
            del self._compiled[key]
        self.patterns = [
            p for p in self.patterns
            if not (p.category == category and pattern_str in p.patterns)
        ]
        for p in self.patterns:
            if p.category == category and pattern_str in p.patterns:
                p.patterns.remove(pattern_str)
                return True
        return key in self._compiled or any(
            pattern_str in p.patterns and p.category == category
            for p in self.patterns
        )

    def get_match_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [
            {
                "category": m.category.value,
                "pattern": m.pattern,
                "matched_text": m.matched_text,
                "confidence": round(m.confidence, 3),
                "weighted_score": round(m.weighted_score, 3),
                "is_negated": m.is_negated,
                "is_intensified": m.is_intensified,
                "context_window": m.context_window,
            }
            for m in self._match_log[-limit:]
        ]

    def record_feedback(
        self,
        text: str,
        user_id: Optional[str],
        predicted_level: ToxicityLevel,
        correct_level: ToxicityLevel,
        comment: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "text_preview": text[:200],
            "user_id": user_id,
            "predicted_level": predicted_level.value,
            "correct_level": correct_level.value,
            "is_correct": predicted_level == correct_level,
            "comment": comment,
            "feedback_id": uuid.uuid4().hex[:12],
        }
        self._feedback_loop.append(entry)
        if len(self._feedback_loop) > 1000:
            self._feedback_loop = self._feedback_loop[-500:]

    def get_feedback_stats(self) -> Dict[str, Any]:
        if not self._feedback_loop:
            return {"total_feedback": 0}
        total = len(self._feedback_loop)
        correct = sum(1 for f in self._feedback_loop if f.get("is_correct"))
        return {
            "total_feedback": total,
            "correct_predictions": correct,
            "accuracy": round(correct / total * 100, 2) if total > 0 else 0.0,
        }

    def analyze_trends(self, window_hours: int = 24) -> Dict[str, Any]:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)
        recent_matches = [
            m for m in self._match_log
        ]
        window_matches = recent_matches[-500:]
        if not window_matches:
            return {"matches_in_window": 0}
        cat_counts: Dict[str, int] = defaultdict(int)
        for m in window_matches:
            cat_counts[m.category.value] += 1
        avg_confidence = sum(m.confidence for m in window_matches) / len(window_matches)
        avg_score = sum(m.weighted_score for m in window_matches) / len(window_matches)
        return {
            "matches_in_window": len(window_matches),
            "window_hours": window_hours,
            "category_counts": dict(sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)),
            "average_confidence": round(avg_confidence, 4),
            "average_score": round(avg_score, 4),
            "unique_users_in_window": len({
                uid for uid in self._user_records
            }),
        }

    def validate_config(self) -> List[str]:
        errors: List[str] = []
        t = self.config.thresholds
        if t.get("low_max", 0) >= t.get("medium_max", 0):
            errors.append("low_max must be less than medium_max")
        if t.get("medium_max", 0) >= t.get("high_max", 0):
            errors.append("medium_max must be less than high_max")
        if t.get("high_max", 0) >= t.get("critical_min", 0):
            errors.append("high_max must be less than critical_min")
        if not 0 <= self.config.min_confidence <= 1:
            errors.append("min_confidence must be between 0 and 1")
        if self.config.escalation_threshold < 1:
            errors.append("escalation_threshold must be >= 1")
        if self.config.max_tracked_users < 1:
            errors.append("max_tracked_users must be >= 1")
        if self.config.metric_window_days < 1:
            errors.append("metric_window_days must be >= 1")
        return errors

    def __repr__(self) -> str:
        return (
            f"ToxicityFilter(patterns={len(self.patterns)}, "
            f"compiled={len(self._compiled)}, "
            f"evaluations={self._evaluation_count}, "
            f"violations={self._violation_count})"
        )
