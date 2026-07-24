"""Preference Rule Engine - Tier 3 enforcement with adaptive handling."""
import logging
import re
import json
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleContext
from rules_emerging_pattern.models.validation import ValidationResult, Suggestion

logger = logging.getLogger(__name__)


class PreferenceDomain(str, Enum):
    TONE = "tone"
    FORMATTING = "formatting"
    STYLE = "style"
    STRUCTURE = "structure"
    TERMINOLOGY = "terminology"
    LENGTH = "length"
    LANGUAGE = "language"
    ACCESSIBILITY = "accessibility"
    INCLUSIVITY = "inclusivity"
    CONSISTENCY = "consistency"


class ConfidenceLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


CONFIDENCE_THRESHOLDS = {
    ConfidenceLevel.VERY_LOW: 0.20,
    ConfidenceLevel.LOW: 0.40,
    ConfidenceLevel.MEDIUM: 0.60,
    ConfidenceLevel.HIGH: 0.80,
    ConfidenceLevel.VERY_HIGH: 0.95,
}


class PreferenceSuggestion:
    def __init__(
        self,
        category: str,
        domain: PreferenceDomain,
        suggestion_text: str,
        original_text: str = "",
        suggested_replacement: str = "",
        confidence: float = 0.75,
        auto_applicable: bool = False,
        reasoning: str = "",
        implementation_steps: Optional[List[str]] = None,
    ):
        self.category = category
        self.domain = domain
        self.suggestion_text = suggestion_text
        self.original_text = original_text
        self.suggested_replacement = suggested_replacement
        self.confidence = min(max(confidence, 0.0), 1.0)
        self.auto_applicable = auto_applicable
        self.reasoning = reasoning
        self.implementation_steps = implementation_steps or []
        self.created_at = datetime.utcnow()
        self.applied: bool = False
        self.user_approved: Optional[bool] = None
        self.feedback_score: Optional[float] = None

    def to_suggestion(self, source_rule: str) -> Suggestion:
        return Suggestion(
            type=self.domain.value,
            title=f"Preference: {self.category}",
            description=self.suggestion_text,
            confidence=self.confidence,
            original_text=self.original_text or None,
            suggested_text=self.suggested_replacement or None,
            reasoning=self.reasoning or None,
            auto_applicable=self.auto_applicable,
            user_approval_required=not self.auto_applicable,
            implementation_steps=list(self.implementation_steps),
            source_rule=source_rule,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "domain": self.domain.value,
            "suggestion_text": self.suggestion_text,
            "original_text": self.original_text,
            "suggested_replacement": self.suggested_replacement,
            "confidence": self.confidence,
            "auto_applicable": self.auto_applicable,
            "reasoning": self.reasoning,
            "applied": self.applied,
            "user_approved": self.user_approved,
            "feedback_score": self.feedback_score,
        }


class UserPreferenceProfile:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.preferred_domains: Dict[str, float] = {}
        self.rejected_suggestions: Dict[str, int] = {}
        self.accepted_suggestions: Dict[str, int] = {}
        self.custom_patterns: List[Dict[str, Any]] = []
        self.dismissed_categories: Set[str] = set()
        self.auto_apply_domains: Set[str] = set()
        self.learning_rate: float = 0.1
        self.total_suggestions: int = 0
        self.accepted_count: int = 0
        self.rejected_count: int = 0
        self.last_updated: datetime = datetime.utcnow()

    def record_feedback(self, category: str, accepted: bool, confidence: float) -> None:
        self.total_suggestions += 1
        if accepted:
            self.accepted_count += 1
            self.accepted_suggestions[category] = (
                self.accepted_suggestions.get(category, 0) + 1
            )
        else:
            self.rejected_count += 1
            self.rejected_suggestions[category] = (
                self.rejected_suggestions.get(category, 0) + 1
            )
        self.last_updated = datetime.utcnow()

    def get_acceptance_rate(self, category: Optional[str] = None) -> float:
        if category:
            total = self.accepted_suggestions.get(category, 0) + self.rejected_suggestions.get(category, 0)
            if total == 0:
                return 0.0
            return self.accepted_suggestions.get(category, 0) / total
        if self.total_suggestions == 0:
            return 0.0
        return self.accepted_count / self.total_suggestions

    def should_auto_apply(self, category: str) -> bool:
        return (
            self.get_acceptance_rate(category) >= 0.8
            and self.accepted_suggestions.get(category, 0) >= 5
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferred_domains": dict(self.preferred_domains),
            "accepted_suggestions": dict(self.accepted_suggestions),
            "rejected_suggestions": dict(self.rejected_suggestions),
            "dismissed_categories": list(self.dismissed_categories),
            "auto_apply_domains": list(self.auto_apply_domains),
            "total_suggestions": self.total_suggestions,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "acceptance_rate": round(self.get_acceptance_rate(), 4),
            "learning_rate": self.learning_rate,
            "last_updated": self.last_updated.isoformat(),
        }


class PreferencePattern:
    def __init__(
        self,
        category: str,
        domain: PreferenceDomain,
        patterns: List[str],
        regex_patterns: Optional[List[str]] = None,
        suggestion_template: str = "",
        suggested_replacement: str = "",
        base_confidence: float = 0.75,
        auto_applicable_threshold: float = 0.90,
        requires_context: bool = False,
        contextual_conditions: Optional[Dict[str, Any]] = None,
        reasoning_template: str = "",
        implementation_steps: Optional[List[str]] = None,
    ):
        self.category = category
        self.domain = domain
        self.patterns = [p.lower() for p in patterns]
        self.regex_patterns = regex_patterns or []
        self.suggestion_template = suggestion_template
        self.suggested_replacement = suggested_replacement
        self.base_confidence = base_confidence
        self.auto_applicable_threshold = auto_applicable_threshold
        self.requires_context = requires_context
        self.contextual_conditions = contextual_conditions or {}
        self.reasoning_template = reasoning_template
        self.implementation_steps = implementation_steps or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "domain": self.domain.value,
            "pattern_count": len(self.patterns),
            "regex_count": len(self.regex_patterns),
            "base_confidence": self.base_confidence,
            "auto_applicable_threshold": self.auto_applicable_threshold,
            "requires_context": self.requires_context,
        }


class PreferenceStats:
    def __init__(self):
        self.evaluation_count: int = 0
        self.suggestion_count: int = 0
        self.auto_applied_count: int = 0
        self.user_approved_count: int = 0
        self.user_rejected_count: int = 0
        self.category_counts: Dict[str, int] = {}
        self.domain_counts: Dict[str, int] = {}
        self.total_processing_time_ms: int = 0
        self.feedback_score_sum: float = 0.0
        self.feedback_count: int = 0

    def record_suggestion(
        self, category: str, domain: PreferenceDomain, auto_applied: bool, processing_ms: int
    ) -> None:
        self.evaluation_count += 1
        self.suggestion_count += 1
        self.total_processing_time_ms += processing_ms
        self.category_counts[category] = self.category_counts.get(category, 0) + 1
        domain_key = domain.value
        self.domain_counts[domain_key] = self.domain_counts.get(domain_key, 0) + 1
        if auto_applied:
            self.auto_applied_count += 1

    def record_feedback(self, accepted: bool, score: float) -> None:
        if accepted:
            self.user_approved_count += 1
        else:
            self.user_rejected_count += 1
        self.feedback_score_sum += score
        self.feedback_count += 1

    def get_average_feedback_score(self) -> float:
        if self.feedback_count == 0:
            return 0.0
        return round(self.feedback_score_sum / self.feedback_count, 4)

    def get_summary(self) -> Dict[str, Any]:
        return {
            "evaluation_count": self.evaluation_count,
            "suggestion_count": self.suggestion_count,
            "auto_applied_count": self.auto_applied_count,
            "user_approved_count": self.user_approved_count,
            "user_rejected_count": self.user_rejected_count,
            "category_counts": dict(self.category_counts),
            "domain_counts": dict(self.domain_counts),
            "avg_processing_time_ms": round(
                self.total_processing_time_ms / max(self.evaluation_count, 1), 2
            ),
            "avg_feedback_score": self.get_average_feedback_score(),
            "total_processing_time_ms": self.total_processing_time_ms,
        }


class PreferenceRuleEngine:
    """Tier 3 Preference Rule Engine with adaptive enforcement."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.tier = RuleTier.PREFERENCE
        self.config = config or {}
        self.stats = PreferenceStats()
        self._compiled_regexes: Dict[str, re.Pattern] = {}
        self._patterns: List[PreferencePattern] = []
        self._user_profiles: Dict[str, UserPreferenceProfile] = {}
        self._initialize_patterns()
        self._compile_regexes()
        logger.info(
            "PreferenceRuleEngine initialized with %d patterns across %d domains",
            len(self._patterns),
            len(set(p.domain.value for p in self._patterns)),
        )

    def _initialize_patterns(self) -> None:
        self._patterns = [
            PreferencePattern(
                category="informal_tone",
                domain=PreferenceDomain.TONE,
                patterns=[
                    "informal tone", "casual language", "slang usage",
                    "colloquial expression", "too casual", "unprofessional tone",
                    "conversational tone", "overly familiar", "slang term",
                    "text speak", "internet slang",
                ],
                regex_patterns=[
                    r"\b(gonna|wanna|gotta|kinda|sorta|cuz|dunno|gimme|lemme)\b",
                ],
                suggestion_template="Consider using a more professional tone",
                suggested_replacement="Use formal language appropriate for the context",
                base_confidence=0.75,
                auto_applicable_threshold=0.90,
                reasoning_template="The content uses informal language that may not be suitable for professional contexts",
                implementation_steps=[
                    "Replace slang with formal equivalents",
                    "Review for casual expressions",
                    "Ensure tone matches target audience",
                ],
            ),
            PreferencePattern(
                category="passive_voice",
                domain=PreferenceDomain.TONE,
                patterns=[
                    "passive voice", "was done by", "were created by",
                    "is being handled", "has been decided", "was determined",
                    "are considered", "is believed", "was found",
                    "has been shown", "were identified",
                ],
                regex_patterns=[
                    r"\b(was|were|been|being)\s+\w+ed\s+by\b",
                    r"\b(is|are)\s+\w+ed\s+(by|in|at)\b",
                ],
                suggestion_template="Consider using active voice for clarity",
                suggested_replacement="Rewrite passive constructions in active voice",
                base_confidence=0.70,
                reasoning_template="Passive voice can make content less direct and harder to read",
                implementation_steps=[
                    "Identify the subject performing the action",
                    "Rewrite with subject-verb-object structure",
                    "Maintain the same meaning with active construction",
                ],
            ),
            PreferencePattern(
                category="negative_tone",
                domain=PreferenceDomain.TONE,
                patterns=[
                    "negative language", "pessimistic tone", "critical tone",
                    "dismissive language", "blaming language", "complaint tone",
                    "aggressive wording", "hostile language", "confrontational tone",
                ],
                regex_patterns=[
                    r"\b(never|nobody|nothing|no.?one|nowhere|can.?t|won.?t|shouldn.?t)\s+\w+ly\b",
                ],
                suggestion_template="Consider using a more constructive tone",
                suggested_replacement="Rephrase with solution-oriented language",
                base_confidence=0.65,
                reasoning_template="The tone may come across as negative or discouraging",
                implementation_steps=[
                    "Focus on solutions rather than problems",
                    "Use constructive language",
                    "Maintain a positive framing where possible",
                ],
            ),
            PreferencePattern(
                category="no_formatting",
                domain=PreferenceDomain.FORMATTING,
                patterns=[
                    "no formatting", "unformatted text", "plain text only",
                    "missing formatting", "no markdown", "raw text",
                    "unstructured content", "formatting needed",
                    "plain text block", "no paragraph breaks",
                ],
                regex_patterns=[
                    r"\b\w{200,}\b",
                ],
                suggestion_template="Add proper formatting for better readability",
                suggested_replacement="Apply appropriate formatting (headings, lists, emphasis)",
                base_confidence=0.75,
                auto_applicable_threshold=0.85,
                reasoning_template="Content lacks formatting that would improve readability",
                implementation_steps=[
                    "Add section headings for structure",
                    "Use bullet points for lists",
                    "Apply bold/italic for emphasis",
                    "Break up long paragraphs",
                ],
            ),
            PreferencePattern(
                category="missing_headings",
                domain=PreferenceDomain.FORMATTING,
                patterns=[
                    "no headings", "missing headings", "no section headers",
                    "unstructured document", "no hierarchy",
                    "flat structure", "no organization",
                ],
                regex_patterns=[
                    r"^[^#\n]{200,}$",
                ],
                suggestion_template="Add hierarchical headings to structure your content",
                suggested_replacement="Use H1, H2, H3 headings to organize sections",
                base_confidence=0.70,
                auto_applicable_threshold=0.80,
                reasoning_template="Headings help readers navigate and understand content structure",
                implementation_steps=[
                    "Identify main topics as H1 headings",
                    "Add H2 headings for subsections",
                    "Use H3 for detailed sub-topics",
                ],
            ),
            PreferencePattern(
                category="inconsistent_list_style",
                domain=PreferenceDomain.FORMATTING,
                patterns=[
                    "inconsistent list", "mixed list style",
                    "numbered and bullet mix", "list format mismatch",
                    "irregular list formatting",
                ],
                regex_patterns=[
                    r"(?:^|\n)(?:\d+\.|[-*])\s.*\n(?:[-*])\s",
                ],
                suggestion_template="Standardize list formatting for consistency",
                suggested_replacement="Use uniform list style throughout",
                base_confidence=0.65,
                reasoning_template="Inconsistent list styles can confuse readers",
                implementation_steps=[
                    "Choose either numbered or bullet lists",
                    "Apply the same style consistently",
                    "Use nested lists for sub-items",
                ],
            ),
            PreferencePattern(
                category="verbose_writing",
                domain=PreferenceDomain.STYLE,
                patterns=[
                    "verbose writing", "wordy content", "unnecessary words",
                    "overly complex sentences", "redundant phrasing",
                    "flowery language", "excessive adjectives",
                    "run on sentences", "convoluted expression",
                ],
                regex_patterns=[
                    r"\b(in order to|due to the fact that|in the event of|at this point in time|"
                    r"for the purpose of|with the exception of|in the absence of|"
                    r"on a regular basis|in a timely manner|the majority of)\b",
                ],
                suggestion_template="Consider making the writing more concise",
                suggested_replacement="Use simpler, more direct language",
                base_confidence=0.70,
                auto_applicable_threshold=0.85,
                reasoning_template="The content contains wordy phrases that can be simplified",
                implementation_steps=[
                    "Identify wordy phrases",
                    "Replace with simpler alternatives",
                    "Review sentence length and structure",
                ],
            ),
            PreferencePattern(
                category="jargon_overuse",
                domain=PreferenceDomain.STYLE,
                patterns=[
                    "excessive jargon", "too many acronyms", "technical overkill",
                    "unnecessary terminology", "specialized language",
                    "insider terminology", "acronym overload",
                ],
                regex_patterns=[
                    r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){2,}\b",
                ],
                suggestion_template="Consider simplifying technical jargon for wider audience",
                suggested_replacement="Explain acronyms and technical terms on first use",
                base_confidence=0.60,
                reasoning_template="The content may be difficult to understand for non-specialist readers",
                implementation_steps=[
                    "Identify unexplained acronyms",
                    "Define technical terms on first use",
                    "Consider your target audience's expertise level",
                ],
            ),
            PreferencePattern(
                category="inconsistent_terminology",
                domain=PreferenceDomain.TERMINOLOGY,
                patterns=[
                    "inconsistent term", "mixed terminology",
                    "same concept different name", "term inconsistency",
                    "naming inconsistency", "multiple terms same thing",
                ],
                regex_patterns=[
                    r"\b(customer|client|user|member)\b.*\b(customer|client|user|member)\b",
                ],
                suggestion_template="Use consistent terminology throughout",
                suggested_replacement="Pick one term for each concept and use it consistently",
                base_confidence=0.65,
                reasoning_template="Inconsistent terminology can confuse readers",
                implementation_steps=[
                    "Identify all terms used for each concept",
                    "Select the preferred term",
                    "Replace all instances consistently",
                ],
            ),
            PreferencePattern(
                category="missing_summary",
                domain=PreferenceDomain.STRUCTURE,
                patterns=[
                    "no summary", "missing executive summary",
                    "no tl dr", "no abstract", "missing overview",
                    "no key points", "no conclusion",
                ],
                regex_patterns=[
                    r"\b\d{4,}\b.*$",
                ],
                suggestion_template="Add a summary or key points section",
                suggested_replacement="Include a brief overview at the start and conclusion at the end",
                base_confidence=0.60,
                reasoning_template="Longer content benefits from summary sections",
                implementation_steps=[
                    "Extract 3-5 key points",
                    "Write a brief summary paragraph",
                    "Place the summary at the beginning",
                ],
            ),
            PreferencePattern(
                category="too_long",
                domain=PreferenceDomain.LENGTH,
                patterns=[
                    "too long", "excessive length", "needs trimming",
                    "overly long content", "too wordy", "content too verbose",
                ],
                regex_patterns=[
                    r"\b\w{30,}\b",
                ],
                suggestion_template="Consider shortening this content",
                suggested_replacement="Aim for concise, scannable content",
                base_confidence=0.55,
                reasoning_template="Content may be too long for the intended audience",
                implementation_steps=[
                    "Remove redundant information",
                    "Break into smaller sections",
                    "Consider a shorter format",
                ],
            ),
            PreferencePattern(
                category="missing_alt_text",
                domain=PreferenceDomain.ACCESSIBILITY,
                patterns=[
                    "no alt text", "missing image description",
                    "image without alt", "missing alt attribute",
                    "no image caption", "inaccessible image",
                ],
                regex_patterns=[
                    r"!\[.*?\]\(.*?\)",
                ],
                suggestion_template="Add descriptive alt text for images",
                suggested_replacement="Include meaningful descriptions for all images",
                base_confidence=0.85,
                auto_applicable_threshold=0.90,
                reasoning_template="Images without descriptions are inaccessible to screen readers",
                implementation_steps=[
                    "Describe the image content concisely",
                    "Include relevant context",
                    "Keep alt text under 125 characters",
                ],
            ),
            PreferencePattern(
                category="non_inclusive_language",
                domain=PreferenceDomain.INCLUSIVITY,
                patterns=[
                    "non inclusive language", "exclusive terminology",
                    "gendered language", "ableist language",
                    "culturally insensitive", "exclusive phrasing",
                ],
                regex_patterns=[
                    r"\b(mankind|manpower|chairman|freshman|salesman|"
                    r"fireman|policeman|stewardess|waitress|actress)\b",
                ],
                suggestion_template="Consider using more inclusive language",
                suggested_replacement="Use gender-neutral alternatives",
                base_confidence=0.80,
                auto_applicable_threshold=0.85,
                reasoning_template="Some terms may be perceived as exclusionary",
                implementation_steps=[
                    "Identify gendered or exclusionary terms",
                    "Replace with inclusive alternatives",
                    "Review for cultural sensitivity",
                ],
            ),
            PreferencePattern(
                category="inconsistent_tense",
                domain=PreferenceDomain.CONSISTENCY,
                patterns=[
                    "tense shift", "inconsistent tense",
                    "mixed past present", "tense switching",
                    "verb tense inconsistency",
                ],
                regex_patterns=[
                    r"\b(\w+ed)\b.*\b(\w+s)\b.*\b(\w+ed)\b",
                ],
                suggestion_template="Maintain consistent verb tense throughout",
                suggested_replacement="Choose one tense and stick with it",
                base_confidence=0.60,
                reasoning_template="Shifting tenses can confuse readers about timing",
                implementation_steps=[
                    "Identify the primary tense used",
                    "Apply consistently throughout",
                    "Review for unintended shifts",
                ],
            ),
            PreferencePattern(
                category="missing_code_blocks",
                domain=PreferenceDomain.FORMATTING,
                patterns=[
                    "code not formatted", "inline code missing",
                    "code block needed", "unformatted code snippet",
                    "code without syntax highlighting",
                ],
                regex_patterns=[
                    r"(?:```|\s{4})?[\w\W]*?(?:function|class|def|import|const|let|var)\s+\w+",
                ],
                suggestion_template="Format code snippets with proper code blocks",
                suggested_replacement="Use triple backticks for multi-line code and single backticks for inline",
                base_confidence=0.75,
                auto_applicable_threshold=0.85,
                reasoning_template="Code without formatting is harder to read",
                implementation_steps=[
                    "Wrap multi-line code in triple backticks",
                    "Use single backticks for inline code",
                    "Specify the language for syntax highlighting",
                ],
            ),
            PreferencePattern(
                category="missing_tables",
                domain=PreferenceDomain.FORMATTING,
                patterns=[
                    "tabular data not formatted", "data needs table",
                    "unstructured data", "list of values needs table",
                    "comparison data unformatted",
                ],
                regex_patterns=[
                    r"(?:\|.*\|.*\n?)*",
                ],
                suggestion_template="Format structured data as a table",
                suggested_replacement="Use markdown tables for data comparison",
                base_confidence=0.60,
                reasoning_template="Structured data is easier to read in table format",
                implementation_steps=[
                    "Identify the data columns",
                    "Create header row with column names",
                    "Format each row consistently",
                ],
            ),
            PreferencePattern(
                category="overly_formal",
                domain=PreferenceDomain.TONE,
                patterns=[
                    "overly formal", "too formal", "stiff language",
                    "excessively formal tone", "stilted writing",
                    "too rigid", "overly academic",
                ],
                regex_patterns=[
                    r"\b(heretofore|hereinafter|aforementioned|thereof|thereto|"
                    r"wherein|whereby|whereupon|thusly|henceforth)\b",
                ],
                suggestion_template="Consider a less formal tone for better engagement",
                suggested_replacement="Use natural, conversational language where appropriate",
                base_confidence=0.65,
                reasoning_template="Overly formal language can feel distant and harder to connect with",
                implementation_steps=[
                    "Replace formal adverbs with simpler alternatives",
                    "Use contractions where appropriate",
                    "Write as you would speak in a professional setting",
                ],
            ),
            PreferencePattern(
                category="missing_call_to_action",
                domain=PreferenceDomain.STRUCTURE,
                patterns=[
                    "no call to action", "missing cta",
                    "no next steps", "no action items",
                    "missing conclusion action",
                ],
                regex_patterns=[],
                suggestion_template="Add a clear call to action or next steps",
                suggested_replacement="Tell readers what you want them to do next",
                base_confidence=0.55,
                reasoning_template="Content without a clear action item may leave readers unsure",
                implementation_steps=[
                    "Define the desired outcome",
                    "Write a clear action statement",
                    "Make it easy for readers to follow through",
                ],
            ),
            PreferencePattern(
                category="repetitive_language",
                domain=PreferenceDomain.STYLE,
                patterns=[
                    "repetitive words", "repeated phrases",
                    "overused terms", "language repetition",
                    "same word multiple times",
                ],
                regex_patterns=[
                    r"\b(\w+)\s+\1\b",
                ],
                suggestion_template="Vary your language to avoid repetition",
                suggested_replacement="Use synonyms or restructure sentences to reduce repetition",
                base_confidence=0.65,
                reasoning_template="Repeated words or phrases can make content feel monotonous",
                implementation_steps=[
                    "Identify repeated words within close proximity",
                    "Use synonyms or pronouns",
                    "Restructure sentences to eliminate redundancy",
                ],
            ),
            PreferencePattern(
                category="contradictory_statements",
                domain=PreferenceDomain.CONSISTENCY,
                patterns=[
                    "contradictory statement", "logical inconsistency",
                    "self contradictory", "conflicting information",
                    "mixed message",
                ],
                regex_patterns=[],
                suggestion_template="Resolve contradictory statements for consistency",
                suggested_replacement="Ensure all statements are logically consistent",
                base_confidence=0.50,
                reasoning_template="Contradictory information undermines credibility",
                implementation_steps=[
                    "Identify the conflicting statements",
                    "Determine which is correct",
                    "Update or remove the incorrect statement",
                ],
            ),
            PreferencePattern(
                category="missing_links",
                domain=PreferenceDomain.STRUCTURE,
                patterns=[
                    "no references", "missing citations",
                    "no source links", "unsubstantiated claims",
                    "missing attribution",
                ],
                regex_patterns=[],
                suggestion_template="Add references or links to support claims",
                suggested_replacement="Cite sources for factual claims",
                base_confidence=0.55,
                reasoning_template="Supporting claims with sources increases credibility",
                implementation_steps=[
                    "Identify factual claims that need support",
                    "Find reliable sources",
                    "Add inline citations or reference links",
                ],
            ),
            PreferencePattern(
                category="emotional_language",
                domain=PreferenceDomain.TONE,
                patterns=[
                    "emotional language", "overly dramatic",
                    "hyperbolic language", "sensational wording",
                    "exaggerated claims",
                ],
                regex_patterns=[
                    r"\b(amazing|incredible|unbelievable|extraordinary|"
                    r"mind.?blowing|life.?changing|revolutionary|game.?changer)\b",
                ],
                suggestion_template="Use more measured, factual language",
                suggested_replacement="Replace hyperbolic terms with specific, factual descriptions",
                base_confidence=0.60,
                reasoning_template="Emotional language can undermine objectivity",
                implementation_steps=[
                    "Identify hyperbolic or emotional terms",
                    "Replace with specific, factual descriptions",
                    "Maintain a balanced tone",
                ],
            ),
            PreferencePattern(
                category="sentence_complexity",
                domain=PreferenceDomain.STYLE,
                patterns=[
                    "complex sentences", "hard to read",
                    "sentence too long", "convoluted structure",
                    "nested clauses",
                ],
                regex_patterns=[
                    r"\b\w+\b.*\b\w+\b.*\b\w+\b.*\b\w+\b.*\b\w+\b.*\b\w+\b.*,.*,.*,",
                ],
                suggestion_template="Break down complex sentences for readability",
                suggested_replacement="Use shorter, simpler sentence structures",
                base_confidence=0.65,
                auto_applicable_threshold=0.80,
                reasoning_template="Long, complex sentences reduce readability",
                implementation_steps=[
                    "Identify sentences with multiple clauses",
                    "Split into shorter sentences",
                    "Ensure each sentence has one main idea",
                ],
            ),
            PreferencePattern(
                category="reading_level",
                domain=PreferenceDomain.ACCESSIBILITY,
                patterns=[
                    "too complex for audience", "reading level too high",
                    "not accessible to beginners",
                ],
                regex_patterns=[],
                suggestion_template="Adjust content complexity for the target audience",
                suggested_replacement="Simplify language and concepts as needed",
                base_confidence=0.50,
                reasoning_template="Content may be too complex for the intended readership",
                implementation_steps=[
                    "Identify the target audience's reading level",
                    "Simplify technical concepts",
                    "Define specialized terms",
                ],
            ),
            PreferencePattern(
                category="gender_neutral",
                domain=PreferenceDomain.INCLUSIVITY,
                patterns=[
                    "he him exclusive", "she her exclusive",
                    "binary language", "gender assumption",
                ],
                regex_patterns=[
                    r"\b(he|him|his|she|her|hers)\b(?:\s+(?:said|wrote|mentioned|stated|believes|thinks))",
                ],
                suggestion_template="Use gender-neutral pronouns throughout",
                suggested_replacement="Use 'they/them' or restructure to avoid pronouns",
                base_confidence=0.75,
                auto_applicable_threshold=0.85,
                reasoning_template="Using gender-neutral language is more inclusive",
                implementation_steps=[
                    "Identify gendered pronouns",
                    "Replace with 'they/them' or restructure",
                    "Use 'their' as singular possessive",
                ],
            ),
        ]
        custom_patterns = self.config.get("custom_patterns", [])
        for pat_data in custom_patterns:
            self._patterns.append(PreferencePattern(
                category=pat_data.get("category", "custom"),
                domain=PreferenceDomain(pat_data.get("domain", "style")),
                patterns=pat_data.get("patterns", []),
                regex_patterns=pat_data.get("regex_patterns", []),
                suggestion_template=pat_data.get("suggestion_template", ""),
                suggested_replacement=pat_data.get("suggested_replacement", ""),
                base_confidence=pat_data.get("base_confidence", 0.70),
                auto_applicable_threshold=pat_data.get("auto_applicable_threshold", 0.85),
                requires_context=pat_data.get("requires_context", False),
                contextual_conditions=pat_data.get("contextual_conditions"),
                reasoning_template=pat_data.get("reasoning_template", ""),
                implementation_steps=pat_data.get("implementation_steps"),
            ))
        disabled = set(self.config.get("disabled_categories", []))
        self._patterns = [p for p in self._patterns if p.category not in disabled]

    def _compile_regexes(self) -> None:
        for pattern in self._patterns:
            for regex in pattern.regex_patterns:
                try:
                    self._compiled_regexes[f"{pattern.category}:{regex}"] = re.compile(
                        regex, re.IGNORECASE
                    )
                except re.error as e:
                    logger.warning(
                        "Failed to compile regex for %s: %s", pattern.category, e
                    )

    def _get_or_create_profile(self, user_id: str) -> UserPreferenceProfile:
        if user_id not in self._user_profiles:
            self._user_profiles[user_id] = UserPreferenceProfile(user_id)
        return self._user_profiles[user_id]

    def _check_contextual_conditions(
        self, pattern: PreferencePattern, context: Optional[RuleContext]
    ) -> bool:
        if not pattern.requires_context:
            return True
        if not context:
            return not pattern.requires_context
        effective = context.get_effective_context()
        for key, expected_value in pattern.contextual_conditions.items():
            actual = effective.get(key)
            if isinstance(expected_value, list):
                if actual not in expected_value:
                    return False
            elif actual != expected_value:
                return False
        return True

    def _adjust_confidence(
        self, base_confidence: float, category: str, profile: Optional[UserPreferenceProfile]
    ) -> float:
        confidence = base_confidence
        if profile:
            acceptance_rate = profile.get_acceptance_rate(category)
            if acceptance_rate > 0:
                confidence += (acceptance_rate - 0.5) * profile.learning_rate
            if category in profile.dismissed_categories:
                confidence *= 0.5
            if category in profile.auto_apply_domains:
                confidence = min(confidence + 0.1, 1.0)
        return min(max(confidence, 0.0), 1.0)

    def _scan_content(
        self, content: str, content_lower: str, profile: Optional[UserPreferenceProfile]
    ) -> List[PreferenceSuggestion]:
        suggestions: List[PreferenceSuggestion] = []
        seen_categories: Set[str] = set()
        for pattern in self._patterns:
            if pattern.category in seen_categories:
                continue
            if profile and pattern.category in profile.dismissed_categories:
                continue
            matched = False
            matched_text = ""
            for kw in pattern.patterns:
                idx = content_lower.find(kw)
                if idx != -1:
                    matched = True
                    matched_text = content[idx:idx + len(kw)]
                    break
            if not matched:
                for regex_str in pattern.regex_patterns:
                    key = f"{pattern.category}:{regex_str}"
                    compiled = self._compiled_regexes.get(key)
                    if compiled:
                        m = compiled.search(content)
                        if m:
                            matched = True
                            matched_text = m.group()
                            break
            if matched:
                confidence = self._adjust_confidence(
                    pattern.base_confidence, pattern.category, profile
                )
                auto_applicable = confidence >= pattern.auto_applicable_threshold
                if profile:
                    auto_applicable = auto_applicable or profile.should_auto_apply(
                        pattern.category
                    )
                suggestion_obj = PreferenceSuggestion(
                    category=pattern.category,
                    domain=pattern.domain,
                    suggestion_text=pattern.suggestion_template,
                    original_text=matched_text,
                    suggested_replacement=pattern.suggested_replacement,
                    confidence=confidence,
                    auto_applicable=auto_applicable,
                    reasoning=pattern.reasoning_template.format(
                        category=pattern.category,
                        text=matched_text,
                    ) if pattern.reasoning_template else "",
                    implementation_steps=list(pattern.implementation_steps),
                )
                suggestions.append(suggestion_obj)
                seen_categories.add(pattern.category)
        return suggestions

    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = datetime.utcnow()
        content = request.content
        content_lower = content.lower()
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=0.8,
            request_id=f"pref_{self.stats.evaluation_count}",
            content_hash=str(hash(content))[:16],
        )
        user_id = None
        context = request.context
        if context and context.user_id:
            user_id = context.user_id
        profile = self._get_or_create_profile(user_id) if user_id else None
        suggestions = self._scan_content(content, content_lower, profile)
        for suggestion_obj in suggestions:
            source_rule = f"preference_{suggestion_obj.category}"
            suggestion = suggestion_obj.to_suggestion(source_rule=source_rule)
            result.suggestions.append(suggestion)
            if suggestion_obj.auto_applicable:
                suggestion.auto_applicable = True
                suggestion.user_approval_required = False
                self.stats.record_suggestion(
                    category=suggestion_obj.category,
                    domain=suggestion_obj.domain,
                    auto_applied=True,
                    processing_ms=0,
                )
                logger.debug(
                    "Auto-applied preference: category='%s' confidence=%s",
                    suggestion_obj.category, suggestion_obj.confidence,
                )
            else:
                self.stats.record_suggestion(
                    category=suggestion_obj.category,
                    domain=suggestion_obj.domain,
                    auto_applied=False,
                    processing_ms=0,
                )
            logger.info(
                "Preference suggestion: category='%s' domain=%s confidence=%s auto=%s",
                suggestion_obj.category,
                suggestion_obj.domain.value,
                suggestion_obj.confidence,
                suggestion_obj.auto_applicable,
            )
        processing_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.processing_time_ms = processing_ms
        result.total_rules_evaluated = len(self._patterns)
        logger.debug(
            "Preference evaluation completed: %d suggestions in %dms",
            len(result.suggestions), processing_ms,
        )
        return result

    def record_feedback(
        self,
        category: str,
        user_id: str,
        accepted: bool,
        feedback_score: Optional[float] = None,
    ) -> None:
        profile = self._get_or_create_profile(user_id)
        score = feedback_score if feedback_score is not None else (1.0 if accepted else 0.0)
        profile.record_feedback(category, accepted, score)
        self.stats.record_feedback(accepted, score)
        logger.info(
            "Preference feedback: user='%s' category='%s' accepted=%s score=%s",
            user_id, category, accepted, score,
        )

    def dismiss_category(self, category: str, user_id: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.dismissed_categories.add(category)
        logger.info(
            "Category dismissed: user='%s' category='%s'", user_id, category
        )

    def enable_auto_apply(self, domain: PreferenceDomain, user_id: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.auto_apply_domains.add(domain.value)
        logger.info(
            "Auto-apply enabled: user='%s' domain='%s'", user_id, domain.value
        )

    def disable_auto_apply(self, domain: PreferenceDomain, user_id: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.auto_apply_domains.discard(domain.value)
        logger.info(
            "Auto-apply disabled: user='%s' domain='%s'", user_id, domain.value
        )

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        profile = self._user_profiles.get(user_id)
        return profile.to_dict() if profile else None

    def get_all_user_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {
            uid: profile.to_dict()
            for uid, profile in self._user_profiles.items()
        }

    def get_patterns(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._patterns]

    def get_active_categories(self) -> List[str]:
        return [p.category for p in self._patterns]

    def get_patterns_by_domain(self, domain: PreferenceDomain) -> List[Dict[str, Any]]:
        return [
            p.to_dict() for p in self._patterns if p.domain == domain
        ]

    def get_statistics(self) -> Dict[str, Any]:
        return self.stats.get_summary()

    def add_custom_pattern(self, pattern_data: Dict[str, Any]) -> None:
        pat = PreferencePattern(
            category=pattern_data["category"],
            domain=PreferenceDomain(pattern_data.get("domain", "style")),
            patterns=pattern_data.get("patterns", []),
            regex_patterns=pattern_data.get("regex_patterns", []),
            suggestion_template=pattern_data.get("suggestion_template", ""),
            suggested_replacement=pattern_data.get("suggested_replacement", ""),
            base_confidence=pattern_data.get("base_confidence", 0.70),
            auto_applicable_threshold=pattern_data.get("auto_applicable_threshold", 0.85),
            requires_context=pattern_data.get("requires_context", False),
            contextual_conditions=pattern_data.get("contextual_conditions"),
            reasoning_template=pattern_data.get("reasoning_template", ""),
            implementation_steps=pattern_data.get("implementation_steps"),
        )
        self._patterns.append(pat)
        for regex in pat.regex_patterns:
            try:
                self._compiled_regexes[f"{pat.category}:{regex}"] = re.compile(
                    regex, re.IGNORECASE
                )
            except re.error as e:
                logger.warning(
                    "Failed to compile regex for %s: %s", pat.category, e
                )
        logger.info("Added custom preference pattern: %s", pat.category)

    def remove_pattern(self, category: str) -> bool:
        before = len(self._patterns)
        self._patterns = [p for p in self._patterns if p.category != category]
        keys_to_remove = [k for k in self._compiled_regexes if k.startswith(f"{category}:")]
        for k in keys_to_remove:
            del self._compiled_regexes[k]
        removed = len(self._patterns) < before
        if removed:
            logger.info("Removed preference pattern: %s", category)
        return removed

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config.update(config)
        self._patterns.clear()
        self._compiled_regexes.clear()
        self._initialize_patterns()
        self._compile_regexes()
        logger.info("PreferenceRuleEngine configuration updated")

    def reset_statistics(self) -> None:
        self.stats = PreferenceStats()
        logger.info("PreferenceRuleEngine statistics reset")

    def clear_user_profiles(self) -> None:
        self._user_profiles.clear()
        logger.info("User preference profiles cleared")

    def get_suggestion_rate(self) -> float:
        if self.stats.evaluation_count == 0:
            return 0.0
        return round(
            self.stats.suggestion_count / self.stats.evaluation_count, 4
        )

    def get_auto_apply_rate(self) -> float:
        if self.stats.suggestion_count == 0:
            return 0.0
        return round(
            self.stats.auto_applied_count / self.stats.suggestion_count, 4
        )

    def get_approval_rate(self) -> float:
        total_user_feedback = self.stats.user_approved_count + self.stats.user_rejected_count
        if total_user_feedback == 0:
            return 0.0
        return round(
            self.stats.user_approved_count / total_user_feedback, 4
        )

    def get_category_statistics(self) -> Dict[str, Dict[str, int]]:
        result = {}
        all_categories = set(self.stats.category_counts.keys())
        all_categories.update(p.category for p in self._patterns)
        for cat_name in sorted(all_categories):
            result[cat_name] = {
                "total_suggestions": self.stats.category_counts.get(cat_name, 0),
                "is_active": any(p.category == cat_name for p in self._patterns),
            }
        return result

    def get_domain_statistics(self) -> Dict[str, int]:
        return dict(self.stats.domain_counts)
