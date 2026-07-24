"""
Multi-stage evaluation pipeline for rule processing.
"""

import asyncio
import hashlib
import json
import logging
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import (
    ActionTaken,
    Suggestion,
    ValidationResult,
    Violation,
    ViolationType,
)
from rules_emerging_pattern.models.conflict import (
    ConflictResolution,
    ConflictType,
    ResolutionStrategy,
    RuleConflict,
)

from .engine_config import EngineConfig

logger = logging.getLogger(__name__)


class StageType(str, Enum):
    """Types of pipeline stages."""
    PRE_PROCESS = "pre_process"
    EVALUATE = "evaluate"
    POST_PROCESS = "post_process"
    REPORT = "report"
    VALIDATE = "validate"
    ENRICH = "enrich"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    CUSTOM = "custom"


class StageStatus(str, Enum):
    """Status of a pipeline stage execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PipelineStatus(str, Enum):
    """Status of a pipeline execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class PipelineError(Exception):
    """Base exception for pipeline errors."""
    pass


class StageExecutionError(PipelineError):
    """Raised when a stage fails to execute."""
    pass


class StageTimeoutError(PipelineError):
    """Raised when a stage times out."""
    pass


class PipelineConfigurationError(PipelineError):
    """Raised when pipeline configuration is invalid."""
    pass


@dataclass
class StageResult:
    """Result from a single pipeline stage."""

    stage_name: str
    stage_type: StageType
    status: StageStatus
    result: Optional[ValidationResult] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    input_size: int = 0
    output_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "stage_type": self.stage_type.value,
            "status": self.status.value,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "input_size": self.input_size,
            "output_size": self.output_size,
            "metadata": self.metadata,
        }


@dataclass
class PipelineContext:
    """Context passed through pipeline stages."""

    request: RuleEvaluationRequest
    result: Optional[ValidationResult] = None
    stage_results: Dict[str, StageResult] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    pipeline_id: str = ""
    parallel_stages: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.pipeline_id:
            self.pipeline_id = f"pipe_{int(time.time() * 1000)}_{hash(time.time()) % 10000}"

    def get_elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000

    def add_stage_result(self, stage_result: StageResult) -> None:
        self.stage_results[stage_result.stage_name] = stage_result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "elapsed_ms": round(self.get_elapsed_ms(), 2),
            "stage_count": len(self.stage_results),
            "stages": {k: v.to_dict() for k, v in self.stage_results.items()},
            "variable_count": len(self.variables),
            "parallel_stages": self.parallel_stages,
        }


@dataclass
class PipelineMetrics:
    """Metrics collected during pipeline execution."""

    total_pipelines: int = 0
    completed_pipelines: int = 0
    failed_pipelines: int = 0
    partial_pipelines: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    stage_metrics: Dict[str, Dict[str, Any]] = field(default_factory=lambda: defaultdict(lambda: {
        "count": 0, "total_duration_ms": 0.0, "failures": 0, "timeouts": 0,
    }))
    start_time: float = field(default_factory=time.time)

    def record_pipeline(self, duration_ms: float, success: bool, partial: bool = False) -> None:
        self.total_pipelines += 1
        if success:
            self.completed_pipelines += 1
        elif partial:
            self.partial_pipelines += 1
        else:
            self.failed_pipelines += 1
        self.total_duration_ms += duration_ms
        self.min_duration_ms = min(self.min_duration_ms, duration_ms)
        self.max_duration_ms = max(self.max_duration_ms, duration_ms)

    def record_stage(self, stage_name: str, duration_ms: float, status: StageStatus) -> None:
        metrics = self.stage_metrics[stage_name]
        metrics["count"] += 1
        metrics["total_duration_ms"] += duration_ms
        if status == StageStatus.FAILED:
            metrics["failures"] += 1
        elif status == StageStatus.TIMEOUT:
            metrics["timeouts"] += 1

    def to_dict(self) -> Dict[str, Any]:
        total = self.total_pipelines
        avg_ms = self.total_duration_ms / total if total > 0 else 0.0
        return {
            "total_pipelines": total,
            "completed_pipelines": self.completed_pipelines,
            "failed_pipelines": self.failed_pipelines,
            "partial_pipelines": self.partial_pipelines,
            "success_rate": round((self.completed_pipelines / max(total, 1)) * 100, 2),
            "average_duration_ms": round(avg_ms, 2),
            "min_duration_ms": round(self.min_duration_ms, 2) if self.min_duration_ms != float("inf") else 0.0,
            "max_duration_ms": round(self.max_duration_ms, 2),
            "stage_metrics": dict(self.stage_metrics),
            "uptime_seconds": round(time.time() - self.start_time, 1),
        }


class PipelineStage:
    """A single stage in the evaluation pipeline."""

    def __init__(
        self,
        name: str,
        stage_type: StageType,
        handler: Callable,
        timeout_ms: int = 3000,
        required: bool = True,
        order: int = 0,
        description: str = "",
    ):
        self.name = name
        self.stage_type = stage_type
        self.handler = handler
        self.timeout_ms = timeout_ms
        self.required = required
        self.order = order
        self.description = description
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    async def execute(
        self,
        context: PipelineContext,
        metrics: Optional[PipelineMetrics] = None,
    ) -> StageResult:
        if not self._enabled:
            return StageResult(
                stage_name=self.name,
                stage_type=self.stage_type,
                status=StageStatus.SKIPPED,
                start_time=time.time(),
            )

        result = StageResult(
            stage_name=self.name,
            stage_type=self.stage_type,
            status=StageStatus.PENDING,
            start_time=time.time(),
        )

        try:
            result.status = StageStatus.RUNNING
            stage_start = time.time()

            if asyncio.iscoroutinefunction(self.handler):
                stage_output = await asyncio.wait_for(
                    self.handler(context),
                    timeout=self.timeout_ms / 1000.0,
                )
            else:
                loop = asyncio.get_event_loop()
                stage_output = await asyncio.wait_for(
                    loop.run_in_executor(None, self.handler, context),
                    timeout=self.timeout_ms / 1000.0,
                )

            result.end_time = time.time()
            result.duration_ms = (result.end_time - stage_start) * 1000

            if stage_output is not None:
                if isinstance(stage_output, ValidationResult):
                    context.result = stage_output
                result.result = stage_output if isinstance(stage_output, ValidationResult) else None
                result.output_size = 1

            result.status = StageStatus.COMPLETED

        except asyncio.TimeoutError:
            result.end_time = time.time()
            result.duration_ms = (result.end_time - result.start_time) * 1000
            result.status = StageStatus.TIMEOUT
            result.error = f"Stage timed out after {self.timeout_ms}ms"
            if metrics:
                metrics.record_stage(self.name, result.duration_ms, StageStatus.TIMEOUT)

            if self.required:
                raise StageTimeoutError(f"Required stage '{self.name}' timed out")

        except Exception as e:
            result.end_time = time.time()
            result.duration_ms = (result.end_time - result.start_time) * 1000
            result.status = StageStatus.FAILED
            result.error = str(e)
            logger.error(f"Stage '{self.name}' failed: {e}\n{traceback.format_exc()}")

            if metrics:
                metrics.record_stage(self.name, result.duration_ms, StageStatus.FAILED)

            if self.required:
                raise StageExecutionError(f"Required stage '{self.name}' failed: {e}")

        if metrics and result.status not in (StageStatus.FAILED, StageStatus.TIMEOUT):
            metrics.record_stage(self.name, result.duration_ms, result.status)

        context.add_stage_result(result)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "stage_type": self.stage_type.value,
            "timeout_ms": self.timeout_ms,
            "required": self.required,
            "order": self.order,
            "description": self.description,
            "enabled": self._enabled,
        }


@dataclass
class PipelineTemplate:
    """Template for defining pipeline stage configurations."""

    template_id: str
    name: str
    description: str
    stages: List[Dict[str, Any]] = field(default_factory=list)
    default_timeout_ms: int = 3000
    parallel_stages: bool = False
    fail_on_stage_error: bool = False
    collect_metrics: bool = True
    tags: List[str] = field(default_factory=list)

    def add_stage_definition(
        self,
        name: str,
        stage_type: str,
        timeout_ms: Optional[int] = None,
        required: bool = True,
        order: int = 0,
    ) -> "PipelineTemplate":
        self.stages.append({
            "name": name,
            "stage_type": stage_type,
            "timeout_ms": timeout_ms or self.default_timeout_ms,
            "required": required,
            "order": order,
        })
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "stages": self.stages,
            "default_timeout_ms": self.default_timeout_ms,
            "parallel_stages": self.parallel_stages,
            "fail_on_stage_error": self.fail_on_stage_error,
            "collect_metrics": self.collect_metrics,
            "tags": self.tags,
        }


class EvaluationPipeline:
    """Multi-stage evaluation pipeline for rule processing."""

    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        self._stages: Dict[str, PipelineStage] = {}
        self._stage_order: List[str] = []
        self._templates: Dict[str, PipelineTemplate] = {}
        self._metrics = PipelineMetrics()
        self._running = False
        self._concurrent_pipelines: int = 0
        self._max_concurrent = self.config.get_int("pipeline.max_concurrent_pipelines", 10)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._global_pre_hooks: List[Callable] = []
        self._global_post_hooks: List[Callable] = []
        self._default_timeout_ms = self.config.get_int("pipeline.timeout_per_stage_ms", 3000)
        self._fail_on_stage_error = self.config.get_bool("pipeline.fail_on_stage_error", False)
        self._parallel_stages = self.config.get_bool("pipeline.parallel_stages", False)
        self._collect_metrics = self.config.get_bool("pipeline.collect_metrics", True)
        self._stage_timeout_behavior = self.config.get("pipeline.stage_timeout_behavior", "skip")

        logger.info(
            f"EvaluationPipeline initialized with {self._max_concurrent} max concurrent, "
            f"fail_on_error={self._fail_on_stage_error}, parallel={self._parallel_stages}"
        )

    def add_stage(
        self,
        name: str,
        stage_type: StageType,
        handler: Callable,
        timeout_ms: Optional[int] = None,
        required: bool = True,
        order: Optional[int] = None,
        description: str = "",
    ) -> PipelineStage:
        if name in self._stages:
            logger.warning(f"Stage '{name}' already exists, overwriting")
        actual_order = order if order is not None else len(self._stages)
        stage = PipelineStage(
            name=name,
            stage_type=stage_type,
            handler=handler,
            timeout_ms=timeout_ms or self._default_timeout_ms,
            required=required,
            order=actual_order,
            description=description,
        )
        self._stages[name] = stage
        if name not in self._stage_order:
            self._stage_order.append(name)
        self._stage_order.sort(key=lambda n: self._stages[n].order)
        logger.info(f"Stage '{name}' added (type={stage_type.value}, order={actual_order})")
        return stage

    def remove_stage(self, name: str) -> bool:
        if name in self._stages:
            del self._stages[name]
            self._stage_order = [n for n in self._stage_order if n != name]
            logger.info(f"Stage '{name}' removed")
            return True
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        return self._stages.get(name)

    def enable_stage(self, name: str) -> bool:
        stage = self._stages.get(name)
        if stage:
            stage.enable()
            return True
        return False

    def disable_stage(self, name: str) -> bool:
        stage = self._stages.get(name)
        if stage:
            stage.disable()
            return True
        return False

    def add_pre_hook(self, hook: Callable[[PipelineContext], PipelineContext]) -> None:
        self._global_pre_hooks.append(hook)

    def add_post_hook(self, hook: Callable[[PipelineContext], None]) -> None:
        self._global_post_hooks.append(hook)

    def register_template(self, template: PipelineTemplate) -> None:
        self._templates[template.template_id] = template
        logger.info(f"Pipeline template '{template.template_id}' registered")

    def get_template(self, template_id: str) -> Optional[PipelineTemplate]:
        return self._templates.get(template_id)

    def apply_template(self, template_id: str) -> bool:
        template = self._templates.get(template_id)
        if not template:
            logger.error(f"Template '{template_id}' not found")
            return False
        self._clear_stages()
        for stage_def in template.stages:
            stage_type = StageType(stage_def.get("stage_type", "custom"))
            self.add_stage(
                name=stage_def["name"],
                stage_type=stage_type,
                handler=self._create_default_handler(stage_type),
                timeout_ms=stage_def.get("timeout_ms"),
                required=stage_def.get("required", True),
                order=stage_def.get("order"),
            )
        self._parallel_stages = template.parallel_stages
        self._fail_on_stage_error = template.fail_on_stage_error
        self._collect_metrics = template.collect_metrics
        logger.info(f"Pipeline template '{template_id}' applied ({len(template.stages)} stages)")
        return True

    def _clear_stages(self) -> None:
        self._stages.clear()
        self._stage_order.clear()

    def _create_default_handler(self, stage_type: StageType) -> Callable:
        async def default_handler(context: PipelineContext) -> Optional[ValidationResult]:
            return context.result
        return default_handler

    def get_ordered_stages(self) -> List[PipelineStage]:
        return [self._stages[name] for name in self._stage_order if name in self._stages]

    def set_parallel_stages(self, enabled: bool) -> None:
        self._parallel_stages = enabled

    def set_fail_on_stage_error(self, fail: bool) -> None:
        self._fail_on_stage_error = fail

    def set_stage_timeout_behavior(self, behavior: str) -> None:
        if behavior not in ("skip", "fail", "retry"):
            raise ValueError(f"Invalid timeout behavior: {behavior}")
        self._stage_timeout_behavior = behavior

    async def execute(
        self,
        request: RuleEvaluationRequest,
        pipeline_id: Optional[str] = None,
    ) -> PipelineContext:
        async with self._semaphore:
            self._concurrent_pipelines += 1
            try:
                return await self._execute_internal(request, pipeline_id)
            finally:
                self._concurrent_pipelines -= 1

    async def _execute_internal(
        self,
        request: RuleEvaluationRequest,
        pipeline_id: Optional[str] = None,
    ) -> PipelineContext:
        start_time = time.time()
        context = PipelineContext(
            request=request,
            start_time=start_time,
            pipeline_id=pipeline_id or f"pipe_{int(start_time * 1000)}",
            parallel_stages=self._parallel_stages,
        )

        for hook in self._global_pre_hooks:
            try:
                context = hook(context)
            except Exception as e:
                logger.error(f"Pre-hook failed: {e}")

        ordered_stages = self.get_ordered_stages()
        if not ordered_stages:
            logger.warning("No stages configured in pipeline")
            context.result = ValidationResult(
                valid=True,
                total_score=1.0,
                confidence=1.0,
            )
            return context

        try:
            if self._parallel_stages:
                await self._execute_parallel(context, ordered_stages)
            else:
                await self._execute_sequential(context, ordered_stages)
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            if not context.result:
                context.result = ValidationResult(
                    valid=False,
                    total_score=0.0,
                    confidence=0.0,
                )

        total_duration_ms = (time.time() - start_time) * 1000
        all_completed = all(
            sr.status == StageStatus.COMPLETED
            for sr in context.stage_results.values()
        )
        any_failed = any(
            sr.status in (StageStatus.FAILED, StageStatus.TIMEOUT)
            for sr in context.stage_results.values()
        )

        if self._collect_metrics:
            self._metrics.record_pipeline(
                total_duration_ms,
                success=all_completed,
                partial=not all_completed and not any_failed,
            )

        for hook in self._global_post_hooks:
            try:
                hook(context)
            except Exception as e:
                logger.error(f"Post-hook failed: {e}")

        context.metadata["total_duration_ms"] = round(total_duration_ms, 2)
        context.metadata["stage_count"] = len(ordered_stages)
        context.metadata["completed_stages"] = sum(
            1 for sr in context.stage_results.values() if sr.status == StageStatus.COMPLETED
        )

        return context

    async def _execute_sequential(
        self,
        context: PipelineContext,
        stages: List[PipelineStage],
    ) -> None:
        for stage in stages:
            try:
                stage_result = await stage.execute(context, self._metrics if self._collect_metrics else None)
                if stage_result.status in (StageStatus.FAILED, StageStatus.TIMEOUT):
                    if self._fail_on_stage_error and stage.required:
                        raise StageExecutionError(
                            f"Pipeline failed at stage '{stage.name}': {stage_result.error}"
                        )
                    if self._stage_timeout_behavior == "fail":
                        break
            except (StageExecutionError, StageTimeoutError):
                if self._fail_on_stage_error:
                    raise
                break
            except Exception as e:
                logger.error(f"Unexpected error in stage '{stage.name}': {e}")
                if self._fail_on_stage_error:
                    raise

    async def _execute_parallel(
        self,
        context: PipelineContext,
        stages: List[PipelineStage],
    ) -> None:
        stage_groups: Dict[int, List[PipelineStage]] = {}
        for stage in stages:
            if stage.order not in stage_groups:
                stage_groups[stage.order] = []
            stage_groups[stage.order].append(stage)

        for order in sorted(stage_groups.keys()):
            group = stage_groups[order]
            tasks = []
            for stage in group:
                task = asyncio.create_task(
                    stage.execute(context, self._metrics if self._collect_metrics else None)
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    if self._fail_on_stage_error:
                        raise StageExecutionError(f"Parallel stage failed: {result}")
                    logger.error(f"Parallel stage error: {result}")
                elif isinstance(result, StageResult):
                    if result.status in (StageStatus.FAILED, StageStatus.TIMEOUT) and self._fail_on_stage_error:
                        raise StageExecutionError(f"Stage '{result.stage_name}' failed: {result.error}")

    async def execute_batch(
        self,
        requests: List[RuleEvaluationRequest],
        pipeline_id_prefix: str = "batch",
    ) -> List[PipelineContext]:
        results: List[PipelineContext] = []
        for i, request in enumerate(requests):
            try:
                ctx = await self.execute(request, pipeline_id=f"{pipeline_id_prefix}_{i}")
                results.append(ctx)
            except Exception as e:
                logger.error(f"Batch pipeline {i} failed: {e}")
                results.append(PipelineContext(
                    request=request,
                    result=ValidationResult(valid=False, total_score=0.0, confidence=0.0),
                ))
        return results

    async def execute_with_template(
        self,
        request: RuleEvaluationRequest,
        template_id: str,
    ) -> PipelineContext:
        saved_stages = dict(self._stages)
        saved_order = list(self._stage_order)
        try:
            self.apply_template(template_id)
            return await self.execute(request)
        finally:
            self._stages = saved_stages
            self._stage_order = saved_order

    def get_stage_types(self) -> Dict[StageType, List[str]]:
        grouped: Dict[StageType, List[str]] = defaultdict(list)
        for name, stage in self._stages.items():
            grouped[stage.stage_type].append(name)
        return dict(grouped)

    def get_config(self) -> Dict[str, Any]:
        return {
            "max_concurrent": self._max_concurrent,
            "fail_on_stage_error": self._fail_on_stage_error,
            "parallel_stages": self._parallel_stages,
            "collect_metrics": self._collect_metrics,
            "default_timeout_ms": self._default_timeout_ms,
            "stage_timeout_behavior": self._stage_timeout_behavior,
            "stage_count": len(self._stages),
            "template_count": len(self._templates),
        }

    def get_metrics(self) -> Dict[str, Any]:
        return self._metrics.to_dict()

    def get_stage_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for name in self._stage_order:
            stage = self._stages.get(name)
            if stage:
                summary[name] = stage.to_dict()
        return summary

    def get_templates(self) -> Dict[str, Dict[str, Any]]:
        return {tid: tmpl.to_dict() for tid, tmpl in self._templates.items()}

    async def health_check(self) -> Dict[str, Any]:
        status = "healthy"
        issues = []
        details: Dict[str, Any] = {
            "stage_count": len(self._stages),
            "template_count": len(self._templates),
            "concurrent_pipelines": self._concurrent_pipelines,
            "max_concurrent": self._max_concurrent,
            "parallel_stages": self._parallel_stages,
            "fail_on_stage_error": self._fail_on_stage_error,
        }
        if not self._stages:
            issues.append("No stages configured")
            status = "degraded"
        if self._concurrent_pipelines >= self._max_concurrent * 0.9:
            issues.append("Near max concurrent capacity")
            status = "degraded"
        return {
            "status": status,
            "pipeline": "EvaluationPipeline",
            "issues": issues,
            "details": details,
            "metrics": self._metrics.to_dict(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def to_prometheus(self) -> str:
        metrics = self._metrics
        lines = [
            "# HELP evaluation_pipeline_total Total pipeline executions",
            "# TYPE evaluation_pipeline_total counter",
            f"evaluation_pipeline_total {metrics.total_pipelines}",
            "# HELP evaluation_pipeline_completed Completed pipelines",
            "# TYPE evaluation_pipeline_completed counter",
            f"evaluation_pipeline_completed {metrics.completed_pipelines}",
            "# HELP evaluation_pipeline_failed Failed pipelines",
            "# TYPE evaluation_pipeline_failed counter",
            f"evaluation_pipeline_failed {metrics.failed_pipelines}",
            "# HELP evaluation_pipeline_partial Partial pipelines",
            "# TYPE evaluation_pipeline_partial counter",
            f"evaluation_pipeline_partial {metrics.partial_pipelines}",
            "# HELP evaluation_pipeline_success_rate Success rate",
            "# TYPE evaluation_pipeline_success_rate gauge",
            f"evaluation_pipeline_success_rate {metrics.completed_pipelines / max(metrics.total_pipelines, 1)}",
            "# HELP evaluation_pipeline_average_duration_ms Average pipeline duration",
            "# TYPE evaluation_pipeline_average_duration_ms gauge",
            f"evaluation_pipeline_average_duration_ms {metrics.total_duration_ms / max(metrics.total_pipelines, 1)}",
        ]
        for stage_name, stage_metrics in metrics.stage_metrics.items():
            lines.extend([
                f'evaluation_pipeline_stage_count{{stage="{stage_name}"}} {stage_metrics["count"]}',
                f'evaluation_pipeline_stage_failures{{stage="{stage_name}"}} {stage_metrics["failures"]}',
                f'evaluation_pipeline_stage_timeouts{{stage="{stage_name}"}} {stage_metrics["timeouts"]}',
            ])
        return "\n".join(lines)

    def get_pipeline_context(self, request: RuleEvaluationRequest) -> PipelineContext:
        return PipelineContext(
            request=request,
            start_time=time.time(),
            pipeline_id=f"pipe_{int(time.time() * 1000)}",
            parallel_stages=self._parallel_stages,
        )
