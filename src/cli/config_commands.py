"""Configuration management CLI commands."""
import json
import logging
import os
import sys
import time
from copy import deepcopy
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleStatus, RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class ConfigSource(str, Enum):
    """Source of configuration values."""
    DEFAULT = "default"
    FILE = "file"
    ENVIRONMENT = "environment"
    EXPLICIT = "explicit"
    CLI = "cli"


class ConfigType(str, Enum):
    """Configuration value types."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    DICT = "dict"
    PATH = "path"


class ConfigValidationError(Exception):
    """Configuration validation error."""
    pass


@staticmethod
def _validate_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on", "enabled")
    return bool(value)


class ConfigSchema:
    """Schema definition for configuration fields."""

    def __init__(self):
        self.fields: Dict[str, Dict[str, Any]] = {}
        self.groups: Dict[str, List[str]] = {}

    def add_field(
        self,
        key: str,
        field_type: ConfigType,
        default: Any = None,
        description: str = "",
        group: str = "general",
        valid_values: Optional[List[Any]] = None,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        required: bool = False,
        sensitive: bool = False,
    ) -> "ConfigSchema":
        self.fields[key] = {
            "type": field_type,
            "default": default,
            "description": description,
            "group": group,
            "valid_values": valid_values,
            "min_value": min_value,
            "max_value": max_value,
            "required": required,
            "sensitive": sensitive,
        }
        if group not in self.groups:
            self.groups[group] = []
        if key not in self.groups[group]:
            self.groups[group].append(key)
        return self

    def validate(self, key: str, value: Any) -> List[str]:
        errors = []
        field = self.fields.get(key)
        if not field:
            errors.append(f"Unknown configuration key: {key}")
            return errors
        expected_type = field["type"]
        if expected_type == ConfigType.INTEGER:
            try:
                int(value)
            except (ValueError, TypeError):
                errors.append(f"'{key}' must be an integer, got {type(value).__name__}")
        elif expected_type == ConfigType.FLOAT:
            try:
                float(value)
            except (ValueError, TypeError):
                errors.append(f"'{key}' must be a number, got {type(value).__name__}")
        elif expected_type == ConfigType.BOOLEAN:
            if isinstance(value, str):
                if value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                    errors.append(f"'{key}' must be a boolean (true/false), got '{value}'")
            elif not isinstance(value, bool):
                errors.append(f"'{key}' must be a boolean, got {type(value).__name__}")
        elif expected_type == ConfigType.LIST:
            if not isinstance(value, (list, tuple)):
                errors.append(f"'{key}' must be a list, got {type(value).__name__}")
        elif expected_type == ConfigType.DICT:
            if not isinstance(value, dict):
                errors.append(f"'{key}' must be a dictionary, got {type(value).__name__}")
        valid_values = field.get("valid_values")
        if valid_values is not None and value is not None:
            if value not in valid_values:
                errors.append(f"'{key}' must be one of: {', '.join(str(v) for v in valid_values)}")
        min_val = field.get("min_value")
        max_val = field.get("max_value")
        if min_val is not None:
            try:
                if float(value) < min_val:
                    errors.append(f"'{key}' minimum value is {min_val}")
            except (ValueError, TypeError):
                pass
        if max_val is not None:
            try:
                if float(value) > max_val:
                    errors.append(f"'{key}' maximum value is {max_val}")
            except (ValueError, TypeError):
                pass
        return errors

    def get_default(self, key: str) -> Any:
        field = self.fields.get(key)
        if field:
            return field["default"]
        return None

    def get_description(self, key: str) -> str:
        field = self.fields.get(key)
        if field:
            return field["description"]
        return ""

    def get_group(self, key: str) -> str:
        field = self.fields.get(key)
        if field:
            return field.get("group", "general")
        return "general"

    def is_sensitive(self, key: str) -> bool:
        field = self.fields.get(key)
        if field:
            return field.get("sensitive", False)
        return False

    def get_schema_dict(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.fields)


def create_default_schema() -> ConfigSchema:
    """Create the default configuration schema."""
    schema = ConfigSchema()
    schema.add_field("engine.max_workers", ConfigType.INTEGER, 10, "Maximum thread pool workers", "engine", min_value=1, max_value=100)
    schema.add_field("engine.cache_size", ConfigType.INTEGER, 1000, "Maximum cache entries", "engine", min_value=10, max_value=100000)
    schema.add_field("engine.cache_ttl", ConfigType.INTEGER, 300, "Cache TTL in seconds", "engine", min_value=1, max_value=86400)
    schema.add_field("engine.batch_concurrency", ConfigType.INTEGER, 10, "Concurrent batch evaluations", "engine", min_value=1, max_value=100)
    schema.add_field("engine.evaluation_timeout_ms", ConfigType.INTEGER, 5000, "Evaluation timeout in ms", "engine", min_value=100, max_value=60000)
    schema.add_field("engine.profiling_enabled", ConfigType.BOOLEAN, True, "Enable performance profiling", "engine")
    schema.add_field("engine.hot_reload_enabled", ConfigType.BOOLEAN, False, "Enable hot-reload of rules", "engine")
    schema.add_field("engine.hot_reload_interval", ConfigType.FLOAT, 5.0, "Hot-reload check interval in seconds", "engine", min_value=1.0, max_value=300.0)
    schema.add_field("engine.webhook_enabled", ConfigType.BOOLEAN, False, "Enable webhook notifications", "engine")
    schema.add_field("engine.early_termination", ConfigType.BOOLEAN, True, "Stop on critical safety violations", "engine")
    schema.add_field("engine.parallel_tier", ConfigType.BOOLEAN, False, "Evaluate tiers in parallel", "engine")
    schema.add_field("engine.enable_pre_filter", ConfigType.BOOLEAN, True, "Enable rule pre-filtering", "engine")
    schema.add_field("engine.enable_post_process", ConfigType.BOOLEAN, True, "Enable result post-processing", "engine")
    schema.add_field("output.format", ConfigType.STRING, "table", "Default output format", "output", valid_values=["table", "json", "text", "csv", "html"])
    schema.add_field("output.color_enabled", ConfigType.BOOLEAN, True, "Enable colored output", "output")
    schema.add_field("output.verbose", ConfigType.BOOLEAN, False, "Enable verbose output", "output")
    schema.add_field("output.quiet", ConfigType.BOOLEAN, False, "Suppress non-essential output", "output")
    schema.add_field("output.theme", ConfigType.STRING, "default", "Output color theme", "output", valid_values=["default", "dark", "minimal"])
    schema.add_field("logging.level", ConfigType.STRING, "INFO", "Logging level", "logging", valid_values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    schema.add_field("logging.format", ConfigType.STRING, "text", "Logging format", "logging", valid_values=["text", "json", "structured"])
    schema.add_field("logging.file", ConfigType.STRING, "", "Log file path", "logging")
    schema.add_field("logging.max_bytes", ConfigType.INTEGER, 10485760, "Max log file bytes", "logging", min_value=1024, max_value=1073741824)
    schema.add_field("logging.backup_count", ConfigType.INTEGER, 5, "Log backup count", "logging", min_value=0, max_value=100)
    schema.add_field("monitoring.enabled", ConfigType.BOOLEAN, True, "Enable monitoring", "monitoring")
    schema.add_field("monitoring.export_interval", ConfigType.INTEGER, 300, "Stats export interval in seconds", "monitoring", min_value=1, max_value=3600)
    schema.add_field("monitoring.export_path", ConfigType.STRING, "", "Stats export file path", "monitoring")
    schema.add_field("monitoring.prometheus_enabled", ConfigType.BOOLEAN, False, "Enable Prometheus export", "monitoring")
    schema.add_field("monitoring.prometheus_port", ConfigType.INTEGER, 8000, "Prometheus HTTP port", "monitoring", min_value=1024, max_value=65535)
    schema.add_field("cache.enabled", ConfigType.BOOLEAN, True, "Enable caching", "cache")
    schema.add_field("cache.backend", ConfigType.STRING, "memory", "Cache backend type", "cache", valid_values=["memory", "redis", "memcached"])
    schema.add_field("cache.redis_url", ConfigType.STRING, "", "Redis connection URL", "cache", sensitive=True)
    schema.add_field("cache.key_prefix", ConfigType.STRING, "rule_engine:", "Cache key prefix", "cache")
    schema.add_field("dispatcher.strategy", ConfigType.STRING, "round_robin", "Dispatch strategy", "dispatcher", valid_values=["round_robin", "least_loaded", "random", "priority", "weighted"])
    schema.add_field("dispatcher.queue_size", ConfigType.INTEGER, 1000, "Max queue size", "dispatcher", min_value=10, max_value=100000)
    schema.add_field("dispatcher.max_retries", ConfigType.INTEGER, 3, "Max dispatch retries", "dispatcher", min_value=0, max_value=10)
    schema.add_field("pipeline.enabled", ConfigType.BOOLEAN, True, "Enable evaluation pipeline", "pipeline")
    schema.add_field("pipeline.timeout_per_stage_ms", ConfigType.INTEGER, 3000, "Per-stage timeout in ms", "pipeline", min_value=100, max_value=60000)
    return schema


class ConfigCommands:
    """CLI commands for configuration management."""

    def __init__(
        self,
        console: Console,
        config_path: Optional[Path] = None,
        schema: Optional[ConfigSchema] = None,
    ):
        self.console = console
        self.schema = schema or create_default_schema()
        self.config_path = config_path or self._find_config_path()
        self.config: Dict[str, Any] = {}
        self.env_prefix = "RULE_ENGINE_"
        self._loaded_sources: List[ConfigSource] = []
        self._load_all()

    def _find_config_path(self) -> Path:
        candidates = [
            Path("config.json"),
            Path("config.yaml"),
            Path.home() / ".rules-emerging-pattern" / "config.json",
            Path.home() / ".rules-emerging-pattern" / "config.yaml",
            Path.cwd() / ".rules-emerging-pattern.json",
            Path.cwd() / ".rules-emerging-pattern.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return Path.home() / ".rules-emerging-pattern" / "config.json"

    def _load_all(self) -> None:
        self._load_defaults()
        self._load_from_file()
        self._load_from_env()
        self._loaded_sources.append(ConfigSource.EXPLICIT)

    def _load_defaults(self) -> None:
        for key, field in self.schema.fields.items():
            if field["default"] is not None:
                self.config[key] = deepcopy(field["default"])

    def _load_from_file(self) -> None:
        if not self.config_path or not self.config_path.exists():
            return
        try:
            content = self.config_path.read_text(encoding="utf-8")
            if self.config_path.suffix in (".yaml", ".yml"):
                import yaml
                data = yaml.safe_load(content) or {}
            else:
                data = json.loads(content)
            if isinstance(data, dict):
                for key, value in self._flatten_dict(data).items():
                    if key in self.schema.fields:
                        self.config[key] = value
                self._loaded_sources.append(ConfigSource.FILE)
                logger.info(f"Loaded config from {self.config_path}")
        except Exception as e:
            logger.warning(f"Could not load config from {self.config_path}: {e}")

    def _load_from_env(self) -> None:
        env_vars = {}
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                config_key = key[len(self.env_prefix):].lower().replace("__", ".")
                if config_key in self.schema.fields:
                    typed_value = self._coerce_type(config_key, value)
                    env_vars[config_key] = typed_value
        if env_vars:
            self.config.update(env_vars)
            self._loaded_sources.append(ConfigSource.ENVIRONMENT)
            logger.debug(f"Loaded {len(env_vars)} config values from environment")

    def _coerce_type(self, key: str, value: str) -> Any:
        field = self.schema.fields.get(key)
        if not field:
            return value
        ftype = field["type"]
        if ftype == ConfigType.INTEGER:
            try:
                return int(value)
            except ValueError:
                return value
        elif ftype == ConfigType.FLOAT:
            try:
                return float(value)
            except ValueError:
                return value
        elif ftype == ConfigType.BOOLEAN:
            return value.lower() in ("true", "1", "yes", "on", "enabled")
        elif ftype == ConfigType.LIST:
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
        items = {}
        for key, value in d.items():
            new_key = f"{parent_key}.{key}" if parent_key else key
            if isinstance(value, dict) and not self._is_leaf_dict(new_key, value):
                items.update(self._flatten_dict(value, new_key))
            else:
                items[new_key] = value
        return items

    def _is_leaf_dict(self, key: str, value: Dict[str, Any]) -> bool:
        for field_key in self.schema.fields:
            if field_key.startswith(key + "."):
                return False
        return True

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any, source: ConfigSource = ConfigSource.CLI) -> bool:
        errors = self.schema.validate(key, value)
        if errors:
            raise ConfigValidationError("; ".join(errors))
        self.config[key] = value
        if source == ConfigSource.CLI:
            self._save()
        return True

    def _save(self) -> bool:
        if not self.config_path:
            return False
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            nested = self._to_nested(self.config)
            if self.config_path.suffix in (".yaml", ".yml"):
                import yaml
                self.config_path.write_text(yaml.dump(nested, default_flow_style=False), encoding="utf-8")
            else:
                self.config_path.write_text(json.dumps(nested, indent=2, default=str), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def _to_nested(self, flat: Dict[str, Any]) -> Dict[str, Any]:
        nested = {}
        for key, value in flat.items():
            if key in self.schema.fields:
                parts = key.split(".")
                current = nested
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
        return nested

    def reset(self) -> None:
        self.config.clear()
        self._load_defaults()
        self._save()

    def view_all(self, output_json: bool = False) -> None:
        if output_json:
            self.console.print(json.dumps(self._to_nested(self.config), indent=2))
            return

        groups: Dict[str, List[Tuple[str, Any]]] = {}
        for key, field in self.schema.fields.items():
            group = field.get("group", "general")
            if group not in groups:
                groups[group] = []
            val = self.config.get(key, field["default"])
            groups[group].append((key, val, field))

        group_labels = {
            "engine": "Engine Configuration",
            "output": "Output Configuration",
            "logging": "Logging Configuration",
            "monitoring": "Monitoring Configuration",
            "cache": "Cache Configuration",
            "dispatcher": "Dispatcher Configuration",
            "pipeline": "Pipeline Configuration",
            "general": "General Configuration",
        }

        for group_name in sorted(groups.keys()):
            entries = groups[group_name]
            if not entries:
                continue
            label = group_labels.get(group_name, group_name.title())
            table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
            table.add_column("Key", style="green", no_wrap=True)
            table.add_column("Value", style="yellow")
            table.add_column("Type", style="blue")
            table.add_column("Description", style="grey50")

            for key, val, field in sorted(entries, key=lambda x: x[0]):
                if field.get("sensitive") and val:
                    display_val = "********"
                elif isinstance(val, list):
                    display_val = ", ".join(str(v) for v in val)
                elif isinstance(val, dict):
                    display_val = json.dumps(val)
                else:
                    display_val = str(val)
                table.add_row(
                    key,
                    display_val,
                    field["type"].value,
                    field.get("description", "")[:60],
                )
            self.console.print(Panel(table, title=label, border_style="blue"))
            self.console.print()

    def view_key(self, key: str, output_json: bool = False) -> None:
        field = self.schema.fields.get(key)
        if not field:
            self.console.print(f"[red]Unknown configuration key: {key}[/red]")
            return
        value = self.config.get(key, field["default"])
        if output_json:
            self.console.print(json.dumps({key: value}, indent=2))
            return
        sensitive = field.get("sensitive", False)
        display = "********" if sensitive and value else str(value)
        self.console.print(Panel(
            f"Key: [green]{key}[/green]\n"
            f"Value: [yellow]{display}[/yellow]\n"
            f"Type: [blue]{field['type'].value}[/blue]\n"
            f"Default: {field['default']}\n"
            f"Description: {field.get('description', '')}",
            title="Configuration Value",
            border_style="blue"
        ))

    def set_key(self, key: str, value: str) -> None:
        if key not in self.schema.fields:
            self.console.print(f"[red]Unknown configuration key: {key}[/red]")
            self.console.print(f"[yellow]Use 'config list' to see available keys[/yellow]")
            return
        coerced = self._coerce_type(key, value)
        try:
            self.set(key, coerced)
            self.console.print(f"[green]Set {key} = {value}[/green]")
        except ConfigValidationError as e:
            self.console.print(f"[red]Validation error: {e}[/red]")

    def reset_to_defaults(self) -> None:
        self.reset()
        self.console.print("[green]Configuration reset to defaults[/green]")
        self.console.print(f"[yellow]Saved to {self.config_path}[/yellow]")

    def load_from_file(self, filepath: Path) -> None:
        if not filepath.exists():
            self.console.print(f"[red]File not found: {filepath}[/red]")
            return
        old_path = self.config_path
        self.config_path = filepath
        try:
            self._load_from_file()
            self._save()
            self.console.print(f"[green]Configuration loaded from {filepath}[/green]")
        except Exception as e:
            self.config_path = old_path
            self.console.print(f"[red]Failed to load config: {e}[/red]")

    def list_sections(self, output_json: bool = False) -> None:
        groups: Dict[str, List[str]] = {}
        for key, field in self.schema.fields.items():
            group = field.get("group", "general")
            if group not in groups:
                groups[group] = []
            groups[group].append(key)

        if output_json:
            self.console.print(json.dumps({g: sorted(ks) for g, ks in groups.items()}, indent=2))
            return

        group_labels = {
            "engine": "Engine Configuration",
            "output": "Output Configuration",
            "logging": "Logging Configuration",
            "monitoring": "Monitoring Configuration",
            "cache": "Cache Configuration",
            "dispatcher": "Dispatcher Configuration",
            "pipeline": "Pipeline Configuration",
            "general": "General Configuration",
        }

        for group_name in sorted(groups.keys()):
            keys = groups[group_name]
            label = group_labels.get(group_name, group_name.title())
            self.console.print(f"[bold cyan]{label}[/bold cyan] ({len(keys)} keys)")
            for key in sorted(keys):
                self.console.print(f"  {key}")
            self.console.print()

    def validate_config(self) -> List[str]:
        errors = []
        for key in self.schema.fields:
            value = self.config.get(key)
            field_errors = self.schema.validate(key, value)
            errors.extend(field_errors)
        return errors

    def export_config(self, fmt: str = "json") -> str:
        nested = self._to_nested(self.config)
        if fmt == "json":
            return json.dumps(nested, indent=2)
        elif fmt == "yaml":
            import yaml
            return yaml.dump(nested, default_flow_style=False)
        elif fmt == "env":
            lines = []
            for key, value in self.config.items():
                env_key = f"{self.env_prefix}{key.upper().replace('.', '__')}"
                lines.append(f"{env_key}={value}")
            return "\n".join(lines)
        return json.dumps(nested, indent=2)

    def print_config_file_info(self) -> None:
        if self.config_path and self.config_path.exists():
            self.console.print(Panel(
                f"Path: {self.config_path}\n"
                f"Size: {self.config_path.stat().st_size} bytes\n"
                f"Format: {self.config_path.suffix}\n"
                f"Loaded from: {', '.join(s.value for s in self._loaded_sources)}",
                title="Config File Info",
                border_style="blue"
            ))
        else:
            self.console.print("[yellow]No configuration file loaded[/yellow]")

    def get_diff(self, other: "ConfigCommands") -> Dict[str, Tuple[Any, Any]]:
        diffs = {}
        all_keys = set(self.config.keys()) | set(other.config.keys())
        for key in all_keys:
            v1 = self.config.get(key)
            v2 = other.config.get(key)
            if v1 != v2:
                diffs[key] = (v1, v2)
        return diffs

    def print_diff(self, other: "ConfigCommands") -> None:
        diffs = self.get_diff(other)
        if not diffs:
            self.console.print("[green]Configurations are identical[/green]")
            return
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("Key", style="green")
        table.add_column("Current", style="yellow")
        table.add_column("Other", style="magenta")
        for key, (v1, v2) in sorted(diffs.items()):
            table.add_row(key, str(v1), str(v2))
        self.console.print(Panel(table, title="Configuration Diff", border_style="yellow"))

    def migrate(self, new_path: Path) -> bool:
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            nested = self._to_nested(self.config)
            if new_path.suffix in (".yaml", ".yml"):
                import yaml
                new_path.write_text(yaml.dump(nested, default_flow_style=False), encoding="utf-8")
            else:
                new_path.write_text(json.dumps(nested, indent=2, default=str), encoding="utf-8")
            old_path = self.config_path
            self.config_path = new_path
            if old_path and old_path.exists() and old_path != new_path:
                old_path.unlink()
            return True
        except Exception:
            return False

    def get_source_info(self, key: str) -> str:
        for source in reversed(self._loaded_sources):
            if source == ConfigSource.ENVIRONMENT:
                env_key = f"{self.env_prefix}{key.upper().replace('.', '__')}"
                if env_key in os.environ:
                    return f"environment ({env_key})"
            elif source == ConfigSource.FILE:
                if self.config_path and self.config_path.exists():
                    return f"file ({self.config_path})"
            elif source == ConfigSource.DEFAULT:
                return "default"
            elif source == ConfigSource.EXPLICIT:
                return "explicit"
            elif source == ConfigSource.CLI:
                return "CLI"
        return "unknown"

    def print_source_audit(self) -> None:
        self.console.print()
        self.console.print(Panel("Configuration Value Sources", title="Source Audit", border_style="blue"))
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("Key", style="green")
        table.add_column("Value", style="yellow")
        table.add_column("Source", style="magenta")
        for key in sorted(self.schema.fields.keys()):
            val = self.config.get(key, self.schema.get_default(key))
            source = self.get_source_info(key)
            display = "********" if self.schema.is_sensitive(key) and val else str(val)
            table.add_row(key, display[:60], source)
        self.console.print(table)

    def set_many(self, config_updates: Dict[str, str]) -> int:
        count = 0
        for key, value in config_updates.items():
            try:
                coerced = self._coerce_type(key, value)
                self.set(key, coerced)
                count += 1
            except ConfigValidationError as e:
                self.console.print(f"[red]Skipped {key}: {e}[/red]")
            except Exception as e:
                self.console.print(f"[red]Error setting {key}: {e}[/red]")
        if count > 0:
            self._save()
        return count

    def get_section_config(self, section: str) -> Dict[str, Any]:
        prefix = f"{section}."
        return {k[len(prefix):]: v for k, v in self.config.items() if k.startswith(prefix)}

    def print_section(self, section: str, output_json: bool = False) -> None:
        section_config = self.get_section_config(section)
        if not section_config:
            self.console.print(f"[yellow]No configuration found for section '{section}'[/yellow]")
            return
        if output_json:
            self.console.print(json.dumps(section_config, indent=2))
            return
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("Key", style="green")
        table.add_column("Value", style="yellow")
        for key, value in sorted(section_config.items()):
            full_key = f"{section}.{key}"
            display = "********" if self.schema.is_sensitive(full_key) and value else str(value)
            table.add_row(key, display)
        label = f"{section.title()} Configuration"
        self.console.print(Panel(table, title=label, border_style="blue"))

    def search_config(self, query: str) -> List[Tuple[str, Any]]:
        query_lower = query.lower()
        results = []
        for key in self.schema.fields:
            if query_lower in key.lower():
                results.append((key, self.config.get(key, self.schema.get_default(key))))
            else:
                desc = self.schema.get_description(key)
                if query_lower in desc.lower():
                    results.append((key, self.config.get(key, self.schema.get_default(key))))
        return results

    def print_search_results(self, query: str) -> None:
        results = self.search_config(query)
        if not results:
            self.console.print(f"[yellow]No results for '{query}'[/yellow]")
            return
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("Key", style="green")
        table.add_column("Value", style="yellow")
        table.add_column("Description", style="grey50")
        for key, value in results:
            display = "********" if self.schema.is_sensitive(key) and value else str(value)
            desc = self.schema.get_description(key)
            table.add_row(key, display[:60], desc[:60])
        self.console.print(Panel(table, title=f"Search Results for '{query}'", border_style="blue"))

    def get_stats(self) -> Dict[str, Any]:
        total = len(self.schema.fields)
        configured = sum(1 for k in self.schema.fields if k in self.config)
        return {
            "total_keys": total,
            "configured_keys": configured,
            "unconfigured_keys": total - configured,
            "config_file": str(self.config_path) if self.config_path else "none",
            "config_file_exists": self.config_path.exists() if self.config_path else False,
            "loaded_sources": [s.value for s in self._loaded_sources],
            "config_size": self.config_path.stat().st_size if self.config_path and self.config_path.exists() else 0,
        }
