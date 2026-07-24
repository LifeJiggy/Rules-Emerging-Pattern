"""Data structure validation with schema enforcement, type checking, and custom validators."""

import logging
import re
import time
import json
import hashlib
from collections import defaultdict, Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, date
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
    Type,
    get_type_hints,
)

logger = logging.getLogger(__name__)


class SchemaType(str, Enum):
    DICT = "dict"
    LIST = "list"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    DATE = "date"
    ANY = "any"
    NULLABLE_STRING = "nullable_string"
    NULLABLE_INTEGER = "nullable_integer"
    UNION = "union"
    ENUM = "enum"
    CUSTOM = "custom"


class FieldType(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    CONDITIONAL = "conditional"


@dataclass
class FieldConstraint:
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    pattern: Optional[str] = None
    enum_values: Optional[List[Any]] = None
    allowed_types: Optional[List[str]] = None
    custom_validator: Optional[Callable] = None


@dataclass
class SchemaDefinition:
    name: str
    version: str = "1.0.0"
    type: SchemaType = SchemaType.DICT
    fields: Optional[Dict[str, Any]] = None
    item_type: Optional[SchemaType] = None
    item_schema: Optional["SchemaDefinition"] = None
    constraints: Optional[FieldConstraint] = None
    nullable: bool = False
    default: Any = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureValidationResult:
    path: str
    is_valid: bool
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    coerced_value: Any = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }

    def add_error(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        self.errors.append({
            "message": message,
            "code": code,
            "expected": expected,
            "actual": actual,
        })
        self.is_valid = False

    def add_warning(self, message: str, code: str = "WARNING") -> None:
        self.warnings.append({
            "message": message,
            "code": code,
        })


@dataclass
class CustomValidator:
    name: str
    validator_func: Callable
    description: str = ""
    applies_to: List[str] = field(default_factory=list)
    priority: int = 100
    enabled: bool = True


class StructureValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._schemas: Dict[str, SchemaDefinition] = {}
        self._custom_validators: Dict[str, CustomValidator] = {}
        self._type_coercion_map: Dict[str, Callable] = {}
        self._pattern_cache: Dict[str, Pattern] = {}
        self._schema_versions: Dict[str, List[str]] = defaultdict(list)
        self._validation_history: List[StructureValidationResult] = []
        self._max_history: int = self.config.get("max_history", 500)
        self._stats: Counter = Counter()
        self._coerce_types: bool = self.config.get("coerce_types", False)
        self._strict_mode: bool = self.config.get("strict_mode", False)
        self._max_depth: int = self.config.get("max_depth", 20)
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)

        self._init_type_coercion()
        logger.info(
            f"StructureValidator initialized with {len(self._custom_validators)} "
            f"custom validators"
        )

    def _init_type_coercion(self) -> None:
        self._type_coercion_map = {
            "string": lambda v: str(v) if not isinstance(v, str) else v,
            "integer": self._coerce_to_int,
            "float": self._coerce_to_float,
            "boolean": self._coerce_to_bool,
            "list": lambda v: list(v) if isinstance(v, (list, tuple, set)) else (
                [v] if not isinstance(v, (dict, str, int, float, bool)) else v
            ),
            "dict": lambda v: dict(v) if isinstance(v, (dict,)) else v,
        }

    def _coerce_to_int(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except (ValueError, AttributeError):
                pass
        return value

    def _coerce_to_float(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except (ValueError, AttributeError):
                pass
        return value

    def _coerce_to_bool(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes", "y"):
                return True
            if value.lower() in ("false", "0", "no", "n"):
                return False
        if isinstance(value, (int, float)):
            return value != 0
        return value

    def _compile_pattern(self, pattern: str) -> Pattern:
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(pattern)
        return self._pattern_cache[pattern]

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Callback '{event}' failed: {e}")

    def register_callback(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> bool:
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
            return True
        return False

    def register_schema(
        self,
        name: str,
        schema_def: SchemaDefinition,
        version: str = "1.0.0",
    ) -> None:
        schema_def.name = name
        schema_def.version = version
        self._schemas[name] = schema_def
        self._schema_versions[name].append(version)
        logger.info(f"Registered schema '{name}' version {version}")

    def register_schema_from_dict(
        self,
        name: str,
        schema_dict: Dict[str, Any],
        version: str = "1.0.0",
    ) -> SchemaDefinition:
        schema_def = self._dict_to_schema(schema_dict, name)
        schema_def.version = version
        self._schemas[name] = schema_def
        self._schema_versions[name].append(version)
        logger.info(f"Registered schema '{name}' version {version} from dict")
        return schema_def

    def _dict_to_schema(
        self, schema_dict: Dict[str, Any], name: str = ""
    ) -> SchemaDefinition:
        stype = SchemaType(schema_dict.get("type", "dict"))
        fields = None
        if stype == SchemaType.DICT and "fields" in schema_dict:
            fields = {}
            for field_name, field_def in schema_dict["fields"].items():
                if isinstance(field_def, dict):
                    fields[field_name] = self._dict_to_schema(
                        field_def, f"{name}.{field_name}"
                    )
                else:
                    fields[field_name] = field_def

        item_schema = None
        if "item_schema" in schema_dict:
            item_schema = self._dict_to_schema(
                schema_dict["item_schema"], f"{name}.items"
            )

        constraints = None
        if "constraints" in schema_dict:
            c = schema_dict["constraints"]
            constraints = FieldConstraint(
                min_length=c.get("min_length"),
                max_length=c.get("max_length"),
                min_value=c.get("min_value"),
                max_value=c.get("max_value"),
                pattern=c.get("pattern"),
                enum_values=c.get("enum_values"),
                allowed_types=c.get("allowed_types"),
            )

        return SchemaDefinition(
            name=name,
            type=stype,
            fields=fields,
            item_type=(
                SchemaType(schema_dict["item_type"])
                if "item_type" in schema_dict else None
            ),
            item_schema=item_schema,
            constraints=constraints,
            nullable=schema_dict.get("nullable", False),
            default=schema_dict.get("default"),
            description=schema_dict.get("description", ""),
            metadata=schema_dict.get("metadata", {}),
        )

    def get_schema(self, name: str) -> Optional[SchemaDefinition]:
        return self._schemas.get(name)

    def remove_schema(self, name: str) -> bool:
        if name in self._schemas:
            del self._schemas[name]
            logger.info(f"Removed schema '{name}'")
            return True
        return False

    def list_schemas(self) -> List[str]:
        return list(self._schemas.keys())

    def get_schema_versions(self, name: str) -> List[str]:
        return list(self._schema_versions.get(name, []))

    def has_schema(self, name: str) -> bool:
        return name in self._schemas

    def register_custom_validator(
        self,
        name: str,
        validator_func: Callable,
        description: str = "",
        applies_to: Optional[List[str]] = None,
        priority: int = 100,
    ) -> CustomValidator:
        cv = CustomValidator(
            name=name,
            validator_func=validator_func,
            description=description,
            applies_to=applies_to or [],
            priority=priority,
        )
        self._custom_validators[name] = cv
        logger.info(f"Registered custom validator '{name}'")
        return cv

    def unregister_custom_validator(self, name: str) -> bool:
        if name in self._custom_validators:
            del self._custom_validators[name]
            return True
        return False

    def get_custom_validator(self, name: str) -> Optional[CustomValidator]:
        return self._custom_validators.get(name)

    def validate(
        self,
        data: Any,
        schema_name: Optional[str] = None,
        schema: Optional[SchemaDefinition] = None,
        path: str = "$",
        coerce: Optional[bool] = None,
    ) -> StructureValidationResult:
        start_time = time.perf_counter()
        result = StructureValidationResult(path=path, is_valid=True)

        if coerce is None:
            coerce = self._coerce_types

        active_schema = schema
        if schema_name:
            active_schema = self._schemas.get(schema_name)
            if active_schema is None:
                result.add_error(
                    f"Schema '{schema_name}' not found",
                    code="SCHEMA_NOT_FOUND",
                )
                result.execution_time_ms = (time.perf_counter() - start_time) * 1000
                self._stats["schema_not_found"] += 1
                return result

        if active_schema is None:
            result.add_error(
                "No schema provided and no schema name given",
                code="NO_SCHEMA",
            )
            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
            return result

        self._trigger_callbacks("before_validate", data, active_schema, path)

        coerced_data = None
        if coerce:
            coerced_data = self._coerce_value(data, active_schema)
        else:
            coerced_data = data

        validation_data = coerced_data if coerce else data
        self._validate_value(validation_data, active_schema, path, result, coerce)

        if result.is_valid:
            custom_validators = sorted(
                [v for v in self._custom_validators.values() if v.enabled],
                key=lambda v: v.priority,
            )
            for cv in custom_validators:
                if cv.applies_to and active_schema.name not in cv.applies_to:
                    continue
                if not cv.applies_to:
                    continue
                try:
                    cv_result = cv.validator_func(validation_data, active_schema, path)
                    if isinstance(cv_result, list):
                        for err in cv_result:
                            if isinstance(err, dict):
                                result.add_error(
                                    err.get("message", "Custom validation failed"),
                                    code=err.get("code", "CUSTOM_ERROR"),
                                )
                except Exception as e:
                    logger.warning(f"Custom validator '{cv.name}' failed: {e}")

        result.coerced_value = coerced_data if coerce else None
        result.execution_time_ms = (time.perf_counter() - start_time) * 1000

        self._validation_history.append(result)
        if len(self._validation_history) > self._max_history:
            self._validation_history.pop(0)

        self._stats["total_validations"] += 1
        if not result.is_valid:
            self._stats["failed_validations"] += 1

        self._trigger_callbacks(
            "after_validate", data, active_schema, path, result
        )

        return result

    def _coerce_value(self, value: Any, schema: SchemaDefinition) -> Any:
        stype = schema.type

        if stype == SchemaType.ANY:
            return value

        if stype in (SchemaType.NULLABLE_STRING, SchemaType.NULLABLE_INTEGER):
            if value is None:
                return None
            actual_type = stype.value.replace("nullable_", "")
            coercer = self._type_coercion_map.get(actual_type)
            if coercer:
                return coercer(value)
            return value

        if stype == SchemaType.DICT and schema.fields:
            if not isinstance(value, dict):
                if self._coerce_types:
                    return value
                return value
            coerced: Dict[str, Any] = {}
            for field_name, field_schema in schema.fields.items():
                if isinstance(field_schema, SchemaDefinition):
                    if field_name in value:
                        coerced[field_name] = self._coerce_value(
                            value[field_name], field_schema
                        )
                    elif field_schema.default is not None:
                        coerced[field_name] = field_schema.default
                else:
                    if field_name in value:
                        coerced[field_name] = value[field_name]
            for key, val in value.items():
                if key not in coerced:
                    coerced[key] = val
            return coerced

        if stype == SchemaType.LIST:
            if not isinstance(value, list):
                return value
            if schema.item_schema:
                return [
                    self._coerce_value(item, schema.item_schema)
                    for item in value
                ]
            return value

        coercer = self._type_coercion_map.get(stype.value)
        if coercer:
            return coercer(value)
        return value

    def _validate_value(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: str,
        result: StructureValidationResult,
        coerce: bool,
    ) -> None:
        stype = schema.type

        if stype in (SchemaType.NULLABLE_STRING, SchemaType.NULLABLE_INTEGER):
            if value is None:
                return
            actual_type = stype.value.replace("nullable_", "")
            self._validate_type(
                value, SchemaType(actual_type), path, result
            )
            return

        if stype == SchemaType.ANY:
            return

        if stype == SchemaType.DICT:
            self._validate_dict(value, schema, path, result, coerce)

        elif stype == SchemaType.LIST:
            self._validate_list(value, schema, path, result, coerce)

        elif stype == SchemaType.STRING:
            self._validate_type(value, SchemaType.STRING, path, result)
            if isinstance(value, str) and schema.constraints:
                self._apply_string_constraints(value, schema.constraints, path, result)

        elif stype == SchemaType.INTEGER:
            self._validate_type(value, SchemaType.INTEGER, path, result)
            if isinstance(value, int) and not isinstance(value, bool):
                if schema.constraints:
                    self._apply_numeric_constraints(
                        value, schema.constraints, path, result
                    )

        elif stype == SchemaType.FLOAT:
            self._validate_type(value, SchemaType.FLOAT, path, result)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if schema.constraints:
                    self._apply_numeric_constraints(
                        float(value), schema.constraints, path, result
                    )

        elif stype == SchemaType.BOOLEAN:
            self._validate_type(value, SchemaType.BOOLEAN, path, result)

        elif stype == SchemaType.DATETIME:
            self._validate_datetime(value, path, result)

        elif stype == SchemaType.DATE:
            self._validate_date(value, path, result)

        elif stype == SchemaType.ENUM:
            self._validate_enum(value, schema, path, result)

        elif stype == SchemaType.UNION:
            self._validate_union(value, schema, path, result, coerce)

        elif stype == SchemaType.CUSTOM:
            pass

    def _validate_type(
        self,
        value: Any,
        expected_type: SchemaType,
        path: str,
        result: StructureValidationResult,
    ) -> None:
        type_map = {
            SchemaType.STRING: str,
            SchemaType.INTEGER: (int,),
            SchemaType.FLOAT: (int, float),
            SchemaType.BOOLEAN: bool,
            SchemaType.DICT: dict,
            SchemaType.LIST: list,
        }

        expected = type_map.get(expected_type)
        if expected is None:
            return

        if isinstance(value, bool) and expected_type == SchemaType.INTEGER:
            result.add_error(
                f"Type mismatch at {path}: expected integer, got boolean",
                code="TYPE_MISMATCH",
                expected="integer",
                actual="boolean",
            )
            return

        if not isinstance(value, expected):
            result.add_error(
                f"Type mismatch at {path}: expected {expected_type.value}, "
                f"got {type(value).__name__}",
                code="TYPE_MISMATCH",
                expected=expected_type.value,
                actual=type(value).__name__,
            )

    def _validate_dict(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: str,
        result: StructureValidationResult,
        coerce: bool,
    ) -> None:
        if not isinstance(value, dict):
            result.add_error(
                f"Expected dict at {path}, got {type(value).__name__}",
                code="TYPE_MISMATCH",
                expected="dict",
                actual=type(value).__name__,
            )
            return

        if schema.fields is None:
            return

        for field_name, field_schema in schema.fields.items():
            field_path = f"{path}.{field_name}"
            field_type = FieldType.REQUIRED
            field_def = field_schema

            if isinstance(field_schema, dict):
                field_type = FieldType(
                    field_schema.get("type", FieldType.REQUIRED.value)
                )
                if "schema" in field_schema:
                    field_def = field_schema["schema"]
                else:
                    field_type = FieldType.REQUIRED

            if isinstance(field_def, SchemaDefinition):
                pass
            elif isinstance(field_def, str):
                try:
                    st = SchemaType(field_def)
                    field_def = SchemaDefinition(
                        name=field_name, type=st
                    )
                except ValueError:
                    if field_def in self._schemas:
                        field_def = self._schemas[field_def]
                    else:
                        field_def = SchemaDefinition(
                            name=field_name, type=SchemaType.STRING
                        )
            else:
                field_def = SchemaDefinition(
                    name=field_name, type=SchemaType.STRING
                )

            field_schema_def: SchemaDefinition = field_def

            if field_name not in value:
                if field_type == FieldType.REQUIRED:
                    result.add_error(
                        f"Required field missing at {field_path}",
                        code="MISSING_FIELD",
                        expected=f"field '{field_name}'",
                        actual="missing",
                    )
                elif field_type == FieldType.CONDITIONAL:
                    condition_met = self._check_condition(
                        field_schema_def, value, path
                    )
                    if condition_met:
                        result.add_error(
                            f"Conditional required field missing at {field_path}",
                            code="MISSING_CONDITIONAL_FIELD",
                            expected=f"field '{field_name}'",
                            actual="missing",
                        )
                if field_schema_def.default is not None:
                    value[field_name] = field_schema_def.default
                continue

            field_val = value[field_name]
            if field_val is None:
                if field_schema_def.nullable:
                    continue
                result.add_error(
                    f"Field at {field_path} is null but not nullable",
                    code="NULL_NOT_ALLOWED",
                    expected="non-null",
                    actual="null",
                )
                continue

            self._validate_value(
                field_val, field_schema_def, field_path, result, coerce
            )

        unknown_fields = set(value.keys()) - (
            set(schema.fields.keys()) if schema.fields else set()
        )
        if unknown_fields and self._strict_mode:
            for uf in unknown_fields:
                result.add_warning(
                    f"Unknown field '{uf}' at {path}",
                    code="UNKNOWN_FIELD",
                )

    def _check_condition(
        self,
        schema: SchemaDefinition,
        data: Dict[str, Any],
        path: str,
    ) -> bool:
        metadata = schema.metadata
        if "depends_on" in metadata:
            dep_field = metadata["depends_on"]
            dep_value = metadata.get("depends_value")
            actual_value = data.get(dep_field)
            if dep_value is not None:
                return actual_value == dep_value
            return actual_value is not None
        return False

    def _validate_list(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: str,
        result: StructureValidationResult,
        coerce: bool,
    ) -> None:
        if not isinstance(value, list):
            result.add_error(
                f"Expected list at {path}, got {type(value).__name__}",
                code="TYPE_MISMATCH",
                expected="list",
                actual=type(value).__name__,
            )
            return

        if schema.constraints:
            self._apply_list_constraints(
                value, schema.constraints, path, result
            )

        if schema.item_schema:
            for i, item in enumerate(value):
                item_path = f"{path}[{i}]"
                self._validate_value(
                    item, schema.item_schema, item_path, result, coerce
                )

        elif schema.item_type:
            item_schema = SchemaDefinition(
                name=f"{schema.name}.items",
                type=schema.item_type,
            )
            for i, item in enumerate(value):
                item_path = f"{path}[{i}]"
                self._validate_value(
                    item, item_schema, item_path, result, coerce
                )

    def _validate_datetime(
        self, value: Any, path: str, result: StructureValidationResult
    ) -> None:
        if isinstance(value, datetime):
            return
        if isinstance(value, str):
            formats = [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y",
            ]
            for fmt in formats:
                try:
                    datetime.strptime(value, fmt)
                    return
                except ValueError:
                    continue
            result.add_error(
                f"Invalid datetime format at {path}: '{value[:50]}'",
                code="INVALID_DATETIME",
                expected="ISO 8601 datetime string",
                actual=value[:50],
            )
        else:
            result.add_error(
                f"Expected datetime/string at {path}, got {type(value).__name__}",
                code="TYPE_MISMATCH",
                expected="datetime or string",
                actual=type(value).__name__,
            )

    def _validate_date(
        self, value: Any, path: str, result: StructureValidationResult
    ) -> None:
        if isinstance(value, (datetime, date)):
            return
        if isinstance(value, str):
            formats = [
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%d/%m/%Y",
                "%Y-%m-%dT%H:%M:%S",
            ]
            for fmt in formats:
                try:
                    datetime.strptime(value, fmt)
                    return
                except ValueError:
                    continue
            result.add_error(
                f"Invalid date format at {path}: '{value[:30]}'",
                code="INVALID_DATE",
                expected="date string (YYYY-MM-DD)",
                actual=value[:30],
            )
        else:
            result.add_error(
                f"Expected date/string at {path}, got {type(value).__name__}",
                code="TYPE_MISMATCH",
                expected="date or string",
                actual=type(value).__name__,
            )

    def _validate_enum(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: str,
        result: StructureValidationResult,
    ) -> None:
        if schema.constraints and schema.constraints.enum_values:
            if value not in schema.constraints.enum_values:
                result.add_error(
                    f"Value '{value}' not in enum at {path}: "
                    f"{schema.constraints.enum_values}",
                    code="INVALID_ENUM_VALUE",
                    expected=schema.constraints.enum_values,
                    actual=value,
                )

    def _validate_union(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: str,
        result: StructureValidationResult,
        coerce: bool,
    ) -> None:
        if not schema.fields:
            result.add_error(
                f"Union type at {path} has no variant definitions",
                code="INVALID_UNION",
            )
            return

        discriminator = schema.metadata.get("discriminator", "type")
        if isinstance(value, dict):
            variant_key = value.get(discriminator)
            if variant_key and variant_key in schema.fields:
                variant_schema = schema.fields[variant_key]
                if isinstance(variant_schema, SchemaDefinition):
                    self._validate_value(
                        value, variant_schema, path, result, coerce
                    )
                    return

        valid = False
        for variant_name, variant_schema in schema.fields.items():
            if isinstance(variant_schema, SchemaDefinition):
                temp_result = StructureValidationResult(path=path, is_valid=True)
                self._validate_value(
                    value, variant_schema, path, temp_result, coerce
                )
                if temp_result.is_valid:
                    valid = True
                    break

        if not valid:
            result.add_error(
                f"Value at {path} does not match any union variant",
                code="UNION_MISMATCH",
                expected=f"one of: {list(schema.fields.keys())}",
                actual=type(value).__name__,
            )

    def _apply_string_constraints(
        self,
        value: str,
        constraints: FieldConstraint,
        path: str,
        result: StructureValidationResult,
    ) -> None:
        if constraints.min_length is not None and len(value) < constraints.min_length:
            result.add_error(
                f"String too short at {path}: {len(value)} chars "
                f"(min: {constraints.min_length})",
                code="STRING_TOO_SHORT",
                expected=f"min_length={constraints.min_length}",
                actual=len(value),
            )
        if constraints.max_length is not None and len(value) > constraints.max_length:
            result.add_error(
                f"String too long at {path}: {len(value)} chars "
                f"(max: {constraints.max_length})",
                code="STRING_TOO_LONG",
                expected=f"max_length={constraints.max_length}",
                actual=len(value),
            )
        if constraints.pattern is not None:
            pattern = self._compile_pattern(constraints.pattern)
            if not pattern.match(value):
                result.add_error(
                    f"String at {path} does not match pattern '{constraints.pattern}'",
                    code="PATTERN_MISMATCH",
                    expected=constraints.pattern,
                    actual=value[:100],
                )

    def _apply_numeric_constraints(
        self,
        value: Union[int, float],
        constraints: FieldConstraint,
        path: str,
        result: StructureValidationResult,
    ) -> None:
        if constraints.min_value is not None and value < constraints.min_value:
            result.add_error(
                f"Value too small at {path}: {value} (min: {constraints.min_value})",
                code="VALUE_TOO_SMALL",
                expected=f">= {constraints.min_value}",
                actual=value,
            )
        if constraints.max_value is not None and value > constraints.max_value:
            result.add_error(
                f"Value too large at {path}: {value} (max: {constraints.max_value})",
                code="VALUE_TOO_LARGE",
                expected=f"<= {constraints.max_value}",
                actual=value,
            )

    def _apply_list_constraints(
        self,
        value: List[Any],
        constraints: FieldConstraint,
        path: str,
        result: StructureValidationResult,
    ) -> None:
        if constraints.min_length is not None and len(value) < constraints.min_length:
            result.add_error(
                f"List too short at {path}: {len(value)} items "
                f"(min: {constraints.min_length})",
                code="LIST_TOO_SHORT",
                expected=f"min_items={constraints.min_length}",
                actual=len(value),
            )
        if constraints.max_length is not None and len(value) > constraints.max_length:
            result.add_error(
                f"List too long at {path}: {len(value)} items "
                f"(max: {constraints.max_length})",
                code="LIST_TOO_LONG",
                expected=f"max_items={constraints.max_length}",
                actual=len(value),
            )

    def validate_json_string(
        self,
        json_str: str,
        schema_name: Optional[str] = None,
        schema: Optional[SchemaDefinition] = None,
    ) -> StructureValidationResult:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            result = StructureValidationResult(path="$", is_valid=False)
            result.add_error(
                f"Invalid JSON: {e.msg}",
                code="INVALID_JSON",
            )
            return result
        return self.validate(data, schema_name=schema_name, schema=schema)

    def validate_batch(
        self,
        items: List[Any],
        schema_name: str,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> List[StructureValidationResult]:
        if parallel:
            return self._validate_batch_parallel(
                items, schema_name, max_workers
            )
        results = []
        for i, item in enumerate(items):
            result = self.validate(item, schema_name=schema_name)
            results.append(result)
        return results

    def _validate_batch_parallel(
        self,
        items: List[Any],
        schema_name: str,
        max_workers: int,
    ) -> List[StructureValidationResult]:
        results: List[StructureValidationResult] = []
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self.validate, item, schema_name=schema_name
                    ): i
                    for i, item in enumerate(items)
                }
                ordered: List[Optional[StructureValidationResult]] = [
                    None
                ] * len(items)
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        ordered[idx] = future.result()
                    except Exception as e:
                        r = StructureValidationResult(path="$", is_valid=False)
                        r.add_error(str(e), code="BATCH_ERROR")
                        ordered[idx] = r
                results = [r for r in ordered if r is not None]
        except ImportError:
            logger.warning("ThreadPoolExecutor unavailable, using sequential")
            results = [
                self.validate(item, schema_name=schema_name) for item in items
            ]
        return results

    def set_coercion(self, enabled: bool) -> None:
        self._coerce_types = enabled

    def set_strict_mode(self, enabled: bool) -> None:
        self._strict_mode = enabled

    def set_max_depth(self, depth: int) -> None:
        self._max_depth = depth

    def get_stats(self) -> Dict[str, Any]:
        total = self._stats.get("total_validations", 0)
        failed = self._stats.get("failed_validations", 0)
        return {
            "total_validations": total,
            "failed_validations": failed,
            "failure_rate": round(failed / total, 4) if total > 0 else 0.0,
            "schema_count": len(self._schemas),
            "custom_validator_count": len(self._custom_validators),
            "history_size": len(self._validation_history),
            "pattern_cache_size": len(self._pattern_cache),
        }

    def reset_stats(self) -> None:
        self._stats.clear()
        logger.info("Structure validation stats reset")

    def get_validation_history(
        self,
        limit: int = 10,
        only_failed: bool = False,
    ) -> List[StructureValidationResult]:
        history = list(self._validation_history)
        if only_failed:
            history = [r for r in history if not r.is_valid]
        return history[-limit:]

    def clear_history(self) -> None:
        self._validation_history.clear()
        logger.info("Validation history cleared")

    def export_schemas(self) -> Dict[str, Any]:
        def _schema_to_dict(sd: SchemaDefinition) -> Dict[str, Any]:
            result: Dict[str, Any] = {
                "name": sd.name,
                "version": sd.version,
                "type": sd.type.value,
                "nullable": sd.nullable,
                "description": sd.description,
            }
            if sd.fields:
                result["fields"] = {
                    k: (
                        _schema_to_dict(v)
                        if isinstance(v, SchemaDefinition)
                        else v
                    )
                    for k, v in sd.fields.items()
                }
            if sd.item_type:
                result["item_type"] = sd.item_type.value
            if sd.item_schema:
                result["item_schema"] = _schema_to_dict(sd.item_schema)
            if sd.constraints:
                c = sd.constraints
                result["constraints"] = {
                    k: v for k, v in {
                        "min_length": c.min_length,
                        "max_length": c.max_length,
                        "min_value": c.min_value,
                        "max_value": c.max_value,
                        "pattern": c.pattern,
                        "enum_values": c.enum_values,
                    }.items() if v is not None
                }
            if sd.metadata:
                result["metadata"] = sd.metadata
            return result

        return {
            name: _schema_to_dict(sd)
            for name, sd in self._schemas.items()
        }

    def import_schemas(self, schemas_dict: Dict[str, Any]) -> int:
        count = 0
        for name, schema_data in schemas_dict.items():
            try:
                self.register_schema_from_dict(name, schema_data)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import schema '{name}': {e}")
        logger.info(f"Imported {count} schemas")
        return count

    def create_schema_from_instance(
        self,
        instance: Dict[str, Any],
        name: str,
        infer_types: bool = True,
    ) -> SchemaDefinition:
        fields: Dict[str, Any] = {}
        for key, value in instance.items():
            if infer_types:
                if isinstance(value, bool):
                    st = SchemaType.BOOLEAN
                elif isinstance(value, int):
                    st = SchemaType.INTEGER
                elif isinstance(value, float):
                    st = SchemaType.FLOAT
                elif isinstance(value, str):
                    st = SchemaType.STRING
                elif isinstance(value, list):
                    st = SchemaType.LIST
                elif isinstance(value, dict):
                    st = SchemaType.DICT
                elif value is None:
                    st = SchemaType.NULLABLE_STRING
                else:
                    st = SchemaType.STRING
                fields[key] = SchemaDefinition(name=key, type=st)
            else:
                fields[key] = SchemaDefinition(
                    name=key, type=SchemaType.STRING
                )
        return SchemaDefinition(name=name, type=SchemaType.DICT, fields=fields)

    def diff_schemas(
        self,
        schema_a: str,
        schema_b: str,
    ) -> Dict[str, Any]:
        sa = self._schemas.get(schema_a)
        sb = self._schemas.get(schema_b)
        if not sa or not sb:
            return {"error": "One or both schemas not found"}

        def _compare_fields(
            fa: Optional[Dict[str, Any]],
            fb: Optional[Dict[str, Any]],
            path: str = "",
        ) -> List[Dict[str, str]]:
            diffs: List[Dict[str, str]] = []
            fa = fa or {}
            fb = fb or {}
            all_keys = set(fa.keys()) | set(fb.keys())
            for key in sorted(all_keys):
                full_path = f"{path}.{key}" if path else key
                if key not in fa:
                    diffs.append({
                        "path": full_path,
                        "type": "added",
                        "message": f"Field '{full_path}' added in schema B",
                    })
                elif key not in fb:
                    diffs.append({
                        "path": full_path,
                        "type": "removed",
                        "message": f"Field '{full_path}' removed in schema B",
                    })
                else:
                    va = fa[key]
                    vb = fb[key]
                    if isinstance(va, SchemaDefinition) and isinstance(vb, SchemaDefinition):
                        if va.type != vb.type:
                            diffs.append({
                                "path": full_path,
                                "type": "changed",
                                "message": (
                                    f"Field '{full_path}' type changed: "
                                    f"{va.type.value} -> {vb.type.value}"
                                ),
                            })
                        if va.fields or vb.fields:
                            diffs.extend(
                                _compare_fields(va.fields, vb.fields, full_path)
                            )
                    elif va != vb:
                        diffs.append({
                            "path": full_path,
                            "type": "changed",
                            "message": f"Field '{full_path}' definition changed",
                        })
            return diffs

        diffs = _compare_fields(sa.fields, sb.fields)
        return {
            "schema_a": schema_a,
            "schema_b": schema_b,
            "has_differences": len(diffs) > 0,
            "differences": diffs,
            "added_count": sum(1 for d in diffs if d["type"] == "added"),
            "removed_count": sum(1 for d in diffs if d["type"] == "removed"),
            "changed_count": sum(1 for d in diffs if d["type"] == "changed"),
        }

    def __repr__(self) -> str:
        return (
            f"StructureValidator(schemas={len(self._schemas)}, "
            f"validators={len(self._custom_validators)}, "
            f"coerce={self._coerce_types})"
        )
