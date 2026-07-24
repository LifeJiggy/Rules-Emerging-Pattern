"""
Copyright filter - detection of copyrighted content through keyword/phrase matching,
URL/domain checking against known copyright sources, fair use heuristics, quotation
analysis, attribution checking, source caching, and config-driven thresholds.
"""

import copy
import hashlib
import json
import logging
import os
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


class CopyrightRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CopyrightMatchType(str, Enum):
    EXACT_PHRASE = "exact_phrase"
    KEYWORD = "keyword"
    URL_SOURCE = "url_source"
    DOMAIN_BLOCK = "domain_block"
    FUZZY = "fuzzy"
    QUOTATION = "quotation"
    ATTRIBUTION = "attribution"


@dataclass
class CopyrightSource:
    source_id: str
    name: str
    content_hash: Optional[str] = None
    phrases: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    risk_level: CopyrightRiskLevel = CopyrightRiskLevel.MEDIUM
    description: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuotationEntry:
    text: str
    author: Optional[str] = None
    source: Optional[str] = None
    is_attributed: bool = False
    length: int = 0


@dataclass
class CopyrightMatch:
    source_id: str
    source_name: str
    match_type: CopyrightMatchType
    matched_text: str
    start_pos: int
    end_pos: int
    risk_level: CopyrightRiskLevel
    confidence: float
    score: float
    context_before: str = ""
    context_after: str = ""
    is_quotation: bool = False
    has_attribution: bool = False
    fair_use_likely: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CopyrightStats:
    total_evaluations: int = 0
    total_matches: int = 0
    total_blocks: int = 0
    total_warnings: int = 0
    total_attributed: int = 0
    total_fair_use: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    match_rate: float = 0.0
    false_positive_rate: float = 0.0
    risk_level_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    match_type_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    source_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_processing_time_ms: int = 0
    avg_processing_time_ms: float = 0.0
    last_evaluated: Optional[datetime] = None
    first_evaluated: Optional[datetime] = None

    def record_evaluation(self, processing_time_ms: int,
                          matches: List[CopyrightMatch],
                          blocked: bool = False,
                          warned: bool = False) -> None:
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
                self.risk_level_counts[m.risk_level.value] += 1
                self.match_type_counts[m.match_type.value] += 1
                self.source_counts[m.source_id] += 1
                if m.is_quotation:
                    self.total_attributed += 1
                if m.fair_use_likely:
                    self.total_fair_use += 1
        date_key = now.strftime("%Y-%m-%d")
        self.daily_counts[date_key] += 1
        if blocked:
            self.total_blocks += 1
        if warned:
            self.total_warnings += 1
        if self.total_evaluations > 0:
            self.match_rate = self.total_matches / self.total_evaluations

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
            "total_attributed": self.total_attributed,
            "total_fair_use": self.total_fair_use,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "match_rate": round(self.match_rate, 4),
            "risk_level_counts": dict(self.risk_level_counts),
            "match_type_counts": dict(self.match_type_counts),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
        }

    def reset(self) -> None:
        self.total_evaluations = 0
        self.total_matches = 0
        self.total_blocks = 0
        self.total_warnings = 0
        self.total_attributed = 0
        self.total_fair_use = 0
        self.false_positives = 0
        self.false_negatives = 0
        self.match_rate = 0.0
        self.false_positive_rate = 0.0
        self.risk_level_counts.clear()
        self.match_type_counts.clear()
        self.source_counts.clear()
        self.daily_counts.clear()
        self.total_processing_time_ms = 0
        self.avg_processing_time_ms = 0.0
        self.last_evaluated = None
        self.first_evaluated = None


RISK_LEVEL_WEIGHTS = {
    CopyrightRiskLevel.NONE: 0,
    CopyrightRiskLevel.LOW: 5,
    CopyrightRiskLevel.MEDIUM: 15,
    CopyrightRiskLevel.HIGH: 30,
    CopyrightRiskLevel.CRITICAL: 60,
}

FAIR_USE_THRESHOLD_CHARS = 500
FAIR_USE_THRESHOLD_PERCENT = 0.1
MIN_QUOTATION_LENGTH = 20
MAX_CACHED_SOURCES = 10000
CACHE_TTL_SECONDS = 3600


class CopyrightFilter:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.filter_id = str(uuid.uuid4())[:8]
        self._sources: Dict[str, CopyrightSource] = {}
        self._source_cache: Dict[str, Tuple[datetime, CopyrightSource]] = {}
        self._known_copyright_domains: Set[str] = set()
        self._quotation_pattern = re.compile(r'"([^"]{10,})"')
        self._attribution_pattern = re.compile(
            r'(?:according to|as said by|as stated by|as noted by|as per|'
            r'as reported by|according to|source|attributed to|credited to|'
            r'cited in|quoted in|quoted by|cited by|per)\s+([A-Z][A-Za-z\s.]+)',
            re.IGNORECASE
        )
        self._citation_pattern = re.compile(
            r'(?:\([A-Za-z]+\s+\d{4}\)|\[\d+\]|\d+\.\s+[A-Z][A-Za-z]+)'
        )
        self._stats = CopyrightStats()
        self._block_threshold = self.config.get("block_threshold", 50)
        self._warn_threshold = self.config.get("warn_threshold", 15)
        self._fair_use_enabled = self.config.get("fair_use_enabled", True)
        self._quotation_analysis = self.config.get("quotation_analysis", True)
        self._attribution_check = self.config.get("attribution_check", True)
        self._enable_cache = self.config.get("enable_cache", True)
        self._context_window = self.config.get("context_window", 80)
        self._max_phrase_length = self.config.get("max_phrase_length", 200)
        self._fuzzy_match_threshold = self.config.get("fuzzy_match_threshold", 0.85)
        self._version = "2.0.0"

        self._init_default_sources()
        self.logger.info("CopyrightFilter initialized (id=%s, version=%s, sources=%d)",
                         self.filter_id, self._version, len(self._sources))

    def _init_default_sources(self) -> None:
        default_sources = [
            CopyrightSource(
                source_id="copyright_news_agency_1",
                name="Associated Press",
                keywords=["Associated Press", "AP News", "AP - "],
                urls=["apnews.com", "ap.org"],
                domains=["apnews.com", "ap.org"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Associated Press news content",
            ),
            CopyrightSource(
                source_id="copyright_news_agency_2",
                name="Reuters",
                keywords=["Reuters", "Reuters News"],
                urls=["reuters.com"],
                domains=["reuters.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Reuters news content",
            ),
            CopyrightSource(
                source_id="copyright_news_agency_3",
                name="Bloomberg",
                keywords=["Bloomberg", "Bloomberg News", "Bloomberg LP"],
                urls=["bloomberg.com"],
                domains=["bloomberg.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Bloomberg financial news content",
            ),
            CopyrightSource(
                source_id="copyright_news_agency_4",
                name="The New York Times",
                keywords=["New York Times", "NYT", "The New York Times"],
                urls=["nytimes.com"],
                domains=["nytimes.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="New York Times content",
            ),
            CopyrightSource(
                source_id="copyright_news_agency_5",
                name="The Wall Street Journal",
                keywords=["Wall Street Journal", "WSJ", "The Wall Street Journal"],
                urls=["wsj.com"],
                domains=["wsj.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Wall Street Journal content",
            ),
            CopyrightSource(
                source_id="copyright_news_agency_6",
                name="The Washington Post",
                keywords=["Washington Post", "WaPo", "The Washington Post"],
                urls=["washingtonpost.com"],
                domains=["washingtonpost.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Washington Post content",
            ),
            CopyrightSource(
                source_id="copyright_publisher_1",
                name="Penguin Random House",
                keywords=["Penguin Random House", "Penguin Books", "Random House"],
                domains=["penguinrandomhouse.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="Penguin Random House published works",
            ),
            CopyrightSource(
                source_id="copyright_publisher_2",
                name="HarperCollins",
                keywords=["HarperCollins", "Harper Collins", "Harper & Row"],
                domains=["harpercollins.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="HarperCollins published works",
            ),
            CopyrightSource(
                source_id="copyright_publisher_3",
                name="Simon & Schuster",
                keywords=["Simon & Schuster", "Simon and Schuster"],
                domains=["simonandschuster.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="Simon & Schuster published works",
            ),
            CopyrightSource(
                source_id="copyright_publisher_4",
                name="Hachette Book Group",
                keywords=["Hachette", "Hachette Book Group", "Little Brown"],
                domains=["hachettebookgroup.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="Hachette published works",
            ),
            CopyrightSource(
                source_id="copyright_publisher_5",
                name="Macmillan Publishers",
                keywords=["Macmillan", "Macmillan Publishers", "St. Martin's Press"],
                domains=["macmillan.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="Macmillan published works",
            ),
            CopyrightSource(
                source_id="copyright_media_1",
                name="BBC",
                keywords=["BBC", "BBC News", "British Broadcasting Corporation"],
                urls=["bbc.com", "bbc.co.uk"],
                domains=["bbc.com", "bbc.co.uk"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="BBC content",
            ),
            CopyrightSource(
                source_id="copyright_media_2",
                name="CNN",
                keywords=["CNN", "CNN News", "Cable News Network"],
                urls=["cnn.com"],
                domains=["cnn.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="CNN content",
            ),
            CopyrightSource(
                source_id="copyright_media_3",
                name="NPR",
                keywords=["NPR", "National Public Radio"],
                urls=["npr.org"],
                domains=["npr.org"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="NPR content",
            ),
            CopyrightSource(
                source_id="copyright_image_1",
                name="Getty Images",
                keywords=["Getty Images", "Getty"],
                urls=["gettyimages.com"],
                domains=["gettyimages.com"],
                risk_level=CopyrightRiskLevel.HIGH,
                description="Getty Images content",
            ),
            CopyrightSource(
                source_id="copyright_image_2",
                name="Shutterstock",
                keywords=["Shutterstock"],
                urls=["shutterstock.com"],
                domains=["shutterstock.com"],
                risk_level=CopyrightRiskLevel.MEDIUM,
                description="Shutterstock content",
            ),
        ]
        for src in default_sources:
            self._sources[src.source_id] = src
            for domain in src.domains:
                self._known_copyright_domains.add(domain.lower())

    def add_source(self, name: str,
                   risk_level: CopyrightRiskLevel = CopyrightRiskLevel.MEDIUM,
                   phrases: Optional[List[str]] = None,
                   keywords: Optional[List[str]] = None,
                   urls: Optional[List[str]] = None,
                   domains: Optional[List[str]] = None,
                   description: str = "") -> CopyrightSource:
        source_id = f"copyright_source_{uuid.uuid4().hex[:12]}"
        src = CopyrightSource(
            source_id=source_id,
            name=name,
            risk_level=risk_level,
            phrases=phrases or [],
            keywords=keywords or [],
            urls=urls or [],
            domains=domains or [],
            description=description or f"Copyright source: {name}",
        )
        self._sources[source_id] = src
        for domain in src.domains:
            self._known_copyright_domains.add(domain.lower())
        self.logger.info("Added copyright source '%s' (id=%s, risk=%s)",
                         name, source_id, risk_level.value)
        return src

    def remove_source(self, source_id: str) -> bool:
        if source_id not in self._sources:
            return False
        src = self._sources.pop(source_id)
        for domain in src.domains:
            self._known_copyright_domains.discard(domain.lower())
        self._source_cache.pop(source_id, None)
        self.logger.info("Removed copyright source '%s'", src.name)
        return True

    def update_source(self, source_id: str, **updates) -> Optional[CopyrightSource]:
        if source_id not in self._sources:
            return None
        src = self._sources[source_id]
        old_domains = set(src.domains)
        for key, value in updates.items():
            if hasattr(src, key) and key != "source_id":
                setattr(src, key, value)
        if "domains" in updates:
            for domain in old_domains:
                self._known_copyright_domains.discard(domain.lower())
            for domain in src.domains:
                self._known_copyright_domains.add(domain.lower())
        src.metadata["updated_at"] = datetime.utcnow().isoformat()
        return src

    def get_source(self, source_id: str) -> Optional[CopyrightSource]:
        if self._enable_cache and source_id in self._source_cache:
            cached_at, cached = self._source_cache[source_id]
            if (datetime.utcnow() - cached_at).total_seconds() < CACHE_TTL_SECONDS:
                return cached
        src = self._sources.get(source_id)
        if src and self._enable_cache:
            self._source_cache[source_id] = (datetime.utcnow(), src)
        return src

    def list_sources(self, risk_level: Optional[CopyrightRiskLevel] = None,
                     active_only: bool = False) -> List[CopyrightSource]:
        sources = list(self._sources.values())
        if risk_level:
            sources = [s for s in sources if s.risk_level == risk_level]
        if active_only:
            sources = [s for s in sources if s.is_active]
        return sources

    def cache_source_content(self, source_id: str, content_hash: str) -> bool:
        if source_id not in self._sources:
            return False
        self._sources[source_id].content_hash = content_hash
        return True

    def clear_cache(self) -> None:
        self._source_cache.clear()
        self.logger.info("Copyright source cache cleared")

    def _levenshtein_similarity(self, s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        if len(s1) < len(s2):
            s1, s2 = s2, s1
        if len(s2) == 0:
            return 1.0
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
        distance = prev_row[-1]
        max_len = max(len(s1), len(s2))
        return 1.0 - (distance / max_len) if max_len > 0 else 1.0

    def _extract_quotations(self, content: str) -> List[QuotationEntry]:
        quotations: List[QuotationEntry] = []
        for match in self._quotation_pattern.finditer(content):
            text = match.group(1).strip()
            if len(text) >= MIN_QUOTATION_LENGTH:
                quotations.append(QuotationEntry(
                    text=text,
                    length=len(text),
                ))
        return quotations

    def _check_attribution(self, content: str, quotation_text: str) -> bool:
        before_match = re.search(
            r'.{0,100}' + re.escape(quotation_text[:30]),
            content,
            re.DOTALL
        )
        if not before_match:
            return False
        context = content[max(0, before_match.start() - 150):before_match.start()]
        if self._attribution_pattern.search(context):
            return True
        if self._citation_pattern.search(context):
            return True
        author_pattern = re.compile(
            r'(?:said|writes|notes|argues|states|claims|suggests|explains|'
            r'reports|observes|comments|adds|concludes|emphasizes|highlights|'
            r'points out|mentions)\s+([A-Z][A-Za-z\s.]+?)(?:,|\.|\s+that)',
            re.IGNORECASE
        )
        if author_pattern.search(context):
            return True
        return False

    def _assess_fair_use(self, content: str, matched_text: str,
                          source: CopyrightSource) -> Tuple[bool, float]:
        content_len = len(content)
        match_len = len(matched_text)
        if content_len == 0:
            return False, 0.0
        length_ratio = match_len / content_len
        char_threshold_ok = match_len <= FAIR_USE_THRESHOLD_CHARS
        percent_threshold_ok = length_ratio <= FAIR_USE_THRESHOLD_PERCENT
        if char_threshold_ok and percent_threshold_ok:
            content_lower = content.lower()
            transformative_indicators = [
                "in other words", "for example", "such as", "for instance",
                "however", "nevertheless", "on the other hand", "alternatively",
                "in contrast", "similarly", "likewise", "furthermore",
                "moreover", "additionally", "specifically", "particularly",
                "this means", "which suggests", "indicating that",
                "this demonstrates", "this illustrates", "this shows",
                "in summary", "overall", "ultimately", "consequently",
                "as a result", "therefore", "thus", "hence", "accordingly",
            ]
            transformative_score = sum(
                2 for ind in transformative_indicators if ind in content_lower
            )
            fair_use_score = min(1.0, 0.3 + (transformative_score * 0.1))
            if char_threshold_ok:
                fair_use_score += 0.2
            if percent_threshold_ok:
                fair_use_score += 0.2
            return fair_use_score > 0.5, fair_use_score
        return False, 0.0

    def _check_url_match(self, content: str) -> List[CopyrightMatch]:
        matches: List[CopyrightMatch] = []
        url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+')
        for url_match in url_pattern.finditer(content):
            url = url_match.group().lower()
            for src in self._sources.values():
                if not src.is_active:
                    continue
                for domain in src.domains:
                    if domain in url:
                        cm = CopyrightMatch(
                            source_id=src.source_id,
                            source_name=src.name,
                            match_type=CopyrightMatchType.URL_SOURCE,
                            matched_text=url_match.group(),
                            start_pos=url_match.start(),
                            end_pos=url_match.end(),
                            risk_level=src.risk_level,
                            confidence=0.95,
                            score=RISK_LEVEL_WEIGHTS.get(src.risk_level, 15) * 1.2,
                        )
                        matches.append(cm)
                        break
                else:
                    for kw in src.keywords:
                        if kw.lower() in url:
                            cm = CopyrightMatch(
                                source_id=src.source_id,
                                source_name=src.name,
                                match_type=CopyrightMatchType.DOMAIN_BLOCK,
                                matched_text=url_match.group(),
                                start_pos=url_match.start(),
                                end_pos=url_match.end(),
                                risk_level=src.risk_level,
                                confidence=0.8,
                                score=RISK_LEVEL_WEIGHTS.get(src.risk_level, 15),
                            )
                            matches.append(cm)
                            break
        return matches

    def _check_keyword_match(self, content: str) -> List[CopyrightMatch]:
        matches: List[CopyrightMatch] = []
        content_lower = content.lower()
        for src in self._sources.values():
            if not src.is_active:
                continue
            for keyword in src.keywords:
                kw_lower = keyword.lower()
                pos = content_lower.find(kw_lower)
                if pos >= 0:
                    end = pos + len(keyword)
                    context_before, context_after = self._extract_context(content, pos, len(kw_lower))
                    cm = CopyrightMatch(
                        source_id=src.source_id,
                        source_name=src.name,
                        match_type=CopyrightMatchType.KEYWORD,
                        matched_text=content[pos:end],
                        start_pos=pos,
                        end_pos=end,
                        risk_level=src.risk_level,
                        confidence=0.7,
                        score=RISK_LEVEL_WEIGHTS.get(src.risk_level, 15) * 0.8,
                        context_before=context_before,
                        context_after=context_after,
                    )
                    matches.append(cm)
        return matches

    def _check_phrase_match(self, content: str) -> List[CopyrightMatch]:
        matches: List[CopyrightMatch] = []
        content_lower = content.lower()
        for src in self._sources.values():
            if not src.is_active:
                continue
            for phrase in src.phrases:
                phrase_lower = phrase.lower()
                if len(phrase_lower) < 10:
                    continue
                if phrase_lower in content_lower:
                    pos = content_lower.index(phrase_lower)
                    end = pos + len(phrase)
                    context_before, context_after = self._extract_context(content, pos, len(phrase_lower))
                    cm = CopyrightMatch(
                        source_id=src.source_id,
                        source_name=src.name,
                        match_type=CopyrightMatchType.EXACT_PHRASE,
                        matched_text=content[pos:end],
                        start_pos=pos,
                        end_pos=end,
                        risk_level=src.risk_level,
                        confidence=0.9,
                        score=RISK_LEVEL_WEIGHTS.get(src.risk_level, 15) * 1.5,
                        context_before=context_before,
                        context_after=context_after,
                    )
                    matches.append(cm)
                else:
                    similarity = self._levenshtein_similarity(phrase_lower, content_lower)
                    if similarity >= self._fuzzy_match_threshold:
                        pos = 0
                        end = len(content)
                        context_before, context_after = self._extract_context(content, 0, len(content))
                        cm = CopyrightMatch(
                            source_id=src.source_id,
                            source_name=src.name,
                            match_type=CopyrightMatchType.FUZZY,
                            matched_text=content[:min(len(phrase), len(content))],
                            start_pos=pos,
                            end_pos=end,
                            risk_level=src.risk_level,
                            confidence=similarity * 0.7,
                            score=RISK_LEVEL_WEIGHTS.get(src.risk_level, 15) * similarity,
                            context_before=context_before,
                            context_after=context_after,
                        )
                        matches.append(cm)
        return matches

    def _extract_context(self, content: str, pos: int, length: int) -> Tuple[str, str]:
        start = max(0, pos - self._context_window)
        end = min(len(content), pos + length + self._context_window)
        return content[start:pos].strip(), content[pos + length:end].strip()

    def filter(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        ctx = context or {}
        all_matches: List[CopyrightMatch] = []
        now = datetime.utcnow()

        url_matches = self._check_url_match(content)
        all_matches.extend(url_matches)
        keyword_matches = self._check_keyword_match(content)
        all_matches.extend(keyword_matches)
        phrase_matches = self._check_phrase_match(content)
        all_matches.extend(phrase_matches)

        quotations: List[QuotationEntry] = []
        if self._quotation_analysis:
            quotations = self._extract_quotations(content)
            for q in quotations:
                if self._attribution_check:
                    q.is_attributed = self._check_attribution(content, q.text)
        for q in quotations:
            if self._attribution_check and not q.is_attributed:
                for src in self._sources.values():
                    q_lower = q.text.lower()
                    if any(kw.lower() in q_lower for kw in src.keywords):
                        cm = CopyrightMatch(
                            source_id=src.source_id,
                            source_name=src.name,
                            match_type=CopyrightMatchType.QUOTATION,
                            matched_text=q.text[:100],
                            start_pos=0,
                            end_pos=0,
                            risk_level=CopyrightRiskLevel.MEDIUM,
                            confidence=0.6,
                            score=RISK_LEVEL_WEIGHTS[CopyrightRiskLevel.MEDIUM] * 0.7,
                            is_quotation=True,
                            has_attribution=q.is_attributed,
                            metadata={"quotation_length": q.length},
                        )
                        all_matches.append(cm)
                        break

        if self._fair_use_enabled:
            for m in all_matches:
                src = self._sources.get(m.source_id)
                if src:
                    fair_use, score = self._assess_fair_use(content, m.matched_text, src)
                    m.fair_use_likely = fair_use
                    if fair_use:
                        m.score *= 0.3
                        m.confidence *= 0.5
                    m.metadata["fair_use_score"] = score

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
            if m.risk_level == CopyrightRiskLevel.CRITICAL:
                severity = RuleSeverity.CRITICAL
            elif m.risk_level == CopyrightRiskLevel.HIGH:
                severity = RuleSeverity.HIGH
            elif m.risk_level == CopyrightRiskLevel.LOW:
                severity = RuleSeverity.LOW
            action = ActionTaken.WARNING
            if blocked:
                action = ActionTaken.BLOCK
            elif m.risk_level == CopyrightRiskLevel.CRITICAL:
                action = ActionTaken.QUARANTINE
            v = Violation(
                rule_id=f"copyright_{m.source_id}_{m.match_type.value}",
                rule_name=f"Copyright - {m.source_name}",
                rule_tier=RuleTier.OPERATIONAL,
                rule_severity=severity,
                violation_type=ViolationType.COMPLIANCE_VIOLATION,
                matched_content=m.matched_text[:80],
                matched_patterns=[m.source_id],
                confidence_score=m.confidence,
                position_info={},
                action_taken=action,
                blocked=blocked,
                explanation=f"Copyrighted content detected from '{m.source_name}' ({m.match_type.value})",
                detected_at=now,
            )
            violations.append(v)

        result = {
            "clean": len(unique_matches) == 0,
            "blocked": blocked,
            "warned": warned,
            "total_score": round(total_score, 2),
            "total_matches": len(unique_matches),
            "quotations_found": len(quotations),
            "attributed_quotations": sum(1 for q in quotations if q.is_attributed),
            "fair_use_applied": sum(1 for m in unique_matches if m.fair_use_likely),
            "matches": [
                {
                    "source": m.source_name,
                    "match_type": m.match_type.value,
                    "risk_level": m.risk_level.value,
                    "confidence": round(m.confidence, 3),
                    "score": round(m.score, 2),
                    "fair_use_likely": m.fair_use_likely,
                    "is_quotation": m.is_quotation,
                    "has_attribution": m.has_attribution,
                }
                for m in unique_matches[:50]
            ],
            "summary": {
                "highest_risk": max((m.risk_level for m in unique_matches),
                                    key=lambda r: RISK_LEVEL_WEIGHTS.get(r, 0)).value if unique_matches else None,
                "sources_found": list(set(m.source_name for m in unique_matches)),
                "match_types": list(set(m.match_type.value for m in unique_matches)),
            },
            "processing_time_ms": processing_time_ms,
            "filter_id": self.filter_id,
            "version": self._version,
            "violations": violations,
        }
        return result

    def _deduplicate_matches(self, matches: List[CopyrightMatch]) -> List[CopyrightMatch]:
        seen: Set[str] = set()
        unique: List[CopyrightMatch] = []
        for m in sorted(matches, key=lambda x: -x.score):
            key = f"{m.source_id}:{m.match_type.value}:{m.matched_text[:50]}"
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique

    def get_stats(self) -> Dict[str, Any]:
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        self._stats.reset()
        self.logger.info("Statistics reset for copyright filter %s", self.filter_id)

    def generate_report(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "generated_at": datetime.utcnow().isoformat(),
            "stats": self._stats.to_dict(),
            "configuration": {
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "fair_use_enabled": self._fair_use_enabled,
                "quotation_analysis": self._quotation_analysis,
                "attribution_check": self._attribution_check,
                "fuzzy_match_threshold": self._fuzzy_match_threshold,
            },
            "sources": {
                sid: {
                    "name": src.name,
                    "risk_level": src.risk_level.value,
                    "phrases": len(src.phrases),
                    "keywords": len(src.keywords),
                    "domains": len(src.domains),
                    "active": src.is_active,
                }
                for sid, src in self._sources.items()
            },
            "total_sources": len(self._sources),
            "total_domains": len(self._known_copyright_domains),
        }

    def export_config(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "configuration": {
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "fair_use_enabled": self._fair_use_enabled,
                "quotation_analysis": self._quotation_analysis,
                "attribution_check": self._attribution_check,
                "fuzzy_match_threshold": self._fuzzy_match_threshold,
                "context_window": self._context_window,
                "max_phrase_length": self._max_phrase_length,
            },
            "sources": [
                {
                    "source_id": src.source_id,
                    "name": src.name,
                    "risk_level": src.risk_level.value,
                    "phrases": src.phrases,
                    "keywords": src.keywords,
                    "urls": src.urls,
                    "domains": src.domains,
                    "description": src.description,
                    "is_active": src.is_active,
                }
                for src in self._sources.values()
            ],
        }

    def import_config(self, config: Dict[str, Any]) -> int:
        imported = 0
        if "configuration" in config:
            cfg = config["configuration"]
            self._block_threshold = cfg.get("block_threshold", self._block_threshold)
            self._warn_threshold = cfg.get("warn_threshold", self._warn_threshold)
            self._fair_use_enabled = cfg.get("fair_use_enabled", self._fair_use_enabled)
            self._quotation_analysis = cfg.get("quotation_analysis", self._quotation_analysis)
            self._attribution_check = cfg.get("attribution_check", self._attribution_check)
            self._fuzzy_match_threshold = cfg.get("fuzzy_match_threshold", self._fuzzy_match_threshold)
        if "sources" in config:
            for s in config["sources"]:
                try:
                    risk = CopyrightRiskLevel(s.get("risk_level", "medium"))
                except ValueError:
                    risk = CopyrightRiskLevel.MEDIUM
                self.add_source(
                    name=s["name"],
                    risk_level=risk,
                    phrases=s.get("phrases", []),
                    keywords=s.get("keywords", []),
                    urls=s.get("urls", []),
                    domains=s.get("domains", []),
                    description=s.get("description", ""),
                )
                imported += 1
        self.logger.info("Imported %d copyright sources", imported)
        return imported

    def to_validation_result(self, filter_result: Dict[str, Any]) -> ValidationResult:
        violations = filter_result.get("violations", [])
        score = filter_result.get("total_score", 0)
        max_possible = self._block_threshold * 2
        clean_score = max(0.0, 1.0 - (score / max_possible))
        return ValidationResult(
            valid=filter_result.get("clean", True),
            total_score=clean_score,
            confidence=1.0 - min(0.3, len(violations) / 30.0),
            total_rules_evaluated=len(self._sources),
            rules_triggered=len(violations),
            rules_violated=len(violations),
            violations=violations,
            critical_violations=[v for v in violations if v.is_critical()],
            warnings=[v for v in violations if v.action_taken == ActionTaken.WARNING],
            processing_time_ms=filter_result.get("processing_time_ms", 0),
            evaluator_version=self._version,
        )

    def check_url(self, url: str) -> Dict[str, Any]:
        url_lower = url.lower()
        for src in self._sources.values():
            for domain in src.domains:
                if domain in url_lower:
                    return {
                        "matched": True,
                        "source": src.name,
                        "risk_level": src.risk_level.value,
                        "domains": src.domains,
                    }
        return {"matched": False, "source": None}

    def analyze_copyright_risk(self, content: str) -> Dict[str, Any]:
        result = self.filter(content)
        return {
            "risk_score": result["total_score"],
            "risk_level": CopyrightRiskLevel.CRITICAL.value if result["total_score"] >= 50
            else CopyrightRiskLevel.HIGH.value if result["total_score"] >= 30
            else CopyrightRiskLevel.MEDIUM.value if result["total_score"] >= 15
            else CopyrightRiskLevel.LOW.value if result["total_score"] > 0
            else CopyrightRiskLevel.NONE.value,
            "sources_found": result["summary"]["sources_found"],
            "quotations": result["quotations_found"],
            "attributed": result["attributed_quotations"],
            "fair_use_count": result["fair_use_applied"],
            "matches": len(result["matches"]),
        }
