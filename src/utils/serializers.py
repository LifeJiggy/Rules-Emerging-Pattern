"""Production-grade serialization utilities with JSON, YAML, compact, schema, and config-driven options."""

import json
import io
import os
import re
import gzip
import base64
import csv
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import datetime
import decimal
import uuid
import enum
import inspect
import hashlib
import threading
from typing import Any, Callable, Optional, Union, List, Dict, Tuple, Type, Set
from dataclasses import dataclass, field, asdict, is_dataclass
from collections import defaultdict, OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.debug("PyYAML not available, YAML serialization disabled")


@dataclass
class SerializerConfig:
    json_default_encoding: str = "utf-8"
    json_ensure_ascii: bool = True
    json_sort_keys: bool = False
    json_skip_none: bool = False
    json_allow_nan: bool = True
    yaml_default_flow_style: bool = False
    yaml_allow_unicode: bool = True
    yaml_width: int = 80
    csv_delimiter: str = ","
    csv_quotechar: str = '"'
    csv_quoting: int = csv.QUOTE_MINIMAL
    xml_default_encoding: str = "utf-8"
    xml_pretty: bool = True
    compact_compression_level: int = 9
    compact_base64: bool = True
    schema_strict: bool = False
    schema_allow_additional: bool = True
    max_depth: int = 10
    max_serialization_size: int = 100 * 1024 * 1024
    detect_sample_size: int = 4096
    datetime_format: str = "iso"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H:%M:%S"
    decimal_str: bool = True
    custom_encoders: Dict[str, Callable] = field(default_factory=dict)


DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$")
UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
ISO_DATETIME_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
)


class SerializationError(Exception):
    pass


class DeserializationError(Exception):
    pass


class SchemaValidationError(Exception):
    pass


class UnknownFormatError(ValueError):
    pass


class CustomJSONEncoder(json.JSONEncoder):
    def __init__(self, config: Optional[SerializerConfig] = None, extra_encoders: Optional[Dict[Type, Callable]] = None, **kwargs):
        super().__init__(**kwargs)
        self._config = config or SerializerConfig()
        self._extra_encoders = extra_encoders or {}

    def default(self, obj: Any) -> Any:
        obj_type = type(obj)
        if obj_type in self._extra_encoders:
            return self._extra_encoders[obj_type](obj)
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.date):
            return obj.isoformat()
        if isinstance(obj, datetime.time):
            return obj.isoformat()
        if isinstance(obj, datetime.timedelta):
            return obj.total_seconds()
        if isinstance(obj, decimal.Decimal):
            return str(obj) if self._config.decimal_str else float(obj)
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, enum.Enum):
            return obj.value
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        if isinstance(obj, complex):
            return {"real": obj.real, "imag": obj.imag}
        if isinstance(obj, range):
            return list(obj)
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return super().default(obj)


class Serializers:
    """Production-grade serialization with JSON, YAML, compact, schema validation, and format detection."""

    def __init__(self, config: Optional[SerializerConfig] = None):
        self.config = config or SerializerConfig()
        self._extra_encoders: Dict[Type, Callable] = {}
        self._extra_decoders: Dict[str, Callable] = {}
        self._schema_cache: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._serialization_count: int = 0
        self._deserialization_count: int = 0

    def to_json(self, obj: Any, pretty: bool = False, **kwargs) -> str:
        self._serialization_count += 1
        opts = {
            "ensure_ascii": self.config.json_ensure_ascii,
            "sort_keys": self.config.json_sort_keys,
            "allow_nan": self.config.json_allow_nan,
        }
        if pretty:
            opts["indent"] = 2
            opts["separators"] = (",", ": ")
        else:
            opts["separators"] = (",", ":")
        opts.update(kwargs)
        if self.config.json_skip_none:
            obj = self._skip_none(obj)
        encoder = CustomJSONEncoder(config=self.config, extra_encoders=self._extra_encoders, **opts)
        try:
            return encoder.encode(obj)
        except (TypeError, ValueError) as e:
            raise SerializationError(f"JSON serialization failed: {e}") from e

    def to_json_pretty(self, obj: Any) -> str:
        return self.to_json(obj, pretty=True)

    def from_json(self, text: Union[str, bytes], **kwargs) -> Any:
        self._deserialization_count += 1
        if isinstance(text, bytes):
            text = text.decode(self.config.json_default_encoding)
        try:
            parsed = json.loads(text, **kwargs)
            return self._post_process(parsed)
        except json.JSONDecodeError as e:
            raise DeserializationError(f"JSON deserialization failed at line {e.lineno}: {e.msg}") from e

    def to_json_stream(self, objs: List[Any], pretty: bool = False) -> str:
        items = [self.to_json(obj, pretty=pretty) for obj in objs]
        if pretty:
            return "[\n" + ",\n".join(items) + "\n]"
        return "[" + ",".join(items) + "]"

    def from_json_stream(self, text: str) -> List[Any]:
        parsed = self.from_json(text)
        if isinstance(parsed, list):
            return parsed
        raise DeserializationError("JSON stream must be an array")

    def to_jsonl(self, objs: List[Any]) -> str:
        lines = []
        for obj in objs:
            try:
                lines.append(self.to_json(obj))
            except SerializationError as e:
                logger.warning("Skipping object in JSONL: %s", e)
        return "\n".join(lines)

    def from_jsonl(self, text: str) -> List[Any]:
        results = []
        for i, line in enumerate(text.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                results.append(self.from_json(line))
            except DeserializationError as e:
                logger.warning("Error parsing JSONL line %d: %s", i, e)
        return results

    def to_yaml(self, obj: Any) -> str:
        self._serialization_count += 1
        if not HAS_YAML:
            raise SerializationError("PyYAML is not installed")
        try:
            return yaml.dump(
                obj,
                default_flow_style=self.config.yaml_default_flow_style,
                allow_unicode=self.config.yaml_allow_unicode,
                width=self.config.yaml_width,
                sort_keys=False
            )
        except yaml.YAMLError as e:
            raise SerializationError(f"YAML serialization failed: {e}") from e

    def from_yaml(self, text: str) -> Any:
        self._deserialization_count += 1
        if not HAS_YAML:
            raise DeserializationError("PyYAML is not installed")
        try:
            parsed = yaml.safe_load(text)
            return self._post_process(parsed)
        except yaml.YAMLError as e:
            raise DeserializationError(f"YAML deserialization failed: {e}") from e

    def to_yaml_file(self, obj: Any, path: Union[str, Path]) -> None:
        content = self.to_yaml(obj)
        Path(path).write_text(content, encoding=self.config.yaml_allow_unicode and "utf-8" or "ascii")

    def from_yaml_file(self, path: Union[str, Path]) -> Any:
        text = Path(path).read_text(encoding="utf-8")
        return self.from_yaml(text)

    def to_compact(self, obj: Any) -> str:
        self._serialization_count += 1
        json_str = self.to_json(obj)
        compressed = gzip.compress(json_str.encode("utf-8"), compresslevel=self.config.compact_compression_level)
        if self.config.compact_base64:
            return base64.b64encode(compressed).decode("ascii")
        return compressed.hex()

    def from_compact(self, text: str) -> Any:
        self._deserialization_count += 1
        try:
            if self.config.compact_base64:
                compressed = base64.b64decode(text)
            else:
                compressed = bytes.fromhex(text)
            json_str = gzip.decompress(compressed).decode("utf-8")
            return self.from_json(json_str)
        except (base64.binascii.Error, gzip.BadGzipFile, ValueError) as e:
            raise DeserializationError(f"Compact deserialization failed: {e}") from e

    def to_csv(self, objs: List[Dict[str, Any]]) -> str:
        self._serialization_count += 1
        if not objs:
            return ""
        fieldnames = list(OrderedDict.fromkeys(k for obj in objs for k in obj.keys()))
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            delimiter=self.config.csv_delimiter,
            quotechar=self.config.csv_quotechar,
            quoting=self.config.csv_quoting
        )
        writer.writeheader()
        for obj in objs:
            row = {k: self._csv_format(v) for k, v in obj.items()}
            writer.writerow(row)
        return output.getvalue()

    def from_csv(self, text: str) -> List[Dict[str, str]]:
        self._deserialization_count += 1
        output = io.StringIO(text)
        reader = csv.DictReader(
            output,
            delimiter=self.config.csv_delimiter,
            quotechar=self.config.csv_quotechar
        )
        return [dict(row) for row in reader]

    def to_xml(self, obj: Any, root_name: str = "root") -> str:
        self._serialization_count += 1
        root = ET.Element(root_name)
        self._build_xml(root, obj)
        if self.config.xml_pretty:
            rough = ET.tostring(root, encoding="unicode")
            dom = minidom.parseString(rough.encode("utf-8"))
            return dom.toprettyxml(indent="  ")
        return ET.tostring(root, encoding="unicode")

    def from_xml(self, text: str) -> Dict[str, Any]:
        self._deserialization_count += 1
        try:
            root = ET.fromstring(text)
            return self._parse_xml(root)
        except ET.ParseError as e:
            raise DeserializationError(f"XML deserialization failed: {e}") from e

    def _build_xml(self, parent: ET.Element, obj: Any):
        if isinstance(obj, dict):
            for key, value in obj.items():
                child = ET.SubElement(parent, str(key).replace(" ", "_"))
                self._build_xml(child, value)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                child = ET.SubElement(parent, "item")
                self._build_xml(child, item)
        elif isinstance(obj, bool):
            parent.text = str(obj).lower()
        elif obj is None:
            parent.text = ""
        else:
            parent.text = str(obj)

    def _parse_xml(self, element: ET.Element) -> Any:
        children = list(element)
        if not children:
            text = (element.text or "").strip()
            if text == "true":
                return True
            if text == "false":
                return False
            if text == "":
                return None
            try:
                if "." in text or "e" in text.lower():
                    return float(text)
                return int(text)
            except ValueError:
                return text
        result = {}
        tags_seen = defaultdict(int)
        for child in children:
            tags_seen[child.tag] += 1
        for child in children:
            parsed = self._parse_xml(child)
            if tags_seen[child.tag] > 1:
                result.setdefault(child.tag, []).append(parsed)
            else:
                result[child.tag] = parsed
        return result

    def detect_format(self, text: Union[str, bytes]) -> str:
        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8")
            except UnicodeDecodeError:
                return "binary"
        sample = text[:self.config.detect_sample_size].strip()
        if not sample:
            return "empty"
        if sample.startswith("{") or sample.startswith("["):
            try:
                json.loads(sample)
                return "json"
            except json.JSONDecodeError:
                pass
        if sample.startswith("%YAML") or sample.startswith("---"):
            return "yaml"
        if HAS_YAML:
            try:
                yaml.safe_load(sample)
                return "yaml"
            except yaml.YAMLError:
                pass
        if sample.startswith("<?xml") or sample.startswith("<"):
            try:
                ET.fromstring(sample + ("</root>" if not sample.rstrip().endswith(">") else ""))
                return "xml"
            except ET.ParseError:
                pass
        first_line = sample.split("\n")[0] if "\n" in sample else sample
        comma_count = first_line.count(self.config.csv_delimiter)
        if comma_count >= 1 and not first_line.startswith("<") and not first_line.startswith("{"):
            return "csv"
        if re.match(r"^[A-Za-z0-9+/=]{20,}$", sample[:100]):
            try:
                compressed = base64.b64decode(sample[:100])
                gzip.decompress(compressed)
                return "compact"
            except Exception:
                pass
        if re.match(r"^[0-9a-fA-F]{20,}$", sample[:100]):
            try:
                compressed = bytes.fromhex(sample[:100])
                gzip.decompress(compressed)
                return "compact"
            except Exception:
                pass
        return "unknown"

    def to_format(self, obj: Any, fmt: str, **kwargs) -> str:
        fmt = fmt.lower().strip()
        if fmt in ("json", "js"):
            return self.to_json(obj, **kwargs)
        if fmt in ("yaml", "yml"):
            return self.to_yaml(obj)
        if fmt == "compact":
            return self.to_compact(obj)
        if fmt == "csv":
            return self.to_csv(obj if isinstance(obj, list) else [obj], **kwargs)
        if fmt == "xml":
            return self.to_xml(obj, **kwargs)
        raise UnknownFormatError(f"Unknown serialization format: {fmt}")

    def from_format(self, text: str, fmt: Optional[str] = None) -> Any:
        if fmt is None:
            fmt = self.detect_format(text)
        fmt = fmt.lower().strip()
        if fmt in ("json", "js"):
            return self.from_json(text)
        if fmt in ("yaml", "yml"):
            return self.from_yaml(text)
        if fmt == "compact":
            return self.from_compact(text)
        if fmt == "csv":
            return self.from_csv(text)
        if fmt == "xml":
            return self.from_xml(text)
        raise UnknownFormatError(f"Unknown deserialization format: {fmt}")

    def to_file(self, obj: Any, path: Union[str, Path], fmt: Optional[str] = None) -> None:
        path = Path(path)
        if fmt is None:
            ext = path.suffix.lower()
            fmt_map = {".json": "json", ".yaml": "yaml", ".yml": "yaml",
                       ".csv": "csv", ".xml": "xml", ".cmp": "compact", ".gz": "compact"}
            fmt = fmt_map.get(ext, "json")
        content = self.to_format(obj, fmt)
        if fmt == "csv":
            path.write_text(content, encoding="utf-8-sig")
        else:
            path.write_text(content, encoding="utf-8")

    def from_file(self, path: Union[str, Path], fmt: Optional[str] = None) -> Any:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        return self.from_format(text, fmt)

    def register_encoder(self, obj_type: Type, encoder_fn: Callable[[Any], Any]):
        with self._lock:
            self._extra_encoders[obj_type] = encoder_fn
            logger.debug("Registered encoder for %s", obj_type.__name__)

    def register_decoder(self, type_name: str, decoder_fn: Callable[[Any], Any]):
        with self._lock:
            self._extra_decoders[type_name] = decoder_fn
            logger.debug("Registered decoder for type '%s'", type_name)

    def unregister_encoder(self, obj_type: Type):
        with self._lock:
            self._extra_encoders.pop(obj_type, None)

    def unregister_decoder(self, type_name: str):
        with self._lock:
            self._extra_decoders.pop(type_name, None)

    def validate_schema(self, data: Any, schema: Dict[str, Any]) -> bool:
        return self._validate_against_schema(data, schema, path="$")

    def _validate_against_schema(self, data: Any, schema: Any, path: str = "$") -> bool:
        if schema is None:
            return True
        if isinstance(schema, dict):
            if "type" in schema:
                type_map = {
                    "string": str, "number": (int, float), "integer": int,
                    "boolean": bool, "array": list, "object": dict, "null": type(None)
                }
                expected = type_map.get(schema["type"])
                if expected is not None and not isinstance(data, expected):
                    raise SchemaValidationError(f"{path}: expected type '{schema['type']}', got {type(data).__name__}")
            if "enum" in schema:
                if data not in schema["enum"]:
                    raise SchemaValidationError(f"{path}: value {data!r} not in enum {schema['enum']}")
            if schema.get("type") == "array" and "items" in schema:
                if isinstance(data, list):
                    for i, item in enumerate(data):
                        self._validate_against_schema(item, schema["items"], f"{path}[{i}]")
            if schema.get("type") == "object" and "properties" in schema:
                if isinstance(data, dict):
                    for prop_name, prop_schema in schema["properties"].items():
                        if prop_name in data:
                            self._validate_against_schema(data[prop_name], prop_schema, f"{path}.{prop_name}")
                        elif prop_schema.get("required", False):
                            raise SchemaValidationError(f"{path}: missing required property '{prop_name}'")
                    if not self.config.schema_allow_additional:
                        allowed = set(schema.get("properties", {}).keys())
                        extra = set(data.keys()) - allowed
                        if extra:
                            raise SchemaValidationError(f"{path}: unexpected properties {extra}")
            if "minLength" in schema and isinstance(data, str):
                if len(data) < schema["minLength"]:
                    raise SchemaValidationError(f"{path}: length {len(data)} < minLength {schema['minLength']}")
            if "maxLength" in schema and isinstance(data, str):
                if len(data) > schema["maxLength"]:
                    raise SchemaValidationError(f"{path}: length {len(data)} > maxLength {schema['maxLength']}")
            if "minimum" in schema and isinstance(data, (int, float)):
                if data < schema["minimum"]:
                    raise SchemaValidationError(f"{path}: {data} < minimum {schema['minimum']}")
            if "maximum" in schema and isinstance(data, (int, float)):
                if data > schema["maximum"]:
                    raise SchemaValidationError(f"{path}: {data} > maximum {schema['maximum']}")
            if "pattern" in schema and isinstance(data, str):
                if not re.search(schema["pattern"], data):
                    raise SchemaValidationError(f"{path}: does not match pattern {schema['pattern']}")
            if "minItems" in schema and isinstance(data, (list, tuple)):
                if len(data) < schema["minItems"]:
                    raise SchemaValidationError(f"{path}: length {len(data)} < minItems {schema['minItems']}")
            if "maxItems" in schema and isinstance(data, (list, tuple)):
                if len(data) > schema["maxItems"]:
                    raise SchemaValidationError(f"{path}: length {len(data)} > maxItems {schema['maxItems']}")
            if "required" in schema and isinstance(data, dict):
                for field in schema["required"]:
                    if field not in data:
                        raise SchemaValidationError(f"{path}: missing required field '{field}'")
            if "$ref" in schema:
                ref_path = schema["$ref"].lstrip("#/")
                ref_schema = self._resolve_json_ref(self.config, ref_path)
                if ref_schema:
                    self._validate_against_schema(data, ref_schema, path)
        return True

    def _resolve_json_ref(self, schema: Any, path: str) -> Optional[Any]:
        parts = path.split("/")
        current = schema
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return None
            else:
                return None
        return current

    def serialize_schema(self, schema: Dict[str, Any]) -> str:
        return self.to_json(schema, pretty=True)

    def _skip_none(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._skip_none(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [self._skip_none(item) for item in obj if item is not None]
        return obj

    def _csv_format(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def _post_process(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._post_process(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._post_process(item) for item in obj]
        if isinstance(obj, str):
            if ISO_DATETIME_REGEX.match(obj):
                try:
                    return datetime.datetime.fromisoformat(obj)
                except ValueError:
                    return obj
            if UUID_REGEX.match(obj):
                try:
                    return uuid.UUID(obj)
                except ValueError:
                    return obj
        return obj

    def to_bytes(self, obj: Any, encoding: str = "utf-8") -> bytes:
        return self.to_json(obj).encode(encoding)

    def from_bytes(self, data: bytes, encoding: str = "utf-8") -> Any:
        return self.from_json(data.decode(encoding))

    def hash_serialize(self, obj: Any, algorithm: str = "sha256") -> str:
        serialized = self.to_compact(obj)
        h = hashlib.new(algorithm)
        h.update(serialized.encode("utf-8"))
        return h.hexdigest()

    def deep_copy(self, obj: Any) -> Any:
        return self.from_compact(self.to_compact(obj))

    def merge_dicts(self, *dicts: Dict[str, Any], deep: bool = True) -> Dict[str, Any]:
        if not dicts:
            return {}
        if len(dicts) == 1:
            return dicts[0]
        result = {}
        for d in dicts:
            if deep:
                result = self._deep_merge(result, d)
            else:
                result.update(d)
        return result

    def _deep_merge(self, base: Any, override: Any) -> Any:
        if isinstance(base, dict) and isinstance(override, dict):
            merged = {}
            all_keys = set(base) | set(override)
            for key in all_keys:
                if key in base and key in override:
                    merged[key] = self._deep_merge(base[key], override[key])
                elif key in base:
                    merged[key] = base[key]
                else:
                    merged[key] = override[key]
            return merged
        return override

    def flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def unflatten_dict(self, d: Dict[str, Any], sep: str = ".") -> Dict[str, Any]:
        result = {}
        for key, value in d.items():
            parts = key.split(sep)
            current = result
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        return result

    def pretty_size(self, obj: Any) -> str:
        data = self.to_json(obj)
        size = len(data.encode("utf-8"))
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "serialization_count": self._serialization_count,
                "deserialization_count": self._deserialization_count,
                "custom_encoders": len(self._extra_encoders),
                "custom_decoders": len(self._extra_decoders),
                "has_yaml": HAS_YAML,
                "config": {
                    "json_ensure_ascii": self.config.json_ensure_ascii,
                    "json_sort_keys": self.config.json_sort_keys,
                    "json_skip_none": self.config.json_skip_none,
                    "schema_strict": self.config.schema_strict,
                    "max_depth": self.config.max_depth,
                }
            }

    def set_config(self, config: SerializerConfig):
        self.config = config

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning("Unknown config key: %s", key)

    def to_json_safe(self, obj: Any, fallback: Optional[str] = None) -> str:
        try:
            return self.to_json(obj)
        except (SerializationError, TypeError, ValueError):
            if fallback is not None:
                return fallback
            return "{}"

    def from_json_safe(self, text: str, fallback: Any = None) -> Any:
        try:
            return self.from_json(text)
        except DeserializationError:
            return fallback

    def json_diff(self, old: Any, new: Any) -> Dict[str, Any]:
        old_str = self.to_json(old, sort_keys=True)
        new_str = self.to_json(new, sort_keys=True)
        if old_str == new_str:
            return {"changed": False}
        old_dict = self.from_json(old_str) if isinstance(old, (dict, list)) else old
        new_dict = self.from_json(new_str) if isinstance(new, (dict, list)) else new
        return {
            "changed": True,
            "added": self._diff_keys(new_dict, old_dict) if isinstance(new_dict, dict) else {},
            "removed": self._diff_keys(old_dict, new_dict) if isinstance(old_dict, dict) else {},
            "modified": self._diff_modified(old_dict, new_dict) if isinstance(old_dict, dict) and isinstance(new_dict, dict) else {}
        }

    def _diff_keys(self, a: Dict, b: Dict) -> Dict:
        return {k: a[k] for k in a if k not in b}

    def _diff_modified(self, old: Dict, new: Dict) -> Dict:
        result = {}
        for k in old:
            if k in new:
                if old[k] != new[k]:
                    if isinstance(old[k], dict) and isinstance(new[k], dict):
                        nested = self._diff_modified(old[k], new[k])
                        if nested:
                            result[k] = nested
                    else:
                        result[k] = {"old": old[k], "new": new[k]}
        return result

    def roundtrip(self, obj: Any, fmt: str = "json") -> bool:
        try:
            serialized = self.to_format(obj, fmt)
            deserialized = self.from_format(serialized, fmt)
            return self.to_json(obj) == self.to_json(deserialized)
        except Exception:
            return False
