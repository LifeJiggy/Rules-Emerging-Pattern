"""Format validation for structured data including JSON, XML, YAML, Markdown, HTML, and CSV."""

import csv
import io
import json
import logging
import re
import time
import traceback
import xml.dom.minidom
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
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


class FormatType(str, Enum):
    JSON = "json"
    XML = "xml"
    YAML = "yaml"
    MARKDOWN = "markdown"
    HTML = "html"
    CSV = "csv"
    PLAIN_TEXT = "plain_text"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class FormatError:
    format_type: str
    message: str
    severity: Severity = Severity.ERROR
    line: Optional[int] = None
    column: Optional[int] = None
    rule_name: Optional[str] = None
    suggestion: Optional[str] = None
    position: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_type": self.format_type,
            "message": self.message,
            "severity": self.severity.value,
            "line": self.line,
            "column": self.column,
            "rule_name": self.rule_name,
            "suggestion": self.suggestion,
            "position": self.position,
        }


@dataclass
class MarkdownElement:
    type: str
    content: str
    level: Optional[int] = None
    line_number: int = 0


@dataclass
class HtmlTag:
    name: str
    attributes: Dict[str, str] = field(default_factory=dict)
    self_closing: bool = False
    line: int = 0


@dataclass
class FormatConfig:
    indent: int = 2
    encoding: str = "utf-8"
    allow_comments: bool = True
    strict: bool = False
    max_size_bytes: int = 10 * 1024 * 1024
    allowed_html_tags: Optional[Set[str]] = None
    allowed_html_attributes: Optional[Set[str]] = None
    markdown_max_heading_level: int = 6
    csv_delimiter: str = ","
    csv_quotechar: str = '"'
    csv_strict: bool = False
    yaml_loader: str = "safe"
    xml_validate_dtd: bool = False
    max_nesting_depth: int = 50
    json_allow_trailing_comma: bool = False
    json_allow_comments: bool = False
    markdown_require_blank_after_heading: bool = False
    html_require_doctype: bool = False
    csv_require_header: bool = True
    xml_require_root: bool = True


class FormatValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = FormatConfig()
        self._schema_validators: Dict[str, Dict[str, Any]] = {}
        self._custom_validators: Dict[str, Callable] = {}
        self._stats: Dict[str, Counter] = defaultdict(Counter)
        self._allowed_html_tags: Set[str] = {
            "a", "abbr", "article", "b", "blockquote", "br",
            "caption", "cite", "code", "col", "colgroup", "dd",
            "del", "details", "dfn", "div", "dl", "dt", "em",
            "figcaption", "figure", "footer", "h1", "h2", "h3",
            "h4", "h5", "h6", "header", "hr", "i", "img", "ins",
            "kbd", "li", "link", "main", "mark", "nav", "ol",
            "p", "pre", "q", "s", "samp", "section", "small",
            "span", "strong", "sub", "summary", "sup", "table",
            "tbody", "td", "tfoot", "th", "thead", "time", "tr",
            "u", "ul", "var",
        }
        self._allowed_html_attributes: Set[str] = {
            "href", "src", "alt", "title", "class", "id", "style",
            "width", "height", "target", "rel", "type", "name",
            "value", "placeholder", "disabled", "readonly", "checked",
            "selected", "lang", "dir", "hidden", "tabindex",
        }
        self._format_detectors: Dict[str, Callable[[str], float]] = {}
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_size: int = 1000
        self._cache: OrderedDict = OrderedDict()
        self._cache_max_size: int = 100
        self._cache_ttl: int = 60
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._init_detectors()
        if config:
            self._apply_config(config)
        logger.info(f"FormatValidator initialized with {len(FormatType)} format types")

    def _init_detectors(self) -> None:
        self._format_detectors = {
            "json": self._detect_json,
            "xml": self._detect_xml,
            "yaml": self._detect_yaml,
            "html": self._detect_html,
            "csv": self._detect_csv,
        }

    def _apply_config(self, config: Dict[str, Any]) -> None:
        for key, value in config.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
            elif key == "allowed_html_tags" and isinstance(value, list):
                self._allowed_html_tags = set(value)
            elif key == "allowed_html_attributes" and isinstance(value, list):
                self._allowed_html_attributes = set(value)

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Callback '{event}' failed: {e}")

    def register_callback(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> bool:
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
            return True
        return False

    def _build_cache_key(self, content: str, format_type: str) -> str:
        import hashlib
        h = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        return f"{format_type}:{h}"

    def _get_cached(self, key: str) -> Optional[Tuple[bool, List[FormatError]]]:
        if key in self._cache:
            result, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                self._cache.move_to_end(key)
                return result
            del self._cache[key]
        return None

    def _set_cached(self, key: str, result: Tuple[bool, List[FormatError]]) -> None:
        self._cache[key] = (result, time.time())
        if len(self._cache) > self._cache_max_size:
            self._cache.popitem(last=False)

    def validate(
        self, content: str, format_type: str
    ) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        start_time = time.perf_counter()

        cache_key = self._build_cache_key(content, format_type)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self._trigger_callbacks("before_validate", content, format_type)

        if not content or not content.strip():
            errors.append(FormatError(
                format_type=format_type,
                message="Content is empty",
                severity=Severity.ERROR,
            ))
            return False, errors

        if len(content.encode(self._config.encoding)) > self._config.max_size_bytes:
            errors.append(FormatError(
                format_type=format_type,
                message=f"Content exceeds max size of {self._config.max_size_bytes} bytes",
                severity=Severity.ERROR,
            ))
            return False, errors

        validator_map: Dict[str, Callable] = {
            "json": self._validate_json,
            "xml": self._validate_xml,
            "yaml": self._validate_yaml,
            "markdown": self._validate_markdown,
            "html": self._validate_html,
            "csv": self._validate_csv,
            "plain_text": self._validate_plain_text,
        }

        validator = validator_map.get(format_type)
        if validator is None:
            errors.append(FormatError(
                format_type=format_type,
                message=f"Unsupported format type: {format_type}",
                severity=Severity.ERROR,
            ))
            return False, errors

        valid, format_errors = validator(content)
        errors.extend(format_errors)

        custom_key = f"custom_{format_type}"
        if custom_key in self._custom_validators:
            try:
                self._custom_validators[custom_key](content, errors)
            except Exception as e:
                logger.warning(f"Custom validator for {format_type} failed: {e}")

        elapsed = int((time.perf_counter() - start_time) * 1000)
        self._stats[format_type]["total_checks"] += 1
        self._stats[format_type]["total_errors"] += len(errors)
        self._stats[format_type]["total_time_ms"] += elapsed

        is_valid = len([e for e in errors if e.severity == Severity.ERROR]) == 0

        self._trigger_callbacks("after_validate", content, format_type, errors, is_valid)

        result = (is_valid, errors)
        self._set_cached(cache_key, result)
        return result

    def _get_error_snippet(self, content: str, line_num: int) -> str:
        lines = content.split("\n")
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()[:200]
        return ""

    def _validate_json(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        try:
            if self._config.json_allow_trailing_comma or self._config.json_allow_comments:
                import json as json_module
                parsed = self._parse_json_lenient(content)
            else:
                parsed = json.loads(content)
            self._check_json_depth(parsed, errors)
            self._check_json_size(content, errors)
            if self._config.strict:
                self._check_json_duplicate_keys(content, errors)
        except json.JSONDecodeError as e:
            line_info = ""
            if e.lineno is not None:
                line_info = f" at line {e.lineno}, column {e.colno}"
                snippet = self._get_error_snippet(content, e.lineno)
            else:
                snippet = None
            errors.append(FormatError(
                format_type="json",
                message=f"Invalid JSON: {e.msg}{line_info}",
                severity=Severity.ERROR,
                line=e.lineno,
                column=e.colno,
                suggestion=snippet,
            ))
        except Exception as e:
            errors.append(FormatError(
                format_type="json",
                message=f"JSON validation error: {str(e)}",
                severity=Severity.ERROR,
            ))
        return len(errors) == 0, errors

    def _parse_json_lenient(self, content: str) -> Any:
        if self._config.json_allow_comments:
            content = re.sub(r"//[^\n]*", "", content)
            content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        if self._config.json_allow_trailing_comma:
            content = re.sub(r",\s*([\]}])", r"\1", content)
        return json.loads(content)

    def _check_json_depth(self, obj: Any, errors: List[FormatError], current_depth: int = 0) -> None:
        if current_depth > self._config.max_nesting_depth:
            errors.append(FormatError(
                format_type="json",
                message=f"JSON nesting exceeds max depth of {self._config.max_nesting_depth}",
                severity=Severity.ERROR,
                rule_name="max_depth",
            ))
            return
        if isinstance(obj, dict):
            for v in obj.values():
                self._check_json_depth(v, errors, current_depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._check_json_depth(item, errors, current_depth + 1)

    def _check_json_size(self, content: str, errors: List[FormatError]) -> None:
        byte_size = len(content.encode("utf-8"))
        if byte_size > 5 * 1024 * 1024:
            errors.append(FormatError(
                format_type="json",
                message=f"JSON content is very large: {byte_size} bytes",
                severity=Severity.WARNING,
                rule_name="large_size",
            ))

    def _check_json_duplicate_keys(self, content: str, errors: List[FormatError]) -> None:
        try:
            lines = content.split("\n")
            key_pattern = re.compile(r'^\s*"([^"]+)"\s*:')
            seen_keys: Dict[str, List[int]] = defaultdict(list)
            for i, line in enumerate(lines, 1):
                match = key_pattern.match(line)
                if match:
                    key = match.group(1)
                    seen_keys[key].append(i)
            for key, line_nums in seen_keys.items():
                if len(line_nums) > 1:
                    errors.append(FormatError(
                        format_type="json",
                        message=f"Duplicate key '{key}' found on lines {line_nums}",
                        severity=Severity.WARNING,
                        line=line_nums[0],
                        rule_name="duplicate_key",
                    ))
        except Exception:
            pass

    def _validate_xml(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        try:
            root = ET.fromstring(content)
            self._check_xml_depth(root, errors)
            if self._config.strict:
                self._validate_xml_structure(root, errors)
            if self._config.xml_validate_dtd:
                self._validate_xml_dtd(content, errors)
            self._check_xml_well_formed(content, errors)
        except ET.ParseError as e:
            line_num = getattr(e, "position", (0, 0))[0]
            col_num = getattr(e, "position", (0, 0))[1]
            errors.append(FormatError(
                format_type="xml",
                message=f"Invalid XML: {str(e)}",
                severity=Severity.ERROR,
                line=line_num or None,
                column=col_num or None,
            ))
        except Exception as e:
            errors.append(FormatError(
                format_type="xml",
                message=f"XML validation error: {str(e)}",
                severity=Severity.ERROR,
            ))
        return len(errors) == 0, errors

    def _check_xml_depth(self, element: ET.Element, errors: List[FormatError], depth: int = 0) -> None:
        if depth > self._config.max_nesting_depth:
            errors.append(FormatError(
                format_type="xml",
                message=f"XML nesting exceeds max depth of {self._config.max_nesting_depth}",
                severity=Severity.ERROR,
                rule_name="max_depth",
            ))
            return
        for child in element:
            self._check_xml_depth(child, errors, depth + 1)

    def _validate_xml_structure(self, element: ET.Element, errors: List[FormatError]) -> None:
        if not element.tag:
            errors.append(FormatError(
                format_type="xml",
                message="Empty tag name found",
                severity=Severity.ERROR,
                rule_name="empty_tag",
            ))
        for child in element:
            self._validate_xml_structure(child, errors)

    def _validate_xml_dtd(self, content: str, errors: List[FormatError]) -> None:
        try:
            dom = xml.dom.minidom.parseString(content)
            internal_subset = dom.ownerDocument.doctype
            if internal_subset is None:
                errors.append(FormatError(
                    format_type="xml",
                    message="No DTD declaration found",
                    severity=Severity.WARNING,
                    rule_name="missing_dtd",
                ))
        except Exception as e:
            errors.append(FormatError(
                format_type="xml",
                message=f"DTD validation error: {str(e)}",
                severity=Severity.WARNING,
                rule_name="dtd_error",
            ))

    def _check_xml_well_formed(self, content: str, errors: List[FormatError]) -> None:
        if not content.strip().startswith("<?xml") and not content.strip().startswith("<"):
            errors.append(FormatError(
                format_type="xml",
                message="XML content does not start with XML declaration or root element",
                severity=Severity.WARNING,
                rule_name="well_formed",
            ))

    def _validate_yaml(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        try:
            import yaml
            loader_map = {
                "safe": yaml.SafeLoader,
                "full": yaml.FullLoader,
                "base": yaml.BaseLoader,
            }
            loader = loader_map.get(self._config.yaml_loader, yaml.SafeLoader)
            parsed = yaml.load(content, Loader=loader)
            self._check_yaml_depth(parsed, errors)
        except yaml.YAMLError as e:
            line_num = getattr(e.problem_mark, "line", None) if hasattr(e, "problem_mark") else None
            col_num = getattr(e.problem_mark, "column", None) if hasattr(e, "problem_mark") else None
            if line_num is not None:
                line_num += 1
            if col_num is not None:
                col_num += 1
            errors.append(FormatError(
                format_type="yaml",
                message=f"Invalid YAML: {str(e)}",
                severity=Severity.ERROR,
                line=line_num,
                column=col_num,
            ))
        except ImportError:
            errors.append(FormatError(
                format_type="yaml",
                message="YAML library not available (install PyYAML)",
                severity=Severity.ERROR,
            ))
        except Exception as e:
            errors.append(FormatError(
                format_type="yaml",
                message=f"YAML validation error: {str(e)}",
                severity=Severity.ERROR,
            ))
        return len(errors) == 0, errors

    def _check_yaml_depth(self, obj: Any, errors: List[FormatError], depth: int = 0) -> None:
        if depth > self._config.max_nesting_depth:
            errors.append(FormatError(
                format_type="yaml",
                message=f"YAML nesting exceeds max depth of {self._config.max_nesting_depth}",
                severity=Severity.ERROR,
                rule_name="max_depth",
            ))
            return
        if isinstance(obj, dict):
            for v in obj.values():
                self._check_yaml_depth(v, errors, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._check_yaml_depth(item, errors, depth + 1)

    def _validate_markdown(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        lines = content.split("\n")

        if self._config.strict:
            self._check_markdown_headings(lines, errors)
        self._check_markdown_code_blocks(lines, errors)
        self._check_markdown_links(lines, errors)
        self._check_markdown_lists(lines, errors)
        self._check_markdown_images(lines, errors)
        self._check_markdown_tables(lines, errors)
        self._check_markdown_horizontal_rules(lines, errors)
        self._check_markdown_blank_lines(lines, errors)
        self._check_markdown_html_injection(lines, errors)

        return len(errors) == 0, errors

    def _check_markdown_headings(self, lines: List[str], errors: List[FormatError]) -> None:
        heading_levels: List[int] = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if match:
                level = len(match.group(1))
                if level > self._config.markdown_max_heading_level:
                    errors.append(FormatError(
                        format_type="markdown",
                        message=f"Heading level {level} exceeds max ({self._config.markdown_max_heading_level})",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="heading_level",
                    ))
                if heading_levels and level > heading_levels[-1] + 1:
                    errors.append(FormatError(
                        format_type="markdown",
                        message=f"Heading level jumps from {heading_levels[-1]} to {level} (skip detected)",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="heading_skip",
                    ))
                heading_levels.append(level)

    def _check_markdown_code_blocks(self, lines: List[str], errors: List[FormatError]) -> None:
        in_fence = False
        fence_type = ""
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            fence_match = re.match(r"^(```|~~~)(\w*)$", stripped)
            if fence_match:
                if in_fence:
                    if fence_match.group(1) == fence_type:
                        in_fence = False
                    else:
                        errors.append(FormatError(
                            format_type="markdown",
                            message=f"Mismatched code fence closer at line {i}",
                            severity=Severity.WARNING,
                            line=i,
                            rule_name="code_fence",
                        ))
                else:
                    in_fence = True
                    fence_type = fence_match.group(1)

    def _check_markdown_links(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            inline_links = re.finditer(r"\[([^\]]*)\]\(([^)]*)\)", line)
            for match in inline_links:
                text = match.group(1)
                url = match.group(2)
                if not text.strip():
                    errors.append(FormatError(
                        format_type="markdown",
                        message="Empty link text found",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="empty_link_text",
                        suggestion="Add descriptive text to the link",
                    ))
                if not url.strip() or url.strip() == "#":
                    errors.append(FormatError(
                        format_type="markdown",
                        message="Empty or placeholder URL in link",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="empty_url",
                    ))

    def _check_markdown_lists(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            ordered_match = re.match(r"^(\d+)\.\s", stripped)
            if ordered_match:
                pass

    def _check_markdown_images(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            images = re.finditer(r"!\[([^\]]*)\]\(([^)]*)\)", line)
            for match in images:
                alt_text = match.group(1)
                src = match.group(2)
                if not alt_text.strip():
                    errors.append(FormatError(
                        format_type="markdown",
                        message="Image missing alt text",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="image_alt_text",
                    ))
                if not src.strip():
                    errors.append(FormatError(
                        format_type="markdown",
                        message="Image with empty source URL",
                        severity=Severity.WARNING,
                        line=i,
                        rule_name="image_src",
                    ))

    def _check_markdown_tables(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                if i + 1 <= len(lines):
                    next_line = lines[i - 1].strip() if i > 0 else ""
                    if re.match(r"^\|[-:| ]+\|$", stripped):
                        continue
                cols = len(stripped.split("|")) - 1
                if i + 1 <= len(lines) and re.match(r"^\|[-:| ]+\|$", lines[i].strip()):
                    next_cols = len(lines[i].strip().split("|")) - 1
                    if cols != next_cols:
                        errors.append(FormatError(
                            format_type="markdown",
                            message=f"Table column mismatch at line {i} ({cols} vs {next_cols})",
                            severity=Severity.ERROR,
                            line=i,
                            rule_name="table_columns",
                        ))

    def _check_markdown_horizontal_rules(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
                pass

    def _check_markdown_blank_lines(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r"^#{1,6}\s+.+$", stripped):
                if i < len(lines) and lines[i].strip():
                    if self._config.markdown_require_blank_after_heading:
                        errors.append(FormatError(
                            format_type="markdown",
                            message=f"Heading at line {i} not followed by blank line",
                            severity=Severity.INFO,
                            line=i,
                            rule_name="heading_blank_line",
                        ))

    def _check_markdown_html_injection(self, lines: List[str], errors: List[FormatError]) -> None:
        for i, line in enumerate(lines, 1):
            html_tags = re.findall(r"<(script|iframe|embed|object)[^>]*>", line, re.IGNORECASE)
            for tag in html_tags:
                errors.append(FormatError(
                    format_type="markdown",
                    message=f"Potentially unsafe HTML tag '<{tag}>' in markdown",
                    severity=Severity.WARNING,
                    line=i,
                    rule_name="unsafe_html",
                ))

    def _validate_html(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        tags = self._parse_html_tags(content)
        self._check_html_tag_balance(tags, errors)
        self._check_html_allowed_tags(tags, errors)
        self._check_html_allowed_attributes(tags, errors)
        self._check_html_doctype(content, errors)
        self._check_html_nested_tags(content, errors)
        self._check_html_self_closing(content, errors)
        self._check_html_aria(content, errors)

        open_tags = len([t for t in tags if not t.self_closing])
        close_tags_inline = len(re.findall(r"</[a-zA-Z][^>]*>", content))
        self_closing_td = len(re.findall(r"<[a-zA-Z][^>]*/>", content))
        if open_tags > (close_tags_inline + self_closing_td):
            errors.append(FormatError(
                format_type="html",
                message="Potentially unclosed HTML tags detected",
                severity=Severity.WARNING,
                rule_name="unclosed_tags",
            ))
        return len(errors) == 0, errors

    def _parse_html_tags(self, content: str) -> List[HtmlTag]:
        tags: List[HtmlTag] = []
        tag_pattern = re.compile(r"<\/?([a-zA-Z][a-zA-Z0-9]*)\b([^>]*?)(\/?>|$)", re.DOTALL)
        self_closing_pattern = re.compile(r"\/>$")
        attr_pattern = re.compile(r'(\w+)\s*=\s*"([^"]*)"|\b(\w+)\b(?=\s|/?>)')
        lines = content.split("\n")
        for match in tag_pattern.finditer(content):
            tag_name = match.group(1).lower()
            rest = match.group(2)
            closing = "/" in match.group(0) and match.group(0).startswith("</")
            sc = bool(self_closing_pattern.search(rest or ""))
            if closing:
                tags.append(HtmlTag(name=tag_name, self_closing=False, line=0))
                continue
            attributes: Dict[str, str] = {}
            if rest:
                for attr_match in attr_pattern.finditer(rest):
                    if attr_match.group(1):
                        attributes[attr_match.group(1)] = attr_match.group(2)
                    elif attr_match.group(3):
                        attributes[attr_match.group(3)] = ""
            tags.append(HtmlTag(name=tag_name, attributes=attributes, self_closing=sc, line=0))
        return tags

    def _check_html_tag_balance(self, tags: List[HtmlTag], errors: List[FormatError]) -> None:
        self_closing_tags = {
            "br", "hr", "img", "input", "meta", "link",
            "area", "base", "col", "embed", "source", "track", "wbr",
        }
        stack: List[str] = []
        for tag in tags:
            if tag.self_closing or tag.name in self_closing_tags:
                continue
            if tag.name.startswith("/"):
                expected = tag.name[1:]
                if stack and stack[-1] == expected:
                    stack.pop()
                else:
                    errors.append(FormatError(
                        format_type="html",
                        message=f"Unexpected closing tag </{expected}>",
                        severity=Severity.ERROR,
                        rule_name="tag_balance",
                    ))
            else:
                stack.append(tag.name)
        for unclosed in stack:
            errors.append(FormatError(
                format_type="html",
                message=f"Unclosed tag <{unclosed}>",
                severity=Severity.WARNING,
                rule_name="unclosed_tag",
            ))

    def _check_html_allowed_tags(self, tags: List[HtmlTag], errors: List[FormatError]) -> None:
        if not self._allowed_html_tags:
            return
        for tag in tags:
            tag_name = tag.name.lstrip("/")
            if tag_name not in self._allowed_html_tags:
                errors.append(FormatError(
                    format_type="html",
                    message=f"Tag '{tag_name}' is not in allowed list",
                    severity=Severity.WARNING,
                    rule_name="disallowed_tag",
                ))

    def _check_html_allowed_attributes(self, tags: List[HtmlTag], errors: List[FormatError]) -> None:
        if not self._allowed_html_attributes:
            return
        for tag in tags:
            for attr in tag.attributes:
                if attr not in self._allowed_html_attributes:
                    errors.append(FormatError(
                        format_type="html",
                        message=f"Attribute '{attr}' on <{tag.name}> is not allowed",
                        severity=Severity.WARNING,
                        rule_name="disallowed_attribute",
                    ))

    def _check_html_doctype(self, content: str, errors: List[FormatError]) -> None:
        if self._config.html_require_doctype:
            if not content.strip().startswith("<!DOCTYPE") and not content.strip().startswith("<!doctype"):
                errors.append(FormatError(
                    format_type="html",
                    message="Missing DOCTYPE declaration",
                    severity=Severity.WARNING,
                    rule_name="doctype",
                ))

    def _check_html_nested_tags(self, content: str, errors: List[FormatError]) -> None:
        invalid_nesting = re.findall(
            r"<(p|li|dt|dd|th|td|option)[^>]*?>.*?</(p|li|dt|dd|th|td|option)>",
            content, re.DOTALL
        )
        if invalid_nesting:
            errors.append(FormatError(
                format_type="html",
                message="Potential invalid HTML nesting detected",
                severity=Severity.WARNING,
                rule_name="nesting",
            ))

    def _check_html_self_closing(self, content: str, errors: List[FormatError]) -> None:
        non_void_self_closing = re.findall(
            r"<(div|span|p|a|li|h[1-6]|section|article|header|footer)[^>]*?/>",
            content, re.IGNORECASE
        )
        if non_void_self_closing:
            for tag in non_void_self_closing[:3]:
                errors.append(FormatError(
                    format_type="html",
                    message=f"Non-void tag '<{tag}/>' should not be self-closing",
                    severity=Severity.WARNING,
                    rule_name="self_closing",
                ))

    def _check_html_aria(self, content: str, errors: List[FormatError]) -> None:
        interactive = re.findall(r"<(button|a|input|select|textarea)[^>]*>", content, re.IGNORECASE)
        if interactive:
            aria_labels = re.findall(r"aria-label\s*=|aria-labelledby\s*=", content)
            if not aria_labels:
                errors.append(FormatError(
                    format_type="html",
                    message=f"Interactive elements ({len(interactive)}) without ARIA labels for accessibility",
                    severity=Severity.INFO,
                    rule_name="aria_accessibility",
                ))

    def _validate_csv(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        try:
            reader = csv.reader(
                io.StringIO(content),
                delimiter=self._config.csv_delimiter,
                quotechar=self._config.csv_quotechar,
                strict=self._config.csv_strict,
            )
            rows = list(reader)
            if not rows:
                errors.append(FormatError(
                    format_type="csv",
                    message="CSV content has no rows",
                    severity=Severity.ERROR,
                ))
                return False, errors

            header_cols = len(rows[0])
            if self._config.csv_require_header:
                if not any(c.strip() for c in rows[0]):
                    errors.append(FormatError(
                        format_type="csv",
                        message="CSV header row appears empty",
                        severity=Severity.WARNING,
                        rule_name="empty_header",
                    ))

            for i, row in enumerate(rows[1:], 2):
                if len(row) != header_cols:
                    errors.append(FormatError(
                        format_type="csv",
                        message=f"Row {i} has {len(row)} columns, expected {header_cols}",
                        severity=Severity.ERROR,
                        line=i,
                        rule_name="column_count",
                    ))

            if self._config.strict:
                self._check_csv_quoting(content, errors)
                self._check_csv_delimiter(content, errors)
        except csv.Error as e:
            errors.append(FormatError(
                format_type="csv",
                message=f"CSV parsing error: {str(e)}",
                severity=Severity.ERROR,
            ))
        except Exception as e:
            errors.append(FormatError(
                format_type="csv",
                message=f"CSV validation error: {str(e)}",
                severity=Severity.ERROR,
            ))
        return len(errors) == 0, errors

    def _check_csv_quoting(self, content: str, errors: List[FormatError]) -> None:
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue
            quote_count = stripped.count(self._config.csv_quotechar)
            if quote_count % 2 != 0:
                errors.append(FormatError(
                    format_type="csv",
                    message=f"Unbalanced quotes at line {i}",
                    severity=Severity.WARNING,
                    line=i,
                    rule_name="quoting",
                ))

    def _check_csv_delimiter(self, content: str, errors: List[FormatError]) -> None:
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if line.strip():
                if self._config.csv_delimiter not in line:
                    errors.append(FormatError(
                        format_type="csv",
                        message=f"Row {i} missing delimiter '{self._config.csv_delimiter}'",
                        severity=Severity.INFO,
                        line=i,
                        rule_name="delimiter",
                    ))
                    break

    def _validate_plain_text(self, content: str) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        encoding_errors = self._check_encoding(content)
        errors.extend(encoding_errors)
        return len(errors) == 0, errors

    def _check_encoding(self, content: str) -> List[FormatError]:
        errors: List[FormatError] = []
        try:
            content.encode(self._config.encoding)
        except UnicodeEncodeError as e:
            errors.append(FormatError(
                format_type="plain_text",
                message=f"Content cannot be encoded as {self._config.encoding}: {e}",
                severity=Severity.ERROR,
            ))
        except LookupError:
            errors.append(FormatError(
                format_type="plain_text",
                message=f"Unknown encoding: {self._config.encoding}",
                severity=Severity.ERROR,
            ))
        return errors

    def validate_with_schema(
        self, content: str, format_type: str, schema: Any
    ) -> Tuple[bool, List[FormatError]]:
        errors: List[FormatError] = []
        is_valid, format_errors = self.validate(content, format_type)
        errors.extend(format_errors)
        if format_type == "json":
            schema_errors = self._apply_json_schema(content, schema)
            errors.extend(schema_errors)
        elif format_type == "xml":
            schema_errors = self._apply_xml_schema(content, schema)
            errors.extend(schema_errors)
        is_valid = len([e for e in errors if e.severity == Severity.ERROR]) == 0
        return is_valid, errors

    def _apply_json_schema(self, content: str, schema: Dict[str, Any]) -> List[FormatError]:
        errors: List[FormatError] = []
        try:
            import jsonschema
            data = json.loads(content)
            validator = jsonschema.Draft7Validator(schema)
            validation_errors = list(validator.iter_errors(data))
            for ve in validation_errors:
                path = " -> ".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
                errors.append(FormatError(
                    format_type="json",
                    message=f"Schema violation at {path}: {ve.message}",
                    severity=Severity.ERROR,
                    rule_name="json_schema",
                ))
        except ImportError:
            errors.append(FormatError(
                format_type="json",
                message="jsonschema library not available for schema validation",
                severity=Severity.WARNING,
            ))
        except json.JSONDecodeError as e:
            errors.append(FormatError(
                format_type="json",
                message=f"Cannot validate schema on invalid JSON: {e}",
                severity=Severity.ERROR,
            ))
        return errors

    def _apply_xml_schema(self, content: str, schema_path: str) -> List[FormatError]:
        errors: List[FormatError] = []
        try:
            import xmlschema
            schema = xmlschema.XMLSchema(schema_path)
            if not schema.is_valid(content):
                for ve in schema.iter_errors(content):
                    errors.append(FormatError(
                        format_type="xml",
                        message=f"XML Schema violation: {ve}",
                        severity=Severity.ERROR,
                        rule_name="xml_schema",
                    ))
        except ImportError:
            errors.append(FormatError(
                format_type="xml",
                message="xmlschema library not available for XSD validation",
                severity=Severity.WARNING,
            ))
        except Exception as e:
            errors.append(FormatError(
                format_type="xml",
                message=f"XSD validation error: {str(e)}",
                severity=Severity.WARNING,
            ))
        return errors

    def set_schema(self, format_type: str, schema: Dict[str, Any]) -> None:
        self._schema_validators[format_type] = schema
        logger.info(f"Schema set for format: {format_type}")

    def get_schema(self, format_type: str) -> Optional[Dict[str, Any]]:
        return self._schema_validators.get(format_type)

    def remove_schema(self, format_type: str) -> bool:
        if format_type in self._schema_validators:
            del self._schema_validators[format_type]
            return True
        return False

    def register_custom_validator(self, format_type: str, validator_func: Callable) -> None:
        key = f"custom_{format_type}"
        self._custom_validators[key] = validator_func
        logger.info(f"Custom validator registered for format: {format_type}")

    def unregister_custom_validator(self, format_type: str) -> bool:
        key = f"custom_{format_type}"
        if key in self._custom_validators:
            del self._custom_validators[key]
            return True
        return False

    def update_config(self, config: Dict[str, Any]) -> None:
        self._apply_config(config)

    def get_config(self) -> Dict[str, Any]:
        return {
            "indent": self._config.indent,
            "encoding": self._config.encoding,
            "allow_comments": self._config.allow_comments,
            "strict": self._config.strict,
            "max_size_bytes": self._config.max_size_bytes,
            "markdown_max_heading_level": self._config.markdown_max_heading_level,
            "csv_delimiter": self._config.csv_delimiter,
            "csv_quotechar": self._config.csv_quotechar,
            "csv_strict": self._config.csv_strict,
            "yaml_loader": self._config.yaml_loader,
            "xml_validate_dtd": self._config.xml_validate_dtd,
            "max_nesting_depth": self._config.max_nesting_depth,
            "json_allow_trailing_comma": self._config.json_allow_trailing_comma,
            "json_allow_comments": self._config.json_allow_comments,
            "html_require_doctype": self._config.html_require_doctype,
            "csv_require_header": self._config.csv_require_header,
        }

    def get_stats(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for fmt, counter in self._stats.items():
            total = counter.get("total_checks", 0)
            result[fmt] = {
                "total_checks": total,
                "total_errors": counter.get("total_errors", 0),
                "error_rate": round(counter["total_errors"] / total, 4) if total > 0 else 0.0,
                "total_time_ms": counter.get("total_time_ms", 0),
                "avg_time_ms": round(counter["total_time_ms"] / total, 2) if total > 0 else 0.0,
            }
        return result

    def reset_stats(self) -> None:
        self._stats.clear()

    def get_allowed_html_tags(self) -> Set[str]:
        return set(self._allowed_html_tags)

    def set_allowed_html_tags(self, tags: Set[str]) -> None:
        self._allowed_html_tags = tags

    def add_allowed_html_tag(self, tag: str) -> None:
        self._allowed_html_tags.add(tag.lower())

    def remove_allowed_html_tag(self, tag: str) -> bool:
        tag_lower = tag.lower()
        if tag_lower in self._allowed_html_tags:
            self._allowed_html_tags.discard(tag_lower)
            return True
        return False

    def get_allowed_html_attributes(self) -> Set[str]:
        return set(self._allowed_html_attributes)

    def set_allowed_html_attributes(self, attrs: Set[str]) -> None:
        self._allowed_html_attributes = attrs

    def add_allowed_html_attribute(self, attr: str) -> None:
        self._allowed_html_attributes.add(attr)

    def remove_allowed_html_attribute(self, attr: str) -> bool:
        if attr in self._allowed_html_attributes:
            self._allowed_html_attributes.discard(attr)
            return True
        return False

    def clear_cache(self) -> None:
        self._cache.clear()

    def format_detection(self, content: str) -> Tuple[Optional[str], float]:
        best_format: Optional[str] = None
        best_score: float = 0.0
        for fmt, detector in self._format_detectors.items():
            score = detector(content)
            if score > best_score:
                best_score = score
                best_format = fmt
        return best_format, best_score

    def _detect_json(self, content: str) -> float:
        try:
            json.loads(content)
            return 1.0
        except (json.JSONDecodeError, ValueError):
            stripped = content.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                return 0.3
            return 0.0

    def _detect_xml(self, content: str) -> float:
        stripped = content.strip()
        if stripped.startswith("<?xml") or stripped.startswith("<"):
            try:
                ET.fromstring(content)
                return 0.9
            except ET.ParseError:
                return 0.3
        return 0.0

    def _detect_yaml(self, content: str) -> float:
        try:
            import yaml
            yaml.safe_load(content)
            return 0.9
        except (yaml.YAMLError, ImportError):
            stripped = content.strip()
            if ":" in stripped and "\n" in stripped:
                return 0.2
            return 0.0

    def _detect_html(self, content: str) -> float:
        stripped = content.strip()
        if stripped.startswith("<!DOCTYPE") or stripped.startswith("<!doctype"):
            return 0.9
        html_tags = re.findall(r"<\/?[a-zA-Z][^>]*>", content)
        if len(html_tags) > 2:
            return 0.7
        if stripped.startswith("<html"):
            return 0.8
        return 0.0

    def _detect_csv(self, content: str) -> float:
        lines = content.strip().split("\n")
        if len(lines) < 2:
            return 0.0
        header = lines[0]
        if self._config.csv_delimiter in header:
            cols = len(header.split(self._config.csv_delimiter))
            if cols >= 2:
                consistent = True
                for line in lines[1:]:
                    if line.strip() and len(line.split(self._config.csv_delimiter)) != cols:
                        consistent = False
                        break
                if consistent:
                    return 0.8
        return 0.0

    def validate_batch(
        self,
        contents: List[str],
        format_type: str,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> List[Tuple[bool, List[FormatError]]]:
        if parallel:
            return self._validate_batch_parallel(contents, format_type, max_workers)
        results = []
        for i, content in enumerate(contents):
            result = self.validate(content, format_type)
            results.append(result)
        return results

    def _validate_batch_parallel(
        self,
        contents: List[str],
        format_type: str,
        max_workers: int,
    ) -> List[Tuple[bool, List[FormatError]]]:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.validate, content, format_type): i
                    for i, content in enumerate(contents)
                }
                ordered: List[Optional[Tuple[bool, List[FormatError]]]] = [None] * len(contents)
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        ordered[idx] = future.result()
                    except Exception as e:
                        logger.error(f"Batch validation failed at index {idx}: {e}")
                        ordered[idx] = (False, [
                            FormatError(format_type=format_type, message=str(e), severity=Severity.ERROR)
                        ])
                return [r for r in ordered if r is not None]
        except ImportError:
            return [self.validate(c, format_type) for c in contents]

    def __repr__(self) -> str:
        return (
            f"FormatValidator(formats={len(FormatType)}, "
            f"strict={self._config.strict})"
        )
