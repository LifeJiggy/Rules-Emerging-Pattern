"""
Rule template validator - schema validation, syntax checking, semantic validation,
cross-template reference validation, and detailed reporting.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import jsonschema
import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

from .template_engine import RuleTemplateEngine, TemplateSyntaxConfig

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity levels for validation findings."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


class ValidationCategory(str, Enum):
    """Categories of validation checks."""
    SYNTAX = "syntax"
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    CROSS_REFERENCE = "cross_reference"
    TYPE = "type"
    BOUNDARY = "boundary"
    CONSISTENCY = "consistency"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class ValidationFinding:
    """Individual validation finding with details."""
    severity: ValidationSeverity
    category: ValidationCategory
    code: str
    message: str
    template_name: str
    line: int = 0
    column: int = 0
    field_path: Optional[str] = None
    suggested_fix: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert finding to dictionary for serialization."""
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "template_name": self.template_name,
            "line": self.line,
            "column": self.column,
            "field_path": self.field_path,
            "suggested_fix": self.suggested_fix,
            "context": self.context,
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        prefix = f"[{self.severity.value.upper()}] {self.code}"
        location = f"in '{self.template_name}'"
        if self.line > 0:
            location += f" at line {self.line}"
            if self.column > 0:
                location += f", column {self.column}"
        return f"{prefix} {location}: {self.message}"


@dataclass
class ValidationReport:
    """Complete validation report with summary statistics."""
    findings: List[ValidationFinding] = field(default_factory=list)
    template_name: str = ""
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    warnings: int = 0
    info_messages: int = 0
    suggestions: int = 0
    validation_time_ms: float = 0.0
    schema_version: str = "1.0.0"
    validated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if validation passed (no errors)."""
        return self.findings_count_by_severity(ValidationSeverity.ERROR) == 0

    @property
    def has_warnings(self) -> bool:
        """Check if report contains warnings."""
        return self.warnings > 0

    def add_finding(self, finding: ValidationFinding) -> None:
        """Add a finding and update summary counts."""
        self.findings.append(finding)
        self.failed_checks += 1
        if finding.severity == ValidationSeverity.ERROR:
            self.passed_checks = max(0, self.total_checks - self.failed_checks)
        elif finding.severity == ValidationSeverity.WARNING:
            self.warnings += 1
        elif finding.severity == ValidationSeverity.INFO:
            self.info_messages += 1
        elif finding.severity == ValidationSeverity.SUGGESTION:
            self.suggestions += 1

    def add_pass(self) -> None:
        """Record a passed check."""
        self.total_checks += 1
        self.passed_checks += 1

    def findings_count_by_severity(self, severity: ValidationSeverity) -> int:
        """Count findings of a specific severity."""
        return sum(1 for f in self.findings if f.severity == severity)

    def findings_by_category(self, category: ValidationCategory) -> List[ValidationFinding]:
        """Get all findings in a specific category."""
        return [f for f in self.findings if f.category == category]

    def merge(self, other: "ValidationReport") -> "ValidationReport":
        """Merge another report into this one."""
        self.findings.extend(other.findings)
        self.total_checks += other.total_checks
        self.passed_checks += other.passed_checks
        self.failed_checks += other.failed_checks
        self.warnings += other.warnings
        self.info_messages += other.info_messages
        self.suggestions += other.suggestions
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialize report to dictionary."""
        return {
            "template_name": self.template_name,
            "passed": self.passed,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "total_checks": self.total_checks,
            "warnings": self.warnings,
            "info_messages": self.info_messages,
            "suggestions": self.suggestions,
            "validation_time_ms": self.validation_time_ms,
            "schema_version": self.schema_version,
            "validated_at": self.validated_at.isoformat(),
            "findings": [f.to_dict() for f in self.findings],
        }

    def summary(self) -> str:
        """Generate a human-readable summary string."""
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Validation {status} for '{self.template_name}'",
            f"  Checks: {self.total_checks} total, {self.passed_checks} passed, "
            f"{len(self.findings)} failed ({self.warnings} warnings, "
            f"{self.info_messages} info, {self.suggestions} suggestions)",
            f"  Time: {self.validation_time_ms:.1f}ms",
        ]
        if self.findings:
            lines.append("  Findings:")
            for finding in self.findings:
                lines.append(f"    {finding}")
        return "\n".join(lines)


class TemplateSchema:
    """Schema definition for validating template structure and content."""

    def __init__(
        self,
        schema_def: Optional[Dict[str, Any]] = None,
        schema_file: Optional[str] = None,
    ) -> None:
        self.schema_def: Dict[str, Any] = schema_def or self._default_schema()
        if schema_file:
            self._load_schema_file(schema_file)

    def _default_schema(self) -> Dict[str, Any]:
        """Return the default JSON schema for rule templates."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "RuleTemplate",
            "type": "object",
            "required": ["name", "description", "tier", "rule_type", "pattern"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 256},
                "description": {"type": "string", "minLength": 1, "maxLength": 4096},
                "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                "tier": {
                    "type": "string",
                    "enum": [t.value for t in RuleTier],
                },
                "rule_type": {
                    "type": "string",
                    "enum": [t.value for t in RuleType],
                },
                "severity": {
                    "type": "string",
                    "enum": [s.value for s in RuleSeverity],
                },
                "enforcement_level": {
                    "type": "string",
                    "enum": [e.value for e in EnforcementLevel],
                },
                "status": {
                    "type": "string",
                    "enum": [s.value for s in RuleStatus],
                },
                "pattern": {
                    "type": "object",
                    "required": ["type", "keywords"],
                    "properties": {
                        "type": {"type": "string"},
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "regex_patterns": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "confidence_threshold": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "action": {"type": "string"},
                    },
                },
                "conditions": {"type": "object"},
                "exceptions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                },
                "priority": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                },
                "metadata": {"type": "object"},
                "variables": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "string", "integer", "float", "boolean",
                                    "list", "dict", "any",
                                ],
                            },
                            "required": {"type": "boolean"},
                            "default": {},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "type"],
                    },
                },
                "imports": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

    def _load_schema_file(self, schema_file: str) -> None:
        """Load schema definition from a file."""
        path = Path(schema_file)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")
        content = path.read_text(encoding="utf-8")
        if schema_file.endswith((".yaml", ".yml")):
            self.schema_def = yaml.safe_load(content)
        elif schema_file.endswith(".json"):
            self.schema_def = json.loads(content)
        else:
            raise ValueError(f"Unsupported schema file format: {schema_file}")

    def validate(self, template_data: Dict[str, Any]) -> List[ValidationFinding]:
        """Validate template data against the schema."""
        findings: List[ValidationFinding] = []
        try:
            jsonschema.validate(template_data, self.schema_def)
        except jsonschema.exceptions.ValidationError as exc:
            finding = ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SCHEMA,
                code="SCHEMA_VIOLATION",
                message=str(exc.message),
                template_name=template_data.get("name", "<unknown>"),
                field_path=".".join(str(p) for p in exc.path) if exc.path else None,
            )
            findings.append(finding)
            if exc.context:
                for cause in exc.context:
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SCHEMA,
                        code="SCHEMA_CAUSE",
                        message=str(cause.message),
                        template_name=template_data.get("name", "<unknown>"),
                        field_path=".".join(str(p) for p in cause.path) if cause.path else None,
                    ))
        except jsonschema.exceptions.SchemaError as exc:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SCHEMA,
                code="SCHEMA_DEFINITION_ERROR",
                message=f"Schema definition error: {exc}",
                template_name=template_data.get("name", "<unknown>"),
            ))
        return findings


class TemplateSyntaxValidator:
    """Validates template syntax - balanced tags, valid constructs."""

    def __init__(self, engine: RuleTemplateEngine) -> None:
        self.engine = engine

    def validate(self, source: str, template_name: str = "<string>") -> List[ValidationFinding]:
        """Validate template syntax and return findings."""
        findings: List[ValidationFinding] = []

        block_stack: List[Tuple[str, int, int]] = []
        lines = source.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            if_match = re.match(
                r"\{%\s*if\s+(.+?)\s*%\}", stripped, re.IGNORECASE
            )
            if if_match:
                block_stack.append(("if", line_num, 0))
                cond_findings = self._validate_condition_expression(
                    if_match.group(1), template_name, line_num
                )
                findings.extend(cond_findings)
                continue

            if re.match(r"\{%\s*else\s*%\}", stripped, re.IGNORECASE):
                if not block_stack or block_stack[-1][0] != "if":
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="UNEXPECTED_ELSE",
                        message="Unexpected {% else %} without matching {% if %}",
                        template_name=template_name,
                        line=line_num,
                    ))
                continue

            if re.match(r"\{%\s*endif\s*%\}", stripped, re.IGNORECASE):
                if not block_stack:
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="UNEXPECTED_ENDIF",
                        message="Unexpected {% endif %} without matching {% if %}",
                        template_name=template_name,
                        line=line_num,
                    ))
                elif block_stack[-1][0] != "if":
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="MISMATCHED_ENDIF",
                        message=f"Mismatched {{% endif %}}: expected {{% end{block_stack[-1][0]} %}}",
                        template_name=template_name,
                        line=line_num,
                    ))
                else:
                    block_stack.pop()
                continue

            for_match = re.match(
                r"\{%\s*for\s+(\w+)\s+in\s+(.+?)\s*%\}", stripped, re.IGNORECASE
            )
            if for_match:
                block_stack.append(("for", line_num, 0))
                var_name = for_match.group(1)
                collection = for_match.group(2).strip()
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", var_name):
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="INVALID_LOOP_VARIABLE",
                        message=f"Invalid loop variable name: '{var_name}'",
                        template_name=template_name,
                        line=line_num,
                    ))
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", collection):
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.WARNING,
                        category=ValidationCategory.SYNTAX,
                        code="SUSPICIOUS_COLLECTION",
                        message=f"Collection expression '{collection}' may not be valid",
                        template_name=template_name,
                        line=line_num,
                    ))
                continue

            if re.match(r"\{%\s*endfor\s*%\}", stripped, re.IGNORECASE):
                if not block_stack:
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="UNEXPECTED_ENDFOR",
                        message="Unexpected {% endfor %} without matching {% for %}",
                        template_name=template_name,
                        line=line_num,
                    ))
                elif block_stack[-1][0] != "for":
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="MISMATCHED_ENDFOR",
                        message=f"Mismatched {{% endfor %}}: expected {{% end{block_stack[-1][0]} %}}",
                        template_name=template_name,
                        line=line_num,
                    ))
                else:
                    block_stack.pop()
                continue

            include_match = re.match(
                r"\{%\s*include\s+[\"'](.+?)[\"']\s*%\}", stripped, re.IGNORECASE
            )
            if include_match:
                template_path = include_match.group(1)
                if not template_path.endswith((".yaml", ".yml", ".j2", ".template")):
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.WARNING,
                        category=ValidationCategory.SYNTAX,
                        code="UNUSUAL_TEMPLATE_EXTENSION",
                        message=f"Included template '{template_path}' has unusual extension",
                        template_name=template_name,
                        line=line_num,
                        suggested_fix="Use .yaml, .yml, .j2, or .template extension",
                    ))
                continue

            var_matches = re.findall(r"\{\{(.+?)\}\}", line)
            for var_expr in var_matches:
                var_expr = var_expr.strip()
                pipe_parts = var_expr.split("|")
                var_name = pipe_parts[0].strip()
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*(\[.*?\])*$", var_name):
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SYNTAX,
                        code="INVALID_VARIABLE_SYNTAX",
                        message=f"Invalid variable expression: '{var_name}'",
                        template_name=template_name,
                        line=line_num,
                    ))
                for filter_part in pipe_parts[1:]:
                    filter_name = filter_part.strip()
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", filter_name):
                        findings.append(ValidationFinding(
                            severity=ValidationSeverity.WARNING,
                            category=ValidationCategory.SYNTAX,
                            code="INVALID_FILTER",
                            message=f"Invalid filter name: '{filter_name}'",
                            template_name=template_name,
                            line=line_num,
                        ))

        for block_type, block_line, _ in reversed(block_stack):
            findings.append(ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SYNTAX,
                code="UNCLOSED_BLOCK",
                message=f"Unclosed {{% {block_type} %}} block opened at line {block_line}",
                template_name=template_name,
                line=block_line,
                suggested_fix=f"Add {{% end{block_type} %}} to close the block",
            ))

        return findings

    def _validate_condition_expression(
        self, condition: str, template_name: str, line_num: int
    ) -> List[ValidationFinding]:
        """Validate a condition expression syntax."""
        findings: List[ValidationFinding] = []
        condition = condition.strip()

        if not condition:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SYNTAX,
                code="EMPTY_CONDITION",
                message="Condition expression is empty",
                template_name=template_name,
                line=line_num,
            ))
            return findings

        open_parens = condition.count("(")
        close_parens = condition.count(")")
        if open_parens != close_parens:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SYNTAX,
                code="UNBALANCED_PARENS",
                message=f"Unbalanced parentheses in condition: "
                        f"{open_parens} open, {close_parens} close",
                template_name=template_name,
                line=line_num,
            ))

        invalid_chars = re.findall(r"[^a-zA-Z0-9_\.\s\(\)!=<>&|]+", condition)
        if invalid_chars:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.SYNTAX,
                code="SUSPICIOUS_CONDITION_CHARS",
                message=f"Unusual characters in condition: {set(invalid_chars)}",
                template_name=template_name,
                line=line_num,
            ))

        operators = ["==", "!=", "<=", ">=", "<", ">", "&&", r"\|\|", "and", "or", "not", "in"]
        has_operator = any(re.search(rf"\b{op}\b", condition) if op.isalpha() else op in condition
                          for op in operators)
        if not has_operator and len(condition.split()) == 1:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.INFO,
                category=ValidationCategory.SYNTAX,
                code="SIMPLE_CONDITION",
                message=f"Condition is a single variable '{condition}' - evaluates as truthy",
                template_name=template_name,
                line=line_num,
            ))

        return findings


class TemplateSemanticValidator:
    """Validates template semantics - variable existence, type matching, etc."""

    def __init__(self, engine: RuleTemplateEngine) -> None:
        self.engine = engine

    def validate(
        self,
        source: str,
        template_name: str = "<string>",
        expected_variables: Optional[Dict[str, str]] = None,
    ) -> List[ValidationFinding]:
        """Validate template semantics."""
        findings: List[ValidationFinding] = []
        expected_vars = expected_variables or {}

        analysis = self.engine.analyze_template(source)
        used_vars: Set[str] = set(analysis.get("variables", []))

        for var_name in used_vars:
            base_var = var_name.split(".")[0]
            if base_var in expected_vars:
                expected_type = expected_vars[base_var]
                self._check_variable_usage(
                    source, base_var, expected_type, template_name, findings
                )
            elif base_var not in ("loop", "block", "super", "self"):
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.WARNING,
                    category=ValidationCategory.SEMANTIC,
                    code="UNDECLARED_VARIABLE",
                    message=f"Variable '{base_var}' used but not declared in template variables section",
                    template_name=template_name,
                    suggested_fix=f"Add '{base_var}' to the template's variables definition",
                ))

        included_templates = analysis.get("variables", [])
        include_count = analysis.get("include_count", 0)
        if include_count > 0 and not expected_vars.get("_includes_loaded"):
            pass

        conditional_count = analysis.get("conditional_count", 0)
        if conditional_count > 10:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.SEMANTIC,
                code="HIGH_CONDITIONAL_COMPLEXITY",
                message=f"Template has {conditional_count} conditionals - consider simplifying",
                template_name=template_name,
                suggested_fix="Extract complex conditionals into sub-templates or simplify logic",
            ))

        loop_count = analysis.get("loop_count", 0)
        if loop_count > 5:
            findings.append(ValidationFinding(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.SEMANTIC,
                code="HIGH_LOOP_COMPLEXITY",
                message=f"Template has {loop_count} loops - consider refactoring",
                template_name=template_name,
                suggested_fix="Nested loops may impact rendering performance",
            ))

        return findings

    def _check_variable_usage(
        self,
        source: str,
        var_name: str,
        expected_type: str,
        template_name: str,
        findings: List[ValidationFinding],
    ) -> None:
        """Check that a variable is used in a type-consistent way."""
        type_indicators = {
            "string": [r"\|upper", r"\|lower", r"\|capitalize", r"\|trim"],
            "integer": ["==", "!=", "<", ">", "<=", ">=", "+", "-", "*", "/"],
            "boolean": ["not", "and", "or"],
            "list": [r"\|length", r"\|first", r"\|last", r"\bfor\s+\w+\s+in"],
            "dict": [r"\.\w+", r"\bk\s+in"],
        }

        if expected_type in type_indicators:
            indicators = type_indicators[expected_type]
            found_match = any(
                re.search(pattern, source) for pattern in indicators
            )
            if not found_match:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.INFO,
                    category=ValidationCategory.SEMANTIC,
                    code="POSSIBLE_TYPE_MISMATCH",
                    message=f"Variable '{var_name}' declared as '{expected_type}' "
                            f"but no type-typical operations detected",
                    template_name=template_name,
                ))

    def validate_template_data(
        self,
        template_data: Dict[str, Any],
        template_name: str = "<unknown>",
    ) -> List[ValidationFinding]:
        """Validate the semantic content of parsed template data."""
        findings: List[ValidationFinding] = []

        if "name" in template_data:
            name = template_data["name"]
            if len(name) > 200:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.WARNING,
                    category=ValidationCategory.SEMANTIC,
                    code="LONG_TEMPLATE_NAME",
                    message=f"Template name '{name}' is excessively long ({len(name)} chars)",
                    template_name=template_name,
                    suggested_fix="Keep template names under 200 characters",
                ))

        if "tier" in template_data and "rule_type" in template_data:
            tier = template_data.get("tier")
            rule_type = template_data.get("rule_type")
            tier_type_restrictions = {
                RuleTier.SAFETY.value: [
                    RuleType.CONTENT_FILTERING.value,
                    RuleType.COMPLIANCE_CHECK.value,
                ],
                RuleTier.OPERATIONAL.value: [
                    RuleType.PATTERN_MATCHING.value,
                    RuleType.STRUCTURAL_VALIDATION.value,
                    RuleType.QUALITY_ASSESSMENT.value,
                ],
            }
            restricted = tier_type_restrictions.get(tier, [])
            if restricted and rule_type not in restricted:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.WARNING,
                    category=ValidationCategory.SEMANTIC,
                    code="TIER_TYPE_MISMATCH",
                    message=f"Rule type '{rule_type}' may not be appropriate for tier '{tier}'",
                    template_name=template_name,
                    suggested_fix=f"Consider using one of: {restricted}",
                ))

        if "version" in template_data:
            version = template_data["version"]
            version_pattern = re.compile(r"^\d+\.\d+\.\d+$")
            if not version_pattern.match(version):
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.SEMANTIC,
                    code="INVALID_VERSION_FORMAT",
                    message=f"Version '{version}' does not follow semver (X.Y.Z)",
                    template_name=template_name,
                    suggested_fix="Use semantic versioning format: major.minor.patch (e.g. 1.0.0)",
                ))

        if "variables" in template_data:
            declared_names: Set[str] = set()
            for var_def in template_data["variables"]:
                var_name = var_def.get("name", "")
                if var_name in declared_names:
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.SEMANTIC,
                        code="DUPLICATE_VARIABLE_DECLARATION",
                        message=f"Variable '{var_name}' declared multiple times",
                        template_name=template_name,
                    ))
                declared_names.add(var_name)

        if "tags" in template_data:
            tags = template_data["tags"]
            if len(tags) != len(set(tags)):
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.WARNING,
                    category=ValidationCategory.SEMANTIC,
                    code="DUPLICATE_TAGS",
                    message="Template contains duplicate tags",
                    template_name=template_name,
                ))
            for tag in tags:
                if ":" in tag and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*:", tag):
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.WARNING,
                        category=ValidationCategory.SEMANTIC,
                        code="UNUSUAL_TAG_FORMAT",
                        message=f"Tag '{tag}' has unusual format",
                        template_name=template_name,
                    ))

        if "description" in template_data:
            desc = template_data["description"]
            if len(desc) < 10:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.WARNING,
                    category=ValidationCategory.SEMANTIC,
                    code="SHORT_DESCRIPTION",
                    message="Template description is very short",
                    template_name=template_name,
                    suggested_fix="Provide a more descriptive explanation of this template's purpose",
                ))

        return findings


class CrossTemplateValidator:
    """Validates cross-template references and consistency."""

    def __init__(self, template_index: Dict[str, Dict[str, Any]]) -> None:
        self.template_index = template_index

    def validate(
        self, template_name: str, template_data: Dict[str, Any]
    ) -> List[ValidationFinding]:
        """Cross-validate a template against all indexed templates."""
        findings: List[ValidationFinding] = []

        imports = template_data.get("imports", [])
        for import_ref in imports:
            if import_ref not in self.template_index:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.CROSS_REFERENCE,
                    code="MISSING_IMPORT",
                    message=f"Template imports '{import_ref}' which is not registered",
                    template_name=template_name,
                    suggested_fix=f"Ensure '{import_ref}' exists or remove the import",
                ))
            else:
                imported_imports = self.template_index[import_ref].get("imports", [])
                if template_name in imported_imports:
                    findings.append(ValidationFinding(
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.CROSS_REFERENCE,
                        code="CIRCULAR_IMPORT",
                        message=f"Circular import detected: '{template_name}' "
                                f"<-> '{import_ref}'",
                        template_name=template_name,
                    ))

        if "extends" in template_data:
            parent_name = template_data["extends"]
            if parent_name not in self.template_index:
                findings.append(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.CROSS_REFERENCE,
                    code="MISSING_PARENT",
                    message=f"Template extends '{parent_name}' which does not exist",
                    template_name=template_name,
                ))
            else:
                parent = self.template_index[parent_name]
                if "overridable" in parent:
                    overridable = parent.get("overridable", [])
                    for field in template_data.get("overrides", []):
                        if field not in overridable:
                            findings.append(ValidationFinding(
                                severity=ValidationSeverity.WARNING,
                                category=ValidationCategory.CROSS_REFERENCE,
                                code="NON_OVERRIDABLE_FIELD",
                                message=f"Field '{field}' is not declared overridable in parent",
                                template_name=template_name,
                            ))

        if "tags" in template_data:
            template_tags = set(template_data["tags"])
            for other_name, other_data in self.template_index.items():
                if other_name == template_name:
                    continue
                if "tags" in other_data:
                    common_tags = template_tags & set(other_data["tags"])
                    if len(common_tags) > 0:
                        if template_data.get("tier") != other_data.get("tier"):
                            shared_tags_str = ", ".join(sorted(common_tags)[:5])
                            findings.append(ValidationFinding(
                                severity=ValidationSeverity.INFO,
                                category=ValidationCategory.CROSS_REFERENCE,
                                code="SHARED_TAGS_DIFFERENT_TIER",
                                message=f"Shares tags [{shared_tags_str}] with "
                                        f"'{other_name}' but has different tier",
                                template_name=template_name,
                            ))

        return findings


class RuleTemplateValidator:
    """Main validator orchestrating all validation checks for rule templates."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        engine: Optional[RuleTemplateEngine] = None,
        schema: Optional[TemplateSchema] = None,
    ) -> None:
        self.config = config or self._default_config()
        self.engine = engine or RuleTemplateEngine()
        self.schema = schema or TemplateSchema()
        self._lock = Lock()
        self._template_index: Dict[str, Dict[str, Any]] = {}

        self._syntax_validator = TemplateSyntaxValidator(self.engine)
        self._semantic_validator = TemplateSemanticValidator(self.engine)
        self._cross_validator = CrossTemplateValidator(self._template_index)

    def _default_config(self) -> Dict[str, Any]:
        """Return the default validator configuration."""
        return {
            "strict_mode": True,
            "max_findings_per_template": 100,
            "validate_syntax": True,
            "validate_schema": True,
            "validate_semantics": True,
            "validate_cross_references": True,
            "check_circular_imports": True,
            "check_unused_variables": True,
            "max_variable_depth": 5,
            "allowed_filters": [
                "upper", "lower", "capitalize", "title", "trim",
                "reverse", "length", "json", "default", "escape",
            ],
            "warn_on_deprecated_features": True,
            "version_compatibility": ">=1.0.0",
            "schema_version": "1.0.0",
        }

    def register_template(self, name: str, data: Dict[str, Any]) -> None:
        """Register a template in the index for cross-referencing."""
        with self._lock:
            self._template_index[name] = data

    def unregister_template(self, name: str) -> None:
        """Remove a template from the index."""
        with self._lock:
            self._template_index.pop(name, None)

    def build_index(self, templates: Dict[str, Dict[str, Any]]) -> None:
        """Build or rebuild the template index."""
        with self._lock:
            self._template_index.clear()
            self._template_index.update(templates)
            self._cross_validator = CrossTemplateValidator(self._template_index)

    def validate_source(
        self,
        source: str,
        template_name: str = "<string>",
        expected_variables: Optional[Dict[str, str]] = None,
    ) -> ValidationReport:
        """Validate a template source string."""
        start_time = time.time()
        report = ValidationReport(template_name=template_name)

        if self.config.get("validate_syntax", True):
            report.total_checks += 1
            syntax_findings = self._syntax_validator.validate(source, template_name)
            for finding in syntax_findings:
                report.add_finding(finding)
            if not syntax_findings:
                report.add_pass()

        if self.config.get("validate_semantics", True):
            report.total_checks += 1
            semantic_findings = self._semantic_validator.validate(
                source, template_name, expected_variables
            )
            for finding in semantic_findings:
                report.add_finding(finding)
            if not semantic_findings:
                report.add_pass()

        report.validation_time_ms = (time.time() - start_time) * 1000
        return report

    def validate_data(
        self,
        template_data: Dict[str, Any],
        template_name: str = "<unknown>",
    ) -> ValidationReport:
        """Validate parsed template data."""
        start_time = time.time()
        report = ValidationReport(template_name=template_name)

        if self.config.get("validate_schema", True):
            report.total_checks += 1
            schema_findings = self.schema.validate(template_data)
            for finding in schema_findings:
                report.add_finding(finding)
            if not schema_findings:
                report.add_pass()

        if self.config.get("validate_semantics", True):
            report.total_checks += 1
            semantic_findings = self._semantic_validator.validate_template_data(
                template_data, template_name
            )
            for finding in semantic_findings:
                report.add_finding(finding)
            if not semantic_findings:
                report.add_pass()

        if self.config.get("validate_cross_references", True) and self._template_index:
            report.total_checks += 1
            cross_findings = self._cross_validator.validate(template_name, template_data)
            for finding in cross_findings:
                report.add_finding(finding)
            if not cross_findings:
                report.add_pass()

        report.validation_time_ms = (time.time() - start_time) * 1000
        return report

    def validate_template(
        self,
        template_name: str,
        source: str,
        template_data: Optional[Dict[str, Any]] = None,
        expected_variables: Optional[Dict[str, str]] = None,
    ) -> ValidationReport:
        """Comprehensive validation of both source and data."""
        report = self.validate_source(source, template_name, expected_variables)

        if template_data:
            data_report = self.validate_data(template_data, template_name)
            report.merge(data_report)

        return report

    def validate_all(
        self,
        templates: Dict[str, Tuple[str, Optional[Dict[str, Any]]]],
    ) -> Dict[str, ValidationReport]:
        """Validate multiple templates and return reports."""
        reports: Dict[str, ValidationReport] = {}
        for name, (source, data) in templates.items():
            reports[name] = self.validate_template(name, source, data)
        return reports

    def validate_file(
        self, file_path: str, expected_variables: Optional[Dict[str, str]] = None
    ) -> ValidationReport:
        """Validate a template file."""
        path = Path(file_path)
        if not path.exists():
            report = ValidationReport(template_name=path.name)
            report.add_finding(ValidationFinding(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.SCHEMA,
                code="FILE_NOT_FOUND",
                message=f"Template file not found: {file_path}",
                template_name=path.name,
            ))
            return report

        source = path.read_text(encoding="utf-8")
        template_data: Optional[Dict[str, Any]] = None
        if file_path.endswith((".yaml", ".yml")):
            try:
                template_data = yaml.safe_load(source)
            except yaml.YAMLError as exc:
                report = ValidationReport(template_name=path.name)
                report.add_finding(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.SCHEMA,
                    code="YAML_PARSE_ERROR",
                    message=f"Failed to parse YAML: {exc}",
                    template_name=path.name,
                ))
                return report
        elif file_path.endswith(".json"):
            try:
                template_data = json.loads(source)
            except json.JSONDecodeError as exc:
                report = ValidationReport(template_name=path.name)
                report.add_finding(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.SCHEMA,
                    code="JSON_PARSE_ERROR",
                    message=f"Failed to parse JSON: {exc}",
                    template_name=path.name,
                ))
                return report

        return self.validate_template(path.name, source, template_data, expected_variables)

    def validate_directory(
        self,
        directory_path: str,
        pattern: str = "*.yaml",
        recursive: bool = True,
    ) -> Dict[str, ValidationReport]:
        """Validate all template files in a directory."""
        reports: Dict[str, ValidationReport] = {}
        path = Path(directory_path)
        if not path.exists() or not path.is_dir():
            logger.error("Directory not found: %s", directory_path)
            return reports

        glob_method = path.rglob if recursive else path.glob
        for file_path in glob_method(pattern):
            try:
                report = self.validate_file(str(file_path))
                reports[file_path.name] = report
            except Exception as exc:
                logger.error("Error validating %s: %s", file_path, exc)
                report = ValidationReport(template_name=file_path.name)
                report.add_finding(ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.SCHEMA,
                    code="VALIDATION_EXCEPTION",
                    message=f"Unexpected validation error: {exc}",
                    template_name=file_path.name,
                ))
                reports[file_path.name] = report

        return reports

    def get_validation_config(self) -> Dict[str, Any]:
        """Get the current validation configuration."""
        return dict(self.config)

    def update_validation_config(self, updates: Dict[str, Any]) -> None:
        """Update validation configuration."""
        with self._lock:
            self.config.update(updates)

    def reset_validation_config(self) -> None:
        """Reset validation config to defaults."""
        with self._lock:
            self.config = self._default_config()
