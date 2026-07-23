"""
Rule template renderer - parameter binding, type coercion, multi-pass rendering,
partial rendering, and Rule object construction from rendered templates.
"""

import copy
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

from .template_engine import RuleTemplateEngine, TemplateContext, TemplateError
from .template_validator import RuleTemplateValidator, ValidationReport

logger = logging.getLogger(__name__)


class RenderPhase(str, Enum):
    """Phases of the rendering pipeline."""
    PRE_PROCESSING = "pre_processing"
    VARIABLE_BINDING = "variable_binding"
    TYPE_COERCION = "type_coercion"
    TEMPLATE_EVALUATION = "template_evaluation"
    POST_PROCESSING = "post_processing"
    RULE_CONSTRUCTION = "rule_construction"
    FINALIZATION = "finalization"


class RenderError(Exception):
    """Base exception for rendering errors."""


class BindingError(RenderError):
    """Raised when variable binding fails."""


class CoercionError(RenderError):
    """Raised when type coercion fails."""


class ConstructionError(RenderError):
    """Raised when Rule object construction fails."""


@dataclass
class ParameterBinding:
    """Defines a single parameter binding from context to template variable."""
    name: str
    source_path: str
    target_type: Optional[str] = None
    required: bool = False
    default_value: Any = None
    coerce_func: Optional[Callable[[Any], Any]] = None
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def resolve(self, context: Dict[str, Any]) -> Any:
        """Resolve the parameter value from context."""
        parts = self.source_path.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict):
                if "[" in part and part.endswith("]"):
                    key, idx_str = part[:-1].split("[", 1)
                    value = value.get(key, {})
                    try:
                        idx = int(idx_str)
                        value = value[idx] if isinstance(value, (list, tuple)) else value
                    except (ValueError, IndexError, TypeError):
                        if self.required:
                            raise BindingError(
                                f"Cannot index '{key}' with '{idx_str}' in context"
                            )
                        return self.default_value
                else:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        if self.required:
                            raise BindingError(
                                f"Required parameter '{self.name}' not found "
                                f"at path '{self.source_path}'"
                            )
                        return self.default_value
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                if self.required:
                    raise BindingError(
                        f"Required parameter '{self.name}' not found "
                        f"at path '{self.source_path}'"
                    )
                return self.default_value

        if self.coerce_func and value is not None:
            try:
                value = self.coerce_func(value)
            except Exception as exc:
                raise CoercionError(
                    f"Coercion failed for '{self.name}': {exc}"
                ) from exc

        if self.target_type and value is not None:
            try:
                value = self._coerce_type(value, self.target_type)
            except Exception as exc:
                raise CoercionError(
                    f"Type coercion failed for '{self.name}': "
                    f"expected {self.target_type}, got {type(value).__name__}: {exc}"
                ) from exc

        return value

    def _coerce_type(self, value: Any, target_type: str) -> Any:
        """Coerce a value to the target type."""
        type_map: Dict[str, Callable[[Any], Any]] = {
            "string": str,
            "integer": int,
            "float": float,
            "boolean": bool,
            "list": lambda v: list(v) if hasattr(v, "__iter__") else [v],
            "dict": lambda v: dict(v) if hasattr(v, "items") else {"value": v},
        }
        coerce_func = type_map.get(target_type)
        if coerce_func:
            if target_type in ("integer", "float") and isinstance(value, str):
                value = value.strip()
            return coerce_func(value)
        return value


@dataclass
class BindingGroup:
    """Group of parameter bindings for structured binding."""
    name: str
    bindings: List[ParameterBinding] = field(default_factory=list)
    required: bool = False
    description: str = ""

    def resolve_all(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve all bindings in the group."""
        resolved: Dict[str, Any] = {}
        for binding in self.bindings:
            try:
                resolved[binding.name] = binding.resolve(context)
            except (BindingError, CoercionError):
                if binding.required:
                    raise
                resolved[binding.name] = binding.default_value
        return resolved


@dataclass
class RenderResult:
    """Result of a template rendering operation."""
    rendered_text: str
    bound_variables: Dict[str, Any]
    phases_completed: List[RenderPhase]
    duration_ms: float = 0.0
    pass_count: int = 1
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if rendering completed without errors."""
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rendered_text": self.rendered_text,
            "bound_variables": self.bound_variables,
            "phases_completed": [p.value for p in self.phases_completed],
            "duration_ms": self.duration_ms,
            "pass_count": self.pass_count,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


class TypeCoercionEngine:
    """Handles type coercion and validation for rendered values."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or self._default_config()
        self._coercers: Dict[str, Callable[[Any], Any]] = self._register_coercers()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "strict_coercion": True,
            "allow_none": False,
            "truncate_strings": True,
            "max_string_length": 4096,
            "coerce_lists_to_sets": False,
            "coerce_none_to_default": True,
        }

    def _register_coercers(self) -> Dict[str, Callable[[Any], Any]]:
        """Register built-in type coercers."""
        return {
            "string": self._coerce_string,
            "integer": self._coerce_integer,
            "float": self._coerce_float,
            "boolean": self._coerce_boolean,
            "list": self._coerce_list,
            "dict": self._coerce_dict,
            "rule_tier": self._coerce_rule_tier,
            "rule_type": self._coerce_rule_type,
            "rule_severity": self._coerce_rule_severity,
            "rule_status": self._coerce_rule_status,
            "enforcement_level": self._coerce_enforcement_level,
            "any": lambda v: v,
        }

    def coerce(self, value: Any, target_type: str, name: str = "") -> Any:
        """Coerce a value to the target type."""
        if value is None:
            if self.config.get("allow_none"):
                return None
            if self.config.get("coerce_none_to_default"):
                return self._default_for_type(target_type)
            raise CoercionError(
                f"Cannot coerce None to '{target_type}' for '{name}'"
            )

        coercer = self._coercers.get(target_type)
        if coercer is None:
            logger.warning("No coercer registered for type '%s'", target_type)
            return value

        try:
            coerced = coercer(value)
            return coerced
        except (ValueError, TypeError) as exc:
            raise CoercionError(
                f"Cannot coerce {type(value).__name__} to '{target_type}' "
                f"for '{name}': {exc}"
            ) from exc

    def _coerce_string(self, value: Any) -> str:
        """Coerce value to string."""
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=str)
        result = str(value)
        if self.config.get("truncate_strings"):
            max_len = self.config.get("max_string_length", 4096)
            if len(result) > max_len:
                logger.warning("String truncated from %d to %d chars", len(result), max_len)
                result = result[:max_len]
        return result

    def _coerce_integer(self, value: Any) -> int:
        """Coerce value to integer."""
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, float):
            if self.config.get("strict_coercion") and not value.is_integer():
                raise ValueError(f"Float {value} is not an integer")
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                try:
                    return int(float(value.strip()))
                except ValueError:
                    raise ValueError(f"Cannot parse '{value}' as integer")
        return int(value)

    def _coerce_float(self, value: Any) -> float:
        """Coerce value to float."""
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, str):
            return float(value.strip())
        return float(value)

    def _coerce_boolean(self, value: Any) -> bool:
        """Coerce value to boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower().strip() in ("true", "yes", "1", "on", "y")
        if isinstance(value, (int, float)):
            return value != 0
        return bool(value)

    def _coerce_list(self, value: Any) -> list:
        """Coerce value to list."""
        if isinstance(value, (list, tuple)):
            if self.config.get("coerce_lists_to_sets"):
                return list(set(value))
            return list(value)
        if isinstance(value, dict):
            return list(value.items())
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return [item.strip() for item in value.split(",") if item.strip()]
        if hasattr(value, "__iter__"):
            return list(value)
        return [value]

    def _coerce_dict(self, value: Any) -> dict:
        """Coerce value to dict."""
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
            pairs = value.split(",")
            result: Dict[str, Any] = {}
            for pair in pairs:
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    result[k.strip()] = v.strip()
            return result
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        if isinstance(value, (list, tuple)):
            return {str(i): v for i, v in enumerate(value)}
        return {"value": value}

    def _coerce_rule_tier(self, value: Any) -> RuleTier:
        """Coerce value to RuleTier enum."""
        if isinstance(value, RuleTier):
            return value
        if isinstance(value, str):
            return RuleTier(value.lower())
        raise ValueError(f"Cannot coerce {type(value).__name__} to RuleTier")

    def _coerce_rule_type(self, value: Any) -> RuleType:
        """Coerce value to RuleType enum."""
        if isinstance(value, RuleType):
            return value
        if isinstance(value, str):
            return RuleType(value.lower())
        raise ValueError(f"Cannot coerce {type(value).__name__} to RuleType")

    def _coerce_rule_severity(self, value: Any) -> RuleSeverity:
        """Coerce value to RuleSeverity enum."""
        if isinstance(value, RuleSeverity):
            return value
        if isinstance(value, str):
            return RuleSeverity(value.lower())
        raise ValueError(f"Cannot coerce {type(value).__name__} to RuleSeverity")

    def _coerce_rule_status(self, value: Any) -> RuleStatus:
        """Coerce value to RuleStatus enum."""
        if isinstance(value, RuleStatus):
            return value
        if isinstance(value, str):
            return RuleStatus(value.lower())
        raise ValueError(f"Cannot coerce {type(value).__name__} to RuleStatus")

    def _coerce_enforcement_level(self, value: Any) -> EnforcementLevel:
        """Coerce value to EnforcementLevel enum."""
        if isinstance(value, EnforcementLevel):
            return value
        if isinstance(value, str):
            return EnforcementLevel(value.lower())
        raise ValueError(f"Cannot coerce {type(value).__name__} to EnforcementLevel")

    def _default_for_type(self, target_type: str) -> Any:
        """Return default value for a given type."""
        defaults = {
            "string": "",
            "integer": 0,
            "float": 0.0,
            "boolean": False,
            "list": [],
            "dict": {},
            "any": None,
        }
        return defaults.get(target_type, None)

    def register_coercer(self, name: str, func: Callable[[Any], Any]) -> None:
        """Register a custom type coercer."""
        self._coercers[name] = func

    def validate_type(self, value: Any, expected_type: str) -> bool:
        """Check if a value matches an expected type without coercing."""
        type_checks: Dict[str, Callable[[Any], bool]] = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "float": lambda v: isinstance(v, float),
            "boolean": lambda v: isinstance(v, bool),
            "list": lambda v: isinstance(v, (list, tuple)),
            "dict": lambda v: isinstance(v, dict),
            "rule_tier": lambda v: isinstance(v, RuleTier),
            "rule_type": lambda v: isinstance(v, RuleType),
            "rule_severity": lambda v: isinstance(v, RuleSeverity),
            "rule_status": lambda v: isinstance(v, RuleStatus),
            "enforcement_level": lambda v: isinstance(v, EnforcementLevel),
            "any": lambda v: True,
        }
        check = type_checks.get(expected_type)
        if check is None:
            return True
        return check(value)


class RuleConstructor:
    """Constructs Rule objects from rendered template data."""

    def __init__(
        self,
        type_coercion: TypeCoercionEngine,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.type_coercion = type_coercion
        self.config = config or {
            "generate_missing_ids": True,
            "id_prefix": "rule_",
            "strict_construction": True,
            "validate_required_fields": True,
        }

    def construct(
        self,
        rendered_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Rule:
        """Construct a Rule object from rendered template data."""
        ctx = context or {}

        if self.config.get("validate_required_fields"):
            self._validate_required(rendered_data)

        rule_data = copy.deepcopy(rendered_data)

        rule_id = rule_data.get("id", "")
        if not rule_id and self.config.get("generate_missing_ids"):
            rule_id = f"{self.config['id_prefix']}{uuid.uuid4().hex[:12]}"
            rule_data["id"] = rule_id

        rule_name = self._coerce_field(rule_data, "name", "string", "Rule name")
        description = self._coerce_field(rule_data, "description", "string", "Rule description")
        tier = self._coerce_field(rule_data, "tier", "rule_tier", "Rule tier")
        rule_type = self._coerce_field(rule_data, "rule_type", "rule_type", "Rule type")

        severity = rule_data.get("severity", RuleSeverity.MEDIUM)
        if isinstance(severity, str):
            severity = self.type_coercion.coerce(severity, "rule_severity", "severity")

        status = rule_data.get("status", RuleStatus.ACTIVE)
        if isinstance(status, str):
            status = self.type_coercion.coerce(status, "rule_status", "status")

        enforcement = rule_data.get("enforcement_level", EnforcementLevel.ADVISORY)
        if isinstance(enforcement, str):
            enforcement = self.type_coercion.coerce(
                enforcement, "enforcement_level", "enforcement_level"
            )

        patterns = self._construct_patterns(rule_data.get("patterns", []), ctx)
        conditions = rule_data.get("conditions", {})
        exceptions = self._coerce_field(rule_data, "exceptions", "list", "exceptions")
        tags = self._coerce_field(rule_data, "tags", "list", "tags")

        priority = self._coerce_field(rule_data, "priority", "integer", "priority", 100)
        timeout_ms = self._coerce_field(rule_data, "timeout_ms", "integer", "timeout_ms", 1000)
        cache_ttl = self._coerce_field(rule_data, "cache_ttl_seconds", "integer", "cache_ttl", 300)

        auto_block = self._coerce_field(rule_data, "auto_block", "boolean", "auto_block", False)
        user_override = self._coerce_field(
            rule_data, "user_override", "boolean", "user_override", True
        )
        override_justification = self._coerce_field(
            rule_data, "override_justification_required", "boolean",
            "override_justification_required", False
        )

        version = str(rule_data.get("version", "1.0.0"))
        created_by = rule_data.get("created_by")

        rule = Rule(
            id=rule_id,
            name=rule_name,
            description=description,
            tier=tier,
            rule_type=rule_type,
            severity=severity,
            status=status,
            patterns=patterns,
            conditions=conditions,
            exceptions=exceptions,
            enforcement_level=enforcement,
            auto_block=auto_block,
            user_override=user_override,
            override_justification_required=override_justification,
            version=version,
            created_by=created_by,
            tags=tags,
            priority=priority,
            timeout_ms=timeout_ms,
            cache_ttl_seconds=cache_ttl,
        )

        if ctx:
            rule.updated_at = ctx.get("_render_timestamp", datetime.utcnow())

        return rule

    def _validate_required(self, data: Dict[str, Any]) -> None:
        """Validate that all required fields are present."""
        required_fields = ["name", "description", "tier", "rule_type"]
        missing = [f for f in required_fields if f not in data or data.get(f) is None]
        if missing:
            raise ConstructionError(
                f"Missing required fields for Rule construction: {missing}"
            )

    def _coerce_field(
        self,
        data: Dict[str, Any],
        field_name: str,
        target_type: str,
        display_name: str,
        default: Any = None,
    ) -> Any:
        """Coerce a single field with proper error handling."""
        value = data.get(field_name, default)
        if value is None and default is None:
            return None
        try:
            return self.type_coercion.coerce(value, target_type, display_name)
        except CoercionError as exc:
            if self.config.get("strict_construction"):
                raise ConstructionError(
                    f"Field '{field_name}' ({display_name}): {exc}"
                ) from exc
            logger.warning("Coercion failed for '%s', using default: %s", field_name, exc)
            return default

    def _construct_patterns(
        self,
        patterns_data: List[Union[Dict[str, Any], RulePattern]],
        context: Dict[str, Any],
    ) -> List[RulePattern]:
        """Construct RulePattern objects from pattern data."""
        patterns: List[RulePattern] = []
        for idx, pattern_item in enumerate(patterns_data):
            if isinstance(pattern_item, RulePattern):
                patterns.append(pattern_item)
                continue

            if not isinstance(pattern_item, dict):
                logger.warning("Invalid pattern data at index %d, skipping", idx)
                continue

            pattern_type_raw = pattern_item.get("type", "custom")
            try:
                pattern_type = self.type_coercion.coerce(
                    pattern_type_raw, "rule_type", f"patterns[{idx}].type"
                )
            except CoercionError:
                pattern_type = RuleType.CUSTOM

            keywords = pattern_item.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [kw.strip() for kw in keywords.split(",") if kw.strip()]

            regex_patterns = pattern_item.get("regex_patterns", [])
            if isinstance(regex_patterns, str):
                regex_patterns = [regex_patterns]

            ml_model = pattern_item.get("ml_model")
            confidence = pattern_item.get("confidence_threshold", 0.7)
            try:
                confidence = self.type_coercion.coerce(
                    confidence, "float", f"patterns[{idx}].confidence_threshold"
                )
            except CoercionError:
                confidence = 0.7

            action = str(pattern_item.get("action", "warn"))

            pattern = RulePattern(
                type=pattern_type,
                keywords=keywords,
                regex_patterns=regex_patterns,
                ml_model=ml_model,
                confidence_threshold=confidence,
                action=action,
            )
            patterns.append(pattern)

        return patterns


class RuleTemplateRenderer:
    """Renders rule templates into Rule objects with full pipeline support."""

    def __init__(
        self,
        engine: Optional[RuleTemplateEngine] = None,
        validator: Optional[RuleTemplateValidator] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.engine = engine or RuleTemplateEngine()
        self.validator = validator
        self.config = config or self._default_config()
        self._type_coercion = TypeCoercionEngine(
            self.config.get("coercion_config", {})
        )
        self._rule_constructor = RuleConstructor(
            self._type_coercion,
            self.config.get("construction_config", {}),
        )
        self._lock = Lock()
        self._bindings: Dict[str, List[ParameterBinding]] = {}
        self._binding_groups: Dict[str, BindingGroup] = {}
        self._render_hooks: Dict[RenderPhase, List[Callable]] = {
            phase: [] for phase in RenderPhase
        }

    def _default_config(self) -> Dict[str, Any]:
        """Return the default renderer configuration."""
        return {
            "max_render_passes": 5,
            "partial_rendering_enabled": True,
            "strict_binding": True,
            "allow_missing_variables": False,
            "default_missing_value": "",
            "coercion_config": {
                "strict_coercion": True,
                "allow_none": False,
                "coerce_none_to_default": True,
            },
            "construction_config": {
                "generate_missing_ids": True,
                "id_prefix": "rule_",
                "strict_construction": True,
            },
            "enable_caching": True,
            "log_rendering": True,
        }

    def register_binding(self, name: str, binding: ParameterBinding) -> None:
        """Register a parameter binding."""
        with self._lock:
            if name not in self._bindings:
                self._bindings[name] = []
            self._bindings[name].append(binding)

    def register_binding_group(self, group: BindingGroup) -> None:
        """Register a binding group."""
        with self._lock:
            self._binding_groups[group.name] = group

    def register_render_hook(
        self, phase: RenderPhase, hook: Callable
    ) -> None:
        """Register a hook function for a render phase."""
        if phase in self._render_hooks:
            self._render_hooks[phase].append(hook)

    def render_string(
        self,
        template_source: str,
        context: Dict[str, Any],
        template_name: str = "<string>",
    ) -> RenderResult:
        """Render a template string with context variables."""
        start_time = time.time()
        result = RenderResult(
            rendered_text="",
            bound_variables={},
            phases_completed=[],
        )

        try:
            variables = self._execute_hooks(
                RenderPhase.PRE_PROCESSING, context, result
            )

            bound_vars, phase_result = self._perform_binding(variables, result)
            variables.update(bound_vars)

            coerced_vars = self._perform_coercion(variables, result)

            rendered = self._execute_hooks(
                RenderPhase.TEMPLATE_EVALUATION, coerced_vars, result
            )
            text = self.engine.render_string(template_source, rendered)
            result.rendered_text = text
            result.phases_completed.append(RenderPhase.TEMPLATE_EVALUATION)

            result = self._execute_hooks(
                RenderPhase.POST_PROCESSING, {"text": text, "vars": coerced_vars}, result
            )

        except TemplateError as exc:
            result.errors.append(f"Template rendering error: {exc}")
        except RenderError as exc:
            result.errors.append(f"Render error: {exc}")
        except Exception as exc:
            result.errors.append(f"Unexpected error: {exc}")
            logger.exception("Unexpected rendering error for '%s'", template_name)

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def render_template(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> RenderResult:
        """Render a named template with context variables."""
        return self.render_string(
            self.engine._load_template_source(template_name) or "",
            context,
            template_name,
        )

    def render_to_rule(
        self,
        template_source: str,
        context: Dict[str, Any],
        template_name: str = "<string>",
        validate: bool = True,
    ) -> Rule:
        """Render a template and construct a Rule object."""
        render_result = self.render_string(template_source, context, template_name)

        if not render_result.success:
            raise ConstructionError(
                f"Cannot construct Rule: template rendering failed: "
                f"{'; '.join(render_result.errors)}"
            )

        try:
            rendered_data = yaml.safe_load(render_result.rendered_text)
        except yaml.YAMLError as exc:
            raise ConstructionError(
                f"Rendered output is not valid YAML: {exc}"
            ) from exc

        if rendered_data is None or not isinstance(rendered_data, dict):
            raise ConstructionError(
                "Rendered template must produce a mapping (dictionary), "
                f"got {type(rendered_data).__name__}"
            )

        if validate and self.validator:
            validation_report = self.validator.validate_data(
                rendered_data, template_name
            )
            if not validation_report.passed:
                error_msgs = [
                    f.message for f in validation_report.findings
                    if f.severity.value == "error"
                ]
                if error_msgs:
                    raise ConstructionError(
                        f"Validation failed for rendered template: "
                        f"{'; '.join(error_msgs)}"
                    )

        rule = self._rule_constructor.construct(rendered_data, context)
        return rule

    def multi_pass_render(
        self,
        template_source: str,
        context: Dict[str, Any],
        max_passes: Optional[int] = None,
        template_name: str = "<string>",
    ) -> RenderResult:
        """Multi-pass rendering for templates with nested variables."""
        max_passes = max_passes or self.config.get("max_render_passes", 5)
        current_source = template_source
        current_context = dict(context)
        final_result = RenderResult(
            rendered_text="",
            bound_variables={},
            phases_completed=[],
        )

        for pass_num in range(1, max_passes + 1):
            result = self.render_string(current_source, current_context, template_name)
            final_result.phases_completed = result.phases_completed
            final_result.errors.extend(result.errors)

            if not result.success:
                break

            new_source = result.rendered_text
            if new_source == current_source:
                final_result.rendered_text = new_source
                final_result.bound_variables = result.bound_variables
                final_result.pass_count = pass_num
                break

            current_source = new_source
            current_context.update(result.bound_variables)
            final_result.pass_count = pass_num

            if pass_num == max_passes:
                final_result.warnings.append(
                    f"Max render passes ({max_passes}) reached - output may "
                    f"still contain unresolved variables"
                )

        return final_result

    def partial_render(
        self,
        template_source: str,
        context: Dict[str, Any],
        unresolved_placeholder: str = "{{__UNRESOLVED__}}",
        template_name: str = "<string>",
    ) -> RenderResult:
        """Render a template partially, leaving unresolved variables in place."""
        original_behavior = self.engine.config.undefined_behavior
        original_auto_escape = self.engine.config.auto_escape

        self.engine.config.undefined_behavior = "keep"
        self.engine.config.auto_escape = False

        try:
            result = self.render_string(template_source, context, template_name)
        finally:
            self.engine.config.undefined_behavior = original_behavior
            self.engine.config.auto_escape = original_auto_escape

        return result

    def batch_render(
        self,
        templates: Dict[str, Tuple[str, Dict[str, Any]]],
    ) -> Dict[str, RenderResult]:
        """Render multiple templates with their respective contexts."""
        results: Dict[str, RenderResult] = {}
        for name, (source, context) in templates.items():
            try:
                results[name] = self.render_string(source, context, name)
            except Exception as exc:
                result = RenderResult(
                    rendered_text="",
                    bound_variables={},
                    phases_completed=[],
                )
                result.errors.append(str(exc))
                results[name] = result
                logger.error("Batch render failed for '%s': %s", name, exc)
        return results

    def batch_render_to_rules(
        self,
        templates: Dict[str, Tuple[str, Dict[str, Any]]],
        validate: bool = True,
    ) -> Dict[str, Rule]:
        """Render multiple templates to Rule objects."""
        rules: Dict[str, Rule] = {}
        for name, (source, context) in templates.items():
            try:
                rules[name] = self.render_to_rule(source, context, name, validate)
            except Exception as exc:
                logger.error("Batch rule construction failed for '%s': %s", name, exc)
        return rules

    def _perform_binding(
        self, context: Dict[str, Any], result: RenderResult
    ) -> Tuple[Dict[str, Any], RenderResult]:
        """Perform variable binding from context to template variables."""
        bound: Dict[str, Any] = {}
        with self._lock:
            for binding_name, binding_list in self._bindings.items():
                for binding in binding_list:
                    try:
                        value = binding.resolve(context)
                        bound[binding_name] = value
                    except (BindingError, CoercionError) as exc:
                        if self.config.get("strict_binding"):
                            result.errors.append(
                                f"Binding failed for '{binding_name}': {exc}"
                            )
                        else:
                            bound[binding_name] = binding.default_value

            for group_name, group in self._binding_groups.items():
                try:
                    group_resolved = group.resolve_all(context)
                    bound[group_name] = group_resolved
                except (BindingError, CoercionError) as exc:
                    if group.required and self.config.get("strict_binding"):
                        result.errors.append(
                            f"Binding group '{group_name}' failed: {exc}"
                        )

        result.bound_variables = bound
        result.phases_completed.append(RenderPhase.VARIABLE_BINDING)
        return bound, result

    def _perform_coercion(
        self, variables: Dict[str, Any], result: RenderResult
    ) -> Dict[str, Any]:
        """Coerce all known typed variables."""
        coerced = dict(variables)
        with self._lock:
            for binding_name, binding_list in self._bindings.items():
                if binding_name not in coerced:
                    continue
                for binding in binding_list:
                    if binding.target_type:
                        try:
                            coerced[binding_name] = self._type_coercion.coerce(
                                coerced[binding_name],
                                binding.target_type,
                                binding_name,
                            )
                        except CoercionError as exc:
                            if self.config.get("strict_binding"):
                                result.errors.append(
                                    f"Coercion failed for '{binding_name}': {exc}"
                                )

        result.phases_completed.append(RenderPhase.TYPE_COERCION)
        return coerced

    def _execute_hooks(
        self,
        phase: RenderPhase,
        data: Any,
        result: RenderResult,
    ) -> Any:
        """Execute all registered hooks for a given phase."""
        hooks = self._render_hooks.get(phase, [])
        current_data = data
        for hook in hooks:
            try:
                hook_result = hook(current_data, result)
                if hook_result is not None:
                    current_data = hook_result
            except Exception as exc:
                result.warnings.append(f"Hook '{hook.__name__}' failed in {phase.value}: {exc}")
                logger.warning("Render hook '%s' failed in phase %s: %s",
                               hook.__name__, phase.value, exc)
        result.phases_completed.append(phase)
        return current_data

    def get_renderer_config(self) -> Dict[str, Any]:
        """Get the current renderer configuration."""
        return dict(self.config)

    def update_renderer_config(self, updates: Dict[str, Any]) -> None:
        """Update renderer configuration."""
        with self._lock:
            self.config.update(updates)
