"""Persistent rule storage with filesystem backend supporting JSON and YAML formats."""

import copy
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from ..models.rule import Rule, RuleSet, RuleStatus, RuleTier, RuleType, RuleGroup, RuleTemplate

logger = logging.getLogger(__name__)


class StorageFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"


class StorageError(Exception):
    pass


class RuleNotFoundError(StorageError):
    pass


class RuleExistsError(StorageError):
    pass


class StorageCorruptionError(StorageError):
    pass


@dataclass
class StorageConfig:
    base_path: str = "storage/rules"
    format: StorageFormat = StorageFormat.JSON
    index_enabled: bool = True
    auto_save: bool = True
    pretty_print: bool = True
    backup_on_write: bool = False
    max_rules_per_file: int = 1000
    compression_enabled: bool = False
    file_extension: str = ".json"
    index_file_name: str = "index.json"
    batch_size: int = 100
    max_import_batch: int = 10000
    validate_on_write: bool = True
    create_backup_on_error: bool = True


class RuleIndex:
    """Multi-dimensional index for fast rule lookup."""

    def __init__(self):
        self._by_id: Dict[str, str] = {}
        self._by_tier: Dict[str, List[str]] = {}
        self._by_type: Dict[str, List[str]] = {}
        self._by_status: Dict[str, List[str]] = {}
        self._by_tag: Dict[str, List[str]] = {}
        self._by_name: Dict[str, str] = {}
        self._by_priority_range: Dict[str, List[str]] = {}
        self._by_severity: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

    def add_rule(self, rule: Rule, file_path: str) -> None:
        with self._lock:
            self._by_id[rule.id] = file_path
            self._by_tier.setdefault(rule.tier.value, []).append(rule.id)
            self._by_type.setdefault(rule.rule_type.value, []).append(rule.id)
            self._by_status.setdefault(rule.status.value, []).append(rule.id)
            self._by_name[rule.name] = rule.id
            for tag in rule.tags:
                self._by_tag.setdefault(tag, []).append(rule.id)
            priority_key = self._priority_bucket(rule.priority)
            self._by_priority_range.setdefault(priority_key, []).append(rule.id)
            self._by_severity.setdefault(rule.severity.value, []).append(rule.id)

    def remove_rule(self, rule_id: str) -> Optional[str]:
        with self._lock:
            file_path = self._by_id.pop(rule_id, None)
            if file_path is None:
                return None
            for index in [self._by_tier, self._by_type, self._by_status, self._by_severity]:
                for key, ids in list(index.items()):
                    if rule_id in ids:
                        ids.remove(rule_id)
                        if not ids:
                            del index[key]
            for tag, ids in list(self._by_tag.items()):
                if rule_id in ids:
                    ids.remove(rule_id)
                    if not ids:
                        del self._by_tag[tag]
            name_to_remove = None
            for name, rid in list(self._by_name.items()):
                if rid == rule_id:
                    name_to_remove = name
                    break
            if name_to_remove:
                del self._by_name[name_to_remove]
            for bucket, ids in list(self._by_priority_range.items()):
                if rule_id in ids:
                    ids.remove(rule_id)
                    if not ids:
                        del self._by_priority_range[bucket]
            return file_path

    def update_rule(self, old_rule: Rule, new_rule: Rule, file_path: str) -> None:
        with self._lock:
            self.remove_rule(old_rule.id)
            self.add_rule(new_rule, file_path)

    def find_by_id(self, rule_id: str) -> Optional[str]:
        with self._lock:
            return self._by_id.get(rule_id)

    def find_by_tier(self, tier: RuleTier) -> List[str]:
        with self._lock:
            return list(self._by_tier.get(tier.value, []))

    def find_by_type(self, rule_type: RuleType) -> List[str]:
        with self._lock:
            return list(self._by_type.get(rule_type.value, []))

    def find_by_status(self, status: RuleStatus) -> List[str]:
        with self._lock:
            return list(self._by_status.get(status.value, []))

    def find_by_tag(self, tag: str) -> List[str]:
        with self._lock:
            return list(self._by_tag.get(tag, []))

    def find_by_name(self, name: str) -> Optional[str]:
        with self._lock:
            return self._by_name.get(name)

    def find_by_severity(self, severity: str) -> List[str]:
        with self._lock:
            return list(self._by_severity.get(severity, []))

    def find_by_priority_range(self, min_p: int, max_p: int) -> List[str]:
        with self._lock:
            results = []
            for key, ids in self._by_priority_range.items():
                parts = key.split("-")
                if len(parts) == 2:
                    try:
                        bmin, bmax = int(parts[0]), int(parts[1])
                        if bmin <= max_p and bmax >= min_p:
                            results.extend(ids)
                    except ValueError:
                        pass
            return results

    def get_all_ids(self) -> List[str]:
        with self._lock:
            return list(self._by_id.keys())

    def get_count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_rules": len(self._by_id),
                "by_tier": {k: len(v) for k, v in self._by_tier.items()},
                "by_type": {k: len(v) for k, v in self._by_type.items()},
                "by_status": {k: len(v) for k, v in self._by_status.items()},
                "by_severity": {k: len(v) for k, v in self._by_severity.items()},
                "unique_tags": len(self._by_tag),
            }

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._by_tier.clear()
            self._by_type.clear()
            self._by_status.clear()
            self._by_tag.clear()
            self._by_name.clear()
            self._by_priority_range.clear()
            self._by_severity.clear()

    def rebuild_from(self, rules: Dict[str, Tuple[Rule, str]]) -> None:
        with self._lock:
            self.clear()
            for rule_id, (rule, file_path) in rules.items():
                self.add_rule(rule, file_path)

    def search(self, query: str, fields: Optional[List[str]] = None) -> List[str]:
        with self._lock:
            query_lower = query.lower()
            results = set()
            search_fields = fields or ["id", "name"]
            for rule_id, file_path in self._by_id.items():
                for field_name in search_fields:
                    if field_name == "id" and query_lower in rule_id.lower():
                        results.add(rule_id)
                    elif field_name == "name":
                        name = self._find_name_for_id(rule_id)
                        if name and query_lower in name.lower():
                            results.add(rule_id)
            return list(results)

    def _priority_bucket(self, priority: int) -> str:
        bucket_size = 100
        lower = ((priority - 1) // bucket_size) * bucket_size + 1
        upper = lower + bucket_size - 1
        return f"{lower}-{upper}"

    def _find_name_for_id(self, rule_id: str) -> Optional[str]:
        for name, rid in self._by_name.items():
            if rid == rule_id:
                return name
        return None

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "by_id": dict(self._by_id),
                "by_tier": {k: list(v) for k, v in self._by_tier.items()},
                "by_type": {k: list(v) for k, v in self._by_type.items()},
                "by_status": {k: list(v) for k, v in self._by_status.items()},
                "by_tag": {k: list(v) for k, v in self._by_tag.items()},
                "by_name": dict(self._by_name),
                "by_severity": {k: list(v) for k, v in self._by_severity.items()},
            }

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._by_id = data.get("by_id", {})
            self._by_tier = {k: list(v) for k, v in data.get("by_tier", {}).items()}
            self._by_type = {k: list(v) for k, v in data.get("by_type", {}).items()}
            self._by_status = {k: list(v) for k, v in data.get("by_status", {}).items()}
            self._by_tag = {k: list(v) for k, v in data.get("by_tag", {}).items()}
            self._by_name = data.get("by_name", {})
            self._by_severity = {k: list(v) for k, v in data.get("by_severity", {}).items()}


class RuleStorage:
    """Persistent rule storage with filesystem backend, indexing, batch operations, and import/export."""

    def __init__(self, config: Optional[StorageConfig] = None):
        self.config = config or StorageConfig()
        self._index = RuleIndex()
        self._rules_cache: Dict[str, Rule] = {}
        self._file_registry: Dict[str, Set[str]] = {}
        self._lock = threading.RLock()
        self._change_callbacks: List[Callable] = []
        self._load_count: int = 0
        self._write_count: int = 0
        self._error_count: int = 0
        self._last_load_time: float = 0.0
        self._base_path = Path(self.config.base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)
        if self.config.index_enabled:
            self._load_index()
        logger.info("RuleStorage initialized at %s (format: %s)", self.config.base_path, self.config.format.value)

    def _resolve_path(self, rule_id: str) -> Path:
        prefix = rule_id[:2] if len(rule_id) >= 2 else "xx"
        subdir = self._base_path / prefix
        subdir.mkdir(parents=True, exist_ok=True)
        ext = self.config.file_extension
        return subdir / f"{rule_id}{ext}"

    def _serialize_rule(self, rule: Rule) -> Dict[str, Any]:
        data = rule.dict()
        data["_storage_version"] = "1.0"
        data["_stored_at"] = datetime.utcnow().isoformat()
        return data

    def _deserialize_rule(self, data: Dict[str, Any]) -> Rule:
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        return Rule(**clean)

    def _write_file(self, path: Path, content: Dict[str, Any]) -> None:
        tmp_path = None
        try:
            tmp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
            if self.config.format == StorageFormat.YAML:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    yaml.dump(content, f, default_flow_style=False, sort_keys=False)
            else:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, indent=2 if self.config.pretty_print else None, default=str, ensure_ascii=False)
            shutil.move(str(tmp_path), str(path))
            self._write_count += 1
        except Exception as e:
            self._error_count += 1
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if self.config.create_backup_on_error and path.exists():
                backup_path = path.with_suffix(f".bak.{int(time.time())}{path.suffix}")
                shutil.copy2(str(path), str(backup_path))
            raise StorageError(f"Failed to write {path}: {e}") from e

    def _read_file(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise RuleNotFoundError(f"File not found: {path}")
        try:
            content = path.read_text(encoding="utf-8")
            if self.config.format == StorageFormat.YAML:
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            if not isinstance(data, dict):
                raise StorageCorruptionError(f"Invalid data structure in {path}")
            return data
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            self._error_count += 1
            raise StorageCorruptionError(f"Corrupted file {path}: {e}") from e
        except Exception as e:
            self._error_count += 1
            raise StorageError(f"Failed to read {path}: {e}") from e

    def save_rule(self, rule: Rule, overwrite: bool = True) -> None:
        with self._lock:
            existing = self._index.find_by_id(rule.id)
            if existing and not overwrite:
                raise RuleExistsError(f"Rule {rule.id} already exists")
            file_path = self._resolve_path(rule.id)
            data = self._serialize_rule(rule)
            if self.config.validate_on_write:
                self._validate_rule_data(data)
            self._write_file(file_path, data)
            if existing:
                old_rule = self._rules_cache.get(rule.id)
                if old_rule:
                    self._index.update_rule(old_rule, rule, str(file_path))
                else:
                    self._index.add_rule(rule, str(file_path))
            else:
                self._index.add_rule(rule, str(file_path))
            self._rules_cache[rule.id] = rule
            self._file_registry.setdefault(str(file_path), set()).add(rule.id)
            if self.config.index_enabled:
                self._save_index()
            for cb in self._change_callbacks:
                try:
                    cb("save", rule)
                except Exception as e:
                    logger.error("Change callback error: %s", e)
            logger.debug("Saved rule %s to %s", rule.id, file_path)

    def get_rule(self, rule_id: str) -> Rule:
        with self._lock:
            cached = self._rules_cache.get(rule_id)
            if cached:
                return cached
            file_path_str = self._index.find_by_id(rule_id)
            if file_path_str:
                path = Path(file_path_str)
            else:
                path = self._resolve_path(rule_id)
            if not path.exists():
                raise RuleNotFoundError(f"Rule {rule_id} not found")
            data = self._read_file(path)
            rule = self._deserialize_rule(data)
            self._rules_cache[rule_id] = rule
            return rule

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Rule:
        with self._lock:
            existing = self.get_rule(rule_id)
            for key, value in updates.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
            self.save_rule(existing, overwrite=True)
            logger.debug("Updated rule %s with %d fields", rule_id, len(updates))
            return existing

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            file_path_str = self._index.find_by_id(rule_id)
            if file_path_str:
                path = Path(file_path_str)
            else:
                path = self._resolve_path(rule_id)
            if not path.exists():
                raise RuleNotFoundError(f"Rule {rule_id} not found")
            path.unlink(missing_ok=True)
            self._index.remove_rule(rule_id)
            self._rules_cache.pop(rule_id, None)
            if str(path) in self._file_registry:
                self._file_registry[str(path)].discard(rule_id)
                if not self._file_registry[str(path)]:
                    del self._file_registry[str(path)]
            if self.config.index_enabled:
                self._save_index()
            for cb in self._change_callbacks:
                try:
                    cb("delete", rule_id)
                except Exception as e:
                    logger.error("Change callback error: %s", e)
            logger.debug("Deleted rule %s", rule_id)
            return True

    def rule_exists(self, rule_id: str) -> bool:
        with self._lock:
            if rule_id in self._rules_cache:
                return True
            file_path_str = self._index.find_by_id(rule_id)
            if file_path_str:
                return Path(file_path_str).exists()
            return self._resolve_path(rule_id).exists()

    def find_rules(self, tier: Optional[RuleTier] = None, rule_type: Optional[RuleType] = None,
                   status: Optional[RuleStatus] = None, tag: Optional[str] = None,
                   severity: Optional[str] = None, name: Optional[str] = None,
                   limit: Optional[int] = None, offset: int = 0) -> List[Rule]:
        with self._lock:
            result_ids: Optional[Set[str]] = None
            if tier:
                ids = set(self._index.find_by_tier(tier))
                result_ids = ids if result_ids is None else result_ids & ids
            if rule_type:
                ids = set(self._index.find_by_type(rule_type))
                result_ids = ids if result_ids is None else result_ids & ids
            if status:
                ids = set(self._index.find_by_status(status))
                result_ids = ids if result_ids is None else result_ids & ids
            if tag:
                ids = set(self._index.find_by_tag(tag))
                result_ids = ids if result_ids is None else result_ids & ids
            if severity:
                ids = set(self._index.find_by_severity(severity))
                result_ids = ids if result_ids is None else result_ids & ids
            if name:
                rid = self._index.find_by_name(name)
                ids = {rid} if rid else set()
                result_ids = ids if result_ids is None else result_ids & ids
            if result_ids is None:
                result_ids = set(self._index.get_all_ids())
            sorted_ids = sorted(result_ids)
            if offset:
                sorted_ids = sorted_ids[offset:]
            if limit:
                sorted_ids = sorted_ids[:limit]
            rules = []
            for rid in sorted_ids:
                try:
                    rules.append(self.get_rule(rid))
                except RuleNotFoundError:
                    continue
            return rules

    def find_rule_by_name(self, name: str) -> Optional[Rule]:
        with self._lock:
            rule_id = self._index.find_by_name(name)
            if rule_id:
                try:
                    return self.get_rule(rule_id)
                except RuleNotFoundError:
                    return None
            return None

    def get_all_rules(self) -> List[Rule]:
        with self._lock:
            ids = self._index.get_all_ids()
            rules = []
            for rid in ids:
                try:
                    rules.append(self.get_rule(rid))
                except RuleNotFoundError:
                    continue
            return rules

    def get_rule_count(self) -> int:
        with self._lock:
            return self._index.get_count()

    def save_rules_batch(self, rules: List[Rule], overwrite: bool = True) -> Tuple[int, int]:
        success = 0
        errors = 0
        for rule in rules:
            try:
                self.save_rule(rule, overwrite=overwrite)
                success += 1
            except Exception as e:
                errors += 1
                logger.error("Failed to save rule %s: %s", rule.id, e)
        logger.info("Batch saved %d rules (%d errors)", success, errors)
        return success, errors

    def delete_rules_batch(self, rule_ids: List[str]) -> Tuple[int, int]:
        success = 0
        errors = 0
        for rid in rule_ids:
            try:
                self.delete_rule(rid)
                success += 1
            except Exception as e:
                errors += 1
                logger.error("Failed to delete rule %s: %s", rid, e)
        logger.info("Batch deleted %d rules (%d errors)", success, errors)
        return success, errors

    def import_rules(self, file_path: str, format: Optional[str] = None,
                     overwrite: bool = False, validate: bool = True) -> Tuple[int, int]:
        path = Path(file_path)
        if not path.exists():
            raise StorageError(f"Import file not found: {file_path}")
        fmt = format or path.suffix.lstrip(".")
        try:
            content = path.read_text(encoding="utf-8")
            if fmt == "json":
                data = json.loads(content)
            elif fmt in ("yaml", "yml"):
                data = yaml.safe_load(content)
            else:
                raise StorageError(f"Unsupported import format: {fmt}")
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                raise StorageError("Import data must be a list of rules or a single rule object")
            if len(data) > self.config.max_import_batch:
                logger.warning("Import batch size %d exceeds limit %d, truncating", len(data), self.config.max_import_batch)
                data = data[:self.config.max_import_batch]
            rules = []
            errors = 0
            for item in data:
                try:
                    rule = Rule(**item)
                    if validate:
                        rule.validate()
                    rules.append(rule)
                except Exception as e:
                    errors += 1
                    logger.warning("Skipping invalid rule entry: %s", e)
            success = 0
            for rule in rules:
                try:
                    self.save_rule(rule, overwrite=overwrite)
                    success += 1
                except Exception as e:
                    errors += 1
                    logger.error("Failed to import rule %s: %s", rule.id, e)
            logger.info("Imported %d rules from %s (%d errors)", success, file_path, errors)
            return success, errors
        except Exception as e:
            raise StorageError(f"Import failed: {e}") from e

    def export_rules(self, file_path: str, rule_ids: Optional[List[str]] = None,
                     format: Optional[str] = None, pretty: bool = True) -> int:
        path = Path(file_path)
        fmt = format or path.suffix.lstrip(".")
        if rule_ids:
            rules = []
            for rid in rule_ids:
                try:
                    rules.append(self.get_rule(rid))
                except RuleNotFoundError:
                    logger.warning("Rule %s not found, skipping export", rid)
        else:
            rules = self.get_all_rules()
        data = [rule.dict() for rule in rules]
        try:
            if fmt == "json":
                content = json.dumps(data, indent=2 if pretty else None, default=str, ensure_ascii=False)
            elif fmt in ("yaml", "yml"):
                content = yaml.dump(data, default_flow_style=False, sort_keys=False)
            else:
                raise StorageError(f"Unsupported export format: {fmt}")
            path.write_text(content, encoding="utf-8")
            logger.info("Exported %d rules to %s", len(rules), file_path)
            return len(rules)
        except Exception as e:
            raise StorageError(f"Export failed: {e}") from e

    def save_ruleset(self, ruleset: RuleSet) -> None:
        with self._lock:
            ruleset_path = self._base_path / "rulesets"
            ruleset_path.mkdir(parents=True, exist_ok=True)
            file_path = ruleset_path / f"{ruleset.id}.json"
            data = ruleset.dict()
            data["_storage_version"] = "1.0"
            self._write_file(file_path, data)
            logger.debug("Saved ruleset %s", ruleset.id)

    def load_ruleset(self, ruleset_id: str) -> Optional[RuleSet]:
        ruleset_path = self._base_path / "rulesets"
        file_path = ruleset_path / f"{ruleset_id}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            return RuleSet(**clean)
        except Exception as e:
            logger.error("Failed to load ruleset %s: %s", ruleset_id, e)
            return None

    def delete_ruleset(self, ruleset_id: str) -> bool:
        ruleset_path = self._base_path / "rulesets"
        file_path = ruleset_path / f"{ruleset_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.debug("Deleted ruleset %s", ruleset_id)
            return True
        return False

    def list_rulesets(self) -> List[str]:
        ruleset_path = self._base_path / "rulesets"
        if not ruleset_path.exists():
            return []
        return [p.stem for p in ruleset_path.glob("*.json")]

    def save_rule_group(self, group: RuleGroup) -> None:
        groups_path = self._base_path / "groups"
        groups_path.mkdir(parents=True, exist_ok=True)
        file_path = groups_path / f"{group.group_id}.json"
        data = group.dict()
        data["_storage_version"] = "1.0"
        self._write_file(file_path, data)

    def load_rule_group(self, group_id: str) -> Optional[RuleGroup]:
        groups_path = self._base_path / "groups"
        file_path = groups_path / f"{group_id}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            return RuleGroup(**clean)
        except Exception as e:
            logger.error("Failed to load rule group %s: %s", group_id, e)
            return None

    def save_template(self, template: RuleTemplate) -> None:
        templates_path = self._base_path / "templates"
        templates_path.mkdir(parents=True, exist_ok=True)
        file_path = templates_path / f"{template.template_id}.json"
        data = template.dict()
        data["_storage_version"] = "1.0"
        self._write_file(file_path, data)

    def list_templates(self) -> List[str]:
        templates_path = self._base_path / "templates"
        if not templates_path.exists():
            return []
        return [p.stem for p in templates_path.glob("*.json")]

    def rebuild_index(self) -> int:
        with self._lock:
            self._index.clear()
            self._rules_cache.clear()
            self._file_registry.clear()
            count = 0
            for file_path in self._base_path.rglob(f"*{self.config.file_extension}"):
                if "rulesets" in file_path.parts or "groups" in file_path.parts or "templates" in file_path.parts or "index" in file_path.parts:
                    continue
                try:
                    data = self._read_file(file_path)
                    rule = self._deserialize_rule(data)
                    self._index.add_rule(rule, str(file_path))
                    self._rules_cache[rule.id] = rule
                    self._file_registry.setdefault(str(file_path), set()).add(rule.id)
                    count += 1
                except Exception as e:
                    logger.warning("Skipping corrupted file %s: %s", file_path, e)
            if self.config.index_enabled:
                self._save_index()
            logger.info("Rebuilt index with %d rules", count)
            return count

    def add_change_callback(self, callback: Callable[[str, Any], None]) -> None:
        self._change_callbacks.append(callback)

    def remove_change_callback(self, callback: Callable) -> None:
        self._change_callbacks = [c for c in self._change_callbacks if c is not callback]

    def search_rules(self, query: str, fields: Optional[List[str]] = None,
                     limit: int = 50) -> List[Rule]:
        with self._lock:
            ids = self._index.search(query, fields)
            ids = ids[:limit]
            rules = []
            for rid in ids:
                try:
                    rules.append(self.get_rule(rid))
                except RuleNotFoundError:
                    continue
            return rules

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            index_stats = self._index.get_stats()
            total_size = 0
            file_count = 0
            for path in self._base_path.rglob(f"*{self.config.file_extension}"):
                try:
                    total_size += path.stat().st_size
                    file_count += 1
                except OSError:
                    pass
            return {
                **index_stats,
                "total_files": file_count,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "load_count": self._load_count,
                "write_count": self._write_count,
                "error_count": self._error_count,
                "last_load_time": datetime.fromtimestamp(self._last_load_time).isoformat() if self._last_load_time else None,
                "cache_size": len(self._rules_cache),
                "base_path": str(self._base_path),
                "format": self.config.format.value,
            }

    def clear(self) -> int:
        with self._lock:
            count = 0
            for file_path in self._base_path.rglob(f"*{self.config.file_extension}"):
                try:
                    file_path.unlink()
                    count += 1
                except OSError:
                    pass
            self._index.clear()
            self._rules_cache.clear()
            self._file_registry.clear()
            self._write_count = 0
            self._error_count = 0
            logger.info("Cleared storage, removed %d files", count)
            return count

    def compact(self) -> Dict[str, Any]:
        with self._lock:
            before_count = self._index.get_count()
            before_size = sum(p.stat().st_size for p in self._base_path.rglob(f"*{self.config.file_extension}") if p.is_file())
            self.rebuild_index()
            after_count = self._index.get_count()
            after_size = sum(p.stat().st_size for p in self._base_path.rglob(f"*{self.config.file_extension}") if p.is_file())
            return {
                "rules_before": before_count,
                "rules_after": after_count,
                "size_before": before_size,
                "size_after": after_size,
                "size_reduced": before_size - after_size,
            }

    def _save_index(self) -> None:
        index_path = self._base_path / self.config.index_file_name
        data = self._index.to_dict()
        self._write_file(index_path, data)

    def _load_index(self) -> None:
        index_path = self._base_path / self.config.index_file_name
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                self._index.load_from_dict(data)
                self._load_count += 1
                self._last_load_time = time.time()
                logger.info("Loaded index with %d rules", self._index.get_count())
            except Exception as e:
                logger.warning("Failed to load index, rebuilding: %s", e)
                self.rebuild_index()
        else:
            logger.info("No index file found, starting with empty index")

    def _validate_rule_data(self, data: Dict[str, Any]) -> None:
        required = {"id", "name", "tier", "rule_type", "severity", "status", "enforcement_level"}
        missing = required - set(data.keys())
        if missing:
            raise StorageError(f"Rule data missing required fields: {missing}")
        allowed_tiers = {"safety", "operational", "preference"}
        if data.get("tier") not in allowed_tiers:
            raise StorageError(f"Invalid tier: {data.get('tier')}")
        allowed_statuses = {"active", "inactive", "deprecated", "testing"}
        if data.get("status") not in allowed_statuses:
            raise StorageError(f"Invalid status: {data.get('status')}")

    def close(self) -> None:
        with self._lock:
            if self.config.index_enabled:
                self._save_index()
            self._rules_cache.clear()
            self._change_callbacks.clear()
            logger.info("RuleStorage closed")

    def __enter__(self) -> "RuleStorage":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"RuleStorage(path={self.config.base_path}, rules={self._index.get_count()})"

    def __len__(self) -> int:
        return self._index.get_count()

    def __contains__(self, rule_id: str) -> bool:
        return self.rule_exists(rule_id)

    def __getitem__(self, rule_id: str) -> Rule:
        return self.get_rule(rule_id)

    def __setitem__(self, rule_id: str, rule: Rule) -> None:
        if rule.id != rule_id:
            raise StorageError("Rule ID mismatch")
        self.save_rule(rule, overwrite=True)

    def __delitem__(self, rule_id: str) -> None:
        self.delete_rule(rule_id)

    def __iter__(self):
        ids = self._index.get_all_ids()
        for rid in ids:
            try:
                yield self.get_rule(rid)
            except RuleNotFoundError:
                continue