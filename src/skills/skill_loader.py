"""SkillLoader - Load skills from filesystem or packages, parse YAML/JSON definitions, resolve dependencies, with caching and hot-reload."""

import logging
import os
import json
import time
import glob
import importlib
import importlib.util
import inspect
import sys
import hashlib
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class LoaderEvent(Enum):
    SKILL_LOADED = "skill_loaded"
    SKILL_UNLOADED = "skill_unloaded"
    SKILL_RELOADED = "skill_reloaded"
    SKILL_FAILED = "skill_failed"
    SOURCE_CHANGED = "source_changed"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    DEPENDENCY_RESOLVED = "dependency_resolved"
    DEPENDENCY_MISSING = "dependency_missing"
    HOT_RELOAD_TRIGGERED = "hot_reload_triggered"
    PARSE_ERROR = "parse_error"
    IMPORT_ERROR = "import_error"


class SourceType(Enum):
    YAML = "yaml"
    JSON = "json"
    PYTHON = "python"
    PACKAGE = "package"
    DIRECTORY = "directory"
    MODULE = "module"


@dataclass
class SkillSource:
    path: str
    source_type: SourceType
    name: str = ""
    checksum: str = ""
    last_modified: float = 0.0
    size: int = 0
    loaded_at: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_changed(self) -> bool:
        try:
            mod_time = os.path.getmtime(self.path)
            return mod_time != self.last_modified
        except OSError:
            return False

    def update_stats(self) -> None:
        try:
            self.last_modified = os.path.getmtime(self.path)
            self.size = os.path.getsize(self.path)
            with open(self.path, "rb") as f:
                self.checksum = hashlib.md5(f.read()).hexdigest()[:16]
        except OSError:
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "source_type": self.source_type.value,
            "name": self.name,
            "checksum": self.checksum,
            "last_modified": self.last_modified,
            "size": self.size,
            "loaded_at": self.loaded_at,
            "error": self.error,
        }


@dataclass
class LoaderConfig:
    load_paths: List[str] = field(default_factory=lambda: ["."])
    recursive: bool = True
    file_patterns: List[str] = field(default_factory=lambda: ["*.yaml", "*.yml", "*.json", "*.py"])
    ignore_patterns: List[str] = field(default_factory=lambda: ["__pycache__", "*.pyc", ".git", ".DS_Store"])
    default_format: str = "yaml"
    lazy_loading: bool = True
    enable_cache: bool = True
    cache_ttl: float = 300.0
    hot_reload: bool = False
    hot_reload_interval: float = 10.0
    resolve_dependencies: bool = True
    validate_on_load: bool = True
    auto_register: bool = False
    follow_symlinks: bool = False
    max_depth: int = 5
    max_skills: int = 1000
    allow_python_exec: bool = True
    python_import_paths: List[str] = field(default_factory=list)
    strict_mode: bool = False
    namespace_from_path: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoaderConfig":
        return cls(
            load_paths=data.get("load_paths", ["."]),
            recursive=data.get("recursive", True),
            file_patterns=data.get("file_patterns", ["*.yaml", "*.yml", "*.json", "*.py"]),
            ignore_patterns=data.get("ignore_patterns", ["__pycache__", "*.pyc", ".git", ".DS_Store"]),
            default_format=data.get("default_format", "yaml"),
            lazy_loading=data.get("lazy_loading", True),
            enable_cache=data.get("enable_cache", True),
            cache_ttl=data.get("cache_ttl", 300.0),
            hot_reload=data.get("hot_reload", False),
            hot_reload_interval=data.get("hot_reload_interval", 10.0),
            resolve_dependencies=data.get("resolve_dependencies", True),
            validate_on_load=data.get("validate_on_load", True),
            auto_register=data.get("auto_register", False),
            follow_symlinks=data.get("follow_symlinks", False),
            max_depth=data.get("max_depth", 5),
            max_skills=data.get("max_skills", 1000),
            allow_python_exec=data.get("allow_python_exec", True),
            python_import_paths=data.get("python_import_paths", []),
            strict_mode=data.get("strict_mode", False),
            namespace_from_path=data.get("namespace_from_path", True),
        )


@dataclass
class LoaderStats:
    total_loaded: int = 0
    total_failed: int = 0
    total_reloaded: int = 0
    total_unloaded: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_sources: int = 0
    parse_errors: int = 0
    import_errors: int = 0
    dependency_resolved: int = 0
    dependency_missing: int = 0
    start_time: float = field(default_factory=time.time)
    last_load_time: Optional[float] = None
    last_reload_time: Optional[float] = None
    avg_load_time: float = 0.0
    sources_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors_by_source: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


@dataclass
class LoadedSkill:
    skill: "RuleSkill"
    source: SkillSource
    loaded_at: float = field(default_factory=time.time)
    namespace: str = "root"
    dependencies_resolved: bool = False
    checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.skill.name,
            "source": self.source.to_dict(),
            "loaded_at": self.loaded_at,
            "namespace": self.namespace,
            "dependencies_resolved": self.dependencies_resolved,
        }


from .rule_skill import RuleSkill, SkillMetadata, SkillVersion, SkillCategory, SkillPriority, SkillInput, SkillOutput, SkillDependency, SkillTrigger


class SkillLoader:
    def __init__(
        self,
        config: Optional[Union[LoaderConfig, Dict[str, Any]]] = None,
        name: str = "default",
    ):
        self._name = name
        if isinstance(config, dict):
            self._config = LoaderConfig.from_dict(config)
        elif config is None:
            self._config = LoaderConfig()
        else:
            self._config = config
        self._loaded_skills: Dict[str, LoadedSkill] = {}
        self._sources: Dict[str, SkillSource] = {}
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._hot_reload_thread: Optional[threading.Thread] = None
        self._hot_reload_stop = threading.Event()
        self._lock = threading.RLock()
        self._stats = LoaderStats()
        self._listeners: Dict[LoaderEvent, List[Callable[..., Any]]] = defaultdict(list)
        self._imported_modules: Dict[str, Any] = {}
        self._failed_sources: Set[str] = set()
        self._parsers: Dict[SourceType, Callable[..., Any]] = {}
        self._init_parsers()

    def _init_parsers(self) -> None:
        self._parsers[SourceType.YAML] = self._parse_yaml
        self._parsers[SourceType.JSON] = self._parse_json
        self._parsers[SourceType.PYTHON] = self._parse_python
        self._parsers[SourceType.DIRECTORY] = self._parse_directory

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> LoaderConfig:
        return self._config

    @property
    def stats(self) -> LoaderStats:
        with self._lock:
            return self._stats

    @property
    def loaded_skills(self) -> Dict[str, LoadedSkill]:
        with self._lock:
            return dict(self._loaded_skills)

    @property
    def sources(self) -> Dict[str, SkillSource]:
        with self._lock:
            return dict(self._sources)

    def load(
        self,
        source: Union[str, Path, List[str]],
        source_type: Optional[SourceType] = None,
        namespace: str = "root",
    ) -> List[LoadedSkill]:
        started = time.time()
        loaded: List[LoadedSkill] = []
        if isinstance(source, (str, Path)):
            paths = [str(source)]
        else:
            paths = list(source)
        for path in paths:
            path = os.path.abspath(path)
            if not os.path.exists(path):
                logger.warning(f"Source path does not exist: {path}")
                continue
            resolved_type = source_type or self._infer_source_type(path)
            source_obj = SkillSource(
                path=path,
                source_type=resolved_type,
                name=os.path.basename(path),
            )
            source_obj.update_stats()
            self._sources[path] = source_obj
            try:
                parser = self._parsers.get(resolved_type)
                if not parser:
                    logger.error(f"No parser for source type: {resolved_type}")
                    continue
                skills = parser(path, namespace)
                for loaded_skill in skills:
                    skill_name = loaded_skill.skill.name
                    if skill_name in self._loaded_skills and self._config.strict_mode:
                        logger.warning(f"Duplicate skill '{skill_name}' from {path}")
                        continue
                    self._loaded_skills[skill_name] = loaded_skill
                    self._stats.total_loaded += 1
                    loaded.append(loaded_skill)
                    self._notify(LoaderEvent.SKILL_LOADED, skill_name, {
                        "path": path,
                        "namespace": namespace,
                    })
                if self._config.resolve_dependencies:
                    for ls in skills:
                        self._resolve_dependencies(ls)
                if self._config.auto_register:
                    for ls in skills:
                        ls.skill.register()
                        ls.skill.activate()
                source_obj.loaded_at = time.time()
                source_obj.error = None
                self._failed_sources.discard(path)
            except Exception as e:
                source_obj.error = str(e)
                self._failed_sources.add(path)
                self._stats.total_failed += 1
                self._stats.errors_by_source[path] = str(e)
                self._notify(LoaderEvent.SKILL_FAILED, path, {"error": str(e)})
                logger.error(f"Failed to load skills from {path}: {e}")
                if self._config.strict_mode:
                    raise
        elapsed = time.time() - started
        self._stats.last_load_time = elapsed
        self._stats.avg_load_time = (
            (self._stats.avg_load_time * (self._stats.total_loaded - len(loaded)) + elapsed)
            / max(self._stats.total_loaded, 1)
        )
        self._stats.total_sources = len(self._sources)
        return loaded

    def load_from_directory(
        self,
        directory: str,
        namespace: str = "root",
    ) -> List[LoadedSkill]:
        return self.load(directory, source_type=SourceType.DIRECTORY, namespace=namespace)

    def load_from_package(self, package_name: str) -> List[LoadedSkill]:
        try:
            mod = importlib.import_module(package_name)
            path = os.path.dirname(mod.__file__) if mod.__file__ else ""
            source_obj = SkillSource(
                path=path,
                source_type=SourceType.PACKAGE,
                name=package_name,
            )
            self._sources[path] = source_obj
            return self._parse_package(package_name)
        except ImportError as e:
            self._stats.import_errors += 1
            self._notify(LoaderEvent.IMPORT_ERROR, package_name, {"error": str(e)})
            logger.error(f"Failed to import package '{package_name}': {e}")
            raise

    def load_from_string(
        self,
        content: str,
        fmt: str = "yaml",
        name: str = "inline",
        namespace: str = "root",
    ) -> Optional[LoadedSkill]:
        try:
            if fmt == "yaml":
                import yaml
                data = yaml.safe_load(content)
            elif fmt == "json":
                data = json.loads(content)
            else:
                raise ValueError(f"Unsupported format: {fmt}")
            skill = RuleSkill.from_dict(data)
            source = SkillSource(
                path=f"inline:{name}",
                source_type=SourceType.YAML if fmt == "yaml" else SourceType.JSON,
                name=name,
            )
            loaded = LoadedSkill(skill=skill, source=source, namespace=namespace)
            self._loaded_skills[skill.name] = loaded
            self._stats.total_loaded += 1
            return loaded
        except Exception as e:
            self._stats.parse_errors += 1
            self._notify(LoaderEvent.PARSE_ERROR, name, {"error": str(e)})
            logger.error(f"Failed to parse inline skill '{name}': {e}")
            return None

    def reload(self, name: Optional[str] = None) -> bool:
        with self._lock:
            if name:
                loaded = self._loaded_skills.get(name)
                if not loaded:
                    logger.warning(f"Skill '{name}' not loaded")
                    return False
                path = loaded.source.path
                self._loaded_skills.pop(name, None)
                self.load(path, namespace=loaded.namespace)
                self._stats.total_reloaded += 1
                self._notify(LoaderEvent.SKILL_RELOADED, name, {"path": path})
                return True
            else:
                for name, loaded in list(self._loaded_skills.items()):
                    self.reload(name)
                self._stats.total_reloaded += len(self._loaded_skills)
                self._stats.last_reload_time = time.time()
                return True

    def unload(self, name: str) -> bool:
        with self._lock:
            loaded = self._loaded_skills.pop(name, None)
            if loaded:
                self._stats.total_unloaded += 1
                self._notify(LoaderEvent.SKILL_UNLOADED, name, {})
                logger.info(f"Skill '{name}' unloaded")
                return True
            return False

    def unload_all(self) -> int:
        with self._lock:
            count = len(self._loaded_skills)
            names = list(self._loaded_skills.keys())
            for name in names:
                self.unload(name)
            return count

    def get(self, name: str) -> Optional[LoadedSkill]:
        with self._lock:
            return self._loaded_skills.get(name)

    def get_skill(self, name: str) -> Optional[RuleSkill]:
        with self._lock:
            loaded = self._loaded_skills.get(name)
            return loaded.skill if loaded else None

    def find(self, pattern: str) -> List[RuleSkill]:
        with self._lock:
            import fnmatch
            results = []
            for name, loaded in self._loaded_skills.items():
                if fnmatch.fnmatch(name, pattern):
                    results.append(loaded.skill)
                elif fnmatch.fnmatch(loaded.source.path, pattern):
                    results.append(loaded.skill)
            return results

    def query(
        self,
        namespace: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[RuleSkill]:
        with self._lock:
            results = []
            for loaded in self._loaded_skills.values():
                skill = loaded.skill
                if namespace and loaded.namespace != namespace:
                    continue
                if category and skill.metadata.category.name != category:
                    continue
                if tags and not all(t in skill.tags for t in tags):
                    continue
                results.append(skill)
            return results

    def _infer_source_type(self, path: str) -> SourceType:
        if os.path.isdir(path):
            return SourceType.DIRECTORY
        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            return SourceType.YAML
        elif ext == ".json":
            return SourceType.JSON
        elif ext == ".py":
            return SourceType.PYTHON
        return SourceType.YAML

    def _parse_yaml(self, path: str, namespace: str) -> List[LoadedSkill]:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        data = yaml.safe_load(content)
        if not data:
            return []
        if isinstance(data, list):
            skills = []
            for item in data:
                skill = RuleSkill.from_dict(item)
                source = SkillSource(
                    path=path, source_type=SourceType.YAML, name=skill.name
                )
                source.update_stats()
                skills.append(LoadedSkill(skill=skill, source=source, namespace=namespace))
            return skills
        elif isinstance(data, dict):
            if "skills" in data:
                skills = []
                for item in data["skills"]:
                    skill = RuleSkill.from_dict(item)
                    source = SkillSource(
                        path=path, source_type=SourceType.YAML, name=skill.name
                    )
                    source.update_stats()
                    ns = data.get("namespace", namespace)
                    skills.append(LoadedSkill(skill=skill, source=source, namespace=ns))
                return skills
            elif all(k in data for k in ("name", "metadata")):
                skill = RuleSkill.from_dict(data)
                source = SkillSource(
                    path=path, source_type=SourceType.YAML, name=skill.name
                )
                source.update_stats()
                return [LoadedSkill(skill=skill, source=source, namespace=namespace)]
        self._stats.parse_errors += 1
        self._notify(LoaderEvent.PARSE_ERROR, path, {"error": "Invalid YAML structure"})
        raise ValueError(f"Invalid YAML skill definition in {path}")

    def _parse_json(self, path: str, namespace: str) -> List[LoadedSkill]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            skills = []
            for item in data:
                skill = RuleSkill.from_dict(item)
                source = SkillSource(
                    path=path, source_type=SourceType.JSON, name=skill.name
                )
                source.update_stats()
                skills.append(LoadedSkill(skill=skill, source=source, namespace=namespace))
            return skills
        elif isinstance(data, dict):
            if "skills" in data:
                skills = []
                for item in data["skills"]:
                    skill = RuleSkill.from_dict(item)
                    source = SkillSource(
                        path=path, source_type=SourceType.JSON, name=skill.name
                    )
                    source.update_stats()
                    ns = data.get("namespace", namespace)
                    skills.append(LoadedSkill(skill=skill, source=source, namespace=ns))
                return skills
            else:
                skill = RuleSkill.from_dict(data)
                source = SkillSource(
                    path=path, source_type=SourceType.JSON, name=skill.name
                )
                source.update_stats()
                return [LoadedSkill(skill=skill, source=source, namespace=namespace)]
        raise ValueError(f"Invalid JSON skill definition in {path}")

    def _parse_python(self, path: str, namespace: str) -> List[LoadedSkill]:
        if not self._config.allow_python_exec:
            raise PermissionError("Python execution disabled by config")
        module_name = f"_skill_loader_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load module from {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            self._stats.import_errors += 1
            self._notify(LoaderEvent.IMPORT_ERROR, path, {"error": str(e)})
            raise ImportError(f"Failed to execute {path}: {e}")
        skills = []
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if isinstance(attr, RuleSkill):
                source = SkillSource(
                    path=path, source_type=SourceType.PYTHON, name=attr.name
                )
                source.update_stats()
                skills.append(LoadedSkill(skill=attr, source=source, namespace=namespace))
        if not skills:
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if callable(attr) and hasattr(attr, "_is_skill_handler"):
                    skill_name = attr_name.replace("_", " ").title().replace(" ", "")
                    metadata = SkillMetadata(
                        author="auto",
                        tags=[],
                        version=SkillVersion(1, 0, 0),
                    )
                    skill = RuleSkill(
                        name=skill_name,
                        handler=attr,
                        metadata=metadata,
                    )
                    source = SkillSource(
                        path=path, source_type=SourceType.PYTHON, name=skill.name
                    )
                    source.update_stats()
                    skills.append(LoadedSkill(skill=skill, source=source, namespace=namespace))
        return skills

    def _parse_directory(self, path: str, namespace: str) -> List[LoadedSkill]:
        all_skills = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".svn")]
            depth = root.replace(path, "").count(os.sep)
            if depth > self._config.max_depth:
                dirs.clear()
                continue
            for pattern in self._config.file_patterns:
                for filepath in glob.glob(os.path.join(root, pattern)):
                    if any(
                        glob.fnmatch.fnmatch(filepath, ign)
                        for ign in self._config.ignore_patterns
                    ):
                        continue
                    sub_ns = namespace
                    if self._config.namespace_from_path:
                        rel_path = os.path.relpath(os.path.dirname(filepath), path)
                        if rel_path != ".":
                            sub_ns = f"{namespace}.{rel_path.replace(os.sep, '.')}"
                    try:
                        skills = self.load(filepath, namespace=sub_ns)
                        all_skills.extend(skills)
                    except Exception as e:
                        logger.warning(f"Skipping {filepath}: {e}")
                        continue
        return all_skills

    def _parse_package(self, package_name: str) -> List[LoadedSkill]:
        try:
            mod = importlib.import_module(package_name)
        except ImportError as e:
            self._stats.import_errors += 1
            raise
        skills = []
        pkg_path = os.path.dirname(mod.__file__) if mod.__file__ else ""
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if isinstance(attr, RuleSkill):
                source = SkillSource(
                    path=pkg_path,
                    source_type=SourceType.PACKAGE,
                    name=attr.name,
                )
                source.update_stats()
                skills.append(LoadedSkill(skill=attr, source=source, namespace=package_name))
        if not skills and pkg_path:
            directory_skills = self._parse_directory(pkg_path, namespace=package_name)
            skills.extend(directory_skills)
        return skills

    def _resolve_dependencies(self, loaded: LoadedSkill) -> None:
        skill = loaded.skill
        for dep in skill.dependencies:
            dep_name = dep.name
            if dep_name in self._loaded_skills:
                loaded.dependencies_resolved = True
                self._stats.dependency_resolved += 1
                self._notify(LoaderEvent.DEPENDENCY_RESOLVED, skill.name, {
                    "dependency": dep_name,
                })
            elif not dep.optional:
                self._stats.dependency_missing += 1
                self._notify(LoaderEvent.DEPENDENCY_MISSING, skill.name, {
                    "dependency": dep_name,
                })
                logger.warning(f"Missing dependency '{dep_name}' for skill '{skill.name}'")

    def add_listener(self, event: LoaderEvent, listener: Callable[..., Any]) -> None:
        with self._lock:
            self._listeners[event].append(listener)

    def remove_listener(self, event: LoaderEvent, listener: Callable[..., Any]) -> None:
        with self._lock:
            if listener in self._listeners[event]:
                self._listeners[event].remove(listener)

    def _notify(self, event: LoaderEvent, name: str, details: Dict[str, Any]) -> None:
        for listener in self._listeners.get(event, []):
            try:
                listener(event, name, details)
            except Exception as e:
                logger.warning(f"Listener failed for {event.value}: {e}")

    def add_load_path(self, path: str) -> None:
        if path not in self._config.load_paths:
            self._config.load_paths.append(path)

    def remove_load_path(self, path: str) -> None:
        if path in self._config.load_paths:
            self._config.load_paths.remove(path)

    def start_hot_reload(self) -> None:
        if self._hot_reload_thread and self._hot_reload_thread.is_alive():
            logger.warning("Hot-reload already running")
            return
        self._hot_reload_stop.clear()
        self._hot_reload_thread = threading.Thread(
            target=self._hot_reload_loop,
            name=f"skill_hot_reload_{self._name}",
            daemon=True,
        )
        self._hot_reload_thread.start()
        logger.info(f"Hot-reload started for loader '{self._name}'")

    def stop_hot_reload(self) -> None:
        self._hot_reload_stop.set()
        if self._hot_reload_thread:
            self._hot_reload_thread.join(timeout=5)
        logger.info(f"Hot-reload stopped for loader '{self._name}'")

    def _hot_reload_loop(self) -> None:
        while not self._hot_reload_stop.is_set():
            time.sleep(self._config.hot_reload_interval)
            if self._hot_reload_stop.is_set():
                break
            self._check_for_changes()

    def _check_for_changes(self) -> None:
        with self._lock:
            for name, loaded in list(self._loaded_skills.items()):
                source = loaded.source
                try:
                    if source.has_changed():
                        self._notify(LoaderEvent.SOURCE_CHANGED, name, {
                            "path": source.path,
                        })
                        self._notify(LoaderEvent.HOT_RELOAD_TRIGGERED, name, {})
                        self._loaded_skills.pop(name, None)
                        self.load(source.path, namespace=loaded.namespace)
                        logger.info(f"Hot-reloaded skill '{name}' from {source.path}")
                except OSError:
                    continue

    def get_cache(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and time.time() < entry[1]:
            self._stats.cache_hits += 1
            self._notify(LoaderEvent.CACHE_HIT, key, {})
            return entry[0]
        if entry:
            del self._cache[key]
        self._stats.cache_misses += 1
        self._notify(LoaderEvent.CACHE_MISS, key, {})
        return None

    def set_cache(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        expires = time.time() + (ttl or self._config.cache_ttl)
        self._cache[key] = (value, expires)

    def clear_cache(self) -> None:
        self._cache.clear()

    def scan_load_paths(self) -> List[str]:
        found = []
        for load_path in self._config.load_paths:
            if not os.path.exists(load_path):
                continue
            for root, dirs, files in os.walk(load_path):
                depth = root.replace(load_path, "").count(os.sep)
                if depth > self._config.max_depth:
                    dirs.clear()
                    continue
                for pattern in self._config.file_patterns:
                    for f in glob.glob(os.path.join(root, pattern)):
                        found.append(f)
        return found

    def load_all_from_paths(self) -> List[LoadedSkill]:
        all_loaded = []
        for load_path in self._config.load_paths:
            loaded = self.load(load_path)
            all_loaded.extend(loaded)
        return all_loaded

    def get_failed_sources(self) -> Dict[str, str]:
        return dict(self._stats.errors_by_source)

    def clear_failed_sources(self) -> None:
        self._failed_sources.clear()
        self._stats.errors_by_source.clear()

    def get_skill_count(self) -> int:
        return len(self._loaded_skills)

    def list_skills(self) -> List[str]:
        return list(self._loaded_skills.keys())

    def list_sources(self) -> List[SkillSource]:
        return list(self._sources.values())

    def summary(self) -> str:
        lines = []
        lines.append(f"Loader Report: {self._name}")
        lines.append("=" * 60)
        lines.append(f"Total Loaded: {self._stats.total_loaded}")
        lines.append(f"Total Failed: {self._stats.total_failed}")
        lines.append(f"Total Reloaded: {self._stats.total_reloaded}")
        lines.append(f"Total Unloaded: {self._stats.total_unloaded}")
        lines.append(f"Cache Hits: {self._stats.cache_hits}")
        lines.append(f"Cache Misses: {self._stats.cache_misses}")
        lines.append(f"Parse Errors: {self._stats.parse_errors}")
        lines.append(f"Import Errors: {self._stats.import_errors}")
        lines.append(f"Dependencies Resolved: {self._stats.dependency_resolved}")
        lines.append(f"Dependencies Missing: {self._stats.dependency_missing}")
        lines.append(f"Avg Load Time: {self._stats.avg_load_time:.3f}s")
        lines.append(f"Loaded Skills: {len(self._loaded_skills)}")
        for name, loaded in self._loaded_skills.items():
            lines.append(f"  - {name} [{loaded.namespace}] ({loaded.source.source_type.value})")
        if self._stats.errors_by_source:
            lines.append(f"\nFailed Sources:")
            for path, err in list(self._stats.errors_by_source.items())[:10]:
                lines.append(f"  - {path}: {err}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "config": self._config.to_dict(),
            "stats": self._stats.to_dict(),
            "loaded_skills": {k: v.to_dict() for k, v in self._loaded_skills.items()},
            "sources": {k: v.to_dict() for k, v in self._sources.items()},
            "failed_sources": list(self._failed_sources),
            "cache_size": len(self._cache),
        }

    def reset(self) -> None:
        with self._lock:
            self._loaded_skills.clear()
            self._sources.clear()
            self._cache.clear()
            self._failed_sources.clear()
            self._stats = LoaderStats()
            self._imported_modules.clear()

    def __repr__(self) -> str:
        return f"SkillLoader(name='{self._name}', loaded={len(self._loaded_skills)}, sources={len(self._sources)})"

    def __str__(self) -> str:
        return f"SkillLoader[{self._name}] ({len(self._loaded_skills)} skills, {len(self._sources)} sources)"

    def __len__(self) -> int:
        return len(self._loaded_skills)

    def __contains__(self, name: str) -> bool:
        return name in self._loaded_skills

    def __iter__(self):
        return iter(self._loaded_skills.values())

    def __getitem__(self, name: str) -> LoadedSkill:
        loaded = self._loaded_skills.get(name)
        if loaded is None:
            raise KeyError(f"Skill '{name}' not loaded")
        return loaded


def create_loader(config: Optional[Dict[str, Any]] = None, name: str = "default") -> SkillLoader:
    return SkillLoader(config=config, name=name)


def load_skill_from_file(path: str) -> Optional[RuleSkill]:
    loader = SkillLoader()
    loaded = loader.load(path)
    return loaded[0].skill if loaded else None


def load_skills_from_directory(directory: str) -> List[RuleSkill]:
    loader = SkillLoader()
    loaded = loader.load_from_directory(directory)
    return [ls.skill for ls in loaded]


from collections import defaultdict
