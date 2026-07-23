"""Rule serializer - serializes/deserializes rules between dict, JSON, YAML, and database formats."""
import logging
import json
import yaml
from typing import List, Dict, Any, Optional, Union, Type
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SerializationFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"
    DICT = "dict"
    COMPACT = "compact"


@dataclass
class SerializationOptions:
    include_metadata: bool = True
    pretty_print: bool = True
    sort_keys: bool = False
    exclude_fields: List[str] = field(default_factory=list)
    default_tier: str = "preference"


@dataclass
class RuleSchema:
    version: str = "1.0"
    required_fields: List[str] = field(default_factory=lambda: ["id", "name", "tier", "patterns"])
    optional_fields: Dict[str, Any] = field(default_factory=lambda: {
        "description": "", "severity": "medium", "enforcement": "advisory",
        "priority": 100, "timeout_ms": 1000, "tags": [],
        "conditions": {}, "user_override": True, "auto_block": False,
    })


class RuleSerializer:
    def __init__(self, schema: Optional[RuleSchema] = None) -> None:
        self.schema = schema or RuleSchema()
        self.supported_formats = {SerializationFormat.JSON, SerializationFormat.YAML,
                                  SerializationFormat.DICT, SerializationFormat.COMPACT}
        logger.info("RuleSerializer initialized (format=%s)", self.supported_formats)

    def serialize(self, rule: Dict[str, Any],
                  format: SerializationFormat = SerializationFormat.JSON,
                  options: Optional[SerializationOptions] = None) -> Union[str, Dict[str, Any]]:
        opts = options or SerializationOptions()
        data = self._prepare_rule(rule, opts)

        if format == SerializationFormat.DICT:
            return data
        elif format == SerializationFormat.JSON:
            return json.dumps(data, indent=2 if opts.pretty_print else None,
                             sort_keys=opts.sort_keys, default=str)
        elif format == SerializationFormat.YAML:
            return yaml.dump(data, default_flow_style=False, sort_keys=opts.sort_keys)
        elif format == SerializationFormat.COMPACT:
            compact = {k: v for k, v in data.items()
                      if k in ("id", "name", "tier", "patterns", "enforcement")}
            return json.dumps(compact, default=str)
        raise ValueError(f"Unsupported format: {format}")

    def serialize_many(self, rules: List[Dict[str, Any]],
                       format: SerializationFormat = SerializationFormat.JSON,
                       options: Optional[SerializationOptions] = None) -> Union[str, List[Dict[str, Any]]]:
        serialized = [self.serialize(r, SerializationFormat.DICT, options) for r in rules]
        if format == SerializationFormat.DICT:
            return serialized
        elif format == SerializationFormat.JSON:
            return json.dumps({"rules": serialized}, indent=2 if options and options.pretty_print else None,
                             default=str)
        elif format == SerializationFormat.YAML:
            return yaml.dump({"rules": serialized}, default_flow_style=False)
        raise ValueError(f"Unsupported format: {format}")

    def deserialize(self, data: Union[str, Dict[str, Any]],
                    format: SerializationFormat = SerializationFormat.JSON) -> Dict[str, Any]:
        if format == SerializationFormat.DICT:
            parsed = data
        elif format in (SerializationFormat.JSON, SerializationFormat.COMPACT):
            parsed = json.loads(data) if isinstance(data, str) else data
        elif format == SerializationFormat.YAML:
            parsed = yaml.safe_load(data) if isinstance(data, str) else data
        else:
            raise ValueError(f"Unsupported format: {format}")

        return self._normalize_rule(parsed)

    def deserialize_many(self, data: Union[str, List, Dict],
                         format: SerializationFormat = SerializationFormat.JSON) -> List[Dict[str, Any]]:
        if format == SerializationFormat.DICT and isinstance(data, list):
            items = data
        elif isinstance(data, str):
            parsed = json.loads(data) if format in (SerializationFormat.JSON, SerializationFormat.COMPACT) else yaml.safe_load(data)
            items = parsed.get("rules", parsed) if isinstance(parsed, dict) else parsed
        else:
            items = data.get("rules", [data]) if isinstance(data, dict) else data

        if isinstance(items, dict):
            items = [items]
        return [self.deserialize(item, SerializationFormat.DICT) for item in items]

    def convert_format(self, rule: Dict[str, Any],
                       target_format: SerializationFormat,
                       options: Optional[SerializationOptions] = None) -> Union[str, Dict[str, Any]]:
        normalized = self.deserialize(rule, SerializationFormat.DICT)
        return self.serialize(normalized, target_format, options)

    def validate_structure(self, rule: Dict[str, Any]) -> List[str]:
        errors = []
        for field in self.schema.required_fields:
            if field not in rule:
                errors.append(f"Missing required field: {field}")
        if "patterns" in rule and not isinstance(rule["patterns"], list):
            errors.append("'patterns' must be a list")
        if "tier" in rule and rule["tier"] not in ("safety", "operational", "preference"):
            errors.append(f"Invalid tier: {rule['tier']}")
        return errors

    def merge_with_defaults(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        merged = {}
        for k, v in self.schema.optional_fields.items():
            merged[k] = v
        merged.update(rule)
        if "tier" not in rule:
            merged["tier"] = self.schema.default_tier
        return merged

    def _prepare_rule(self, rule: Dict[str, Any], opts: SerializationOptions) -> Dict[str, Any]:
        data = dict(rule)
        for field in opts.exclude_fields:
            data.pop(field, None)
        if not opts.include_metadata:
            data.pop("metadata", None)
            data.pop("created_at", None)
            data.pop("updated_at", None)
        return data

    def _normalize_rule(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data)}")
        return self.merge_with_defaults(data)
