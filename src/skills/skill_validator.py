"""SkillValidator - Validate skill definitions against schema, input/output types, compatibility, security, and performance."""

import logging
import time
import json
import re
import inspect
import ast
import hashlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


class ValidationCategory(Enum):
    SCHEMA = "schema"
    INPUT_OUTPUT = "input_output"
    COMPATIBILITY = "compatibility"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DEPENDENCY = "dependency"
    NAMING = "naming"
    DOCUMENTATION = "documentation"
    BEST_PRACTICE = "best_practice"
    CUSTOM = "custom"


class CompatibilityLevel(Enum):
    FULL = "full"
    BACKWARD = "backward"
    FORWARD = "forward"
    NONE = "none"
    UNKNOWN = "unknown"


class SecurityRisk(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ValidationResult:
    skill_name: str
    passed: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    info: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    score: float = 1.0
    duration: float = 0.0
    validated_at: float = field(default_factory=time.time)
    validator_name: str = "default"
    details: Dict[str, Any] = field(default_factory=dict)

    def add_issue(
        self,
        message: str,
        category: ValidationCategory = ValidationCategory.CUSTOM,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
        location: Optional[str] = None,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        issue = {
            "message": message,
            "category": category.value,
            "severity": severity.value,
            "location": location,
            "code": code,
            "details": details or {},
        }
        if severity == ValidationSeverity.ERROR:
            self.errors.append(issue)
            self.passed = False
        elif severity == ValidationSeverity.WARNING:
            self.warnings.append(issue)
        elif severity == ValidationSeverity.INFO:
            self.info.append(issue)
        elif severity == ValidationSeverity.SUGGESTION:
            self.suggestions.append(issue)
        self._update_score()

    def _update_score(self) -> None:
        penalty = 0.0
        penalty += len(self.errors) * 0.2
        penalty += len(self.warnings) * 0.05
        penalty += len(self.info) * 0.01
        self.score = max(0.0, 1.0 - penalty)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        self.suggestions.extend(other.suggestions)
        self.passed = self.passed and other.passed
        self._update_score()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "passed": self.passed,
            "score": self.score,
            "duration": self.duration,
            "validated_at": self.validated_at,
            "validator_name": self.validator_name,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "suggestions": self.suggestions,
            "details": self.details,
        }

    def summary(self) -> str:
        parts = []
        parts.append(f"Validation for '{self.skill_name}': {'PASSED' if self.passed else 'FAILED'}")
        parts.append(f"  Score: {self.score:.2f}")
        parts.append(f"  Errors: {len(self.errors)}")
        parts.append(f"  Warnings: {len(self.warnings)}")
        parts.append(f"  Info: {len(self.info)}")
        parts.append(f"  Suggestions: {len(self.suggestions)}")
        if self.errors:
            parts.append("  Errors:")
            for e in self.errors[:5]:
                parts.append(f"    - [{e['category']}] {e['message']}")
        if self.warnings:
            parts.append("  Warnings:")
            for w in self.warnings[:5]:
                parts.append(f"    - [{w['category']}] {w['message']}")
        return "\n".join(parts)


@dataclass
class ValidationReport:
    results: Dict[str, ValidationResult] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    total_skills: int = 0
    passed_count: int = 0
    failed_count: int = 0
    avg_score: float = 0.0
    total_errors: int = 0
    total_warnings: int = 0
    validator_name: str = "default"

    def add_result(self, result: ValidationResult) -> None:
        self.results[result.skill_name] = result
        self.total_skills = len(self.results)
        if result.passed:
            self.passed_count += 1
        else:
            self.failed_count += 1
        self.total_errors += len(result.errors)
        self.total_warnings += len(result.warnings)
        self.avg_score = sum(r.score for r in self.results.values()) / max(len(self.results), 1)

    def finalize(self) -> None:
        self.completed_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": (self.completed_at or time.time()) - self.started_at,
            "total_skills": self.total_skills,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "avg_score": self.avg_score,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "results": {k: v.to_dict() for k, v in self.results.items()},
        }

    def summary(self) -> str:
        lines = []
        lines.append(f"Validation Report: {self.total_skills} skills")
        lines.append("=" * 60)
        lines.append(f"Passed: {self.passed_count}")
        lines.append(f"Failed: {self.failed_count}")
        lines.append(f"Avg Score: {self.avg_score:.2f}")
        lines.append(f"Total Errors: {self.total_errors}")
        lines.append(f"Total Warnings: {self.total_warnings}")
        for name, result in self.results.items():
            lines.append(f"\n  {name}: {'PASS' if result.passed else 'FAIL'} (score: {result.score:.2f})")
            for e in result.errors[:3]:
                lines.append(f"    ERROR: {e['message']}")
            for w in result.warnings[:3]:
                lines.append(f"    WARN: {w['message']}")
        return "\n".join(lines)


@dataclass
class ValidatorConfig:
    strict_mode: bool = False
    max_errors: int = 50
    max_warnings: int = 100
    check_schema: bool = True
    check_input_output: bool = True
    check_compatibility: bool = True
    check_security: bool = True
    check_performance: bool = True
    check_dependencies: bool = True
    check_naming: bool = True
    check_documentation: bool = True
    check_best_practices: bool = True
    score_threshold: float = 0.7
    max_handler_time: float = 5.0
    max_dependencies: int = 20
    max_inputs: int = 30
    max_outputs: int = 30
    max_name_length: int = 100
    max_description_length: int = 1000
    forbidden_patterns: List[str] = field(default_factory=lambda: [
        r"exec\s*\(", r"eval\s*\(", r"__import__\s*\(", r"subprocess", r"os\.system",
    ])
    allowed_builtins: Set[str] = field(default_factory=lambda: {
        "print", "len", "range", "int", "str", "float", "list", "dict", "set",
        "tuple", "bool", "type", "isinstance", "hasattr", "getattr", "setattr",
        "min", "max", "sum", "sorted", "reversed", "enumerate", "zip", "map",
        "filter", "any", "all", "abs", "round", "open",
    })
    security_risk_patterns: List[str] = field(default_factory=lambda: [
        r"subprocess\.(call|Popen|run|check_output)",
        r"os\.(system|popen|execl|execle|execlp|execv|execve|execvp)",
        r"shutil\.rmtree",
        r"pickle\.loads",
        r"yaml\.load\s*\([^)]*Loader\s*=\s*yaml\.UnsafeLoader",
        r"sqlite3\.connect",
        r"open\s*\(.*['\"]w['\"]",
        r"request\.get\b",
        r"request\.post\b",
    ])
    naming_pattern: str = r"^[a-z][a-z0-9_]*$"
    version_pattern: str = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidatorConfig":
        return cls(
            strict_mode=data.get("strict_mode", False),
            max_errors=data.get("max_errors", 50),
            max_warnings=data.get("max_warnings", 100),
            check_schema=data.get("check_schema", True),
            check_input_output=data.get("check_input_output", True),
            check_compatibility=data.get("check_compatibility", True),
            check_security=data.get("check_security", True),
            check_performance=data.get("check_performance", True),
            check_dependencies=data.get("check_dependencies", True),
            check_naming=data.get("check_naming", True),
            check_documentation=data.get("check_documentation", True),
            check_best_practices=data.get("check_best_practices", True),
            score_threshold=data.get("score_threshold", 0.7),
            max_handler_time=data.get("max_handler_time", 5.0),
            max_dependencies=data.get("max_dependencies", 20),
            max_inputs=data.get("max_inputs", 30),
            max_outputs=data.get("max_outputs", 30),
            max_name_length=data.get("max_name_length", 100),
            max_description_length=data.get("max_description_length", 1000),
            forbidden_patterns=data.get("forbidden_patterns", []),
            allowed_builtins=set(data.get("allowed_builtins", [])),
            security_risk_patterns=data.get("security_risk_patterns", []),
            naming_pattern=data.get("naming_pattern", r"^[a-z][a-z0-9_]*$"),
            version_pattern=data.get("version_pattern", r"^\d+\.\d+\.\d+"),
        )


from .rule_skill import RuleSkill, SkillDependency, SkillCategory, SkillVersion, SkillStatus


class SkillValidator:
    def __init__(
        self,
        config: Optional[Union[ValidatorConfig, Dict[str, Any]]] = None,
        name: str = "default",
    ):
        self._name = name
        if isinstance(config, dict):
            self._config = ValidatorConfig.from_dict(config)
        elif config is None:
            self._config = ValidatorConfig()
        else:
            self._config = config
        self._custom_validators: Dict[str, Callable[..., Any]] = {}
        self._validation_history: List[ValidationReport] = []
        self._lock = threading.RLock()
        self._started_at = time.time()

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> ValidatorConfig:
        return self._config

    def validate(
        self,
        skill: RuleSkill,
        full: bool = True,
    ) -> ValidationResult:
        started = time.time()
        result = ValidationResult(
            skill_name=skill.name,
            validator_name=self._name,
        )
        if self._config.check_schema:
            self._validate_schema(skill, result)
        if self._config.check_naming:
            self._validate_naming(skill, result)
        if self._config.check_input_output:
            self._validate_input_output(skill, result)
        if self._config.check_dependencies:
            self._validate_dependencies(skill, result)
        if self._config.check_compatibility and full:
            self._validate_compatibility(skill, result)
        if self._config.check_security and full:
            self._validate_security(skill, result)
        if self._config.check_performance and full:
            self._validate_performance(skill, result)
        if self._config.check_documentation:
            self._validate_documentation(skill, result)
        if self._config.check_best_practices:
            self._validate_best_practices(skill, result)
        for name, validator in self._custom_validators.items():
            try:
                validator(skill, result)
            except Exception as e:
                result.add_issue(
                    message=f"Custom validator '{name}' failed: {e}",
                    category=ValidationCategory.CUSTOM,
                    severity=ValidationSeverity.ERROR,
                )
        if self._config.strict_mode:
            for w in result.warnings:
                result.errors.append(w)
            result.warnings = []
            result.passed = len(result.errors) == 0
        result.duration = time.time() - started
        return result

    def validate_batch(
        self,
        skills: List[RuleSkill],
        full: bool = True,
    ) -> ValidationReport:
        report = ValidationReport(validator_name=self._name)
        for skill in skills:
            result = self.validate(skill, full=full)
            report.add_result(result)
        report.finalize()
        self._validation_history.append(report)
        if len(self._validation_history) > 100:
            self._validation_history = self._validation_history[-100:]
        return report

    def _validate_schema(self, skill: RuleSkill, result: ValidationResult) -> None:
        if not skill.name:
            result.add_issue(
                "Skill name is required",
                category=ValidationCategory.SCHEMA,
                severity=ValidationSeverity.ERROR,
            )
        if not skill.handler and skill.status != SkillStatus.DRAFT:
            result.add_issue(
                "Active skill must have a handler",
                category=ValidationCategory.SCHEMA,
                severity=ValidationSeverity.ERROR,
                location="handler",
            )
        required_fields = ["name"]
        for field in required_fields:
            if not getattr(skill, field, None):
                result.add_issue(
                    f"Required field '{field}' is missing",
                    category=ValidationCategory.SCHEMA,
                    severity=ValidationSeverity.ERROR,
                )
        if not isinstance(skill.metadata, SkillMetadata):
            result.add_issue(
                "Metadata must be a SkillMetadata instance",
                category=ValidationCategory.SCHEMA,
                severity=ValidationSeverity.ERROR,
            )

    def _validate_naming(self, skill: RuleSkill, result: ValidationResult) -> None:
        if len(skill.name) > self._config.max_name_length:
            result.add_issue(
                f"Skill name too long ({len(skill.name)} > {self._config.max_name_length})",
                category=ValidationCategory.NAMING,
                severity=ValidationSeverity.ERROR,
                location="name",
            )
        if not re.match(self._config.naming_pattern, skill.name):
            result.add_issue(
                f"Skill name '{skill.name}' does not match pattern '{self._config.naming_pattern}'",
                category=ValidationCategory.NAMING,
                severity=ValidationSeverity.WARNING,
                location="name",
            )
        for inp in skill.inputs:
            if not re.match(self._config.naming_pattern, inp.name):
                result.add_issue(
                    f"Input name '{inp.name}' does not match naming pattern",
                    category=ValidationCategory.NAMING,
                    severity=ValidationSeverity.WARNING,
                    location=f"input.{inp.name}",
                )
        for out in skill.outputs:
            if not re.match(self._config.naming_pattern, out.name):
                result.add_issue(
                    f"Output name '{out.name}' does not match naming pattern",
                    category=ValidationCategory.NAMING,
                    severity=ValidationSeverity.WARNING,
                    location=f"output.{out.name}",
                )
        reserved_names = {"skill", "context", "registry", "executor", "validator"}
        if skill.name.lower() in reserved_names:
            result.add_issue(
                f"Skill name '{skill.name}' is a reserved word",
                category=ValidationCategory.NAMING,
                severity=ValidationSeverity.WARNING,
            )
        for alias in skill.aliases:
            if not re.match(self._config.naming_pattern, alias):
                result.add_issue(
                    f"Alias '{alias}' does not match naming pattern",
                    category=ValidationCategory.NAMING,
                    severity=ValidationSeverity.WARNING,
                )

    def _validate_input_output(self, skill: RuleSkill, result: ValidationResult) -> None:
        if len(skill.inputs) > self._config.max_inputs:
            result.add_issue(
                f"Too many inputs ({len(skill.inputs)} > {self._config.max_inputs})",
                category=ValidationCategory.INPUT_OUTPUT,
                severity=ValidationSeverity.WARNING,
            )
        if len(skill.outputs) > self._config.max_outputs:
            result.add_issue(
                f"Too many outputs ({len(skill.outputs)} > {self._config.max_outputs})",
                category=ValidationCategory.INPUT_OUTPUT,
                severity=ValidationSeverity.WARNING,
            )
        input_names = [i.name for i in skill.inputs]
        if len(input_names) != len(set(input_names)):
            duplicates = [n for n in input_names if input_names.count(n) > 1]
            result.add_issue(
                f"Duplicate input names: {duplicates}",
                category=ValidationCategory.INPUT_OUTPUT,
                severity=ValidationSeverity.ERROR,
            )
        output_names = [o.name for o in skill.outputs]
        if len(output_names) != len(set(output_names)):
            duplicates = [n for n in output_names if output_names.count(n) > 1]
            result.add_issue(
                f"Duplicate output names: {duplicates}",
                category=ValidationCategory.INPUT_OUTPUT,
                severity=ValidationSeverity.ERROR,
            )
        for inp in skill.inputs:
            if inp.type_hint and inp.type_hint not in _VALID_TYPE_HINTS:
                result.add_issue(
                    f"Unknown type hint '{inp.type_hint}' for input '{inp.name}'",
                    category=ValidationCategory.INPUT_OUTPUT,
                    severity=ValidationSeverity.WARNING,
                    location=f"input.{inp.name}",
                )
        for out in skill.outputs:
            if out.type_hint and out.type_hint not in _VALID_TYPE_HINTS:
                result.add_issue(
                    f"Unknown type hint '{out.type_hint}' for output '{out.name}'",
                    category=ValidationCategory.INPUT_OUTPUT,
                    severity=ValidationSeverity.WARNING,
                    location=f"output.{out.name}",
                )

    def _validate_dependencies(self, skill: RuleSkill, result: ValidationResult) -> None:
        if len(skill.dependencies) > self._config.max_dependencies:
            result.add_issue(
                f"Too many dependencies ({len(skill.dependencies)} > {self._config.max_dependencies})",
                category=ValidationCategory.DEPENDENCY,
                severity=ValidationSeverity.WARNING,
            )
        dep_names = [d.name for d in skill.dependencies]
        if len(dep_names) != len(set(dep_names)):
            duplicates = [n for n in dep_names if dep_names.count(n) > 1]
            result.add_issue(
                f"Duplicate dependencies: {duplicates}",
                category=ValidationCategory.DEPENDENCY,
                severity=ValidationSeverity.WARNING,
            )
        for dep in skill.dependencies:
            if dep.name == skill.name:
                result.add_issue(
                    f"Self-referencing dependency on '{dep.name}'",
                    category=ValidationCategory.DEPENDENCY,
                    severity=ValidationSeverity.ERROR,
                )
        for dep in skill.dependencies:
            if dep.version:
                if not re.match(self._config.version_pattern, str(dep.version)):
                    result.add_issue(
                        f"Dependency '{dep.name}' has invalid version '{dep.version}'",
                        category=ValidationCategory.DEPENDENCY,
                        severity=ValidationSeverity.WARNING,
                    )

    def _validate_compatibility(self, skill: RuleSkill, result: ValidationResult) -> None:
        if not skill.handler:
            return
        try:
            sig = inspect.signature(skill.handler)
            handler_params = list(sig.parameters.keys())
            required_params = [
                p for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.name != "self"
                and p.name != "cls"
            ]
            input_names = {i.name for i in skill.inputs}
            if not input_names:
                return
            handler_inputs = set(handler_params) - {"ctx", "context", "self", "cls", "kwargs"}
            for inp_name in input_names:
                if inp_name not in handler_inputs and "kwargs" not in handler_params:
                    result.add_issue(
                        f"Input '{inp_name}' not found in handler signature",
                        category=ValidationCategory.COMPATIBILITY,
                        severity=ValidationSeverity.ERROR,
                        location=f"input.{inp_name}",
                    )
            for param in required_params:
                if param in ("ctx", "context", "self", "cls", "kwargs"):
                    continue
                if param not in input_names:
                    result.add_issue(
                        f"Handler parameter '{param}' has no matching input definition",
                        category=ValidationCategory.COMPATIBILITY,
                        severity=ValidationSeverity.WARNING,
                        location=f"handler.{param}",
                    )
        except (ValueError, TypeError):
            result.add_issue(
                "Cannot inspect handler signature",
                category=ValidationCategory.COMPATIBILITY,
                severity=ValidationSeverity.WARNING,
                location="handler",
            )

    def _validate_security(self, skill: RuleSkill, result: ValidationResult) -> None:
        if not skill.handler:
            return
        try:
            source = inspect.getsource(skill.handler)
        except (OSError, TypeError):
            result.add_issue(
                "Cannot inspect handler source for security check",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.INFO,
            )
            return
        for pattern in self._config.forbidden_patterns:
            matches = re.findall(pattern, source, re.IGNORECASE)
            if matches:
                result.add_issue(
                    f"Forbidden pattern detected: {matches[0]}",
                    category=ValidationCategory.SECURITY,
                    severity=ValidationSeverity.WARNING,
                    location="handler",
                    code=matches[0],
                )
        for pattern in self._config.security_risk_patterns:
            matches = re.findall(pattern, source, re.IGNORECASE)
            if matches:
                result.add_issue(
                    f"Security risk pattern detected: {matches[0]}",
                    category=ValidationCategory.SECURITY,
                    severity=ValidationSeverity.WARNING,
                    location="handler",
                    code=matches[0],
                )
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            full_name = f"{node.func.value.id}.{node.func.attr}"
                            if full_name in ("os.system", "subprocess.call", "subprocess.Popen"):
                                result.add_issue(
                                    f"Potentially dangerous call: {full_name}",
                                    category=ValidationCategory.SECURITY,
                                    severity=ValidationSeverity.WARNING,
                                    location=f"handler:{node.lineno}",
                                )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ("os", "subprocess", "shutil", "pickle"):
                            result.add_issue(
                                f"Import of potentially dangerous module: {alias.name}",
                                category=ValidationCategory.SECURITY,
                                severity=ValidationSeverity.INFO,
                                location=f"handler:{node.lineno}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module in ("os", "subprocess", "shutil", "pickle"):
                        for alias in node.names:
                            result.add_issue(
                                f"Import from potentially dangerous module: {node.module}.{alias.name}",
                                category=ValidationCategory.SECURITY,
                                severity=ValidationSeverity.INFO,
                                location=f"handler:{node.lineno}",
                            )
        except SyntaxError:
            result.add_issue(
                "Handler source contains syntax errors",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.WARNING,
            )

    def _validate_performance(self, skill: RuleSkill, result: ValidationResult) -> None:
        if skill._timeout and skill._timeout > self._config.max_handler_time * 2:
            result.add_issue(
                f"Timeout ({skill._timeout}s) is more than double the max ({self._config.max_handler_time}s)",
                category=ValidationCategory.PERFORMANCE,
                severity=ValidationSeverity.WARNING,
            )
        if skill._retry_policy.get("max_retries", 0) > 10:
            result.add_issue(
                f"High retry count ({skill._retry_policy.get('max_retries')}) may cause performance issues",
                category=ValidationCategory.PERFORMANCE,
                severity=ValidationSeverity.WARNING,
            )
        if len(skill._cache) > 1000:
            result.add_issue(
                f"Large cache size ({len(skill._cache)}) may impact memory",
                category=ValidationCategory.PERFORMANCE,
                severity=ValidationSeverity.INFO,
            )
        if not skill.handler:
            return
        try:
            source = inspect.getsource(skill.handler)
            line_count = source.count("\n") + 1
            if line_count > 200:
                result.add_issue(
                    f"Handler is very long ({line_count} lines), consider refactoring",
                    category=ValidationCategory.PERFORMANCE,
                    severity=ValidationSeverity.SUGGESTION,
                )
            if "for" in source and "range" in source:
                deep_loops = len(re.findall(r"for\s+\w+\s+in\s+range", source))
                if deep_loops > 3:
                    result.add_issue(
                        f"Multiple range loops ({deep_loops}) may indicate performance issues",
                        category=ValidationCategory.PERFORMANCE,
                        severity=ValidationSeverity.SUGGESTION,
                    )
        except (OSError, TypeError):
            pass

    def _validate_documentation(self, skill: RuleSkill, result: ValidationResult) -> None:
        if not skill.metadata.description:
            result.add_issue(
                "Skill has no description",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.WARNING,
            )
        elif len(skill.metadata.description) < 10:
            result.add_issue(
                "Skill description is too short (< 10 chars)",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.INFO,
            )
        if len(skill.metadata.description) > self._config.max_description_length:
            result.add_issue(
                f"Description too long ({len(skill.metadata.description)} > {self._config.max_description_length})",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.WARNING,
            )
        if not skill.metadata.tags:
            result.add_issue(
                "Skill has no tags",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.SUGGESTION,
            )
        if not skill.metadata.author:
            result.add_issue(
                "Skill has no author",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.SUGGESTION,
            )
        if skill.handler:
            try:
                source = inspect.getsource(skill.handler)
                if '"""' not in source and "'''" not in source:
                    result.add_issue(
                        "Handler has no docstring",
                        category=ValidationCategory.DOCUMENTATION,
                        severity=ValidationSeverity.SUGGESTION,
                    )
            except (OSError, TypeError):
                pass
        for inp in skill.inputs:
            if not inp.description:
                result.add_issue(
                    f"Input '{inp.name}' has no description",
                    category=ValidationCategory.DOCUMENTATION,
                    severity=ValidationSeverity.SUGGESTION,
                    location=f"input.{inp.name}",
                )
        for out in skill.outputs:
            if not out.description:
                result.add_issue(
                    f"Output '{out.name}' has no description",
                    category=ValidationCategory.DOCUMENTATION,
                    severity=ValidationSeverity.SUGGESTION,
                    location=f"output.{out.name}",
                )

    def _validate_best_practices(self, skill: RuleSkill, result: ValidationResult) -> None:
        if skill.metadata.category == SkillCategory.CUSTOM:
            result.add_issue(
                "Skill uses generic CUSTOM category, consider a more specific category",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.SUGGESTION,
            )
        if skill.metadata.priority == SkillPriority.NORMAL:
            result.add_issue(
                "Skill uses default NORMAL priority, consider setting explicitly",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.SUGGESTION,
            )
        if not skill._environments or len(skill._environments) == 1:
            result.add_issue(
                "Skill only targets default environment",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.SUGGESTION,
            )
        if skill._timeout and skill._timeout < 1.0:
            result.add_issue(
                f"Very short timeout ({skill._timeout}s) may cause frequent failures",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.INFO,
            )
        if not skill.triggers or skill.triggers == [SkillTrigger.MANUAL]:
            result.add_issue(
                "Skill only has MANUAL trigger, consider adding EVENT or SCHEDULE triggers",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.SUGGESTION,
            )
        if skill._retry_policy.get("max_retries", 0) == 0:
            result.add_issue(
                "Skill has no retry policy configured",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.SUGGESTION,
            )
        if skill.error_count and skill.error_count > skill.execution_count * 0.5:
            result.add_issue(
                "Skill has high error rate (>50%)",
                category=ValidationCategory.BEST_PRACTICE,
                severity=ValidationSeverity.WARNING,
            )

    def validate_compatibility_between(
        self,
        skill_a: RuleSkill,
        skill_b: RuleSkill,
    ) -> CompatibilityLevel:
        score = 0
        checks = 0
        if skill_a.metadata.version.major == skill_b.metadata.version.major:
            score += 1
        checks += 1
        a_inputs = {i.name for i in skill_a.inputs if i.required}
        b_inputs = {i.name for i in skill_b.inputs if i.required}
        if a_inputs == b_inputs:
            score += 1
        elif a_inputs.issubset(b_inputs) or b_inputs.issubset(a_inputs):
            score += 0.5
        checks += 1
        a_outputs = {o.name for o in skill_a.outputs}
        b_outputs = {o.name for o in skill_b.outputs}
        overlap = a_outputs & b_outputs
        if overlap == a_outputs and overlap == b_outputs:
            score += 1
        elif overlap:
            score += 0.5
        checks += 1
        if skill_a.metadata.category == skill_b.metadata.category:
            score += 1
        checks += 1
        ratio = score / max(checks, 1)
        if ratio >= 0.9:
            return CompatibilityLevel.FULL
        elif ratio >= 0.7:
            return CompatibilityLevel.BACKWARD
        elif ratio >= 0.4:
            return CompatibilityLevel.FORWARD
        elif ratio > 0:
            return CompatibilityLevel.NONE
        return CompatibilityLevel.UNKNOWN

    def add_custom_validator(self, name: str, validator: Callable[..., Any]) -> None:
        self._custom_validators[name] = validator

    def remove_custom_validator(self, name: str) -> None:
        self._custom_validators.pop(name, None)

    def validate_handler(self, handler: Callable[..., Any]) -> ValidationResult:
        dummy_skill = RuleSkill(name="_handler_validation", handler=handler)
        return self.validate(dummy_skill, full=False)

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(skill_name="_config_validation")
        if not isinstance(config, dict):
            result.add_issue("Config must be a dictionary", severity=ValidationSeverity.ERROR)
            return result
        valid_keys = {"timeout", "retry", "cache", "environment", "triggers", "metadata"}
        for key in config:
            if key not in valid_keys:
                result.add_issue(
                    f"Unknown config key '{key}'",
                    category=ValidationCategory.SCHEMA,
                    severity=ValidationSeverity.WARNING,
                )
        return result

    def get_history(self, limit: int = 10) -> List[ValidationReport]:
        return list(self._validation_history[-limit:])

    def summary(self) -> str:
        total = len(self._validation_history)
        if total == 0:
            return "No validations performed yet"
        last = self._validation_history[-1]
        lines = []
        lines.append(f"Validator: {self._name}")
        lines.append(f"Total Validation Runs: {total}")
        lines.append(f"Last Run:")
        lines.append(f"  Skills: {last.total_skills}")
        lines.append(f"  Passed: {last.passed_count}")
        lines.append(f"  Failed: {last.failed_count}")
        lines.append(f"  Avg Score: {last.avg_score:.2f}")
        lines.append(f"  Total Errors: {last.total_errors}")
        lines.append(f"  Total Warnings: {last.total_warnings}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "config": self._config.to_dict(),
            "total_validations": len(self._validation_history),
            "custom_validators": list(self._custom_validators.keys()),
        }

    def __repr__(self) -> str:
        return f"SkillValidator(name='{self._name}', validations={len(self._validation_history)})"

    def __str__(self) -> str:
        return f"SkillValidator[{self._name}] ({len(self._validation_history)} runs)"


_VALID_TYPE_HINTS = {
    "str", "int", "float", "bool", "bytes", "None", "Any",
    "Dict", "List", "Set", "Tuple", "Optional", "Union",
    "Dict[str, Any]", "List[str]", "List[int]", "List[float]",
    "Dict[str, str]", "Dict[str, int]",
    "str, int, float, bool, bytes, None, Any",
}


def validate_skill(
    skill: RuleSkill,
    config: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    validator = SkillValidator(config=ValidatorConfig.from_dict(config) if config else None)
    return validator.validate(skill)


def validate_skills_batch(
    skills: List[RuleSkill],
    config: Optional[Dict[str, Any]] = None,
) -> ValidationReport:
    validator = SkillValidator(config=ValidatorConfig.from_dict(config) if config else None)
    return validator.validate_batch(skills)


import threading
from .rule_skill import (
    RuleSkill, SkillDependency, SkillCategory, SkillVersion, SkillStatus,
    SkillPriority, SkillTrigger, SkillMetadata, SkillInput, SkillOutput, ExecutionContext,
)
