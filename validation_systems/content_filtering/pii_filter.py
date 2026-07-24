"""
PII filter - detection of personally identifiable information including SSN, credit
cards, emails, phones, addresses, DOB, IPs, passports with Luhn validation, partial
match detection, redaction strategies, and statistical tracking.
"""

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType

logger = logging.getLogger(__name__)


class PIICategory(str, Enum):
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    DOB = "date_of_birth"
    IP_ADDRESS = "ip_address"
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    BANK_ACCOUNT = "bank_account"
    TAX_ID = "tax_id"
    MEDICAL_RECORD = "medical_record"
    CUSTOM = "custom"


class RedactionStrategy(str, Enum):
    MASK = "mask"
    TRUNCATE = "truncate"
    REPLACE = "replace"
    HASH = "hash"
    REMOVE = "remove"


class MatchConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"


@dataclass
class PIIPattern:
    pattern_id: str
    category: PIICategory
    pattern: str
    description: str = ""
    confidence: MatchConfidence = MatchConfidence.MEDIUM
    weight: float = 1.0
    requires_validation: bool = False
    is_active: bool = True
    redaction_strategy: RedactionStrategy = RedactionStrategy.MASK
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compile(self) -> Optional[re.Pattern]:
        try:
            return re.compile(self.pattern, re.IGNORECASE | re.UNICODE)
        except re.error as e:
            logger.warning("Failed to compile PII pattern %s: %s", self.pattern_id, e)
            return None


@dataclass
class PIIDetection:
    pattern_id: str
    category: PIICategory
    matched_text: str
    start_pos: int
    end_pos: int
    confidence: MatchConfidence
    confidence_score: float
    value: str
    is_validated: bool = False
    redacted: Optional[str] = None
    context_before: str = ""
    context_after: str = ""


@dataclass
class PIIStats:
    total_evaluations: int = 0
    total_detections: int = 0
    total_redactions: int = 0
    total_blocks: int = 0
    total_warnings: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    detection_rate: float = 0.0
    false_positive_rate: float = 0.0
    category_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    confidence_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_processing_time_ms: int = 0
    avg_processing_time_ms: float = 0.0
    last_evaluated: Optional[datetime] = None
    first_evaluated: Optional[datetime] = None
    recent_detections: deque = field(default_factory=lambda: deque(maxlen=500))

    def record_evaluation(self, processing_time_ms: int,
                          detections: List[PIIDetection],
                          blocked: bool = False,
                          warned: bool = False) -> None:
        self.total_evaluations += 1
        self.total_processing_time_ms += processing_time_ms
        self.avg_processing_time_ms = self.total_processing_time_ms / self.total_evaluations
        now = datetime.utcnow()
        self.last_evaluated = now
        if self.first_evaluated is None:
            self.first_evaluated = now
        if detections:
            self.total_detections += len(detections)
            for d in detections:
                self.category_counts[d.category.value] += 1
                self.confidence_counts[d.confidence.value] += 1
                if d.redacted:
                    self.total_redactions += 1
                self.recent_detections.append({
                    "timestamp": now.isoformat(),
                    "category": d.category.value,
                    "confidence": d.confidence.value,
                    "validated": d.is_validated,
                })
        date_key = now.strftime("%Y-%m-%d")
        self.daily_counts[date_key] += 1
        if blocked:
            self.total_blocks += 1
        if warned:
            self.total_warnings += 1
        if self.total_evaluations > 0:
            self.detection_rate = self.total_detections / self.total_evaluations
        total = self.total_detections + self.false_positives
        if total > 0:
            self.false_positive_rate = self.false_positives / total

    def record_false_positive(self) -> None:
        self.false_positives += 1

    def record_false_negative(self) -> None:
        self.false_negatives += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_detections": self.total_detections,
            "total_redactions": self.total_redactions,
            "total_blocks": self.total_blocks,
            "total_warnings": self.total_warnings,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "detection_rate": round(self.detection_rate, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "category_counts": dict(self.category_counts),
            "confidence_counts": dict(self.confidence_counts),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
        }

    def reset(self) -> None:
        self.total_evaluations = 0
        self.total_detections = 0
        self.total_redactions = 0
        self.total_blocks = 0
        self.total_warnings = 0
        self.false_positives = 0
        self.false_negatives = 0
        self.detection_rate = 0.0
        self.false_positive_rate = 0.0
        self.category_counts.clear()
        self.confidence_counts.clear()
        self.daily_counts.clear()
        self.total_processing_time_ms = 0
        self.avg_processing_time_ms = 0.0
        self.last_evaluated = None
        self.first_evaluated = None
        self.recent_detections.clear()


DEFAULT_PII_PATTERNS: Dict[PIICategory, List[Dict[str, Any]]] = {
    PIICategory.SSN: [
        {
            "pattern": r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 2.0,
            "requires_validation": False,
        },
        {
            "pattern": r'\b(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.5,
            "requires_validation": False,
        },
    ],
    PIICategory.CREDIT_CARD: [
        {
            "pattern": r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.8,
            "requires_validation": True,
        },
        {
            "pattern": r'\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 2.0,
            "requires_validation": True,
        },
    ],
    PIICategory.EMAIL: [
        {
            "pattern": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.0,
        },
    ],
    PIICategory.PHONE: [
        {
            "pattern": r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.2,
        },
        {
            "pattern": r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 0.8,
        },
    ],
    PIICategory.ADDRESS: [
        {
            "pattern": r'\b\d{1,5}\s+(?:[A-Za-z]+\s?){1,5}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Place|Pl|Court|Ct|Circle|Cir|Terrace|Ter|Trail|Trl|Parkway|Pkwy|Highway|Hwy|Square|Sq|Row|Alley|Ally|Run|Point|Pt|Pike|View|Vw|Loop|Landing|Lndg|Center|Ctr|Glen|Gl|Hollow|Holw|Junction|Jct|Manor|Mnr|Meadows|Mdws|Mill|Orchard|Orch|Ridge|Rdg|Village|Vlg)\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.0,
        },
    ],
    PIICategory.DOB: [
        {
            "pattern": r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.0,
        },
        {
            "pattern": r'\b(?:birth\s*date|date\s*of\s*birth|dob|born\s*on|born)\s*:?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.5,
        },
    ],
    PIICategory.IP_ADDRESS: [
        {
            "pattern": r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 0.8,
        },
        {
            "pattern": r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 0.8,
        },
    ],
    PIICategory.PASSPORT: [
        {
            "pattern": r'\b[A-Z]\d{8}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.5,
        },
        {
            "pattern": r'\b\d{9}\b',
            "confidence": MatchConfidence.LOW,
            "weight": 0.5,
        },
    ],
    PIICategory.DRIVER_LICENSE: [
        {
            "pattern": r'\b(?:DL|Dl|dL|dl|D/L|d/l|Driver' + "'" + r's?\s*License|Drivers?\s*Lic|License\s*No)[:\s]*[A-Z0-9]{5,20}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.3,
        },
    ],
    PIICategory.BANK_ACCOUNT: [
        {
            "pattern": r'\b(?:account\s*(?:number|no|#|num)|acct\s*(?:no|#|num)|routing\s*(?:number|no|#|num))[\s:]*\d{4,17}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.8,
        },
        {
            "pattern": r'\b\d{8,17}\b',
            "confidence": MatchConfidence.LOW,
            "weight": 0.5,
        },
    ],
    PIICategory.TAX_ID: [
        {
            "pattern": r'\b\d{2}-\d{7}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.5,
        },
        {
            "pattern": r'\b(?:TIN|EIN|tax\s*(?:id|identifier|number|no|#))[\s:]*\d{2}-?\d{7}\b',
            "confidence": MatchConfidence.HIGH,
            "weight": 1.8,
        },
    ],
    PIICategory.MEDICAL_RECORD: [
        {
            "pattern": r'\b(?:MRN|medical\s*record\s*(?:number|no|#|num)|patient\s*(?:id|identifier|number|no|#|num))[\s:]*[A-Z0-9]{4,15}\b',
            "confidence": MatchConfidence.MEDIUM,
            "weight": 1.3,
        },
    ],
}

REDACTION_CHAR = "*"


class PIIFilter:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.filter_id = str(uuid.uuid4())[:8]
        self._patterns: Dict[str, PIIPattern] = {}
        self._compiled: Dict[str, Optional[re.Pattern]] = {}
        self._categories: Dict[PIICategory, List[str]] = defaultdict(list)
        self._redaction_strategies: Dict[PIICategory, RedactionStrategy] = defaultdict(
            lambda: RedactionStrategy.MASK
        )
        self._allowlist: Set[str] = set()
        self._stats = PIIStats()
        self._block_on_critical = self.config.get("block_on_critical", True)
        self._block_threshold = self.config.get("block_threshold", 40)
        self._warn_threshold = self.config.get("warn_threshold", 10)
        self._enable_luhn = self.config.get("enable_luhn", True)
        self._enable_partial_match = self.config.get("enable_partial_match", True)
        self._min_confidence_for_action = self.config.get("min_confidence_for_action", 0.4)
        self._auto_redact = self.config.get("auto_redact", False)
        self._context_window = self.config.get("context_window", 30)
        self._version = "2.0.0"

        self._init_default_patterns()
        self.logger.info("PIIFilter initialized (id=%s, version=%s, patterns=%d)",
                         self.filter_id, self._version, len(self._patterns))

    def _init_default_patterns(self) -> None:
        for category, patterns in DEFAULT_PII_PATTERNS.items():
            for idx, p in enumerate(patterns):
                pid = f"pii_{category.value}_{idx}_{uuid.uuid4().hex[:6]}"
                pp = PIIPattern(
                    pattern_id=pid,
                    category=category,
                    pattern=p["pattern"],
                    confidence=p.get("confidence", MatchConfidence.MEDIUM),
                    weight=p.get("weight", 1.0),
                    requires_validation=p.get("requires_validation", False),
                    description=f"Default {category.value} pattern {idx}",
                )
                self._patterns[pid] = pp
                self._compiled[pid] = pp.compile()
                self._categories[category].append(pid)

    def _luhn_check(self, card_number: str) -> bool:
        digits = [int(c) for c in card_number if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        check_digit = digits.pop()
        digits.reverse()
        total = 0
        for i, d in enumerate(digits):
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return (total + check_digit) % 10 == 0

    def _validate_ssn(self, ssn: str) -> bool:
        digits = re.sub(r'\D', '', ssn)
        if len(digits) != 9:
            return False
        if digits[:3] in {"000", "666"} or int(digits[:3]) > 899:
            return False
        if digits[3:5] == "00":
            return False
        if digits[5:] == "0000":
            return False
        return True

    def _validate_email(self, email: str) -> bool:
        if len(email) > 254:
            return False
        local, _, domain = email.partition("@")
        if not local or not domain:
            return False
        if len(local) > 64:
            return False
        if ".." in local or ".." in domain:
            return False
        if local.startswith(".") or local.endswith("."):
            return False
        if domain.startswith("-") or domain.endswith("-"):
            return False
        return True

    def _validate_ip(self, ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for p in parts:
            if not p.isdigit():
                return False
            val = int(p)
            if val < 0 or val > 255:
                return False
        if parts[0] == "0":
            return False
        return True

    def _get_confidence_score(self, confidence: MatchConfidence) -> float:
        scores = {
            MatchConfidence.LOW: 0.3,
            MatchConfidence.MEDIUM: 0.6,
            MatchConfidence.HIGH: 0.85,
            MatchConfidence.CONFIRMED: 1.0,
        }
        return scores.get(confidence, 0.5)

    def apply_redaction(self, text: str, strategy: RedactionStrategy) -> str:
        if not text:
            return text
        if strategy == RedactionStrategy.MASK:
            visible_chars = max(1, len(text) // 4)
            return text[:visible_chars] + REDACTION_CHAR * (len(text) - visible_chars)
        elif strategy == RedactionStrategy.TRUNCATE:
            return text[:1] + REDACTION_CHAR * 3
        elif strategy == RedactionStrategy.REPLACE:
            return f"[REDACTED {hashlib.md5(text.encode()).hexdigest()[:8]}]"
        elif strategy == RedactionStrategy.HASH:
            return hashlib.sha256(text.encode()).hexdigest()[:16]
        elif strategy == RedactionStrategy.REMOVE:
            return ""
        return text

    def add_pattern(self, category: PIICategory, pattern: str,
                    confidence: MatchConfidence = MatchConfidence.MEDIUM,
                    weight: float = 1.0,
                    requires_validation: bool = False,
                    redaction_strategy: Optional[RedactionStrategy] = None,
                    description: str = "") -> PIIPattern:
        pid = f"custom_pii_{uuid.uuid4().hex[:12]}"
        pp = PIIPattern(
            pattern_id=pid,
            category=category,
            pattern=pattern,
            confidence=confidence,
            weight=weight,
            requires_validation=requires_validation,
            description=description or f"Custom {category.value} pattern",
            redaction_strategy=redaction_strategy or self._redaction_strategies[category],
        )
        self._patterns[pid] = pp
        self._compiled[pid] = pp.compile()
        self._categories[category].append(pid)
        self.logger.info("Added PII pattern %s for category %s", pid, category.value)
        return pp

    def remove_pattern(self, pattern_id: str) -> bool:
        if pattern_id not in self._patterns:
            return False
        pp = self._patterns[pattern_id]
        self._patterns.pop(pattern_id, None)
        self._compiled.pop(pattern_id, None)
        cat = pp.category
        if pattern_id in self._categories[cat]:
            self._categories[cat].remove(pattern_id)
        self.logger.info("Removed PII pattern %s", pattern_id)
        return True

    def update_pattern(self, pattern_id: str, **updates) -> Optional[PIIPattern]:
        if pattern_id not in self._patterns:
            return None
        pp = self._patterns[pattern_id]
        for key, value in updates.items():
            if hasattr(pp, key) and key != "pattern_id":
                setattr(pp, key, value)
        if "pattern" in updates:
            self._compiled[pattern_id] = pp.compile()
        pp.metadata["updated_at"] = datetime.utcnow().isoformat()
        return pp

    def get_pattern(self, pattern_id: str) -> Optional[PIIPattern]:
        return self._patterns.get(pattern_id)

    def list_patterns(self, category: Optional[PIICategory] = None,
                      active_only: bool = False) -> List[PIIPattern]:
        patterns = list(self._patterns.values())
        if category:
            patterns = [p for p in patterns if p.category == category]
        if active_only:
            patterns = [p for p in patterns if p.is_active]
        return patterns

    def set_redaction_strategy(self, category: PIICategory,
                               strategy: RedactionStrategy) -> None:
        self._redaction_strategies[category] = strategy

    def get_redaction_strategy(self, category: PIICategory) -> RedactionStrategy:
        return self._redaction_strategies[category]

    def add_to_allowlist(self, value: str) -> None:
        self._allowlist.add(value.lower().strip())

    def remove_from_allowlist(self, value: str) -> bool:
        normalized = value.lower().strip()
        if normalized in self._allowlist:
            self._allowlist.remove(normalized)
            return True
        return False

    def list_allowlist(self) -> List[str]:
        return sorted(self._allowlist)

    def is_allowlisted(self, value: str) -> bool:
        return value.lower().strip() in self._allowlist

    def filter(self, content: str, context: Optional[Dict[str, Any]] = None,
               categories: Optional[List[PIICategory]] = None,
               auto_redact: Optional[bool] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        ctx = context or {}
        target_categories = categories or list(self._categories.keys())
        all_detections: List[PIIDetection] = []
        should_redact = auto_redact if auto_redact is not None else self._auto_redact
        now = datetime.utcnow()

        for cat in target_categories:
            pattern_ids = self._categories.get(cat, [])
            for pid in pattern_ids:
                pp = self._patterns.get(pid)
                if not pp or not pp.is_active:
                    continue
                compiled = self._compiled.get(pid)
                if compiled is None:
                    continue
                try:
                    for match in compiled.finditer(content):
                        matched_text = match.group()
                        if self.is_allowlisted(matched_text):
                            continue
                        validated = False
                        confidence_score = self._get_confidence_score(pp.confidence)
                        if pp.requires_validation:
                            if pp.category == PIICategory.CREDIT_CARD and self._enable_luhn:
                                validated = self._luhn_check(matched_text)
                                if not validated:
                                    continue
                                confidence_score = 1.0 if validated else 0.2
                            elif pp.category == PIICategory.SSN:
                                validated = self._validate_ssn(matched_text)
                                if not validated:
                                    continue
                                confidence_score = 1.0 if validated else 0.2
                            elif pp.category == PIICategory.EMAIL:
                                validated = self._validate_email(matched_text)
                                confidence_score = 0.9 if validated else 0.3
                            elif pp.category == PIICategory.IP_ADDRESS:
                                validated = self._validate_ip(matched_text)
                                confidence_score = 0.9 if validated else 0.2
                        else:
                            validated = True

                        strategy = pp.redaction_strategy
                        if strategy == RedactionStrategy.MASK and cat in self._redaction_strategies:
                            strategy = self._redaction_strategies[cat]

                        redacted = None
                        if should_redact:
                            redacted = self.apply_redaction(matched_text, strategy)

                        context_before, context_after = self._extract_context(
                            content, match.start(), match.end() - match.start()
                        )
                        detection = PIIDetection(
                            pattern_id=pid,
                            category=cat,
                            matched_text=matched_text,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            confidence=pp.confidence,
                            confidence_score=confidence_score,
                            value=matched_text,
                            is_validated=validated,
                            redacted=redacted,
                            context_before=context_before,
                            context_after=context_after,
                        )
                        all_detections.append(detection)
                except re.error as e:
                    self.logger.warning("Regex error on PII pattern %s: %s", pid, e)

        if self._enable_partial_match:
            all_detections = self._find_partial_matches(content, all_detections)

        all_detections.sort(key=lambda d: (d.confidence_score * d._get_pattern_weight()), reverse=True)
        unique_detections = self._deduplicate_detections(all_detections)
        total_score = sum(
            d.confidence_score * self._patterns.get(d.pattern_id, PIIPattern(
                pattern_id="", category=PIICategory.CUSTOM, pattern=""
            )).weight * 10
            for d in unique_detections
        )
        blocked = total_score >= self._block_threshold
        warned = total_score >= self._warn_threshold and not blocked

        redacted_content = None
        if should_redact and unique_detections:
            redacted_content = content
            for d in reversed(unique_detections):
                if d.redacted:
                    redacted_content = (
                        redacted_content[:d.start_pos]
                        + d.redacted
                        + redacted_content[d.end_pos:]
                    )

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        self._stats.record_evaluation(processing_time_ms, unique_detections, blocked=blocked, warned=warned)

        violations = []
        for d in unique_detections[:30]:
            severity = RuleSeverity.HIGH
            if d.confidence in (MatchConfidence.CONFIRMED, MatchConfidence.HIGH):
                severity = RuleSeverity.CRITICAL
            elif d.confidence == MatchConfidence.LOW:
                severity = RuleSeverity.MEDIUM
            action = ActionTaken.WARNING
            if blocked:
                action = ActionTaken.BLOCK
            elif d.category in (PIICategory.SSN, PIICategory.CREDIT_CARD):
                action = ActionTaken.REDACT
            v = Violation(
                rule_id=f"pii_{d.category.value}_{d.pattern_id}",
                rule_name=f"PII Detected - {d.category.value}",
                rule_tier=RuleTier.SAFETY,
                rule_severity=severity,
                violation_type=ViolationType.REGEX_MATCH,
                matched_content=d.matched_text[:50],
                matched_patterns=[d.pattern_id],
                confidence_score=d.confidence_score,
                position_info={"start": d.start_pos, "end": d.end_pos},
                action_taken=action,
                blocked=blocked,
                explanation=f"PII detected: {d.category.value} (confidence: {d.confidence.value})",
                detected_at=now,
            )
            violations.append(v)

        result = {
            "clean": len(unique_detections) == 0,
            "blocked": blocked,
            "warned": warned,
            "total_score": round(total_score, 2),
            "total_detections": len(unique_detections),
            "auto_redacted": should_redact,
            "redacted_content": redacted_content,
            "detections": [
                {
                    "category": d.category.value,
                    "confidence": d.confidence.value,
                    "confidence_score": round(d.confidence_score, 3),
                    "validated": d.is_validated,
                    "redacted": d.redacted,
                    "position": {"start": d.start_pos, "end": d.end_pos},
                }
                for d in unique_detections[:50]
            ],
            "summary": {
                "categories_found": list(set(d.category.value for d in unique_detections)),
                "validated_count": sum(1 for d in unique_detections if d.is_validated),
                "redacted_count": sum(1 for d in unique_detections if d.redacted),
            },
            "processing_time_ms": processing_time_ms,
            "filter_id": self.filter_id,
            "version": self._version,
            "violations": violations,
        }
        return result

    def _get_pattern_weight(self, pattern_id: str) -> float:
        pp = self._patterns.get(pattern_id)
        return pp.weight if pp else 1.0

    def _extract_context(self, content: str, pos: int, length: int) -> Tuple[str, str]:
        start = max(0, pos - self._context_window)
        end = min(len(content), pos + length + self._context_window)
        return content[start:pos].strip(), content[pos + length:end].strip()

    def _find_partial_matches(self, content: str,
                               existing: List[PIIDetection]) -> List[PIIDetection]:
        for cat in [PIICategory.SSN, PIICategory.CREDIT_CARD, PIICategory.PHONE]:
            for d in existing:
                if d.category == cat:
                    break
            else:
                for pid in self._categories.get(cat, []):
                    pp = self._patterns.get(pid)
                    if not pp or not pp.is_active:
                        continue
                    compiled = self._compiled.get(pid)
                    if compiled is None:
                        continue
                    partial_pattern = r'\b\d{4}\b'
                    try:
                        for pm in re.finditer(partial_pattern, content):
                            val = pm.group()
                            if self.is_allowlisted(val):
                                continue
                            already_detected = any(
                                0 <= pd.start_pos - pm.start() <= 5 or
                                0 <= pm.start() - pd.start_pos <= 5
                                for pd in existing
                            )
                            if not already_detected:
                                detection = PIIDetection(
                                    pattern_id=f"partial_{pid}",
                                    category=cat,
                                    matched_text=val,
                                    start_pos=pm.start(),
                                    end_pos=pm.end(),
                                    confidence=MatchConfidence.LOW,
                                    confidence_score=0.3,
                                    value=val,
                                    is_validated=False,
                                )
                                existing.append(detection)
                    except re.error:
                        pass
        return existing

    def _deduplicate_detections(self, detections: List[PIIDetection]) -> List[PIIDetection]:
        seen_ranges: List[Tuple[int, int]] = []
        unique: List[PIIDetection] = []
        for d in sorted(detections, key=lambda x: (x.start_pos, -x.confidence_score)):
            overlapping = any(
                d.start_pos < end and d.end_pos > start
                for start, end in seen_ranges
            )
            if not overlapping:
                seen_ranges.append((d.start_pos, d.end_pos))
                unique.append(d)
        return unique

    def redact_text(self, text: str, categories: Optional[List[PIICategory]] = None) -> str:
        result = self.filter(text, categories=categories, auto_redact=True)
        return result.get("redacted_content", text)

    def get_stats(self) -> Dict[str, Any]:
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        self._stats.reset()
        self.logger.info("Statistics reset for PII filter %s", self.filter_id)

    def generate_report(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "generated_at": datetime.utcnow().isoformat(),
            "stats": self._stats.to_dict(),
            "configuration": {
                "block_on_critical": self._block_on_critical,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "enable_luhn": self._enable_luhn,
                "enable_partial_match": self._enable_partial_match,
                "auto_redact": self._auto_redact,
                "min_confidence_for_action": self._min_confidence_for_action,
            },
            "categories": {
                cat.value: {
                    "pattern_count": len(self._categories.get(cat, [])),
                    "redaction_strategy": self._redaction_strategies[cat].value,
                }
                for cat in self._categories
            },
            "allowlist_count": len(self._allowlist),
            "patterns": {
                pid: {
                    "category": pp.category.value,
                    "confidence": pp.confidence.value,
                    "weight": pp.weight,
                    "requires_validation": pp.requires_validation,
                    "active": pp.is_active,
                }
                for pid, pp in self._patterns.items()
            },
        }

    def export_config(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "configuration": {
                "block_on_critical": self._block_on_critical,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "enable_luhn": self._enable_luhn,
                "enable_partial_match": self._enable_partial_match,
                "auto_redact": self._auto_redact,
                "min_confidence_for_action": self._min_confidence_for_action,
                "context_window": self._context_window,
            },
            "patterns": [
                {
                    "pattern_id": pp.pattern_id,
                    "category": pp.category.value,
                    "pattern": pp.pattern,
                    "confidence": pp.confidence.value,
                    "weight": pp.weight,
                    "requires_validation": pp.requires_validation,
                    "description": pp.description,
                    "redaction_strategy": pp.redaction_strategy.value,
                    "is_active": pp.is_active,
                }
                for pp in self._patterns.values()
            ],
            "redaction_strategies": {
                cat.value: strat.value for cat, strat in self._redaction_strategies.items()
            },
        }

    def import_config(self, config: Dict[str, Any]) -> int:
        imported = 0
        if "configuration" in config:
            cfg = config["configuration"]
            self._block_on_critical = cfg.get("block_on_critical", self._block_on_critical)
            self._block_threshold = cfg.get("block_threshold", self._block_threshold)
            self._warn_threshold = cfg.get("warn_threshold", self._warn_threshold)
            self._enable_luhn = cfg.get("enable_luhn", self._enable_luhn)
            self._enable_partial_match = cfg.get("enable_partial_match", self._enable_partial_match)
            self._auto_redact = cfg.get("auto_redact", self._auto_redact)
        if "patterns" in config:
            for p in config["patterns"]:
                try:
                    cat = PIICategory(p.get("category", "custom"))
                except ValueError:
                    cat = PIICategory.CUSTOM
                try:
                    confidence = MatchConfidence(p.get("confidence", "medium"))
                except ValueError:
                    confidence = MatchConfidence.MEDIUM
                try:
                    redact_strat = RedactionStrategy(p.get("redaction_strategy", "mask"))
                except ValueError:
                    redact_strat = RedactionStrategy.MASK
                self.add_pattern(
                    category=cat,
                    pattern=p["pattern"],
                    confidence=confidence,
                    weight=p.get("weight", 1.0),
                    requires_validation=p.get("requires_validation", False),
                    redaction_strategy=redact_strat,
                    description=p.get("description", ""),
                )
                imported += 1
        if "redaction_strategies" in config:
            for cat_str, strat_str in config["redaction_strategies"].items():
                try:
                    cat = PIICategory(cat_str)
                    strat = RedactionStrategy(strat_str)
                    self._redaction_strategies[cat] = strat
                except (ValueError, KeyError):
                    pass
        self.logger.info("Imported %d PII patterns", imported)
        return imported

    def to_validation_result(self, filter_result: Dict[str, Any]) -> ValidationResult:
        violations = filter_result.get("violations", [])
        score = filter_result.get("total_score", 0)
        max_possible = self._block_threshold * 2
        clean_score = max(0.0, 1.0 - (score / max_possible))
        return ValidationResult(
            valid=filter_result.get("clean", True),
            total_score=clean_score,
            confidence=1.0 - min(0.5, len(violations) / 30.0),
            total_rules_evaluated=len(self._patterns),
            rules_triggered=len(violations),
            rules_violated=len(violations),
            violations=violations,
            critical_violations=[v for v in violations if v.is_critical()],
            warnings=[v for v in violations if v.action_taken == ActionTaken.WARNING],
            processing_time_ms=filter_result.get("processing_time_ms", 0),
            evaluator_version=self._version,
        )

    def extract_all_pii(self, content: str) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = defaultdict(list)
        filter_result = self.filter(content)
        for d in filter_result.get("detections", []):
            result[d["category"]].append(d)
        return dict(result)

    def validate_content_safety(self, content: str) -> Dict[str, Any]:
        result = self.filter(content)
        return {
            "is_safe": result["clean"],
            "has_pii": not result["clean"],
            "pii_count": result["total_detections"],
            "pii_score": result["total_score"],
            "needs_redaction": result["total_detections"] > 0,
        }
