"""Session-scoped context memory with TTL, merging, prioritization, and compaction."""

import copy
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MergeStrategy(Enum):
    OVERWRITE = "overwrite"
    KEEP_OLDEST = "keep_oldest"
    KEEP_NEWEST = "keep_newest"
    MERGE_DICT = "merge_dict"


class Priority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ContextEntry:
    key: str
    value: Any
    session_id: str
    priority: Priority = Priority.NORMAL
    created_at: float = 0.0
    expires_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    source: str = ""


@dataclass
class SessionContext:
    session_id: str
    entries: Dict[str, ContextEntry] = field(default_factory=dict)
    created_at: float = 0.0
    last_activity: float = 0.0
    entry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextMemoryConfig:
    max_entries_per_session: int = 1000
    max_sessions: int = 100
    default_ttl: float = 3600.0
    merge_strategy: MergeStrategy = MergeStrategy.KEEP_NEWEST
    enable_compaction: bool = True
    compaction_interval: float = 300.0
    compaction_threshold: float = 0.8
    max_memory_entries: int = 50000
    track_access_stats: bool = True
    auto_prune: bool = True
    prune_interval: float = 120.0


class ContextMemory:
    """Session-scoped context memory with TTL, merging, prioritization, and compaction."""

    def __init__(self, config: Optional[ContextMemoryConfig] = None) -> None:
        self._config = config or ContextMemoryConfig()
        self._sessions: Dict[str, SessionContext] = {}
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._total_stores: int = 0
        self._total_deletes: int = 0
        self._compaction_count: int = 0
        self._prune_count: int = 0
        self._running = True
        if self._config.auto_prune and self._config.prune_interval > 0:
            self._start_prune_thread()
        if self._config.enable_compaction and self._config.compaction_interval > 0:
            self._start_compaction_thread()

    def _start_prune_thread(self) -> None:
        def _loop() -> None:
            while self._running:
                time.sleep(self._config.prune_interval)
                try:
                    self.prune_expired()
                except Exception as exc:
                    logger.error("Prune error: %s", exc)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()

    def _start_compaction_thread(self) -> None:
        def _loop() -> None:
            while self._running:
                time.sleep(self._config.compaction_interval)
                try:
                    self.compact()
                except Exception as exc:
                    logger.error("Compaction error: %s", exc)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False

    def _get_ttl(self, ttl: Optional[float]) -> float:
        return ttl if ttl is not None else self._config.default_ttl

    def _is_expired(self, entry: ContextEntry) -> bool:
        if entry.expires_at <= 0:
            return False
        return time.time() >= entry.expires_at

    def _enforce_session_limit(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if len(session.entries) > self._config.max_entries_per_session:
            sorted_entries = sorted(
                session.entries.values(),
                key=lambda e: (e.priority.value, e.last_accessed),
            )
            to_remove = sorted_entries[: (len(sorted_entries) - self._config.max_entries_per_session)]
            for entry in to_remove:
                del session.entries[entry.key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)

    def _enforce_session_count(self) -> None:
        if len(self._sessions) > self._config.max_sessions:
            sorted_sessions = sorted(
                self._sessions.values(),
                key=lambda s: s.last_activity,
            )
            to_remove = sorted_sessions[: (len(sorted_sessions) - self._config.max_sessions)]
            for session in to_remove:
                del self._sessions[session.session_id]

    def _enforce_total_entries(self) -> None:
        total = sum(len(s.entries) for s in self._sessions.values())
        if total > self._config.max_memory_entries:
            excess = total - self._config.max_memory_entries
            removed = 0
            for session in sorted(self._sessions.values(), key=lambda s: s.last_activity):
                if removed >= excess:
                    break
                for key in list(session.entries.keys()):
                    if removed >= excess:
                        break
                    del session.entries[key]
                    session.entry_count = len(session.entries)
                    self._total_deletes += 1
                    removed += 1

    def _merge_values(self, existing: Any, incoming: Any, strategy: MergeStrategy) -> Any:
        if strategy == MergeStrategy.OVERWRITE:
            return incoming
        if strategy == MergeStrategy.KEEP_OLDEST:
            return existing
        if strategy == MergeStrategy.KEEP_NEWEST:
            return incoming
        if strategy == MergeStrategy.MERGE_DICT:
            if isinstance(existing, dict) and isinstance(incoming, dict):
                merged = copy.deepcopy(existing)
                merged.update(incoming)
                return merged
            return incoming
        return incoming

    def store(
        self,
        session_id: str,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        priority: Priority = Priority.NORMAL,
        source: str = "",
    ) -> None:
        now = time.time()
        effective_ttl = self._get_ttl(ttl)
        expires_at = now + effective_ttl if effective_ttl > 0 else 0.0
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(
                    session_id=session_id,
                    created_at=now,
                    last_activity=now,
                )
            session = self._sessions[session_id]
            existing = session.entries.get(key)
            if existing is not None:
                merged_value = self._merge_values(existing.value, value, self._config.merge_strategy)
                existing.value = merged_value
                existing.expires_at = expires_at
                existing.last_accessed = now
                existing.priority = priority
                existing.source = source or existing.source
                if self._config.track_access_stats:
                    existing.access_count += 1
            else:
                entry = ContextEntry(
                    key=key,
                    value=value,
                    session_id=session_id,
                    priority=priority,
                    created_at=now,
                    expires_at=expires_at,
                    last_accessed=now,
                    source=source,
                )
                session.entries[key] = entry
                session.entry_count = len(session.entries)
            session.last_activity = now
            self._total_stores += 1
            self._enforce_session_limit(session_id)
            self._enforce_session_count()
            self._enforce_total_entries()

    def store_many(
        self,
        session_id: str,
        entries: Dict[str, Any],
        ttl: Optional[float] = None,
        priority: Priority = Priority.NORMAL,
        source: str = "",
    ) -> int:
        count = 0
        for key, value in entries.items():
            self.store(session_id, key, value, ttl=ttl, priority=priority, source=source)
            count += 1
        return count

    def retrieve(self, session_id: str, key: str) -> Optional[Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                self._misses += 1
                return None
            entry = session.entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._is_expired(entry):
                del session.entries[key]
                session.entry_count = len(session.entries)
                self._total_deletes += 1
                self._misses += 1
                return None
            if self._config.track_access_stats:
                entry.last_accessed = time.time()
                entry.access_count += 1
            session.last_activity = time.time()
            self._hits += 1
            return entry.value

    def retrieve_entry(self, session_id: str, key: str) -> Optional[ContextEntry]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                self._misses += 1
                return None
            entry = session.entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._is_expired(entry):
                del session.entries[key]
                session.entry_count = len(session.entries)
                self._total_deletes += 1
                self._misses += 1
                return None
            if self._config.track_access_stats:
                entry.last_accessed = time.time()
                entry.access_count += 1
            session.last_activity = time.time()
            self._hits += 1
            return entry

    def retrieve_all(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            result: Dict[str, Any] = {}
            now = time.time()
            to_delete: List[str] = []
            for key, entry in session.entries.items():
                if self._is_expired(entry):
                    to_delete.append(key)
                    continue
                result[key] = entry.value
                if self._config.track_access_stats:
                    entry.last_accessed = now
                    entry.access_count += 1
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            if result:
                self._hits += len(result)
            if to_delete:
                self._misses += len(to_delete)
            session.last_activity = now
            return result

    def retrieve_by_priority(self, session_id: str, min_priority: Priority = Priority.NORMAL) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            result: Dict[str, Any] = {}
            now = time.time()
            to_delete: List[str] = []
            for key, entry in session.entries.items():
                if entry.priority.value < min_priority.value:
                    continue
                if self._is_expired(entry):
                    to_delete.append(key)
                    continue
                result[key] = entry.value
                if self._config.track_access_stats:
                    entry.last_accessed = now
                    entry.access_count += 1
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            session.last_activity = now
            return result

    def retrieve_by_source(self, session_id: str, source: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            result: Dict[str, Any] = {}
            now = time.time()
            to_delete: List[str] = []
            for key, entry in session.entries.items():
                if entry.source != source:
                    continue
                if self._is_expired(entry):
                    to_delete.append(key)
                    continue
                result[key] = entry.value
                if self._config.track_access_stats:
                    entry.last_accessed = now
                    entry.access_count += 1
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            session.last_activity = now
            return result

    def retrieve_range(self, session_id: str, keys: List[str]) -> Dict[str, Optional[Any]]:
        result: Dict[str, Optional[Any]] = {}
        for key in keys:
            result[key] = self.retrieve(session_id, key)
        return result

    def delete(self, session_id: str, key: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if key not in session.entries:
                return False
            del session.entries[key]
            session.entry_count = len(session.entries)
            self._total_deletes += 1
            return True

    def delete_many(self, session_id: str, keys: List[str]) -> int:
        count = 0
        for key in keys:
            if self.delete(session_id, key):
                count += 1
        return count

    def delete_by_prefix(self, session_id: str, prefix: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0
            to_delete = [k for k in session.entries if k.startswith(prefix)]
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            return len(to_delete)

    def delete_by_source(self, session_id: str, source: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0
            to_delete = [k for k, e in session.entries.items() if e.source == source]
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            return len(to_delete)

    def delete_by_priority(self, session_id: str, max_priority: Priority) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0
            to_delete = [k for k, e in session.entries.items() if e.priority.value <= max_priority.value]
            for key in to_delete:
                del session.entries[key]
                self._total_deletes += 1
            session.entry_count = len(session.entries)
            return len(to_delete)

    def clear_session(self, session_id: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0
            count = len(session.entries)
            session.entries.clear()
            session.entry_count = 0
            session.last_activity = time.time()
            self._total_deletes += count
            return count

    def clear(self) -> int:
        with self._lock:
            count = sum(len(s.entries) for s in self._sessions.values())
            self._sessions.clear()
            self._total_deletes += count
            logger.info("Cleared all context memory (%d entries)", count)
            return count

    def has_key(self, session_id: str, key: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            entry = session.entries.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                del session.entries[key]
                session.entry_count = len(session.entries)
                self._total_deletes += 1
                return False
            return True

    def list_sessions(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())

    def list_keys(self, session_id: str) -> List[str]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            return [
                k for k, e in session.entries.items()
                if not self._is_expired(e)
            ]

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return {
                "session_id": session.session_id,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "entry_count": session.entry_count,
                "metadata": session.metadata,
                "age_seconds": round(time.time() - session.created_at, 2),
                "idle_seconds": round(time.time() - session.last_activity, 2),
            }

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            return dict(session.metadata)

    def set_session_metadata(self, session_id: str, metadata: Dict[str, Any]) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(
                    session_id=session_id,
                    created_at=time.time(),
                    last_activity=time.time(),
                )
            self._sessions[session_id].metadata.update(metadata)

    def update_session_metadata(self, session_id: str, **kwargs: Any) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(
                    session_id=session_id,
                    created_at=time.time(),
                    last_activity=time.time(),
                )
            self._sessions[session_id].metadata.update(kwargs)

    def remove_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._sessions:
                return False
            count = len(self._sessions[session_id].entries)
            del self._sessions[session_id]
            self._total_deletes += count
            return True

    def prune_expired(self) -> int:
        now = time.time()
        total_removed = 0
        with self._lock:
            expired_sessions: List[str] = []
            for sid, session in self._sessions.items():
                expired_keys = [k for k, e in session.entries.items() if e.expires_at > 0 and now >= e.expires_at]
                for key in expired_keys:
                    del session.entries[key]
                    self._total_deletes += 1
                session.entry_count = len(session.entries)
                total_removed += len(expired_keys)
                if session.entry_count == 0:
                    expired_sessions.append(sid)
            for sid in expired_sessions:
                del self._sessions[sid]
            self._prune_count += total_removed
        if total_removed > 0:
            logger.debug("Pruned %d expired entries", total_removed)
        return total_removed

    def compact(self) -> Dict[str, Any]:
        with self._lock:
            total_before = sum(len(s.entries) for s in self._sessions.values())
            for session in list(self._sessions.values()):
                expired_keys = [
                    k for k, e in session.entries.items()
                    if e.expires_at > 0 and time.time() >= e.expires_at
                ]
                for key in expired_keys:
                    del session.entries[key]
                    self._total_deletes += 1
                session.entry_count = len(session.entries)
            self._compact_sessions()
            total_after = sum(len(s.entries) for s in self._sessions.values())
            removed = total_before - total_after
            self._compaction_count += 1
            return {
                "entries_before": total_before,
                "entries_after": total_after,
                "removed": removed,
                "sessions": len(self._sessions),
            }

    def _compact_sessions(self) -> None:
        empty_sessions = [sid for sid, s in self._sessions.items() if s.entry_count == 0]
        for sid in empty_sessions:
            del self._sessions[sid]

    def merge_contexts(self, target_session: str, source_session: str, strategy: Optional[MergeStrategy] = None) -> int:
        merge_strat = strategy or self._config.merge_strategy
        with self._lock:
            source = self._sessions.get(source_session)
            if source is None:
                return 0
            if target_session not in self._sessions:
                self._sessions[target_session] = SessionContext(
                    session_id=target_session,
                    created_at=time.time(),
                    last_activity=time.time(),
                )
            target = self._sessions[target_session]
            count = 0
            for key, entry in source.entries.items():
                existing = target.entries.get(key)
                if existing is not None:
                    merged_val = self._merge_values(existing.value, entry.value, merge_strat)
                    if merged_val is not None:
                        existing.value = merged_val
                else:
                    new_entry = ContextEntry(
                        key=entry.key,
                        value=entry.value,
                        session_id=target_session,
                        priority=entry.priority,
                        created_at=entry.created_at,
                        expires_at=entry.expires_at,
                        last_accessed=time.time(),
                        source=entry.source,
                    )
                    target.entries[key] = new_entry
                    target.entry_count = len(target.entries)
                count += 1
            target.last_activity = time.time()
            self._enforce_session_limit(target_session)
            return count

    def prioritize(self, session_id: str, key: str, priority: Priority) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            entry = session.entries.get(key)
            if entry is None:
                return False
            entry.priority = priority
            return True

    def get_priority_distribution(self, session_id: str) -> Dict[str, int]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            dist: Dict[str, int] = {}
            for entry in session.entries.values():
                pname = entry.priority.name
                dist[pname] = dist.get(pname, 0) + 1
            return dist

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_entries = sum(len(s.entries) for s in self._sessions.values())
            total = self._hits + self._misses
            hit_ratio = self._hits / total if total > 0 else 0.0
            active_sessions = sum(1 for s in self._sessions.values() if s.entry_count > 0)
            return {
                "active_sessions": active_sessions,
                "total_sessions": len(self._sessions),
                "total_entries": total_entries,
                "max_entries_per_session": self._config.max_entries_per_session,
                "max_sessions": self._config.max_sessions,
                "max_memory_entries": self._config.max_memory_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 4),
                "total_stores": self._total_stores,
                "total_deletes": self._total_deletes,
                "compaction_count": self._compaction_count,
                "prune_count": self._prune_count,
                "default_ttl": self._config.default_ttl,
                "merge_strategy": self._config.merge_strategy.value,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._total_stores = 0
            self._total_deletes = 0
            self._compaction_count = 0
            self._prune_count = 0

    def get_hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def get_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def get_entry_count(self) -> int:
        with self._lock:
            return sum(len(s.entries) for s in self._sessions.values())

    def get_entry_count_for_session(self, session_id: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.entry_count if session else 0

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return {
                "session_id": session.session_id,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "metadata": session.metadata,
                "entries": {
                    k: {
                        "value": e.value,
                        "priority": e.priority.name,
                        "created_at": e.created_at,
                        "expires_at": e.expires_at,
                        "access_count": e.access_count,
                        "source": e.source,
                    }
                    for k, e in session.entries.items()
                },
            }

    def import_session(self, data: Dict[str, Any], reset: bool = False) -> bool:
        session_id = data.get("session_id")
        if not session_id:
            return False
        if reset:
            self.clear_session(session_id)
        for key, entry_data in data.get("entries", {}).items():
            priority_name = entry_data.get("priority", "NORMAL")
            priority = Priority[priority_name] if priority_name in Priority.__members__ else Priority.NORMAL
            self.store(
                session_id,
                key,
                entry_data["value"],
                priority=priority,
                source=entry_data.get("source", ""),
            )
        metadata = data.get("metadata", {})
        if metadata:
            self.set_session_metadata(session_id, metadata)
        return True

    def snapshot(self) -> Dict[str, Any]:
        stats = self.get_stats()
        sessions = self.list_sessions()
        return {
            "stats": stats,
            "sessions": sessions,
            "total_entries": self.get_entry_count(),
        }

    def __len__(self) -> int:
        return self.get_entry_count()

    def __contains__(self, key: Tuple[str, str]) -> bool:
        session_id, entry_key = key
        return self.has_key(session_id, entry_key)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"ContextMemory(sessions={stats['active_sessions']}/{stats['total_sessions']}, "
            f"entries={stats['total_entries']}, "
            f"hit_ratio={stats['hit_ratio']})"
        )