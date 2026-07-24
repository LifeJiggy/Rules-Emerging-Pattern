"""Quality validation for generated outputs."""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple, Counter as CounterType
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class QualityMetrics:
    """Metrics for content quality assessment."""
    readability_score: float = 0.0
    coherence_score: float = 0.0
    relevance_score: float = 0.0
    completeness_score: float = 0.0
    grammar_score: float = 1.0
    tone_score: float = 1.0
    structure_score: float = 1.0
    redundancy_score: float = 1.0
    consistency_score: float = 1.0


@dataclass
class QualityIssue:
    """Represents a quality issue found in content."""
    issue_type: str
    description: str
    severity: str
    location: Optional[str] = None
    suggestion: Optional[str] = None
    confidence: float = 0.8


@dataclass
class ReadabilityDetails:
    """Detailed readability metrics."""
    flesch_score: float = 0.0
    avg_words_per_sentence: float = 0.0
    avg_syllables_per_word: float = 0.0
    long_sentence_count: int = 0
    short_sentence_count: int = 0
    complex_word_count: int = 0
    total_sentences: int = 0
    total_words: int = 0
    grade_level: str = "unknown"


@dataclass
class StructureDetails:
    """Detailed structure metrics."""
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0
    min_paragraph_length: int = 0
    max_paragraph_length: int = 0
    section_count: int = 0
    has_introduction: bool = False
    has_conclusion: bool = False
    paragraph_length_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class QualityReport:
    """Comprehensive quality report."""
    overall_score: float = 0.0
    passed: bool = True
    metrics: QualityMetrics = field(default_factory=QualityMetrics)
    readability_details: Optional[ReadabilityDetails] = None
    structure_details: Optional[StructureDetails] = None
    issues: List[QualityIssue] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    tone_assessment: Optional[Dict[str, Any]] = None
    redundancy_details: List[Dict[str, Any]] = field(default_factory=list)


TRANSITION_WORDS: Set[str] = {
    "however", "therefore", "furthermore", "moreover", "consequently",
    "meanwhile", "additionally", "similarly", "nevertheless", "nonetheless",
    "accordingly", "subsequently", "conversely", "otherwise", "hence",
    "thus", "indeed", "instead", "likewise", "notably", "specifically",
    "particularly", "regarding", "besides", "further", "plus",
    "alternatively", "although", "though", "while", "whereas",
    "despite", "in spite of", "on the contrary", "in contrast",
    "on the other hand", "in addition", "for example", "for instance",
    "in particular", "as a result", "because of", "due to",
    "first", "second", "third", "finally", "lastly",
    "firstly", "secondly", "thirdly", "initially", "ultimately",
    "then", "next", "afterwards", "later", "previously",
}

GRAMMAR_ISSUE_PATTERNS: List[Tuple[str, Pattern, str]] = [
    ("subject_verb_agreement", re.compile(r"\b(he|she|it)\s+(don't|doesn't|wasn't|weren't)\b", re.IGNORECASE), "Check subject-verb agreement"),
    ("double_negative", re.compile(r"\b(not\s+(no|none|never|nothing|nobody|nowhere))\b", re.IGNORECASE), "Avoid double negatives"),
    ("sentence_fragment", re.compile(r"(?:^|\s)([A-Z][a-z]*(?:\s+[a-z]+){0,3})[.!?](?=\s+[a-z])"), "Check for sentence fragments"),
    ("run_on_sentence", re.compile(r"[a-z]+\s+(?:and|but|or)\s+[a-z]+,\s+(?:and|but|or)\s+[a-z]+,\s+(?:and|but|or)\s+[a-z]+"), "Consider splitting long sentences"),
    ("misplaced_modifier", re.compile(r"\b(almost|nearly|just|hardly|scarcely|barely)\s+\w+,\s+\w+\b", re.IGNORECASE), "Check modifier placement"),
    ("wordiness", re.compile(r"\b(in order to|due to the fact that|at this point in time|in the event that)\b", re.IGNORECASE), "Use simpler phrasing"),
    ("informal_contraction", re.compile(r"\b(gonna|wanna|gotta|ain't|y'all)\b", re.IGNORECASE), "Use formal language"),
]

PASSIVE_VOICE_PATTERN = re.compile(r"\b(am|is|are|was|were|be|been|being)\s+\w+ed\b", re.IGNORECASE)
REDUNDANCY_PATTERN = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

POSITIVE_WORDS: Set[str] = {
    "excellent", "outstanding", "remarkable", "superior", "exceptional",
    "beneficial", "effective", "successful", "innovative", "efficient",
    "improved", "enhanced", "optimal", "robust", "reliable",
    "comprehensive", "thorough", "accurate", "precise", "powerful",
    "significant", "substantial", "notable", "impressive", "valuable",
}
NEGATIVE_WORDS: Set[str] = {
    "poor", "inadequate", "insufficient", "failure", "failed",
    "problematic", "deficient", "weak", "flawed", "inferior",
    "ineffective", "inefficient", "suboptimal", "unreliable", "inaccurate",
    "limited", "restricted", "unsatisfactory", "unacceptable", "detrimental",
}
FORMAL_WORDS: Set[str] = {
    "therefore", "consequently", "furthermore", "nevertheless", "nonetheless",
    "accordingly", "subsequently", "heretofore", "hereafter", "thereby",
    "therein", "thereafter", "thereupon", "wherein", "whereby",
    "thus", "hence", "thence", "whilst", "amongst",
}
INFORMAL_WORDS: Set[str] = {
    "gonna", "wanna", "gotta", "ain't", "yeah", "nah",
    "kinda", "sorta", "lotsa", "dunno", "gimme",
    "cool", "awesome", "amazing", "literally", "basically",
    "actually", "honestly", "frankly", "anyways", "cuz",
}


class QualityValidator:
    """Validates content quality based on various metrics."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.min_readability: float = self.config.get("min_readability", 0.6)
        self.min_coherence: float = self.config.get("min_coherence", 0.7)
        self.min_relevance: float = self.config.get("min_relevance", 0.5)
        self.min_completeness: float = self.config.get("min_completeness", 0.6)
        self.min_grammar: float = self.config.get("min_grammar", 0.7)
        self.min_tone: float = self.config.get("min_tone", 0.5)
        self.min_structure: float = self.config.get("min_structure", 0.6)
        self.max_redundancy: float = self.config.get("max_redundancy", 0.3)
        self.min_consistency: float = self.config.get("min_consistency", 0.6)
        self.quality_thresholds: Dict[str, float] = {
            "readability": self.min_readability,
            "coherence": self.min_coherence,
            "relevance": self.min_relevance,
            "completeness": self.min_completeness,
            "grammar": self.min_grammar,
            "tone": self.min_tone,
            "structure": self.min_structure,
            "consistency": self.min_consistency,
        }
        self.logger = logger
        self.logger.info("QualityValidator initialized with thresholds: %s", self.quality_thresholds)

    def validate_quality(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate content quality and return comprehensive assessment."""
        self.logger.debug("Validating quality for content length: %d", len(content))
        metrics = self._calculate_metrics(content, context)
        issues = self._identify_issues(metrics)
        readability_details = self._compute_readability_details(content)
        structure_details = self._compute_structure_details(content)
        tone_assessment = self._assess_tone(content)
        redundancy_details = self._detect_redundancies(content)
        passed = len(issues) == 0
        report = QualityReport(
            overall_score=metrics.readability_score * 0.15
            + metrics.coherence_score * 0.15
            + metrics.relevance_score * 0.10
            + metrics.completeness_score * 0.10
            + metrics.grammar_score * 0.15
            + metrics.tone_score * 0.10
            + metrics.structure_score * 0.10
            + (1.0 - metrics.redundancy_score) * 0.05
            + metrics.consistency_score * 0.10,
            passed=passed,
            metrics=metrics,
            readability_details=readability_details,
            structure_details=structure_details,
            issues=issues,
            tone_assessment=tone_assessment,
            redundancy_details=redundancy_details,
        )
        report.recommendations = self._generate_recommendations(report)
        result = {
            "passed": passed,
            "overall_score": round(report.overall_score, 4),
            "metrics": {
                "readability_score": metrics.readability_score,
                "coherence_score": metrics.coherence_score,
                "relevance_score": metrics.relevance_score,
                "completeness_score": metrics.completeness_score,
                "grammar_score": metrics.grammar_score,
                "tone_score": metrics.tone_score,
                "structure_score": metrics.structure_score,
                "redundancy_score": metrics.redundancy_score,
                "consistency_score": metrics.consistency_score,
            },
            "readability_details": {
                "flesch_score": readability_details.flesch_score,
                "avg_words_per_sentence": round(readability_details.avg_words_per_sentence, 2),
                "avg_syllables_per_word": round(readability_details.avg_syllables_per_word, 2),
                "long_sentence_count": readability_details.long_sentence_count,
                "short_sentence_count": readability_details.short_sentence_count,
                "complex_word_count": readability_details.complex_word_count,
                "total_sentences": readability_details.total_sentences,
                "total_words": readability_details.total_words,
                "grade_level": readability_details.grade_level,
            },
            "structure_details": {
                "paragraph_count": structure_details.paragraph_count,
                "avg_paragraph_length": round(structure_details.avg_paragraph_length, 2),
                "min_paragraph_length": structure_details.min_paragraph_length,
                "max_paragraph_length": structure_details.max_paragraph_length,
                "section_count": structure_details.section_count,
                "has_introduction": structure_details.has_introduction,
                "has_conclusion": structure_details.has_conclusion,
                "paragraph_length_distribution": structure_details.paragraph_length_distribution,
            },
            "tone_assessment": tone_assessment,
            "redundancy_details": redundancy_details,
            "issues": [
                {"type": i.issue_type, "description": i.description, "severity": i.severity, "suggestion": i.suggestion}
                for i in issues
            ],
            "recommendations": report.recommendations,
        }
        self.logger.info(
            "Quality validation completed: passed=%s, overall_score=%s, issues=%d",
            passed, result["overall_score"], len(issues),
        )
        return result

    def _calculate_metrics(self, content: str, context: Optional[Dict[str, Any]]) -> QualityMetrics:
        """Calculate all quality metrics for content."""
        readability = self._calculate_readability(content)
        coherence = self._calculate_coherence(content)
        relevance = self._calculate_relevance(content, context)
        completeness = self._calculate_completeness(content)
        grammar = self._calculate_grammar(content)
        tone = self._calculate_tone(content)
        structure = self._calculate_structure(content)
        redundancy = self._calculate_redundancy(content)
        consistency = self._calculate_consistency(content)
        return QualityMetrics(
            readability_score=readability,
            coherence_score=coherence,
            relevance_score=relevance,
            completeness_score=completeness,
            grammar_score=grammar,
            tone_score=tone,
            structure_score=structure,
            redundancy_score=redundancy,
            consistency_score=consistency,
        )

    def _calculate_readability(self, content: str) -> float:
        """Calculate readability score using Flesch-based metrics."""
        sentences = re.split(r"[.!?]+", content)
        words = content.split()
        if len(sentences) <= 1 or len(words) <= 3:
            return 0.0
        sentences = [s.strip() for s in sentences if s.strip()]
        total_sentences = len(sentences)
        total_words = len(words)
        avg_words_per_sentence = total_words / total_sentences if total_sentences > 0 else 0
        syllable_count = sum(self._count_syllables(w) for w in words)
        avg_syllables_per_word = syllable_count / total_words if total_words > 0 else 0
        flesch = 206.835 - 1.015 * avg_words_per_sentence - 84.6 * avg_syllables_per_word
        normalized = max(0.0, min(1.0, flesch / 100.0))
        return round(normalized, 4)

    def _count_syllables(self, word: str) -> int:
        """Estimate syllable count for a word."""
        word = word.lower().strip().strip(".,!?;:\"'()[]{}")
        if not word:
            return 1
        vowel_groups = re.findall(r"[aeiouy]+", word)
        count = len(vowel_groups) if vowel_groups else 1
        if word.endswith("e") and count > 1:
            count -= 1
        if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiouy":
            count += 1
        if count == 0:
            count = 1
        return count

    def _calculate_coherence(self, content: str) -> float:
        """Calculate coherence score based on flow and structure."""
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            return 0.8
        transition_count = self._count_transitions(content)
        transition_density = transition_count / max(1, len(paragraphs))
        coherence = min(1.0, 0.5 + transition_density * 0.3)
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) >= 3:
            pronoun_chains = 0
            for i in range(1, len(sentences)):
                prev_words = set(sentences[i - 1].lower().split())
                curr_words = set(sentences[i].lower().split())
                pronouns = {"it", "this", "that", "these", "those", "he", "she", "they", "them", "we", "you"}
                if curr_words & pronouns:
                    noun_refs = prev_words - pronouns
                    if noun_refs:
                        pronoun_chains += 1
            if len(sentences) > 1:
                chain_ratio = pronoun_chains / (len(sentences) - 1)
                coherence = min(1.0, coherence + chain_ratio * 0.2)
        return round(coherence, 4)

    def _calculate_relevance(self, content: str, context: Optional[Dict[str, Any]]) -> float:
        """Calculate relevance to context."""
        if not context or "topic" not in context:
            return 0.7
        topic = context["topic"].lower()
        content_lower = content.lower()
        topic_words = topic.split()
        if not topic_words:
            return 0.5
        matches = sum(1 for word in topic_words if word in content_lower)
        direct_score = matches / len(topic_words)
        if "keywords" in context:
            keywords = context["keywords"]
            if isinstance(keywords, list) and keywords:
                kw_matches = sum(1 for kw in keywords if kw.lower() in content_lower)
                kw_score = kw_matches / len(keywords)
                direct_score = direct_score * 0.6 + kw_score * 0.4
        return round(min(1.0, direct_score), 4)

    def _calculate_completeness(self, content: str) -> float:
        """Calculate completeness score."""
        min_length = 100
        ideal_length = 500
        length = len(content)
        if length < min_length:
            return round(length / min_length, 4)
        base_score = min(1.0, 0.7 + (length - min_length) / (ideal_length * 3))
        sections = self._count_sections(content)
        if sections >= 2:
            base_score = min(1.0, base_score + 0.1)
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        paragraph_lengths = [len(p.split()) for p in paragraphs]
        if paragraph_lengths:
            avg_p_len = sum(paragraph_lengths) / len(paragraph_lengths)
            if avg_p_len < 15:
                base_score = max(0.0, base_score - 0.15)
        return round(base_score, 4)

    def _calculate_grammar(self, content: str) -> float:
        """Calculate grammar quality score."""
        issues_found = 0
        for issue_type, pattern, _ in GRAMMAR_ISSUE_PATTERNS:
            matches = pattern.findall(content)
            issues_found += len(matches)
        passive_count = len(PASSIVE_VOICE_PATTERN.findall(content))
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        total_sentences = len(sentences)
        if total_sentences == 0:
            return 1.0
        grammar_score = 1.0 - (issues_found / max(1, total_sentences)) * 0.3
        grammar_score -= (passive_count / max(1, total_sentences)) * 0.1
        return round(max(0.0, grammar_score), 4)

    def _calculate_tone(self, content: str) -> float:
        """Calculate tone appropriateness score."""
        assessment = self._assess_tone(content)
        if assessment["inconsistency"]:
            return 0.5
        return round(assessment["score"], 4)

    def _calculate_structure(self, content: str) -> float:
        """Calculate structure quality score."""
        details = self._compute_structure_details(content)
        if details.paragraph_count == 0:
            return 0.3
        score = 0.6
        if details.has_introduction:
            score += 0.1
        if details.has_conclusion:
            score += 0.1
        if details.paragraph_count >= 3:
            score += 0.05
        if details.avg_paragraph_length >= 30:
            score += 0.05
        bad_paras = details.paragraph_length_distribution.get("too_short", 0) + details.paragraph_length_distribution.get("too_long", 0)
        if details.paragraph_count > 0:
            score -= (bad_paras / details.paragraph_count) * 0.2
        return round(min(1.0, max(0.0, score)), 4)

    def _calculate_redundancy(self, content: str) -> float:
        """Calculate redundancy score (higher means less redundant)."""
        redundancies = self._detect_redundancies(content)
        if not redundancies:
            return 1.0
        penalty = min(1.0, len(redundancies) * 0.15)
        return round(max(0.0, 1.0 - penalty), 4)

    def _calculate_consistency(self, content: str) -> float:
        """Calculate consistency score across content."""
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < 3:
            return 0.8
        terms = self._extract_terminology(content)
        inconsistencies = 0
        for term, variants in terms.items():
            if len(variants) > 1:
                inconsistencies += 1
        consistency_penalty = min(0.5, inconsistencies * 0.1)
        personal_pronouns = set()
        for sentence in sentences:
            for pronoun in ["I", "we", "you", "one", "the author", "this paper"]:
                if pronoun in sentence.lower():
                    personal_pronouns.add(pronoun)
        if len(personal_pronouns) > 1:
            consistency_penalty += 0.1
        return round(max(0.0, min(1.0, 1.0 - consistency_penalty)), 4)

    def _count_transitions(self, content: str) -> int:
        """Count transition words in content."""
        content_lower = content.lower()
        count = 0
        for transition in TRANSITION_WORDS:
            if " " in transition:
                count += len(re.findall(re.escape(transition), content_lower))
            else:
                count += len(re.findall(r"\b" + re.escape(transition) + r"\b", content_lower))
        return count

    def _count_sections(self, content: str) -> int:
        """Count numbered or headed sections in content."""
        patterns = [
            re.compile(r"^#{1,6}\s+\w+", re.MULTILINE),
            re.compile(r"^\d+\.\s+\w+", re.MULTILINE),
            re.compile(r"^[A-Z][^.]*[a-z]+:\s", re.MULTILINE),
        ]
        count = 0
        for pat in patterns:
            count += len(pat.findall(content))
        return count

    def _compute_readability_details(self, content: str) -> ReadabilityDetails:
        """Compute detailed readability metrics."""
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = content.split()
        if not sentences or not words:
            return ReadabilityDetails()
        total_sentences = len(sentences)
        total_words = len(words)
        avg_words = total_words / total_sentences
        syllable_count = sum(self._count_syllables(w) for w in words)
        avg_syllables = syllable_count / total_words if total_words > 0 else 0
        flesch = 206.835 - 1.015 * avg_words - 84.6 * avg_syllables
        long_sentences = sum(1 for s in sentences if len(s.split()) > 25)
        short_sentences = sum(1 for s in sentences if len(s.split()) < 8)
        complex_words = sum(1 for w in words if self._count_syllables(w) >= 3)
        if flesch >= 90:
            grade = "very_easy"
        elif flesch >= 80:
            grade = "easy"
        elif flesch >= 70:
            grade = "fairly_easy"
        elif flesch >= 60:
            grade = "standard"
        elif flesch >= 50:
            grade = "fairly_difficult"
        elif flesch >= 30:
            grade = "difficult"
        else:
            grade = "very_difficult"
        return ReadabilityDetails(
            flesch_score=round(flesch, 2),
            avg_words_per_sentence=round(avg_words, 2),
            avg_syllables_per_word=round(avg_syllables, 4),
            long_sentence_count=long_sentences,
            short_sentence_count=short_sentences,
            complex_word_count=complex_words,
            total_sentences=total_sentences,
            total_words=total_words,
            grade_level=grade,
        )

    def _compute_structure_details(self, content: str) -> StructureDetails:
        """Compute detailed structure metrics."""
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            return StructureDetails()
        paragraph_lengths = [len(p.split()) for p in paragraphs]
        has_intro = False
        has_conclusion = False
        if paragraphs:
            first_lower = paragraphs[0].lower()
            has_intro = any(word in first_lower for word in [
                "introduction", "overview", "background", "this paper",
                "this article", "this report", "in this",
            ]) or len(first_lower) < 200
            last_lower = paragraphs[-1].lower()
            has_conclusion = any(word in last_lower for word in [
                "conclusion", "summary", "in conclusion", "to conclude",
                "in summary", "overall", "finally", "in closing",
                "to summarize",
            ]) or len(last_lower) < 200 and len(paragraphs) > 2
        dist: Dict[str, int] = {"too_short": 0, "short": 0, "medium": 0, "long": 0, "too_long": 0}
        for pl in paragraph_lengths:
            if pl < 10:
                dist["too_short"] += 1
            elif pl < 25:
                dist["short"] += 1
            elif pl < 60:
                dist["medium"] += 1
            elif pl < 100:
                dist["long"] += 1
            else:
                dist["too_long"] += 1
        sections = self._count_sections(content)
        return StructureDetails(
            paragraph_count=len(paragraphs),
            avg_paragraph_length=sum(paragraph_lengths) / len(paragraph_lengths),
            min_paragraph_length=min(paragraph_lengths),
            max_paragraph_length=max(paragraph_lengths),
            section_count=sections,
            has_introduction=has_intro,
            has_conclusion=has_conclusion,
            paragraph_length_distribution=dist,
        )

    def _assess_tone(self, content: str) -> Dict[str, Any]:
        """Assess the tone of the content."""
        words = content.lower().split()
        if not words:
            return {"overall_tone": "neutral", "score": 1.0, "inconsistency": False, "formal_ratio": 0.5}
        positive_count = sum(1 for w in words if w.strip(".,!?;:\"'()") in POSITIVE_WORDS)
        negative_count = sum(1 for w in words if w.strip(".,!?;:\"'()") in NEGATIVE_WORDS)
        formal_count = sum(1 for w in words if w.strip(".,!?;:\"'()") in FORMAL_WORDS)
        informal_count = sum(1 for w in words if w.strip(".,!?;:\"'()") in INFORMAL_WORDS)
        total_formal_indicators = formal_count + informal_count
        formal_ratio = formal_count / max(1, total_formal_indicators)
        tone_score = 0.5 + (formal_ratio - 0.5) * 0.6
        if positive_count > negative_count * 3 and negative_count > 0:
            tone_score = min(1.0, tone_score + 0.1)
        if informal_count > formal_count:
            tone_score = max(0.0, tone_score - 0.2)
        inconsistency = (positive_count > 0 and negative_count > 3 and abs(positive_count - negative_count) < 3)
        if positive_count > negative_count * 2:
            overall_tone = "positive"
        elif negative_count > positive_count * 2:
            overall_tone = "negative"
        elif formal_ratio > 0.7:
            overall_tone = "formal"
        elif informal_count > 0:
            overall_tone = "informal"
        else:
            overall_tone = "neutral"
        return {
            "overall_tone": overall_tone,
            "score": round(tone_score, 4),
            "positive_word_count": positive_count,
            "negative_word_count": negative_count,
            "formal_word_count": formal_count,
            "informal_word_count": informal_count,
            "formal_ratio": round(formal_ratio, 4),
            "inconsistency": inconsistency,
        }

    def _detect_redundancies(self, content: str) -> List[Dict[str, Any]]:
        """Detect redundant phrases and repeated content."""
        redundancies: List[Dict[str, Any]] = []
        for match in REDUNDANCY_PATTERN.finditer(content):
            word = match.group(1)
            if len(word) > 3:
                redundancies.append({
                    "type": "immediate_repetition",
                    "text": match.group(),
                    "position": match.start(),
                    "word": word,
                })
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip().lower() for s in sentences if s.strip()]
        for i, s1 in enumerate(sentences):
            for j in range(i + 1, min(i + 5, len(sentences))):
                s2 = sentences[j]
                if s1 == s2 and len(s1) > 20:
                    redundancies.append({
                        "type": "duplicate_sentence",
                        "text": s1[:100],
                        "sentence_1": i,
                        "sentence_2": j,
                    })
                elif s1 and s2 and len(s1) > 30 and len(s2) > 30:
                    words1 = set(s1.split())
                    words2 = set(s2.split())
                    overlap = len(words1 & words2) / max(len(words1), len(words2))
                    if overlap > 0.75:
                        redundancies.append({
                            "type": "near_duplicate",
                            "text": s1[:80],
                            "sentence_1": i,
                            "sentence_2": j,
                            "overlap_ratio": round(overlap, 4),
                        })
        phrases = [
            (r"\bin\s+order\s+to\b", "to"),
            (r"\bdue\s+to\s+the\s+fact\s+that\b", "because"),
            (r"\bat\s+this\s+point\s+in\s+time\b", "now"),
            (r"\bin\s+the\s+event\s+that\b", "if"),
            (r"\ba\s+majority\s+of\b", "most"),
            (r"\ba\s+number\s+of\b", "some"),
            (r"\bis\s+able\s+to\b", "can"),
            (r"\bhas\s+the\s+ability\s+to\b", "can"),
        ]
        for phrase_pat, suggestion in phrases:
            for match in re.finditer(phrase_pat, content, re.IGNORECASE):
                redundancies.append({
                    "type": "wordy_phrase",
                    "text": match.group(),
                    "position": match.start(),
                    "suggestion": suggestion,
                })
        return redundancies

    def _extract_terminology(self, content: str) -> Dict[str, Set[str]]:
        """Extract terminology variants for consistency checking."""
        terms: Dict[str, Set[str]] = {}
        patterns = [
            re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"),
            re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,})*\b"),
        ]
        for pat in patterns:
            for match in pat.finditer(content):
                term = match.group()
                if len(term) > 3:
                    normalized = term.lower()
                    if normalized not in terms:
                        terms[normalized] = set()
                    terms[normalized].add(term)
        return terms

    def _identify_issues(self, metrics: QualityMetrics) -> List[QualityIssue]:
        """Identify quality issues based on metrics."""
        issues: List[QualityIssue] = []
        if metrics.readability_score < self.quality_thresholds["readability"]:
            issues.append(QualityIssue(
                issue_type="readability",
                description=f"Readability too low: {metrics.readability_score:.2f}",
                severity="warning",
                suggestion="Simplify sentence structure and vocabulary to improve readability.",
            ))
        if metrics.coherence_score < self.quality_thresholds["coherence"]:
            issues.append(QualityIssue(
                issue_type="coherence",
                description=f"Coherence issues detected: {metrics.coherence_score:.2f}",
                severity="warning",
                suggestion="Add transition words and improve paragraph flow.",
            ))
        if metrics.relevance_score < self.quality_thresholds["relevance"]:
            issues.append(QualityIssue(
                issue_type="relevance",
                description=f"Content may not be relevant: {metrics.relevance_score:.2f}",
                severity="warning",
                suggestion="Focus on the main topic and remove tangential content.",
            ))
        if metrics.completeness_score < self.quality_thresholds["completeness"]:
            issues.append(QualityIssue(
                issue_type="completeness",
                description=f"Content appears incomplete: {metrics.completeness_score:.2f}",
                severity="warning",
                suggestion="Expand on key points and add supporting details.",
            ))
        if metrics.grammar_score < self.quality_thresholds["grammar"]:
            issues.append(QualityIssue(
                issue_type="grammar",
                description=f"Grammar quality below threshold: {metrics.grammar_score:.2f}",
                severity="warning",
                suggestion="Review grammar and sentence structure.",
            ))
        if metrics.tone_score < self.quality_thresholds["tone"]:
            issues.append(QualityIssue(
                issue_type="tone",
                description=f"Tone inconsistency detected: {metrics.tone_score:.2f}",
                severity="info",
                suggestion="Maintain a consistent tone throughout the content.",
            ))
        if metrics.structure_score < self.quality_thresholds["structure"]:
            issues.append(QualityIssue(
                issue_type="structure",
                description=f"Structure quality below threshold: {metrics.structure_score:.2f}",
                severity="warning",
                suggestion="Improve document structure with clear sections and balanced paragraphs.",
            ))
        if metrics.redundancy_score < (1.0 - self.max_redundancy):
            issues.append(QualityIssue(
                issue_type="redundancy",
                description=f"Redundancy detected: redundancy score is {metrics.redundancy_score:.2f}",
                severity="info",
                suggestion="Remove repeated content and wordy phrases.",
            ))
        if metrics.consistency_score < self.quality_thresholds["consistency"]:
            issues.append(QualityIssue(
                issue_type="consistency",
                description=f"Consistency issues detected: {metrics.consistency_score:.2f}",
                severity="warning",
                suggestion="Use consistent terminology and voice throughout the content.",
            ))
        return issues

    def _generate_recommendations(self, report: QualityReport) -> List[str]:
        """Generate recommendations for identified issues."""
        recommendations: List[str] = []
        for issue in report.issues:
            if issue.suggestion and issue.suggestion not in recommendations:
                recommendations.append(issue.suggestion)
        if report.readability_details:
            rd = report.readability_details
            if rd.long_sentence_count > rd.total_sentences * 0.3:
                recommendations.append("Break down long sentences for better readability.")
            if rd.complex_word_count > rd.total_words * 0.15:
                recommendations.append("Replace complex words with simpler alternatives where possible.")
        if report.structure_details:
            sd = report.structure_details
            if not sd.has_introduction:
                recommendations.append("Add an introductory section to set context.")
            if not sd.has_conclusion:
                recommendations.append("Add a concluding section to summarize key points.")
            too_short = sd.paragraph_length_distribution.get("too_short", 0)
            if too_short > sd.paragraph_count * 0.3:
                recommendations.append("Merge very short paragraphs for better flow.")
            too_long = sd.paragraph_length_distribution.get("too_long", 0)
            if too_long > 0:
                recommendations.append("Consider splitting very long paragraphs.")
        if report.tone_assessment and report.tone_assessment.get("inconsistency"):
            recommendations.append("Maintain consistent tone throughout the document.")
        if report.redundancy_details:
            wordy_count = sum(1 for r in report.redundancy_details if r["type"] == "wordy_phrase")
            if wordy_count > 0:
                recommendations.append("Replace wordy phrases with concise alternatives.")
            dup_count = sum(1 for r in report.redundancy_details if r["type"] in ("duplicate_sentence", "near_duplicate"))
            if dup_count > 0:
                recommendations.append("Remove duplicate or near-duplicate sentences.")
        if not recommendations:
            recommendations.append("Content quality meets all thresholds.")
        return recommendations

    def check_readability(self, content: str) -> Dict[str, Any]:
        """Convenience method for readability checking only."""
        details = self._compute_readability_details(content)
        return {
            "score": details.flesch_score,
            "grade_level": details.grade_level,
            "avg_words_per_sentence": details.avg_words_per_sentence,
            "avg_syllables_per_word": details.avg_syllables_per_word,
            "long_sentence_count": details.long_sentence_count,
            "complex_word_count": details.complex_word_count,
        }

    def check_consistency(self, content: str) -> Dict[str, Any]:
        """Convenience method for consistency checking only."""
        score = self._calculate_consistency(content)
        terms = self._extract_terminology(content)
        term_variants = {t: list(v) for t, v in terms.items() if len(v) > 1}
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        pronouns_used = set()
        for s in sentences:
            for pronoun in ["I", "we", "you", "one", "the author", "this paper"]:
                if pronoun in s.lower():
                    pronouns_used.add(pronoun)
        return {
            "score": round(score, 4),
            "inconsistent_terminology": term_variants,
            "pronouns_used": list(pronouns_used),
            "has_pronoun_inconsistency": len(pronouns_used) > 1,
        }

    def analyze_tone(self, content: str) -> Dict[str, Any]:
        """Convenience method for tone analysis only."""
        return self._assess_tone(content)

    def detect_redundancies(self, content: str) -> List[Dict[str, Any]]:
        """Convenience method for redundancy detection only."""
        return self._detect_redundancies(content)

    def analyze_structure(self, content: str) -> Dict[str, Any]:
        """Convenience method for structure analysis only."""
        details = self._compute_structure_details(content)
        return {
            "paragraph_count": details.paragraph_count,
            "avg_paragraph_length": details.avg_paragraph_length,
            "paragraph_length_distribution": details.paragraph_length_distribution,
            "section_count": details.section_count,
            "has_introduction": details.has_introduction,
            "has_conclusion": details.has_conclusion,
        }
