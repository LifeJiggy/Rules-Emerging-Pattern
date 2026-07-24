"""Feature extraction module for pattern analysis and model training."""
import logging
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple, Set, Callable

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern

logger = logging.getLogger(__name__)


class FeatureType(Enum):
    TEXT = "text"
    STATISTICAL = "statistical"
    STRUCTURAL = "structural"
    CONTENT = "content"
    DERIVED = "derived"


class NormalizationMethod(Enum):
    NONE = "none"
    MIN_MAX = "min_max"
    Z_SCORE = "z_score"
    ROBUST = "robust"
    LOG = "log"
    UNIT_LENGTH = "unit_length"


class FeatureCategory(Enum):
    LOW_LEVEL = "low_level"
    HIGH_LEVEL = "high_level"
    META = "meta"


@dataclass
class FeatureConfig:
    enable_text_features: bool = True
    enable_statistical_features: bool = True
    enable_structural_features: bool = True
    enable_content_features: bool = True
    normalization_method: str = "z_score"
    variance_threshold: float = 0.01
    max_features: int = 100
    min_feature_frequency: int = 3
    correlation_threshold: float = 0.95
    enable_feature_selection: bool = True
    extract_ngrams: bool = True
    max_ngram_size: int = 3
    sentiment_enabled: bool = True
    readability_enabled: bool = True
    cache_features: bool = True
    parallel_extraction: bool = False
    feature_store_size: int = 10000
    min_text_length: int = 1
    max_text_length: int = 100000
    default_batch_size: int = 100


@dataclass
class FeatureDefinition:
    name: str
    feature_type: FeatureType
    category: FeatureCategory
    extractor: str
    normalization: NormalizationMethod = NormalizationMethod.NONE
    min_value: float = float('-inf')
    max_value: float = float('inf')
    default_value: float = 0.0
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    is_categorical: bool = False
    categories: List[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass
class ExtractedFeature:
    name: str
    value: float
    raw_value: Any = None
    normalized_value: Optional[float] = None
    feature_type: FeatureType = FeatureType.TEXT
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureVector:
    features: Dict[str, ExtractedFeature]
    source_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    label: Optional[Any] = None
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_array(self, normalize: bool = True, feature_names: Optional[List[str]] = None) -> List[float]:
        names = feature_names or sorted(self.features.keys())
        result = []
        for name in names:
            if name in self.features:
                f = self.features[name]
                if normalize and f.normalized_value is not None:
                    result.append(f.normalized_value)
                else:
                    result.append(f.value)
            else:
                result.append(0.0)
        return result

    def to_dict(self, normalize: bool = True) -> Dict[str, float]:
        result = {}
        for name, f in self.features.items():
            if normalize and f.normalized_value is not None:
                result[name] = f.normalized_value
            else:
                result[name] = f.value
        return result

    def get_feature_names(self) -> List[str]:
        return sorted(self.features.keys())

    def get_feature_count(self) -> int:
        return len(self.features)

    def merge(self, other: 'FeatureVector') -> 'FeatureVector':
        merged = FeatureVector(
            features={**self.features, **other.features},
            source_id=self.source_id or other.source_id,
            timestamp=self.timestamp,
            label=self.label or other.label,
            weight=max(self.weight, other.weight),
            metadata={**self.metadata, **other.metadata}
        )
        return merged


@dataclass
class FeatureStatistics:
    feature_name: str
    count: int
    mean: float
    std: float
    min_val: float
    max_val: float
    q25: float
    q50: float
    q75: float
    missing_count: int
    variance: float
    entropy: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0


class FeatureExtractor:
    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()
        self.feature_definitions: Dict[str, FeatureDefinition] = {}
        self.feature_cache: Dict[str, Dict[str, float]] = {}
        self.normalization_params: Dict[str, Dict[str, float]] = {}
        self.feature_stats: Dict[str, FeatureStatistics] = {}
        self.extraction_count = 0
        self._sentiment_lexicon: Dict[str, float] = {}
        self._stop_words: Set[str] = set()
        self._initialize_default_features()
        self._load_lexicons()
        logger.info(f"FeatureExtractor initialized (normalization={self.config.normalization_method})")

    def _load_lexicons(self) -> None:
        self._sentiment_lexicon = {
            'good': 0.5, 'bad': -0.5, 'great': 0.8, 'terrible': -0.8, 'excellent': 0.9,
            'poor': -0.6, 'amazing': 0.9, 'awful': -0.9, 'positive': 0.6, 'negative': -0.6,
            'wonderful': 0.8, 'horrible': -0.8, 'fantastic': 0.85, 'dreadful': -0.85,
            'happy': 0.7, 'sad': -0.5, 'love': 0.8, 'hate': -0.8, 'beautiful': 0.7,
            'ugly': -0.6, 'success': 0.7, 'failure': -0.7, 'pass': 0.3, 'fail': -0.5,
            'correct': 0.4, 'incorrect': -0.4, 'valid': 0.3, 'invalid': -0.3,
            'safe': 0.5, 'dangerous': -0.6, 'secure': 0.5, 'vulnerable': -0.5,
            'allow': 0.2, 'deny': -0.3, 'approve': 0.4, 'reject': -0.4,
            'upgrade': 0.4, 'downgrade': -0.3, 'improve': 0.5, 'worsen': -0.5,
            'clean': 0.3, 'dirty': -0.3, 'efficient': 0.5, 'inefficient': -0.4,
            'fast': 0.3, 'slow': -0.3, 'reliable': 0.4, 'unreliable': -0.4,
        }
        self._stop_words = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'shall',
            'should', 'may', 'might', 'must', 'can', 'could', 'i', 'you', 'he',
            'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
            'this', 'that', 'these', 'those', 'my', 'your', 'his', 'its',
            'our', 'their', 'and', 'but', 'or', 'nor', 'for', 'yet', 'so',
            'if', 'then', 'else', 'when', 'where', 'why', 'how', 'which',
            'who', 'whom', 'what', 'not', 'no', 'none', 'very', 'too',
            'just', 'about', 'up', 'down', 'in', 'out', 'on', 'off', 'over',
            'under', 'again', 'further', 'once', 'here', 'there', 'all',
            'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
        }

    def _initialize_default_features(self) -> None:
        text_features = [
            ("word_count", "count_words", "Total number of words"),
            ("char_count", "count_characters", "Total number of characters"),
            ("sentence_count", "count_sentences", "Total number of sentences"),
            ("avg_word_length", "average_word_length", "Average word length in characters"),
            ("max_word_length", "max_word_length", "Maximum word length"),
            ("min_word_length", "min_word_length", "Minimum word length"),
            ("unique_word_count", "count_unique_words", "Number of unique words"),
            ("type_token_ratio", "type_token_ratio", "Ratio of unique words to total words"),
            ("long_word_ratio", "long_word_ratio", "Ratio of words with >6 characters"),
            ("short_word_ratio", "short_word_ratio", "Ratio of words with <3 characters"),
            ("digit_count", "count_digits", "Number of digit characters"),
            ("uppercase_count", "count_uppercase", "Number of uppercase characters"),
            ("punctuation_count", "count_punctuation", "Number of punctuation characters"),
            ("whitespace_ratio", "whitespace_ratio", "Ratio of whitespace to total characters"),
            ("alpha_ratio", "alpha_ratio", "Ratio of alphabetic characters to total"),
            ("digit_ratio", "digit_ratio", "Ratio of digit characters to total"),
        ]
        for name, ext, desc in text_features:
            self.register_feature(FeatureDefinition(
                name=name, feature_type=FeatureType.TEXT, category=FeatureCategory.LOW_LEVEL,
                extractor=ext, description=desc
            ))
        stat_features = [
            ("mean_word_length", "mean_word_length", "Mean of word lengths"),
            ("std_word_length", "std_word_length", "Standard deviation of word lengths"),
            ("sentence_length_mean", "sentence_length_mean", "Mean sentence length in words"),
            ("sentence_length_std", "sentence_length_std", "Std dev of sentence lengths"),
            ("vocabulary_richness", "vocabulary_richness", "Herdan's C = log(unique)/log(total)"),
            ("hapax_legomena_ratio", "hapax_legomena_ratio", "Ratio of words appearing once"),
            ("word_frequency_entropy", "word_frequency_entropy", "Entropy of word frequency distribution"),
            ("char_entropy", "char_entropy", "Entropy of character distribution"),
        ]
        for name, ext, desc in stat_features:
            self.register_feature(FeatureDefinition(
                name=name, feature_type=FeatureType.STATISTICAL, category=FeatureCategory.HIGH_LEVEL,
                extractor=ext, description=desc
            ))
        struct_features = [
            ("paragraph_count", "count_paragraphs", "Number of paragraphs"),
            ("avg_paragraph_length", "avg_paragraph_length", "Average paragraph length in sentences"),
            ("section_header_count", "count_section_headers", "Number of section headers"),
            ("list_item_count", "count_list_items", "Number of list items"),
            ("code_block_count", "count_code_blocks", "Number of code blocks"),
            ("code_block_ratio", "code_block_ratio", "Ratio of code block lines to total lines"),
            ("url_count", "count_urls", "Number of URLs"),
            ("email_count", "count_emails", "Number of email addresses"),
            ("line_count", "count_lines", "Number of lines"),
            ("blank_line_ratio", "blank_line_ratio", "Ratio of blank lines to total lines"),
            ("structure_depth", "structure_depth", "Estimated nesting depth of structure"),
            ("table_count", "count_tables", "Number of tabular structures"),
        ]
        for name, ext, desc in struct_features:
            self.register_feature(FeatureDefinition(
                name=name, feature_type=FeatureType.STRUCTURAL, category=FeatureCategory.HIGH_LEVEL,
                extractor=ext, description=desc
            ))
        content_features = [
            ("keyword_density", "keyword_density", "Density of predefined keywords"),
            ("sentiment_score", "sentiment_score", "Aggregate sentiment score"),
            ("sentiment_volatility", "sentiment_volatility", "Variation in sentiment across sentences"),
            ("readability_flesch", "readability_flesch", "Flesch reading ease score"),
            ("readability_fkgl", "readability_fkgl", "Flesch-Kincaid grade level"),
            ("formality_score", "formality_score", "Measure of text formality"),
            ("subjectivity_score", "subjectivity_score", "Measure of text subjectivity"),
            ("technical_jargon_ratio", "technical_jargon_ratio", "Ratio of technical terms"),
            ("modal_verb_count", "count_modal_verbs", "Number of modal auxiliary verbs"),
            ("hedging_word_count", "count_hedging_words", "Number of hedging words"),
            ("intensifier_count", "count_intensifiers", "Number of intensifier words"),
            ("question_ratio", "question_ratio", "Ratio of sentences ending with ?"),
            ("exclamation_ratio", "exclamation_ratio", "Ratio of sentences ending with !"),
        ]
        for name, ext, desc in content_features:
            self.register_feature(FeatureDefinition(
                name=name, feature_type=FeatureType.CONTENT, category=FeatureCategory.HIGH_LEVEL,
                extractor=ext, description=desc
            ))

    def register_feature(self, definition: FeatureDefinition) -> None:
        self.feature_definitions[definition.name] = definition
        logger.debug(f"Registered feature: {definition.name} ({definition.feature_type.value})")

    def register_custom_extractor(self, name: str, extractor: Callable[[str], float],
                                  feature_type: FeatureType = FeatureType.DERIVED,
                                  description: str = "") -> None:
        self.feature_definitions[name] = FeatureDefinition(
            name=name, feature_type=feature_type, category=FeatureCategory.META,
            extractor=f"custom_{len(self.feature_definitions)}", description=description
        )
        self._custom_extractors[name] = extractor

    def _count_words(self, text: str) -> float:
        tokens = text.split()
        return float(len(tokens))

    def _count_characters(self, text: str) -> float:
        return float(len(text))

    def _count_sentences(self, text: str) -> float:
        sentences = re.split(r'[.!?]+', text)
        return float(len([s for s in sentences if s.strip()]))

    def _average_word_length(self, text: str) -> float:
        words = text.split()
        if not words:
            return 0.0
        return statistics.mean(len(w) for w in words)

    def _max_word_length(self, text: str) -> float:
        words = text.split()
        return float(max((len(w) for w in words), default=0))

    def _min_word_length(self, text: str) -> float:
        words = text.split()
        return float(min((len(w) for w in words), default=0))

    def _count_unique_words(self, text: str) -> float:
        words = text.lower().split()
        return float(len(set(words)))

    def _type_token_ratio(self, text: str) -> float:
        words = text.lower().split()
        if not words:
            return 0.0
        return len(set(words)) / len(words)

    def _long_word_ratio(self, text: str) -> float:
        words = text.split()
        if not words:
            return 0.0
        return sum(1 for w in words if len(w) > 6) / len(words)

    def _short_word_ratio(self, text: str) -> float:
        words = text.split()
        if not words:
            return 0.0
        return sum(1 for w in words if len(w) < 3) / len(words)

    def _count_digits(self, text: str) -> float:
        return float(sum(1 for c in text if c.isdigit()))

    def _count_uppercase(self, text: str) -> float:
        return float(sum(1 for c in text if c.isupper()))

    def _count_punctuation(self, text: str) -> float:
        return float(sum(1 for c in text if c in '.,;:!?"\'()[]{}<>-–—/\\|`~@#$%^&*_+='))

    def _whitespace_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        return sum(1 for c in text if c.isspace()) / len(text)

    def _alpha_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        alpha = sum(1 for c in text if c.isalpha())
        return alpha / len(text)

    def _digit_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        digits = sum(1 for c in text if c.isdigit())
        return digits / len(text)

    def _mean_word_length(self, text: str) -> float:
        return self._average_word_length(text)

    def _std_word_length(self, text: str) -> float:
        words = [len(w) for w in text.split()]
        if len(words) < 2:
            return 0.0
        try:
            return statistics.stdev(words)
        except statistics.StatisticsError:
            return 0.0

    def _sentence_length_mean(self, text: str) -> float:
        sentences = [s.split() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        return statistics.mean(len(s) for s in sentences)

    def _sentence_length_std(self, text: str) -> float:
        sentences = [len(s.split()) for s in re.split(r'[.!?]+', text) if s.strip()]
        if len(sentences) < 2:
            return 0.0
        try:
            return statistics.stdev(sentences)
        except statistics.StatisticsError:
            return 0.0

    def _vocabulary_richness(self, text: str) -> float:
        words = text.lower().split()
        if len(words) < 2:
            return 1.0
        return math.log(len(set(words))) / math.log(len(words)) if len(words) > 1 else 1.0

    def _hapax_legomena_ratio(self, text: str) -> float:
        words = text.lower().split()
        if not words:
            return 0.0
        freq = Counter(words)
        hapax = sum(1 for count in freq.values() if count == 1)
        return hapax / len(words)

    def _word_frequency_entropy(self, text: str) -> float:
        words = text.lower().split()
        if not words:
            return 0.0
        freq = Counter(words)
        total = len(words)
        entropy = 0.0
        for count in freq.values():
            p = count / total
            entropy -= p * math.log2(p)
        return entropy

    def _char_entropy(self, text: str) -> float:
        if not text:
            return 0.0
        freq = Counter(text)
        total = len(text)
        entropy = 0.0
        for count in freq.values():
            p = count / total
            entropy -= p * math.log2(p)
        return entropy

    def _count_paragraphs(self, text: str) -> float:
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        return float(len(paragraphs))

    def _avg_paragraph_length(self, text: str) -> float:
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if not paragraphs:
            return 0.0
        para_sentence_counts = []
        for p in paragraphs:
            sentences = [s for s in re.split(r'[.!?]+', p) if s.strip()]
            para_sentence_counts.append(len(sentences))
        return statistics.mean(para_sentence_counts) if para_sentence_counts else 0.0

    def _count_section_headers(self, text: str) -> float:
        header_patterns = [
            r'^#{1,6}\s+\w+',
            r'^[A-Z][A-Z\s]+:$',
            r'^[A-Z][a-z]+(?:[A-Z][a-z]+)*:',
            r'^-\s*\[.*\]',
            r'^\d+\.\d+\s+\w+',
        ]
        count = 0
        for line in text.split('\n'):
            line = line.strip()
            for pattern in header_patterns:
                if re.match(pattern, line):
                    count += 1
                    break
        return float(count)

    def _count_list_items(self, text: str) -> float:
        list_patterns = [r'^[\*\-\+]\s+', r'^\d+[\.\)]\s+', r'^\[[ x]\]\s+']
        count = 0
        for line in text.split('\n'):
            line = line.strip()
            for pattern in list_patterns:
                if re.match(pattern, line):
                    count += 1
                    break
        return float(count)

    def _count_code_blocks(self, text: str) -> float:
        fences = re.findall(r'```', text)
        return float(len(fences) // 2)

    def _code_block_ratio(self, text: str) -> float:
        lines = text.split('\n')
        if not lines:
            return 0.0
        in_code = False
        code_lines = 0
        for line in lines:
            if line.strip().startswith('```'):
                in_code = not in_code
            elif in_code:
                code_lines += 1
        return code_lines / len(lines)

    def _count_urls(self, text: str) -> float:
        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*', text)
        return float(len(urls))

    def _count_emails(self, text: str) -> float:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        return float(len(emails))

    def _count_lines(self, text: str) -> float:
        return float(len(text.split('\n')))

    def _blank_line_ratio(self, text: str) -> float:
        lines = text.split('\n')
        if not lines:
            return 0.0
        blanks = sum(1 for line in lines if not line.strip())
        return blanks / len(lines)

    def _structure_depth(self, text: str) -> float:
        max_depth = 0
        for line in text.split('\n'):
            stripped = line.rstrip()
            indent = len(stripped) - len(stripped.lstrip())
            depth = indent // 2
            max_depth = max(max_depth, depth)
        return float(max_depth)

    def _count_tables(self, text: str) -> float:
        lines = text.split('\n')
        table_count = 0
        in_table = False
        for line in lines:
            if re.match(r'^\|.*\|$', line.strip()):
                if not in_table:
                    table_count += 1
                    in_table = True
            else:
                in_table = False
        return float(table_count)

    def _keyword_density(self, text: str) -> float:
        code_keywords = {'class', 'def', 'function', 'import', 'from', 'return', 'if', 'else',
                         'for', 'while', 'try', 'except', 'raise', 'with', 'as', 'yield',
                         'lambda', 'pass', 'break', 'continue', 'async', 'await'}
        data_keywords = {'data', 'value', 'key', 'result', 'response', 'error', 'status',
                         'config', 'param', 'option', 'setting', 'property', 'attribute'}
        security_keywords = {'password', 'token', 'secret', 'auth', 'permission', 'access',
                             'key', 'certificate', 'credential', 'session', 'cookie'}
        words = text.lower().split()
        if not words:
            return 0.0
        keyword_set = code_keywords | data_keywords | security_keywords
        keyword_count = sum(1 for w in words if w in keyword_set)
        return keyword_count / len(words)

    def _sentiment_score(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        total_score = 0.0
        word_count = 0
        for sentence in sentences:
            words = sentence.lower().split()
            for word in words:
                if word in self._sentiment_lexicon:
                    total_score += self._sentiment_lexicon[word]
                    word_count += 1
        if word_count == 0:
            return 0.0
        return total_score / word_count

    def _sentiment_volatility(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        scores = []
        for sentence in sentences:
            words = sentence.lower().split()
            sent_score = 0.0
            sent_words = 0
            for word in words:
                if word in self._sentiment_lexicon:
                    sent_score += self._sentiment_lexicon[word]
                    sent_words += 1
            if sent_words > 0:
                scores.append(sent_score / sent_words)
        if len(scores) < 2:
            return 0.0
        try:
            return statistics.stdev(scores)
        except statistics.StatisticsError:
            return 0.0

    def _readability_flesch(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        words = text.split()
        syllables = self._count_syllables(text)
        if not sentences or not words:
            return 0.0
        avg_sent_len = len(words) / len(sentences)
        avg_syllables = syllables / len(words) if words else 0
        score = 206.835 - 1.015 * avg_sent_len - 84.6 * avg_syllables
        return max(0.0, min(100.0, score))

    def _readability_fkgl(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        words = text.split()
        syllables = self._count_syllables(text)
        if not sentences or not words:
            return 0.0
        avg_sent_len = len(words) / len(sentences)
        avg_syllables = syllables / len(words) if words else 0
        return 0.39 * avg_sent_len + 11.8 * avg_syllables - 15.59

    def _count_syllables(self, text: str) -> int:
        count = 0
        for word in text.lower().split():
            word = re.sub(r'e$', '', word)
            word = re.sub(r'[^aeiouy]+', ' ', word)
            syllables = len(word.split())
            count += max(1, syllables)
        return count

    def _formality_score(self, text: str) -> float:
        words = text.split()
        if not words:
            return 0.0
        nouns = re.findall(r'\b[A-Z][a-z]*\b', text)
        pronouns = re.findall(r'\b(I|you|he|she|it|we|they|me|him|her|us|them)\b', text, re.IGNORECASE)
        noun_count = len(nouns)
        pronoun_count = len(pronouns)
        total = noun_count + pronoun_count
        if total == 0:
            return 0.5
        return noun_count / total

    def _subjectivity_score(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        subjective_indicators = {'think', 'believe', 'feel', 'opinion', 'seems', 'appears',
                                  'probably', 'maybe', 'perhaps', 'possibly', 'likely',
                                  'i think', 'in my opinion', 'from my perspective'}
        subjective_count = 0
        for sentence in sentences:
            lower = sentence.lower()
            for indicator in subjective_indicators:
                if indicator in lower:
                    subjective_count += 1
                    break
        return subjective_count / len(sentences)

    def _technical_jargon_ratio(self, text: str) -> float:
        jargon_patterns = [
            r'\b[A-Z]{2,}\b',
            r'\b\w+_\w+\b',
            r'\b\d+\.\d+\.\d+\.\d+\b',
            r'\b[a-z]+[A-Z][a-zA-Z]*\b',
            r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
        ]
        words = text.split()
        if not words:
            return 0.0
        jargon_count = 0
        for word in words:
            for pattern in jargon_patterns:
                if re.match(pattern, word):
                    jargon_count += 1
                    break
        return jargon_count / len(words)

    def _count_modal_verbs(self, text: str) -> float:
        modals = re.findall(r'\b(can|could|may|might|must|shall|should|will|would)\b', text, re.IGNORECASE)
        return float(len(modals))

    def _count_hedging_words(self, text: str) -> float:
        hedging = re.findall(
            r'\b(perhaps|maybe|possibly|probably|apparently|seemingly|generally|'
            r'relatively|quite|rather|somewhat|fairly|slightly|about|around|almost|nearly)\b',
            text, re.IGNORECASE
        )
        return float(len(hedging))

    def _count_intensifiers(self, text: str) -> float:
        intensifiers = re.findall(
            r'\b(very|extremely|incredibly|absolutely|completely|totally|entirely|'
            r'highly|deeply|strongly|severely|seriously|terribly|awfully|really|truly)\b',
            text, re.IGNORECASE
        )
        return float(len(intensifiers))

    def _question_ratio(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        questions = sum(1 for s in sentences if s.endswith('?'))
        return questions / len(sentences)

    def _exclamation_ratio(self, text: str) -> float:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        exclamations = sum(1 for s in sentences if s.endswith('!'))
        return exclamations / len(sentences)

    def extract(self, text: str, context: Optional[Dict] = None,
                feature_names: Optional[List[str]] = None) -> FeatureVector:
        if not isinstance(text, str):
            logger.warning(f"Non-string input to extract: {type(text)}")
            text = str(text) if text is not None else ""
        if len(text) < self.config.min_text_length:
            text = ""
        if len(text) > self.config.max_text_length:
            text = text[:self.config.max_text_length]
        cache_key = None
        if self.config.cache_features and len(text) < 10000:
            cache_key = f"{hash(text)}_{self.config.normalization_method}"
            if cache_key in self.feature_cache:
                cached = self.feature_cache[cache_key]
                vector = FeatureVector(
                    features={name: ExtractedFeature(name=name, value=val, raw_value=val)
                              for name, val in cached.items()},
                    source_id=str(hash(text)),
                    metadata=context or {}
                )
                self.extraction_count += 1
                return vector
        features: Dict[str, ExtractedFeature] = {}
        if self.config.enable_text_features:
            features.update(self._extract_text_features(text))
        if self.config.enable_statistical_features:
            features.update(self._extract_statistical_features(text))
        if self.config.enable_structural_features:
            features.update(self._extract_structural_features(text))
        if self.config.enable_content_features:
            features.update(self._extract_content_features(text))
        if feature_names:
            features = {k: v for k, v in features.items() if k in feature_names}
        vector = FeatureVector(features=features, source_id=str(hash(text)), metadata=context or {})
        vector = self.normalize(vector)
        if cache_key and self.config.cache_features:
            if len(self.feature_cache) < self.config.feature_store_size:
                self.feature_cache[cache_key] = vector.to_dict(normalize=False)
        self.extraction_count += 1
        self._update_feature_stats(vector)
        return vector

    def _extract_text_features(self, text: str) -> Dict[str, ExtractedFeature]:
        results = {}
        extractors = [
            "word_count", "char_count", "sentence_count", "avg_word_length",
            "max_word_length", "min_word_length", "unique_word_count",
            "type_token_ratio", "long_word_ratio", "short_word_ratio",
            "digit_count", "uppercase_count", "punctuation_count",
            "whitespace_ratio", "alpha_ratio", "digit_ratio",
        ]
        for name in extractors:
            if name not in self.feature_definitions:
                continue
            try:
                method_name = f"_{self.feature_definitions[name].extractor}"
                method = getattr(self, method_name, None)
                if method:
                    value = method(text)
                    results[name] = ExtractedFeature(
                        name=name, value=value, raw_value=value,
                        feature_type=FeatureType.TEXT
                    )
            except Exception as e:
                logger.warning(f"Failed to extract text feature '{name}': {e}")
                results[name] = ExtractedFeature(
                    name=name, value=0.0, raw_value=None,
                    feature_type=FeatureType.TEXT, confidence=0.0
                )
        return results

    def _extract_statistical_features(self, text: str) -> Dict[str, ExtractedFeature]:
        results = {}
        extractors = [
            "mean_word_length", "std_word_length", "sentence_length_mean",
            "sentence_length_std", "vocabulary_richness", "hapax_legomena_ratio",
            "word_frequency_entropy", "char_entropy",
        ]
        for name in extractors:
            if name not in self.feature_definitions:
                continue
            try:
                method_name = f"_{self.feature_definitions[name].extractor}"
                method = getattr(self, method_name, None)
                if method:
                    value = method(text)
                    results[name] = ExtractedFeature(
                        name=name, value=value, raw_value=value,
                        feature_type=FeatureType.STATISTICAL
                    )
            except Exception as e:
                logger.warning(f"Failed to extract statistical feature '{name}': {e}")
                results[name] = ExtractedFeature(
                    name=name, value=0.0, raw_value=None,
                    feature_type=FeatureType.STATISTICAL, confidence=0.0
                )
        return results

    def _extract_structural_features(self, text: str) -> Dict[str, ExtractedFeature]:
        results = {}
        extractors = [
            "paragraph_count", "avg_paragraph_length", "section_header_count",
            "list_item_count", "code_block_count", "code_block_ratio",
            "url_count", "email_count", "line_count", "blank_line_ratio",
            "structure_depth", "table_count",
        ]
        for name in extractors:
            if name not in self.feature_definitions:
                continue
            try:
                method_name = f"_{self.feature_definitions[name].extractor}"
                method = getattr(self, method_name, None)
                if method:
                    value = method(text)
                    results[name] = ExtractedFeature(
                        name=name, value=value, raw_value=value,
                        feature_type=FeatureType.STRUCTURAL
                    )
            except Exception as e:
                logger.warning(f"Failed to extract structural feature '{name}': {e}")
                results[name] = ExtractedFeature(
                    name=name, value=0.0, raw_value=None,
                    feature_type=FeatureType.STRUCTURAL, confidence=0.0
                )
        return results

    def _extract_content_features(self, text: str) -> Dict[str, ExtractedFeature]:
        results = {}
        extractors = [
            "keyword_density", "sentiment_score", "sentiment_volatility",
            "readability_flesch", "readability_fkgl", "formality_score",
            "subjectivity_score", "technical_jargon_ratio", "modal_verb_count",
            "hedging_word_count", "intensifier_count", "question_ratio",
            "exclamation_ratio",
        ]
        for name in extractors:
            if name not in self.feature_definitions:
                continue
            try:
                method_name = f"_{self.feature_definitions[name].extractor}"
                method = getattr(self, method_name, None)
                if method:
                    value = method(text)
                    results[name] = ExtractedFeature(
                        name=name, value=value, raw_value=value,
                        feature_type=FeatureType.CONTENT
                    )
            except Exception as e:
                logger.warning(f"Failed to extract content feature '{name}': {e}")
                results[name] = ExtractedFeature(
                    name=name, value=0.0, raw_value=None,
                    feature_type=FeatureType.CONTENT, confidence=0.0
                )
        return results

    def normalize(self, vector: FeatureVector) -> FeatureVector:
        method = self.config.normalization_method
        for name, feature in vector.features.items():
            value = feature.value
            if method == NormalizationMethod.NONE.value or method == "none":
                normalized = value
            elif method == NormalizationMethod.MIN_MAX.value or method == "min_max":
                params = self.normalization_params.get(name, {})
                min_val = params.get('min', 0.0)
                max_val = params.get('max', 1.0)
                if max_val > min_val:
                    normalized = (value - min_val) / (max_val - min_val)
                else:
                    normalized = 0.5
            elif method == NormalizationMethod.Z_SCORE.value or method == "z_score":
                params = self.normalization_params.get(name, {})
                mean = params.get('mean', 0.0)
                std = params.get('std', 1.0)
                if std > 0:
                    normalized = (value - mean) / std
                else:
                    normalized = 0.0
            elif method == NormalizationMethod.ROBUST.value or method == "robust":
                params = self.normalization_params.get(name, {})
                median = params.get('median', 0.0)
                iqr = params.get('iqr', 1.0)
                if iqr > 0:
                    normalized = (value - median) / iqr
                else:
                    normalized = 0.0
            elif method == NormalizationMethod.LOG.value or method == "log":
                normalized = math.log1p(max(0.0, value))
            elif method == NormalizationMethod.UNIT_LENGTH.value or method == "unit_length":
                norm = math.sqrt(sum(f.value ** 2 for f in vector.features.values()))
                normalized = value / norm if norm > 0 else 0.0
            else:
                normalized = value
            defn = self.feature_definitions.get(name)
            if defn:
                normalized = max(defn.min_value, min(defn.max_value, normalized))
            feature.normalized_value = normalized
        return vector

    def fit_normalization(self, vectors: List[FeatureVector]) -> None:
        feature_values: Dict[str, List[float]] = defaultdict(list)
        for vector in vectors:
            for name, feature in vector.features.items():
                if not math.isnan(feature.value) and not math.isinf(feature.value):
                    feature_values[name].append(feature.value)
        for name, values in feature_values.items():
            if not values:
                continue
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            self.normalization_params[name] = {
                'min': sorted_vals[0],
                'max': sorted_vals[-1],
                'mean': statistics.mean(values),
                'std': statistics.stdev(values) if len(values) > 1 else 1.0,
                'median': statistics.median(values),
                'q25': sorted_vals[n // 4] if n > 0 else 0.0,
                'q75': sorted_vals[3 * n // 4] if n > 0 else 0.0,
                'iqr': (sorted_vals[3 * n // 4] - sorted_vals[n // 4]) if n > 0 else 1.0,
                'count': n,
            }
        logger.info(f"Fitted normalization params for {len(feature_values)} features")

    def select_features(self, vectors: List[FeatureVector], method: str = "variance",
                        top_k: Optional[int] = None) -> List[str]:
        if top_k is None:
            top_k = self.config.max_features
        if not vectors:
            return []
        if method == "variance":
            return self._select_by_variance(vectors, top_k)
        elif method == "correlation":
            return self._select_by_correlation(vectors, top_k)
        elif method == "frequency":
            return self._select_by_frequency(vectors, top_k)
        elif method == "mutual_information":
            return self._select_by_mutual_information(vectors, top_k)
        return sorted(vectors[0].features.keys())[:top_k]

    def _select_by_variance(self, vectors: List[FeatureVector], top_k: int) -> List[str]:
        feature_values: Dict[str, List[float]] = defaultdict(list)
        for vector in vectors:
            for name, feature in vector.features.items():
                feature_values[name].append(feature.value)
        variances = []
        for name, values in feature_values.items():
            if len(values) < 2:
                continue
            try:
                var = statistics.variance(values)
                if var >= self.config.variance_threshold:
                    variances.append((name, var))
            except statistics.StatisticsError:
                pass
        variances.sort(key=lambda x: x[1], reverse=True)
        selected = [name for name, _ in variances[:top_k]]
        logger.info(f"Variance selection kept {len(selected)}/{len(feature_values)} features")
        return selected

    def _select_by_correlation(self, vectors: List[FeatureVector], top_k: int) -> List[str]:
        feature_values: Dict[str, List[float]] = defaultdict(list)
        for vector in vectors:
            for name, feature in vector.features.items():
                feature_values[name].append(feature.value)
        names = list(feature_values.keys())
        if len(names) <= top_k:
            return names
        to_remove = set()
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if names[i] in to_remove or names[j] in to_remove:
                    continue
                vals_i = feature_values[names[i]]
                vals_j = feature_values[names[j]]
                if len(vals_i) < 3 or len(vals_j) < 3:
                    continue
                try:
                    corr = self._pearson(vals_i, vals_j)
                    if abs(corr) > self.config.correlation_threshold:
                        var_i = statistics.variance(vals_i) if len(vals_i) > 1 else 0
                        var_j = statistics.variance(vals_j) if len(vals_j) > 1 else 0
                        to_remove.add(names[i] if var_i < var_j else names[j])
                except (statistics.StatisticsError, ZeroDivisionError):
                    pass
        selected = [n for n in names if n not in to_remove][:top_k]
        logger.info(f"Correlation selection kept {len(selected)}/{len(names)} features")
        return selected

    def _select_by_frequency(self, vectors: List[FeatureVector], top_k: int) -> List[str]:
        counts: Counter = Counter()
        for vector in vectors:
            for name in vector.features:
                counts[name] += 1
        frequent = [(name, count) for name, count in counts.items()
                    if count >= self.config.min_feature_frequency]
        frequent.sort(key=lambda x: x[1], reverse=True)
        selected = [name for name, _ in frequent[:top_k]]
        logger.info(f"Frequency selection kept {len(selected)}/{len(counts)} features")
        return selected

    def _select_by_mutual_information(self, vectors: List[FeatureVector], top_k: int) -> List[str]:
        labeled = [(v, v.label) for v in vectors if v.label is not None]
        if len(labeled) < 10:
            return self._select_by_variance(vectors, top_k)
        feature_values: Dict[str, List[float]] = defaultdict(list)
        labels = []
        for vector, label in labeled:
            labels.append(label)
            for name, feature in vector.features.items():
                feature_values[name].append(feature.value)
        mi_scores = []
        for name, values in feature_values.items():
            if len(values) < 10:
                continue
            mi = self._compute_mutual_information(values, labels)
            mi_scores.append((name, mi))
        mi_scores.sort(key=lambda x: x[1], reverse=True)
        selected = [name for name, _ in mi_scores[:top_k]]
        logger.info(f"MI selection kept {len(selected)}/{len(feature_values)} features")
        return selected

    def _compute_mutual_information(self, x: List[float], y: List[Any]) -> float:
        n = len(x)
        x_bins = 10
        x_min, x_max = min(x), max(x)
        if x_max == x_min:
            return 0.0
        x_bin_size = (x_max - x_min) / x_bins
        y_unique = list(set(y))
        y_bins = len(y_unique)
        if y_bins < 2:
            return 0.0
        y_to_idx = {v: i for i, v in enumerate(y_unique)}
        joint: Counter = Counter()
        x_marg: Counter = Counter()
        y_marg: Counter = Counter()
        for xi, yi in zip(x, y):
            xi_bin = min(int((xi - x_min) / x_bin_size), x_bins - 1) if x_bin_size > 0 else 0
            yi_bin = y_to_idx.get(yi, 0)
            joint[(xi_bin, yi_bin)] += 1
            x_marg[xi_bin] += 1
            y_marg[yi_bin] += 1
        mi = 0.0
        for (xi_bin, yi_bin), joint_count in joint.items():
            p_xy = joint_count / n
            p_x = x_marg[xi_bin] / n
            p_y = y_marg[yi_bin] / n
            if p_xy > 0 and p_x > 0 and p_y > 0:
                mi += p_xy * math.log2(p_xy / (p_x * p_y))
        return mi

    def _pearson(self, x: List[float], y: List[float]) -> float:
        n = len(x)
        if n < 3:
            return 0.0
        try:
            mean_x = statistics.mean(x)
            mean_y = statistics.mean(y)
            std_x = statistics.stdev(x)
            std_y = statistics.stdev(y)
            if std_x == 0 or std_y == 0:
                return 0.0
            cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (n - 1)
            return max(-1.0, min(1.0, cov / (std_x * std_y)))
        except (statistics.StatisticsError, ZeroDivisionError):
            return 0.0

    def _update_feature_stats(self, vector: FeatureVector) -> None:
        for name, feature in vector.features.items():
            if name not in self.feature_stats:
                self.feature_stats[name] = FeatureStatistics(
                    feature_name=name, count=0, mean=0.0, std=0.0,
                    min_val=feature.value, max_val=feature.value,
                    q25=0.0, q50=0.0, q75=0.0, missing_count=0, variance=0.0
                )
            stat = self.feature_stats[name]
            stat.count += 1
            stat.min_val = min(stat.min_val, feature.value)
            stat.max_val = max(stat.max_val, feature.value)

    def compute_feature_statistics(self, vectors: Optional[List[FeatureVector]] = None) -> Dict[str, FeatureStatistics]:
        if vectors:
            all_values: Dict[str, List[float]] = defaultdict(list)
            for v in vectors:
                for name, f in v.features.items():
                    if not math.isnan(f.value) and not math.isinf(f.value):
                        all_values[name].append(f.value)
            for name, values in all_values.items():
                if len(values) < 2:
                    continue
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                mean = statistics.mean(values)
                try:
                    std = statistics.stdev(values)
                    variance = std ** 2
                except statistics.StatisticsError:
                    std = 0.0
                    variance = 0.0
                self.feature_stats[name] = FeatureStatistics(
                    feature_name=name, count=n, mean=mean, std=std,
                    min_val=sorted_vals[0], max_val=sorted_vals[-1],
                    q25=sorted_vals[n // 4], q50=statistics.median(values),
                    q75=sorted_vals[3 * n // 4],
                    missing_count=0, variance=variance
                )
        return dict(self.feature_stats)

    def get_statistics(self) -> Dict:
        return {
            'total_extractions': self.extraction_count,
            'registered_features': len(self.feature_definitions),
            'features_by_type': {
                ft.value: len([d for d in self.feature_definitions.values() if d.feature_type == ft])
                for ft in FeatureType
            },
            'features_by_category': {
                fc.value: len([d for d in self.feature_definitions.values() if d.category == fc])
                for fc in FeatureCategory
            },
            'normalization_method': self.config.normalization_method,
            'cache_size': len(self.feature_cache),
            'feature_stats_count': len(self.feature_stats),
            'normalization_params_count': len(self.normalization_params),
            'config': {
                'enable_text_features': self.config.enable_text_features,
                'enable_statistical_features': self.config.enable_statistical_features,
                'enable_structural_features': self.config.enable_structural_features,
                'enable_content_features': self.config.enable_content_features,
                'variance_threshold': self.config.variance_threshold,
                'max_features': self.config.max_features,
                'correlation_threshold': self.config.correlation_threshold,
                'sentiment_enabled': self.config.sentiment_enabled,
                'readability_enabled': self.config.readability_enabled,
            }
        }

    def export_config(self) -> Dict:
        defs = {}
        for name, defn in self.feature_definitions.items():
            defs[name] = {
                'name': defn.name,
                'feature_type': defn.feature_type.value,
                'category': defn.category.value,
                'extractor': defn.extractor,
                'description': defn.description,
                'is_categorical': defn.is_categorical,
                'weight': defn.weight,
            }
        return {
            'config': asdict(self.config),
            'feature_definitions': defs,
            'normalization_params': {
                k: {sk: sv for sk, sv in v.items()}
                for k, v in self.normalization_params.items()
            },
            'exported_at': datetime.now().isoformat(),
        }

    def import_config(self, data: Dict) -> int:
        count = 0
        if 'config' in data:
            self.config = FeatureConfig(**{k: v for k, v in data['config'].items()
                                            if k in FeatureConfig.__dataclass_fields__})
            count += 1
        if 'feature_definitions' in data:
            for name, defn_data in data['feature_definitions'].items():
                defn_data['feature_type'] = FeatureType(defn_data['feature_type'])
                defn_data['category'] = FeatureCategory(defn_data['category'])
                self.feature_definitions[name] = FeatureDefinition(**defn_data)
                count += 1
        if 'normalization_params' in data:
            self.normalization_params = data['normalization_params']
            count += 1
        logger.info(f"Imported {count} feature config items")
        return count

    def reset(self) -> None:
        self.feature_cache.clear()
        self.normalization_params.clear()
        self.feature_stats.clear()
        self.extraction_count = 0
        logger.info("FeatureExtractor reset")
