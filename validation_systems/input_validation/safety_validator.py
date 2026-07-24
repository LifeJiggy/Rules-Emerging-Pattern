"""Safety validation for content with multi-category dangerous pattern detection."""

import logging
import re
import time
import hashlib
import json
import threading
from collections import defaultdict, Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

logger = logging.getLogger(__name__)


class SafetyCategory(str, Enum):
    CHILD_SAFETY = "child_safety"
    WEAPONS = "weapons"
    SELF_HARM = "self_harm"
    VIOLENCE = "violence"
    TERRORISM = "terrorism"
    DRUGS = "drugs"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    EXPLICIT_CONTENT = "explicit_content"
    PERSONAL_INFO = "personal_info"
    FRAUD = "fraud"
    MALWARE = "malware"
    CYBERBULLYING = "cyberbullying"
    MISINFORMATION = "misinformation"
    SPAM = "spam"
    HUMAN_TRAFFICKING = "human_trafficking"
    GAMBLING = "gambling"
    ANIMAL_CRUELTY = "animal_cruelty"
    EXTREMISM = "extremism"
    CENSORSHIP_EVASION = "censorship_evasion"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyAction(str, Enum):
    NONE = "none"
    WARN = "warn"
    BLOCK = "block"
    REDACT = "redact"
    ESCALATE = "escalate"
    QUARANTINE = "quarantine"
    LOG_ONLY = "log_only"
    REVIEW = "review"


@dataclass
class SafetyViolation:
    category: SafetyCategory
    pattern_name: str
    matched_text: str
    severity: SeverityLevel
    message: str
    position_start: int = 0
    position_end: int = 0
    confidence: float = 1.0
    context: Optional[str] = None
    suggested_action: SafetyAction = SafetyAction.WARN
    timestamp: datetime = field(default_factory=datetime.utcnow)
    match_count: int = 1
    matched_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "pattern_name": self.pattern_name,
            "matched_text": self.matched_text,
            "severity": self.severity.value,
            "message": self.message,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "confidence": self.confidence,
            "context": self.context,
            "suggested_action": self.suggested_action.value,
            "timestamp": self.timestamp.isoformat(),
            "match_count": self.match_count,
        }


@dataclass
class SafetyPattern:
    name: str
    category: SafetyCategory
    regex: Pattern
    severity: SeverityLevel
    description: str
    action: SafetyAction = SafetyAction.WARN
    confidence: float = 1.0
    enabled: bool = True
    exempt_contexts: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    max_matches: int = 0
    case_sensitive: bool = False
    weight: float = 1.0

    def matches(self, content: str) -> List[Tuple[str, int, int]]:
        if not self.enabled:
            return []
        results = []
        flags = 0 if self.case_sensitive else re.IGNORECASE | re.UNICODE
        compiled = re.compile(self.regex.pattern, flags) if flags != re.IGNORECASE | re.UNICODE else self.regex
        for i, match in enumerate(compiled.finditer(content)):
            if self.max_matches > 0 and i >= self.max_matches:
                break
            results.append((match.group(), match.start(), match.end()))
        return results


@dataclass
class SafetyStats:
    total_checks: int = 0
    total_violations: int = 0
    violations_by_category: Counter = field(default_factory=Counter)
    violations_by_severity: Counter = field(default_factory=Counter)
    patterns_triggered: Counter = field(default_factory=Counter)
    blocked_count: int = 0
    warned_count: int = 0
    escalated_count: int = 0
    quarantined_count: int = 0
    redacted_count: int = 0
    last_check_time: Optional[datetime] = None
    average_response_time_ms: float = 0.0
    total_response_time_ms: float = 0.0
    peak_response_time_ms: float = 0.0
    false_positive_count: int = 0
    true_positive_count: int = 0

    def record_check(self, response_time_ms: float, violations: int) -> None:
        self.total_checks += 1
        self.total_violations += violations
        self.total_response_time_ms += response_time_ms
        self.average_response_time_ms = self.total_response_time_ms / self.total_checks
        self.peak_response_time_ms = max(self.peak_response_time_ms, response_time_ms)
        self.last_check_time = datetime.utcnow()

    def record_violation(
        self,
        category: SafetyCategory,
        severity: SeverityLevel,
        pattern_name: str,
        action: SafetyAction,
    ) -> None:
        self.violations_by_category[category.value] += 1
        self.violations_by_severity[severity.value] += 1
        self.patterns_triggered[pattern_name] += 1
        if action == SafetyAction.BLOCK:
            self.blocked_count += 1
        elif action == SafetyAction.WARN:
            self.warned_count += 1
        elif action == SafetyAction.ESCALATE:
            self.escalated_count += 1
        elif action == SafetyAction.QUARANTINE:
            self.quarantined_count += 1
        elif action == SafetyAction.REDACT:
            self.redacted_count += 1

    def record_feedback(self, is_false_positive: bool) -> None:
        if is_false_positive:
            self.false_positive_count += 1
        else:
            self.true_positive_count += 1

    def to_dict(self) -> Dict[str, Any]:
        total_feedback = self.true_positive_count + self.false_positive_count
        return {
            "total_checks": self.total_checks,
            "total_violations": self.total_violations,
            "violations_by_category": dict(self.violations_by_category),
            "violations_by_severity": dict(self.violations_by_severity),
            "patterns_triggered": dict(self.patterns_triggered),
            "blocked_count": self.blocked_count,
            "warned_count": self.warned_count,
            "escalated_count": self.escalated_count,
            "quarantined_count": self.quarantined_count,
            "redacted_count": self.redacted_count,
            "last_check_time": (
                self.last_check_time.isoformat() if self.last_check_time else None
            ),
            "average_response_time_ms": round(self.average_response_time_ms, 2),
            "peak_response_time_ms": round(self.peak_response_time_ms, 2),
            "false_positive_count": self.false_positive_count,
            "true_positive_count": self.true_positive_count,
            "accuracy": (
                round(self.true_positive_count / total_feedback, 4)
                if total_feedback > 0 else 0.0
            ),
        }


class SafetyConfig:
    DEFAULT_SEVERITY_THRESHOLDS: Dict[SeverityLevel, int] = {
        SeverityLevel.LOW: 1,
        SeverityLevel.MEDIUM: 3,
        SeverityLevel.HIGH: 5,
        SeverityLevel.CRITICAL: 10,
    }

    CATEGORY_ACTIONS: Dict[SafetyCategory, SafetyAction] = {
        SafetyCategory.CHILD_SAFETY: SafetyAction.ESCALATE,
        SafetyCategory.WEAPONS: SafetyAction.BLOCK,
        SafetyCategory.SELF_HARM: SafetyAction.ESCALATE,
        SafetyCategory.VIOLENCE: SafetyAction.BLOCK,
        SafetyCategory.TERRORISM: SafetyAction.ESCALATE,
        SafetyCategory.DRUGS: SafetyAction.WARN,
        SafetyCategory.HATE_SPEECH: SafetyAction.BLOCK,
        SafetyCategory.HARASSMENT: SafetyAction.WARN,
        SafetyCategory.EXPLICIT_CONTENT: SafetyAction.REDACT,
        SafetyCategory.PERSONAL_INFO: SafetyAction.REDACT,
        SafetyCategory.FRAUD: SafetyAction.BLOCK,
        SafetyCategory.MALWARE: SafetyAction.BLOCK,
        SafetyCategory.CYBERBULLYING: SafetyAction.WARN,
        SafetyCategory.MISINFORMATION: SafetyAction.WARN,
        SafetyCategory.SPAM: SafetyAction.WARN,
        SafetyCategory.HUMAN_TRAFFICKING: SafetyAction.ESCALATE,
        SafetyCategory.GAMBLING: SafetyAction.WARN,
        SafetyCategory.ANIMAL_CRUELTY: SafetyAction.BLOCK,
        SafetyCategory.EXTREMISM: SafetyAction.BLOCK,
        SafetyCategory.CENSORSHIP_EVASION: SafetyAction.WARN,
    }

    EDUCATIONAL_CONTEXTS: List[str] = [
        "education",
        "research",
        "academic",
        "medical",
        "news_reporting",
        "historical_analysis",
        "public_safety_awareness",
    ]


class SafetyValidator:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or {}
        self._patterns: Dict[SafetyCategory, List[SafetyPattern]] = {}
        self._global_exempt_contexts: Set[str] = set(
            SafetyConfig.EDUCATIONAL_CONTEXTS
        )
        self._stats: SafetyStats = SafetyStats()
        self._category_actions: Dict[SafetyCategory, SafetyAction] = dict(
            SafetyConfig.CATEGORY_ACTIONS
        )
        self._severity_thresholds: Dict[SeverityLevel, int] = dict(
            SafetyConfig.DEFAULT_SEVERITY_THRESHOLDS
        )
        self._severity_scores: Dict[SeverityLevel, float] = {
            SeverityLevel.LOW: 1.0,
            SeverityLevel.MEDIUM: 2.0,
            SeverityLevel.HIGH: 3.0,
            SeverityLevel.CRITICAL: 5.0,
        }
        self._max_severity_score: float = float(
            self.config.get("max_severity_score", 15.0)
        )
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_size: int = self.config.get("max_audit_size", 1000)
        self._callbacks_before: List[Callable] = []
        self._callbacks_after: List[Callable] = []
        self._exempt_keywords: Set[str] = set()
        self._cache: OrderedDict = OrderedDict()
        self._cache_max_size: int = self.config.get("cache_max_size", 200)
        self._cache_ttl: int = self.config.get("cache_ttl_seconds", 60)
        self._lock = threading.RLock()
        self._disallowed_categories: Set[SafetyCategory] = set()
        self._content_overrides: Dict[str, List[str]] = {}
        self._pattern_metadata: Dict[str, Dict[str, Any]] = {}
        self._compact_mode: bool = self.config.get("compact_mode", False)
        self._initialize_default_patterns()
        logger.info(
            f"SafetyValidator initialized with {self._total_pattern_count()} "
            f"patterns across {len(self._patterns)} categories"
        )

    def _initialize_default_patterns(self) -> None:
        from validation_systems.input_validation._safety_defaults import SAFETY_PATTERNS
        for category_name, pattern_defs in SAFETY_PATTERNS.items():
            category = SafetyCategory(category_name)
            self._patterns[category] = []
            for pattern_def in pattern_defs:
                compiled = re.compile(
                    pattern_def["regex"], re.IGNORECASE | re.UNICODE
                )
                pattern = SafetyPattern(
                    name=pattern_def["name"],
                    category=category,
                    regex=compiled,
                    severity=SeverityLevel(pattern_def["severity"]),
                    description=pattern_def["description"],
                    action=SafetyAction(pattern_def.get("action", "warn")),
                    confidence=pattern_def.get("confidence", 1.0),
                    enabled=pattern_def.get("enabled", True),
                    exempt_contexts=pattern_def.get("exempt_contexts", []),
                    max_matches=pattern_def.get("max_matches", 0),
                )
                self._patterns[category].append(pattern)

    def _total_pattern_count(self) -> int:
        return sum(len(patterns) for patterns in self._patterns.values())

    def validate(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[SafetyViolation]]:
        start_time = time.perf_counter()
        context = context or {}
        violations: List[SafetyViolation] = []

        cache_key = self._build_cache_key(content, context)
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._stats.total_checks += 1
            return cached

        if not content or not content.strip():
            elapsed = (time.perf_counter() - start_time) * 1000
            self._stats.record_check(elapsed, 0)
            return True, violations

        with self._lock:
            for callback in self._callbacks_before:
                try:
                    callback(content, context)
                except Exception as e:
                    logger.warning(f"Pre-validation callback failed: {e}")

            exempt_context = self._is_exempt_context(context)

            for category, patterns in self._patterns.items():
                if category in self._disallowed_categories:
                    continue
                if exempt_context and category not in self._get_non_exempt_categories():
                    continue
                category_action = self._category_actions.get(category, SafetyAction.WARN)
                for pattern in patterns:
                    if not pattern.enabled:
                        continue
                    if exempt_context and pattern.exempt_contexts:
                        if any(
                            ctx in context.get("context_types", [])
                            for ctx in pattern.exempt_contexts
                        ):
                            continue
                    matches = pattern.matches(content)
                    if not matches:
                        continue
                    for matched_text, pos_start, pos_end in matches:
                        matched_lower = matched_text.lower()
                        if exempt_context and self._is_contextually_exempt(
                            matched_lower, category, context
                        ):
                            continue
                        if self._is_keyword_exempt(matched_lower):
                            continue
                        line = content[:pos_start].count("\n") + 1
                        violation = SafetyViolation(
                            category=category,
                            pattern_name=pattern.name,
                            matched_text=matched_text,
                            severity=pattern.severity,
                            message=(
                                f"Safety violation: {pattern.description} "
                                f"[{category.value}]"
                            ),
                            position_start=pos_start,
                            position_end=pos_end,
                            confidence=pattern.confidence,
                            context=self._build_violation_context(
                                content, pos_start, pos_end
                            ),
                            suggested_action=category_action,
                            matched_line=line,
                        )
                        violations.append(violation)
                        self._stats.record_violation(
                            category, pattern.severity, pattern.name, category_action
                        )
                        self._log_audit(violation, context)

        total_score = sum(
            self._severity_scores.get(v.severity, 1.0) for v in violations
        )
        is_valid = total_score < self._max_severity_score

        if not is_valid:
            logger.warning(
                f"Safety validation failed with {len(violations)} violations "
                f"(score: {total_score:.1f})"
            )

        elapsed = (time.perf_counter() - start_time) * 1000
        self._stats.record_check(elapsed, len(violations))

        with self._lock:
            for callback in self._callbacks_after:
                try:
                    callback(content, context, violations, is_valid)
                except Exception as e:
                    logger.warning(f"Post-validation callback failed: {e}")

        result = (is_valid, violations)
        self._set_cached(cache_key, result)
        return result

    def _build_cache_key(self, content: str, context: Dict[str, Any]) -> str:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        context_hash = hashlib.md5(
            str(sorted((context or {}).items())).encode()
        ).hexdigest()[:8]
        return f"{content_hash}:{context_hash}"

    def _get_cached(self, key: str) -> Optional[Tuple[bool, List[SafetyViolation]]]:
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                self._cache.move_to_end(key)
                return result
            del self._cache[key]
        return None

    def _set_cached(self, key: str, result: Tuple[bool, List[SafetyViolation]]) -> None:
        self._cache[key] = (result, time.time())
        if len(self._cache) > self._cache_max_size:
            self._cache.popitem(last=False)

    def _is_exempt_context(self, context: Dict[str, Any]) -> bool:
        context_types = context.get("context_types", [])
        if isinstance(context_types, str):
            context_types = [context_types]
        return any(
            exempt in context_types for exempt in self._global_exempt_contexts
        )

    def _get_non_exempt_categories(self) -> Set[SafetyCategory]:
        return {
            SafetyCategory.CHILD_SAFETY,
            SafetyCategory.SELF_HARM,
            SafetyCategory.TERRORISM,
            SafetyCategory.HUMAN_TRAFFICKING,
        }

    def _is_contextually_exempt(
        self,
        matched_text: str,
        category: SafetyCategory,
        context: Dict[str, Any],
    ) -> bool:
        exempt_keywords = context.get("exempt_keywords", [])
        if any(kw in matched_text for kw in exempt_keywords):
            return True
        intent = context.get("intent", "").lower()
        if "educational" in intent or "academic" in intent:
            if category in {
                SafetyCategory.WEAPONS,
                SafetyCategory.DRUGS,
                SafetyCategory.VIOLENCE,
                SafetyCategory.EXTREMISM,
            }:
                return True
        if "medical" in intent and category in {
            SafetyCategory.DRUGS,
            SafetyCategory.SELF_HARM,
        }:
            return True
        if "news" in intent or "journalism" in intent:
            return True
        return False

    def _is_keyword_exempt(self, matched_text: str) -> bool:
        return any(kw.lower() in matched_text for kw in self._exempt_keywords)

    def _build_violation_context(self, content: str, start: int, end: int) -> str:
        ctx_radius = 40
        ctx_start = max(0, start - ctx_radius)
        ctx_end = min(len(content), end + ctx_radius)
        prefix = "..." if ctx_start > 0 else ""
        suffix = "..." if ctx_end < len(content) else ""
        return f"{prefix}{content[ctx_start:ctx_end]}{suffix}"

    def _log_audit(self, violation: SafetyViolation, context: Dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "category": violation.category.value,
            "pattern": violation.pattern_name,
            "severity": violation.severity.value,
            "matched_text": violation.matched_text,
            "action": violation.suggested_action.value,
            "context_types": context.get("context_types", []),
            "user_id": context.get("user_id"),
            "content_id": context.get("content_id"),
            "session_id": context.get("session_id"),
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_size:
            self._audit_log = self._audit_log[-self._max_audit_size:]

    def add_pattern(
        self,
        category: SafetyCategory,
        name: str,
        regex: str,
        severity: SeverityLevel = SeverityLevel.MEDIUM,
        description: str = "",
        action: SafetyAction = SafetyAction.WARN,
        confidence: float = 1.0,
        exempt_contexts: Optional[List[str]] = None,
        max_matches: int = 0,
    ) -> SafetyPattern:
        if category not in self._patterns:
            self._patterns[category] = []
        compiled = re.compile(regex, re.IGNORECASE | re.UNICODE)
        pattern = SafetyPattern(
            name=name,
            category=category,
            regex=compiled,
            severity=severity,
            description=description or f"Custom pattern: {name}",
            action=action,
            confidence=confidence,
            exempt_contexts=exempt_contexts or [],
            max_matches=max_matches,
        )
        self._patterns[category].append(pattern)
        self._pattern_metadata[name] = {
            "created_at": datetime.utcnow().isoformat(),
            "source": "custom",
        }
        logger.info(f"Added safety pattern '{name}' to category '{category.value}'")
        return pattern

    def remove_pattern(self, category: SafetyCategory, name: str) -> bool:
        if category not in self._patterns:
            return False
        initial_count = len(self._patterns[category])
        self._patterns[category] = [
            p for p in self._patterns[category] if p.name != name
        ]
        removed = len(self._patterns[category]) < initial_count
        if removed:
            self._pattern_metadata.pop(name, None)
            logger.info(f"Removed safety pattern '{name}' from '{category.value}'")
        return removed

    def update_pattern(self, category: SafetyCategory, name: str, **kwargs: Any) -> bool:
        if category not in self._patterns:
            return False
        for pattern in self._patterns[category]:
            if pattern.name == name:
                if "regex" in kwargs:
                    pattern.regex = re.compile(kwargs["regex"], re.IGNORECASE | re.UNICODE)
                if "severity" in kwargs:
                    pattern.severity = kwargs["severity"]
                if "description" in kwargs:
                    pattern.description = kwargs["description"]
                if "action" in kwargs:
                    pattern.action = kwargs["action"]
                if "confidence" in kwargs:
                    pattern.confidence = kwargs["confidence"]
                if "enabled" in kwargs:
                    pattern.enabled = kwargs["enabled"]
                if "exempt_contexts" in kwargs:
                    pattern.exempt_contexts = kwargs["exempt_contexts"]
                if "max_matches" in kwargs:
                    pattern.max_matches = kwargs["max_matches"]
                logger.info(f"Updated safety pattern '{name}'")
                return True
        return False

    def enable_pattern(self, category: SafetyCategory, name: str) -> bool:
        return self.update_pattern(category, name, enabled=True)

    def disable_pattern(self, category: SafetyCategory, name: str) -> bool:
        return self.update_pattern(category, name, enabled=False)

    def get_pattern(self, category: SafetyCategory, name: str) -> Optional[SafetyPattern]:
        if category not in self._patterns:
            return None
        for pattern in self._patterns[category]:
            if pattern.name == name:
                return pattern
        return None

    def get_patterns_by_category(self, category: SafetyCategory) -> List[SafetyPattern]:
        return list(self._patterns.get(category, []))

    def get_all_patterns(self) -> Dict[SafetyCategory, List[SafetyPattern]]:
        return dict(self._patterns)

    def get_enabled_patterns(self) -> Dict[SafetyCategory, List[SafetyPattern]]:
        return {
            cat: [p for p in patterns if p.enabled]
            for cat, patterns in self._patterns.items()
        }

    def add_category(self, category: SafetyCategory, default_action: SafetyAction = SafetyAction.WARN) -> None:
        if category not in self._patterns:
            self._patterns[category] = []
            self._category_actions[category] = default_action
            logger.info(f"Added safety category '{category.value}'")

    def remove_category(self, category: SafetyCategory) -> bool:
        if category in self._patterns:
            del self._patterns[category]
            self._category_actions.pop(category, None)
            logger.info(f"Removed safety category '{category.value}'")
            return True
        return False

    def set_category_action(self, category: SafetyCategory, action: SafetyAction) -> None:
        self._category_actions[category] = action

    def get_category_action(self, category: SafetyCategory) -> SafetyAction:
        return self._category_actions.get(category, SafetyAction.WARN)

    def add_exempt_context(self, context_type: str) -> None:
        self._global_exempt_contexts.add(context_type)
        logger.info(f"Added exempt context: {context_type}")

    def remove_exempt_context(self, context_type: str) -> bool:
        if context_type in self._global_exempt_contexts:
            self._global_exempt_contexts.discard(context_type)
            logger.info(f"Removed exempt context: {context_type}")
            return True
        return False

    def get_exempt_contexts(self) -> List[str]:
        return list(self._global_exempt_contexts)

    def add_exempt_keyword(self, keyword: str) -> None:
        self._exempt_keywords.add(keyword.lower())
        logger.info(f"Added exempt keyword: {keyword}")

    def remove_exempt_keyword(self, keyword: str) -> bool:
        kw = keyword.lower()
        if kw in self._exempt_keywords:
            self._exempt_keywords.discard(kw)
            logger.info(f"Removed exempt keyword: {keyword}")
            return True
        return False

    def set_severity_threshold(self, severity: SeverityLevel, max_violations: int) -> None:
        self._severity_thresholds[severity] = max_violations

    def get_severity_threshold(self, severity: SeverityLevel) -> int:
        return self._severity_thresholds.get(severity, 0)

    def set_max_severity_score(self, score: float) -> None:
        self._max_severity_score = score

    def get_max_severity_score(self) -> float:
        return self._max_severity_score

    def register_before_callback(self, callback: Callable) -> None:
        self._callbacks_before.append(callback)

    def register_after_callback(self, callback: Callable) -> None:
        self._callbacks_after.append(callback)

    def unregister_before_callback(self, callback: Callable) -> bool:
        if callback in self._callbacks_before:
            self._callbacks_before.remove(callback)
            return True
        return False

    def unregister_after_callback(self, callback: Callable) -> bool:
        if callback in self._callbacks_after:
            self._callbacks_after.remove(callback)
            return True
        return False

    def get_stats(self) -> SafetyStats:
        return self._stats

    def get_stats_dict(self) -> Dict[str, Any]:
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = SafetyStats()
        logger.info("Safety validation stats reset")

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
        logger.info("Validation cache cleared")

    def enable_category(self, category: SafetyCategory) -> None:
        self._disallowed_categories.discard(category)
        logger.info(f"Enabled safety category '{category.value}'")

    def disable_category(self, category: SafetyCategory) -> None:
        self._disallowed_categories.add(category)
        logger.info(f"Disabled safety category '{category.value}'")

    def is_category_enabled(self, category: SafetyCategory) -> bool:
        return category not in self._disallowed_categories

    def get_disallowed_categories(self) -> List[SafetyCategory]:
        return list(self._disallowed_categories)

    def set_content_overrides(self, content_id: str, allowed_patterns: List[str]) -> None:
        self._content_overrides[content_id] = allowed_patterns

    def remove_content_override(self, content_id: str) -> bool:
        if content_id in self._content_overrides:
            del self._content_overrides[content_id]
            return True
        return False

    def get_audit_log(
        self,
        limit: int = 100,
        category: Optional[SafetyCategory] = None,
        severity: Optional[SeverityLevel] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        entries = list(self._audit_log)
        if category:
            entries = [e for e in entries if e["category"] == category.value]
        if severity:
            entries = [e for e in entries if e["severity"] == severity.value]
        if start_time:
            entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= start_time]
        if end_time:
            entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) <= end_time]
        return entries[-limit:]

    def clear_audit_log(self) -> None:
        self._audit_log.clear()
        logger.info("Audit log cleared")

    def record_feedback(self, violation_index: int, is_false_positive: bool) -> None:
        self._stats.record_feedback(is_false_positive)

    def validate_batch(
        self,
        contents: List[str],
        context: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> List[Tuple[bool, List[SafetyViolation]]]:
        if parallel:
            return self._validate_batch_parallel(contents, context, max_workers)
        results = []
        for i, content in enumerate(contents):
            logger.debug(f"Validating content item {i + 1}/{len(contents)}")
            is_valid, violations = self.validate(content, context)
            results.append((is_valid, violations))
        return results

    def _validate_batch_parallel(
        self,
        contents: List[str],
        context: Optional[Dict[str, Any]],
        max_workers: int,
    ) -> List[Tuple[bool, List[SafetyViolation]]]:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.validate, content, context): i
                    for i, content in enumerate(contents)
                }
                ordered = [None] * len(contents)
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        ordered[idx] = future.result()
                    except Exception as e:
                        logger.error(f"Batch validation failed at index {idx}: {e}")
                        ordered[idx] = (False, [])
                return [r for r in ordered if r is not None]
        except ImportError:
            logger.warning("ThreadPoolExecutor not available, using sequential")
            return [self.validate(c, context) for c in contents]

    def validate_with_score(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        is_valid, violations = self.validate(content, context)
        total_score = sum(self._severity_scores.get(v.severity, 1.0) for v in violations)
        by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for v in violations:
            by_category[v.category.value].append(v.to_dict())
        return {
            "is_valid": is_valid,
            "score": total_score,
            "max_score": self._max_severity_score,
            "violations_count": len(violations),
            "violations_by_category": dict(by_category),
            "violations": [v.to_dict() for v in violations],
        }

    def generate_report(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        stats = self._stats
        violations_detail: Counter = Counter()
        severity_detail: Counter = Counter()
        for entry in self._audit_log:
            entry_time = datetime.fromisoformat(entry["timestamp"])
            if start_time and entry_time < start_time:
                continue
            if end_time and entry_time > end_time:
                continue
            violations_detail[entry["category"]] += 1
            severity_detail[entry["severity"]] += 1
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "period": {
                "start": start_time.isoformat() if start_time else "all",
                "end": end_time.isoformat() if end_time else "all",
            },
            "statistics": stats.to_dict(),
            "violations_by_category_in_period": dict(violations_detail),
            "violations_by_severity_in_period": dict(severity_detail),
            "top_triggered_patterns": dict(stats.patterns_triggered.most_common(10)),
            "category_actions": {k.value: v.value for k, v in self._category_actions.items()},
            "exempt_contexts": list(self._global_exempt_contexts),
            "total_patterns": self._total_pattern_count(),
            "active_patterns": sum(
                1 for patterns in self._patterns.values() for p in patterns if p.enabled
            ),
        }

    def get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def validate_cached(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        cache: Optional[Dict[str, Tuple[bool, List[SafetyViolation]]]] = None,
    ) -> Tuple[bool, List[SafetyViolation]]:
        if cache is None:
            return self.validate(content, context)
        content_hash = self.get_content_hash(content)
        context_hash = hashlib.md5(
            str(sorted((context or {}).items())).encode()
        ).hexdigest()
        cache_key = f"{content_hash}:{context_hash}"
        if cache_key in cache:
            logger.debug("Returning cached validation result")
            return cache[cache_key]
        result = self.validate(content, context)
        cache[cache_key] = result
        return result

    def to_config_dict(self) -> Dict[str, Any]:
        return {
            "max_severity_score": self._max_severity_score,
            "max_audit_size": self._max_audit_size,
            "severity_thresholds": {k.value: v for k, v in self._severity_thresholds.items()},
            "severity_scores": {k.value: v for k, v in self._severity_scores.items()},
            "category_actions": {k.value: v.value for k, v in self._category_actions.items()},
            "exempt_contexts": list(self._global_exempt_contexts),
            "pattern_summary": {cat.value: len(patterns) for cat, patterns in self._patterns.items()},
        }

    def merge_config(self, config: Dict[str, Any]) -> None:
        if "max_severity_score" in config:
            self._max_severity_score = config["max_severity_score"]
        if "max_audit_size" in config:
            self._max_audit_size = config["max_audit_size"]
        if "severity_thresholds" in config:
            for k, v in config["severity_thresholds"].items():
                try:
                    self._severity_thresholds[SeverityLevel(k)] = v
                except ValueError:
                    logger.warning(f"Unknown severity level: {k}")
        if "severity_scores" in config:
            for k, v in config["severity_scores"].items():
                try:
                    self._severity_scores[SeverityLevel(k)] = v
                except ValueError:
                    logger.warning(f"Unknown severity level: {k}")
        logger.info("Configuration merged into SafetyValidator")

    def export_patterns(self, filepath: str) -> None:
        patterns_data: Dict[str, Any] = {}
        for category, patterns in self._patterns.items():
            patterns_data[category.value] = []
            for p in patterns:
                patterns_data[category.value].append({
                    "name": p.name,
                    "regex": p.regex.pattern,
                    "severity": p.severity.value,
                    "description": p.description,
                    "action": p.action.value,
                    "confidence": p.confidence,
                    "enabled": p.enabled,
                    "exempt_contexts": p.exempt_contexts,
                    "max_matches": p.max_matches,
                })
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(patterns_data, f, indent=2)
        logger.info(f"Patterns exported to {filepath}")

    def import_patterns(self, filepath: str) -> int:
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            patterns_data = json.load(f)
        for category_name, pattern_defs in patterns_data.items():
            try:
                category = SafetyCategory(category_name)
                for pd in pattern_defs:
                    self.add_pattern(
                        category=category,
                        name=pd["name"],
                        regex=pd["regex"],
                        severity=SeverityLevel(pd["severity"]),
                        description=pd.get("description", ""),
                        action=SafetyAction(pd.get("action", "warn")),
                        confidence=pd.get("confidence", 1.0),
                        exempt_contexts=pd.get("exempt_contexts", []),
                        max_matches=pd.get("max_matches", 0),
                    )
                    count += 1
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to import category '{category_name}': {e}")
        logger.info(f"Imported {count} patterns from {filepath}")
        return count

    def __repr__(self) -> str:
        return (
            f"SafetyValidator(categories={len(self._patterns)}, "
            f"patterns={self._total_pattern_count()}, "
            f"checks={self._stats.total_checks})"
        )
