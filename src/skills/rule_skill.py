"""RuleSkill - Skill-based rule definitions with registration, versioning, dependencies, and execution context."""

import logging
import uuid
import hashlib
import json
import time
import copy
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)


class SkillCategory(Enum):
    TRANSFORM = auto()
    VALIDATE = auto()
    EXECUTE = auto()
    ANALYZE = auto()
    INFER = auto()
    FILTER = auto()
    AGGREGATE = auto()
    GENERATE = auto()
    CUSTOM = auto()


class SkillPriority(Enum):
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100
    CRITICAL = 1000


class SkillStatus(Enum):
    DRAFT = "draft"
    REGISTERED = "registered"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    ERROR = "error"


class SkillTrigger(Enum):
    MANUAL = "manual"
    EVENT = "event"
    SCHEDULE = "schedule"
    PIPELINE = "pipeline"
    CHAIN = "chain"
    CONDITION = "condition"


@dataclass
class SkillVersion:
    major: int = 1
    minor: int = 0
    patch: int = 0
    build: Optional[str] = None
    prerelease: Optional[str] = None

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base = f"{base}-{self.prerelease}"
        if self.build:
            base = f"{base}+{self.build}"
        return base

    @classmethod
    def parse(cls, version_str: str) -> "SkillVersion":
        parts = version_str.split("+")
        build = parts[1] if len(parts) > 1 else None
        prerelease_parts = parts[0].split("-")
        prerelease = prerelease_parts[1] if len(prerelease_parts) > 1 else None
        nums = prerelease_parts[0].split(".")
        major = int(nums[0]) if len(nums) > 0 else 1
        minor = int(nums[1]) if len(nums) > 1 else 0
        patch = int(nums[2]) if len(nums) > 2 else 0
        return cls(major=major, minor=minor, patch=patch, prerelease=prerelease, build=build)

    def compat(self, other: "SkillVersion", strategy: str = "major") -> bool:
        if strategy == "exact":
            return self == other
        if strategy == "major":
            return self.major == other.major
        if strategy == "minor":
            return self.major == other.major and self.minor == other.minor
        if strategy == "patch":
            return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SkillVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease, self.build) == (
            other.major, other.minor, other.patch, other.prerelease, other.build)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SkillVersion):
            return NotImplemented
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        if self.patch != other.patch:
            return self.patch < other.patch
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and other.prerelease:
            return self.prerelease < other.prerelease
        return False

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SkillVersion):
            return NotImplemented
        return self < other or self == other

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SkillVersion):
            return NotImplemented
        return not self <= other

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SkillVersion):
            return NotImplemented
        return not self < other

    def __hash__(self) -> int:
        return hash(str(self))


@dataclass
class SkillDependency:
    name: str
    version: Optional[SkillVersion] = None
    version_strategy: str = "major"
    optional: bool = False
    source: Optional[str] = None
    alias: Optional[str] = None

    def resolved(self, version: SkillVersion) -> bool:
        if self.version is None:
            return True
        return self.version.compat(version, self.version_strategy)

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class SkillInput:
    name: str
    type_hint: str = "Any"
    required: bool = True
    default: Any = None
    description: str = ""
    validators: List[Callable[[Any], bool]] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def validate(self, value: Any) -> bool:
        if self.required and value is None:
            logger.warning(f"Required input '{self.name}' is missing")
            return False
        if value is None and not self.required:
            return True
        for validator in self.validators:
            if not validator(value):
                logger.warning(f"Input '{self.name}' failed validation")
                return False
        return True


@dataclass
class SkillOutput:
    name: str
    type_hint: str = "Any"
    description: str = ""
    optional: bool = False


@dataclass
class SkillMetadata:
    author: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: SkillVersion = field(default_factory=SkillVersion)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    category: SkillCategory = SkillCategory.CUSTOM
    priority: SkillPriority = SkillPriority.NORMAL
    license: str = ""
    documentation_url: str = ""
    source_url: str = ""
    maintainers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "author": self.author,
            "description": self.description,
            "tags": self.tags,
            "version": str(self.version),
            "created": self.created,
            "updated": self.updated,
            "category": self.category.name,
            "priority": self.priority.name,
            "license": self.license,
            "documentation_url": self.documentation_url,
            "source_url": self.source_url,
            "maintainers": self.maintainers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        return cls(
            author=data.get("author", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            version=SkillVersion.parse(data.get("version", "1.0.0")),
            created=data.get("created", datetime.now(timezone.utc).isoformat()),
            updated=data.get("updated", datetime.now(timezone.utc).isoformat()),
            category=SkillCategory[data.get("category", "CUSTOM")],
            priority=SkillPriority[data.get("priority", "NORMAL")],
            license=data.get("license", ""),
            documentation_url=data.get("documentation_url", ""),
            source_url=data.get("source_url", ""),
            maintainers=data.get("maintainers", []),
        )


@dataclass
class ExecutionContext:
    skill_name: str
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    parent: Optional["ExecutionContext"] = None
    children: List["ExecutionContext"] = field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    retry_delay: float = 1.0

    def start(self) -> None:
        self.started_at = time.time()
        self.trace.append({
            "event": "start",
            "timestamp": self.started_at,
            "execution_id": self.execution_id,
        })

    def complete(self, outputs: Optional[Dict[str, Any]] = None) -> None:
        self.completed_at = time.time()
        if outputs:
            self.outputs.update(outputs)
        self.trace.append({
            "event": "complete",
            "timestamp": self.completed_at,
            "duration": self.completed_at - (self.started_at or self.completed_at),
        })

    def fail(self, error: str) -> None:
        self.error = error
        self.completed_at = time.time()
        self.trace.append({
            "event": "fail",
            "timestamp": self.completed_at,
            "error": error,
        })

    def elapsed(self) -> float:
        end = self.completed_at or time.time()
        start = self.started_at or end
        return end - start

    def child_context(self, name: str) -> "ExecutionContext":
        child = ExecutionContext(
            skill_name=name,
            parent=self,
            inputs=dict(self.inputs),
            config=dict(self.config),
            environment=dict(self.environment),
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            timeout=self.timeout,
        )
        self.children.append(child)
        return child

    def should_retry(self) -> bool:
        return self.retry_count < self.max_retries and self.error is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "execution_id": self.execution_id,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "state": self.state,
            "config": self.config,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "elapsed": self.elapsed(),
            "retry_count": self.retry_count,
            "trace": self.trace,
        }


class RuleSkill:
    def __init__(
        self,
        name: str,
        handler: Optional[Callable[..., Any]] = None,
        metadata: Optional[SkillMetadata] = None,
        inputs: Optional[List[SkillInput]] = None,
        outputs: Optional[List[SkillOutput]] = None,
        dependencies: Optional[List[SkillDependency]] = None,
        triggers: Optional[List[SkillTrigger]] = None,
        tags: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._name = name
        self._skill_id = str(uuid.uuid4())
        self._handler = handler
        self._metadata = metadata or SkillMetadata()
        self._inputs = inputs or []
        self._outputs = outputs or []
        self._dependencies = dependencies or []
        self._triggers = triggers or [SkillTrigger.MANUAL]
        self._tags = tags or []
        self._config = config or {}
        self._status = SkillStatus.DRAFT
        self._checksum = self._compute_checksum()
        self._registered_at: Optional[str] = None
        self._activated_at: Optional[str] = None
        self._deactivated_at: Optional[str] = None
        self._hooks: Dict[str, List[Callable[..., Any]]] = {
            "before_execute": [],
            "after_execute": [],
            "on_error": [],
            "on_activate": [],
            "on_deactivate": [],
            "on_register": [],
            "on_unregister": [],
        }
        self._middleware: List[Callable[..., Any]] = []
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: float = 300.0
        self._execution_count: int = 0
        self._error_count: int = 0
        self._total_elapsed: float = 0.0
        self._last_execution: Optional[float] = None
        self._context: Optional[ExecutionContext] = None
        self._aliases: List[str] = []
        self._groups: List[str] = []
        self._environments: List[str] = ["default"]
        self._timeout: float = 30.0
        self._retry_policy: Dict[str, Any] = field(default_factory=lambda: {
            "max_retries": 3,
            "delay": 1.0,
            "backoff": 2.0,
            "max_delay": 60.0,
        })

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        old_name = self._name
        self._name = value
        self._checksum = self._compute_checksum()
        logger.debug(f"Skill renamed from '{old_name}' to '{value}'")

    @property
    def skill_id(self) -> str:
        return self._skill_id

    @property
    def handler(self) -> Optional[Callable[..., Any]]:
        return self._handler

    @handler.setter
    def handler(self, value: Callable[..., Any]) -> None:
        self._handler = value
        self._checksum = self._compute_checksum()

    @property
    def metadata(self) -> SkillMetadata:
        return self._metadata

    @metadata.setter
    def metadata(self, value: SkillMetadata) -> None:
        self._metadata = value
        self._checksum = self._compute_checksum()

    @property
    def status(self) -> SkillStatus:
        return self._status

    @property
    def inputs(self) -> List[SkillInput]:
        return list(self._inputs)

    @property
    def outputs(self) -> List[SkillOutput]:
        return list(self._outputs)

    @property
    def dependencies(self) -> List[SkillDependency]:
        return list(self._dependencies)

    @property
    def triggers(self) -> List[SkillTrigger]:
        return list(self._triggers)

    @property
    def tags(self) -> List[str]:
        return list(self._tags)

    @property
    def aliases(self) -> List[str]:
        return list(self._aliases)

    @property
    def groups(self) -> List[str]:
        return list(self._groups)

    @property
    def execution_count(self) -> int:
        return self._execution_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def total_elapsed(self) -> float:
        return self._total_elapsed

    @property
    def last_execution(self) -> Optional[float]:
        return self._last_execution

    @property
    def checksum(self) -> str:
        return self._checksum

    def _compute_checksum(self) -> str:
        raw = f"{self._name}:{self._metadata}:{self._config}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def add_input(self, inp: SkillInput) -> "RuleSkill":
        existing = [i for i in self._inputs if i.name == inp.name]
        if existing:
            logger.warning(f"Input '{inp.name}' already exists, replacing")
            self._inputs.remove(existing[0])
        self._inputs.append(inp)
        self._checksum = self._compute_checksum()
        return self

    def add_output(self, out: SkillOutput) -> "RuleSkill":
        existing = [o for o in self._outputs if o.name == out.name]
        if existing:
            logger.warning(f"Output '{out.name}' already exists, replacing")
            self._outputs.remove(existing[0])
        self._outputs.append(out)
        self._checksum = self._compute_checksum()
        return self

    def add_dependency(self, dep: SkillDependency) -> "RuleSkill":
        if dep not in self._dependencies:
            self._dependencies.append(dep)
            self._checksum = self._compute_checksum()
        return self

    def remove_dependency(self, name: str) -> "RuleSkill":
        self._dependencies = [d for d in self._dependencies if d.name != name]
        self._checksum = self._compute_checksum()
        return self

    def add_tag(self, tag: str) -> "RuleSkill":
        if tag not in self._tags:
            self._tags.append(tag)
        return self

    def remove_tag(self, tag: str) -> "RuleSkill":
        self._tags = [t for t in self._tags if t != tag]
        return self

    def add_alias(self, alias: str) -> "RuleSkill":
        if alias not in self._aliases:
            self._aliases.append(alias)
        return self

    def add_group(self, group: str) -> "RuleSkill":
        if group not in self._groups:
            self._groups.append(group)
        return self

    def add_trigger(self, trigger: SkillTrigger) -> "RuleSkill":
        if trigger not in self._triggers:
            self._triggers.append(trigger)
        return self

    def set_config(self, key: str, value: Any) -> "RuleSkill":
        self._config[key] = value
        self._checksum = self._compute_checksum()
        return self

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def has_tag(self, tag: str) -> bool:
        return tag in self._tags

    def has_group(self, group: str) -> bool:
        return group in self._groups

    def has_alias(self, alias: str) -> bool:
        return alias in self._aliases

    def has_dependency(self, name: str) -> bool:
        return any(d.name == name for d in self._dependencies)

    def register(self) -> None:
        self._status = SkillStatus.REGISTERED
        self._registered_at = datetime.now(timezone.utc).isoformat()
        self._run_hooks("on_register")
        logger.info(f"Skill '{self._name}' registered at {self._registered_at}")

    def unregister(self) -> None:
        self._status = SkillStatus.DRAFT
        self._run_hooks("on_unregister")
        logger.info(f"Skill '{self._name}' unregistered")

    def activate(self) -> None:
        if self._status == SkillStatus.ERROR:
            logger.warning(f"Cannot activate skill '{self._name}' in ERROR status")
            return
        self._status = SkillStatus.ACTIVE
        self._activated_at = datetime.now(timezone.utc).isoformat()
        self._run_hooks("on_activate")
        logger.info(f"Skill '{self._name}' activated at {self._activated_at}")

    def deactivate(self) -> None:
        self._status = SkillStatus.INACTIVE
        self._deactivated_at = datetime.now(timezone.utc).isoformat()
        self._run_hooks("on_deactivate")
        logger.info(f"Skill '{self._name}' deactivated at {self._deactivated_at}")

    def deprecate(self) -> None:
        self._status = SkillStatus.DEPRECATED
        logger.info(f"Skill '{self._name}' deprecated")

    def disable(self) -> None:
        self._status = SkillStatus.DISABLED
        logger.info(f"Skill '{self._name}' disabled")

    def is_active(self) -> bool:
        return self._status == SkillStatus.ACTIVE

    def is_executable(self) -> bool:
        return self._status == SkillStatus.ACTIVE and self._handler is not None

    def can_execute(self, context: Optional[ExecutionContext] = None) -> Tuple[bool, str]:
        if self._status != SkillStatus.ACTIVE:
            return False, f"Skill '{self._name}' is not active (status: {self._status.value})"
        if self._handler is None:
            return False, f"Skill '{self._name}' has no handler"
        if self._dependencies:
            for dep in self._dependencies:
                if not dep.optional and dep.version is None:
                    return False, f"Dependency '{dep.name}' has unresolved version"
        if context:
            for inp in self._inputs:
                if inp.required and inp.name not in context.inputs:
                    return False, f"Required input '{inp.name}' not provided"
        return True, ""

    def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        exec_ctx = self._create_context(context, **kwargs)
        if not self.is_executable():
            exec_ctx.fail(f"Skill '{self._name}' is not executable (status: {self._status.value})")
            return exec_ctx.to_dict()
        can_exec, reason = self.can_execute(exec_ctx)
        if not can_exec:
            exec_ctx.fail(reason)
            return exec_ctx.to_dict()
        exec_ctx.start()
        try:
            self._run_hooks("before_execute", exec_ctx)
            for middleware_fn in self._middleware:
                result = middleware_fn(self, exec_ctx)
                if result is not None:
                    exec_ctx.outputs.update(result if isinstance(result, dict) else {"result": result})
                    exec_ctx.complete()
                    self._record_execution(exec_ctx)
                    return exec_ctx.to_dict()
            result = self._handler(exec_ctx, **exec_ctx.inputs)
            exec_ctx.complete(result if isinstance(result, dict) else {"result": result})
            self._run_hooks("after_execute", exec_ctx)
        except Exception as e:
            exec_ctx.fail(str(e))
            self._run_hooks("on_error", exec_ctx, e)
            if exec_ctx.should_retry():
                logger.info(f"Retrying skill '{self._name}' (attempt {exec_ctx.retry_count + 1}/{exec_ctx.max_retries})")
                exec_ctx.retry_count += 1
                time.sleep(exec_ctx.retry_delay * (self._retry_policy.get("backoff", 2.0) ** (exec_ctx.retry_count - 1)))
                return self.execute(context=exec_ctx.inputs, **{})
            logger.error(f"Skill '{self._name}' execution failed: {e}")
        finally:
            self._record_execution(exec_ctx)
            self._evict_cache()
        return exec_ctx.to_dict()

    def _create_context(self, context: Optional[Dict[str, Any]], **kwargs: Any) -> ExecutionContext:
        merged = dict(context or {})
        merged.update(kwargs)
        return ExecutionContext(
            skill_name=self._name,
            inputs=merged,
            config=dict(self._config),
            environment={},
            timeout=self._timeout,
            max_retries=self._retry_policy.get("max_retries", 3),
            retry_delay=self._retry_policy.get("delay", 1.0),
        )

    def _record_execution(self, ctx: ExecutionContext) -> None:
        self._execution_count += 1
        self._total_elapsed += ctx.elapsed()
        self._last_execution = ctx.completed_at or time.time()
        if ctx.error:
            self._error_count += 1

    def add_hook(self, event: str, hook: Callable[..., Any]) -> "RuleSkill":
        if event in self._hooks:
            self._hooks[event].append(hook)
        else:
            logger.warning(f"Unknown hook event '{event}'")
        return self

    def remove_hook(self, event: str, hook: Callable[..., Any]) -> "RuleSkill":
        if event in self._hooks:
            self._hooks[event] = [h for h in self._hooks[event] if h is not hook]
        return self

    def _run_hooks(self, event: str, *args: Any, **kwargs: Any) -> None:
        for hook in self._hooks.get(event, []):
            try:
                hook(self, *args, **kwargs)
            except Exception as e:
                logger.warning(f"Hook '{event}' failed in skill '{self._name}': {e}")

    def add_middleware(self, middleware_fn: Callable[..., Any]) -> "RuleSkill":
        self._middleware.append(middleware_fn)
        return self

    def remove_middleware(self, middleware_fn: Callable[..., Any]) -> "RuleSkill":
        self._middleware = [m for m in self._middleware if m is not middleware_fn]
        return self

    def cache_result(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        expires = time.time() + (ttl or self._cache_ttl)
        self._cache[key] = {"value": value, "expires": expires}

    def get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and time.time() < entry["expires"]:
            return entry["value"]
        if entry:
            del self._cache[key]
        return None

    def invalidate_cache(self, key: Optional[str] = None) -> None:
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def _evict_cache(self) -> None:
        now = time.time()
        expired = [k for k, v in self._cache.items() if v["expires"] < now]
        for k in expired:
            del self._cache[k]

    def set_timeout(self, timeout: float) -> "RuleSkill":
        self._timeout = timeout
        return self

    def set_retry_policy(
        self,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        max_delay: float = 60.0,
    ) -> "RuleSkill":
        self._retry_policy = {
            "max_retries": max_retries,
            "delay": delay,
            "backoff": backoff,
            "max_delay": max_delay,
        }
        return self

    def add_environment(self, env: str) -> "RuleSkill":
        if env not in self._environments:
            self._environments.append(env)
        return self

    def remove_environment(self, env: str) -> "RuleSkill":
        if env in self._environments:
            self._environments.remove(env)
        return self

    def in_environment(self, env: str) -> bool:
        return env in self._environments

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "skill_id": self._skill_id,
            "status": self._status.value,
            "metadata": self._metadata.to_dict(),
            "inputs": [asdict(i) for i in self._inputs],
            "outputs": [asdict(o) for o in self._outputs],
            "dependencies": [asdict(d) for d in self._dependencies],
            "triggers": [t.value for t in self._triggers],
            "tags": self._tags,
            "config": self._config,
            "aliases": self._aliases,
            "groups": self._groups,
            "environments": self._environments,
            "checksum": self._checksum,
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "total_elapsed": self._total_elapsed,
            "last_execution": self._last_execution,
            "registered_at": self._registered_at,
            "activated_at": self._activated_at,
            "deactivated_at": self._deactivated_at,
            "timeout": self._timeout,
            "retry_policy": self._retry_policy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleSkill":
        skill = cls(
            name=data["name"],
            metadata=SkillMetadata.from_dict(data.get("metadata", {})),
            inputs=[SkillInput(**i) for i in data.get("inputs", [])],
            outputs=[SkillOutput(**o) for o in data.get("outputs", [])],
            dependencies=[SkillDependency(**d) for d in data.get("dependencies", [])],
            triggers=[SkillTrigger(t) for t in data.get("triggers", [])],
            tags=data.get("tags", []),
            config=data.get("config", {}),
        )
        skill._skill_id = data.get("skill_id", skill._skill_id)
        skill._status = SkillStatus(data.get("status", "draft"))
        skill._aliases = data.get("aliases", [])
        skill._groups = data.get("groups", [])
        skill._environments = data.get("environments", ["default"])
        skill._checksum = data.get("checksum", skill._checksum)
        skill._execution_count = data.get("execution_count", 0)
        skill._error_count = data.get("error_count", 0)
        skill._total_elapsed = data.get("total_elapsed", 0.0)
        skill._last_execution = data.get("last_execution")
        skill._registered_at = data.get("registered_at")
        skill._activated_at = data.get("activated_at")
        skill._deactivated_at = data.get("deactivated_at")
        skill._timeout = data.get("timeout", 30.0)
        skill._retry_policy = data.get("retry_policy", {"max_retries": 3, "delay": 1.0, "backoff": 2.0, "max_delay": 60.0})
        return skill

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "RuleSkill":
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)

    def clone(self, new_name: Optional[str] = None) -> "RuleSkill":
        cloned = copy.deepcopy(self)
        cloned._skill_id = str(uuid.uuid4())
        if new_name:
            cloned._name = new_name
        cloned._execution_count = 0
        cloned._error_count = 0
        cloned._total_elapsed = 0.0
        cloned._last_execution = None
        cloned._status = SkillStatus.DRAFT
        cloned._registered_at = None
        cloned._activated_at = None
        cloned._deactivated_at = None
        cloned._cache = {}
        return cloned

    def merge(self, other: "RuleSkill", strategy: str = "override") -> "RuleSkill":
        merged = self.clone()
        if strategy == "override":
            merged._config.update(other._config)
            for inp in other._inputs:
                merged.add_input(inp)
            for out in other._outputs:
                merged.add_output(out)
            for dep in other._dependencies:
                merged.add_dependency(dep)
            for tag in other._tags:
                merged.add_tag(tag)
            for alias in other._aliases:
                merged.add_alias(alias)
            for group in other._groups:
                merged.add_group(group)
        elif strategy == "merge":
            for k, v in other._config.items():
                if k not in merged._config:
                    merged._config[k] = v
            existing_inputs = {i.name for i in merged._inputs}
            for inp in other._inputs:
                if inp.name not in existing_inputs:
                    merged.add_input(inp)
            existing_outputs = {o.name for o in merged._outputs}
            for out in other._outputs:
                if out.name not in existing_outputs:
                    merged.add_output(out)
            existing_deps = {d.name for d in merged._dependencies}
            for dep in other._dependencies:
                if dep.name not in existing_deps:
                    merged.add_dependency(dep)
            for tag in other._tags:
                merged.add_tag(tag)
        merged._checksum = merged._compute_checksum()
        return merged

    def validate_inputs(self, **kwargs: Any) -> List[str]:
        errors = []
        for inp in self._inputs:
            value = kwargs.get(inp.name)
            if inp.required and value is None:
                errors.append(f"Required input '{inp.name}' is missing")
                continue
            if value is not None and not inp.validate(value):
                errors.append(f"Input '{inp.name}' validation failed")
        return errors

    def validate_outputs(self, outputs: Dict[str, Any]) -> List[str]:
        errors = []
        for out in self._outputs:
            if out.name not in outputs and not out.optional:
                errors.append(f"Required output '{out.name}' is missing")
        return errors

    def has_handler(self) -> bool:
        return self._handler is not None

    def attach_handler(self, handler: Callable[..., Any]) -> "RuleSkill":
        self._handler = handler
        self._checksum = self._compute_checksum()
        return self

    def detach_handler(self) -> "RuleSkill":
        self._handler = None
        self._checksum = self._compute_checksum()
        return self

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "status": self._status.value,
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "error_rate": (self._error_count / max(self._execution_count, 1)) * 100,
            "total_elapsed": self._total_elapsed,
            "avg_elapsed": self._total_elapsed / max(self._execution_count, 1),
            "last_execution": self._last_execution,
            "cache_size": len(self._cache),
            "dependencies": len(self._dependencies),
            "inputs": len(self._inputs),
            "outputs": len(self._outputs),
            "hooks": {k: len(v) for k, v in self._hooks.items()},
            "middleware": len(self._middleware),
        }

    def reset_stats(self) -> "RuleSkill":
        self._execution_count = 0
        self._error_count = 0
        self._total_elapsed = 0.0
        self._last_execution = None
        return self

    def __repr__(self) -> str:
        return f"RuleSkill(name='{self._name}', status={self._status.value}, checksum={self._checksum})"

    def __str__(self) -> str:
        return f"RuleSkill[{self._name}] (v{self._metadata.version}, {self._status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuleSkill):
            return NotImplemented
        return self._skill_id == other._skill_id

    def __hash__(self) -> int:
        return hash(self._skill_id)


def skill_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    func._is_skill_handler = True
    return func


def rule_skill(
    name: str,
    category: SkillCategory = SkillCategory.CUSTOM,
    priority: SkillPriority = SkillPriority.NORMAL,
    author: str = "",
    description: str = "",
    version: str = "1.0.0",
    tags: Optional[List[str]] = None,
    triggers: Optional[List[SkillTrigger]] = None,
    timeout: float = 30.0,
) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> RuleSkill:
        metadata = SkillMetadata(
            author=author,
            description=description,
            tags=tags or [],
            version=SkillVersion.parse(version),
            category=category,
            priority=priority,
        )
        skill = RuleSkill(
            name=name,
            handler=func,
            metadata=metadata,
            triggers=triggers or [SkillTrigger.MANUAL],
        )
        skill.set_timeout(timeout)
        skill._checksum = skill._compute_checksum()
        return skill
    return decorator


def compose_skills(*skills: RuleSkill) -> RuleSkill:
    if not skills:
        raise ValueError("At least one skill required for composition")
    base = skills[0].clone()
    for skill in skills[1:]:
        base = base.merge(skill, strategy="merge")
    base._name = f"composed_{'_'.join(s.name for s in skills)}"
    composed_handler = _make_composed_handler(skills)
    base.attach_handler(composed_handler)
    return base


def _make_composed_handler(skills: Tuple[RuleSkill, ...]) -> Callable[..., Any]:
    def handler(ctx: ExecutionContext, **kwargs: Any) -> Dict[str, Any]:
        results = {}
        for skill in skills:
            if not skill.is_executable():
                logger.warning(f"Skipping non-executable skill '{skill.name}' in composition")
                continue
            try:
                result = skill.execute(context=dict(ctx.inputs))
                results[skill.name] = result
                if result.get("error"):
                    logger.error(f"Composed skill '{skill.name}' failed: {result['error']}")
                    break
            except Exception as e:
                logger.error(f"Composed skill '{skill.name}' raised exception: {e}")
                results[skill.name] = {"error": str(e)}
                break
        return results
    return handler
