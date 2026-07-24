"""Style validation for generated outputs."""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple, Pattern

logger = logging.getLogger(__name__)


@dataclass
class StyleGuide:
    """Configuration for a style guide."""
    name: str
    preferred_spelling: str = "american"
    use_oxford_comma: bool = True
    max_sentence_length: int = 35
    max_passive_voice_ratio: float = 0.2
    allow_contractions: bool = False
    allow_first_person: bool = False
    allow_second_person: bool = False
    preferred_quote_style: str = "double"
    citation_style: str = "apa"
    heading_case: str = "title"
    max_paragraph_length: int = 150


@dataclass
class StyleIssue:
    """Represents a style issue found in content."""
    issue_type: str
    description: str
    severity: str
    location: Optional[str] = None
    suggestion: Optional[str] = None
    original_text: Optional[str] = None
    suggested_text: Optional[str] = None


@dataclass
class StyleStatistics:
    """Statistics about content style."""
    total_sentences: int = 0
    total_words: int = 0
    avg_sentence_length: float = 0.0
    long_sentences: int = 0
    passive_voice_count: int = 0
    passive_voice_ratio: float = 0.0
    contraction_count: int = 0
    first_person_count: int = 0
    second_person_count: int = 0
    jargon_count: int = 0
    spelling_inconsistencies: List[str] = field(default_factory=list)
    punctuation_issues: int = 0
    sentence_complexity: Dict[str, int] = field(default_factory=dict)


STYLE_GUIDES: Dict[str, StyleGuide] = {
    "ap": StyleGuide(
        name="AP",
        preferred_spelling="american",
        use_oxford_comma=False,
        max_sentence_length=30,
        max_passive_voice_ratio=0.15,
        allow_contractions=True,
        allow_first_person=False,
        allow_second_person=False,
        preferred_quote_style="double",
        citation_style="apa",
        heading_case="title",
        max_paragraph_length=100,
    ),
    "chicago": StyleGuide(
        name="Chicago",
        preferred_spelling="american",
        use_oxford_comma=True,
        max_sentence_length=40,
        max_passive_voice_ratio=0.25,
        allow_contractions=False,
        allow_first_person=True,
        allow_second_person=False,
        preferred_quote_style="double",
        citation_style="chicago",
        heading_case="title",
        max_paragraph_length=200,
    ),
    "apa_style": StyleGuide(
        name="APA Style",
        preferred_spelling="american",
        use_oxford_comma=True,
        max_sentence_length=35,
        max_passive_voice_ratio=0.2,
        allow_contractions=False,
        allow_first_person=True,
        allow_second_person=False,
        preferred_quote_style="double",
        citation_style="apa",
        heading_case="title",
        max_paragraph_length=150,
    ),
    "mla_style": StyleGuide(
        name="MLA Style",
        preferred_spelling="american",
        use_oxford_comma=True,
        max_sentence_length=35,
        max_passive_voice_ratio=0.2,
        allow_contractions=False,
        allow_first_person=True,
        allow_second_person=False,
        preferred_quote_style="double",
        citation_style="mla",
        heading_case="title",
        max_paragraph_length=150,
    ),
    "custom": StyleGuide(
        name="Custom",
        preferred_spelling="american",
        use_oxford_comma=True,
        max_sentence_length=35,
        max_passive_voice_ratio=0.2,
        allow_contractions=False,
        allow_first_person=False,
        allow_second_person=False,
        preferred_quote_style="double",
        citation_style="apa",
        heading_case="title",
        max_paragraph_length=150,
    ),
}

PASSIVE_PATTERN = re.compile(
    r"\b(am|is|are|was|were|be|been|being)\s+(\w+ed|"
    r"written|spoken|built|made|known|found|shown|seen|given|taken|"
    r"kept|held|set|put|left|brought|bought|taught|thought|sold|told)\b",
    re.IGNORECASE,
)

CONTRACTION_PATTERN = re.compile(
    r"\b(can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
    r"hasn't|haven't|hadn't|it's|that's|there's|here's|what's|who's|"
    r"where's|why's|how's|let's|i'm|we're|they're|you're|he's|she's|"
    r"i've|we've|they've|you've|i'd|we'd|they'd|you'd|he'd|she'd|"
    r"i'll|we'll|they'll|you'll|he'll|she'll|ain't|gonna|wanna|gotta)\b",
    re.IGNORECASE,
)

FIRST_PERSON_PATTERN = re.compile(
    r"\b(I|me|my|mine|myself|we|us|our|ours|ourselves)\b", re.IGNORECASE
)

SECOND_PERSON_PATTERN = re.compile(
    r"\b(you|your|yours|yourself|yourselves)\b", re.IGNORECASE
)

SPELLING_VARIANTS: Dict[str, List[str]] = {
    "american": ["color", "flavor", "honor", "labor", "neighbor", "organize", "realize", "recognize", "center", "meter", "theater", "defense", "license", "offense", "pretense", "analyze", "catalog", "dialog", "traveled", "traveling", "jewelry", "woolen"],
    "british": ["colour", "flavour", "honour", "labour", "neighbour", "organise", "realise", "recognise", "centre", "metre", "theatre", "defence", "licence", "offence", "pretence", "analyse", "catalogue", "dialogue", "travelled", "travelling", "jewellery", "woollen"],
}

JARGON_TERMS: Dict[str, List[str]] = {
    "business": ["synergy", "leverage", "paradigm", "scalable", "actionable", "bandwidth", "circle back", "drill down", "touch base", "thought leadership", "deep dive", "pain point", "value add", "low hanging fruit", "move the needle"],
    "academic": ["thus", "hence", "notably", "consequently", "heretofore", "discourse", "paradigm", "epistemological", "ontological", "hermeneutic", "heuristic", "pedagogical"],
    "technical": ["leverage", "utilize", "implement", "robust", "scalable", "optimize", "streamline", "facilitate"],
}

PUNCTUATION_ISSUES: List[Tuple[Pattern, str, str]] = [
    (re.compile(r"\s+\.\s*$"), "space_before_period", "Remove space before period"),
    (re.compile(r"\s+,\s*[a-z]"), "space_before_comma", "Remove space before comma"),
    (re.compile(r"\s+;\s*"), "space_before_semicolon", "Remove space before semicolon"),
    (re.compile(r"\s+:\s*[a-z]"), "space_before_colon", "Remove space before colon"),
    (re.compile(r'"[^"]+"'), "straight_quotes", "Use curly quotes instead of straight quotes"),
    (re.compile(r"'[^']+'"), "straight_apostrophes", "Use curly apostrophes"),
    (re.compile(r"\.[A-Z][a-z]{2,}\."), "missing_abbreviation_space", "Check spacing around abbreviations"),
]

COMPLEXITY_PATTERNS: List[Tuple[str, Pattern, int]] = [
    ("very_simple", re.compile(r"^[A-Z][a-z]*(?:\s+[a-z]+){1,4}\.$"), 1),
    ("simple", re.compile(r"^[A-Z][a-z]*(?:\s+[a-z]+){1,8}\.$"), 2),
    ("moderate", re.compile(r"^[A-Z][a-z]*(?:\s+[a-z]+){5,15}\.$"), 3),
]

SPLIT_INFINITIVE_PATTERN = re.compile(r"\bto\s+\w+\s+\w+[ed|ing|ly]\b", re.IGNORECASE)


class StyleValidator:
    """Validates content style against configurable style guides."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        style_guide_name = self.config.get("style_guide", "apa_style")
        self.style_guide = STYLE_GUIDES.get(style_guide_name, STYLE_GUIDES["custom"])
        self.custom_style_guide: Optional[StyleGuide] = None
        if "custom_style" in self.config:
            cs = self.config["custom_style"]
            self.custom_style_guide = StyleGuide(
                name=cs.get("name", "Custom"),
                preferred_spelling=cs.get("preferred_spelling", self.style_guide.preferred_spelling),
                use_oxford_comma=cs.get("use_oxford_comma", self.style_guide.use_oxford_comma),
                max_sentence_length=cs.get("max_sentence_length", self.style_guide.max_sentence_length),
                max_passive_voice_ratio=cs.get("max_passive_voice_ratio", self.style_guide.max_passive_voice_ratio),
                allow_contractions=cs.get("allow_contractions", self.style_guide.allow_contractions),
                allow_first_person=cs.get("allow_first_person", self.style_guide.allow_first_person),
                allow_second_person=cs.get("allow_second_person", self.style_guide.allow_second_person),
                preferred_quote_style=cs.get("preferred_quote_style", self.style_guide.preferred_quote_style),
                citation_style=cs.get("citation_style", self.style_guide.citation_style),
                heading_case=cs.get("heading_case", self.style_guide.heading_case),
                max_paragraph_length=cs.get("max_paragraph_length", self.style_guide.max_paragraph_length),
            )
        self.jargon_allowed: Set[str] = set(
            self.config.get("jargon_allowed", [])
        )
        self.jargon_blocked: Set[str] = set(
            self.config.get("jargon_blocked", [])
        )
        self.allowed_terminology: Dict[str, str] = self.config.get("allowed_terminology", {})
        self.logger.info(
            "StyleValidator initialized with guide=%s", self.style_guide.name,
        )

    def validate(self, content: str) -> Dict[str, Any]:
        """Validate content style and return assessment."""
        self.logger.debug("Validating style for content length: %d", len(content))
        sentences = re.split(r"(?<=[.!?])\s+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = content.split()
        issues: List[StyleIssue] = []
        passive_issues = self._check_passive_voice(sentences)
        issues.extend(passive_issues)
        contraction_issues = self._check_contractions(content)
        issues.extend(contraction_issues)
        person_issues = self._check_person_usage(content)
        issues.extend(person_issues)
        sentence_issues = self._check_sentence_length(sentences)
        issues.extend(sentence_issues)
        spelling_issues = self._check_spelling(content)
        issues.extend(spelling_issues)
        punctuation_issues = self._check_punctuation(content)
        issues.extend(punctuation_issues)
        jargon_issues = self._check_jargon(content)
        issues.extend(jargon_issues)
        consistency_issues = self._check_consistency(content)
        issues.extend(consistency_issues)
        paragraph_issues = self._check_paragraph_structure(content)
        issues.extend(paragraph_issues)
        grammar_issues = self._check_grammar(content)
        issues.extend(grammar_issues)
        stats = self._compute_statistics(content, sentences, words, issues)
        error_count = sum(1 for i in issues if i.severity == "error")
        result = {
            "valid": error_count == 0,
            "style_guide": self.style_guide.name,
            "issues": [
                {
                    "type": i.issue_type,
                    "description": i.description,
                    "severity": i.severity,
                    "original_text": i.original_text,
                    "suggested_text": i.suggested_text,
                    "suggestion": i.suggestion,
                }
                for i in issues
            ],
            "statistics": {
                "total_sentences": stats.total_sentences,
                "total_words": stats.total_words,
                "avg_sentence_length": round(stats.avg_sentence_length, 2),
                "long_sentences": stats.long_sentences,
                "long_sentence_ratio": round(stats.long_sentences / max(1, stats.total_sentences), 4),
                "passive_voice_count": stats.passive_voice_count,
                "passive_voice_ratio": round(stats.passive_voice_ratio, 4),
                "contraction_count": stats.contraction_count,
                "first_person_count": stats.first_person_count,
                "second_person_count": stats.second_person_count,
                "jargon_count": stats.jargon_count,
                "spelling_inconsistencies": stats.spelling_inconsistencies,
                "punctuation_issues": stats.punctuation_issues,
                "sentence_complexity": stats.sentence_complexity,
            },
            "recommendations": self._generate_recommendations(issues, stats),
            "style_guide_config": {
                "preferred_spelling": self.style_guide.preferred_spelling,
                "use_oxford_comma": self.style_guide.use_oxford_comma,
                "max_sentence_length": self.style_guide.max_sentence_length,
                "max_passive_voice_ratio": self.style_guide.max_passive_voice_ratio,
                "allow_contractions": self.style_guide.allow_contractions,
                "allow_first_person": self.style_guide.allow_first_person,
                "allow_second_person": self.style_guide.allow_second_person,
            },
        }
        self.logger.info(
            "Style validation completed: valid=%s, issues=%d",
            result["valid"], len(issues),
        )
        return result

    def _check_passive_voice(self, sentences: List[str]) -> List[StyleIssue]:
        """Detect passive voice usage."""
        issues: List[StyleIssue] = []
        for sentence in sentences:
            matches = PASSIVE_PATTERN.findall(sentence)
            for match in matches:
                full_phrase = f"{match[0]} {match[1]}"
                issues.append(StyleIssue(
                    issue_type="passive_voice",
                    description=f"Passive voice detected: '{full_phrase}'",
                    severity="info" if self.style_guide.max_passive_voice_ratio > 0.2 else "warning",
                    location=sentence[:50],
                    original_text=sentence,
                    suggestion="Consider rewriting in active voice.",
                ))
        return issues

    def _check_contractions(self, content: str) -> List[StyleIssue]:
        """Check for contractions against style guide."""
        if self.style_guide.allow_contractions:
            return []
        issues: List[StyleIssue] = []
        for match in CONTRACTION_PATTERN.finditer(content):
            contraction = match.group()
            expansion = self._expand_contraction(contraction)
            issues.append(StyleIssue(
                issue_type="contraction",
                description=f"Contraction '{contraction}' used (prefer '{expansion}')",
                severity="warning",
                location=contraction,
                original_text=contraction,
                suggested_text=expansion,
                suggestion=f"Replace '{contraction}' with '{expansion}'.",
            ))
        return issues

    def _expand_contraction(self, contraction: str) -> str:
        """Expand a contraction to its full form."""
        expansion_map = {
            "can't": "cannot",
            "won't": "will not",
            "don't": "do not",
            "doesn't": "does not",
            "didn't": "did not",
            "isn't": "is not",
            "aren't": "are not",
            "wasn't": "was not",
            "weren't": "were not",
            "hasn't": "has not",
            "haven't": "have not",
            "hadn't": "had not",
            "it's": "it is",
            "that's": "that is",
            "there's": "there is",
            "here's": "here is",
            "what's": "what is",
            "who's": "who is",
            "where's": "where is",
            "why's": "why is",
            "how's": "how is",
            "let's": "let us",
            "i'm": "I am",
            "we're": "we are",
            "they're": "they are",
            "you're": "you are",
            "he's": "he is",
            "she's": "she is",
            "i've": "I have",
            "we've": "we have",
            "they've": "they have",
            "you've": "you have",
            "i'd": "I would",
            "we'd": "we would",
            "they'd": "they would",
            "you'd": "you would",
            "he'd": "he would",
            "she'd": "she would",
            "i'll": "I will",
            "we'll": "we will",
            "they'll": "they will",
            "you'll": "you will",
            "he'll": "he will",
            "she'll": "she will",
        }
        return expansion_map.get(contraction.lower(), contraction)

    def _check_person_usage(self, content: str) -> List[StyleIssue]:
        """Check first and second person usage."""
        issues: List[StyleIssue] = []
        if not self.style_guide.allow_first_person:
            for match in FIRST_PERSON_PATTERN.finditer(content):
                word = match.group()
                if word.lower() == "i":
                    issues.append(StyleIssue(
                        issue_type="first_person",
                        description=f"First-person pronoun '{word}' used",
                        severity="warning",
                        location=word,
                        original_text=word,
                        suggestion="Use third-person perspective instead.",
                    ))
                elif word.lower() in ("we", "us", "our"):
                    issues.append(StyleIssue(
                        issue_type="first_person_plural",
                        description=f"First-person plural '{word}' used",
                        severity="warning" if not self.style_guide.allow_first_person else "info",
                        location=word,
                        original_text=word,
                        suggestion="Consider using 'one' or restructuring the sentence.",
                    ))
        if not self.style_guide.allow_second_person:
            for match in SECOND_PERSON_PATTERN.finditer(content):
                word = match.group()
                issues.append(StyleIssue(
                    issue_type="second_person",
                    description=f"Second-person pronoun '{word}' used",
                    severity="warning",
                    location=word,
                    original_text=word,
                    suggestion="Replace with third-person or impersonal construction.",
                ))
        return issues

    def _check_sentence_length(self, sentences: List[str]) -> List[StyleIssue]:
        """Check for sentence length issues."""
        issues: List[StyleIssue] = []
        for sentence in sentences:
            word_count = len(sentence.split())
            if word_count > self.style_guide.max_sentence_length:
                issues.append(StyleIssue(
                    issue_type="long_sentence",
                    description=f"Sentence too long ({word_count} words, max {self.style_guide.max_sentence_length})",
                    severity="warning",
                    location=sentence[:60],
                    original_text=sentence,
                    suggestion="Consider splitting this sentence into shorter ones for better readability.",
                ))
            elif word_count < 3 and len(sentence) > 5:
                context_words = sentence.split()
                if context_words and context_words[0][0].isupper():
                    issues.append(StyleIssue(
                        issue_type="short_sentence",
                        description="Very short sentence may be a fragment",
                        severity="info",
                        location=sentence[:60],
                        suggestion="Consider combining with adjacent sentence.",
                    ))
        return issues

    def _check_spelling(self, content: str) -> List[StyleIssue]:
        """Check spelling consistency (American vs British)."""
        issues: List[StyleIssue] = []
        preferred = self.style_guide.preferred_spelling
        if preferred not in SPELLING_VARIANTS:
            return issues
        preferred_list = SPELLING_VARIANTS[preferred]
        variant_name = "british" if preferred == "american" else "american"
        variant_list = SPELLING_VARIANTS.get(variant_name, [])
        variant_word_map = dict(zip(variant_list, preferred_list))
        words = content.lower().split()
        for variant_word, preferred_word in variant_word_map.items():
            for word in words:
                word_clean = word.strip(".,!?;:\"'()[]{}")
                if word_clean == variant_word:
                    issues.append(StyleIssue(
                        issue_type="spelling_variant",
                        description=f"'{variant_word}' is {variant_name} spelling (prefer '{preferred_word}')",
                        severity="info",
                        location=word,
                        original_text=word,
                        suggested_text=preferred_word,
                        suggestion=f"Use '{preferred_word}' instead of '{variant_word}'.",
                    ))
        return issues

    def _check_punctuation(self, content: str) -> List[StyleIssue]:
        """Check for common punctuation issues."""
        issues: List[StyleIssue] = []
        for pattern, issue_type, suggestion in PUNCTUATION_ISSUES:
            for match in pattern.finditer(content):
                issues.append(StyleIssue(
                    issue_type=issue_type,
                    description=f"Punctuation issue: {suggestion}",
                    severity="info",
                    location=match.group(),
                    original_text=match.group(),
                    suggestion=suggestion,
                ))
        if self.style_guide.use_oxford_comma:
            no_oxford = re.findall(r"\b(\w+,\s+\w+)\s+and\s+\w+\b", content)
            for match in no_oxford:
                issues.append(StyleIssue(
                    issue_type="oxford_comma",
                    description=f"Missing Oxford comma in listing",
                    severity="info",
                    location=match,
                    suggestion="Consider adding a comma before 'and' in lists.",
                ))
        else:
            oxford = re.findall(r"\b(\w+,\s+\w+,\s+and\s+\w+)\b", content)
            for match in oxford:
                issues.append(StyleIssue(
                    issue_type="unnecessary_oxford_comma",
                    description="Oxford comma used but style guide discourages it",
                    severity="info",
                    location=match[:50],
                    suggestion="Remove the comma before 'and' in lists.",
                ))
        return issues

    def _check_jargon(self, content: str) -> List[StyleIssue]:
        """Check for jargon and unnecessary technical terms."""
        issues: List[StyleIssue] = []
        content_lower = content.lower()
        all_jargon: List[Tuple[str, str]] = []
        for domain, terms in JARGON_TERMS.items():
            for term in terms:
                if term.lower() in self.jargon_allowed:
                    continue
                if term.lower() in self.jargon_blocked:
                    all_jargon.append((term, domain))
                elif term in content_lower:
                    all_jargon.append((term, domain))
        for term, domain in all_jargon:
            issues.append(StyleIssue(
                issue_type="jargon",
                description=f"Jargon term '{term}' (common in {domain}) may confuse readers",
                severity="info",
                location=term,
                original_text=term,
                suggestion=f"Replace '{term}' with simpler language or define it on first use.",
            ))
        return issues

    def _check_consistency(self, content: str) -> List[StyleIssue]:
        """Check for style consistency issues."""
        issues: List[StyleIssue] = []
        terminology_issues = self._check_terminology_consistency(content)
        issues.extend(terminology_issues)
        voice_issues = self._check_voice_consistency(content)
        issues.extend(voice_issues)
        heading_issues = self._check_heading_case(content)
        issues.extend(heading_issues)
        return issues

    def _check_terminology_consistency(self, content: str) -> List[StyleIssue]:
        """Check terminology consistency."""
        issues: List[StyleIssue] = []
        if not self.allowed_terminology:
            return issues
        for wrong, correct in self.allowed_terminology.items():
            if wrong.lower() in content.lower():
                issues.append(StyleIssue(
                    issue_type="terminology_inconsistency",
                    description=f"'{wrong}' used instead of preferred '{correct}'",
                    severity="warning",
                    location=wrong,
                    original_text=wrong,
                    suggested_text=correct,
                    suggestion=f"Replace '{wrong}' with '{correct}' for consistency.",
                ))
        return issues

    def _check_voice_consistency(self, content: str) -> List[StyleIssue]:
        """Check for voice consistency."""
        issues: List[StyleIssue] = []
        sentences = re.split(r"(?<=[.!?])\s+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s) > 20]
        if len(sentences) < 5:
            return issues
        passive_count = sum(1 for s in sentences if PASSIVE_PATTERN.search(s))
        total = len(sentences)
        passive_ratio = passive_count / total
        if passive_ratio > self.style_guide.max_passive_voice_ratio + 0.1:
            issues.append(StyleIssue(
                issue_type="high_passive_ratio",
                description=f"Passive voice ratio ({passive_ratio:.1%}) exceeds recommended maximum "
                            f"({self.style_guide.max_passive_voice_ratio:.0%})",
                severity="warning",
                suggestion="Increase active voice usage for more direct writing.",
            ))
        person_consistency = self._check_person_consistency(content)
        if person_consistency:
            issues.append(person_consistency)
        return issues

    def _check_person_consistency(self, content: str) -> Optional[StyleIssue]:
        """Check for consistency in person usage."""
        sentences = re.split(r"(?<=[.!?])\s+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s) > 15]
        if len(sentences) < 5:
            return None
        first_person_sentences = sum(1 for s in sentences if FIRST_PERSON_PATTERN.search(s))
        third_person_sentences = len(sentences) - first_person_sentences
        if first_person_sentences > 0 and third_person_sentences > first_person_sentences * 2:
            if first_person_sentences > 1:
                return StyleIssue(
                    issue_type="inconsistent_person",
                    description=f"Mixed first-person ({first_person_sentences} sentences) and "
                                f"third-person ({third_person_sentences} sentences) usage",
                    severity="warning",
                    suggestion="Maintain consistent person throughout the content.",
                )
        return None

    def _check_heading_case(self, content: str) -> List[StyleIssue]:
        """Check heading case consistency."""
        issues: List[StyleIssue] = []
        heading_pattern = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
        for match in heading_pattern.finditer(content):
            heading = match.group(1).strip()
            if self.style_guide.heading_case == "title":
                title_case = heading.title()
                if heading != title_case and not heading.isupper():
                    issues.append(StyleIssue(
                        issue_type="heading_case",
                        description=f"Heading '{heading}' may not use title case",
                        severity="info",
                        location=heading,
                        original_text=heading,
                        suggested_text=title_case,
                        suggestion="Use title case for headings: capitalize major words.",
                    ))
        return issues

    def _check_paragraph_structure(self, content: str) -> List[StyleIssue]:
        """Check paragraph structure issues."""
        issues: List[StyleIssue] = []
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            word_count = len(para.split())
            if word_count > self.style_guide.max_paragraph_length * 1.5:
                issues.append(StyleIssue(
                    issue_type="long_paragraph",
                    description=f"Paragraph {i + 1} has {word_count} words "
                                f"(recommended max: {self.style_guide.max_paragraph_length})",
                    severity="warning",
                    location=para[:80],
                    suggestion="Consider splitting this paragraph into shorter paragraphs.",
                ))
            elif word_count < 10 and len(paragraphs) > 1:
                issues.append(StyleIssue(
                    issue_type="short_paragraph",
                    description=f"Paragraph {i + 1} has only {word_count} words",
                    severity="info",
                    location=para[:80],
                    suggestion="Consider merging with adjacent paragraph.",
                ))
        return issues

    def _check_grammar(self, content: str) -> List[StyleIssue]:
        """Check for common grammar issues."""
        issues: List[StyleIssue] = []
        split_infinitives = SPLIT_INFINITIVE_PATTERN.findall(content)
        if split_infinitives:
            issues.append(StyleIssue(
                issue_type="split_infinitive",
                description=f"Split infinitive detected: '{' '.join(split_infinitives[:3])}'",
                severity="info",
                suggestion="Consider avoiding split infinitives for formal writing.",
            ))
        double_spaces = re.findall(r"[.!?]\s{3,}[A-Z]", content)
        if double_spaces:
            issues.append(StyleIssue(
                issue_type="excessive_spacing",
                description="Excessive spacing between sentences detected",
                severity="info",
                suggestion="Use single space between sentences.",
            ))
        comma_splices = re.findall(r"[a-z]+\s*,\s*[a-z]+\s*,\s*[a-z]+\s*,\s*[a-z]+", content)
        if comma_splices:
            issues.append(StyleIssue(
                issue_type="comma_splice",
                description="Possible comma splice detected",
                severity="info",
                suggestion="Use semicolons or periods to separate independent clauses.",
            ))
        return issues

    def _compute_statistics(self, content: str, sentences: List[str], words: List[str], issues: List[StyleIssue]) -> StyleStatistics:
        """Compute comprehensive style statistics."""
        stats = StyleStatistics()
        stats.total_sentences = len(sentences)
        stats.total_words = len(words)
        if sentences:
            stats.avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        stats.long_sentences = sum(
            1 for s in sentences if len(s.split()) > self.style_guide.max_sentence_length
        )
        stats.passive_voice_count = len(PASSIVE_PATTERN.findall(content))
        stats.passive_voice_ratio = stats.passive_voice_count / max(1, stats.total_sentences)
        stats.contraction_count = len(CONTRACTION_PATTERN.findall(content))
        stats.first_person_count = len(FIRST_PERSON_PATTERN.findall(content))
        stats.second_person_count = len(SECOND_PERSON_PATTERN.findall(content))
        all_jargon: Set[str] = set()
        for domain, terms in JARGON_TERMS.items():
            for term in terms:
                if term.lower() in content.lower():
                    all_jargon.add(term)
        stats.jargon_count = len(all_jargon)
        stats.punctuation_issues = sum(
            1 for i in issues if i.issue_type in ("space_before_period", "space_before_comma",
                                                   "space_before_semicolon", "space_before_colon")
        )
        complexity_counts: Dict[str, int] = {"very_simple": 0, "simple": 0, "moderate": 0, "complex": 0}
        for sentence in sentences:
            length = len(sentence.split())
            if length <= 5:
                complexity_counts["very_simple"] += 1
            elif length <= 10:
                complexity_counts["simple"] += 1
            elif length <= 20:
                complexity_counts["moderate"] += 1
            else:
                complexity_counts["complex"] += 1
        stats.sentence_complexity = complexity_counts
        return stats

    def _generate_recommendations(self, issues: List[StyleIssue], stats: StyleStatistics) -> List[str]:
        """Generate style recommendations."""
        recommendations: List[str] = []
        recommendations_map: Dict[str, str] = {
            "passive_voice": "Reduce passive voice usage for more direct writing.",
            "contraction": "Expand contractions to maintain formal style.",
            "first_person": "Use third-person perspective for objectivity.",
            "second_person": "Avoid addressing the reader directly.",
            "long_sentence": "Break long sentences into shorter ones for readability.",
            "short_sentence": "Combine very short sentences for better flow.",
            "spelling_variant": "Use consistent spelling (American/British) throughout.",
            "oxford_comma": "Use Oxford commas for clarity in lists.",
            "unnecessary_oxford_comma": "Remove Oxford comma per style guide.",
            "jargon": "Replace jargon with plain language.",
            "terminology_inconsistency": "Use consistent terminology throughout.",
            "high_passive_ratio": "Rewrite passive constructions in active voice.",
            "inconsistent_person": "Choose a consistent grammatical person.",
            "heading_case": "Use consistent heading capitalization.",
            "long_paragraph": "Break long paragraphs into smaller sections.",
            "short_paragraph": "Merge very short paragraphs for better structure.",
            "split_infinitive": "Avoid split infinitives in formal writing.",
            "comma_splice": "Use proper punctuation to separate clauses.",
        }
        seen_types: Set[str] = set()
        for issue in issues:
            if issue.issue_type not in seen_types:
                seen_types.add(issue.issue_type)
                rec = recommendations_map.get(issue.issue_type)
                if rec and rec not in recommendations:
                    recommendations.append(rec)
        if stats.passive_voice_ratio > self.style_guide.max_passive_voice_ratio:
            active_rec = "Rewrite approximately " + str(
                int(stats.passive_voice_count - self.style_guide.max_passive_voice_ratio * stats.total_sentences)
            ) + " passive constructions in active voice."
            if active_rec not in recommendations:
                recommendations.append(active_rec)
        if not recommendations:
            recommendations.append("Content style is consistent with the selected style guide.")
        return recommendations

    def set_style_guide(self, guide_name: str) -> None:
        """Switch to a different predefined style guide."""
        if guide_name in STYLE_GUIDES:
            self.style_guide = STYLE_GUIDES[guide_name]
            self.logger.info("Switched to style guide: %s", guide_name)
        else:
            self.logger.warning("Unknown style guide: %s", guide_name)

    def get_available_guides(self) -> List[str]:
        """Get list of available predefined style guides."""
        return list(STYLE_GUIDES.keys())

    def add_jargon_term(self, term: str, domain: str = "custom") -> None:
        """Add a jargon term for detection."""
        if domain not in JARGON_TERMS:
            JARGON_TERMS[domain] = []
        if term not in JARGON_TERMS[domain]:
            JARGON_TERMS[domain].append(term)

    def allow_jargon_term(self, term: str) -> None:
        """Allow a specific jargon term (exclude from detection)."""
        self.jargon_allowed.add(term.lower())

    def block_jargon_term(self, term: str) -> None:
        """Always flag a specific jargon term."""
        self.jargon_blocked.add(term.lower())

    def set_terminology(self, terminology: Dict[str, str]) -> None:
        """Set terminology mappings for consistency checking."""
        self.allowed_terminology = terminology

    def detect_passive_voice(self, content: str) -> List[Dict[str, Any]]:
        """Convenience method for passive voice detection only."""
        sentences = re.split(r"(?<=[.!?])\s+", content)
        detections: List[Dict[str, Any]] = []
        for sentence in sentences:
            matches = PASSIVE_PATTERN.findall(sentence)
            for match in matches:
                detections.append({
                    "sentence": sentence[:80],
                    "passive_phrase": f"{match[0]} {match[1]}",
                    "position": content.find(sentence),
                })
        return detections

    def analyze_sentence_complexity(self, content: str) -> Dict[str, Any]:
        """Analyze sentence complexity distribution."""
        sentences = re.split(r"(?<=[.!?])\s+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return {"distribution": {}, "avg_length": 0.0}
        lengths = [len(s.split()) for s in sentences]
        distribution: Dict[str, int] = {"very_simple": 0, "simple": 0, "moderate": 0, "complex": 0}
        for length in lengths:
            if length <= 5:
                distribution["very_simple"] += 1
            elif length <= 10:
                distribution["simple"] += 1
            elif length <= 20:
                distribution["moderate"] += 1
            else:
                distribution["complex"] += 1
        return {
            "distribution": distribution,
            "avg_length": round(sum(lengths) / len(lengths), 2),
            "max_length": max(lengths),
            "min_length": min(lengths),
        }
