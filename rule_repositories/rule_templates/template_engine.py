"""
Rule template engine - processing, variable substitution, conditional blocks,
loop constructs, nested templates, caching, and error handling.
"""

import hashlib
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class TemplateSyntax(str, Enum):
    """Supported template syntax flavors."""
    DOUBLE_CURLY = "double_curly"
    DOLLAR_CURLY = "dollar_curly"
    JINJA_LIKE = "jinja_like"
    CUSTOM = "custom"


class TemplateTokenType(str, Enum):
    """Token types for template lexing."""
    TEXT = "text"
    VARIABLE = "variable"
    VARIABLE_DOLLAR = "variable_dollar"
    IF_BLOCK = "if_block"
    ELSE_BLOCK = "else_block"
    ENDIF_BLOCK = "endif_block"
    FOR_BLOCK = "for_block"
    ENDFOR_BLOCK = "endfor_block"
    INCLUDE_BLOCK = "include_block"
    IMPORT_BLOCK = "import_block"
    COMMENT = "comment"


class TemplateError(Exception):
    """Base exception for template processing errors."""


class TemplateSyntaxError(TemplateError):
    """Raised when template syntax is invalid."""


class TemplateVariableError(TemplateError):
    """Raised when a variable referenced in template is missing or invalid."""


class TemplateIncludeError(TemplateError):
    """Raised when an included or imported template cannot be resolved."""


class TemplateSyntaxConfig(BaseModel):
    """Configuration for template syntax delimiters."""

    syntax: TemplateSyntax = TemplateSyntax.JINJA_LIKE
    variable_open: str = "{{"
    variable_close: str = "}}"
    variable_dollar_open: str = "${"
    variable_dollar_close: str = "}"
    block_open: str = "{%"
    block_close: str = "%}"
    comment_open: str = "{#"
    comment_close: str = "#}"
    escape_char: str = "\\"
    trim_blocks: bool = True
    lstrip_blocks: bool = False
    keep_trailing_newline: bool = False
    auto_escape: bool = True
    undefined_behavior: str = "strict"

    @validator("syntax", pre=True)
    def resolve_syntax(cls, v: Any) -> TemplateSyntax:
        if isinstance(v, TemplateSyntax):
            return v
        if isinstance(v, str):
            return TemplateSyntax(v.lower())
        return TemplateSyntax.DOUBLE_CURLY

    def configure_for_syntax(self, syntax: TemplateSyntax) -> "TemplateSyntaxConfig":
        """Set delimiters based on the chosen syntax flavor."""
        config_map: Dict[TemplateSyntax, Dict[str, str]] = {
            TemplateSyntax.DOUBLE_CURLY: {
                "variable_open": "{{", "variable_close": "}}",
                "block_open": "{%", "block_close": "%}",
                "comment_open": "{#", "comment_close": "#}",
            },
            TemplateSyntax.DOLLAR_CURLY: {
                "variable_open": "${", "variable_close": "}",
                "block_open": "{%", "block_close": "%}",
                "comment_open": "{#", "comment_close": "#}",
            },
            TemplateSyntax.JINJA_LIKE: {
                "variable_open": "{{", "variable_close": "}}",
                "block_open": "{%", "block_close": "%}",
                "comment_open": "{#", "comment_close": "#}",
            },
            TemplateSyntax.CUSTOM: {},
        }
        if syntax in config_map:
            for key, value in config_map[syntax].items():
                setattr(self, key, value)
        self.syntax = syntax
        return self

    class Config:
        use_enum_values = True


@dataclass
class TemplateToken:
    """Represents a single token from template lexing."""
    token_type: TemplateTokenType
    value: str
    line: int
    column: int
    raw: str = ""


@dataclass
class TemplateCacheEntry:
    """Cached entry for a parsed template."""
    ast: List[Any]
    source_hash: str
    compiled_time: float
    access_count: int = 0
    dependencies: Set[str] = field(default_factory=set)


class TemplateContext(BaseModel):
    """Context variables available during template rendering."""

    variables: Dict[str, Any] = Field(default_factory=dict)
    parent: Optional["TemplateContext"] = None
    loop_state: Optional[Dict[str, Any]] = None
    depth: int = 0
    max_depth: int = 10

    def get(self, name: str, default: Any = None) -> Any:
        """Get a variable from context, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent is not None:
            return self.parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set a variable in the current scope."""
        self.variables[name] = value

    def has(self, name: str) -> bool:
        """Check if a variable exists in this scope or parent scopes."""
        if name in self.variables:
            return True
        if self.parent is not None:
            return self.parent.has(name)
        return False

    def push(self) -> "TemplateContext":
        """Create a new child scope."""
        return TemplateContext(
            variables={},
            parent=self,
            depth=self.depth + 1,
            max_depth=self.max_depth,
        )

    def pop(self) -> Optional["TemplateContext"]:
        """Return the parent scope."""
        return self.parent

    class Config:
        arbitrary_types_allowed = True


class TemplateLexer:
    """Lexer that tokenizes template strings into tokens."""

    def __init__(self, config: TemplateSyntaxConfig) -> None:
        self.config = config
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for tokenizing based on config."""
        vo = re.escape(self.config.variable_open)
        vc = re.escape(self.config.variable_close)
        vdo = re.escape(self.config.variable_dollar_open)
        vdc = re.escape(self.config.variable_dollar_close)
        bo = re.escape(self.config.block_open)
        bc = re.escape(self.config.block_close)
        co = re.escape(self.config.comment_open)
        cc = re.escape(self.config.comment_close)

        self._patterns = [
            (TemplateTokenType.COMMENT, re.compile(f"{co}.*?{cc}")),
            (TemplateTokenType.IF_BLOCK, re.compile(
                f"{bo}\\s*if\\s+(.+?)\\s*{bc}", re.IGNORECASE | re.DOTALL
            )),
            (TemplateTokenType.ELSE_BLOCK, re.compile(
                f"{bo}\\s*else\\s*{bc}", re.IGNORECASE
            )),
            (TemplateTokenType.ENDIF_BLOCK, re.compile(
                f"{bo}\\s*endif\\s*{bc}", re.IGNORECASE
            )),
            (TemplateTokenType.FOR_BLOCK, re.compile(
                f"{bo}\\s*for\\s+(\\w+)\\s+in\\s+(.+?)\\s*{bc}", re.IGNORECASE | re.DOTALL
            )),
            (TemplateTokenType.ENDFOR_BLOCK, re.compile(
                f"{bo}\\s*endfor\\s*{bc}", re.IGNORECASE
            )),
            (TemplateTokenType.INCLUDE_BLOCK, re.compile(
                f"{bo}\\s*include\\s+[\"'](.+?)[\"']\\s*{bc}", re.IGNORECASE
            )),
            (TemplateTokenType.IMPORT_BLOCK, re.compile(
                f"{bo}\\s*import\\s+[\"'](.+?)[\"']\\s*{bc}", re.IGNORECASE
            )),
            (TemplateTokenType.VARIABLE, re.compile(f"{vo}(.+?){vc}", re.DOTALL)),
            (TemplateTokenType.VARIABLE_DOLLAR, re.compile(f"{vdo}(.+?){vdc}", re.DOTALL)),
        ]
        self._any_pattern = re.compile(
            "|".join(f"(?P<{t.value}>{p.pattern})" for t, p in self._patterns),
            re.DOTALL | re.IGNORECASE,
        )

    def tokenize(self, source: str) -> List[TemplateToken]:
        """Tokenize a template source string into a list of tokens."""
        tokens: List[TemplateToken] = []
        pos = 0
        line = 1
        col = 1
        source_len = len(source)

        while pos < source_len:
            match = self._any_pattern.search(source, pos)
            if match is None:
                tokens.append(TemplateToken(
                    token_type=TemplateTokenType.TEXT,
                    value=source[pos:],
                    line=line,
                    column=col,
                ))
                break

            if match.start() > pos:
                text = source[pos:match.start()]
                tokens.append(TemplateToken(
                    token_type=TemplateTokenType.TEXT,
                    value=text,
                    line=line,
                    column=col,
                ))
                lc = text.count("\n")
                if lc > 0:
                    line += lc
                    col = len(text) - text.rfind("\n")
                else:
                    col += len(text)

            raw = match.group(0)
            for token_type, _ in self._patterns:
                val = match.group(token_type.value)
                if val is not None:
                    val = val.strip()
                    if token_type in (
                        TemplateTokenType.VARIABLE,
                        TemplateTokenType.VARIABLE_DOLLAR,
                        TemplateTokenType.IF_BLOCK,
                        TemplateTokenType.FOR_BLOCK,
                        TemplateTokenType.INCLUDE_BLOCK,
                        TemplateTokenType.IMPORT_BLOCK,
                    ):
                        pass
                    tokens.append(TemplateToken(
                        token_type=token_type,
                        value=val,
                        line=line,
                        column=col,
                        raw=raw,
                    ))
                    break

            pos = match.end()
            lc = raw.count("\n")
            if lc > 0:
                line += lc
                col = len(raw) - raw.rfind("\n")
            else:
                col += len(raw)

        return tokens


class TemplateParser:
    """Parser that converts tokens into an AST (list of AST nodes)."""

    def __init__(self, config: TemplateSyntaxConfig) -> None:
        self.config = config

    def parse(self, tokens: List[TemplateToken]) -> List[Any]:
        """Parse tokens into an abstract syntax tree."""
        ast: List[Any] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.token_type == TemplateTokenType.TEXT:
                ast.append(TextNode(token.value))
            elif token.token_type == TemplateTokenType.VARIABLE:
                ast.append(VariableNode(token.value, token.raw))
            elif token.token_type == TemplateTokenType.VARIABLE_DOLLAR:
                ast.append(VariableNode(token.value, token.raw, dollar_style=True))
            elif token.token_type == TemplateTokenType.IF_BLOCK:
                node, i = self._parse_if_block(tokens, i)
                ast.append(node)
            elif token.token_type == TemplateTokenType.FOR_BLOCK:
                node, i = self._parse_for_block(tokens, i)
                ast.append(node)
            elif token.token_type == TemplateTokenType.INCLUDE_BLOCK:
                ast.append(IncludeNode(token.value))
            elif token.token_type == TemplateTokenType.IMPORT_BLOCK:
                ast.append(ImportNode(token.value))
            elif token.token_type == TemplateTokenType.COMMENT:
                pass
            elif token.token_type == TemplateTokenType.ELSE_BLOCK:
                raise TemplateSyntaxError(
                    f"Unexpected {{% else %}} at line {token.line}, column {token.column}"
                )
            elif token.token_type == TemplateTokenType.ENDIF_BLOCK:
                raise TemplateSyntaxError(
                    f"Unexpected {{% endif %}} at line {token.line}, column {token.column}"
                )
            elif token.token_type == TemplateTokenType.ENDFOR_BLOCK:
                raise TemplateSyntaxError(
                    f"Unexpected {{% endfor %}} at line {token.line}, column {token.column}"
                )
            i += 1
        return ast

    def _parse_if_block(self, tokens: List[TemplateToken], start: int) -> Tuple[ConditionalNode, int]:
        """Parse an if/else/endif block from tokens starting at given index."""
        if_token = tokens[start]
        condition = if_token.value.strip()
        body: List[Any] = []
        else_body: List[Any] = []
        current_body = body
        i = start + 1
        depth = 1

        while i < len(tokens):
            token = tokens[i]
            if token.token_type == TemplateTokenType.IF_BLOCK:
                depth += 1
                sub_node, i = self._parse_if_block(tokens, i)
                current_body.append(sub_node)
                continue
            elif token.token_type == TemplateTokenType.ENDIF_BLOCK:
                depth -= 1
                if depth == 0:
                    node = ConditionalNode(condition, body, else_body)
                    return node, i
            elif token.token_type == TemplateTokenType.ELSE_BLOCK:
                if depth == 1:
                    current_body = else_body
                    i += 1
                    continue
            current_body.append(self._parse_single_token(token))
            i += 1

        raise TemplateSyntaxError(
            f"Unclosed {{% if %}} block starting at line {if_token.line}, "
            f"column {if_token.column} - missing {{% endif %}}"
        )

    def _parse_for_block(self, tokens: List[TemplateToken], start: int) -> Tuple[LoopNode, int]:
        """Parse a for/endfor block from tokens starting at given index."""
        for_token = tokens[start]
        parts = for_token.value.split(" in ", 1)
        if len(parts) != 2:
            raise TemplateSyntaxError(
                f"Invalid {{% for %}} syntax at line {for_token.line}: "
                f"expected 'for item in collection'"
            )
        loop_var = parts[0].strip()
        collection_expr = parts[1].strip()
        body: List[Any] = []
        i = start + 1
        depth = 1

        while i < len(tokens):
            token = tokens[i]
            if token.token_type == TemplateTokenType.FOR_BLOCK:
                depth += 1
                sub_node, i = self._parse_for_block(tokens, i)
                body.append(sub_node)
                continue
            elif token.token_type == TemplateTokenType.ENDFOR_BLOCK:
                depth -= 1
                if depth == 0:
                    node = LoopNode(loop_var, collection_expr, body)
                    return node, i
            body.append(self._parse_single_token(token))
            i += 1

        raise TemplateSyntaxError(
            f"Unclosed {{% for %}} block starting at line {for_token.line}, "
            f"column {for_token.column} - missing {{% endfor %}}"
        )

    def _parse_single_token(self, token: TemplateToken) -> Any:
        """Convert a single token to the appropriate AST node."""
        if token.token_type == TemplateTokenType.TEXT:
            return TextNode(token.value)
        elif token.token_type in (
            TemplateTokenType.VARIABLE, TemplateTokenType.VARIABLE_DOLLAR,
        ):
            return VariableNode(
                token.value, token.raw,
                dollar_style=(token.token_type == TemplateTokenType.VARIABLE_DOLLAR),
            )
        elif token.token_type == TemplateTokenType.COMMENT:
            return TextNode("")
        return TextNode(token.raw)


class TextNode:
    """AST node representing literal text."""

    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        return self.text


class VariableNode:
    """AST node representing a variable substitution."""

    def __init__(self, expression: str, raw: str, dollar_style: bool = False) -> None:
        self.expression = expression.strip()
        self.raw = raw
        self.dollar_style = dollar_style

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        try:
            value = engine._resolve_variable(self.expression, context)
            if value is None:
                if engine.config.undefined_behavior == "strict":
                    raise TemplateVariableError(
                        f"Variable '{self.expression}' is undefined"
                    )
                elif engine.config.undefined_behavior == "silent":
                    return ""
                return f"${{{self.expression}}}"
            if not isinstance(value, str):
                value = str(value)
            return value
        except TemplateVariableError:
            raise
        except Exception as exc:
            raise TemplateVariableError(
                f"Error resolving variable '{self.expression}': {exc}"
            ) from exc


class ConditionalNode:
    """AST node representing an if/else conditional block."""

    def __init__(self, condition: str, body: List[Any], else_body: List[Any]) -> None:
        self.condition = condition.strip()
        self.body = body
        self.else_body = else_body

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        result = engine._evaluate_condition(self.condition, context)
        if result:
            return engine._render_nodes(self.body, context)
        return engine._render_nodes(self.else_body, context)


class LoopNode:
    """AST node representing a for loop block."""

    def __init__(self, loop_var: str, collection_expr: str, body: List[Any]) -> None:
        self.loop_var = loop_var
        self.collection_expr = collection_expr.strip()
        self.body = body

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        collection = engine._resolve_variable(self.collection_expr, context)
        if collection is None:
            if engine.config.undefined_behavior == "strict":
                raise TemplateVariableError(
                    f"Collection '{self.collection_expr}' is undefined in for loop"
                )
            return ""
        if not isinstance(collection, (list, tuple, set, dict)):
            collection = list(collection) if hasattr(collection, "__iter__") else str(collection)

        items: List[Any]
        if isinstance(collection, dict):
            items = list(collection.items())
        else:
            items = list(collection)

        results: List[str] = []
        total = len(items)
        for idx, item in enumerate(items):
            loop_ctx = {
                "index": idx + 1,
                "index0": idx,
                "first": idx == 0,
                "last": idx == total - 1,
                "length": total,
                "item": item,
            }
            child_ctx = context.push()
            child_ctx.set(self.loop_var, item)
            child_ctx.loop_state = loop_ctx
            results.append(engine._render_nodes(self.body, child_ctx))
            child_ctx.pop()

        return "".join(results)


class IncludeNode:
    """AST node representing an include directive."""

    def __init__(self, template_name: str) -> None:
        self.template_name = template_name.strip()

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        if context.depth > context.max_depth:
            raise TemplateError(
                f"Maximum template include depth ({context.max_depth}) exceeded "
                f"for '{self.template_name}'"
            )
        return engine.render_template(self.template_name, context.variables)


class ImportNode:
    """AST node representing an import directive."""

    def __init__(self, template_name: str) -> None:
        self.template_name = template_name.strip()

    def render(self, context: TemplateContext, engine: "RuleTemplateEngine") -> str:
        imported = engine._load_imported_template(self.template_name)
        if imported is None:
            raise TemplateIncludeError(
                f"Imported template '{self.template_name}' not found"
            )
        child_ctx = context.push()
        result = engine._render_nodes(imported, child_ctx)
        child_ctx.pop()
        return result


class RuleTemplateEngine:
    """Engine for processing rule templates with variable substitution,
    conditionals, loops, includes, and imports."""

    def __init__(
        self,
        config: Optional[TemplateSyntaxConfig] = None,
        template_dirs: Optional[List[str]] = None,
        custom_filters: Optional[Dict[str, Callable[[Any], str]]] = None,
        max_cache_size: int = 256,
    ) -> None:
        self.config = config or TemplateSyntaxConfig()
        self.template_dirs = template_dirs or []
        self.custom_filters = custom_filters or {}
        self.max_cache_size = max_cache_size

        self._lexer = TemplateLexer(self.config)
        self._parser = TemplateParser(self.config)
        self._cache: Dict[str, TemplateCacheEntry] = OrderedDict()
        self._loaded_imports: Dict[str, List[Any]] = {}
        self._variable_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
        self._filter_pattern = re.compile(r"^\s*([\w.]+)\s*(\|.*)?$")
        self._setup_default_filters()

    def _setup_default_filters(self) -> None:
        """Register built-in template filters."""
        self.custom_filters.setdefault("upper", lambda v: str(v).upper())
        self.custom_filters.setdefault("lower", lambda v: str(v).lower())
        self.custom_filters.setdefault("capitalize", lambda v: str(v).capitalize())
        self.custom_filters.setdefault("title", lambda v: str(v).title())
        self.custom_filters.setdefault("trim", lambda v: str(v).strip())
        self.custom_filters.setdefault("reverse", lambda v: str(v)[::-1])
        self.custom_filters.setdefault("length", lambda v: str(len(v)))
        self.custom_filters.setdefault("json", lambda v: str(v))
        self.custom_filters.setdefault("bool", lambda v: "true" if v else "false")
        self.custom_filters.setdefault("quote", lambda v: f'"{v}"')
        self.custom_filters.setdefault("default", lambda v: v if v else "")

    def register_filter(self, name: str, func: Callable[[Any], str]) -> None:
        """Register a custom template filter."""
        self.custom_filters[name] = func

    def add_template_directory(self, directory: str) -> None:
        """Add a directory to the template search path."""
        if directory not in self.template_dirs:
            self.template_dirs.append(directory)

    def compile_template(self, source: str, template_name: str = "<string>") -> List[Any]:
        """Compile a template string into an AST, with caching."""
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if template_name in self._cache:
            entry = self._cache[template_name]
            if entry.source_hash == source_hash:
                entry.access_count += 1
                self._cache.move_to_end(template_name)
                return entry.ast

        tokens = self._lexer.tokenize(source)
        ast = self._parser.parse(tokens)
        deps = self._extract_dependencies(ast)

        entry = TemplateCacheEntry(
            ast=ast,
            source_hash=source_hash,
            compiled_time=0.0,
            dependencies=deps,
        )
        self._add_to_cache(template_name, entry)
        return ast

    def _add_to_cache(self, name: str, entry: TemplateCacheEntry) -> None:
        """Add an entry to the template cache, evicting oldest if full."""
        if name in self._cache:
            self._cache.move_to_end(name)
        self._cache[name] = entry
        if len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)

    def _extract_dependencies(self, ast: List[Any]) -> Set[str]:
        """Extract template dependency names from the AST."""
        deps: Set[str] = set()
        for node in ast:
            if isinstance(node, IncludeNode):
                deps.add(node.template_name)
            elif isinstance(node, ImportNode):
                deps.add(node.template_name)
            elif isinstance(node, (ConditionalNode, LoopNode)):
                child_deps = self._extract_dependencies(
                    node.body + getattr(node, "else_body", [])
                )
                deps.update(child_deps)
        return deps

    def render_template(
        self,
        template_name: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render a named template with the given variables."""
        source = self._load_template_source(template_name)
        if source is None:
            raise TemplateIncludeError(
                f"Template '{template_name}' not found in any template directory"
            )
        ast = self.compile_template(source, template_name)
        context = TemplateContext(variables=variables or {})
        return self._render_nodes(ast, context)

    def render_string(
        self,
        source: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render a template string with the given variables."""
        ast = self.compile_template(source)
        context = TemplateContext(variables=variables or {})
        return self._render_nodes(ast, context)

    def _render_nodes(self, nodes: List[Any], context: TemplateContext) -> str:
        """Render a list of AST nodes into a string."""
        parts: List[str] = []
        for node in nodes:
            try:
                result = node.render(context, self)
                parts.append(result)
            except TemplateError:
                raise
            except Exception as exc:
                raise TemplateError(
                    f"Error rendering node {type(node).__name__}: {exc}"
                ) from exc
        return "".join(parts)

    def _resolve_variable(self, expression: str, context: TemplateContext) -> Any:
        """Resolve a variable expression against the context with filter support."""
        expression = expression.strip()
        pipe_parts = [p.strip() for p in expression.split("|")]
        var_expr = pipe_parts[0]
        filters = pipe_parts[1:]

        value: Any = None
        if self._variable_pattern.match(var_expr):
            parts = var_expr.split(".")
            current = context
            for part in parts:
                if isinstance(current, TemplateContext):
                    value = current.get(part)
                    if value is None and not current.has(part):
                        return None
                    current = value
                elif isinstance(current, dict):
                    if part in current:
                        value = current[part]
                    else:
                        return None
                    current = value
                elif hasattr(current, part):
                    value = getattr(current, part)
                    current = value
                else:
                    return None
        else:
            try:
                value = eval(var_expr, {"__builtins__": {}}, context.variables)
            except Exception:
                return None

        for filter_name in filters:
            filter_name = filter_name.strip()
            filter_func = self.custom_filters.get(filter_name)
            if filter_func is None:
                raise TemplateVariableError(f"Unknown filter '{filter_name}'")
            try:
                value = filter_func(value)
            except Exception as exc:
                raise TemplateVariableError(
                    f"Filter '{filter_name}' failed: {exc}"
                ) from exc

        return value

    def _evaluate_condition(self, condition: str, context: TemplateContext) -> bool:
        """Evaluate a conditional expression against the context."""
        condition = condition.strip()
        resolved_condition = self._resolve_condition_variables(condition, context)
        try:
            safe_dict: Dict[str, Any] = {
                "True": True, "False": False, "None": None,
                "and": lambda a, b: a and b,
                "or": lambda a, b: a or b,
                "not": lambda a: not a,
                "in": lambda a, b: a in b,
                "is": lambda a, b: a is b,
            }
            safe_dict.update(context.variables)
            result = eval(resolved_condition, {"__builtins__": {}}, safe_dict)
            return bool(result)
        except Exception as exc:
            logger.warning("Condition evaluation failed: '%s' - %s", condition, exc)
            return False

    def _resolve_condition_variables(self, condition: str, context: TemplateContext) -> str:
        """Replace variables in condition string with their actual values."""
        def replace_var(match: re.Match) -> str:
            var_name = match.group(1)
            value = context.get(var_name)
            if value is None:
                if self.config.undefined_behavior == "strict":
                    raise TemplateVariableError(
                        f"Variable '{var_name}' is undefined in condition"
                    )
                return "None"
            if isinstance(value, str):
                return repr(value)
            return str(value)

        var_pattern = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")
        processed = condition
        for var_name in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", condition):
            if var_name in ("True", "False", "None", "and", "or", "not", "in", "is"):
                continue
            if context.has(var_name):
                value = context.get(var_name)
                if isinstance(value, str):
                    processed = re.sub(
                        rf"\b{re.escape(var_name)}\b",
                        repr(value),
                        processed,
                        count=1,
                    )
                else:
                    processed = re.sub(
                        rf"\b{re.escape(var_name)}\b",
                        str(value),
                        processed,
                        count=1,
                    )
        return processed

    def _load_template_source(self, template_name: str) -> Optional[str]:
        """Load template source from registered template directories."""
        for directory in self.template_dirs:
            candidate = os.path.join(directory, template_name)
            if not candidate.endswith((".yaml", ".yml", ".j2", ".template", ".txt")):
                yaml_path = candidate + ".yaml"
                if os.path.isfile(yaml_path):
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        return f.read()
            if os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return f.read()
        return None

    def _load_imported_template(self, template_name: str) -> Optional[List[Any]]:
        """Load and cache an imported template's AST."""
        if template_name in self._loaded_imports:
            return self._loaded_imports[template_name]
        source = self._load_template_source(template_name)
        if source is None:
            return None
        ast = self.compile_template(source, template_name)
        self._loaded_imports[template_name] = ast
        return ast

    def invalidate_cache(self, template_name: Optional[str] = None) -> None:
        """Invalidate template cache for a specific or all templates."""
        if template_name is None:
            self._cache.clear()
            self._loaded_imports.clear()
        else:
            self._cache.pop(template_name, None)
            self._loaded_imports.pop(template_name, None)

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the current cache state."""
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self.max_cache_size,
            "loaded_imports": len(self._loaded_imports),
            "template_names": list(self._cache.keys()),
            "template_dirs": list(self.template_dirs),
        }

    def validate_syntax(self, source: str) -> List[Dict[str, Any]]:
        """Validate template syntax and return list of errors."""
        errors: List[Dict[str, Any]] = []
        try:
            tokens = self._lexer.tokenize(source)
            self._parser.parse(tokens)
        except TemplateSyntaxError as exc:
            errors.append({
                "type": "syntax_error",
                "message": str(exc),
                "line": getattr(exc, "line", 0),
                "column": getattr(exc, "column", 0),
            })
        except TemplateError as exc:
            errors.append({
                "type": "template_error",
                "message": str(exc),
            })
        return errors

    def analyze_template(self, source: str) -> Dict[str, Any]:
        """Analyze a template and return metadata about its structure."""
        tokens = self._lexer.tokenize(source)
        ast = self._parser.parse(tokens)

        variable_count = 0
        conditional_count = 0
        loop_count = 0
        include_count = 0
        import_count = 0
        variables: Set[str] = set()

        def _count_nodes(nodes: List[Any]) -> None:
            nonlocal variable_count, conditional_count, loop_count
            nonlocal include_count, import_count

            for node in nodes:
                if isinstance(node, VariableNode):
                    variable_count += 1
                    variables.add(node.expression)
                elif isinstance(node, ConditionalNode):
                    conditional_count += 1
                    _count_nodes(node.body)
                    _count_nodes(node.else_body)
                elif isinstance(node, LoopNode):
                    loop_count += 1
                    _count_nodes(node.body)
                elif isinstance(node, IncludeNode):
                    include_count += 1
                elif isinstance(node, ImportNode):
                    import_count += 1

        _count_nodes(ast)

        return {
            "total_nodes": len(ast),
            "variable_count": variable_count,
            "conditional_count": conditional_count,
            "loop_count": loop_count,
            "include_count": include_count,
            "import_count": import_count,
            "variables": sorted(variables),
            "has_conditionals": conditional_count > 0,
            "has_loops": loop_count > 0,
            "has_includes": include_count > 0,
            "has_imports": import_count > 0,
        }
