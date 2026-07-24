"""SkillExecutor - Execute skills in isolated context with timeout, result collection, error handling, and parallel execution."""

import logging
import time
import uuid
import json
import threading
import concurrent.futures
import queue
import signal
import traceback
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime, timezone
from collections import OrderedDict

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"
    CONDITIONAL = "conditional"


class ErrorStrategy(Enum):
    STOP_IMMEDIATELY = "stop_immediately"
    CONTINUE = "continue"
    RETRY = "retry"
    FALLBACK = "fallback"
    IGNORE = "ignore"


@dataclass
class ExecutionResult:
    skill_name: str
    execution_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    traceback: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    child_results: List["ExecutionResult"] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == ExecutionStatus.COMPLETED

    @property
    def elapsed(self) -> float:
        if self.duration:
            return self.duration
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.elapsed,
            "retry_count": self.retry_count,
            "warnings": self.warnings,
            "child_results": [r.to_dict() for r in self.child_results],
        }


@dataclass
class ExecutionBatch:
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    skills: List[str] = field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    results: Dict[str, ExecutionResult] = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    error: Optional[str] = None

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results.values() if r.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "skills": self.skills,
            "mode": self.mode.value,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "status": self.status.value,
            "error": self.error,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


@dataclass
class ExecutorConfig:
    default_timeout: float = 30.0
    max_workers: int = 4
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    error_strategy: ErrorStrategy = ErrorStrategy.CONTINUE
    track_history: bool = True
    history_size: int = 500
    collect_traceback: bool = True
    collect_inputs: bool = True
    collect_outputs: bool = True
    validate_inputs: bool = True
    validate_outputs: bool = True
    propagate_errors: bool = False
    stop_on_first_error: bool = False
    log_execution: bool = True
    max_concurrent_skills: int = 10
    batch_size: int = 50
    enable_caching: bool = False
    cache_ttl: float = 300.0
    metrics_enabled: bool = True
    environment: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutorConfig":
        return cls(
            default_timeout=data.get("default_timeout", 30.0),
            max_workers=data.get("max_workers", 4),
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            retry_backoff=data.get("retry_backoff", 2.0),
            error_strategy=ErrorStrategy(data.get("error_strategy", "continue")),
            track_history=data.get("track_history", True),
            history_size=data.get("history_size", 500),
            collect_traceback=data.get("collect_traceback", True),
            collect_inputs=data.get("collect_inputs", True),
            collect_outputs=data.get("collect_outputs", True),
            validate_inputs=data.get("validate_inputs", True),
            validate_outputs=data.get("validate_outputs", True),
            propagate_errors=data.get("propagate_errors", False),
            stop_on_first_error=data.get("stop_on_first_error", False),
            log_execution=data.get("log_execution", True),
            max_concurrent_skills=data.get("max_concurrent_skills", 10),
            batch_size=data.get("batch_size", 50),
            enable_caching=data.get("enable_caching", False),
            cache_ttl=data.get("cache_ttl", 300.0),
            metrics_enabled=data.get("metrics_enabled", True),
            environment=data.get("environment", "default"),
        )


@dataclass
class ExecutorMetrics:
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    timed_out_executions: int = 0
    cancelled_executions: int = 0
    total_retries: int = 0
    total_duration: float = 0.0
    min_duration: float = float("inf")
    max_duration: float = 0.0
    avg_duration: float = 0.0
    total_batches: int = 0
    errors_by_skill: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    executions_by_skill: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_execution: Optional[float] = None
    active_executions: int = 0
    peak_concurrent: int = 0

    def record(self, result: ExecutionResult) -> None:
        self.total_executions += 1
        self.executions_by_skill[result.skill_name] += 1
        self.last_execution = time.time()
        if result.success:
            self.successful_executions += 1
            self.total_duration += result.elapsed
            self.min_duration = min(self.min_duration, result.elapsed)
            self.max_duration = max(self.max_duration, result.elapsed)
            self.avg_duration = self.total_duration / max(self.successful_executions, 1)
        elif result.status == ExecutionStatus.TIMEOUT:
            self.timed_out_executions += 1
        elif result.status == ExecutionStatus.CANCELLED:
            self.cancelled_executions += 1
        else:
            self.failed_executions += 1
            self.errors_by_skill[result.skill_name] += 1
            if result.error:
                error_type = result.error.split(":")[0] if ":" in result.error else result.error
                self.errors_by_type[error_type] += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "timed_out_executions": self.timed_out_executions,
            "cancelled_executions": self.cancelled_executions,
            "total_retries": self.total_retries,
            "total_duration": self.total_duration,
            "min_duration": self.min_duration if self.min_duration != float("inf") else 0,
            "max_duration": self.max_duration,
            "avg_duration": self.avg_duration,
            "total_batches": self.total_batches,
            "last_execution": self.last_execution,
            "active_executions": self.active_executions,
            "peak_concurrent": self.peak_concurrent,
        }


from .rule_skill import RuleSkill, ExecutionContext, SkillInput, SkillOutput


class SkillExecutor:
    def __init__(
        self,
        config: Optional[Union[ExecutorConfig, Dict[str, Any]]] = None,
        name: str = "default",
    ):
        self._name = name
        if isinstance(config, dict):
            self._config = ExecutorConfig.from_dict(config)
        elif config is None:
            self._config = ExecutorConfig()
        else:
            self._config = config
        self._history: List[ExecutionResult] = []
        self._batches: List[ExecutionBatch] = []
        self._active_executions: Dict[str, ExecutionResult] = {}
        self._metrics = ExecutorMetrics()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._config.max_workers,
            thread_name_prefix=f"skill_exec_{name}",
        )
        self._lock = threading.RLock()
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._fallback_handlers: Dict[str, Callable[..., Any]] = {}
        self._pre_hooks: List[Callable[..., Any]] = []
        self._post_hooks: List[Callable[..., Any]] = []
        self._error_hooks: List[Callable[..., Any]] = []
        self._interrupt_flag = threading.Event()
        self._started_at = time.time()

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> ExecutorConfig:
        return self._config

    @property
    def metrics(self) -> ExecutorMetrics:
        with self._lock:
            return self._metrics

    @property
    def history(self) -> List[ExecutionResult]:
        with self._lock:
            return list(self._history)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_executions)

    def execute(
        self,
        skill: RuleSkill,
        inputs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        merged_inputs = dict(inputs or {})
        merged_inputs.update(kwargs)
        if self._config.validate_inputs:
            validation_errors = skill.validate_inputs(**merged_inputs)
            if validation_errors:
                result = ExecutionResult(
                    skill_name=skill.name,
                    execution_id=str(uuid.uuid4()),
                    status=ExecutionStatus.FAILED,
                    inputs=merged_inputs if self._config.collect_inputs else {},
                    error=f"Input validation failed: {'; '.join(validation_errors)}",
                )
                self._record_result(result)
                return result
        result = ExecutionResult(
            skill_name=skill.name,
            execution_id=str(uuid.uuid4()),
            inputs=merged_inputs if self._config.collect_inputs else {},
            status=ExecutionStatus.PENDING,
        )
        with self._lock:
            self._active_executions[result.execution_id] = result
            self._metrics.active_executions += 1
            self._metrics.peak_concurrent = max(self._metrics.peak_concurrent, self._metrics.active_executions)
        try:
            result.started_at = time.time()
            result.status = ExecutionStatus.RUNNING
            effective_timeout = timeout or self._config.default_timeout
            if self._config.enable_caching:
                cache_key = f"{skill.name}:{json.dumps(merged_inputs, sort_keys=True, default=str)}"
                cached = self._get_cached(cache_key)
                if cached is not None:
                    result.outputs = {"result": cached}
                    result.status = ExecutionStatus.COMPLETED
                    result.completed_at = time.time()
                    result.duration = result.completed_at - result.started_at
                    self._record_result(result)
                    return result
            retries = 0
            max_retries = self._config.max_retries
            while True:
                try:
                    for hook in self._pre_hooks:
                        hook(skill, result)
                    if self._interrupt_flag.is_set():
                        result.status = ExecutionStatus.CANCELLED
                        result.error = "Execution interrupted"
                        break
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as single_executor:
                        future = single_executor.submit(self._do_execute, skill, merged_inputs)
                        try:
                            ctx = future.result(timeout=effective_timeout)
                            result.outputs = ctx.outputs if self._config.collect_outputs else {}
                            result.status = ExecutionStatus.COMPLETED
                            for hook in self._post_hooks:
                                hook(skill, result)
                            if self._config.enable_caching and result.success:
                                self._set_cached(cache_key, result.outputs)
                            break
                        except concurrent.futures.TimeoutError:
                            result.status = ExecutionStatus.TIMEOUT
                            result.error = f"Execution timed out after {effective_timeout}s"
                            future.cancel()
                            if retries < max_retries and self._config.error_strategy in (ErrorStrategy.RETRY, ErrorStrategy.CONTINUE):
                                retries += 1
                                self._metrics.total_retries += 1
                                wait = self._config.retry_delay * (self._config.retry_backoff ** (retries - 1))
                                logger.info(f"Retrying skill '{skill.name}' (attempt {retries}/{max_retries}) after timeout, waiting {wait:.1f}s")
                                time.sleep(wait)
                                continue
                            break
                except Exception as e:
                    if retries < max_retries and self._config.error_strategy in (ErrorStrategy.RETRY, ErrorStrategy.CONTINUE):
                        retries += 1
                        self._metrics.total_retries += 1
                        wait = self._config.retry_delay * (self._config.retry_backoff ** (retries - 1))
                        logger.info(f"Retrying skill '{skill.name}' (attempt {retries}/{max_retries}) after error: {e}")
                        time.sleep(wait)
                        continue
                    result.status = ExecutionStatus.FAILED
                    result.error = str(e)
                    if self._config.collect_traceback:
                        result.traceback = traceback.format_exc()
                    for hook in self._error_hooks:
                        hook(skill, result, e)
                    if self._config.error_strategy == ErrorStrategy.FALLBACK and skill.name in self._fallback_handlers:
                        try:
                            fb_result = self._fallback_handlers[skill.name](merged_inputs)
                            result.outputs = {"result": fb_result} if self._config.collect_outputs else {}
                            result.status = ExecutionStatus.COMPLETED
                            result.warnings.append(f"Fallback handler used after error: {e}")
                        except Exception as fb_e:
                            result.warnings.append(f"Fallback also failed: {fb_e}")
                    break
        finally:
            result.retry_count = retries
            result.completed_at = result.completed_at or time.time()
            result.duration = result.elapsed
            with self._lock:
                self._active_executions.pop(result.execution_id, None)
                self._metrics.active_executions -= 1
            self._metrics.record(result)
            self._record_result(result)
            if self._config.log_execution:
                log_fn = logger.info if result.success else logger.error
                log_fn(f"Skill '{skill.name}' executed: {result.status.value} in {result.duration:.3f}s")
        return result

    def _do_execute(self, skill: RuleSkill, inputs: Dict[str, Any]) -> ExecutionContext:
        ctx = ExecutionContext(
            skill_name=skill.name,
            inputs=inputs,
            config=skill._config,
            timeout=self._config.default_timeout,
        )
        ctx.start()
        try:
            output = skill.handler(ctx, **inputs)
            ctx.complete(output if isinstance(output, dict) else {"result": output})
        except Exception as e:
            ctx.fail(str(e))
            raise
        return ctx

    def execute_batch(
        self,
        skills: List[RuleSkill],
        inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        timeout: Optional[float] = None,
    ) -> ExecutionBatch:
        batch = ExecutionBatch(
            skills=[s.name for s in skills],
            mode=mode,
            started_at=time.time(),
            status=ExecutionStatus.RUNNING,
        )
        with self._lock:
            self._metrics.total_batches += 1
        try:
            if mode == ExecutionMode.SEQUENTIAL:
                for skill in skills:
                    skill_inputs = (inputs or {}).get(skill.name, {})
                    result = self.execute(skill, inputs=skill_inputs, timeout=timeout)
                    batch.results[skill.name] = result
                    if not result.success and self._config.stop_on_first_error:
                        batch.error = f"Stopped at skill '{skill.name}': {result.error}"
                        break
            elif mode == ExecutionMode.PARALLEL:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(skills), self._config.max_concurrent_skills)
                ) as pool:
                    future_to_skill = {}
                    for skill in skills:
                        skill_inputs = (inputs or {}).get(skill.name, {})
                        future = pool.submit(self.execute, skill, inputs=skill_inputs, timeout=timeout)
                        future_to_skill[future] = skill
                    for future in concurrent.futures.as_completed(future_to_skill):
                        skill = future_to_skill[future]
                        try:
                            result = future.result()
                            batch.results[skill.name] = result
                        except Exception as e:
                            batch.results[skill.name] = ExecutionResult(
                                skill_name=skill.name,
                                execution_id=str(uuid.uuid4()),
                                status=ExecutionStatus.FAILED,
                                error=f"Batch execution error: {e}",
                            )
            elif mode == ExecutionMode.PIPELINE:
                pipeline_inputs = dict(inputs or {})
                for skill in skills:
                    skill_inputs = pipeline_inputs.get(skill.name, {})
                    if batch.results:
                        last_result = list(batch.results.values())[-1]
                        if last_result.success:
                            skill_inputs.update(last_result.outputs)
                    result = self.execute(skill, inputs=skill_inputs, timeout=timeout)
                    batch.results[skill.name] = result
                    if not result.success and self._config.stop_on_first_error:
                        batch.error = f"Pipeline stopped at skill '{skill.name}': {result.error}"
                        break
            elif mode == ExecutionMode.FAN_OUT:
                if skills:
                    base_inputs = (inputs or {}).get(skills[0].name, {}) if skills else {}
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(len(skills), self._config.max_concurrent_skills)
                    ) as pool:
                        futures = {}
                        for skill in skills:
                            skill_inputs = dict(base_inputs)
                            skill_inputs.update((inputs or {}).get(skill.name, {}))
                            future = pool.submit(self.execute, skill, inputs=skill_inputs, timeout=timeout)
                            futures[future] = skill
                        for future in concurrent.futures.as_completed(futures):
                            skill = futures[future]
                            try:
                                batch.results[skill.name] = future.result()
                            except Exception as e:
                                batch.results[skill.name] = ExecutionResult(
                                    skill_name=skill.name,
                                    execution_id=str(uuid.uuid4()),
                                    status=ExecutionStatus.FAILED,
                                    error=str(e),
                                )
            elif mode == ExecutionMode.FAN_IN:
                for skill in skills[:-1]:
                    skill_inputs = (inputs or {}).get(skill.name, {})
                    result = self.execute(skill, inputs=skill_inputs, timeout=timeout)
                    batch.results[skill.name] = result
                if skills:
                    last_skill = skills[-1]
                    merged_inputs = dict((inputs or {}).get(last_skill.name, {}))
                    for r in batch.results.values():
                        if r.success:
                            merged_inputs.update(r.outputs)
                    result = self.execute(last_skill, inputs=merged_inputs, timeout=timeout)
                    batch.results[last_skill.name] = result
            elif mode == ExecutionMode.CONDITIONAL:
                for skill in skills:
                    skill_inputs = (inputs or {}).get(skill.name, {})
                    if skill_inputs.get("_condition", True):
                        result = self.execute(skill, inputs=skill_inputs, timeout=timeout)
                        batch.results[skill.name] = result
                    else:
                        result = ExecutionResult(
                            skill_name=skill.name,
                            execution_id=str(uuid.uuid4()),
                            status=ExecutionStatus.SKIPPED,
                            inputs=skill_inputs if self._config.collect_inputs else {},
                        )
                        batch.results[skill.name] = result
            batch.status = ExecutionStatus.COMPLETED if not batch.error else ExecutionStatus.FAILED
        except Exception as e:
            batch.error = str(e)
            batch.status = ExecutionStatus.FAILED
        finally:
            batch.completed_at = time.time()
        self._batches.append(batch)
        if len(self._batches) > self._config.history_size:
            self._batches = self._batches[-self._config.history_size:]
        return batch

    def execute_with_timeout(
        self,
        skill: RuleSkill,
        inputs: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> ExecutionResult:
        return self.execute(skill, inputs=inputs, timeout=timeout)

    def execute_parallel(
        self,
        skills: List[RuleSkill],
        inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        max_workers: Optional[int] = None,
    ) -> ExecutionBatch:
        return self.execute_batch(
            skills,
            inputs=inputs,
            mode=ExecutionMode.PARALLEL,
        )

    def execute_pipeline(
        self,
        skills: List[RuleSkill],
        initial_inputs: Optional[Dict[str, Any]] = None,
    ) -> ExecutionBatch:
        inputs_by_skill: Dict[str, Dict[str, Any]] = {}
        if initial_inputs:
            inputs_by_skill[skills[0].name] = initial_inputs
        return self.execute_batch(
            skills,
            inputs=inputs_by_skill,
            mode=ExecutionMode.PIPELINE,
        )

    def cancel(self, execution_id: Optional[str] = None) -> bool:
        with self._lock:
            if execution_id:
                result = self._active_executions.get(execution_id)
                if result:
                    result.status = ExecutionStatus.CANCELLED
                    result.error = "Cancelled by user"
                    return True
                return False
            else:
                for rid, result in self._active_executions.items():
                    result.status = ExecutionStatus.CANCELLED
                    result.error = "Cancelled by user"
                self._interrupt_flag.set()
                return bool(self._active_executions)

    def cancel_all(self) -> int:
        with self._lock:
            count = len(self._active_executions)
            for result in self._active_executions.values():
                result.status = ExecutionStatus.CANCELLED
                result.error = "Cancelled by user"
            self._interrupt_flag.set()
            return count

    def add_fallback(self, skill_name: str, handler: Callable[..., Any]) -> None:
        self._fallback_handlers[skill_name] = handler

    def remove_fallback(self, skill_name: str) -> None:
        self._fallback_handlers.pop(skill_name, None)

    def add_pre_hook(self, hook: Callable[..., Any]) -> None:
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: Callable[..., Any]) -> None:
        self._post_hooks.append(hook)

    def add_error_hook(self, hook: Callable[..., Any]) -> None:
        self._error_hooks.append(hook)

    def remove_pre_hook(self, hook: Callable[..., Any]) -> None:
        if hook in self._pre_hooks:
            self._pre_hooks.remove(hook)

    def remove_post_hook(self, hook: Callable[..., Any]) -> None:
        if hook in self._post_hooks:
            self._post_hooks.remove(hook)

    def remove_error_hook(self, hook: Callable[..., Any]) -> None:
        if hook in self._error_hooks:
            self._error_hooks.remove(hook)

    def _record_result(self, result: ExecutionResult) -> None:
        if not self._config.track_history:
            return
        with self._lock:
            self._history.append(result)
            if len(self._history) > self._config.history_size:
                self._history = self._history[-self._config.history_size:]

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and time.time() < entry[1]:
            return entry[0]
        if entry:
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (value, time.time() + self._config.cache_ttl)

    def clear_cache(self) -> None:
        self._cache.clear()

    def get_execution(self, execution_id: str) -> Optional[ExecutionResult]:
        with self._lock:
            for result in self._history:
                if result.execution_id == execution_id:
                    return result
            return self._active_executions.get(execution_id)

    def get_batch(self, batch_id: str) -> Optional[ExecutionBatch]:
        for batch in self._batches:
            if batch.batch_id == batch_id:
                return batch
        return None

    def get_history(
        self,
        skill_name: Optional[str] = None,
        status: Optional[ExecutionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ExecutionResult]:
        with self._lock:
            results = list(self._history)
            if skill_name:
                results = [r for r in results if r.skill_name == skill_name]
            if status:
                results = [r for r in results if r.status == status]
            results.reverse()
            if offset:
                results = results[offset:]
            if limit:
                results = results[:limit]
            return results

    def get_batch_history(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ExecutionBatch]:
        with self._lock:
            batches = list(self._batches)
            batches.reverse()
            if offset:
                batches = batches[offset:]
            if limit:
                batches = batches[:limit]
            return batches

    def success_rate(self, skill_name: Optional[str] = None) -> float:
        with self._lock:
            if skill_name:
                total = self._metrics.executions_by_skill.get(skill_name, 0)
                errors = self._metrics.errors_by_skill.get(skill_name, 0)
            else:
                total = self._metrics.total_executions
                errors = self._metrics.failed_executions
            if total == 0:
                return 1.0
            return (total - errors) / total

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self._name,
                "config": self._config.to_dict(),
                "metrics": self._metrics.to_dict(),
                "history_size": len(self._history),
                "batches": len(self._batches),
                "active": len(self._active_executions),
                "cache_size": len(self._cache),
                "uptime": time.time() - self._started_at,
            }

    def top_errors(self, n: int = 10) -> List[Tuple[str, int]]:
        with self._lock:
            sorted_errors = sorted(
                self._metrics.errors_by_skill.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            return sorted_errors[:n]

    def top_slowest(self, n: int = 10) -> List[ExecutionResult]:
        with self._lock:
            completed = [
                r for r in self._history
                if r.status == ExecutionStatus.COMPLETED and r.duration > 0
            ]
            completed.sort(key=lambda r: r.duration, reverse=True)
            return completed[:n]

    def get_failures(self, skill_name: Optional[str] = None) -> List[ExecutionResult]:
        with self._lock:
            failures = [
                r for r in self._history
                if r.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT)
            ]
            if skill_name:
                failures = [r for r in failures if r.skill_name == skill_name]
            return failures

    def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        deadline = time.time() + timeout if timeout else float("inf")
        while time.time() < deadline:
            with self._lock:
                if not self._active_executions:
                    return True
            time.sleep(0.1)
        return False

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
        logger.info(f"Executor '{self._name}' shut down")

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._batches.clear()
            self._cache.clear()
            self._metrics = ExecutorMetrics()
            self._interrupt_flag.clear()
            logger.info(f"Executor '{self._name}' reset")

    def to_dict(self) -> Dict[str, Any]:
        return self.summary()

    def to_json(self) -> str:
        return json.dumps(self.summary(), indent=2, default=str)

    def report(self) -> str:
        lines = []
        lines.append(f"Executor Report: {self._name}")
        lines.append("=" * 60)
        lines.append(f"Total Executions: {self._metrics.total_executions}")
        lines.append(f"  Successful: {self._metrics.successful_executions}")
        lines.append(f"  Failed: {self._metrics.failed_executions}")
        lines.append(f"  Timed Out: {self._metrics.timed_out_executions}")
        lines.append(f"  Cancelled: {self._metrics.cancelled_executions}")
        lines.append(f"Total Retries: {self._metrics.total_retries}")
        lines.append(f"Duration: min={self._metrics.min_duration:.3f}s, max={self._metrics.max_duration:.3f}s, avg={self._metrics.avg_duration:.3f}s")
        lines.append(f"Active Executions: {self._metrics.active_executions}")
        lines.append(f"Peak Concurrent: {self._metrics.peak_concurrent}")
        lines.append(f"Success Rate: {self.success_rate() * 100:.1f}%")
        lines.append(f"Cached Entries: {len(self._cache)}")
        lines.append(f"History Size: {len(self._history)}")
        top_errs = self.top_errors(5)
        if top_errs:
            lines.append(f"\nTop Errors by Skill:")
            for name, count in top_errs:
                lines.append(f"  {name}: {count}")
        top_slow = self.top_slowest(5)
        if top_slow:
            lines.append(f"\nSlowest Executions:")
            for r in top_slow:
                lines.append(f"  {r.skill_name}: {r.duration:.3f}s")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"SkillExecutor(name='{self._name}', executed={self._metrics.total_executions}, active={self._metrics.active_executions})"

    def __str__(self) -> str:
        return f"SkillExecutor[{self._name}] ({self._metrics.total_executions} executions, {self._metrics.active_executions} active)"

    def __len__(self) -> int:
        return len(self._history)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


def create_executor(config: Optional[Dict[str, Any]] = None, name: str = "default") -> SkillExecutor:
    return SkillExecutor(config=config, name=name)


def execute_skills_parallel(
    skills: List[RuleSkill],
    inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    max_workers: int = 4,
) -> Dict[str, ExecutionResult]:
    executor = SkillExecutor(config=ExecutorConfig(max_workers=max_workers))
    batch = executor.execute_batch(skills, inputs=inputs, mode=ExecutionMode.PARALLEL)
    return dict(batch.results)
