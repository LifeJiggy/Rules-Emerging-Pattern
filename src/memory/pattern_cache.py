"""Thread-safe pattern cache with versioning, dependency tracking, and bulk loading."""

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Pattern

logger = logging.getLogger(__name__)


class PatternType(Enum):
    REGEX = "regex"
    GLOB = "glob"
    EXACT = "exact"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    CONTAINS = "contains"


@dataclass
class CompiledPattern:
    pattern_id: str
    pattern_str: str
    pattern_type: PatternType
    compiled: Optional[Pattern] = None
    version: int = 1
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    created_at: float = 0.0
    updated_at: float = 0.0
    last_used: float = 0.0
    use_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    compile_time_ms: float = 0.0


@dataclass
class PatternGroup:
    group_id: str
    pattern_ids: Set[str] = field(default_factory=set)
    description: str = ""
    created_at: float = 0.0


@dataclass
class PatternCacheConfig:
    max_patterns: int = 10000
    max_groups: int = 500
    default_ttl: float = 0.0
    track_usage: bool = True
    enable_dependency_tracking: bool = True
    auto_prune: bool = True
    prune_interval: float = 300.0
    max_pattern_length: int = 10000
    compile_timeout_ms: float = 5000.0
    enable_stats: bool = True


class PatternCache:
    """Pattern cache with versioning, dependency tracking, and bulk loading."""

    def __init__(self, config: Optional[PatternCacheConfig] = None) -> None:
        self._config = config or PatternCacheConfig()
        self._patterns: Dict[str, CompiledPattern] = {}
        self._groups: Dict[str, PatternGroup] = {}
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._total_compiles: int = 0
        self._compile_errors: int = 0
        self._total_invalidations: int = 0
        self._running = True
        if self._config.auto_prune and self._config.prune_interval > 0:
            self._start_prune_thread()

    def _start_prune_thread(self) -> None:
        def _loop() -> None:
            while self._running:
                time.sleep(self._config.prune_interval)
                try:
                    self.prune_unused()
                except Exception as exc:
                    logger.error("Prune error: %s", exc)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False

    def _compile_regex(self, pattern_str: str) -> Optional[Pattern]:
        try:
            start = time.time()
            compiled = re.compile(pattern_str)
            elapsed = (time.time() - start) * 1000
            if elapsed > self._config.compile_timeout_ms:
                logger.warning("Slow regex compile (%.2fms): %s", elapsed, pattern_str[:50])
            return compiled
        except re.error as exc:
            self._compile_errors += 1
            logger.error("Regex compile error for '%s': %s", pattern_str[:50], exc)
            return None

    def _compile_glob(self, pattern_str: str) -> Optional[Pattern]:
        regex_str = ""
        i = 0
        while i < len(pattern_str):
            c = pattern_str[i]
            if c == '*':
                regex_str += '.*'
            elif c == '?':
                regex_str += '.'
            elif c == '.':
                regex_str += '\\.'
            elif c == '[':
                regex_str += '['
            elif c == ']':
                regex_str += ']'
            elif c == '\\':
                regex_str += '\\\\'
            else:
                regex_str += re.escape(c)
            i += 1
        return self._compile_regex(f"^{regex_str}$")

    def _compile_pattern(self, pattern_str: str, pattern_type: PatternType) -> Optional[Pattern]:
        if len(pattern_str) > self._config.max_pattern_length:
            logger.error("Pattern too long (%d chars)", len(pattern_str))
            return None
        if pattern_type == PatternType.REGEX:
            return self._compile_regex(pattern_str)
        if pattern_type == PatternType.GLOB:
            return self._compile_glob(pattern_str)
        if pattern_type == PatternType.EXACT:
            return self._compile_regex(f"^{re.escape(pattern_str)}$")
        if pattern_type == PatternType.PREFIX:
            return self._compile_regex(f"^{re.escape(pattern_str)}")
        if pattern_type == PatternType.SUFFIX:
            return self._compile_regex(f"{re.escape(pattern_str)}$")
        if pattern_type == PatternType.CONTAINS:
            return self._compile_regex(re.escape(pattern_str))
        return None

    def _compute_pattern_hash(self, pattern_str: str, pattern_type: PatternType) -> str:
        raw = f"{pattern_type.value}:{pattern_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def compile(
        self,
        pattern_id: str,
        pattern_str: str,
        pattern_type: PatternType = PatternType.REGEX,
        metadata: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None,
    ) -> bool:
        start = time.time()
        compiled = self._compile_pattern(pattern_str, pattern_type)
        elapsed = (time.time() - start) * 1000
        if compiled is None:
            return False
        with self._lock:
            existing = self._patterns.get(pattern_id)
            if existing:
                existing.pattern_str = pattern_str
                existing.pattern_type = pattern_type
                existing.compiled = compiled
                existing.version += 1
                existing.updated_at = time.time()
                existing.compile_time_ms = elapsed
                existing.metadata = metadata or {}
                if dependencies and self._config.enable_dependency_tracking:
                    self._update_dependencies(pattern_id, set(dependencies))
            else:
                dep_set: Set[str] = set(dependencies or [])
                cp = CompiledPattern(
                    pattern_id=pattern_id,
                    pattern_str=pattern_str,
                    pattern_type=pattern_type,
                    compiled=compiled,
                    version=1,
                    dependencies=dep_set,
                    created_at=time.time(),
                    updated_at=time.time(),
                    compile_time_ms=elapsed,
                    metadata=metadata or {},
                )
                self._patterns[pattern_id] = cp
                if dependencies and self._config.enable_dependency_tracking:
                    for dep_id in dep_set:
                        if dep_id in self._patterns:
                            self._patterns[dep_id].dependents.add(pattern_id)
            self._total_compiles += 1
            self._enforce_max_patterns()
            return True

    def compile_many(
        self,
        patterns: Dict[str, Tuple[str, PatternType]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        count = 0
        for pattern_id, (pattern_str, pattern_type) in patterns.items():
            if self.compile(pattern_id, pattern_str, pattern_type, metadata=metadata):
                count += 1
        return count

    def _update_dependencies(self, pattern_id: str, new_deps: Set[str]) -> None:
        cp = self._patterns.get(pattern_id)
        if cp is None:
            return
        old_deps = cp.dependencies
        added = new_deps - old_deps
        removed = old_deps - new_deps
        for dep_id in removed:
            if dep_id in self._patterns:
                self._patterns[dep_id].dependents.discard(pattern_id)
        for dep_id in added:
            if dep_id in self._patterns:
                self._patterns[dep_id].dependents.add(pattern_id)
        cp.dependencies = new_deps

    def _enforce_max_patterns(self) -> None:
        if len(self._patterns) > self._config.max_patterns:
            excess = len(self._patterns) - self._config.max_patterns
            sorted_patterns = sorted(
                self._patterns.values(),
                key=lambda p: p.last_used,
            )
            for cp in sorted_patterns[:excess]:
                self._remove_pattern(cp.pattern_id)

    def _remove_pattern(self, pattern_id: str) -> None:
        cp = self._patterns.pop(pattern_id, None)
        if cp is None:
            return
        for dep_id in cp.dependencies:
            if dep_id in self._patterns:
                self._patterns[dep_id].dependents.discard(pattern_id)
        for dep_id in list(cp.dependents):
            if dep_id in self._patterns:
                self._patterns[dep_id].dependencies.discard(pattern_id)
        for group in self._groups.values():
            group.pattern_ids.discard(pattern_id)

    def get_pattern(self, pattern_id: str) -> Optional[CompiledPattern]:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            if cp is None:
                self._misses += 1
                return None
            if self._config.track_usage:
                cp.last_used = time.time()
                cp.use_count += 1
            self._hits += 1
            return cp

    def get_compiled(self, pattern_id: str) -> Optional[Pattern]:
        cp = self.get_pattern(pattern_id)
        return cp.compiled if cp else None

    def match(self, pattern_id: str, text: str) -> bool:
        cp = self.get_pattern(pattern_id)
        if cp is None or cp.compiled is None:
            return False
        return bool(cp.compiled.search(text))

    def match_many(self, pattern_ids: List[str], text: str) -> Dict[str, bool]:
        result: Dict[str, bool] = {}
        for pid in pattern_ids:
            result[pid] = self.match(pid, text)
        return result

    def match_any(self, pattern_ids: List[str], text: str) -> bool:
        for pid in pattern_ids:
            if self.match(pid, text):
                return True
        return False

    def match_all(self, pattern_ids: List[str], text: str) -> bool:
        for pid in pattern_ids:
            if not self.match(pid, text):
                return False
        return True

    def find_matching(self, text: str, pattern_ids: Optional[List[str]] = None) -> List[str]:
        with self._lock:
            targets = pattern_ids or list(self._patterns.keys())
            result: List[str] = []
            for pid in targets:
                cp = self._patterns.get(pid)
                if cp and cp.compiled and cp.compiled.search(text):
                    result.append(pid)
                    if self._config.track_usage:
                        cp.last_used = time.time()
                        cp.use_count += 1
            self._hits += len(result)
            self._misses += len(targets) - len(result)
            return result

    def delete_pattern(self, pattern_id: str) -> bool:
        with self._lock:
            if pattern_id not in self._patterns:
                return False
            self._remove_pattern(pattern_id)
            return True

    def delete_patterns(self, pattern_ids: List[str]) -> int:
        count = 0
        for pid in pattern_ids:
            if self.delete_pattern(pid):
                count += 1
        return count

    def clear(self) -> int:
        with self._lock:
            count = len(self._patterns)
            self._patterns.clear()
            self._groups.clear()
            self._total_invalidations += count
            return count

    def invalidate(self, pattern_id: str) -> bool:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            if cp is None:
                return False
            if self._config.enable_dependency_tracking:
                dependents = list(cp.dependents)
                for dep_id in dependents:
                    self.invalidate(dep_id)
            self._remove_pattern(pattern_id)
            self._total_invalidations += 1
            return True

    def invalidate_many(self, pattern_ids: List[str]) -> int:
        count = 0
        for pid in pattern_ids:
            if self.invalidate(pid):
                count += 1
        return count

    def invalidate_by_group(self, group_id: str) -> int:
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                return 0
            pattern_ids = list(group.pattern_ids)
            for pid in pattern_ids:
                self.invalidate(pid)
            return len(pattern_ids)

    def invalidate_by_prefix(self, prefix: str) -> int:
        with self._lock:
            to_remove = [pid for pid in self._patterns if pid.startswith(prefix)]
            for pid in to_remove:
                self._remove_pattern(pid)
                self._total_invalidations += 1
            return len(to_remove)

    def invalidate_by_metadata(self, key: str, value: Any) -> int:
        with self._lock:
            to_remove = [
                pid for pid, cp in self._patterns.items()
                if cp.metadata.get(key) == value
            ]
            for pid in to_remove:
                self._remove_pattern(pid)
                self._total_invalidations += 1
            return len(to_remove)

    def recompile(self, pattern_id: str) -> bool:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            if cp is None:
                return False
            compiled = self._compile_pattern(cp.pattern_str, cp.pattern_type)
            if compiled is None:
                return False
            cp.compiled = compiled
            cp.version += 1
            cp.updated_at = time.time()
            return True

    def recompile_all(self) -> int:
        with self._lock:
            count = 0
            for pid in list(self._patterns.keys()):
                if self.recompile(pid):
                    count += 1
            return count

    def get_version(self, pattern_id: str) -> Optional[int]:
        cp = self.get_pattern(pattern_id)
        return cp.version if cp else None

    def has_changed(self, pattern_id: str, known_version: int) -> bool:
        cp = self.get_pattern(pattern_id)
        if cp is None:
            return True
        return cp.version != known_version

    def has_pattern(self, pattern_id: str) -> bool:
        with self._lock:
            return pattern_id in self._patterns

    def get_dependencies(self, pattern_id: str) -> Set[str]:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            return set(cp.dependencies) if cp else set()

    def get_dependents(self, pattern_id: str) -> Set[str]:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            return set(cp.dependents) if cp else set()

    def get_dependency_chain(self, pattern_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        visited = visited or set()
        if pattern_id in visited:
            return []
        visited.add(pattern_id)
        cp = self._patterns.get(pattern_id)
        if cp is None:
            return []
        chain: List[str] = []
        for dep_id in cp.dependencies:
            chain.append(dep_id)
            chain.extend(self.get_dependency_chain(dep_id, visited))
        return chain

    def get_dependent_chain(self, pattern_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        visited = visited or set()
        if pattern_id in visited:
            return []
        visited.add(pattern_id)
        cp = self._patterns.get(pattern_id)
        if cp is None:
            return []
        chain: List[str] = []
        for dep_id in cp.dependents:
            chain.append(dep_id)
            chain.extend(self.get_dependent_chain(dep_id, visited))
        return chain

    def create_group(self, group_id: str, description: str = "") -> bool:
        with self._lock:
            if group_id in self._groups:
                return False
            self._groups[group_id] = PatternGroup(
                group_id=group_id,
                description=description,
                created_at=time.time(),
            )
            return True

    def delete_group(self, group_id: str) -> bool:
        with self._lock:
            if group_id not in self._groups:
                return False
            del self._groups[group_id]
            return True

    def add_to_group(self, group_id: str, pattern_id: str) -> bool:
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                return False
            if pattern_id not in self._patterns:
                return False
            group.pattern_ids.add(pattern_id)
            return True

    def remove_from_group(self, group_id: str, pattern_id: str) -> bool:
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                return False
            group.pattern_ids.discard(pattern_id)
            return True

    def get_group_patterns(self, group_id: str) -> List[str]:
        with self._lock:
            group = self._groups.get(group_id)
            return list(group.pattern_ids) if group else []

    def list_groups(self) -> Dict[str, int]:
        with self._lock:
            return {gid: len(g.pattern_ids) for gid, g in self._groups.items()}

    def prune_unused(self, max_idle_seconds: float = 3600.0) -> int:
        now = time.time()
        with self._lock:
            to_remove = [
                pid for pid, cp in self._patterns.items()
                if cp.last_used > 0 and now - cp.last_used > max_idle_seconds
            ]
            for pid in to_remove:
                self._remove_pattern(pid)
            logger.debug("Pruned %d unused patterns", len(to_remove))
            return len(to_remove)

    def prune_by_age(self, max_age_seconds: float = 86400.0) -> int:
        now = time.time()
        with self._lock:
            to_remove = [
                pid for pid, cp in self._patterns.items()
                if now - cp.created_at > max_age_seconds
            ]
            for pid in to_remove:
                self._remove_pattern(pid)
            return len(to_remove)

    def bulk_load(self, patterns: Dict[str, Tuple[str, PatternType]]) -> int:
        count = 0
        for pattern_id, (pattern_str, pattern_type) in patterns.items():
            if self.compile(pattern_id, pattern_str, pattern_type):
                count += 1
        return count

    def bulk_load_from_dict(self, data: Dict[str, Dict[str, Any]]) -> int:
        count = 0
        for pattern_id, info in data.items():
            pattern_str = info.get("pattern", "")
            type_name = info.get("type", "regex")
            pattern_type = PatternType[type_name.upper()] if type_name.upper() in PatternType.__members__ else PatternType.REGEX
            metadata = info.get("metadata")
            deps = info.get("dependencies")
            if self.compile(pattern_id, pattern_str, pattern_type, metadata=metadata, dependencies=deps):
                count += 1
        return count

    def export_to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                pid: {
                    "pattern": cp.pattern_str,
                    "type": cp.pattern_type.value,
                    "version": cp.version,
                    "dependencies": list(cp.dependencies),
                    "dependents": list(cp.dependents),
                    "created_at": cp.created_at,
                    "updated_at": cp.updated_at,
                    "use_count": cp.use_count,
                    "metadata": cp.metadata,
                }
                for pid, cp in self._patterns.items()
            }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = self._hits / total if total > 0 else 0.0
            pattern_types: Dict[str, int] = {}
            for cp in self._patterns.values():
                pt = cp.pattern_type.value
                pattern_types[pt] = pattern_types.get(pt, 0) + 1
            return {
                "total_patterns": len(self._patterns),
                "max_patterns": self._config.max_patterns,
                "total_groups": len(self._groups),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 4),
                "total_compiles": self._total_compiles,
                "compile_errors": self._compile_errors,
                "total_invalidations": self._total_invalidations,
                "pattern_types": pattern_types,
                "patterns_with_deps": sum(1 for cp in self._patterns.values() if cp.dependencies),
                "patterns_with_dependents": sum(1 for cp in self._patterns.values() if cp.dependents),
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._total_compiles = 0
            self._compile_errors = 0
            self._total_invalidations = 0

    def list_patterns(self) -> List[str]:
        with self._lock:
            return list(self._patterns.keys())

    def list_patterns_by_type(self, pattern_type: PatternType) -> List[str]:
        with self._lock:
            return [pid for pid, cp in self._patterns.items() if cp.pattern_type == pattern_type]

    def get_most_used(self, n: int = 10) -> List[Tuple[str, int]]:
        with self._lock:
            items = [(pid, cp.use_count) for pid, cp in self._patterns.items()]
            items.sort(key=lambda x: x[1], reverse=True)
            return items[:n]

    def get_least_used(self, n: int = 10) -> List[Tuple[str, int]]:
        with self._lock:
            items = [(pid, cp.use_count) for pid, cp in self._patterns.items()]
            items.sort(key=lambda x: x[1])
            return items[:n]

    def validate_pattern(self, pattern_str: str, pattern_type: PatternType = PatternType.REGEX) -> bool:
        compiled = self._compile_pattern(pattern_str, pattern_type)
        return compiled is not None

    def validate_patterns(self, patterns: Dict[str, Tuple[str, PatternType]]) -> Dict[str, bool]:
        result: Dict[str, bool] = {}
        for pid, (pstr, ptype) in patterns.items():
            result[pid] = self.validate_pattern(pstr, ptype)
        return result

    def count_by_type(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for cp in self._patterns.values():
                pt = cp.pattern_type.value
                counts[pt] = counts.get(pt, 0) + 1
            return counts

    def get_pattern_info(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        cp = self.get_pattern(pattern_id)
        if cp is None:
            return None
        return {
            "pattern_id": cp.pattern_id,
            "pattern_str": cp.pattern_str,
            "pattern_type": cp.pattern_type.value,
            "version": cp.version,
            "dependencies": list(cp.dependencies),
            "dependents": list(cp.dependents),
            "created_at": cp.created_at,
            "updated_at": cp.updated_at,
            "last_used": cp.last_used,
            "use_count": cp.use_count,
            "compile_time_ms": cp.compile_time_ms,
            "metadata": cp.metadata,
        }

    def snapshot(self) -> Dict[str, Any]:
        stats = self.get_stats()
        return {
            "stats": stats,
            "patterns": self.list_patterns(),
            "groups": self.list_groups(),
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._patterns)

    def __contains__(self, pattern_id: str) -> bool:
        return self.has_pattern(pattern_id)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"PatternCache(patterns={stats['total_patterns']}/{stats['max_patterns']}, "
            f"hit_ratio={stats['hit_ratio']}, "
            f"groups={stats['total_groups']})"
        )

    def get_cache_health(self) -> Dict[str, Any]:
        stats = self.get_stats()
        return {
            "total_patterns": stats["total_patterns"],
            "usage_pct": round(stats["total_patterns"] / self._config.max_patterns * 100, 2) if self._config.max_patterns > 0 else 0,
            "compile_success_rate": round((1 - stats["compile_errors"] / max(1, stats["total_compiles"])) * 100, 2),
            "hit_ratio": stats["hit_ratio"],
            "group_count": stats["total_groups"],
        }

    def compile_if_not_exists(self, pattern_id: str, pattern_str: str, pattern_type: PatternType = PatternType.REGEX) -> bool:
        if self.has_pattern(pattern_id):
            return True
        return self.compile(pattern_id, pattern_str, pattern_type)

    def recompile_dependents(self, pattern_id: str) -> int:
        with self._lock:
            cp = self._patterns.get(pattern_id)
            if cp is None:
                return 0
            dependents = list(cp.dependents)
            count = 0
            for dep_id in dependents:
                if self.recompile(dep_id):
                    count += 1
            return count

    def find_patterns_by_source(self, source_key: str, source_value: Any) -> List[str]:
        with self._lock:
            return [
                pid for pid, cp in self._patterns.items()
                if cp.metadata.get(source_key) == source_value
            ]

    def copy_pattern(self, source_id: str, target_id: str) -> bool:
        with self._lock:
            cp = self._patterns.get(source_id)
            if cp is None:
                return False
            return self.compile(
                target_id,
                cp.pattern_str,
                cp.pattern_type,
                metadata=dict(cp.metadata),
                dependencies=list(cp.dependencies),
            )

    def rename_pattern(self, old_id: str, new_id: str) -> bool:
        with self._lock:
            cp = self._patterns.pop(old_id, None)
            if cp is None:
                return False
            cp.pattern_id = new_id
            self._patterns[new_id] = cp
            return True

    def stats_by_type(self) -> Dict[str, Any]:
        return self.count_by_type()