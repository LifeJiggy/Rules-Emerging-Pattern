"""Content validation for input data with encoding, pattern, caching, and batch processing."""

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict, defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

logger = logging.getLogger(__name__)


class SeverityLevel(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ContentType(str, Enum):
    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"
    JSON = "json"
    XML = "xml"
    YAML = "yaml"
    CODE = "code"
    URL = "url"
    EMAIL = "email"
    BINARY = "binary"
    MARKUP = "markup"
    CONFIG = "config"
    LOG = "log"
    TEMPLATE = "template"


class EncodingType(str, Enum):
    UTF_8 = "utf-8"
    UTF_16 = "utf-16"
    UTF_16_BE = "utf-16-be"
    UTF_16_LE = "utf-16-le"
    ASCII = "ascii"
    ISO_8859_1 = "iso-8859-1"
    WINDOWS_1252 = "windows-1252"
    LATIN_1 = "latin-1"
    CP437 = "cp437"
    UNKNOWN = "unknown"


@dataclass
class ValidationError:
    field: str
    message: str
    severity: SeverityLevel = SeverityLevel.ERROR
    code: Optional[str] = None
    position_start: Optional[int] = None
    position_end: Optional[int] = None
    line: Optional[int] = None
    column: Optional[int] = None
    suggestion: Optional[str] = None
    rule_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity.value,
            "code": self.code,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "line": self.line,
            "column": self.column,
            "suggestion": self.suggestion,
            "rule_name": self.rule_name,
        }


@dataclass
class ContentProfile:
    length: int = 0
    word_count: int = 0
    line_count: int = 0
    encoding: EncodingType = EncodingType.UTF_8
    has_html: bool = False
    has_urls: bool = False
    has_emails: bool = False
    character_set: Optional[str] = None
    entropy: float = 0.0
    content_type: Optional[str] = None
    language: Optional[str] = None
    readability_score: float = 0.0
    has_code: bool = False
    null_byte_count: int = 0
    non_ascii_count: int = 0
    unique_chars: int = 0
    avg_word_length: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "length": self.length,
            "word_count": self.word_count,
            "line_count": self.line_count,
            "encoding": self.encoding.value,
            "has_html": self.has_html,
            "has_urls": self.has_urls,
            "has_emails": self.has_emails,
            "character_set": self.character_set,
            "entropy": round(self.entropy, 4),
            "content_type": self.content_type,
            "language": self.language,
            "readability_score": round(self.readability_score, 2),
            "has_code": self.has_code,
            "null_byte_count": self.null_byte_count,
            "non_ascii_count": self.non_ascii_count,
            "unique_chars": self.unique_chars,
            "avg_word_length": round(self.avg_word_length, 2),
        }


@dataclass
class ContentRule:
    name: str
    description: str
    severity: SeverityLevel = SeverityLevel.ERROR
    enabled: bool = True
    exempt_content_types: List[str] = field(default_factory=list)

    def is_applicable(self, content_type: str) -> bool:
        return content_type not in self.exempt_content_types


class ContentValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._max_content_length = self.config.get("max_length", 100000)
        self._min_content_length = self.config.get("min_length", 1)
        self._default_content_type = ContentType.TEXT
        self._forbidden_patterns: List[Pattern] = self._compile_patterns([
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"on\w+\s*=",
            r"document\.(cookie|domain|write|location)",
            r"window\.(location|open|eval)",
            r"eval\s*\(",
            r"new\s+Function\s*\(",
            r"<\s*script[\s>]",
            r"vbscript:",
            r"data:\s*text/html",
            r"expression\s*\(",
        ])
        self._allowed_html_tags: Set[str] = {
            "p", "br", "b", "i", "u", "em", "strong", "a", "ul",
            "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
            "blockquote", "pre", "code", "span", "div", "img",
            "table", "tr", "td", "th", "thead", "tbody", "caption",
        }
        self._content_rules: Dict[str, ContentRule] = {}
        self._encoding_detectors: Dict[str, Callable[[str], bool]] = {}
        self._custom_patterns: Dict[str, Pattern] = {}
        self._cache: OrderedDict = OrderedDict()
        self._cache_max_size: int = self.config.get("cache_max_size", 500)
        self._cache_ttl: int = self.config.get("cache_ttl_seconds", 300)
        self._stats: Counter = Counter()
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._profile_history: List[ContentProfile] = []
        self._profile_history_max: int = self.config.get("profile_history", 100)
        self._max_null_bytes: int = self.config.get("max_null_bytes", 5)
        self._max_non_ascii_ratio: float = self.config.get("max_non_ascii_ratio", 0.5)
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_size: int = self.config.get("audit_max_size", 500)
        self._type_specific_rules: Dict[str, List[Callable]] = defaultdict(list)

        self._init_content_rules()
        self._init_encoding_detectors()
        self._init_type_specific_rules()
        logger.info(
            f"ContentValidator initialized with {len(self._forbidden_patterns)} "
            f"forbidden patterns"
        )

    def _compile_patterns(self, patterns: List[str]) -> List[Pattern]:
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE | re.DOTALL))
            except re.error as e:
                logger.warning(f"Failed to compile pattern '{p}': {e}")
        return compiled

    def _init_content_rules(self) -> None:
        self._content_rules["no_empty_content"] = ContentRule(
            name="no_empty_content",
            description="Content must not be empty",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["length_constraints"] = ContentRule(
            name="length_constraints",
            description="Content must meet length constraints",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["no_forbidden_patterns"] = ContentRule(
            name="no_forbidden_patterns",
            description="Content must not contain forbidden patterns",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["valid_encoding"] = ContentRule(
            name="valid_encoding",
            description="Content must have valid encoding",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["valid_urls"] = ContentRule(
            name="valid_urls",
            description="URLs in content must be valid",
            severity=SeverityLevel.WARNING,
        )
        self._content_rules["no_sql_injection"] = ContentRule(
            name="no_sql_injection",
            description="Content must not contain SQL injection patterns",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["no_path_traversal"] = ContentRule(
            name="no_path_traversal",
            description="Content must not contain path traversal patterns",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["no_command_injection"] = ContentRule(
            name="no_command_injection",
            description="Content must not contain command injection patterns",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["no_null_bytes"] = ContentRule(
            name="no_null_bytes",
            description="Content must not contain excessive null bytes",
            severity=SeverityLevel.WARNING,
        )
        self._content_rules["valid_character_set"] = ContentRule(
            name="valid_character_set",
            description="Content character set must be valid",
            severity=SeverityLevel.WARNING,
        )
        self._content_rules["no_xml_external"] = ContentRule(
            name="no_xml_external",
            description="Content must not contain XML external entity references",
            severity=SeverityLevel.ERROR,
        )
        self._content_rules["no_nosql_injection"] = ContentRule(
            name="no_nosql_injection",
            description="Content must not contain NoSQL injection patterns",
            severity=SeverityLevel.ERROR,
        )

    def _init_encoding_detectors(self) -> None:
        self._encoding_detectors["utf-8"] = self._detect_utf8
        self._encoding_detectors["ascii"] = self._detect_ascii
        self._encoding_detectors["utf-16"] = self._detect_utf16
        self._encoding_detectors["utf-16-be"] = self._detect_utf16_be
        self._encoding_detectors["utf-16-le"] = self._detect_utf16_le
        self._encoding_detectors["iso-8859-1"] = self._detect_iso8859_1
        self._encoding_detectors["windows-1252"] = self._detect_windows1252

    def _init_type_specific_rules(self) -> None:
        self.register_type_rule("json", self._validate_json)
        self.register_type_rule("xml", self._validate_xml)
        self.register_type_rule("yaml", self._validate_yaml)
        self.register_type_rule("html", self._validate_html)
        self.register_type_rule("markdown", self._validate_markdown)
        self.register_type_rule("code", self._validate_code)
        self.register_type_rule("url", self._validate_url_content)
        self.register_type_rule("email", self._validate_email_content)
        self.register_type_rule("template", self._validate_template)

    def register_type_rule(self, content_type: str, rule_func: Callable) -> None:
        self._type_specific_rules[content_type].append(rule_func)

    def unregister_type_rule(self, content_type: str, rule_func: Callable) -> bool:
        if rule_func in self._type_specific_rules.get(content_type, []):
            self._type_specific_rules[content_type].remove(rule_func)
            return True
        return False

    def validate_content(
        self,
        content: str,
        content_type: str = "text",
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[ValidationError]]:
        start_time = time.perf_counter()
        options = options or {}
        errors: List[ValidationError] = []

        cache_key = self._build_cache_key(content, content_type, options)
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached

        self._trigger_callbacks("before_validate", content, content_type, options)

        if not content or not content.strip():
            error = ValidationError(
                field="content",
                message="Content cannot be empty",
                severity=SeverityLevel.ERROR,
                code="EMPTY_CONTENT",
                rule_name="no_empty_content",
            )
            errors.append(error)
            result = (False, errors)
            self._set_cached(cache_key, result)
            return result

        profile = self._profile_content(content)
        self._stats["profile_count"] += 1

        length_valid, length_errors = self._validate_length(content, options)
        errors.extend(length_errors)

        pattern_valid, pattern_errors = self._validate_forbidden_patterns(content)
        errors.extend(pattern_errors)

        encoding_valid, encoding_errors = self._validate_encoding(content)
        errors.extend(encoding_errors)

        injection_valid, injection_errors = self._validate_injection_patterns(content)
        errors.extend(injection_errors)

        url_valid, url_errors = self._validate_urls(content)
        errors.extend(url_errors)

        null_byte_valid, null_byte_errors = self._validate_null_bytes(content)
        errors.extend(null_byte_errors)

        char_set_valid, char_set_errors = self._validate_character_set(content)
        errors.extend(char_set_errors)

        for rule_fn in self._type_specific_rules.get(content_type, []):
            try:
                te, tv = rule_fn(content)
                errors.extend(te)
            except Exception as e:
                logger.warning(f"Type-specific rule for '{content_type}' failed: {e}")

        custom_valid, custom_errors = self._validate_custom_rules(content, content_type)
        errors.extend(custom_valid)

        is_valid = len([e for e in errors if e.severity == SeverityLevel.ERROR]) == 0

        self._stats["total_validations"] += 1
        if not is_valid:
            self._stats["validation_failures"] += 1
            logger.debug(f"Content validation failed with {len(errors)} errors")

        self._trigger_callbacks("after_validate", content, content_type, options, errors, is_valid)

        result = (is_valid, errors)
        self._set_cached(cache_key, result)

        elapsed = (time.perf_counter() - start_time) * 1000
        self._stats["total_time_ms"] += elapsed

        return result

    def _profile_content(self, content: str) -> ContentProfile:
        profile = ContentProfile()
        profile.length = len(content)
        words = content.split()
        profile.word_count = len(words)
        profile.line_count = content.count("\n") + 1
        profile.encoding = self._detect_encoding(content)
        profile.has_html = bool(re.search(r"<[a-zA-Z][^>]*>", content))
        profile.has_urls = bool(re.search(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", content))
        profile.has_emails = bool(re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content))
        profile.entropy = self._calculate_entropy(content)
        profile.has_code = bool(re.search(
            r"(def |class |function |var |let |const |import |from |public |private )", content
        ))
        profile.null_byte_count = content.count("\x00")
        non_ascii = sum(1 for c in content if ord(c) > 127)
        profile.non_ascii_count = non_ascii
        profile.unique_chars = len(set(content))
        if words:
            profile.avg_word_length = sum(len(w) for w in words) / len(words)
        self._profile_history.append(profile)
        if len(self._profile_history) > self._profile_history_max:
            self._profile_history.pop(0)
        return profile

    def _calculate_entropy(self, content: str) -> float:
        if not content:
            return 0.0
        byte_data = content.encode("utf-8")
        length = len(byte_data)
        freq: Dict[int, int] = defaultdict(int)
        for byte in byte_data:
            freq[byte] += 1
        import math
        entropy = 0.0
        for count in freq.values():
            p = count / length
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def _detect_encoding(self, content: str) -> EncodingType:
        for name, detector in self._encoding_detectors.items():
            if detector(content):
                try:
                    return EncodingType(name)
                except ValueError:
                    pass
        try:
            content.encode("utf-8")
            return EncodingType.UTF_8
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        try:
            content.encode("ascii")
            return EncodingType.ASCII
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        try:
            content.encode("latin-1")
            return EncodingType.LATIN_1
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return EncodingType.UNKNOWN

    def _detect_utf8(self, content: str) -> bool:
        try:
            encoded = content.encode("utf-8")
            decoded = encoded.decode("utf-8")
            return decoded == content
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_ascii(self, content: str) -> bool:
        try:
            content.encode("ascii")
            return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_utf16(self, content: str) -> bool:
        try:
            encoded = content.encode("utf-16")
            decoded = encoded.decode("utf-16")
            return decoded == content
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_utf16_be(self, content: str) -> bool:
        try:
            encoded = content.encode("utf-16-be")
            decoded = encoded.decode("utf-16-be")
            return decoded == content
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_utf16_le(self, content: str) -> bool:
        try:
            encoded = content.encode("utf-16-le")
            decoded = encoded.decode("utf-16-le")
            return decoded == content
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_iso8859_1(self, content: str) -> bool:
        try:
            content.encode("iso-8859-1")
            return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _detect_windows1252(self, content: str) -> bool:
        try:
            content.encode("windows-1252")
            return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False

    def _validate_length(
        self,
        content: str,
        options: Dict[str, Any],
    ) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        max_length = options.get("max_length", self._max_content_length)
        min_length = options.get("min_length", self._min_content_length)
        content_length = len(content)

        if content_length < min_length:
            errors.append(ValidationError(
                field="content",
                message=f"Content too short: {content_length} chars (min: {min_length})",
                severity=SeverityLevel.ERROR,
                code="CONTENT_TOO_SHORT",
                rule_name="length_constraints",
            ))

        if content_length > max_length:
            errors.append(ValidationError(
                field="content",
                message=f"Content too long: {content_length} chars (max: {max_length})",
                severity=SeverityLevel.ERROR,
                code="CONTENT_TOO_LONG",
                rule_name="length_constraints",
            ))

        word_count = len(content.split())
        max_words = options.get("max_words", 0)
        if max_words > 0 and word_count > max_words:
            errors.append(ValidationError(
                field="content",
                message=f"Content has {word_count} words (max: {max_words})",
                severity=SeverityLevel.WARNING,
                code="TOO_MANY_WORDS",
                rule_name="length_constraints",
            ))

        return len(errors) == 0, errors

    def _validate_forbidden_patterns(
        self, content: str,
    ) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        for pattern in self._forbidden_patterns:
            for match in pattern.finditer(content):
                start = match.start()
                line = content[:start].count("\n") + 1
                col = start - content[:start].rfind("\n")
                matched = match.group()
                errors.append(ValidationError(
                    field="content",
                    message=f"Forbidden pattern detected: {matched[:80]}{'...' if len(matched) > 80 else ''}",
                    severity=SeverityLevel.ERROR,
                    code="FORBIDDEN_PATTERN",
                    position_start=start,
                    position_end=match.end(),
                    line=line,
                    column=col,
                    rule_name=pattern.pattern[:40],
                ))
        return len(errors) == 0, errors

    def _validate_encoding(
        self, content: str,
    ) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        try:
            content.encode("utf-8")
        except UnicodeEncodeError as e:
            errors.append(ValidationError(
                field="content",
                message=f"Invalid UTF-8 encoding at position {e.start}: {e.reason}",
                severity=SeverityLevel.ERROR,
                code="INVALID_ENCODING",
                position_start=e.start,
                position_end=e.end,
                rule_name="valid_encoding",
            ))
        return len(errors) == 0, errors

    def _validate_injection_patterns(
        self, content: str,
    ) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []

        sql_patterns = [
            (r"(\bSELECT\b.*\bFROM\b|\bINSERT\b.*\bINTO\b|\bDROP\b.*\bTABLE\b|\bDELETE\b.*\bFROM\b|\bUNION\b.*\bSELECT\b)", "SQL_INJECTION"),
            (r"('|\")\s*(OR|AND)\s+('|\")\s*=\s*('|\")", "SQL_INJECTION_COND"),
            (r"(--|#|\/\*).*$", "SQL_COMMENT"),
            (r"exec\s*\(.*\)|xp_cmdshell|sp_executesql", "SQL_DANGEROUS"),
        ]
        for sql_regex, code in sql_patterns:
            for match in re.finditer(sql_regex, content, re.IGNORECASE):
                errors.append(ValidationError(
                    field="content",
                    message=f"Potential SQL injection detected ({code})",
                    severity=SeverityLevel.ERROR,
                    code=code,
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="no_sql_injection",
                ))

        nosql_patterns = [
            (r"\$where\s*:", "NOSQL_WHERE"),
            (r"\$ne\s*:", "NOSQL_NE"),
            (r"\$gt\s*:", "NOSQL_GT"),
            (r"\$regex\s*:", "NOSQL_REGEX"),
        ]
        for nosql_regex, code in nosql_patterns:
            for match in re.finditer(nosql_regex, content, re.IGNORECASE):
                errors.append(ValidationError(
                    field="content",
                    message=f"Potential NoSQL injection detected ({code})",
                    severity=SeverityLevel.ERROR,
                    code=code,
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="no_nosql_injection",
                ))

        path_patterns = [
            (r"\.\./", "PATH_TRAVERSAL"),
            (r"\.\.\\\\", "PATH_TRAVERSAL_WIN"),
            (r"/etc/passwd", "ETC_PASSWD"),
            (r"\.\./\.\./", "DEEP_TRAVERSAL"),
        ]
        for pt_regex, code in path_patterns:
            if re.search(pt_regex, content, re.IGNORECASE):
                errors.append(ValidationError(
                    field="content",
                    message=f"Potential path traversal detected ({code})",
                    severity=SeverityLevel.ERROR,
                    code=code,
                    rule_name="no_path_traversal",
                ))

        cmd_patterns = [
            (r"[`$]\s*\(.*\)", "COMMAND_SUBSTITUTION"),
            (r"\|.*(sh|bash|cmd|powershell|python|perl|ruby)\s", "PIPE_COMMAND"),
            (r"&&.*(del|rm|format|shutdown|reboot)", "CHAINED_COMMAND"),
            (r";(.*(rm|del|format|wget|curl))", "SEMICOLON_COMMAND"),
        ]
        for cmd_regex, code in cmd_patterns:
            match = re.search(cmd_regex, content, re.IGNORECASE)
            if match:
                errors.append(ValidationError(
                    field="content",
                    message=f"Potential command injection detected ({code})",
                    severity=SeverityLevel.ERROR,
                    code=code,
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="no_command_injection",
                ))

        return len(errors) == 0, errors

    def _validate_urls(self, content: str) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        url_pattern = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)", re.IGNORECASE)
        for match in url_pattern.finditer(content):
            url = match.group()
            if len(url) > 2000:
                errors.append(ValidationError(
                    field="content",
                    message=f"URL exceeds maximum length (2000 chars): {url[:50]}...",
                    severity=SeverityLevel.WARNING,
                    code="URL_TOO_LONG",
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="valid_urls",
                ))
        return len(errors) == 0, errors

    def _validate_null_bytes(self, content: str) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        null_count = content.count("\x00")
        if null_count > self._max_null_bytes:
            for i, c in enumerate(content):
                if c == "\x00":
                    errors.append(ValidationError(
                        field="content",
                        message=f"Null byte detected at position {i}",
                        severity=SeverityLevel.WARNING,
                        code="NULL_BYTE",
                        position_start=i,
                        position_end=i + 1,
                        rule_name="no_null_bytes",
                    ))
                    if len(errors) >= self._max_null_bytes:
                        break
        return len(errors) == 0, errors

    def _validate_character_set(self, content: str) -> Tuple[bool, List[ValidationError]]:
        errors: List[ValidationError] = []
        if len(content) == 0:
            return True, errors
        non_ascii = sum(1 for c in content if ord(c) > 127)
        ratio = non_ascii / len(content)
        if ratio > self._max_non_ascii_ratio:
            errors.append(ValidationError(
                field="content",
                message=f"High non-ASCII character ratio: {ratio:.1%} (max: {self._max_non_ascii_ratio:.0%})",
                severity=SeverityLevel.WARNING,
                code="HIGH_NON_ASCII",
                rule_name="valid_character_set",
            ))
        return len(errors) == 0, errors

    def _validate_html(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        tags = re.findall(r"<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?>", content)
        open_tags: List[str] = []
        self_closing = {"br", "hr", "img", "input", "meta", "link"}

        for tag_match in re.finditer(r"<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?>", content):
            full_tag = tag_match.group()
            tag_name = tag_match.group(1).lower()
            line = content[:tag_match.start()].count("\n") + 1

            if tag_name not in self._allowed_html_tags:
                errors.append(ValidationError(
                    field="content",
                    message=f"HTML tag '{tag_name}' is not allowed",
                    severity=SeverityLevel.WARNING,
                    code="DISALLOWED_HTML_TAG",
                    line=line,
                    rule_name="no_forbidden_patterns",
                ))

            if full_tag.startswith("</"):
                if open_tags and open_tags[-1] == tag_name:
                    open_tags.pop()
                else:
                    errors.append(ValidationError(
                        field="content",
                        message=f"Unexpected closing tag </{tag_name}>",
                        severity=SeverityLevel.WARNING,
                        code="UNEXPECTED_CLOSING_TAG",
                        line=line,
                        rule_name="no_forbidden_patterns",
                    ))
            elif tag_name not in self_closing and not full_tag.endswith("/>"):
                open_tags.append(tag_name)

        for unclosed in open_tags:
            errors.append(ValidationError(
                field="content",
                message=f"Unclosed HTML tag <{unclosed}>",
                severity=SeverityLevel.WARNING,
                code="UNCLOSED_HTML_TAG",
                rule_name="no_forbidden_patterns",
            ))

        script_pattern = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
        for match in script_pattern.finditer(content):
            errors.append(ValidationError(
                field="content",
                message="Script tags are not allowed",
                severity=SeverityLevel.ERROR,
                code="SCRIPT_TAG",
                position_start=match.start(),
                position_end=match.end(),
                rule_name="no_forbidden_patterns",
            ))

        return errors, len(errors) == 0

    def _validate_json(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            line_num = e.lineno if e.lineno else 0
            col_num = e.colno if e.colno else 0
            errors.append(ValidationError(
                field="content",
                message=f"Invalid JSON: {e.msg} at line {line_num}, col {col_num}",
                severity=SeverityLevel.ERROR,
                code="INVALID_JSON",
                line=line_num,
                column=col_num,
                rule_name="no_forbidden_patterns",
            ))
        return errors, len(errors) == 0

    def _validate_xml(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(content)
        except ET.ParseError as e:
            pos = getattr(e, "position", (0, 0))
            errors.append(ValidationError(
                field="content",
                message=f"Invalid XML: {e}",
                severity=SeverityLevel.ERROR,
                code="INVALID_XML",
                line=pos[0] if pos else None,
                column=pos[1] if pos else None,
                rule_name="no_forbidden_patterns",
            ))

        xxe_pattern = re.compile(r"<!ENTITY\s+|<!DOCTYPE\s+[^>]*\[", re.IGNORECASE)
        if xxe_pattern.search(content):
            errors.append(ValidationError(
                field="content",
                message="Potential XML external entity (XXE) reference detected",
                severity=SeverityLevel.ERROR,
                code="XXE_DETECTED",
                rule_name="no_xml_external",
            ))
        return errors, len(errors) == 0

    def _validate_yaml(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        try:
            import yaml
            yaml.safe_load(content)
        except ImportError:
            pass
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            line = mark.line + 1 if mark else None
            errors.append(ValidationError(
                field="content",
                message=f"Invalid YAML: {e}",
                severity=SeverityLevel.ERROR,
                code="INVALID_YAML",
                line=line,
                rule_name="no_forbidden_patterns",
            ))
        return errors, len(errors) == 0

    def _validate_markdown(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if re.match(r"^#{7,}\s+", line):
                errors.append(ValidationError(
                    field="content",
                    message=f"Heading level too deep at line {i}",
                    severity=SeverityLevel.WARNING,
                    code="DEEP_HEADING",
                    line=i,
                    rule_name="no_forbidden_patterns",
                ))

            unsafe_html = re.findall(
                r"<(script|iframe|embed|object|applet)[^>]*>", line, re.IGNORECASE
            )
            for tag in unsafe_html:
                errors.append(ValidationError(
                    field="content",
                    message=f"Unsafe HTML tag '<{tag}>' in markdown at line {i}",
                    severity=SeverityLevel.ERROR,
                    code="UNSAFE_HTML_IN_MARKDOWN",
                    line=i,
                    rule_name="no_forbidden_patterns",
                ))

        return errors, len(errors) == 0

    def _validate_code(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        dangerous_patterns = [
            (r"(os\.system|subprocess\.call|subprocess\.Popen|exec\s*\()", "DANGEROUS_FUNCTION"),
            (r"(__import__|__builtins__|__class__|__subclasses__)", "MAGIC_METHOD"),
            (r"(pickle\.loads|marshal\.loads|shelve\.open)", "UNSAFE_DESERIALIZATION"),
            (r"(base64\.b64decode.*exec|eval.*input|exec.*input)", "CODE_EXECUTION"),
            (r"(compile|exec)\s*\(.*\)", "DYNAMIC_CODE"),
        ]
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            for code_regex, code in dangerous_patterns:
                match = re.search(code_regex, line, re.IGNORECASE)
                if match:
                    errors.append(ValidationError(
                        field="content",
                        message=f"Potentially dangerous code pattern: {code}",
                        severity=SeverityLevel.WARNING,
                        code=code,
                        line=i,
                        position_start=match.start(),
                        position_end=match.end(),
                        rule_name="no_forbidden_patterns",
                    ))
        return errors, len(errors) == 0

    def _validate_url_content(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        url_pattern = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
        for match in url_pattern.finditer(content):
            url = match.group()
            if not re.match(r"^https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", url):
                errors.append(ValidationError(
                    field="content",
                    message=f"Malformed URL: {url[:60]}",
                    severity=SeverityLevel.WARNING,
                    code="MALFORMED_URL",
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="valid_urls",
                ))
        return errors, len(errors) == 0

    def _validate_email_content(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        for match in email_pattern.finditer(content):
            email = match.group()
            if len(email) > 254:
                errors.append(ValidationError(
                    field="content",
                    message=f"Email address exceeds maximum length (254 chars)",
                    severity=SeverityLevel.INFO,
                    code="EMAIL_TOO_LONG",
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name="valid_urls",
                ))
        return errors, len(errors) == 0

    def _validate_template(self, content: str) -> Tuple[List[ValidationError], bool]:
        errors: List[ValidationError] = []
        template_injection = re.findall(
            r"\{\{.*?\}\}|{%\s*.*?\s*%}", content
        )
        for i, inj in enumerate(template_injection):
            if re.search(r"(exec|eval|import|os|subprocess|__)", inj):
                errors.append(ValidationError(
                    field="content",
                    message=f"Potential SSTI in template expression at position ~{content.find(inj)}",
                    severity=SeverityLevel.ERROR,
                    code="SSTI_DETECTED",
                    rule_name="no_forbidden_patterns",
                ))
                if len(errors) >= 3:
                    break
        return errors, len(errors) == 0

    def _validate_custom_rules(
        self, content: str, content_type: str,
    ) -> Tuple[List[ValidationError], List[ValidationError]]:
        errors: List[ValidationError] = []
        custom_errors: List[ValidationError] = []
        for rule_name, pattern in self._custom_patterns.items():
            for match in pattern.finditer(content):
                errors.append(ValidationError(
                    field="content",
                    message=f"Custom rule '{rule_name}' matched: {match.group()[:80]}",
                    severity=SeverityLevel.ERROR,
                    code=f"CUSTOM_RULE_{rule_name.upper()}",
                    position_start=match.start(),
                    position_end=match.end(),
                    rule_name=rule_name,
                ))
        return errors, custom_errors

    def _build_cache_key(self, content: str, content_type: str, options: Dict[str, Any]) -> str:
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        opt_hash = hashlib.md5(str(sorted(options.items())).encode()).hexdigest()[:8]
        return f"{content_type}:{content_hash}:{opt_hash}"

    def _get_cached(self, key: str) -> Optional[Tuple[bool, List[ValidationError]]]:
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                self._cache.move_to_end(key)
                return result
            del self._cache[key]
        return None

    def _set_cached(self, key: str, result: Tuple[bool, List[ValidationError]]) -> None:
        self._cache[key] = (result, time.time())
        if len(self._cache) > self._cache_max_size:
            self._cache.popitem(last=False)

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Callback for event '{event}' failed: {e}")

    def add_forbidden_pattern(self, pattern: str) -> None:
        try:
            compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
            self._forbidden_patterns.append(compiled)
            logger.info(f"Added forbidden pattern: {pattern[:50]}...")
        except re.error as e:
            logger.error(f"Invalid regex pattern '{pattern}': {e}")
            raise ValueError(f"Invalid regex pattern: {e}")

    def remove_forbidden_pattern(self, pattern: str) -> bool:
        for i, p in enumerate(self._forbidden_patterns):
            if p.pattern == pattern:
                self._forbidden_patterns.pop(i)
                logger.info(f"Removed forbidden pattern: {pattern[:50]}...")
                return True
        return False

    def add_custom_rule(self, name: str, pattern: str) -> None:
        try:
            compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
            self._custom_patterns[name] = compiled
            logger.info(f"Added custom rule '{name}'")
        except re.error as e:
            logger.error(f"Invalid regex for rule '{name}': {e}")
            raise ValueError(f"Invalid regex: {e}")

    def remove_custom_rule(self, name: str) -> bool:
        if name in self._custom_patterns:
            del self._custom_patterns[name]
            logger.info(f"Removed custom rule '{name}'")
            return True
        return False

    def get_custom_rules(self) -> Dict[str, str]:
        return {name: p.pattern for name, p in self._custom_patterns.items()}

    def register_callback(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> bool:
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
            return True
        return False

    def set_content_limits(self, min_length: int, max_length: int) -> None:
        self._min_content_length = min_length
        self._max_content_length = max_length
        logger.info(f"Content limits set to min={min_length}, max={max_length}")

    def get_content_limits(self) -> Dict[str, int]:
        return {
            "min_length": self._min_content_length,
            "max_length": self._max_content_length,
        }

    def get_stats(self) -> Dict[str, Any]:
        total = self._stats.get("total_validations", 0)
        failures = self._stats.get("validation_failures", 0)
        return {
            "total_validations": total,
            "validation_failures": failures,
            "failure_rate": round(failures / total, 4) if total > 0 else 0.0,
            "cache_hits": self._stats.get("cache_hits", 0),
            "cache_size": len(self._cache),
            "profiles_collected": self._stats.get("profile_count", 0),
            "total_time_ms": round(self._stats.get("total_time_ms", 0), 2),
            "forbidden_patterns_count": len(self._forbidden_patterns),
            "custom_rules_count": len(self._custom_patterns),
            "callbacks_registered": sum(len(v) for v in self._callbacks.values()),
            "profile_history_size": len(self._profile_history),
        }

    def reset_stats(self) -> None:
        self._stats.clear()
        logger.info("Content validation stats reset")

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Validation cache cleared")

    def validate_batch(
        self,
        contents: List[str],
        content_type: str = "text",
        options: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> List[Tuple[bool, List[ValidationError]]]:
        if parallel:
            return self._validate_batch_parallel(contents, content_type, options, max_workers)
        results = []
        for i, content in enumerate(contents):
            logger.debug(f"Validating content item {i + 1}/{len(contents)}")
            is_valid, errors = self.validate_content(content, content_type, options)
            results.append((is_valid, errors))
        return results

    def _validate_batch_parallel(
        self,
        contents: List[str],
        content_type: str,
        options: Optional[Dict[str, Any]],
        max_workers: int,
    ) -> List[Tuple[bool, List[ValidationError]]]:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.validate_content, content, content_type, options): i
                for i, content in enumerate(contents)
            }
            ordered: List[Optional[Tuple[bool, List[ValidationError]]]] = [None] * len(contents)
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    ordered[idx] = future.result()
                except Exception as e:
                    logger.error(f"Batch item {idx} failed: {e}")
                    ordered[idx] = (False, [
                        ValidationError(
                            field="content",
                            message=f"Validation error: {str(e)}",
                            severity=SeverityLevel.ERROR,
                            code="BATCH_ERROR",
                        )
                    ])
        return [r for r in ordered if r is not None]

    def classify_content(self, content: str) -> str:
        if not content.strip():
            return "empty"
        try:
            json.loads(content)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
        if content.strip().startswith("<?xml") or (content.strip().startswith("<") and ">" in content):
            return "xml"
        if "<!DOCTYPE" in content.upper() or re.search(r"<(html|body|div|p|h[1-6])[^>]*>", content, re.IGNORECASE):
            return "html"
        if ":" in content.split("\n")[0] and "  " in content:
            return "yaml"
        if re.search(r"^#{1,6}\s+", content, re.MULTILINE):
            return "markdown"
        if re.search(r"(def |class |function |import |from |#include|package )", content):
            return "code"
        if re.match(r"^https?://", content.strip()):
            return "url"
        if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", content.strip()):
            return "email"
        return "text"

    def get_profile_history(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._profile_history]

    def get_encoding_stats(self) -> Counter:
        encodings: Counter = Counter()
        for profile in self._profile_history:
            encodings[profile.encoding.value] += 1
        return encodings

    def __repr__(self) -> str:
        return (
            f"ContentValidator(patterns={len(self._forbidden_patterns)}, "
            f"cache={len(self._cache)}, "
            f"checks={self._stats.get('total_validations', 0)})"
        )
