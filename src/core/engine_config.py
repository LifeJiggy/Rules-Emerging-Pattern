"""
Configuration management for all rule engines with full lifecycle support.
"""

import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class ConfigEnvironment(str, Enum):
    """Deployment environments for configuration."""
    DEVELOPMENT = "dev"
    STAGING = "staging"
    PRODUCTION = "prod"
    TESTING = "test"


class ConfigSource(str, Enum):
    """Sources of configuration values in override hierarchy."""
    DEFAULT = "default"
    FILE = "file"
    ENVIRONMENT = "environment"
    EXPLICIT = "explicit"


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class ConfigLoadError(Exception):
    """Raised when configuration loading fails."""
    pass


class ConfigLockedError(Exception):
    """Raised when attempting to modify a locked configuration."""
    pass


@dataclass
class ConfigAuditEntry:
    """Audit log entry for configuration changes."""

    timestamp: float
    action: str
    key: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    source: str = ""
    user: str = "system"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "action": self.action,
            "key": self.key,
            "old_value": self._serialize_value(self.old_value),
            "new_value": self._serialize_value(self.new_value),
            "source": self.source,
            "user": self.user,
            "reason": self.reason,
        }

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, set):
            return list(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value


class ConfigSchema:
    """Schema definition for configuration validation with field constraints."""

    def __init__(self):
        self.fields: Dict[str, Dict[str, Any]] = {}
        self.validators: List[Callable] = []
        self._field_groups: Dict[str, List[str]] = {}

    def add_field(
        self,
        name: str,
        field_type: type,
        required: bool = False,
        default: Any = None,
        description: str = "",
        constraints: Optional[Dict[str, Any]] = None,
        group: Optional[str] = None,
    ) -> "ConfigSchema":
        self.fields[name] = {
            "type": field_type,
            "required": required,
            "default": default,
            "description": description,
            "constraints": constraints or {},
        }
        if group:
            if group not in self._field_groups:
                self._field_groups[group] = []
            self._field_groups[group].append(name)
        return self

    def add_validator(self, validator: Callable[["ConfigSchema", Dict[str, Any]], List[str]]) -> "ConfigSchema":
        self.validators.append(validator)
        return self

    def validate(self, config: Dict[str, Any]) -> List[str]:
        errors = []
        for name, field_def in self.fields.items():
            value = config.get(name)
            if field_def["required"] and value is None:
                errors.append(f"Required field '{name}' is missing")
                continue
            if value is None:
                continue
            expected_type = field_def["type"]
            if not isinstance(value, expected_type):
                if expected_type is float and isinstance(value, int):
                    pass
                elif expected_type is bool:
                    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
                        pass
                    else:
                        errors.append(f"Field '{name}' expected type {expected_type.__name__}, got {type(value).__name__}")
                else:
                    errors.append(f"Field '{name}' expected type {expected_type.__name__}, got {type(value).__name__}")
                continue
            constraints = field_def["constraints"]
            if constraints:
                if "min" in constraints and isinstance(value, (int, float)):
                    if value < constraints["min"]:
                        errors.append(f"Field '{name}' value {value} is below minimum {constraints['min']}")
                if "max" in constraints and isinstance(value, (int, float)):
                    if value > constraints["max"]:
                        errors.append(f"Field '{name}' value {value} exceeds maximum {constraints['max']}")
                if "min_length" in constraints and isinstance(value, (str, list)):
                    if len(value) < constraints["min_length"]:
                        errors.append(f"Field '{name}' length {len(value)} is below minimum {constraints['min_length']}")
                if "max_length" in constraints and isinstance(value, (str, list)):
                    if len(value) > constraints["max_length"]:
                        errors.append(f"Field '{name}' length {len(value)} exceeds maximum {constraints['max_length']}")
                if "pattern" in constraints and isinstance(value, str):
                    if not re.match(constraints["pattern"], value):
                        errors.append(f"Field '{name}' does not match pattern {constraints['pattern']}")
                if "enum" in constraints:
                    if isinstance(value, str) and value not in constraints["enum"]:
                        errors.append(f"Field '{name}' value '{value}' not in allowed values: {constraints['enum']}")
                if "allowed_values" in constraints:
                    if value not in constraints["allowed_values"]:
                        errors.append(f"Field '{name}' value '{value}' not allowed")
        for validator in self.validators:
            try:
                validation_errors = validator(self, config)
                errors.extend(validation_errors)
            except Exception as e:
                errors.append(f"Validator error: {e}")
        return errors

    def get_defaults(self) -> Dict[str, Any]:
        defaults = {}
        for name, field_def in self.fields.items():
            if field_def["default"] is not None:
                defaults[name] = field_def["default"]
        return defaults

    def get_field_description(self, name: str) -> str:
        field = self.fields.get(name)
        if field:
            return field.get("description", "")
        return ""

    def get_fields_by_group(self, group: str) -> List[str]:
        return self._field_groups.get(group, [])

    def get_all_field_names(self) -> List[str]:
        return list(self.fields.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": {
                name: {
                    "type": field_def["type"].__name__,
                    "required": field_def["required"],
                    "default": field_def["default"],
                    "description": field_def["description"],
                    "constraints": field_def["constraints"],
                }
                for name, field_def in self.fields.items()
            },
            "groups": self._field_groups,
        }


def create_default_schema() -> ConfigSchema:
    """Create the default configuration schema for the rule engine system."""
    schema = ConfigSchema()

    schema.add_field("engine.max_workers", int, False, 10, "Maximum thread pool workers", {"min": 1, "max": 100}, "engine")
    schema.add_field("engine.cache_size", int, False, 1000, "Maximum cache entries", {"min": 10, "max": 100000}, "engine")
    schema.add_field("engine.cache_ttl", int, False, 300, "Cache TTL in seconds", {"min": 1, "max": 86400}, "engine")
    schema.add_field("engine.batch_concurrency", int, False, 10, "Concurrent batch evaluations", {"min": 1, "max": 100}, "engine")
    schema.add_field("engine.evaluation_timeout_ms", int, False, 5000, "Evaluation timeout in ms", {"min": 100, "max": 60000}, "engine")
    schema.add_field("engine.tier_timeout_ms", int, False, 2000, "Per-tier timeout in ms", {"min": 100, "max": 30000}, "engine")
    schema.add_field("engine.early_termination", bool, False, True, "Stop on critical violations", None, "engine")
    schema.add_field("engine.parallel_tier_evaluation", bool, False, False, "Evaluate tiers in parallel", None, "engine")
    schema.add_field("engine.profiling_enabled", bool, False, True, "Enable performance profiling", None, "engine")
    schema.add_field("engine.profiling_max_records", int, False, 10000, "Max profiling records", {"min": 100, "max": 1000000}, "engine")
    schema.add_field("engine.hot_reload_enabled", bool, False, False, "Enable hot-reload of rules", None, "engine")
    schema.add_field("engine.hot_reload_interval", float, False, 5.0, "Hot-reload check interval in s", {"min": 1.0, "max": 300.0}, "engine")
    schema.add_field("engine.webhook_enabled", bool, False, False, "Enable webhook notifications", None, "engine")
    schema.add_field("engine.webhook_timeout", int, False, 10, "Webhook request timeout in s", {"min": 1, "max": 60}, "engine")

    schema.add_field("dispatcher.enabled", bool, False, True, "Enable rule dispatcher", None, "dispatcher")
    schema.add_field("dispatcher.strategy", str, False, "round_robin", "Dispatch strategy", {"enum": ["round_robin", "least_loaded", "random", "priority", "weighted"]}, "dispatcher")
    schema.add_field("dispatcher.queue_size", int, False, 1000, "Max queue size", {"min": 10, "max": 100000}, "dispatcher")
    schema.add_field("dispatcher.queue_timeout_ms", int, False, 5000, "Queue timeout in ms", {"min": 100, "max": 60000}, "dispatcher")
    schema.add_field("dispatcher.circuit_breaker_threshold", int, False, 5, "Circuit breaker failure threshold", {"min": 1, "max": 100}, "dispatcher")
    schema.add_field("dispatcher.circuit_breaker_timeout_ms", int, False, 30000, "Circuit breaker recovery timeout", {"min": 1000, "max": 300000}, "dispatcher")
    schema.add_field("dispatcher.max_retries", int, False, 3, "Max dispatch retries", {"min": 0, "max": 10}, "dispatcher")
    schema.add_field("dispatcher.priority_levels", int, False, 5, "Priority levels", {"min": 1, "max": 10}, "dispatcher")
    schema.add_field("dispatcher.health_check_interval", int, False, 30, "Engine health check interval", {"min": 5, "max": 300}, "dispatcher")
    schema.add_field("dispatcher.stats_window_size", int, False, 100, "Dispatch stats window size", {"min": 10, "max": 10000}, "dispatcher")

    schema.add_field("pipeline.enabled", bool, False, True, "Enable evaluation pipeline", None, "pipeline")
    schema.add_field("pipeline.timeout_per_stage_ms", int, False, 3000, "Per-stage timeout in ms", {"min": 100, "max": 60000}, "pipeline")
    schema.add_field("pipeline.parallel_stages", bool, False, False, "Run stages in parallel when possible", None, "pipeline")
    schema.add_field("pipeline.collect_metrics", bool, False, True, "Collect pipeline metrics", None, "pipeline")
    schema.add_field("pipeline.fail_on_stage_error", bool, False, False, "Fail pipeline on stage error", None, "pipeline")
    schema.add_field("pipeline.max_concurrent_pipelines", int, False, 10, "Max concurrent pipeline executions", {"min": 1, "max": 100}, "pipeline")
    schema.add_field("pipeline.stage_timeout_behavior", str, False, "skip", "Behavior on stage timeout", {"enum": ["skip", "fail", "retry"]}, "pipeline")

    schema.add_field("aggregator.enabled", bool, False, True, "Enable result aggregation", None, "aggregator")
    schema.add_field("aggregator.strategy", str, False, "weighted", "Aggregation strategy", {"enum": ["weighted", "min", "max", "average", "consensus", "sum"]}, "aggregator")
    schema.add_field("aggregator.deduplicate", bool, False, True, "Deduplicate results before aggregation", None, "aggregator")
    schema.add_field("aggregator.cache_results", bool, False, True, "Cache aggregation results", None, "aggregator")
    schema.add_field("aggregator.cache_ttl", int, False, 300, "Aggregation cache TTL in s", {"min": 1, "max": 86400}, "aggregator")
    schema.add_field("aggregator.max_results_per_batch", int, False, 1000, "Max results per aggregation batch", {"min": 1, "max": 100000}, "aggregator")
    schema.add_field("aggregator.confidence_threshold", float, False, 0.5, "Minimum confidence to include", {"min": 0.0, "max": 1.0}, "aggregator")

    schema.add_field("logging.level", str, False, "INFO", "Logging level", {"enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]}, "logging")
    schema.add_field("logging.format", str, False, "json", "Logging format", {"enum": ["json", "text", "structured"]}, "logging")
    schema.add_field("logging.file", str, False, "", "Log file path", None, "logging")
    schema.add_field("logging.max_bytes", int, False, 10485760, "Max log file bytes", {"min": 1024, "max": 1073741824}, "logging")
    schema.add_field("logging.backup_count", int, False, 5, "Log backup count", {"min": 0, "max": 100}, "logging")

    schema.add_field("monitoring.enabled", bool, False, True, "Enable monitoring", None, "monitoring")
    schema.add_field("monitoring.export_interval", int, False, 300, "Stats export interval in s", {"min": 1, "max": 3600}, "monitoring")
    schema.add_field("monitoring.export_path", str, False, "", "Stats export file path", None, "monitoring")
    schema.add_field("monitoring.prometheus_enabled", bool, False, False, "Enable Prometheus export", None, "monitoring")
    schema.add_field("monitoring.prometheus_port", int, False, 8000, "Prometheus HTTP port", {"min": 1024, "max": 65535}, "monitoring")

    schema.add_field("cache.enabled", bool, False, True, "Enable caching globally", None, "cache")
    schema.add_field("cache.backend", str, False, "memory", "Cache backend type", {"enum": ["memory", "redis", "memcached"]}, "cache")
    schema.add_field("cache.redis_url", str, False, "", "Redis connection URL", None, "cache")
    schema.add_field("cache.memcached_servers", str, False, "", "Memcached server list", None, "cache")
    schema.add_field("cache.key_prefix", str, False, "rule_engine:", "Cache key prefix", None, "cache")
    schema.add_field("cache.enable_compression", bool, False, False, "Enable cache value compression", None, "cache")

    schema.add_validator(_validate_engine_tier_config)
    schema.add_validator(_validate_webhook_config)
    schema.add_validator(_validate_dispatcher_config)
    schema.add_validator(_validate_cache_config)

    return schema


def _validate_engine_tier_config(schema: ConfigSchema, config: Dict[str, Any]) -> List[str]:
    errors = []
    early_term = config.get("engine.early_termination", True)
    parallel = config.get("engine.parallel_tier_evaluation", False)
    if early_term and parallel:
        errors.append("early_termination and parallel_tier_evaluation are mutually exclusive")
    return errors


def _validate_webhook_config(schema: ConfigSchema, config: Dict[str, Any]) -> List[str]:
    errors = []
    webhook_enabled = config.get("engine.webhook_enabled", False)
    if webhook_enabled:
        urls = config.get("engine.webhook_urls", [])
        if not urls:
            errors.append("webhook_enabled is True but no webhook_urls configured")
    return errors


def _validate_dispatcher_config(schema: ConfigSchema, config: Dict[str, Any]) -> List[str]:
    errors = []
    dispatcher_enabled = config.get("dispatcher.enabled", True)
    queue_size = config.get("dispatcher.queue_size", 1000)
    priority_levels = config.get("dispatcher.priority_levels", 5)
    if dispatcher_enabled and queue_size < priority_levels:
        errors.append(f"queue_size ({queue_size}) must be >= priority_levels ({priority_levels})")
    return errors


def _validate_cache_config(schema: ConfigSchema, config: Dict[str, Any]) -> List[str]:
    errors = []
    backend = config.get("cache.backend", "memory")
    if backend == "redis":
        redis_url = config.get("cache.redis_url", "")
        if not redis_url:
            errors.append("cache.backend is 'redis' but no cache.redis_url configured")
    elif backend == "memcached":
        servers = config.get("cache.memcached_servers", "")
        if not servers:
            errors.append("cache.backend is 'memcached' but no cache.memcached_servers configured")
    return errors


class ConfigChangeDetector:
    """Detects configuration file changes for hot-reload."""

    def __init__(self, filepath: str, check_interval: float = 5.0):
        self.filepath = filepath
        self.check_interval = check_interval
        self._last_hash: str = ""
        self._last_mtime: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def add_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        self._callbacks = [c for c in self._callbacks if c is not callback]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        path = Path(self.filepath)
        if path.exists():
            self._last_hash = self._hash_file(path)
            self._last_mtime = path.stat().st_mtime
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"ConfigChangeDetector started for {self.filepath}")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("ConfigChangeDetector stopped")

    def check_now(self) -> bool:
        path = Path(self.filepath)
        if not path.exists():
            return False
        current_mtime = path.stat().st_mtime
        if current_mtime > self._last_mtime:
            current_hash = self._hash_file(path)
            with self._lock:
                if current_hash != self._last_hash:
                    self._last_hash = current_hash
                    self._last_mtime = current_mtime
                    for cb in self._callbacks:
                        try:
                            cb()
                        except Exception as e:
                            logger.error(f"Change callback error: {e}")
                    return True
        return False

    def _watch_loop(self) -> None:
        while self._running:
            try:
                self.check_now()
            except Exception as e:
                logger.error(f"Watch loop error: {e}")
            time.sleep(self.check_interval)

    @staticmethod
    def _hash_file(filepath: Path) -> str:
        try:
            return hashlib.sha256(filepath.read_bytes()).hexdigest()[:64]
        except Exception:
            return ""


class ConfigProfile:
    """Named configuration profile with metadata."""

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config: Dict[str, Any] = config or {}
        self.description: str = ""
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.tags: List[str] = []
        self.is_active: bool = False
        self.priority: int = 100

    def set_description(self, desc: str) -> "ConfigProfile":
        self.description = desc
        return self

    def add_tag(self, tag: str) -> "ConfigProfile":
        if tag not in self.tags:
            self.tags.append(tag)
        return self

    def update(self, config: Dict[str, Any]) -> "ConfigProfile":
        self.config.update(config)
        self.updated_at = time.time()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
            "tags": self.tags,
            "is_active": self.is_active,
            "priority": self.priority,
            "config_keys": len(self.config),
        }


class ConfigProfileManager:
    """Manages named configuration profiles."""

    def __init__(self):
        self._profiles: Dict[str, ConfigProfile] = {}
        self._active_profile: Optional[str] = None

    def add_profile(self, profile: ConfigProfile) -> "ConfigProfileManager":
        self._profiles[profile.name] = profile
        return self

    def create_profile(self, name: str, config: Optional[Dict[str, Any]] = None) -> ConfigProfile:
        profile = ConfigProfile(name, config)
        self._profiles[name] = profile
        return profile

    def get_profile(self, name: str) -> Optional[ConfigProfile]:
        return self._profiles.get(name)

    def delete_profile(self, name: str) -> bool:
        if name in self._profiles:
            del self._profiles[name]
            if self._active_profile == name:
                self._active_profile = None
            return True
        return False

    def activate_profile(self, name: str) -> bool:
        if name not in self._profiles:
            return False
        if self._active_profile:
            self._profiles[self._active_profile].is_active = False
        self._profiles[name].is_active = True
        self._active_profile = name
        return True

    def get_active_profile(self) -> Optional[ConfigProfile]:
        if self._active_profile:
            return self._profiles.get(self._active_profile)
        return None

    def get_active_config(self) -> Dict[str, Any]:
        profile = self.get_active_profile()
        if profile:
            return dict(profile.config)
        return {}

    def list_profiles(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._profiles.values()]

    def merge_active_into(self, config: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(config)
        profile_config = self.get_active_config()
        merged.update(profile_config)
        return merged


class EngineConfig:
    """Configuration management for all rule engines with full lifecycle support."""

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None):
        self._schema = create_default_schema()
        self._config: Dict[str, Any] = {}
        self._raw_configs: Dict[ConfigSource, Dict[str, Any]] = {}
        self._overrides: Dict[str, Any] = {}
        self._environment: ConfigEnvironment = ConfigEnvironment.DEVELOPMENT
        self._file_path: Optional[str] = None
        self._audit_log: List[ConfigAuditEntry] = []
        self._change_callbacks: List[Callable] = []
        self._last_load_time: float = 0.0
        self._config_hash: str = ""
        self._lock = False
        self._lock_owner: Optional[str] = None
        self._change_detector: Optional[ConfigChangeDetector] = None
        self._profile_manager = ConfigProfileManager()
        self._metrics: Dict[str, Any] = {
            "load_count": 0,
            "update_count": 0,
            "validation_error_count": 0,
            "hot_reload_count": 0,
            "last_load_time": 0.0,
        }

        self._initialize_defaults()
        if initial_config:
            self.update(initial_config, source=ConfigSource.EXPLICIT)
            self._config_hash = self._compute_config_hash()

        self._detect_environment_from_env()
        logger.info(f"EngineConfig initialized with env={self._environment.value}")

    def _initialize_defaults(self) -> None:
        defaults = self._schema.get_defaults()
        self._config.update(defaults)
        self._raw_configs[ConfigSource.DEFAULT] = dict(defaults)
        self._log_change(ConfigSource.DEFAULT, "initialize", "", None, dict(defaults))

    def _detect_environment_from_env(self) -> None:
        env_var = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "dev")).lower()
        env_map = {
            "dev": ConfigEnvironment.DEVELOPMENT, "development": ConfigEnvironment.DEVELOPMENT,
            "staging": ConfigEnvironment.STAGING, "stage": ConfigEnvironment.STAGING,
            "prod": ConfigEnvironment.PRODUCTION, "production": ConfigEnvironment.PRODUCTION,
            "test": ConfigEnvironment.TESTING, "testing": ConfigEnvironment.TESTING,
        }
        self._environment = env_map.get(env_var, ConfigEnvironment.DEVELOPMENT)

    def load_yaml(self, filepath: str, env: Optional[ConfigEnvironment] = None) -> "EngineConfig":
        path = Path(filepath)
        if not path.exists():
            raise ConfigLoadError(f"Config file not found: {filepath}")
        if not path.suffix in (".yaml", ".yml"):
            raise ConfigLoadError(f"Not a YAML file: {filepath}")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ConfigLoadError(f"Config file must contain a dictionary, got {type(data).__name__}")
            self._file_path = filepath
            self._apply_file_config(data, env)
            self._config_hash = self._compute_config_hash()
            self._last_load_time = time.time()
            self._metrics["load_count"] += 1
            self._metrics["last_load_time"] = time.time()
            logger.info(f"Configuration loaded from {filepath}")
            return self
        except yaml.YAMLError as e:
            raise ConfigLoadError(f"YAML parse error in {filepath}: {e}")
        except Exception as e:
            raise ConfigLoadError(f"Failed to load {filepath}: {e}")

    def load_json(self, filepath: str, env: Optional[ConfigEnvironment] = None) -> "EngineConfig":
        path = Path(filepath)
        if not path.exists():
            raise ConfigLoadError(f"Config file not found: {filepath}")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ConfigLoadError(f"Config file must contain a dictionary, got {type(data).__name__}")
            self._file_path = filepath
            self._apply_file_config(data, env)
            self._config_hash = self._compute_config_hash()
            self._last_load_time = time.time()
            self._metrics["load_count"] += 1
            logger.info(f"Configuration loaded from {filepath}")
            return self
        except json.JSONDecodeError as e:
            raise ConfigLoadError(f"JSON parse error in {filepath}: {e}")
        except Exception as e:
            raise ConfigLoadError(f"Failed to load {filepath}: {e}")

    def load_env(self, prefix: str = "RULE_ENGINE_") -> "EngineConfig":
        env_config: Dict[str, Any] = {}
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace("__", ".")
                if value.lower() in ("true", "1", "yes"):
                    typed_value: Any = True
                elif value.lower() in ("false", "0", "no"):
                    typed_value = False
                else:
                    try:
                        typed_value = int(value) if "." not in value else float(value)
                    except ValueError:
                        typed_value = value
                env_config[config_key] = typed_value
        if env_config:
            self._apply_env_config(env_config)
            self._config_hash = self._compute_config_hash()
            logger.info(f"Loaded {len(env_config)} config values from environment")
        else:
            logger.debug(f"No environment variables found with prefix '{prefix}'")
        return self

    def set_environment(self, env: ConfigEnvironment) -> "EngineConfig":
        if self._lock:
            raise ConfigLockedError("Configuration is locked")
        old_env = self._environment
        self._environment = env
        self._log_change(ConfigSource.EXPLICIT, "set_environment", "environment", old_env.value, env.value)
        logger.info(f"Environment set to {env.value}")
        return self

    def detect_environment(self) -> ConfigEnvironment:
        self._detect_environment_from_env()
        return self._environment

    def _apply_file_config(self, data: Dict[str, Any], env: Optional[ConfigEnvironment] = None) -> None:
        target_env = env or self._environment
        if "all" in data:
            self._merge_config(data["all"], ConfigSource.FILE)
        env_key = target_env.value
        if env_key in data:
            self._merge_config(data[env_key], ConfigSource.FILE)
        env_aliases = {
            ConfigEnvironment.DEVELOPMENT: ["dev", "development"],
            ConfigEnvironment.STAGING: ["staging", "stage"],
            ConfigEnvironment.PRODUCTION: ["prod", "production"],
            ConfigEnvironment.TESTING: ["test", "testing"],
        }
        for alias in env_aliases.get(target_env, []):
            if alias != env_key and alias in data:
                self._merge_config(data[alias], ConfigSource.FILE)

    def _apply_env_config(self, env_config: Dict[str, Any]) -> None:
        self._merge_config(env_config, ConfigSource.ENVIRONMENT)

    def _merge_config(self, new_config: Dict[str, Any], source: ConfigSource) -> None:
        if source not in self._raw_configs:
            self._raw_configs[source] = {}
        self._raw_configs[source].update(new_config)
        for key, value in new_config.items():
            old_value = self._config.get(key)
            self._set_nested(self._config, key, value)
            self._log_change(source, "merge", key, old_value, value)

    def set(self, key: str, value: Any, reason: str = "", user: str = "system") -> "EngineConfig":
        if self._lock:
            raise ConfigLockedError(f"Configuration is locked by {self._lock_owner}")
        old_value = self._config.get(key)
        self._overrides[key] = value
        self._set_nested(self._config, key, value)
        self._log_change(ConfigSource.EXPLICIT, "set", key, old_value, value, user=user, reason=reason)
        self._config_hash = self._compute_config_hash()
        self._metrics["update_count"] += 1
        for callback in self._change_callbacks:
            try:
                callback(key, old_value, value)
            except Exception as e:
                logger.error(f"Change callback failed for key '{key}': {e}")
        return self

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key, default)
        if isinstance(value, bool):
            return int(value)
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.get(key, default)
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on", "enabled")
        return bool(value) if value is not None else default

    def get_list(self, key: str, default: Optional[List[Any]] = None) -> List[Any]:
        value = self.get(key, default)
        return list(value) if isinstance(value, (list, tuple)) else (default or [])

    def get_dict(self, key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        value = self.get(key, default)
        return dict(value) if isinstance(value, dict) else (default or {})

    def get_section(self, section: str) -> Dict[str, Any]:
        prefix = f"{section}."
        return {k[len(prefix):]: v for k, v in self._config.items() if k.startswith(prefix)}

    def get_nested(self, key: str, default: Any = None) -> Any:
        return self.get(key, default)

    def update(self, config: Dict[str, Any], source: ConfigSource = ConfigSource.EXPLICIT) -> "EngineConfig":
        if self._lock:
            raise ConfigLockedError("Configuration is locked")
        flat_config = self._flatten_dict(config)
        self._merge_config(flat_config, source)
        self._config_hash = self._compute_config_hash()
        self._metrics["update_count"] += len(flat_config)
        for callback in self._change_callbacks:
            for key, value in flat_config.items():
                try:
                    callback(key, None, value)
                except Exception as e:
                    logger.error(f"Change callback failed for key '{key}': {e}")
        return self

    def validate(self) -> List[str]:
        errors = self._schema.validate(self._config)
        if errors:
            self._metrics["validation_error_count"] += len(errors)
            logger.warning(f"Configuration validation found {len(errors)} issues")
        else:
            logger.info("Configuration validation passed")
        return errors

    def validate_strict(self) -> None:
        errors = self.validate()
        if errors:
            raise ConfigValidationError("\n".join(errors))

    def lock(self, owner: str = "system") -> "EngineConfig":
        self._lock = True
        self._lock_owner = owner
        logger.info(f"Configuration locked by {owner}")
        return self

    def unlock(self, owner: str = "system") -> "EngineConfig":
        if self._lock_owner and self._lock_owner != owner:
            logger.warning(f"Attempt to unlock by {owner}, but locked by {self._lock_owner}")
            return self
        self._lock = False
        self._lock_owner = None
        logger.info(f"Configuration unlocked by {owner}")
        return self

    def is_locked(self) -> bool:
        return self._lock

    def add_change_callback(self, callback: Callable[[str, Any, Any], None]) -> "EngineConfig":
        self._change_callbacks.append(callback)
        return self

    def remove_change_callback(self, callback: Callable) -> "EngineConfig":
        self._change_callbacks = [c for c in self._change_callbacks if c is not callback]
        return self

    def enable_hot_reload(self, interval: float = 5.0) -> "EngineConfig":
        if not self._file_path:
            logger.warning("No config file path set for hot-reload")
            return self
        if self._change_detector:
            self._change_detector.stop()
        self._change_detector = ConfigChangeDetector(self._file_path, interval)
        self._change_detector.add_callback(self._on_change_detected)
        self._change_detector.start()
        logger.info(f"Hot-reload enabled for {self._file_path} (interval={interval}s)")
        return self

    def disable_hot_reload(self) -> "EngineConfig":
        if self._change_detector:
            self._change_detector.stop()
            self._change_detector = None
        return self

    def _on_change_detected(self) -> None:
        try:
            old_hash = self._config_hash
            self.hot_reload()
            if old_hash != self._config_hash:
                logger.info("Configuration changed via hot-reload")
        except Exception as e:
            logger.error(f"Hot-reload change handler failed: {e}")

    def hot_reload(self, filepath: Optional[str] = None) -> bool:
        path = filepath or self._file_path
        if not path:
            logger.warning("No config file path set for hot-reload")
            return False
        try:
            path_obj = Path(path)
            if path_obj.suffix in (".yaml", ".yml"):
                old_hash = self._config_hash
                self.load_yaml(path)
                self._metrics["hot_reload_count"] += 1
                if old_hash != self._config_hash:
                    logger.info(f"Configuration reloaded from {path}")
                return True
            elif path_obj.suffix == ".json":
                self.load_json(path)
                self._metrics["hot_reload_count"] += 1
                return True
            else:
                logger.error(f"Unsupported config file format: {path}")
                return False
        except Exception as e:
            logger.error(f"Hot-reload failed: {e}")
            return False

    def check_for_changes(self) -> bool:
        if not self._file_path:
            return False
        path = Path(self._file_path)
        if not path.exists():
            return False
        new_hash = self._hash_file(path)
        changed = new_hash != self._config_hash
        if changed:
            logger.info("Configuration file change detected")
        return changed

    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            return json.dumps(self._config, indent=2, default=str)
        elif fmt == "yaml":
            yaml_config = self._to_nested_dict(self._config)
            return yaml.dump(yaml_config, default_flow_style=False, sort_keys=False)
        elif fmt == "env":
            lines = []
            for key, value in self._config.items():
                env_key = f"RULE_ENGINE_{key.upper().replace('.', '__')}"
                lines.append(f"{env_key}={value}")
            return "\n".join(lines)
        elif fmt == "flat":
            return "\n".join(f"{k}={v}" for k, v in self._config.items())
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

    def export_to_file(self, filepath: str, fmt: Optional[str] = None) -> None:
        fmt = fmt or Path(filepath).suffix.lstrip(".")
        content = self.export(fmt=fmt)
        with open(filepath, "w") as f:
            f.write(content)
        logger.info(f"Configuration exported to {filepath}")

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._config)

    def restore_snapshot(self, snapshot: Dict[str, Any]) -> "EngineConfig":
        if self._lock:
            raise ConfigLockedError("Configuration is locked")
        self._config = dict(snapshot)
        self._config_hash = self._compute_config_hash()
        self._log_change(ConfigSource.EXPLICIT, "restore", "config", "snapshot", "restored")
        logger.info("Configuration restored from snapshot")
        return self

    def diff(self, other_config: "EngineConfig") -> Dict[str, Tuple[Any, Any]]:
        diffs: Dict[str, Tuple[Any, Any]] = {}
        all_keys = set(self._config.keys()) | set(other_config._config.keys())
        for key in all_keys:
            v1 = self._config.get(key)
            v2 = other_config._config.get(key)
            if v1 != v2:
                diffs[key] = (v1, v2)
        return diffs

    def diff_dict(self, other: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
        diffs: Dict[str, Tuple[Any, Any]] = {}
        all_keys = set(self._config.keys()) | set(other.keys())
        for key in all_keys:
            v1 = self._config.get(key)
            v2 = other.get(key)
            if v1 != v2:
                diffs[key] = (v1, v2)
        return diffs

    def get_audit_log(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        entries = self._audit_log[-(limit + offset):]
        if offset:
            entries = entries[:-offset] if len(entries) > offset else []
        else:
            entries = entries[-limit:] if limit else entries
        return [entry.to_dict() for entry in entries]

    def get_audit_summary(self) -> Dict[str, Any]:
        total = len(self._audit_log)
        actions: Dict[str, int] = {}
        sources: Dict[str, int] = {}
        for entry in self._audit_log:
            actions[entry.action] = actions.get(entry.action, 0) + 1
            sources[entry.source] = sources.get(entry.source, 0) + 1
        return {
            "total_entries": total,
            "actions": actions,
            "sources": sources,
            "first_entry": self._audit_log[0].to_dict() if self._audit_log else None,
            "last_entry": self._audit_log[-1].to_dict() if self._audit_log else None,
        }

    def search_audit(self, query: str) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for entry in self._audit_log:
            if (query_lower in entry.key.lower() or
                query_lower in entry.action.lower() or
                query_lower in entry.source.lower()):
                results.append(entry.to_dict())
        return results

    def _log_change(
        self,
        source: ConfigSource,
        action: str,
        key: str,
        old_value: Any,
        new_value: Any,
        user: str = "system",
        reason: str = "",
    ) -> None:
        source_name = source.value if hasattr(source, "value") else str(source)
        entry = ConfigAuditEntry(
            timestamp=time.time(),
            action=action,
            key=key,
            old_value=old_value,
            new_value=new_value,
            source=source_name,
            user=user,
            reason=reason,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    def _compute_config_hash(self) -> str:
        config_str = json.dumps(self._config, sort_keys=True, default=str)
        return hashlib.sha256(config_str.encode()).hexdigest()[:32]

    @staticmethod
    def _hash_file(filepath: Path) -> str:
        try:
            return hashlib.sha256(filepath.read_bytes()).hexdigest()[:32]
        except Exception:
            return ""

    @staticmethod
    def _set_nested(config: Dict[str, Any], key: str, value: Any) -> None:
        keys = key.split(".")
        current = config
        for i, k in enumerate(keys[:-1]):
            if k not in current:
                current[k] = {}
            elif not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    @staticmethod
    def _flatten_dict(d: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
        items: Dict[str, Any] = {}
        for key, value in d.items():
            new_key = f"{parent_key}.{key}" if parent_key else key
            if isinstance(value, dict):
                items.update(EngineConfig._flatten_dict(value, new_key))
            else:
                items[new_key] = value
        return items

    @staticmethod
    def _to_nested_dict(flat_dict: Dict[str, Any]) -> Dict[str, Any]:
        nested: Dict[str, Any] = {}
        for key, value in flat_dict.items():
            parts = key.split(".")
            current = nested
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        return nested

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._config)

    def to_json(self) -> str:
        return json.dumps(self._config, indent=2, default=str)

    def to_yaml(self) -> str:
        return yaml.dump(self._to_nested_dict(self._config), default_flow_style=False, sort_keys=False)

    def get_metrics(self) -> Dict[str, Any]:
        return dict(self._metrics)

    def get_environment(self) -> ConfigEnvironment:
        return self._environment

    def reset_to_defaults(self) -> "EngineConfig":
        if self._lock:
            raise ConfigLockedError("Configuration is locked")
        self._initialize_defaults()
        self._config_hash = self._compute_config_hash()
        self._log_change(ConfigSource.EXPLICIT, "reset", "config", "full", "defaults")
        logger.info("Configuration reset to defaults")
        return self

    def to_prometheus(self) -> str:
        metrics = self._metrics
        lines = [
            "# HELP rule_engine_config_load_count Number of config loads",
            "# TYPE rule_engine_config_load_count counter",
            f"rule_engine_config_load_count {metrics.get('load_count', 0)}",
            "# HELP rule_engine_config_update_count Number of config updates",
            "# TYPE rule_engine_config_update_count counter",
            f"rule_engine_config_update_count {metrics.get('update_count', 0)}",
            "# HELP rule_engine_config_validation_error_count Number of validation errors",
            "# TYPE rule_engine_config_validation_error_count counter",
            f"rule_engine_config_validation_error_count {metrics.get('validation_error_count', 0)}",
            "# HELP rule_engine_config_hot_reload_count Number of hot reloads",
            "# TYPE rule_engine_config_hot_reload_count counter",
            f"rule_engine_config_hot_reload_count {metrics.get('hot_reload_count', 0)}",
        ]
        return "\n".join(lines)

    def get_profile_manager(self) -> ConfigProfileManager:
        return self._profile_manager

    def __repr__(self) -> str:
        return f"EngineConfig(env={self._environment.value}, keys={len(self._config)})"

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(f"Configuration key '{key}' not found")
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __len__(self) -> int:
        return len(self._config)

    def __iter__(self):
        return iter(self._config)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EngineConfig):
            return NotImplemented
        return self._config == other._config

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, EngineConfig):
            return NotImplemented
        return self._config != other._config


class ConfigBuilder:
    """Builder for constructing EngineConfig with fluent interface."""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._file_path: Optional[str] = None
        self._env_prefix: str = "RULE_ENGINE_"
        self._environment: Optional[ConfigEnvironment] = None
        self._validate: bool = True
        self._lock: bool = False
        self._profiles: List[ConfigProfile] = []

    def with_defaults(self) -> "ConfigBuilder":
        schema = create_default_schema()
        self._config.update(schema.get_defaults())
        return self

    def with_yaml(self, filepath: str, env: Optional[ConfigEnvironment] = None) -> "ConfigBuilder":
        self._file_path = filepath
        if env:
            self._environment = env
        return self

    def with_json(self, filepath: str, env: Optional[ConfigEnvironment] = None) -> "ConfigBuilder":
        self._file_path = filepath
        if env:
            self._environment = env
        return self

    def with_env(self, prefix: str = "RULE_ENGINE_") -> "ConfigBuilder":
        self._env_prefix = prefix
        return self

    def with_environment(self, env: ConfigEnvironment) -> "ConfigBuilder":
        self._environment = env
        return self

    def with_value(self, key: str, value: Any) -> "ConfigBuilder":
        self._config[key] = value
        return self

    def with_values(self, config: Dict[str, Any]) -> "ConfigBuilder":
        self._config.update(config)
        return self

    def with_profile(self, profile: ConfigProfile) -> "ConfigBuilder":
        self._profiles.append(profile)
        return self

    def skip_validation(self) -> "ConfigBuilder":
        self._validate = False
        return self

    def lock_config(self) -> "ConfigBuilder":
        self._lock = True
        return self

    def build(self) -> EngineConfig:
        engine_config = EngineConfig(self._config)
        if self._environment:
            engine_config.set_environment(self._environment)
        else:
            engine_config.detect_environment()
        if self._file_path:
            path = Path(self._file_path)
            if path.suffix in (".yaml", ".yml"):
                engine_config.load_yaml(self._file_path, self._environment)
            elif path.suffix == ".json":
                engine_config.load_json(self._file_path, self._environment)
        engine_config.load_env(self._env_prefix)
        for profile in self._profiles:
            engine_config.get_profile_manager().add_profile(profile)
        if self._validate:
            errors = engine_config.validate()
            if errors:
                logger.warning(f"ConfigBuilder: {len(errors)} validation issues found")
        if self._lock:
            engine_config.lock()
        return engine_config


class ConfigTemplate:
    """Configuration templates for common deployment patterns."""

    @staticmethod
    def development() -> Dict[str, Any]:
        return {
            "engine.max_workers": 4,
            "engine.cache_size": 500,
            "engine.cache_ttl": 60,
            "engine.batch_concurrency": 5,
            "engine.profiling_enabled": True,
            "engine.profiling_max_records": 5000,
            "engine.hot_reload_enabled": True,
            "engine.hot_reload_interval": 2.0,
            "engine.webhook_enabled": False,
            "dispatcher.queue_size": 100,
            "dispatcher.circuit_breaker_threshold": 10,
            "pipeline.collect_metrics": True,
            "pipeline.fail_on_stage_error": False,
            "aggregator.cache_results": True,
            "logging.level": "DEBUG",
            "monitoring.export_interval": 60,
        }

    @staticmethod
    def staging() -> Dict[str, Any]:
        return {
            "engine.max_workers": 8,
            "engine.cache_size": 2000,
            "engine.cache_ttl": 120,
            "engine.batch_concurrency": 10,
            "engine.profiling_enabled": True,
            "engine.profiling_max_records": 20000,
            "engine.hot_reload_enabled": True,
            "engine.hot_reload_interval": 5.0,
            "engine.webhook_enabled": True,
            "engine.webhook_timeout": 5,
            "dispatcher.queue_size": 500,
            "dispatcher.circuit_breaker_threshold": 5,
            "dispatcher.max_retries": 2,
            "pipeline.collect_metrics": True,
            "pipeline.fail_on_stage_error": True,
            "aggregator.cache_results": True,
            "aggregator.cache_ttl": 120,
            "logging.level": "INFO",
            "monitoring.export_interval": 120,
        }

    @staticmethod
    def production() -> Dict[str, Any]:
        return {
            "engine.max_workers": 20,
            "engine.cache_size": 10000,
            "engine.cache_ttl": 300,
            "engine.batch_concurrency": 25,
            "engine.evaluation_timeout_ms": 3000,
            "engine.tier_timeout_ms": 1500,
            "engine.early_termination": True,
            "engine.profiling_enabled": True,
            "engine.profiling_max_records": 50000,
            "engine.hot_reload_enabled": False,
            "engine.webhook_enabled": True,
            "engine.webhook_timeout": 10,
            "engine.webhook_max_retries": 3,
            "dispatcher.enabled": True,
            "dispatcher.strategy": "least_loaded",
            "dispatcher.queue_size": 5000,
            "dispatcher.queue_timeout_ms": 3000,
            "dispatcher.circuit_breaker_threshold": 3,
            "dispatcher.circuit_breaker_timeout_ms": 60000,
            "dispatcher.max_retries": 3,
            "dispatcher.priority_levels": 5,
            "pipeline.enabled": True,
            "pipeline.timeout_per_stage_ms": 2000,
            "pipeline.parallel_stages": True,
            "pipeline.collect_metrics": True,
            "pipeline.fail_on_stage_error": True,
            "aggregator.enabled": True,
            "aggregator.strategy": "weighted",
            "aggregator.deduplicate": True,
            "aggregator.cache_results": True,
            "aggregator.cache_ttl": 300,
            "logging.level": "WARNING",
            "logging.format": "json",
            "monitoring.enabled": True,
            "monitoring.export_interval": 300,
        }

    @staticmethod
    def testing() -> Dict[str, Any]:
        return {
            "engine.max_workers": 2,
            "engine.cache_size": 100,
            "engine.cache_ttl": 10,
            "engine.batch_concurrency": 2,
            "engine.profiling_enabled": False,
            "engine.hot_reload_enabled": False,
            "engine.webhook_enabled": False,
            "dispatcher.enabled": False,
            "dispatcher.queue_size": 50,
            "dispatcher.circuit_breaker_threshold": 20,
            "pipeline.collect_metrics": False,
            "pipeline.fail_on_stage_error": False,
            "aggregator.cache_results": False,
            "logging.level": "DEBUG",
            "monitoring.enabled": False,
        }

    @staticmethod
    def performance() -> Dict[str, Any]:
        return {
            "engine.max_workers": 50,
            "engine.cache_size": 50000,
            "engine.cache_ttl": 600,
            "engine.batch_concurrency": 50,
            "engine.profiling_enabled": False,
            "engine.hot_reload_enabled": False,
            "engine.webhook_enabled": False,
            "dispatcher.queue_size": 10000,
            "pipeline.parallel_stages": True,
            "pipeline.collect_metrics": False,
            "aggregator.cache_results": True,
            "aggregator.cache_ttl": 600,
            "logging.level": "ERROR",
            "monitoring.enabled": False,
        }


def load_config(
    filepath: Optional[str] = None,
    env_prefix: str = "RULE_ENGINE_",
    environment: Optional[ConfigEnvironment] = None,
    validate: bool = True,
    lock: bool = False,
) -> EngineConfig:
    """Convenience function to load and build a complete configuration."""
    builder = ConfigBuilder()
    builder.with_defaults()
    if filepath:
        path = Path(filepath)
        if path.suffix in (".yaml", ".yml"):
            builder.with_yaml(filepath, environment)
        elif path.suffix == ".json":
            builder.with_json(filepath, environment)
    builder.with_env(env_prefix)
    if environment:
        builder.with_environment(environment)
    if not validate:
        builder.skip_validation()
    if lock:
        builder.lock_config()
    return builder.build()
