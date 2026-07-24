"""Production-grade configuration loader supporting YAML, JSON, TOML, ENV with hierarchy, schema validation, hot-reload, and secret encryption."""

import os
import re
import io
import json
import logging
import threading
import time
import hashlib
import base64
import copy
import fnmatch
import datetime
from typing import Any, Callable, Optional, Union, List, Dict, Tuple, Set, Type
from dataclasses import dataclass, field
from pathlib import Path
from collections import OrderedDict, defaultdict
from enum import Enum, auto

logger = logging.getLogger(__name__)

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.debug("PyYAML not available")

try:
    import toml
    HAS_TOML = True
except ImportError:
    try:
        import tomllib as toml
        HAS_TOML = True
    except ImportError:
        HAS_TOML = False
        logger.debug("TOML parser not available")

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.debug("cryptography not available, secret encryption disabled")


class ConfigFormat(Enum):
    JSON = auto()
    YAML = auto()
    TOML = auto()
    ENV = auto()
    PYTHON = auto()
    UNKNOWN = auto()


class ConfigError(Exception):
    pass


class SchemaValidationError(ConfigError):
    pass


class ConfigNotFoundError(ConfigError):
    pass


class SecretEncryptionError(ConfigError):
    pass


@dataclass
class ConfigLoaderConfig:
    default_config_path: Optional[str] = None
    env_prefix: str = "APP_"
    env_separator: str = "__"
    allow_env_override: bool = True
    allow_cli_override: bool = False
    auto_reload: bool = False
    auto_reload_interval: float = 30.0
    schema_strict: bool = True
    schema_cache: bool = True
    encryption_enabled: bool = False
    encryption_key: Optional[str] = None
    encryption_salt: Optional[str] = None
    config_search_paths: List[str] = field(default_factory=lambda: [
        ".", "config", "conf", "etc", "~/.config"
    ])
    config_file_names: List[str] = field(default_factory=lambda: [
        "config.yaml", "config.yml", "config.json", "config.toml", ".env"
    ])
    environment_name: str = "development"
    environment_mapping: Dict[str, str] = field(default_factory=lambda: {
        "dev": "development", "development": "development",
        "staging": "staging", "stage": "staging",
        "prod": "production", "production": "production",
        "test": "testing", "testing": "testing",
    })
    max_depth: int = 20
    secret_prefix: str = "encrypted:"
    audit_enabled: bool = True


@dataclass
class ConfigChange:
    timestamp: float
    action: str
    path: str
    old_value: Any = None
    new_value: Any = None
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.datetime.fromtimestamp(self.timestamp).isoformat(),
            "action": self.action,
            "path": self.path,
            "old_value": self._safe_repr(self.old_value),
            "new_value": self._safe_repr(self.new_value),
            "source": self.source,
        }

    @staticmethod
    def _safe_repr(val: Any) -> str:
        try:
            return repr(val)[:500]
        except Exception:
            return "<unprintable>"


class ConfigLoader:
    """Hierarchical configuration loader with multi-format support, schema validation, hot-reload, and secret management."""

    def __init__(self, config: Optional[ConfigLoaderConfig] = None):
        self.config = config or ConfigLoaderConfig()
        self._data: Dict[str, Any] = {}
        self._defaults: Dict[str, Any] = {}
        self._file_data: Dict[str, Any] = {}
        self._flat: Dict[str, Any] = OrderedDict()
        self._lock = threading.RLock()
        self._loaded_files: List[str] = []
        self._loaded_at: Optional[float] = None
        self._reload_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._watched_files: Dict[str, float] = {}
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._audit_log: List[ConfigChange] = []
        self._audit_max: int = 1000
        self._encryption_key_bytes: Optional[bytes] = None
        self._fernet: Any = None

        if self.config.encryption_enabled:
            self._init_encryption()

        if self.config.auto_reload:
            self._start_auto_reload()

    def _init_encryption(self):
        if not HAS_CRYPTO:
            logger.warning("cryptography library not installed, encryption disabled")
            return
        key = self.config.encryption_key
        salt = self.config.encryption_salt
        if key is None:
            key = os.environ.get(f"{self.config.env_prefix}ENCRYPTION_KEY")
        if salt is None:
            salt = os.environ.get(f"{self.config.env_prefix}ENCRYPTION_SALT")
        if key and salt:
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                             salt=salt.encode("utf-8"), iterations=600000)
            self._encryption_key_bytes = base64.urlsafe_b64encode(kdf.derive(key.encode("utf-8")))
            self._fernet = Fernet(self._encryption_key_bytes)
            logger.debug("Encryption initialized")
        else:
            logger.warning("Encryption key/salt not provided, encryption disabled")

    def load(self, path: Optional[Union[str, Path]] = None) -> "ConfigLoader":
        if path is None:
            path = self._find_default_config()
            if path is None:
                logger.info("No default config found, using empty config")
                self._loaded_at = time.time()
                return self
        path = Path(path)
        if not path.exists():
            raise ConfigNotFoundError(f"Config file not found: {path}")
        fmt = self._detect_format(path)
        raw = path.read_text(encoding="utf-8")
        parsed = self._parse_text(raw, fmt)
        with self._lock:
            self._file_data = parsed
            self._loaded_files = [str(path)]
            self._loaded_at = time.time()
            self._rebuild()
            self._watched_files[str(path)] = path.stat().st_mtime
        logger.info("Loaded config from %s (format: %s)", path, fmt.name)
        self._notify("load", str(path), None)
        return self

    def load_text(self, text: str, fmt: Union[str, ConfigFormat] = ConfigFormat.JSON) -> "ConfigLoader":
        if isinstance(fmt, str):
            fmt = ConfigFormat[fmt.upper()]
        parsed = self._parse_text(text, fmt)
        with self._lock:
            self._file_data = parsed
            self._loaded_files = ["<text>"]
            self._loaded_at = time.time()
            self._rebuild()
        self._notify("load", "<text>", None)
        return self

    def load_multiple(self, paths: List[Union[str, Path]]) -> "ConfigLoader":
        combined: Dict[str, Any] = {}
        loaded = []
        for path in paths:
            path = Path(path)
            if not path.exists():
                logger.warning("Config file not found: %s, skipping", path)
                continue
            fmt = self._detect_format(path)
            raw = path.read_text(encoding="utf-8")
            parsed = self._parse_text(raw, fmt)
            combined = self._deep_merge(combined, parsed)
            loaded.append(str(path))
        with self._lock:
            self._file_data = combined
            self._loaded_files = loaded
            self._loaded_at = time.time()
            self._rebuild()
        logger.info("Loaded %d config files", len(loaded))
        return self

    def load_env(self, prefix: Optional[str] = None) -> "ConfigLoader":
        prefix = prefix or self.config.env_prefix
        env_config: Dict[str, Any] = {}
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                config_key = env_key[len(prefix):].lower().replace(self.config.env_separator, ".")
                env_config = self._set_nested(env_config, config_key, self._coerce_env_value(env_value))
        with self._lock:
            self._data = self._deep_merge(self._data, env_config)
            self._rebuild_flat()
        logger.debug("Loaded %d environment variables with prefix '%s'", len(env_config), prefix)
        return self

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            try:
                return self._get_nested(self._data, key)
            except KeyError:
                return default

    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        value = self.get(key, default)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value = self.get(key, default)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: Optional[bool] = None) -> Optional[bool]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on", "y")
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def get_list(self, key: str, default: Optional[List] = None) -> Optional[List]:
        value = self.get(key, default)
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [v.strip() for v in value.split(",")]
        return default

    def get_dict(self, key: str, default: Optional[Dict] = None) -> Optional[Dict]:
        value = self.get(key, default)
        if isinstance(value, dict):
            return value
        return default

    def get_path(self, key: str, default: Optional[str] = None) -> Optional[Path]:
        value = self.get(key, default)
        if value is None:
            return None
        return Path(value)

    def get_duration_seconds(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value = self.get(key, default)
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.match(r"^(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hours?|d|days?|w|weeks?)$", str(value))
        if match:
            num = float(match.group(1))
            unit = match.group(2).lower()[0]
            multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
            return num * multipliers.get(unit, 1)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value: Any, source: str = "explicit") -> "ConfigLoader":
        with self._lock:
            old_value = self._get_nested(self._data, key, _missing=True)
            self._data = self._set_nested(self._data, key, value)
            self._rebuild_flat()
            if self.config.audit_enabled:
                self._audit("set", key, old_value if old_value is not _MISSING else None, value, source)
        self._notify("set", key, value)
        return self

    def update(self, mapping: Dict[str, Any], source: str = "explicit") -> "ConfigLoader":
        with self._lock:
            for key, value in mapping.items():
                self._data = self._set_nested(self._data, key, value)
            self._rebuild_flat()
        return self

    def set_defaults(self, defaults: Dict[str, Any]) -> "ConfigLoader":
        with self._lock:
            self._defaults = defaults
            self._rebuild()
        return self

    def reload(self) -> "ConfigLoader":
        if not self._loaded_files:
            logger.warning("No files loaded, nothing to reload")
            return self
        for file_path in list(self._loaded_files):
            path = Path(file_path)
            if path.exists():
                try:
                    fmt = self._detect_format(path)
                    raw = path.read_text(encoding="utf-8")
                    parsed = self._parse_text(raw, fmt)
                    with self._lock:
                        self._file_data = self._deep_merge(self._file_data, parsed)
                        self._rebuild()
                        self._watched_files[file_path] = path.stat().st_mtime
                    logger.info("Hot-reloaded config from %s", file_path)
                    self._notify("reload", file_path, None)
                except Exception as e:
                    logger.error("Failed to reload %s: %s", file_path, e)
            else:
                logger.warning("Config file %s no longer exists", file_path)
        return self

    def validate(self, schema: Dict[str, Any]) -> bool:
        errors = self._validate_against_schema(self._data, schema, "$")
        if errors:
            if self.config.schema_strict:
                raise SchemaValidationError("\n".join(errors))
            for err in errors:
                logger.warning("Schema validation: %s", err)
            return False
        return True

    def _validate_against_schema(self, data: Any, schema: Any, path: str) -> List[str]:
        errors = []
        if schema is None:
            return errors
        if isinstance(schema, dict):
            if "type" in schema:
                type_map = {
                    "string": str, "number": (int, float), "integer": int,
                    "boolean": bool, "array": list, "object": dict, "null": type(None)
                }
                expected = type_map.get(schema["type"])
                if expected is not None and not isinstance(data, expected):
                    errors.append(f"{path}: expected {schema['type']}, got {type(data).__name__}")
                    return errors
            if "enum" in schema:
                if data not in schema["enum"]:
                    errors.append(f"{path}: value not in enum {schema['enum']}")
            if "properties" in schema and isinstance(data, dict):
                for prop_name, prop_schema in schema["properties"].items():
                    if prop_name in data:
                        errors.extend(self._validate_against_schema(data[prop_name], prop_schema, f"{path}.{prop_name}"))
                    elif prop_schema.get("required") or prop_schema.get("required", False):
                        errors.append(f"{path}: missing required property '{prop_name}'")
            if "items" in schema and isinstance(data, list):
                for i, item in enumerate(data):
                    errors.extend(self._validate_against_schema(item, schema["items"], f"{path}[{i}]"))
            if "required" in schema and isinstance(data, dict):
                for req in schema["required"]:
                    if req not in data:
                        errors.append(f"{path}: missing required field '{req}'")
            if "minLength" in schema and isinstance(data, str) and len(data) < schema["minLength"]:
                errors.append(f"{path}: length {len(data)} < minLength {schema['minLength']}")
            if "maxLength" in schema and isinstance(data, str) and len(data) > schema["maxLength"]:
                errors.append(f"{path}: length {len(data)} > maxLength {schema['maxLength']}")
            if "minimum" in schema and isinstance(data, (int, float)) and data < schema["minimum"]:
                errors.append(f"{path}: {data} < minimum {schema['minimum']}")
            if "maximum" in schema and isinstance(data, (int, float)) and data > schema["maximum"]:
                errors.append(f"{path}: {data} > maximum {schema['maximum']}")
            if "pattern" in schema and isinstance(data, str) and not re.search(schema["pattern"], data):
                errors.append(f"{path}: no match for pattern {schema['pattern']}")
        return errors

    def get_environment(self) -> str:
        return self.config.environment_name

    def set_environment(self, env: str):
        mapped = self.config.environment_mapping.get(env.lower(), env)
        with self._lock:
            self.config.environment_name = mapped

    def is_development(self) -> bool:
        return self.config.environment_name in ("development", "dev")

    def is_production(self) -> bool:
        return self.config.environment_name in ("production", "prod")

    def is_testing(self) -> bool:
        return self.config.environment_name in ("testing", "test")

    def is_staging(self) -> bool:
        return self.config.environment_name in ("staging", "stage")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def to_flat_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._flat)

    def to_json(self, pretty: bool = False) -> str:
        indent = 2 if pretty else None
        return json.dumps(self._data, indent=indent, default=str, ensure_ascii=False)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._flat.keys())

    def items(self) -> List[Tuple[str, Any]]:
        with self._lock:
            return list(self._flat.items())

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any):
        self.set(key, value)

    def __len__(self) -> int:
        return len(self._flat)

    def __repr__(self) -> str:
        return f"ConfigLoader(files={self._loaded_files}, keys={len(self._flat)}, env={self.config.environment_name})"

    def encrypt_secret(self, plaintext: str) -> str:
        if not self._fernet:
            raise SecretEncryptionError("Encryption not initialized")
        encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
        return f"{self.config.secret_prefix}{encrypted.decode('utf-8')}"

    def decrypt_secret(self, encrypted_str: str) -> str:
        if not self._fernet:
            raise SecretEncryptionError("Encryption not initialized")
        if encrypted_str.startswith(self.config.secret_prefix):
            encrypted_str = encrypted_str[len(self.config.secret_prefix):]
        try:
            return self._fernet.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
        except Exception as e:
            raise SecretEncryptionError(f"Decryption failed: {e}") from e

    def resolve_secrets(self, obj: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if obj is None:
            obj = self._data

        def _resolve(item: Any) -> Any:
            if isinstance(item, str) and item.startswith(self.config.secret_prefix):
                try:
                    return self.decrypt_secret(item)
                except SecretEncryptionError:
                    logger.warning("Failed to decrypt secret, keeping encrypted form")
                    return item
            if isinstance(item, dict):
                return {k: _resolve(v) for k, v in item.items()}
            if isinstance(item, list):
                return [_resolve(v) for v in item]
            return item
        return _resolve(obj)

    def subscribe(self, key_pattern: str, callback: Callable):
        self._listeners[key_pattern].append(callback)

    def unsubscribe(self, key_pattern: str, callback: Callable):
        self._listeners[key_pattern] = [cb for cb in self._listeners[key_pattern] if cb != callback]

    def _notify(self, action: str, key: str, value: Any):
        for pattern, callbacks in self._listeners.items():
            if fnmatch.fnmatch(key, pattern):
                for cb in callbacks:
                    try:
                        cb(action, key, value)
                    except Exception as e:
                        logger.error("Listener error for '%s' '%s': %s", pattern, key, e)

    def _audit(self, action: str, path: str, old_value: Any, new_value: Any, source: str):
        entry = ConfigChange(
            timestamp=time.time(),
            action=action,
            path=path,
            old_value=old_value,
            new_value=new_value,
            source=source,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._audit_max:
            self._audit_log = self._audit_log[-self._audit_max:]

    def get_audit_log(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        log = [e.to_dict() for e in self._audit_log]
        if limit:
            log = log[-limit:]
        return log

    def clear_audit_log(self):
        self._audit_log.clear()

    def _rebuild(self):
        self._data = {}
        self._data = self._deep_merge(self._data, self._defaults)
        self._data = self._deep_merge(self._data, self._file_data)
        if self.config.allow_env_override:
            env_data = self._load_env_to_dict()
            self._data = self._deep_merge(self._data, env_data)
        self._rebuild_flat()

    def _rebuild_flat(self):
        self._flat = OrderedDict()
        self._flatten_dict(self._data, "", self._flat)

    def _flatten_dict(self, d: Dict[str, Any], prefix: str, result: OrderedDict):
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and value:
                self._flatten_dict(value, full_key, result)
            else:
                result[full_key] = value

    def _load_env_to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        prefix = self.config.env_prefix
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                config_key = env_key[len(prefix):].lower().replace(self.config.env_separator, ".")
                result = self._set_nested(result, config_key, self._coerce_env_value(env_value))
        return result

    def _parse_text(self, text: str, fmt: ConfigFormat) -> Dict[str, Any]:
        if fmt == ConfigFormat.JSON:
            return json.loads(text)
        if fmt == ConfigFormat.YAML:
            if not HAS_YAML:
                raise ConfigError("PyYAML not available for YAML parsing")
            return yaml.safe_load(text) or {}
        if fmt == ConfigFormat.TOML:
            if not HAS_TOML:
                raise ConfigError("TOML parser not available")
            return toml.loads(text)
        if fmt == ConfigFormat.ENV:
            return self._parse_env_text(text)
        raise ConfigError(f"Unsupported config format: {fmt}")

    def _parse_env_text(self, text: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip().strip("'\"")
            result = self._set_nested(result, key.replace("_", "."), self._coerce_env_value(value))
        return result

    def _coerce_env_value(self, value: str) -> Any:
        if value.lower() in ("true", "yes", "on", "1"):
            return True
        if value.lower() in ("false", "no", "off", "0"):
            return False
        if value.lower() == "null":
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _detect_format(self, path: Path) -> ConfigFormat:
        suffix = path.suffix.lower()
        name = path.name.lower()
        if suffix == ".json":
            return ConfigFormat.JSON
        if suffix in (".yaml", ".yml"):
            return ConfigFormat.YAML
        if suffix == ".toml":
            return ConfigFormat.TOML
        if name == ".env":
            return ConfigFormat.ENV
        content = path.read_text(encoding="utf-8").strip()
        if content.startswith("{") or content.startswith("["):
            try:
                json.loads(content)
                return ConfigFormat.JSON
            except json.JSONDecodeError:
                pass
        if content.startswith("---") or content.startswith("%YAML"):
            return ConfigFormat.YAML
        return ConfigFormat.UNKNOWN

    def _find_default_config(self) -> Optional[Path]:
        for search_dir in self.config.config_search_paths:
            for fname in self.config.config_file_names:
                path = Path(os.path.expanduser(search_dir)) / fname
                if path.exists():
                    return path
        return None

    def _get_nested(self, d: Dict, key: str, _missing: Any = _MISSING) -> Any:
        parts = key.split(".")
        current = d
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                if _missing is not _MISSING:
                    return _missing
                raise KeyError(f"Key '{key}' not found")
        return current

    def _set_nested(self, d: Dict, key: str, value: Any) -> Dict:
        parts = key.split(".")
        current = d
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return d

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

    def _start_auto_reload(self):
        self._shutdown_event.clear()
        self._reload_thread = threading.Thread(
            target=self._auto_reload_loop,
            name="config-auto-reload",
            daemon=True
        )
        self._reload_thread.start()

    def _auto_reload_loop(self):
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(self.config.auto_reload_interval)
            if self._shutdown_event.is_set():
                break
            try:
                self._check_reload()
            except Exception as e:
                logger.error("Auto-reload check failed: %s", e)

    def _check_reload(self):
        for file_path, mtime in list(self._watched_files.items()):
            path = Path(file_path)
            if path.exists() and path.stat().st_mtime != mtime:
                logger.info("Detected change in %s, reloading...", file_path)
                self.reload()
                break

    def set_config(self, config: ConfigLoaderConfig):
        self.config = config
        if config.auto_reload and not self._reload_thread:
            self._start_auto_reload()

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning("Unknown config key: %s", key)

    def close(self):
        self._shutdown_event.set()
        if self._reload_thread and self._reload_thread.is_alive():
            self._reload_thread.join(timeout=5)
        logger.debug("Config loader shut down")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


_MISSING = object()
