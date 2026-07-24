"""
Debug tool for step-by-step rule evaluation tracing, pattern matching,
performance profiling, memory tracking, and debug data export.
"""

import gc
import json
import logging
import os
import pprint
import time
import traceback
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.conflict import ConflictType, RuleConflict
from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import ValidationResult, Violation

logger = logging.getLogger(__name__)


class DebugLevel(str, Enum):
    """Level of debug detail to capture."""
    MINIMAL = "minimal"
    NORMAL = "normal"
    VERBOSE = "verbose"
    EXTREME = "extreme"


class TraceEventType(str, Enum):
    """Types of trace events in the debug log."""
    EVALUATION_START = "evaluation_start"
    EVALUATION_END = "evaluation_end"
    RULE_MATCH = "rule_match"
    RULE_MISMATCH = "rule_mismatch"
    PATTERN_CHECK = "pattern_check"
    CONDITION_CHECK = "condition_check"
    EXCEPTION_CHECK = "exception_check"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    TIMEOUT = "timeout"
    ERROR = "error"
    ACTION_TAKEN = "action_taken"
    CONTEXT_LOOKUP = "context_lookup"
    DEPENDENCY_CHECK = "dependency_check"
    CONFLICT_DETECTED = "conflict_detected"


@dataclass
class DebugConfig:
    """Configuration for the debug tool."""
    debug_level: DebugLevel = DebugLevel.NORMAL
    enabled: bool = True
    trace_max_events: int = 10000
    capture_pattern_details: bool = True
    capture_context_snapshot: bool = True
    capture_performance: bool = True
    capture_memory: bool = False
    export_on_complete: bool = False
    export_format: str = "json"
    export_dir: Optional[str] = None
    color_output: bool = True
    log_to_file: bool = False
    log_file_path: Optional[str] = None
    filter_rule_ids: List[str] = field(default_factory=list)
    filter_tiers: List[RuleTier] = field(default_factory=list)
    filter_event_types: List[TraceEventType] = field(default_factory=list)
    stack_trace_on_error: bool = True
    max_context_depth: int = 5
    show_hidden_patterns: bool = False
    indent_size: int = 2
    trace_timer_precision: int = 4


@dataclass
class TraceEvent:
    """A single trace event in the debug log."""
    event_id: str
    event_type: TraceEventType
    timestamp: float
    rule_id: Optional[str]
    rule_name: Optional[str]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    memory_delta: Optional[int] = None
    depth: int = 0
    thread_id: Optional[int] = None
    parent_event_id: Optional[str] = None


@dataclass
class RuleMatchTrace:
    """Detailed trace of a rule matching attempt."""
    rule_id: str
    rule_name: str
    matched: bool
    match_score: float
    patterns_checked: int
    patterns_matched: int
    conditions_evaluated: int
    conditions_passed: int
    exceptions_checked: int
    exception_matched: bool
    duration_ms: float
    context_keys_used: List[str]
    action_taken: Optional[str]
    events: List[TraceEvent] = field(default_factory=list)


@dataclass
class DebugSession:
    """Complete debug session data."""
    session_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    config_snapshot: Dict[str, Any]
    trace_events: List[TraceEvent]
    rule_traces: List[RuleMatchTrace]
    summary: Dict[str, Any]
    errors: List[Dict[str, Any]]
    memory_snapshots: List[Dict[str, Any]]
    export_filepath: Optional[str] = None


class PatternMatchTracker:
    """Tracks pattern matching with detailed context."""

    def __init__(self, config: DebugConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.PatternMatchTracker")

    def trace_pattern_match(self, rule: Rule, pattern: RulePattern, input_text: str, matched: bool, details: Dict) -> TraceEvent:
        event_id = f"PM-{uuid.uuid4().hex[:8]}"
        keyword_matches = []
        regex_matches = []
        if matched and self.config.capture_pattern_details:
            for kw in pattern.keywords:
                if kw.lower() in input_text.lower():
                    keyword_matches.append(kw)
            for regex_str in pattern.regex_patterns:
                try:
                    import re
                    if re.search(regex_str, input_text, re.IGNORECASE):
                        regex_matches.append(regex_str)
                except re.error:
                    pass
        detail_data = {
            "pattern_type": pattern.type.value if pattern.type else "unknown",
            "keywords": pattern.keywords[:10],
            "regex_patterns": pattern.regex_patterns[:5],
            "matched": matched,
            "keyword_matches": keyword_matches,
            "regex_matches": regex_matches,
            "confidence_threshold": pattern.confidence_threshold,
            "action": pattern.action,
        }
        if self.config.capture_context_snapshot:
            detail_data["input_preview"] = input_text[:200]
        return TraceEvent(
            event_id=event_id,
            event_type=TraceEventType.PATTERN_CHECK,
            timestamp=time.time(),
            rule_id=rule.id,
            rule_name=rule.name,
            message=f"Pattern {'matched' if matched else 'did not match'} for rule '{rule.name}'",
            details=detail_data,
        )

    def trace_condition_check(self, rule: Rule, condition_key: str, condition_value: Any, context: Dict, passed: bool) -> TraceEvent:
        return TraceEvent(
            event_id=f"CC-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.CONDITION_CHECK,
            timestamp=time.time(),
            rule_id=rule.id,
            rule_name=rule.name,
            message=f"Condition '{condition_key}' {'passed' if passed else 'failed'}",
            details={
                "condition_key": condition_key,
                "condition_value": condition_value,
                "context_value": context.get(condition_key),
                "passed": passed,
            },
        )

    def trace_exception_check(self, rule: Rule, content: str, is_exception: bool) -> TraceEvent:
        return TraceEvent(
            event_id=f"EC-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.EXCEPTION_CHECK,
            timestamp=time.time(),
            rule_id=rule.id,
            rule_name=rule.name,
            message=f"Exception {'matched' if is_exception else 'not matched'} for rule '{rule.name}'",
            details={
                "exception_count": len(rule.exceptions),
                "is_exception": is_exception,
            },
        )


class PerformanceProfiler:
    """Per-rule performance profiling during debug."""

    def __init__(self, config: DebugConfig):
        self.config = config
        self._timers: Dict[str, float] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._accumulators: Dict[str, float] = defaultdict(float)
        self._max_times: Dict[str, float] = {}
        self.logger = logging.getLogger(f"{__name__}.PerformanceProfiler")

    def start_timer(self, timer_id: str) -> None:
        self._timers[timer_id] = time.perf_counter()

    def stop_timer(self, timer_id: str) -> float:
        start = self._timers.pop(timer_id, None)
        if start is None:
            return 0.0
        elapsed = time.perf_counter() - start
        self._counters[timer_id] += 1
        self._accumulators[timer_id] += elapsed
        if timer_id not in self._max_times or elapsed > self._max_times[timer_id]:
            self._max_times[timer_id] = elapsed
        return elapsed

    def increment_counter(self, counter_id: str, count: int = 1) -> None:
        self._counters[counter_id] += count

    def get_stats(self, timer_id: str) -> Dict[str, Any]:
        count = self._counters.get(timer_id, 0)
        total = self._accumulators.get(timer_id, 0.0)
        return {
            "timer_id": timer_id,
            "count": count,
            "total_seconds": round(total, self.config.trace_timer_precision),
            "avg_seconds": round(total / count, self.config.trace_timer_precision) if count > 0 else 0.0,
            "max_seconds": round(self._max_times.get(timer_id, 0.0), self.config.trace_timer_precision),
        }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        all_ids = set(list(self._counters.keys()) + list(self._accumulators.keys()) + list(self._max_times.keys()))
        return {tid: self.get_stats(tid) for tid in all_ids}

    def reset(self) -> None:
        self._timers.clear()
        self._counters.clear()
        self._accumulators.clear()
        self._max_times.clear()

    def get_summary(self) -> Dict[str, Any]:
        total_time = sum(self._accumulators.values())
        total_calls = sum(self._counters.values())
        return {
            "total_time_seconds": round(total_time, self.config.trace_timer_precision),
            "total_calls": total_calls,
            "avg_time_per_call": round(total_time / total_calls, self.config.trace_timer_precision) if total_calls > 0 else 0.0,
            "slowest_operation": max(self._max_times, key=self._max_times.get) if self._max_times else None,
            "slowest_time": round(max(self._max_times.values()), self.config.trace_timer_precision) if self._max_times else 0.0,
        }


class MemoryTracker:
    """Tracks memory usage during debug sessions."""

    def __init__(self, config: DebugConfig):
        self.config = config
        self._snapshots: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(f"{__name__}.MemoryTracker")

    def take_snapshot(self, label: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        snapshot = {
            "timestamp": time.time(),
            "datetime": datetime.utcnow().isoformat(),
            "label": label,
        }
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            snapshot["rss_bytes"] = mem_info.rss
            snapshot["vms_bytes"] = mem_info.vms
            snapshot["percent"] = process.memory_percent()
        except ImportError:
            import tracemalloc
            if tracemalloc.is_tracing():
                size, peak = tracemalloc.get_traced_memory()
                snapshot["traced_current_bytes"] = size
                snapshot["traced_peak_bytes"] = peak
        gc.collect()
        snapshot["gc_objects"] = len(gc.get_objects())
        if context:
            snapshot["context"] = context
        self._snapshots.append(snapshot)
        return snapshot

    def get_snapshots(self) -> List[Dict[str, Any]]:
        return list(self._snapshots)

    def get_delta(self, idx_a: int = 0, idx_b: int = -1) -> Optional[Dict[str, Any]]:
        if len(self._snapshots) < 2:
            return None
        snap_a = self._snapshots[idx_a]
        snap_b = self._snapshots[idx_b]
        delta = {
            "from_label": snap_a.get("label"),
            "to_label": snap_b.get("label"),
            "time_delta": snap_b["timestamp"] - snap_a["timestamp"],
        }
        if "rss_bytes" in snap_a and "rss_bytes" in snap_b:
            delta["rss_delta_bytes"] = snap_b["rss_bytes"] - snap_a["rss_bytes"]
            delta["rss_delta_mb"] = (snap_b["rss_bytes"] - snap_a["rss_bytes"]) / (1024 * 1024)
        if "gc_objects" in snap_a and "gc_objects" in snap_b:
            delta["gc_objects_delta"] = snap_b["gc_objects"] - snap_a["gc_objects"]
        return delta

    def get_memory_summary(self) -> Dict[str, Any]:
        if not self._snapshots:
            return {"error": "no snapshots taken"}
        first = self._snapshots[0]
        last = self._snapshots[-1]
        summary = {
            "snapshot_count": len(self._snapshots),
            "first_snapshot": first.get("label"),
            "last_snapshot": last.get("label"),
            "duration_seconds": last["timestamp"] - first["timestamp"],
        }
        if "rss_bytes" in first and "rss_bytes" in last:
            summary["rss_start_mb"] = first["rss_bytes"] / (1024 * 1024)
            summary["rss_end_mb"] = last["rss_bytes"] / (1024 * 1024)
            summary["rss_delta_mb"] = (last["rss_bytes"] - first["rss_bytes"]) / (1024 * 1024)
        if "gc_objects" in first and "gc_objects" in last:
            summary["gc_objects_start"] = first["gc_objects"]
            summary["gc_objects_end"] = last["gc_objects"]
            summary["gc_objects_delta"] = last["gc_objects"] - first["gc_objects"]
        max_rss = max(s.get("rss_bytes", 0) for s in self._snapshots if "rss_bytes" in s)
        if max_rss > 0:
            summary["peak_rss_mb"] = max_rss / (1024 * 1024)
        return summary


class EventFormatter:
    """Formats debug events for console output."""

    def __init__(self, config: DebugConfig):
        self.config = config

    def format_event(self, event: TraceEvent, include_timestamp: bool = True) -> str:
        parts = []
        indent = "  " * event.depth
        prefix = f"{indent}[{event.event_type.value}]"
        if include_timestamp:
            ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S.%f")[:12]
            prefix = f"{ts} {prefix}"
        parts.append(prefix)
        if event.rule_name:
            parts.append(f"rule={event.rule_name}")
        parts.append(f"msg={event.message}")
        if event.duration_ms is not None:
            parts.append(f"({event.duration_ms:.2f}ms)")
        line = " ".join(parts)
        if self.config.color_output:
            color_map = {
                TraceEventType.ERROR: "\x1b[31m",
                TraceEventType.EVALUATION_START: "\x1b[36m",
                TraceEventType.EVALUATION_END: "\x1b[36m",
                TraceEventType.RULE_MATCH: "\x1b[32m",
                TraceEventType.RULE_MISMATCH: "\x1b[33m",
                TraceEventType.CACHE_HIT: "\x1b[35m",
                TraceEventType.CACHE_MISS: "\x1b[35m",
                TraceEventType.TIMEOUT: "\x1b[31m",
            }
            color = color_map.get(event.event_type, "")
            if color:
                line = f"{color}{line}\x1b[0m"
        return line

    def format_rule_trace(self, trace: RuleMatchTrace, verbose: bool = False) -> str:
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"RULE: {trace.rule_name} ({trace.rule_id})")
        lines.append(f"{'='*60}")
        lines.append(f"  Matched: {trace.matched}")
        lines.append(f"  Score: {trace.match_score:.2%}")
        lines.append(f"  Duration: {trace.duration_ms:.2f}ms")
        lines.append(f"  Patterns: {trace.patterns_matched}/{trace.patterns_checked}")
        lines.append(f"  Conditions: {trace.conditions_passed}/{trace.conditions_evaluated}")
        lines.append(f"  Exceptions: {trace.exception_matched} matched / {trace.exceptions_checked} checked")
        lines.append(f"  Action: {trace.action_taken or 'none'}")
        if verbose:
            lines.append(f"  Context keys used: {', '.join(trace.context_keys_used) if trace.context_keys_used else 'none'}")
            lines.append("  Events:")
            for event in trace.events[:20]:
                lines.append(f"    {self.format_event(event)}")
            if len(trace.events) > 20:
                lines.append(f"    ... ({len(trace.events) - 20} more events)")
        lines.append("")
        return "\n".join(lines)

    def format_session_summary(self, session: DebugSession) -> str:
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"DEBUG SESSION: {session.session_id}")
        lines.append(f"{'='*60}")
        lines.append(f"  Started: {session.started_at.isoformat()}")
        if session.finished_at:
            lines.append(f"  Finished: {session.finished_at.isoformat()}")
            duration = (session.finished_at - session.started_at).total_seconds()
            lines.append(f"  Duration: {duration:.2f}s")
        lines.append(f"  Events: {len(session.trace_events)}")
        lines.append(f"  Rule traces: {len(session.rule_traces)}")
        lines.append(f"  Errors: {len(session.errors)}")
        lines.append(f"  Memory snapshots: {len(session.memory_snapshots)}")
        lines.append("")
        lines.append("  SUMMARY:")
        for key, value in session.summary.items():
            lines.append(f"    {key}: {value}")
        lines.append("")
        if session.export_filepath:
            lines.append(f"  Exported to: {session.export_filepath}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


class DebugTool:
    """
    Debug tool for rule evaluation with step-by-step tracing,
    pattern matching details, performance profiling, and memory tracking.
    """

    def __init__(self, config: Optional[DebugConfig] = None):
        self.config = config or DebugConfig()
        self._pattern_tracker = PatternMatchTracker(self.config)
        self._perf_profiler = PerformanceProfiler(self.config)
        self._memory_tracker = MemoryTracker(self.config)
        self._event_formatter = EventFormatter(self.config)
        self._trace_events: List[TraceEvent] = []
        self._rule_traces: List[RuleMatchTrace] = []
        self._errors: List[Dict[str, Any]] = []
        self._session: Optional[DebugSession] = None
        self._active: bool = self.config.enabled
        self._event_count: int = 0
        self.logger = logging.getLogger(f"{__name__}.DebugTool")

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._pattern_tracker = PatternMatchTracker(self.config)
        self._perf_profiler.reset()
        self._event_formatter = EventFormatter(self.config)
        self.logger.info("Debug config updated with %d changes", len(config_updates))

    def start_session(self, label: Optional[str] = None) -> str:
        session_id = f"DEBUG-{uuid.uuid4().hex[:12]}"
        self._session = DebugSession(
            session_id=session_id,
            started_at=datetime.utcnow(),
            finished_at=None,
            config_snapshot=self._config_to_dict(),
            trace_events=[],
            rule_traces=[],
            summary={},
            errors=[],
            memory_snapshots=[],
        )
        self._trace_events = []
        self._rule_traces = []
        self._errors = []
        self._event_count = 0
        self._perf_profiler.reset()
        self._active = True
        if self.config.capture_memory:
            self._memory_tracker.take_snapshot("session_start", {"session_id": session_id, "label": label})
            self._session.memory_snapshots = self._memory_tracker.get_snapshots()
        start_event = TraceEvent(
            event_id=f"START-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.EVALUATION_START,
            timestamp=time.time(),
            rule_id=None,
            rule_name=None,
            message=f"Debug session started: {label or session_id}",
            details={"label": label, "session_id": session_id},
        )
        self._add_event(start_event)
        self.logger.info("Debug session started: %s", session_id)
        return session_id

    def end_session(self) -> DebugSession:
        if not self._session:
            raise RuntimeError("No active debug session")
        self._active = False
        end_event = TraceEvent(
            event_id=f"END-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.EVALUATION_END,
            timestamp=time.time(),
            rule_id=None,
            rule_name=None,
            message="Debug session ended",
        )
        self._add_event(end_event)
        if self.config.capture_memory:
            self._memory_tracker.take_snapshot("session_end")
            self._session.memory_snapshots = self._memory_tracker.get_snapshots()
        self._session.finished_at = datetime.utcnow()
        self._session.trace_events = list(self._trace_events)
        self._session.rule_traces = list(self._rule_traces)
        self._session.errors = list(self._errors)
        self._session.summary = self._build_summary()
        if self.config.export_on_complete:
            filepath = self._export_session(self._session)
            self._session.export_filepath = filepath
        self.logger.info(
            "Debug session ended: %s events, %d rule traces, %d errors",
            len(self._trace_events),
            len(self._rule_traces),
            len(self._errors),
        )
        return self._session

    def trace_rule_evaluation(
        self,
        rule: Rule,
        input_data: Union[str, Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> RuleMatchTrace:
        if not self._active or not self.config.enabled:
            return RuleMatchTrace(
                rule_id=rule.id, rule_name=rule.name, matched=False,
                match_score=0.0, patterns_checked=0, patterns_matched=0,
                conditions_evaluated=0, conditions_passed=0,
                exceptions_checked=0, exception_matched=False,
                duration_ms=0.0, context_keys_used=[], action_taken=None,
            )
        self._perf_profiler.start_timer(f"rule_{rule.id}")
        trace_events: List[TraceEvent] = []
        context = context or {}
        input_text = input_data if isinstance(input_data, str) else json.dumps(input_data)
        patterns_checked = 0
        patterns_matched = 0
        conditions_evaluated = 0
        conditions_passed = 0
        exceptions_checked = 0
        exception_matched = False
        matched = False
        action_taken = None
        context_keys_used = list(context.keys()) if self.config.capture_context_snapshot else []
        for pattern in rule.patterns:
            patterns_checked += 1
            pattern_matched = self._check_pattern(pattern, input_text, context)
            p_event = self._pattern_tracker.trace_pattern_match(rule, pattern, input_text, pattern_matched, {})
            if self.config.debug_level in (DebugLevel.VERBOSE, DebugLevel.EXTREME):
                trace_events.append(p_event)
            if pattern_matched:
                patterns_matched += 1
            if self.config.debug_level == DebugLevel.EXTREME:
                self._add_event(p_event)
        if patterns_matched > 0:
            matched = True
        for key, value in rule.conditions.items():
            conditions_evaluated += 1
            context_val = context.get(key)
            condition_passed = self._check_condition(key, value, context)
            c_event = self._pattern_tracker.trace_condition_check(rule, key, value, context, condition_passed)
            if self.config.debug_level in (DebugLevel.VERBOSE, DebugLevel.EXTREME):
                trace_events.append(c_event)
            if condition_passed:
                conditions_passed += 1
            else:
                matched = False
        if rule.exceptions:
            for exc in rule.exceptions:
                exceptions_checked += 1
                if exc in input_text:
                    exception_matched = True
                    matched = False
                    break
            exc_event = self._pattern_tracker.trace_exception_check(rule, input_text, exception_matched)
            if self.config.debug_level in (DebugLevel.VERBOSE, DebugLevel.EXTREME):
                trace_events.append(exc_event)
        if matched:
            action_taken = rule.patterns[0].action if rule.patterns else "warn"
            match_event = TraceEvent(
                event_id=f"MATCH-{uuid.uuid4().hex[:8]}",
                event_type=TraceEventType.RULE_MATCH,
                timestamp=time.time(),
                rule_id=rule.id,
                rule_name=rule.name,
                message=f"Rule '{rule.name}' matched",
                details={"match_score": patterns_matched / max(patterns_checked, 1)},
            )
            trace_events.append(match_event)
            self._add_event(match_event)
        else:
            mismatch_event = TraceEvent(
                event_id=f"MISM-{uuid.uuid4().hex[:8]}",
                event_type=TraceEventType.RULE_MISMATCH,
                timestamp=time.time(),
                rule_id=rule.id,
                rule_name=rule.name,
                message=f"Rule '{rule.name}' did not match",
                details={"patterns_matched": patterns_matched, "conditions_passed": conditions_passed},
            )
            if self.config.debug_level in (DebugLevel.VERBOSE, DebugLevel.EXTREME):
                trace_events.append(mismatch_event)
        duration_s = self._perf_profiler.stop_timer(f"rule_{rule.id}")
        duration_ms = duration_s * 1000
        rule_trace = RuleMatchTrace(
            rule_id=rule.id,
            rule_name=rule.name,
            matched=matched,
            match_score=patterns_matched / max(patterns_checked, 1) if patterns_checked > 0 else 0.0,
            patterns_checked=patterns_checked,
            patterns_matched=patterns_matched,
            conditions_evaluated=conditions_evaluated,
            conditions_passed=conditions_passed,
            exceptions_checked=exceptions_checked,
            exception_matched=exception_matched,
            duration_ms=duration_ms,
            context_keys_used=context_keys_used,
            action_taken=action_taken,
            events=trace_events,
        )
        self._rule_traces.append(rule_trace)
        return rule_trace

    def trace_evaluation_batch(
        self,
        rules: List[Rule],
        input_data: Union[str, Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleMatchTrace]:
        filtered_rules = self._filter_rules(rules)
        traces = []
        for rule in filtered_rules:
            trace = self.trace_rule_evaluation(rule, input_data, context)
            traces.append(trace)
        return traces

    def _check_pattern(self, pattern: RulePattern, input_text: str, context: Dict) -> bool:
        if pattern.keywords:
            for kw in pattern.keywords:
                if kw.lower() in input_text.lower():
                    return True
        if pattern.regex_patterns:
            import re
            for regex_str in pattern.regex_patterns:
                try:
                    if re.search(regex_str, input_text, re.IGNORECASE):
                        return True
                except re.error:
                    continue
        return False

    def _check_condition(self, key: str, value: Any, context: Dict) -> bool:
        context_val = context.get(key)
        if context_val is None:
            return False
        if isinstance(value, bool) and isinstance(context_val, bool):
            return context_val == value
        if isinstance(value, str) and isinstance(context_val, str):
            return context_val.lower() == value.lower()
        if isinstance(value, (int, float)) and isinstance(context_val, (int, float)):
            return context_val == value
        if isinstance(value, list):
            return context_val in value if not isinstance(context_val, list) else any(v in value for v in context_val)
        if isinstance(value, dict):
            return all(context_val.get(k) == v for k, v in value.items() if k in context_val)
        return str(context_val) == str(value)

    def _add_event(self, event: TraceEvent) -> None:
        if self._event_count >= self.config.trace_max_events:
            return
        self._trace_events.append(event)
        self._event_count += 1

    def _filter_rules(self, rules: List[Rule]) -> List[Rule]:
        filtered = list(rules)
        if self.config.filter_rule_ids:
            filtered = [r for r in filtered if r.id in self.config.filter_rule_ids]
        if self.config.filter_tiers:
            filtered = [r for r in filtered if r.tier in self.config.filter_tiers]
        return filtered

    def record_error(self, rule_id: Optional[str], error: Exception, context: Optional[Dict] = None) -> None:
        error_data = {
            "timestamp": time.time(),
            "datetime": datetime.utcnow().isoformat(),
            "rule_id": rule_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        if self.config.stack_trace_on_error:
            error_data["traceback"] = traceback.format_exc()
        if context:
            error_data["context"] = context
        self._errors.append(error_data)
        error_event = TraceEvent(
            event_id=f"ERR-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.ERROR,
            timestamp=time.time(),
            rule_id=rule_id,
            rule_name=None,
            message=f"Error: {type(error).__name__}: {error}",
            details=error_data,
        )
        self._add_event(error_event)
        self.logger.error("Debug error recorded for rule %s: %s", rule_id, error)

    def record_cache_event(self, rule_id: str, rule_name: str, hit: bool, key: Optional[str] = None) -> None:
        event = TraceEvent(
            event_id=f"CACHE-{uuid.uuid4().hex[:8]}",
            event_type=TraceEventType.CACHE_HIT if hit else TraceEventType.CACHE_MISS,
            timestamp=time.time(),
            rule_id=rule_id,
            rule_name=rule_name,
            message=f"Cache {'hit' if hit else 'miss'} for rule '{rule_name}'",
            details={"cache_key": key, "hit": hit},
        )
        self._add_event(event)

    def _build_summary(self) -> Dict[str, Any]:
        match_count = sum(1 for t in self._rule_traces if t.matched)
        mismatch_count = len(self._rule_traces) - match_count
        total_duration = sum(t.duration_ms for t in self._rule_traces)
        perf_summary = self._perf_profiler.get_summary()
        summary = {
            "total_events": len(self._trace_events),
            "total_rule_traces": len(self._rule_traces),
            "rules_matched": match_count,
            "rules_mismatched": mismatch_count,
            "total_evaluation_time_ms": round(total_duration, 2),
            "avg_rule_time_ms": round(total_duration / len(self._rule_traces), 2) if self._rule_traces else 0.0,
            "total_errors": len(self._errors),
            "perf_profile_time_seconds": perf_summary.get("total_time_seconds", 0),
            "memory_snapshots": len(self._session.memory_snapshots) if self._session else 0,
            "debug_level": self.config.debug_level.value,
        }
        if self._session and self._session.memory_snapshots:
            mem_summary = self._memory_tracker.get_memory_summary()
            summary["memory"] = mem_summary
        return summary

    def get_perf_stats(self) -> Dict[str, Any]:
        return self._perf_profiler.get_all_stats()

    def get_perf_summary(self) -> Dict[str, Any]:
        return self._perf_profiler.get_summary()

    def get_memory_snapshots(self) -> List[Dict[str, Any]]:
        return self._memory_tracker.get_snapshots()

    def get_memory_summary(self) -> Dict[str, Any]:
        return self._memory_tracker.get_memory_summary()

    def get_events_by_type(self, event_type: TraceEventType) -> List[TraceEvent]:
        return [e for e in self._trace_events if e.event_type == event_type]

    def get_events_by_rule(self, rule_id: str) -> List[TraceEvent]:
        return [e for e in self._trace_events if e.rule_id == rule_id]

    def get_traces_by_outcome(self, matched: bool) -> List[RuleMatchTrace]:
        return [t for t in self._rule_traces if t.matched == matched]

    def format_session_output(self, session: Optional[DebugSession] = None) -> str:
        target = session or self._session
        if not target:
            return "No debug session available"
        return self._event_formatter.format_session_summary(target)

    def format_rule_trace_output(self, trace: RuleMatchTrace, verbose: bool = False) -> str:
        return self._event_formatter.format_rule_trace(trace, verbose=verbose)

    def format_all_events(self, max_events: int = 100) -> str:
        lines = []
        for event in self._trace_events[:max_events]:
            lines.append(self._event_formatter.format_event(event))
        if len(self._trace_events) > max_events:
            lines.append(f"... ({len(self._trace_events) - max_events} more events)")
        return "\n".join(lines)

    def export_debug_data(self, session: Optional[DebugSession] = None, filepath: Optional[str] = None) -> str:
        target = session or self._session
        if not target:
            raise RuntimeError("No debug session to export")
        return self._export_session(target, filepath)

    def _export_session(self, session: DebugSession, filepath: Optional[str] = None) -> str:
        data = {
            "session_id": session.session_id,
            "started_at": session.started_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "config": session.config_snapshot,
            "summary": session.summary,
            "errors": session.errors,
            "memory_snapshots": session.memory_snapshots,
            "trace_events": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "timestamp": e.timestamp,
                    "rule_id": e.rule_id,
                    "rule_name": e.rule_name,
                    "message": e.message,
                    "details": e.details,
                    "duration_ms": e.duration_ms,
                    "depth": e.depth,
                }
                for e in session.trace_events
            ],
            "rule_traces": [
                {
                    "rule_id": t.rule_id,
                    "rule_name": t.rule_name,
                    "matched": t.matched,
                    "match_score": t.match_score,
                    "patterns_checked": t.patterns_checked,
                    "patterns_matched": t.patterns_matched,
                    "conditions_evaluated": t.conditions_evaluated,
                    "conditions_passed": t.conditions_passed,
                    "exceptions_checked": t.exceptions_checked,
                    "exception_matched": t.exception_matched,
                    "duration_ms": t.duration_ms,
                    "action_taken": t.action_taken,
                }
                for t in session.rule_traces
            ],
        }
        json_str = json.dumps(data, indent=2, default=str)
        if filepath or (self.config.export_dir and not filepath):
            export_dir = self.config.export_dir or "."
            path = Path(filepath) if filepath else Path(export_dir) / f"debug_{session.session_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json_str, encoding="utf-8")
            self.logger.info("Debug data exported to %s", path)
            return str(path)
        return json_str

    def load_debug_data(self, filepath: str) -> DebugSession:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Debug data file not found: {filepath}")
        data = json.loads(path.read_text(encoding="utf-8"))
        session = DebugSession(
            session_id=data["session_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
            config_snapshot=data.get("config", {}),
            trace_events=[
                TraceEvent(
                    event_id=e["event_id"],
                    event_type=TraceEventType(e["event_type"]),
                    timestamp=e["timestamp"],
                    rule_id=e.get("rule_id"),
                    rule_name=e.get("rule_name"),
                    message=e.get("message", ""),
                    details=e.get("details", {}),
                    duration_ms=e.get("duration_ms"),
                    depth=e.get("depth", 0),
                )
                for e in data.get("trace_events", [])
            ],
            rule_traces=[
                RuleMatchTrace(
                    rule_id=t["rule_id"],
                    rule_name=t["rule_name"],
                    matched=t["matched"],
                    match_score=t["match_score"],
                    patterns_checked=t["patterns_checked"],
                    patterns_matched=t["patterns_matched"],
                    conditions_evaluated=t["conditions_evaluated"],
                    conditions_passed=t["conditions_passed"],
                    exceptions_checked=t.get("exceptions_checked", 0),
                    exception_matched=t.get("exception_matched", False),
                    duration_ms=t["duration_ms"],
                    context_keys_used=t.get("context_keys_used", []),
                    action_taken=t.get("action_taken"),
                )
                for t in data.get("rule_traces", [])
            ],
            summary=data.get("summary", {}),
            errors=data.get("errors", []),
            memory_snapshots=data.get("memory_snapshots", []),
            export_filepath=filepath,
        )
        self._session = session
        self._trace_events = session.trace_events
        self._rule_traces = session.rule_traces
        self._errors = session.errors
        self.logger.info("Debug data loaded from %s", filepath)
        return session

    def _config_to_dict(self) -> Dict[str, Any]:
        return {
            "debug_level": self.config.debug_level.value,
            "enabled": self.config.enabled,
            "trace_max_events": self.config.trace_max_events,
            "capture_pattern_details": self.config.capture_pattern_details,
            "capture_context_snapshot": self.config.capture_context_snapshot,
            "capture_performance": self.config.capture_performance,
            "capture_memory": self.config.capture_memory,
            "export_on_complete": self.config.export_on_complete,
            "export_format": self.config.export_format,
            "filter_rule_ids": self.config.filter_rule_ids,
            "filter_tiers": [t.value for t in self.config.filter_tiers],
            "stack_trace_on_error": self.config.stack_trace_on_error,
        }

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "debug_level": {
                "type": "string",
                "enum": [e.value for e in DebugLevel],
                "default": "normal",
                "description": "Level of debug detail to capture",
            },
            "enabled": {
                "type": "boolean",
                "default": True,
            },
            "trace_max_events": {
                "type": "integer",
                "minimum": 100,
                "maximum": 100000,
                "default": 10000,
            },
            "capture_pattern_details": {"type": "boolean", "default": True},
            "capture_context_snapshot": {"type": "boolean", "default": True},
            "capture_performance": {"type": "boolean", "default": True},
            "capture_memory": {"type": "boolean", "default": False},
            "export_on_complete": {"type": "boolean", "default": False},
            "export_format": {"type": "string", "enum": ["json", "yaml"], "default": "json"},
            "filter_rule_ids": {"type": "array", "items": {"type": "string"}},
            "stack_trace_on_error": {"type": "boolean", "default": True},
            "color_output": {"type": "boolean", "default": True},
        }
