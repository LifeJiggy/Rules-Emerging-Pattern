"""SkillRegistry - Central registry for skills with registration, query, lifecycle, conflict detection, and statistics."""

import logging
import time
import json
import threading
import copy
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class RegistryEvent(Enum):
    SKILL_REGISTERED = "skill_registered"
    SKILL_UNREGISTERED = "skill_unregistered"
    SKILL_ACTIVATED = "skill_activated"
    SKILL_DEACTIVATED = "skill_deactivated"
    SKILL_UPDATED = "skill_updated"
    SKILL_DEPRECATED = "skill_deprecated"
    SKILL_DISABLED = "skill_disabled"
    REGISTRY_CLEARED = "registry_cleared"
    CONFLICT_DETECTED = "conflict_detected"
    DEPENDENCY_RESOLVED = "dependency_resolved"
    DEPENDENCY_FAILED = "dependency_failed"


@dataclass
class RegistryConfig:
    allow_duplicates: bool = False
    auto_activate: bool = False
    validate_on_register: bool = True
    resolve_dependencies: bool = True
    track_history: bool = True
    history_size: int = 1000
    conflict_check: bool = True
    strict_mode: bool = False
    namespace_separator: str = "."
    max_skills: Optional[int] = None
    default_timeout: float = 30.0
    environment: str = "default"
    tags_index: bool = True
    category_index: bool = True
    version_index: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegistryConfig":
        return cls(
            allow_duplicates=data.get("allow_duplicates", False),
            auto_activate=data.get("auto_activate", False),
            validate_on_register=data.get("validate_on_register", True),
            resolve_dependencies=data.get("resolve_dependencies", True),
            track_history=data.get("track_history", True),
            history_size=data.get("history_size", 1000),
            conflict_check=data.get("conflict_check", True),
            strict_mode=data.get("strict_mode", False),
            namespace_separator=data.get("namespace_separator", "."),
            max_skills=data.get("max_skills"),
            default_timeout=data.get("default_timeout", 30.0),
            environment=data.get("environment", "default"),
            tags_index=data.get("tags_index", True),
            category_index=data.get("category_index", True),
            version_index=data.get("version_index", True),
        )


@dataclass
class RegistryEventEntry:
    event: RegistryEvent
    skill_name: str
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event.value,
            "skill_name": self.skill_name,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class RegistryStats:
    total_skills: int = 0
    active_skills: int = 0
    inactive_skills: int = 0
    draft_skills: int = 0
    deprecated_skills: int = 0
    disabled_skills: int = 0
    error_skills: int = 0
    registered_skills: int = 0
    total_categories: int = 0
    total_namespaces: int = 0
    total_dependencies: int = 0
    unresolved_dependencies: int = 0
    total_conflicts: int = 0
    total_events: int = 0
    unique_tags: int = 0
    total_executions: int = 0
    total_errors: int = 0
    avg_elapsed: float = 0.0
    last_updated: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


@dataclass
class RegistryNamespace:
    name: str
    parent: Optional[str] = None
    skills: Dict[str, "RuleSkill"] = field(default_factory=dict)
    sub_namespaces: Dict[str, "RegistryNamespace"] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    description: str = ""

    def skill_count(self) -> int:
        count = len(self.skills)
        for ns in self.sub_namespaces.values():
            count += ns.skill_count()
        return count


@dataclass
class RegistrySnapshot:
    timestamp: float = field(default_factory=time.time)
    skills: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    tags_index: Dict[str, List[str]] = field(default_factory=dict)
    category_index: Dict[str, List[str]] = field(default_factory=dict)


from .rule_skill import RuleSkill, SkillDependency, SkillCategory, SkillStatus, SkillVersion


class SkillRegistry:
    def __init__(
        self,
        config: Optional[Union[RegistryConfig, Dict[str, Any]]] = None,
        name: str = "default",
    ):
        self._name = name
        if isinstance(config, dict):
            self._config = RegistryConfig.from_dict(config)
        elif config is None:
            self._config = RegistryConfig()
        else:
            self._config = config
        self._skills: Dict[str, RuleSkill] = {}
        self._namespaces: Dict[str, RegistryNamespace] = {}
        self._namespace_index: Dict[str, str] = {}
        self._tags_index: Dict[str, List[str]] = {}
        self._category_index: Dict[str, List[str]] = {}
        self._version_index: Dict[str, List[str]] = {}
        self._aliases_index: Dict[str, str] = {}
        self._groups_index: Dict[str, List[str]] = {}
        self._dependencies_graph: Dict[str, List[str]] = {}
        self._reverse_deps: Dict[str, List[str]] = {}
        self._conflicts: List[Dict[str, Any]] = []
        self._history: List[RegistryEventEntry] = []
        self._listeners: Dict[RegistryEvent, List[Callable[..., Any]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._stats: RegistryStats = RegistryStats()
        self._created_at = time.time()
        self._last_snapshot: Optional[RegistrySnapshot] = None
        self._snapshot_interval: float = 300.0
        self._initialized = False
        self._frozen = False
        self._version: str = "1.0.0"

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> RegistryConfig:
        return self._config

    @property
    def stats(self) -> RegistryStats:
        return self._stats

    @property
    def skills(self) -> Dict[str, RuleSkill]:
        with self._lock:
            return dict(self._skills)

    @property
    def history(self) -> List[RegistryEventEntry]:
        with self._lock:
            return list(self._history)

    @property
    def conflicts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._conflicts)

    @property
    def frozen(self) -> bool:
        return self._frozen

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            root_ns = RegistryNamespace(name="root")
            self._namespaces["root"] = root_ns
            self._initialized = True
            self._log_event(RegistryEvent.REGISTRY_CLEARED, "", {"action": "initialize"})
            logger.info(f"Registry '{self._name}' initialized")

    def register(
        self,
        skill: RuleSkill,
        namespace: str = "root",
        auto_activate: Optional[bool] = None,
    ) -> bool:
        with self._lock:
            if self._frozen:
                logger.warning(f"Registry '{self._name}' is frozen, cannot register")
                return False
            if not self._initialized:
                self.initialize()
            if self._config.max_skills and len(self._skills) >= self._config.max_skills:
                logger.error(f"Registry '{self._name}' has reached max skills ({self._config.max_skills})")
                return False
            if skill.name in self._skills and not self._config.allow_duplicates:
                logger.warning(f"Skill '{skill.name}' already registered")
                return False
            if self._config.validate_on_register:
                validation = self._validate_skill(skill)
                if validation:
                    for err in validation:
                        logger.warning(f"Validation error for '{skill.name}': {err}")
                    if self._config.strict_mode:
                        return False
            if self._config.conflict_check:
                conflicts = self._detect_conflicts(skill)
                if conflicts:
                    self._conflicts.extend(conflicts)
                    for c in conflicts:
                        self._log_event(
                            RegistryEvent.CONFLICT_DETECTED, skill.name,
                            {"conflicts": c, "namespace": namespace},
                        )
                    if self._config.strict_mode:
                        return False
            self._ensure_namespace(namespace)
            self._skills[skill.name] = skill
            self._namespace_index[skill.name] = namespace
            self._index_skill(skill)
            self._resolve_dependencies(skill)
            skill.register()
            if auto_activate or (auto_activate is None and self._config.auto_activate):
                skill.activate()
            self._update_stats()
            self._log_event(RegistryEvent.SKILL_REGISTERED, skill.name, {
                "namespace": namespace,
                "category": skill.metadata.category.name,
                "version": str(skill.metadata.version),
            })
            logger.info(f"Skill '{skill.name}' registered in namespace '{namespace}'")
            return True

    def unregister(self, name: str) -> bool:
        with self._lock:
            if self._frozen:
                logger.warning(f"Registry '{self._name}' is frozen, cannot unregister")
                return False
            skill = self._skills.get(name)
            if not skill:
                logger.warning(f"Skill '{name}' not found")
                return False
            reverse_deps = self._reverse_deps.get(name, [])
            if reverse_deps:
                deps_str = ", ".join(reverse_deps)
                logger.warning(f"Skill '{name}' is required by: {deps_str}")
                if self._config.strict_mode:
                    return False
            skill.unregister()
            self._remove_from_indexes(skill)
            del self._skills[name]
            if name in self._namespace_index:
                del self._namespace_index[name]
            self._dependencies_graph.pop(name, None)
            for deps in self._dependencies_graph.values():
                if name in deps:
                    deps.remove(name)
            self._reverse_deps.pop(name, None)
            for k, v in list(self._reverse_deps.items()):
                if name in v:
                    v.remove(name)
            self._update_stats()
            self._log_event(RegistryEvent.SKILL_UNREGISTERED, name, {})
            logger.info(f"Skill '{name}' unregistered")
            return True

    def get(self, name: str, resolve_alias: bool = True) -> Optional[RuleSkill]:
        with self._lock:
            skill = self._skills.get(name)
            if skill is None and resolve_alias:
                resolved = self._aliases_index.get(name)
                if resolved:
                    skill = self._skills.get(resolved)
            return skill

    def get_by_id(self, skill_id: str) -> Optional[RuleSkill]:
        with self._lock:
            for skill in self._skills.values():
                if skill.skill_id == skill_id:
                    return skill
            return None

    def query(
        self,
        category: Optional[SkillCategory] = None,
        tags: Optional[List[str]] = None,
        status: Optional[SkillStatus] = None,
        namespace: Optional[str] = None,
        version: Optional[str] = None,
        group: Optional[str] = None,
        environment: Optional[str] = None,
        min_priority: Optional[int] = None,
        max_priority: Optional[int] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[RuleSkill]:
        with self._lock:
            results = list(self._skills.values())
            if category is not None:
                results = [s for s in results if s.metadata.category == category]
            if tags:
                results = [s for s in results if all(t in s.tags for t in tags)]
            if status is not None:
                results = [s for s in results if s.status == status]
            if namespace is not None:
                results = [
                    s for s in results
                    if self._namespace_index.get(s.name) == namespace
                    or self._namespace_index.get(s.name, "").startswith(f"{namespace}.")
                ]
            if version:
                v_obj = SkillVersion.parse(version)
                results = [s for s in results if s.metadata.version.compat(v_obj)]
            if group:
                results = [s for s in results if group in s.groups]
            if environment:
                results = [s for s in results if environment in s._environments]
            if min_priority is not None:
                results = [s for s in results if s.metadata.priority.value >= min_priority]
            if max_priority is not None:
                results = [s for s in results if s.metadata.priority.value <= max_priority]
            if search:
                search_lower = search.lower()
                results = [
                    s for s in results
                    if search_lower in s.name.lower()
                    or search_lower in s.metadata.description.lower()
                    or any(search_lower in t.lower() for t in s.tags)
                ]
            results.sort(key=lambda s: (s.metadata.priority.value, s.name))
            if offset:
                results = results[offset:]
            if limit is not None:
                results = results[:limit]
            return results

    def query_by_tag(self, tag: str) -> List[RuleSkill]:
        with self._lock:
            names = self._tags_index.get(tag, [])
            return [self._skills[n] for n in names if n in self._skills]

    def query_by_category(self, category: SkillCategory) -> List[RuleSkill]:
        with self._lock:
            names = self._category_index.get(category.name, [])
            return [self._skills[n] for n in names if n in self._skills]

    def query_by_group(self, group: str) -> List[RuleSkill]:
        with self._lock:
            names = self._groups_index.get(group, [])
            return [self._skills[n] for n in names if n in self._skills]

    def activate(self, name: str) -> bool:
        with self._lock:
            skill = self.get(name)
            if not skill:
                logger.warning(f"Skill '{name}' not found")
                return False
            skill.activate()
            self._log_event(RegistryEvent.SKILL_ACTIVATED, name, {})
            self._update_stats()
            return True

    def deactivate(self, name: str) -> bool:
        with self._lock:
            skill = self.get(name)
            if not skill:
                return False
            reverse_deps = self._reverse_deps.get(name, [])
            active_dependents = [
                d for d in reverse_deps
                if d in self._skills and self._skills[d].is_active()
            ]
            if active_dependents:
                deps_str = ", ".join(active_dependents)
                logger.warning(f"Active skills depend on '{name}': {deps_str}")
                if self._config.strict_mode:
                    return False
            skill.deactivate()
            self._log_event(RegistryEvent.SKILL_DEACTIVATED, name, {})
            self._update_stats()
            return True

    def deprecate(self, name: str) -> bool:
        with self._lock:
            skill = self.get(name)
            if not skill:
                return False
            skill.deprecate()
            self._log_event(RegistryEvent.SKILL_DEPRECATED, name, {})
            self._update_stats()
            return True

    def disable(self, name: str) -> bool:
        with self._lock:
            skill = self.get(name)
            if not skill:
                return False
            skill.disable()
            self._log_event(RegistryEvent.SKILL_DISABLED, name, {})
            self._update_stats()
            return True

    def update_skill(self, name: str, updated_skill: RuleSkill) -> bool:
        with self._lock:
            if self._frozen:
                return False
            existing = self.get(name)
            if not existing:
                return False
            old_status = existing.status
            namespace = self._namespace_index.get(name, "root")
            self._remove_from_indexes(existing)
            self._skills[name] = updated_skill
            self._index_skill(updated_skill)
            if old_status == SkillStatus.ACTIVE:
                updated_skill.activate()
            self._update_stats()
            self._log_event(RegistryEvent.SKILL_UPDATED, name, {
                "old_checksum": existing.checksum,
                "new_checksum": updated_skill.checksum,
            })
            return True

    def activate_all(self) -> int:
        with self._lock:
            count = 0
            for name, skill in self._skills.items():
                if skill.status in (SkillStatus.REGISTERED, SkillStatus.INACTIVE):
                    skill.activate()
                    count += 1
            self._update_stats()
            return count

    def deactivate_all(self) -> int:
        with self._lock:
            count = 0
            for name, skill in self._skills.items():
                if skill.is_active():
                    skill.deactivate()
                    count += 1
            self._update_stats()
            return count

    def clear(self) -> None:
        with self._lock:
            if self._frozen:
                return
            self._skills.clear()
            self._namespaces.clear()
            self._namespace_index.clear()
            self._tags_index.clear()
            self._category_index.clear()
            self._version_index.clear()
            self._aliases_index.clear()
            self._groups_index.clear()
            self._dependencies_graph.clear()
            self._reverse_deps.clear()
            self._conflicts.clear()
            root_ns = RegistryNamespace(name="root")
            self._namespaces["root"] = root_ns
            self._update_stats()
            self._log_event(RegistryEvent.REGISTRY_CLEARED, "", {"action": "clear"})
            logger.info(f"Registry '{self._name}' cleared")

    def freeze(self) -> None:
        self._frozen = True
        logger.info(f"Registry '{self._name}' frozen")

    def unfreeze(self) -> None:
        self._frozen = False
        logger.info(f"Registry '{self._name}' unfrozen")

    def has_skill(self, name: str) -> bool:
        with self._lock:
            return name in self._skills or name in self._aliases_index

    def skill_count(self) -> int:
        with self._lock:
            return len(self._skills)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._skills.values() if s.is_active())

    def category_count(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for skill in self._skills.values():
                cat = skill.metadata.category.name
                counts[cat] = counts.get(cat, 0) + 1
            return counts

    def namespace_count(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for ns in self._namespace_index.values():
                counts[ns] = counts.get(ns, 0) + 1
            return counts

    def tags_summary(self) -> Dict[str, int]:
        with self._lock:
            return {tag: len(skills) for tag, skills in self._tags_index.items()}

    def get_namespace(self, namespace: str) -> Optional[RegistryNamespace]:
        with self._lock:
            return self._namespaces.get(namespace)

    def list_namespaces(self) -> List[str]:
        with self._lock:
            return list(self._namespaces.keys())

    def list_categories(self) -> List[str]:
        with self._lock:
            return list(self._category_index.keys())

    def list_tags(self) -> List[str]:
        with self._lock:
            return list(self._tags_index.keys())

    def list_groups(self) -> List[str]:
        with self._lock:
            return list(self._groups_index.keys())

    def add_listener(self, event: RegistryEvent, listener: Callable[..., Any]) -> None:
        with self._lock:
            self._listeners[event].append(listener)

    def remove_listener(self, event: RegistryEvent, listener: Callable[..., Any]) -> None:
        with self._lock:
            if listener in self._listeners[event]:
                self._listeners[event].remove(listener)

    def _validate_skill(self, skill: RuleSkill) -> List[str]:
        errors = []
        if not skill.name:
            errors.append("Skill name is required")
        if self._config.max_skills and len(self._skills) >= self._config.max_skills:
            errors.append(f"Max skills reached ({self._config.max_skills})")
        if self._config.namespace_separator in skill.name:
            errors.append(f"Skill name cannot contain namespace separator '{self._config.namespace_separator}'")
        for existing in self._skills.values():
            if existing.skill_id == skill.skill_id:
                errors.append(f"Duplicate skill ID: {skill.skill_id}")
                break
        return errors

    def _detect_conflicts(self, skill: RuleSkill) -> List[Dict[str, Any]]:
        conflicts = []
        for name, existing in self._skills.items():
            if name == skill.name:
                continue
            if existing.handler and skill.handler and existing.handler.__code__ == skill.handler.__code__:
                conflicts.append({
                    "type": "handler_collision",
                    "skill_a": skill.name,
                    "skill_b": name,
                    "details": "Same handler function reference",
                })
            shared_tags = set(existing.tags) & set(skill.tags)
            if shared_tags and existing.metadata.category == skill.metadata.category:
                if existing.metadata.priority == skill.metadata.priority:
                    conflicts.append({
                        "type": "tag_category_priority_collision",
                        "skill_a": skill.name,
                        "skill_b": name,
                        "tags": list(shared_tags),
                        "details": "Same tags, category, and priority",
                    })
        return conflicts

    def _resolve_dependencies(self, skill: RuleSkill) -> None:
        self._dependencies_graph.setdefault(skill.name, [])
        for dep in skill.dependencies:
            dep_name = dep.name
            resolved = self._aliases_index.get(dep_name, dep_name)
            if resolved in self._skills:
                self._dependencies_graph[skill.name].append(resolved)
                self._reverse_deps.setdefault(resolved, []).append(skill.name)
                self._log_event(
                    RegistryEvent.DEPENDENCY_RESOLVED,
                    skill.name,
                    {"dependency": dep_name, "resolved_to": resolved},
                )
            elif not dep.optional:
                self._log_event(
                    RegistryEvent.DEPENDENCY_FAILED,
                    skill.name,
                    {"dependency": dep_name, "reason": "not_found"},
                )
                logger.warning(f"Dependency '{dep_name}' for skill '{skill.name}' not resolved")

    def _index_skill(self, skill: RuleSkill) -> None:
        if self._config.tags_index:
            for tag in skill.tags:
                self._tags_index.setdefault(tag, []).append(skill.name)
        if self._config.category_index:
            cat_name = skill.metadata.category.name
            self._category_index.setdefault(cat_name, []).append(skill.name)
        if self._config.version_index:
            v_str = str(skill.metadata.version)
            self._version_index.setdefault(v_str, []).append(skill.name)
        for alias in skill.aliases:
            self._aliases_index[alias] = skill.name
        for group in skill.groups:
            self._groups_index.setdefault(group, []).append(skill.name)

    def _remove_from_indexes(self, skill: RuleSkill) -> None:
        for tag in skill.tags:
            if tag in self._tags_index:
                try:
                    self._tags_index[tag].remove(skill.name)
                except ValueError:
                    pass
                if not self._tags_index[tag]:
                    del self._tags_index[tag]
        cat_name = skill.metadata.category.name
        if cat_name in self._category_index:
            try:
                self._category_index[cat_name].remove(skill.name)
            except ValueError:
                pass
            if not self._category_index[cat_name]:
                del self._category_index[cat_name]
        v_str = str(skill.metadata.version)
        if v_str in self._version_index:
            try:
                self._version_index[v_str].remove(skill.name)
            except ValueError:
                pass
            if not self._version_index[v_str]:
                del self._version_index[v_str]
        for alias in skill.aliases:
            self._aliases_index.pop(alias, None)
        for group in skill.groups:
            if group in self._groups_index:
                try:
                    self._groups_index[group].remove(skill.name)
                except ValueError:
                    pass
                if not self._groups_index[group]:
                    del self._groups_index[group]

    def _ensure_namespace(self, namespace: str) -> RegistryNamespace:
        if namespace in self._namespaces:
            return self._namespaces[namespace]
        parts = namespace.split(self._config.namespace_separator)
        current = "root"
        for i in range(1, len(parts) + 1):
            parent = current
            current = self._config.namespace_separator.join(parts[:i])
            if current not in self._namespaces:
                ns = RegistryNamespace(name=current, parent=parent if parent != current else None)
                self._namespaces[current] = ns
                if parent in self._namespaces:
                    self._namespaces[parent].sub_namespaces[current] = ns
        return self._namespaces[namespace]

    def _update_stats(self) -> None:
        self._stats.total_skills = len(self._skills)
        self._stats.active_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.ACTIVE)
        self._stats.inactive_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.INACTIVE)
        self._stats.draft_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.DRAFT)
        self._stats.deprecated_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.DEPRECATED)
        self._stats.disabled_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.DISABLED)
        self._stats.error_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.ERROR)
        self._stats.registered_skills = sum(1 for s in self._skills.values() if s.status == SkillStatus.REGISTERED)
        self._stats.total_categories = len(self._category_index)
        self._stats.total_namespaces = len(self._namespaces)
        self._stats.total_dependencies = sum(len(deps) for deps in self._dependencies_graph.values())
        self._stats.unresolved_dependencies = sum(
            1 for deps in self._dependencies_graph.values()
            for d in deps if d not in self._skills
        )
        self._stats.total_conflicts = len(self._conflicts)
        self._stats.total_events = len(self._history)
        self._stats.unique_tags = len(self._tags_index)
        self._stats.total_executions = sum(s.execution_count for s in self._skills.values())
        self._stats.total_errors = sum(s.error_count for s in self._skills.values())
        total_elapsed = sum(s.total_elapsed for s in self._skills.values())
        self._stats.avg_elapsed = total_elapsed / max(self._stats.total_executions, 1)
        self._stats.last_updated = time.time()

    def _log_event(self, event: RegistryEvent, skill_name: str, details: Dict[str, Any]) -> None:
        if not self._config.track_history:
            return
        entry = RegistryEventEntry(
            event=event,
            skill_name=skill_name,
            details=details,
        )
        self._history.append(entry)
        if len(self._history) > self._config.history_size:
            self._history = self._history[-self._config.history_size:]
        for listener in self._listeners.get(event, []):
            try:
                listener(entry)
            except Exception as e:
                logger.warning(f"Listener failed for event {event.value}: {e}")

    def snapshot(self) -> RegistrySnapshot:
        with self._lock:
            skills_snapshot = {}
            for name, skill in self._skills.items():
                skills_snapshot[name] = skill.to_dict()
            snap = RegistrySnapshot(
                skills=skills_snapshot,
                stats=self._stats.to_dict(),
                config=self._config.to_dict(),
                tags_index=dict(self._tags_index),
                category_index=dict(self._category_index),
            )
            self._last_snapshot = snap
            return snap

    def restore_snapshot(self, snap: RegistrySnapshot) -> bool:
        with self._lock:
            if self._frozen:
                return False
            self._skills.clear()
            self._tags_index.clear()
            self._category_index.clear()
            self._version_index.clear()
            self._aliases_index.clear()
            self._groups_index.clear()
            self._dependencies_graph.clear()
            self._reverse_deps.clear()
            self._conflicts.clear()
            for name, data in snap.skills.items():
                skill = RuleSkill.from_dict(data)
                self._skills[name] = skill
                self._index_skill(skill)
            self._config = RegistryConfig.from_dict(snap.config)
            self._stats = RegistryStats(**snap.stats)
            self._last_snapshot = time.time()
            self._log_event(RegistryEvent.REGISTRY_CLEARED, "", {"action": "restore_snapshot"})
            return True

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self._name,
                "config": self._config.to_dict(),
                "stats": self._stats.to_dict(),
                "skill_count": len(self._skills),
                "namespaces": list(self._namespaces.keys()),
                "tags_index": {k: len(v) for k, v in self._tags_index.items()},
                "category_index": {k: len(v) for k, v in self._category_index.items()},
                "conflicts": self._conflicts,
                "frozen": self._frozen,
                "initialized": self._initialized,
                "created_at": self._created_at,
                "version": self._version,
            }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def export_skills(self, format: str = "json") -> str:
        with self._lock:
            data = {name: skill.to_dict() for name, skill in self._skills.items()}
            if format == "json":
                return json.dumps(data, indent=2, default=str)
            elif format == "python":
                return repr(data)
            else:
                raise ValueError(f"Unsupported export format: {format}")

    def import_skills(self, data: Union[str, Dict[str, Any]], format: str = "json") -> int:
        with self._lock:
            if isinstance(data, str) and format == "json":
                data = json.loads(data)
            count = 0
            for name, skill_data in data.items():
                skill = RuleSkill.from_dict(skill_data)
                if self.register(skill):
                    count += 1
            logger.info(f"Imported {count} skills into registry '{self._name}'")
            return count

    def resolve_aliases(self, name: str) -> Optional[str]:
        with self._lock:
            return self._aliases_index.get(name) or name

    def get_dependents(self, name: str) -> List[str]:
        with self._lock:
            return list(self._reverse_deps.get(name, []))

    def get_dependencies(self, name: str) -> List[str]:
        with self._lock:
            return list(self._dependencies_graph.get(name, []))

    def dependency_chain(self, name: str) -> List[List[str]]:
        with self._lock:
            chains = []

            def walk(current: str, path: List[str]) -> None:
                deps = self._dependencies_graph.get(current, [])
                if not deps:
                    chains.append(list(path))
                    return
                for dep in deps:
                    if dep in path:
                        chains.append(list(path) + [dep])
                        continue
                    path.append(dep)
                    walk(dep, path)
                    path.pop()

            walk(name, [name])
            return chains

    def find_orphans(self) -> List[str]:
        with self._lock:
            all_deps = set()
            for deps in self._dependencies_graph.values():
                all_deps.update(deps)
            return [name for name in self._skills if name not in all_deps]

    def find_circular_dependencies(self) -> List[List[str]]:
        with self._lock:
            visited: Set[str] = set()
            path: List[str] = []
            cycles: List[List[str]] = []

            def dfs(node: str) -> None:
                if node in path:
                    idx = path.index(node)
                    cycles.append(list(path[idx:]))
                    return
                if node in visited:
                    return
                visited.add(node)
                path.append(node)
                for dep in self._dependencies_graph.get(node, []):
                    if dep in self._skills:
                        dfs(dep)
                path.pop()

            for name in self._skills:
                dfs(name)
            return cycles

    def report(self) -> str:
        with self._lock:
            lines = []
            lines.append(f"Registry Report: {self._name}")
            lines.append(f"{'=' * 60}")
            lines.append(f"Total Skills: {self._stats.total_skills}")
            lines.append(f"  Active: {self._stats.active_skills}")
            lines.append(f"  Inactive: {self._stats.inactive_skills}")
            lines.append(f"  Draft: {self._stats.draft_skills}")
            lines.append(f"  Deprecated: {self._stats.deprecated_skills}")
            lines.append(f"  Disabled: {self._stats.disabled_skills}")
            lines.append(f"  Error: {self._stats.error_skills}")
            lines.append(f"Namespaces: {self._stats.total_namespaces}")
            lines.append(f"Categories: {self._stats.total_categories}")
            lines.append(f"Tags: {self._stats.unique_tags}")
            lines.append(f"Dependencies: {self._stats.total_dependencies}")
            lines.append(f"Unresolved Deps: {self._stats.unresolved_dependencies}")
            lines.append(f"Conflicts: {self._stats.total_conflicts}")
            lines.append(f"Total Executions: {self._stats.total_executions}")
            lines.append(f"Total Errors: {self._stats.total_errors}")
            lines.append(f"Avg Elapsed: {self._stats.avg_elapsed:.3f}s")
            if self._conflicts:
                lines.append(f"\nConflicts:")
                for c in self._conflicts:
                    lines.append(f"  - {c['type']}: {c['skill_a']} vs {c['skill_b']}")
            circular = self.find_circular_dependencies()
            if circular:
                lines.append(f"\nCircular Dependencies:")
                for cycle in circular:
                    lines.append(f"  - {' -> '.join(cycle)}")
            return "\n".join(lines)

    def __repr__(self) -> str:
        return f"SkillRegistry(name='{self._name}', skills={len(self._skills)}, active={self._stats.active_skills})"

    def __str__(self) -> str:
        return f"SkillRegistry[{self._name}] ({len(self._skills)} skills, {self._stats.active_skills} active)"

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return self.has_skill(name)

    def __iter__(self):
        return iter(self._skills.values())

    def __getitem__(self, name: str) -> RuleSkill:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Skill '{name}' not found")
        return skill

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def create_registry(config: Optional[Dict[str, Any]] = None, name: str = "default") -> SkillRegistry:
    return SkillRegistry(config=config, name=name)


def merge_registries(*registries: SkillRegistry, name: str = "merged") -> SkillRegistry:
    merged = SkillRegistry(name=name)
    merged.initialize()
    for reg in registries:
        for skill in reg:
            merged.register(skill)
    return merged
