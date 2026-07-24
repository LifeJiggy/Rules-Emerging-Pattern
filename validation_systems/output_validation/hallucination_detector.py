"""Hallucination detection for generated outputs."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple, Pattern

logger = logging.getLogger(__name__)


@dataclass
class HallucinationScore:
    """Scores for different hallucination dimensions."""
    factual_consistency: float = 1.0
    contradiction_score: float = 0.0
    named_entity_risk: float = 0.0
    numerical_risk: float = 0.0
    citation_risk: float = 0.0
    pattern_marker_score: float = 0.0
    overall_score: float = 0.0


@dataclass
class HallucinationSpan:
    """A span of text flagged as potentially hallucinated."""
    text: str
    start: int
    end: int
    category: str
    confidence: float
    explanation: str
    evidence: Optional[str] = None


@dataclass
class HallucinationResult:
    """Complete hallucination detection result."""
    flagged: bool
    overall_score: float
    spans: List[HallucinationSpan]
    scores: HallucinationScore
    warnings: List[str]
    recommendations: List[str]
    processing_time_ms: float = 0.0


HALLUCINATION_PATTERNS: Dict[str, List[Pattern]] = {
    "vague_hedging": [
        re.compile(r"\b(it\s+is\s+(widely\s+)?(believed|thought|considered|regarded)\s+that)\b", re.IGNORECASE),
        re.compile(r"\b(some\s+(people|experts|scientists|researchers)\s+(say|believe|claim|argue))\b", re.IGNORECASE),
        re.compile(r"\b(many\s+(studies|researchers|papers)\s+(show|suggest|indicate))\b", re.IGNORECASE),
        re.compile(r"\b(it\s+is\s+(often|commonly)\s+(said|thought|believed))\b", re.IGNORECASE),
    ],
    "unsupported_absolute": [
        re.compile(r"\b(this\s+(proves|demonstrates|confirms|establishes))\b", re.IGNORECASE),
        re.compile(r"\b(there\s+is\s+no\s+doubt\s+that)\b", re.IGNORECASE),
        re.compile(r"\b(undoubtedly|unquestionably|certainly|absolutely)\b", re.IGNORECASE),
    ],
    "speculative_language": [
        re.compile(r"\b(might\s+indicate|could\s+suggest|may\s+imply)\b", re.IGNORECASE),
        re.compile(r"\b(potentially\s+(leading|causing|resulting))\b", re.IGNORECASE),
        re.compile(r"\b(raises\s+the\s+(possibility|question))\b", re.IGNORECASE),
    ],
    "fabricated_references": [
        re.compile(r"\b(as\s+reported\s+in\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+\(\d{4}\))\b"),
        re.compile(r"\b(according\s+to\s+(a|an)\s+(recent|new|upcoming)\s+(study|paper|research))\b", re.IGNORECASE),
    ],
    "overprecision": [
        re.compile(r"\b\d+\.\d{6,}\b"),
        re.compile(r"\bexactly\s+\d{4,}\b", re.IGNORECASE),
        re.compile(r"\bprecisely\s+\d+\.\d{4,}\b", re.IGNORECASE),
    ],
}

FABRICATED_CITATION_PATTERNS: List[Pattern] = [
    re.compile(r"in\s+a\s+(\d{4})\s+(study|paper|article|report)\s+(?:by\s+)?(?:the\s+)?"
              r"([A-Z][a-z]+(?:\s+(?:and\s+)?[A-Z][a-z]+)*)", re.IGNORECASE),
    re.compile(r"according\s+to\s+(?:a|an)\s+(\d{4})\s+(paper|study|report|article)", re.IGNORECASE),
    re.compile(r"(?:published|cited)\s+in\s+(?:the\s+)?([A-Z][A-Za-z\s]+?)\s*(?:,|\s+)\s*\((\d{4})\)"),
]

KNOWN_IMPLAUSIBLE_DATES: List[Pattern] = [
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"),
]

CONTRADICTION_MARKERS: List[Pattern] = [
    re.compile(r"\b(however|but|yet|although|though|nevertheless|nonetheless)\b", re.IGNORECASE),
    re.compile(r"\b(on\s+the\s+(other\s+)?hand|in\s+contrast|conversely)\b", re.IGNORECASE),
    re.compile(r"\b(contrary\s+to|despite|in\s+spite\s+of)\b", re.IGNORECASE),
]

NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:%\s*|thousand|million|billion|trillion)?", re.IGNORECASE)
YEAR_NUMBER_PATTERN = re.compile(r"\b(19\d{2}|20[0-2]\d|2030)\b")
ENTITY_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


class HallucinationDetector:
    """Detects hallucinations in generated content."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.detection_threshold: float = self.config.get("detection_threshold", 0.5)
        self.entity_threshold: float = self.config.get("entity_threshold", 0.6)
        self.numerical_threshold: float = self.config.get("numerical_threshold", 0.5)
        self.citation_threshold: float = self.config.get("citation_threshold", 0.6)
        self.pattern_threshold: float = self.config.get("pattern_threshold", 0.4)
        self.contradiction_weight: float = self.config.get("contradiction_weight", 0.3)
        self.named_entity_weight: float = self.config.get("named_entity_weight", 0.2)
        self.numerical_weight: float = self.config.get("numerical_weight", 0.15)
        self.citation_weight: float = self.config.get("citation_weight", 0.2)
        self.pattern_weight: float = self.config.get("pattern_weight", 0.15)
        self.knowledge_base: Dict[str, Any] = self.config.get("knowledge_base", {})
        self.known_entities: Set[str] = set(
            self.config.get("known_entities", [])
        )
        self.known_journals: Set[str] = set(
            self.config.get("known_journals", [])
        )
        self.common_contradictions: List[Tuple[str, str]] = [
            (r"\bis always\b", r"\bis never\b"),
            (r"\ball\b", r"\bnone\b"),
            (r"\bincreases\b", r"\bdecreases\b"),
            (r"\bpositive\b", r"\bnegative\b"),
            (r"\ballow\b", r"\bprevent\b"),
        ]
        self.logger.info(
            "HallucinationDetector initialized with threshold=%s",
            self.detection_threshold,
        )

    def detect(self, content: str) -> Dict[str, Any]:
        """Detect hallucinations in content and return assessment."""
        self.logger.debug("Detecting hallucinations for content length: %d", len(content))
        spans: List[HallucinationSpan] = []
        scores = self._compute_all_scores(content)
        entity_spans = self._detect_entity_hallucinations(content)
        spans.extend(entity_spans)
        numerical_spans = self._detect_numerical_hallucinations(content)
        spans.extend(numerical_spans)
        citation_spans = self._detect_citation_hallucinations(content)
        spans.extend(citation_spans)
        pattern_spans = self._detect_pattern_hallucinations(content)
        spans.extend(pattern_spans)
        contradiction_spans = self._detect_contradictions(content)
        spans.extend(contradiction_spans)
        flagged = scores.overall_score > self.detection_threshold
        warnings = self._generate_warnings(spans, scores)
        recommendations = self._generate_recommendations(spans, scores)
        result = {
            "flagged": flagged,
            "overall_score": round(scores.overall_score, 4),
            "hallucination_score": round(scores.overall_score, 4),
            "spans": [
                {
                    "text": s.text,
                    "start": s.start,
                    "end": s.end,
                    "category": s.category,
                    "confidence": round(s.confidence, 4),
                    "explanation": s.explanation,
                    "evidence": s.evidence,
                }
                for s in spans
            ],
            "scores": {
                "factual_consistency": round(scores.factual_consistency, 4),
                "contradiction_score": round(scores.contradiction_score, 4),
                "named_entity_risk": round(scores.named_entity_risk, 4),
                "numerical_risk": round(scores.numerical_risk, 4),
                "citation_risk": round(scores.citation_risk, 4),
                "pattern_marker_score": round(scores.pattern_marker_score, 4),
            },
            "warnings": warnings,
            "recommendations": recommendations,
            "flagged_spans_count": len(spans),
        }
        self.logger.info(
            "Hallucination detection completed: flagged=%s, score=%s, spans=%d",
            flagged, result["overall_score"], len(spans),
        )
        return result

    def _compute_all_scores(self, content: str) -> HallucinationScore:
        """Compute all hallucination risk scores."""
        scores = HallucinationScore()
        contradictions = self._find_contradictions(content)
        scores.contradiction_score = self._score_contradictions(contradictions)
        entity_risk = self._assess_entity_risk(content)
        scores.named_entity_risk = entity_risk
        numerical_risk = self._assess_numerical_risk(content)
        scores.numerical_risk = numerical_risk
        citation_risk = self._assess_citation_risk(content)
        scores.citation_risk = citation_risk
        pattern_score = self._assess_pattern_risk(content)
        scores.pattern_marker_score = pattern_score
        scores.factual_consistency = max(
            0.0,
            1.0 - (
                scores.contradiction_score * self.contradiction_weight
                + entity_risk * self.named_entity_weight
                + numerical_risk * self.numerical_weight
                + citation_risk * self.citation_weight
                + pattern_score * self.pattern_weight
            ),
        )
        scores.overall_score = 1.0 - scores.factual_consistency
        return scores

    def _find_contradictions(self, content: str) -> List[Tuple[str, str, float]]:
        """Find contradictory statements in content."""
        contradictions: List[Tuple[str, str, float]] = []
        sentences = re.split(r"(?<=[.!?])\s+", content)
        for i, s1 in enumerate(sentences):
            for j in range(i + 1, min(i + 10, len(sentences))):
                s2 = sentences[j]
                s1_lower = s1.lower().strip()
                s2_lower = s2.lower().strip()
                if not s1_lower or not s2_lower:
                    continue
                for pat1, pat2 in self.common_contradictions:
                    if re.search(pat1, s1_lower) and re.search(pat2, s2_lower):
                        contradictions.append((s1_lower, s2_lower, 0.8))
                    elif re.search(pat2, s1_lower) and re.search(pat1, s2_lower):
                        contradictions.append((s1_lower, s2_lower, 0.8))
                number_pairs = self._check_numerical_contradiction(s1_lower, s2_lower)
                for pair in number_pairs:
                    contradictions.append(pair)
        return contradictions

    def _check_numerical_contradiction(self, s1: str, s2: str) -> List[Tuple[str, str, float]]:
        """Check for numerical contradictions between two sentences."""
        contradictions: List[Tuple[str, str, float]] = []
        nums1 = set(re.findall(r"\b\d+(?:\.\d+)?\b", s1))
        nums2 = set(re.findall(r"\b\d+(?:\.\d+)?\b", s2))
        if not nums1 or not nums2:
            return contradictions
        for n1 in nums1:
            for n2 in nums2:
                try:
                    v1 = float(n1)
                    v2 = float(n2)
                    if v1 == v2:
                        continue
                    if abs(v1 - v2) < 5.0 and v1 > 0 and v2 > 0:
                        continue
                except ValueError:
                    continue
        return contradictions

    def _score_contradictions(self, contradictions: List[Tuple[str, str, float]]) -> float:
        """Score the severity of contradictions found."""
        if not contradictions:
            return 0.0
        raw_score = sum(c[2] for c in contradictions) / len(contradictions)
        density_boost = min(1.0, len(contradictions) / 10.0)
        return min(1.0, raw_score * (1.0 + density_boost * 0.5))

    def _detect_contradictions(self, content: str) -> List[HallucinationSpan]:
        """Detect contradictory statements in content."""
        spans: List[HallucinationSpan] = []
        contradictions = self._find_contradictions(content)
        for s1, s2, conf in contradictions:
            pos = content.find(s1[:50])
            if pos >= 0:
                spans.append(HallucinationSpan(
                    text=s1[:100],
                    start=pos,
                    end=pos + len(s1[:100]),
                    category="contradiction",
                    confidence=conf,
                    explanation="Contradicts statement elsewhere in content",
                    evidence=s2[:100],
                ))
        return spans

    def _assess_entity_risk(self, content: str) -> float:
        """Assess risk of named entity hallucinations."""
        entities = ENTITY_PATTERN.findall(content)
        if not entities:
            return 0.0
        known_count = sum(1 for e in entities if self._is_known_entity(e))
        unknown_count = len(entities) - known_count
        if unknown_count == 0:
            return 0.0
        unknown_ratio = unknown_count / len(entities)
        if unknown_ratio > 0.5 and unknown_count >= 3:
            return min(1.0, unknown_ratio * 0.8)
        return unknown_ratio * 0.3

    def _is_known_entity(self, entity: str) -> bool:
        """Check if an entity is known/verified."""
        entity_lower = entity.lower().strip()
        if entity_lower in self.known_entities:
            return True
        kb = self.knowledge_base
        if "entities" in kb:
            if entity_lower in {e.lower() for e in kb["entities"]}:
                return True
        known_indicators = [
            "united states", "european", "world war", "president", "university",
            "professor", "dr.", "department", "organization", "corporation",
            "incorporated", "limited", "ltd", "inc", "co.",
            "new york", "london", "paris", "tokyo", "berlin", "beijing",
            "microsoft", "google", "apple", "amazon", "meta", "facebook",
            "harvard", "stanford", "mit", "oxford", "cambridge", "yale",
            "nature", "science", "cell", "lancet", "jama", "nejm",
        ]
        for indicator in known_indicators:
            if indicator in entity_lower:
                return True
        return False

    def _detect_entity_hallucinations(self, content: str) -> List[HallucinationSpan]:
        """Detect potentially hallucinated named entities."""
        spans: List[HallucinationSpan] = []
        entities = ENTITY_PATTERN.finditer(content)
        for match in entities:
            entity = match.group()
            if self._is_known_entity(entity):
                continue
            if len(entity.split()) > 5:
                continue
            risk = self._compute_entity_risk(entity)
            if risk > self.entity_threshold:
                spans.append(HallucinationSpan(
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    category="unverified_entity",
                    confidence=risk,
                    explanation=f"Entity '{entity}' is not in the verified knowledge base",
                ))
        return spans

    def _compute_entity_risk(self, entity: str) -> float:
        """Compute hallucination risk for a named entity."""
        parts = entity.split()
        if len(parts) == 1:
            return 0.3
        name_patterns = [
            (r"^[A-Z][a-z]+ [A-Z][a-z]+$", 0.5),
            (r"^[A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+$", 0.4),
            (r"^[A-Z]\. [A-Z][a-z]+$", 0.3),
            (r"^[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+$", 0.6),
        ]
        risk = 0.5
        for pattern, score in name_patterns:
            if re.match(pattern, entity):
                risk = score
                break
        title_prefixes = ["professor", "dr.", "president", "director", "ceo", "chief"]
        parts_lower = [p.lower() for p in parts]
        for prefix in title_prefixes:
            if prefix in parts_lower:
                risk = min(risk + 0.1, 1.0)
                break
        risk = min(1.0, risk * (0.8 + 0.1 * len(parts)))
        return risk

    def _assess_numerical_risk(self, content: str) -> float:
        """Assess risk of numerical hallucinations."""
        numbers = NUMBER_PATTERN.findall(content)
        if not numbers:
            return 0.0
        suspicious_count = 0
        for num_str in numbers:
            if self._is_suspicious_number(num_str):
                suspicious_count += 1
        suspicious_ratio = suspicious_count / len(numbers) if numbers else 0.0
        density = len(numbers) / max(1, len(content.split()))
        return min(1.0, suspicious_ratio * 0.7 + density * 0.3)

    def _is_suspicious_number(self, num_str: str) -> bool:
        """Check if a number seems suspicious or implausible."""
        cleaned = num_str.replace(",", "").replace("%", "").strip().lower()
        if cleaned in ("thousand", "million", "billion", "trillion"):
            return False
        try:
            value = float(cleaned)
        except ValueError:
            return False
        if value > 1_000_000_000_000_000:
            return True
        if value > 10_000_000_000 and "percent" not in num_str.lower() and "%" not in num_str:
            return True
        if 0 < value < 0.0000001:
            return True
        return False

    def _detect_numerical_hallucinations(self, content: str) -> List[HallucinationSpan]:
        """Detect potentially hallucinated numerical claims."""
        spans: List[HallucinationSpan] = []
        for match in NUMBER_PATTERN.finditer(content):
            num_str = match.group()
            if self._is_suspicious_number(num_str):
                confidence = min(0.9, 0.5 + len(num_str) * 0.02)
                spans.append(HallucinationSpan(
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    category="suspicious_number",
                    confidence=confidence,
                    explanation=f"Number '{num_str}' appears implausibly large or small",
                ))
        year_matches = YEAR_NUMBER_PATTERN.finditer(content)
        current_year = datetime.now().year
        for match in year_matches:
            year = int(match.group())
            if year > current_year + 5:
                spans.append(HallucinationSpan(
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    category="future_year",
                    confidence=0.7,
                    explanation=f"Year '{year}' is too far in the future",
                ))
            elif year < 1800:
                context_start = max(0, match.start() - 50)
                context_end = min(len(content), match.end() + 50)
                context = content[context_start:context_end]
                if "century" not in context.lower() and "bc" not in context.lower():
                    spans.append(HallucinationSpan(
                        text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        category="implausible_year",
                        confidence=0.5,
                        explanation=f"Year '{year}' seems unusually old for modern context",
                    ))
        return spans

    def _assess_citation_risk(self, content: str) -> float:
        """Assess risk of citation hallucinations."""
        spans = self._detect_citation_hallucinations(content)
        if not spans:
            return 0.0
        avg_confidence = sum(s.confidence for s in spans) / len(spans)
        density = min(1.0, len(spans) / 20.0)
        return min(1.0, avg_confidence * 0.6 + density * 0.4)

    def _detect_citation_hallucinations(self, content: str) -> List[HallucinationSpan]:
        """Detect potentially fake or fabricated citations."""
        spans: List[HallucinationSpan] = []
        for pattern in FABRICATED_CITATION_PATTERNS:
            for match in pattern.finditer(content):
                confidence = 0.5
                full_match = match.group()
                if "recent study" in full_match.lower() or "new paper" in full_match.lower():
                    confidence = 0.7
                groups = match.groups()
                if len(groups) >= 2:
                    year_str = groups[0]
                    try:
                        year = int(re.search(r"\d{4}", year_str).group(0))
                        current_year = datetime.now().year
                        if year > current_year or year < 1900:
                            confidence = min(1.0, confidence + 0.3)
                    except (AttributeError, ValueError):
                        pass
                    if len(groups) >= 2 and len(groups[1]) > 3:
                        venue = groups[1].strip()
                        if self.known_journals:
                            venue_lower = venue.lower()
                            is_known = any(
                                known.lower() in venue_lower
                                for known in self.known_journals
                            )
                            if not is_known:
                                confidence = min(1.0, confidence + 0.2)
                spans.append(HallucinationSpan(
                    text=full_match,
                    start=match.start(),
                    end=match.end(),
                    category="fabricated_citation",
                    confidence=confidence,
                    explanation="Citation pattern matches known hallucination indicators",
                ))
        return spans

    def _assess_pattern_risk(self, content: str) -> float:
        """Assess risk based on hallucination pattern markers."""
        matches = 0
        total_weight = 0.0
        for category, patterns in HALLUCINATION_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    matches += 1
                    weight = {
                        "vague_hedging": 0.3,
                        "unsupported_absolute": 0.6,
                        "speculative_language": 0.4,
                        "fabricated_references": 0.7,
                        "overprecision": 0.5,
                    }.get(category, 0.5)
                    total_weight += weight
        if matches == 0:
            return 0.0
        raw_score = total_weight / max(1, matches)
        density = min(1.0, matches / max(1, len(content.split())) * 20)
        return min(1.0, raw_score * 0.6 + density * 0.4)

    def _detect_pattern_hallucinations(self, content: str) -> List[HallucinationSpan]:
        """Detect text spans with hallucination pattern markers."""
        spans: List[HallucinationSpan] = []
        seen_spans: Set[Tuple[int, int]] = set()
        for category, patterns in HALLUCINATION_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    span = (match.start(), match.end())
                    if span in seen_spans:
                        continue
                    seen_spans.add(span)
                    weight = {
                        "vague_hedging": 0.3,
                        "unsupported_absolute": 0.6,
                        "speculative_language": 0.4,
                        "fabricated_references": 0.7,
                        "overprecision": 0.5,
                    }.get(category, 0.5)
                    context_start = max(0, match.start() - 40)
                    context_end = min(len(content), match.end() + 40)
                    context = content[context_start:context_end].strip()
                    spans.append(HallucinationSpan(
                        text=context,
                        start=context_start,
                        end=context_end,
                        category=f"pattern_{category}",
                        confidence=weight,
                        explanation=f"Text contains {category.replace('_', ' ')} pattern",
                    ))
        return spans

    def _generate_warnings(self, spans: List[HallucinationSpan], scores: HallucinationScore) -> List[str]:
        """Generate warnings based on detection results."""
        warnings: List[str] = []
        if scores.overall_score > self.detection_threshold:
            warnings.append(
                f"Overall hallucination score ({scores.overall_score:.2f}) "
                f"exceeds threshold ({self.detection_threshold})"
            )
        if scores.named_entity_risk > self.entity_threshold:
            warnings.append("Multiple unverified named entities detected")
        if scores.numerical_risk > self.numerical_threshold:
            warnings.append("Suspicious numerical claims detected")
        if scores.citation_risk > self.citation_threshold:
            warnings.append("Potentially fabricated citations detected")
        if scores.contradiction_score > 0.3:
            warnings.append("Internal contradictions found in content")
        entity_count = len([s for s in spans if s.category == "unverified_entity"])
        if entity_count > 5:
            warnings.append(f"High number ({entity_count}) of unverified entities")
        citation_count = len([s for s in spans if s.category == "fabricated_citation"])
        if citation_count > 3:
            warnings.append(f"Multiple ({citation_count}) potentially fabricated citations")
        return warnings

    def _generate_recommendations(self, spans: List[HallucinationSpan], scores: HallucinationScore) -> List[str]:
        """Generate recommendations to address detected hallucinations."""
        recommendations: List[str] = []
        if scores.factual_consistency < 0.6:
            recommendations.append("Verify all factual claims against reliable sources")
        if scores.named_entity_risk > self.entity_threshold:
            recommendations.append("Verify named entities (people, organizations, places) for accuracy")
        if scores.numerical_risk > self.numerical_threshold:
            recommendations.append("Cross-check all numerical values and statistics")
        if scores.citation_risk > self.citation_threshold:
            recommendations.append("Verify all citations against actual published works")
        if scores.contradiction_score > 0.3:
            recommendations.append("Resolve contradictory statements to ensure logical consistency")
        if scores.pattern_marker_score > self.pattern_threshold:
            recommendations.append("Replace vague or hedged language with precise, verifiable claims")
        pattern_categories = set(s.category for s in spans)
        if "pattern_unsupported_absolute" in pattern_categories:
            recommendations.append("Qualify absolute claims with appropriate evidence or sources")
        if not recommendations:
            recommendations.append("Content appears factually consistent with low hallucination risk")
        return recommendations

    def check_factual_consistency(self, content: str, source_text: Optional[str] = None) -> float:
        """Check factual consistency against optional source material."""
        if not source_text:
            return 0.5
        scores = self._compute_all_scores(content)
        source_sentences = set(re.split(r"(?<=[.!?])\s+", source_text.lower().strip()))
        content_sentences = re.split(r"(?<=[.!?])\s+", content.strip())
        matched = 0
        for c_sent in content_sentences:
            c_words = set(c_sent.split())
            for s_sent in source_sentences:
                s_words = set(s_sent.split())
                if len(c_words) > 3 and len(s_words) > 3:
                    overlap = len(c_words & s_words) / max(len(c_words), len(s_words))
                    if overlap > 0.6:
                        matched += 1
                        break
        source_ratio = matched / max(1, len(content_sentences))
        combined = (source_ratio * 0.4 + (1.0 - scores.overall_score) * 0.6)
        return round(min(1.0, max(0.0, combined)), 4)

    def detect_statistical_outliers(self, content: str) -> List[Dict[str, Any]]:
        """Detect statistical outliers that may indicate hallucinations."""
        outliers: List[Dict[str, Any]] = []
        numbers = NUMBER_PATTERN.findall(content)
        parsed_numbers: List[float] = []
        for num_str in numbers:
            cleaned = num_str.replace(",", "").replace("%", "").strip().lower()
            if cleaned in ("thousand", "million", "billion", "trillion", ""):
                continue
            try:
                value = float(cleaned)
                parsed_numbers.append(value)
            except ValueError:
                continue
        if len(parsed_numbers) < 5:
            return outliers
        parsed_numbers.sort()
        q1 = parsed_numbers[len(parsed_numbers) // 4]
        q3 = parsed_numbers[3 * len(parsed_numbers) // 4]
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        for num_str in numbers:
            cleaned = num_str.replace(",", "").replace("%", "").strip().lower()
            if cleaned in ("thousand", "million", "billion", "trillion", ""):
                continue
            try:
                value = float(cleaned)
                if value != 0 and (value < lower_bound or value > upper_bound):
                    outliers.append({
                        "value": value,
                        "raw": num_str,
                        "reason": f"Statistical outlier (bounds: {lower_bound:.2f}, {upper_bound:.2f})",
                    })
            except ValueError:
                continue
        return outliers

    def get_entity_uniqueness_score(self, content: str) -> float:
        """Score how unique/unusual entities in the content are."""
        entities = ENTITY_PATTERN.findall(content)
        if not entities:
            return 0.0
        known = sum(1 for e in entities if self._is_known_entity(e))
        return round(1.0 - (known / len(entities)), 4)

    def extract_factual_claims(self, content: str) -> List[Dict[str, Any]]:
        """Extract individual factual claims for verification."""
        claims: List[Dict[str, Any]] = []
        sentences = re.split(r"(?<=[.!?])\s+", content)
        for i, sentence in enumerate(sentences):
            stripped = sentence.strip()
            if not stripped or len(stripped) < 15:
                continue
            claim_type = "unknown"
            numbers = NUMBER_PATTERN.findall(stripped)
            entities = ENTITY_PATTERN.findall(stripped)
            has_citation = bool(re.search(r"\([^)]*\d{4}[^)]*\)|\[\d+\]", stripped))
            if numbers and entities:
                claim_type = "statistical"
            elif entities:
                claim_type = "entity_claim"
            elif numbers:
                claim_type = "numerical"
            if has_citation:
                claim_type += "_cited" if claim_type != "unknown" else "cited"
            claims.append({
                "index": i,
                "text": stripped,
                "type": claim_type,
                "has_citation": has_citation,
                "entity_count": len(entities),
                "number_count": len(numbers),
            })
        return claims

    def set_known_entities(self, entities: List[str]) -> None:
        """Set the known entities list for validation."""
        self.known_entities = set(entities)

    def add_known_entity(self, entity: str) -> None:
        """Add a single known entity."""
        self.known_entities.add(entity)

    def set_knowledge_base(self, kb: Dict[str, Any]) -> None:
        """Set the knowledge base for fact checking."""
        self.knowledge_base = kb
        if "entities" in kb:
            self.known_entities.update(e.lower() for e in kb["entities"])

    def get_hallucination_fingerprint(self, content: str) -> Dict[str, Any]:
        """Generate a hallucination fingerprint for the content."""
        scores = self._compute_all_scores(content)
        entities = ENTITY_PATTERN.findall(content)
        numbers = NUMBER_PATTERN.findall(content)
        return {
            "overall_score": round(scores.overall_score, 4),
            "dimensions": {
                "contradiction": round(scores.contradiction_score, 4),
                "entity_risk": round(scores.named_entity_risk, 4),
                "numerical_risk": round(scores.numerical_risk, 4),
                "citation_risk": round(scores.citation_risk, 4),
                "pattern_risk": round(scores.pattern_marker_score, 4),
            },
            "entity_count": len(entities),
            "known_entity_count": sum(1 for e in entities if self._is_known_entity(e)),
            "number_count": len(numbers),
            "suspicious_number_count": sum(1 for n in numbers if self._is_suspicious_number(n)),
        }
