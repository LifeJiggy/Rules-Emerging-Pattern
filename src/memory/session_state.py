"""Session-level state tracking with TTL, expiry, persistence across evaluations, and cleanup."""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class SessionStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    COMPLETED = "completed"
    SUSPENDED = "suspended"


@dataclass
class Session:
    session_id: str
    created_at: float = 0.0
    last_activity: float = 0.0
    expires_at: float = 0.0
    status: SessionStatus = SessionStatus.ACTIVE
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    access_count: int = 0
    ip_address: str = ""
    user_agent: str = ""
    tags: Set[str] = field(default_factory=set)


@dataclass
class SessionStateConfig:
    default_ttl: float = 3600.0
    max_sessions: int = 10000
    max_data_size_bytes: int = 1048576
    cleanup_interval: float = 120.0
    enable_auto_cleanup: bool = True
    track_ip: bool = False
    track_user_agent: bool = False
    enable_stats: bool = True
    max_data_keys: int = 1000
    extend_on_access: bool = True
    extend_amount: float = 3600.0


class SessionState:
    """Session-level state tracking with TTL, expiry, persistence, and cleanup."""

    def __init__(self, config: Optional[SessionStateConfig] = None) -> None:
        self._config = config or SessionStateConfig()
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()
        self._total_created: int = 0
        self._total_expired: int = 0
        self._total_cleaned: int = 0
        self._total_accesses: int = 0
        self._running = True
        if self._config.enable_auto_cleanup and self._config.cleanup_interval > 0:
            self._start_cleanup_thread()

    def _start_cleanup_thread(self) -> None:
        def _loop() -> None:
            while self._running:
                time.sleep(self._config.cleanup_interval)
                try:
                    self.cleanup_expired()
                except Exception as exc:
                    logger.error("Cleanup error: %s", exc)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False

    def _is_expired(self, session: Session) -> bool:
        if session.expires_at <= 0:
            return False
        return time.time() >= session.expires_at

    def _get_ttl(self, ttl: Optional[float]) -> float:
        return ttl if ttl is not None else self._config.default_ttl

    def _enforce_max_sessions(self) -> None:
        if len(self._sessions) > self._config.max_sessions:
            excess = len(self._sessions) - self._config.max_sessions
            sorted_sessions = sorted(
                self._sessions.values(),
                key=lambda s: s.last_activity,
            )
            for s in sorted_sessions[:excess]:
                del self._sessions[s.session_id]
                self._total_expired += 1

    def create(
        self,
        session_id: Optional[str] = None,
        ttl: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        sid = session_id or str(uuid.uuid4())
        now = time.time()
        effective_ttl = self._get_ttl(ttl)
        expires_at = now + effective_ttl if effective_ttl > 0 else 0.0
        session = Session(
            session_id=sid,
            created_at=now,
            last_activity=now,
            expires_at=expires_at,
            status=SessionStatus.ACTIVE,
            data={},
            metadata=metadata or {},
            access_count=0,
            ip_address=ip_address if self._config.track_ip else "",
            user_agent=user_agent if self._config.track_user_agent else "",
            tags=set(tags or []),
        )
        with self._lock:
            if sid in self._sessions:
                raise ValueError(f"Session {sid} already exists")
            self._sessions[sid] = session
            self._total_created += 1
            self._enforce_max_sessions()
        logger.debug("Created session %s (TTL=%ds)", sid, effective_ttl)
        return sid

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                session.status = SessionStatus.EXPIRED
                del self._sessions[session_id]
                self._total_expired += 1
                return None
            now = time.time()
            session.last_activity = now
            session.access_count += 1
            self._total_accesses += 1
            if self._config.extend_on_access and self._config.extend_amount > 0:
                session.expires_at = now + self._config.extend_amount
            return session

    def get_raw(self, session_id: str) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                session.status = SessionStatus.EXPIRED
                del self._sessions[session_id]
                self._total_expired += 1
                return None
            return session

    def get_data(self, session_id: str) -> Dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {}
        return dict(session.data)

    def set_data(self, session_id: str, key: str, value: Any) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                del self._sessions[session_id]
                self._total_expired += 1
                return False
            if len(session.data) >= self._config.max_data_keys and key not in session.data:
                return False
            session.data[key] = value
            session.last_activity = time.time()
            return True

    def set_data_many(self, session_id: str, data: Dict[str, Any]) -> int:
        count = 0
        for key, value in data.items():
            if self.set_data(session_id, key, value):
                count += 1
            else:
                break
        return count

    def get_data_key(self, session_id: str, key: str) -> Optional[Any]:
        data = self.get_data(session_id)
        return data.get(key)

    def delete_data(self, session_id: str, key: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if key not in session.data:
                return False
            del session.data[key]
            session.last_activity = time.time()
            return True

    def clear_data(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.data.clear()
            session.last_activity = time.time()
            return True

    def exists(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                del self._sessions[session_id]
                self._total_expired += 1
                return False
            return True

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                del self._sessions[session_id]
                self._total_expired += 1
                return False
            return session.status == SessionStatus.ACTIVE

    def set_status(self, session_id: str, status: SessionStatus) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.status = status
            session.last_activity = time.time()
            return True

    def complete(self, session_id: str) -> bool:
        return self.set_status(session_id, SessionStatus.COMPLETED)

    def suspend(self, session_id: str) -> bool:
        return self.set_status(session_id, SessionStatus.SUSPENDED)

    def reactivate(self, session_id: str) -> bool:
        return self.set_status(session_id, SessionStatus.ACTIVE)

    def refresh_ttl(self, session_id: str, ttl: Optional[float] = None) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                del self._sessions[session_id]
                self._total_expired += 1
                return False
            effective_ttl = self._get_ttl(ttl)
            session.expires_at = time.time() + effective_ttl
            session.last_activity = time.time()
            return True

    def touch(self, session_id: str) -> bool:
        return self.refresh_ttl(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            self._total_expired += 1
            return True

    def delete_many(self, session_ids: List[str]) -> int:
        count = 0
        for sid in session_ids:
            if self.delete(sid):
                count += 1
        return count

    def clear(self) -> int:
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            self._total_expired += count
            logger.info("Cleared all sessions (%d)", count)
            return count

    def delete_by_status(self, status: SessionStatus) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._sessions.items() if s.status == status]
            for sid in to_remove:
                del self._sessions[sid]
                self._total_expired += 1
            return len(to_remove)

    def delete_by_tag(self, tag: str) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._sessions.items() if tag in s.tags]
            for sid in to_remove:
                del self._sessions[sid]
                self._total_expired += 1
            return len(to_remove)

    def delete_by_metadata(self, key: str, value: Any) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._sessions.items() if s.metadata.get(key) == value]
            for sid in to_remove:
                del self._sessions[sid]
                self._total_expired += 1
            return len(to_remove)

    def delete_inactive_since(self, cutoff: float) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._sessions.items() if s.last_activity < cutoff]
            for sid in to_remove:
                del self._sessions[sid]
                self._total_expired += 1
            return len(to_remove)

    def cleanup_expired(self) -> int:
        now = time.time()
        count = 0
        with self._lock:
            to_remove = [
                sid for sid, s in self._sessions.items()
                if s.expires_at > 0 and now >= s.expires_at
            ]
            for sid in to_remove:
                self._sessions[sid].status = SessionStatus.EXPIRED
                del self._sessions[sid]
                self._total_expired += 1
                count += 1
            self._total_cleaned += count
        if count > 0:
            logger.debug("Cleaned %d expired sessions", count)
        return count

    def add_tag(self, session_id: str, tag: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.tags.add(tag)
            return True

    def remove_tag(self, session_id: str, tag: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.tags.discard(tag)
            return True

    def has_tag(self, session_id: str, tag: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            return tag in session.tags

    def get_tags(self, session_id: str) -> Set[str]:
        with self._lock:
            session = self._sessions.get(session_id)
            return set(session.tags) if session else set()

    def set_metadata(self, session_id: str, key: str, value: Any) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.metadata[key] = value
            return True

    def set_metadata_many(self, session_id: str, metadata: Dict[str, Any]) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.metadata.update(metadata)
            return True

    def get_metadata(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            return dict(session.metadata) if session else {}

    def get_metadata_key(self, session_id: str, key: str) -> Optional[Any]:
        metadata = self.get_metadata(session_id)
        return metadata.get(key)

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_raw(session_id)
        if session is None:
            return None
        now = time.time()
        return {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "expires_at": session.expires_at,
            "status": session.status.value,
            "access_count": session.access_count,
            "data_size": len(str(session.data)),
            "data_keys": len(session.data),
            "tags": list(session.tags),
            "age_seconds": round(now - session.created_at, 2),
            "idle_seconds": round(now - session.last_activity, 2),
            "ttl_remaining": round(max(0, session.expires_at - now), 2) if session.expires_at > 0 else -1,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
        }

    def list_sessions(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())

    def list_active_sessions(self) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items() if s.status == SessionStatus.ACTIVE]

    def list_sessions_by_status(self, status: SessionStatus) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items() if s.status == status]

    def list_sessions_by_tag(self, tag: str) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items() if tag in s.tags]

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def count_by_status(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for s in self._sessions.values():
                status_name = s.status.value
                counts[status_name] = counts.get(status_name, 0) + 1
            return counts

    def count_active(self) -> int:
        return len(self.list_active_sessions())

    def count_by_tag(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for s in self._sessions.values():
                for tag in s.tags:
                    counts[tag] = counts.get(tag, 0) + 1
            return counts

    def get_expired_sessions(self) -> List[str]:
        now = time.time()
        with self._lock:
            return [
                sid for sid, s in self._sessions.items()
                if s.expires_at > 0 and now >= s.expires_at
            ]

    def get_inactive_sessions(self, idle_seconds: float = 3600.0) -> List[str]:
        cutoff = time.time() - idle_seconds
        with self._lock:
            return [sid for sid, s in self._sessions.items() if s.last_activity < cutoff]

    def get_oldest_sessions(self, n: int = 10) -> List[Tuple[str, float]]:
        with self._lock:
            items = [(sid, s.created_at) for sid, s in self._sessions.items()]
            items.sort(key=lambda x: x[1])
            return items[:n]

    def get_most_active_sessions(self, n: int = 10) -> List[Tuple[str, int]]:
        with self._lock:
            items = [(sid, s.access_count) for sid, s in self._sessions.items()]
            items.sort(key=lambda x: x[1], reverse=True)
            return items[:n]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            status_counts = self.count_by_status()
            now = time.time()
            avg_age = 0.0
            avg_idle = 0.0
            avg_ttl = 0.0
            if self._sessions:
                ages = [now - s.created_at for s in self._sessions.values()]
                idles = [now - s.last_activity for s in self._sessions.values()]
                ttls = [max(0, s.expires_at - now) for s in self._sessions.values() if s.expires_at > 0]
                avg_age = round(sum(ages) / len(ages), 2)
                avg_idle = round(sum(idles) / len(idles), 2)
                avg_ttl = round(sum(ttls) / len(ttls), 2) if ttls else -1
            return {
                "total_sessions": len(self._sessions),
                "max_sessions": self._config.max_sessions,
                "default_ttl": self._config.default_ttl,
                "total_created": self._total_created,
                "total_expired": self._total_expired,
                "total_cleaned": self._total_cleaned,
                "total_accesses": self._total_accesses,
                "status_distribution": status_counts,
                "avg_age_seconds": avg_age,
                "avg_idle_seconds": avg_idle,
                "avg_ttl_remaining": avg_ttl,
                "cleanup_interval": self._config.cleanup_interval,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._total_created = 0
            self._total_expired = 0
            self._total_cleaned = 0
            self._total_accesses = 0

    def export_sessions(self) -> Dict[str, Any]:
        with self._lock:
            return {
                sid: {
                    "created_at": s.created_at,
                    "last_activity": s.last_activity,
                    "expires_at": s.expires_at,
                    "status": s.status.value,
                    "data": dict(s.data),
                    "metadata": dict(s.metadata),
                    "access_count": s.access_count,
                    "tags": list(s.tags),
                }
                for sid, s in self._sessions.items()
            }

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        info = self.get_session_info(session_id)
        if info is None:
            return None
        data = self.get_data(session_id)
        info["data"] = data
        return info

    def import_sessions(self, data: Dict[str, Any], reset: bool = False) -> int:
        if reset:
            self.clear()
        count = 0
        for sid, info in data.items():
            if sid in self._sessions:
                continue
            now = time.time()
            session = Session(
                session_id=sid,
                created_at=info.get("created_at", now),
                last_activity=info.get("last_activity", now),
                expires_at=info.get("expires_at", now + self._config.default_ttl),
                status=SessionStatus(info.get("status", "active")),
                data=info.get("data", {}),
                metadata=info.get("metadata", {}),
                access_count=info.get("access_count", 0),
                tags=set(info.get("tags", [])),
            )
            with self._lock:
                self._sessions[sid] = session
                self._total_created += 1
                count += 1
        return count

    def snapshot(self) -> Dict[str, Any]:
        stats = self.get_stats()
        sessions = self.list_sessions()
        return {
            "stats": stats,
            "sessions": sessions,
            "active_count": self.count_active(),
        }

    def get_config(self) -> SessionStateConfig:
        return self._config

    def update_config(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)

    def update_session_data(self, session_id: str, data: Dict[str, Any]) -> bool:
        return self.set_data_many(session_id, data) > 0

    def get_or_create(self, session_id: Optional[str] = None, ttl: Optional[float] = None) -> str:
        if session_id and self.exists(session_id):
            self.touch(session_id)
            return session_id
        return self.create(session_id=session_id, ttl=ttl)

    def get_or_create_data(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        sid = self.get_or_create(session_id)
        return self.get_data(sid)

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, session_id: str) -> bool:
        return self.exists(session_id)

    def __getitem__(self, session_id: str) -> Dict[str, Any]:
        data = self.get_data(session_id)
        if not data and session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")
        return data

    def __setitem__(self, session_id: str, data: Dict[str, Any]) -> None:
        self.update_session_data(session_id, data)

    def __delitem__(self, session_id: str) -> None:
        if not self.delete(session_id):
            raise KeyError(f"Session {session_id} not found")

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"SessionState(sessions={stats['total_sessions']}/{stats['max_sessions']}, "
            f"status={stats['status_distribution']}, "
            f"created={stats['total_created']}, "
            f"expired={stats['total_expired']})"
        )

    def list_session_ids_by_data_key(self, key: str) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items() if key in s.data]

    def list_session_ids_by_data_value(self, key: str, value: Any) -> List[str]:
        with self._lock:
            return [sid for sid, s in self._sessions.items() if s.data.get(key) == value]

    def count_sessions_with_data_key(self, key: str) -> int:
        return len(self.list_session_ids_by_data_key(key))

    def get_all_data_keys(self) -> Set[str]:
        with self._lock:
            keys: Set[str] = set()
            for s in self._sessions.values():
                keys.update(s.data.keys())
            return keys

    def get_all_metadata_keys(self) -> Set[str]:
        with self._lock:
            keys: Set[str] = set()
            for s in self._sessions.values():
                keys.update(s.metadata.keys())
            return keys

    def batch_refresh_ttl(self, ttl: Optional[float] = None) -> int:
        count = 0
        for sid in self.list_active_sessions():
            if self.refresh_ttl(sid, ttl):
                count += 1
        return count

    def batch_delete_by_status(self, status: SessionStatus) -> int:
        return self.delete_by_status(status)

    def get_average_session_duration(self) -> float:
        with self._lock:
            durations = [
                s.last_activity - s.created_at
                for s in self._sessions.values()
            ]
            if not durations:
                return 0.0
            return round(sum(durations) / len(durations), 2)

    def get_session_count_by_ip(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for s in self._sessions.values():
                if s.ip_address:
                    counts[s.ip_address] = counts.get(s.ip_address, 0) + 1
            return counts

    def get_data_size_estimate(self, session_id: str) -> int:
        data = self.get_data(session_id)
        return len(str(data).encode("utf-8")) if data else 0

    def find_sessions_with_expired_data(self) -> List[str]:
        with self._lock:
            now = time.time()
            return [sid for sid, s in self._sessions.items() if s.expires_at > 0 and now >= s.expires_at]

    def is_suspended(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return session is not None and session.status == SessionStatus.SUSPENDED

    def is_completed(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return session is not None and session.status == SessionStatus.COMPLETED