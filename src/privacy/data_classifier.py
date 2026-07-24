"""Data classification module for sensitivity labelling.

Provides the DataClassifier class that assigns sensitivity levels
(public, internal, confidential, restricted, critical) to data based on
content matching (regex), keyword heuristics, metadata inspection, and
user-defined rules.  Supports config-driven classification policies,
batch classification, and detailed reporting.
"""
import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class SensitivityLevel(Enum):
    """Sensitivity levels for data classification.

    Levels in ascending order of sensitivity:
        PUBLIC: Freely shareable (e.g., marketing materials).
        INTERNAL: OK for internal use, not for external sharing.
        CONFIDENTIAL: Sensitive business data; limited distribution.
        RESTRICTED: Highly sensitive; need-to-know only.
        CRITICAL: Extreme sensitivity; legal/regulatory implications.
    """
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    CRITICAL = "critical"


_LEVEL_ORDER: List[SensitivityLevel] = [
    SensitivityLevel.PUBLIC,
    SensitivityLevel.INTERNAL,
    SensitivityLevel.CONFIDENTIAL,
    SensitivityLevel.RESTRICTED,
    SensitivityLevel.CRITICAL,
]

_LEVEL_RANK: Dict[SensitivityLevel, int] = {
    level: idx for idx, level in enumerate(_LEVEL_ORDER)
}


def level_rank(level: Union[str, SensitivityLevel]) -> int:
    """Return the numeric rank of a sensitivity level.

    Use this to compare levels: higher rank = more sensitive.
    """
    if isinstance(level, str):
        level = SensitivityLevel(level)
    return _LEVEL_RANK.get(level, 0)


@dataclass
class ClassificationRule:
    """A single classification rule.

    Attributes:
        rule_id: Unique identifier.
        name: Human-readable name.
        description: Extended description.
        level: SensitivityLevel assigned when this rule matches.
        patterns: List of regex patterns to match against content.
        keywords: List of keywords (case-insensitive substring match).
        match_any: If True, any single pattern/keyword triggers a match.
                    If False, all must match.
        weight: Numeric weight used in scoring-based classification.
        enabled: Whether the rule is active.
    """
    rule_id: str
    name: str
    description: str
    level: str
    patterns: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    match_any: bool = True
    weight: float = 1.0
    enabled: bool = True


@dataclass
class ClassificationResult:
    """Result of classifying a single data item.

    Attributes:
        level: The assigned sensitivity level.
        score: Numeric confidence score (0.0 - 1.0).
        matched_rules: List of rule IDs that contributed to the result.
        details: Per-rule breakdown of matches.
        is_classified: True if a rule matched (i.e., not default).
        classified_at: ISO-8601 timestamp.
    """
    level: str
    score: float
    matched_rules: List[str]
    details: List[Dict[str, Any]]
    is_classified: bool
    classified_at: str


@dataclass
class ClassificationSummary:
    """Aggregated statistics from a classification run."""
    total_items: int
    level_counts: Dict[str, int]
    level_percentages: Dict[str, float]
    rule_hit_counts: Dict[str, int]
    average_score: float
    highest_level: str
    lowest_level: str
    generated_at: str


# ---------------------------------------------------------------------------
# Built-in classification patterns
# ---------------------------------------------------------------------------

_BUILTIN_PATTERNS: List[Dict[str, Any]] = [
    # --- CRITICAL ---
    {
        "rule_id": "critical_ssn",
        "name": "Social Security Numbers",
        "description": "Contains US SSNs (xxx-xx-xxxx)",
        "level": "critical",
        "patterns": [r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"],
        "weight": 10.0,
    },
    {
        "rule_id": "critical_cc",
        "name": "Credit Card Numbers",
        "description": "Contains credit card numbers (Luhn-validated at runtime)",
        "level": "critical",
        "patterns": [r"\b(?:\d{4}[-\s]?){3}\d{4}\b", r"\b3[47]\d{13}\b"],
        "weight": 10.0,
    },
    {
        "rule_id": "critical_medical",
        "name": "Medical Record Numbers",
        "description": "Contains medical record identifiers",
        "level": "critical",
        "patterns": [r"\b(?:MRN|MR|RECORD)[-:.]?\d{4,10}\b"],
        "keywords": ["diagnosis", "patient", "hipaa", "phi", "medical record"],
        "weight": 8.0,
    },
    {
        "rule_id": "critical_passport",
        "name": "Passport Numbers",
        "description": "Contains passport numbers",
        "level": "critical",
        "patterns": [r"\b[A-Z]{1,2}\d{6,9}\b"],
        "keywords": ["passport"],
        "weight": 9.0,
    },
    {
        "rule_id": "critical_biometric",
        "name": "Biometric Data",
        "description": "Contains biometric / fingerprint data references",
        "level": "critical",
        "keywords": ["fingerprint", "biometric", "faceprint", "iris scan",
                      "retina scan", "dna profile", "genetic data"],
        "weight": 9.0,
    },
    # --- RESTRICTED ---
    {
        "rule_id": "restricted_bank",
        "name": "Bank Account Details",
        "description": "Contains bank account or routing numbers",
        "level": "restricted",
        "patterns": [r"\b\d{8,17}\b"],
        "keywords": ["bank account", "routing number", "iban", "swift code"],
        "weight": 7.0,
    },
    {
        "rule_id": "restricted_dl",
        "name": "Driver's License Numbers",
        "description": "Contains driver's license numbers",
        "level": "restricted",
        "patterns": [r"\b[A-Z]{1,2}\d{5,9}\b"],
        "keywords": ["driver license", "driving license", "dl number"],
        "weight": 7.0,
    },
    {
        "rule_id": "restricted_pwd",
        "name": "Credentials & Secrets",
        "description": "Contains passwords, API keys, or secrets",
        "level": "restricted",
        "keywords": ["password", "passwd", "api_key", "apikey", "secret",
                      "auth_token", "access_token", "private_key",
                      "-----begin", "jwt", "bearer"],
        "weight": 7.0,
    },
    {
        "rule_id": "restricted_dob",
        "name": "Date of Birth",
        "description": "Contains dates of birth",
        "level": "restricted",
        "patterns": [r"\b\d{1,2}[/-]\d{1,2}[/-](?:\d{2}|\d{4})\b"],
        "keywords": ["date of birth", "dob", "birth_date", "birthdate"],
        "weight": 6.0,
    },
    {
        "rule_id": "restricted_employment",
        "name": "Employment / Salary Data",
        "description": "Contains employment or compensation data",
        "level": "restricted",
        "keywords": ["salary", "compensation", "payroll", "bonus",
                      "termination", "disciplinary", "performance review",
                      "offer letter", "employee_id"],
        "weight": 6.0,
    },
    # --- CONFIDENTIAL ---
    {
        "rule_id": "confidential_email",
        "name": "Email Addresses",
        "description": "Contains personal email addresses",
        "level": "confidential",
        "patterns": [r"\b[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@"
                     r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}\.[A-Za-z]{2,}\b"],
        "weight": 5.0,
    },
    {
        "rule_id": "confidential_phone",
        "name": "Phone Numbers",
        "description": "Contains phone numbers",
        "level": "confidential",
        "patterns": [r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"],
        "keywords": ["phone", "telephone", "mobile", "cell"],
        "weight": 5.0,
    },
    {
        "rule_id": "confidential_address",
        "name": "Physical Address",
        "description": "Contains street address data",
        "level": "confidential",
        "keywords": ["street", "avenue", "road", "drive", "lane",
                      "boulevard", "apt", "suite", "po box",
                      "postal code", "zip code", "city", "state"],
        "weight": 4.0,
    },
    {
        "rule_id": "confidential_ip",
        "name": "IP Addresses",
        "description": "Contains internal IP addresses",
        "level": "confidential",
        "patterns": [
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
            r"\b(?:172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b",
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3})\b",
        ],
        "weight": 4.0,
    },
    {
        "rule_id": "confidential_financial",
        "name": "Financial Data",
        "description": "Contains financial or invoice data",
        "level": "confidential",
        "keywords": ["invoice", "purchase order", "po number",
                      "vendor", "supplier", "contract value",
                      "budget", "revenue", "profit", "margin"],
        "weight": 4.0,
    },
    {
        "rule_id": "confidential_hr",
        "name": "HR / Personnel Data",
        "description": "Contains HR or personnel information",
        "level": "confidential",
        "keywords": ["employee", "staff", "personnel", "hire date",
                      "job title", "department", "manager",
                      "work location", "employment status"],
        "weight": 4.0,
    },
    {
        "rule_id": "confidential_legal",
        "name": "Legal Data",
        "description": "Contains legal information",
        "level": "confidential",
        "keywords": ["attorney-client", "legal hold", "litigation",
                      "nda", "confidential agreement", "settlement",
                      "lawsuit", "subpoena", "compliance"],
        "weight": 4.0,
    },
    # --- INTERNAL ---
    {
        "rule_id": "internal_business",
        "name": "Internal Business Data",
        "description": "General internal business information",
        "level": "internal",
        "keywords": ["internal", "proprietary", "business plan",
                      "strategy", "roadmap", "forecast",
                      "project plan", "sprint", "epic",
                      "internal memo", "internal note"],
        "weight": 2.0,
    },
    {
        "rule_id": "internal_username",
        "name": "Usernames / Employee IDs",
        "description": "Contains internal usernames or employee IDs",
        "level": "internal",
        "keywords": ["username", "user_id", "userid", "employee_id",
                      "emp_id", "login", "handle"],
        "weight": 2.0,
    },
]


class DataClassifier:
    """Classifies data into sensitivity levels based on content,
    keywords, and metadata.

    Classification flow:
    1.  Match content against registered regex patterns.
    2.  Match content against registered keyword lists.
    3.  Score each matching rule by its weight; aggregate to a level.
    4.  Return the highest-scoring level with a confidence score.

    Levels: public (0) < internal (1) < confidential (2)
            < restricted (3) < critical (4)
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        default_level: Union[str, SensitivityLevel] = SensitivityLevel.INTERNAL,
    ) -> None:
        """Initialise the classifier.

        Args:
            config_path: Optional YAML/JSON file with custom rules.
            default_level: Level assigned when no rules match.
        """
        self._rules: List[ClassificationRule] = []
        self._compiled_patterns: Dict[str, List[Pattern]] = {}
        self._default_level = (
            default_level.value if isinstance(default_level, SensitivityLevel)
            else default_level
        )
        self._config_path = Path(config_path).resolve() if config_path else None

        self._load_builtin_rules()

        if self._config_path and self._config_path.exists():
            self.load_rules_from_config(self._config_path)

        logger.info(
            "DataClassifier initialized (rules=%d, default=%s)",
            len(self._rules), self._default_level,
        )

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: ClassificationRule) -> None:
        """Register a classification rule.

        Patterns are pre-compiled for performance.
        """
        self._rules.append(rule)
        if rule.patterns:
            compiled: List[Pattern] = []
            for p in rule.patterns:
                try:
                    compiled.append(re.compile(p))
                except re.error as exc:
                    logger.warning("Invalid pattern in rule %s: %s", rule.rule_id, exc)
                    continue
            self._compiled_patterns[rule.rule_id] = compiled
        logger.debug("Added classification rule: %s (%s)", rule.rule_id, rule.level)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID.

        Returns True if found and removed.
        """
        for i, r in enumerate(self._rules):
            if r.rule_id == rule_id:
                self._rules.pop(i)
                self._compiled_patterns.pop(rule_id, None)
                logger.debug("Removed classification rule: %s", rule_id)
                return True
        return False

    def get_rules(self, include_disabled: bool = False) -> List[ClassificationRule]:
        if include_disabled:
            return list(self._rules)
        return [r for r in self._rules if r.enabled]

    def enable_rule(self, rule_id: str, enabled: bool = True) -> bool:
        for r in self._rules:
            if r.rule_id == rule_id:
                r.enabled = enabled
                return True
        return False

    def clear_rules(self) -> None:
        self._rules.clear()
        self._compiled_patterns.clear()
        logger.info("All classification rules cleared")

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    def load_rules_from_config(self, path: Union[str, Path]) -> int:
        """Load classification rules from YAML or JSON.

        Expected YAML format:
        ```yaml
        rules:
          - rule_id: critical_ssn
            name: SSN Detection
            description: Detects US Social Security Numbers
            level: critical
            patterns:
              - "\\\\b(?!000|666|9\\\\d{2})\\\\d{3}-(?!00)\\\\d{2}-(?!0000)\\\\d{4}\\\\b"
            keywords: []
            weight: 10.0
            enabled: true
        ```
        Returns the number of rules loaded.
        """
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            logger.error("Config file not found: %s", path_obj)
            return 0

        raw = path_obj.read_text(encoding="utf-8")
        suffix = path_obj.suffix.lower()

        try:
            if suffix in (".yaml", ".yml"):
                data = yaml.safe_load(raw)
            elif suffix == ".json":
                data = json.loads(raw)
            else:
                raise ValueError(f"Unsupported format: {suffix}")
        except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse config: %s", exc)
            return 0

        if not isinstance(data, dict) or "rules" not in data:
            logger.warning("No 'rules' key in %s", path_obj)
            return 0

        count = 0
        for entry in data["rules"]:
            try:
                rule = ClassificationRule(
                    rule_id=entry["rule_id"],
                    name=entry.get("name", entry["rule_id"]),
                    description=entry.get("description", ""),
                    level=entry.get("level", self._default_level),
                    patterns=entry.get("patterns", []),
                    keywords=entry.get("keywords", []),
                    match_any=entry.get("match_any", True),
                    weight=entry.get("weight", 1.0),
                    enabled=entry.get("enabled", True),
                )
                self.add_rule(rule)
                count += 1
            except KeyError as exc:
                logger.warning("Skipping rule entry missing key: %s", exc)
        logger.info("Loaded %d classification rules from %s", count, path_obj)
        return count

    # ------------------------------------------------------------------
    # Core classification
    # ------------------------------------------------------------------

    def classify(
        self,
        data: Union[str, Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> ClassificationResult:
        """Classify a single data item (string or dict).

        For dicts, each string value is scanned; the highest level
        among all values is returned.

        Args:
            data: The data to classify (string or dictionary).
            context: Optional metadata (e.g., {'source': 'api', 'owner': 'hr'}).

        Returns:
            A ClassificationResult with the assigned level, score, and details.
        """
        if isinstance(data, dict):
            return self._classify_dict(data, context or {})
        return self._classify_text(data, context or {})

    def classify_batch(
        self,
        dataset: List[Union[str, Dict[str, Any]]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ClassificationResult]:
        """Classify a batch of items.

        Args:
            dataset: List of strings or dicts.
            context: Optional metadata applied to every item.

        Returns:
            List of ClassificationResult objects.
        """
        ctx = context or {}
        return [self.classify(item, ctx) for item in dataset]

    def classify_text(self, text: str) -> ClassificationResult:
        """Convenience: classify a plain string."""
        return self._classify_text(text, {})

    # ------------------------------------------------------------------
    # Metadata-based classification
    # ------------------------------------------------------------------

    def classify_with_metadata(
        self,
        data: Union[str, Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> ClassificationResult:
        """Classify data using both content and metadata hints.

        Metadata keys that influence classification:
        - source (str): e.g. 'hr_system', 'payment_processor'
        - owner (str): e.g. 'legal', 'finance'
        - contains_pii (bool)
        - regulatory (list): e.g. ['gdpr', 'hipaa', 'pci']
        - data_type (str): e.g. 'health', 'financial', 'personal'

        The metadata can elevate the level by up to one step.
        """
        result = self.classify(data)

        elevation_score = 0.0

        source = str(metadata.get("source", "")).lower()
        if any(s in source for s in ("hr", "payroll", "legal", "finance", "medical")):
            elevation_score += 1.0
        if metadata.get("contains_pii", False):
            elevation_score += 2.0

        regulatory = metadata.get("regulatory", [])
        if any(r.lower() in ("hipaa", "gdpr", "pci", "sox", "ccpa") for r in regulatory):
            elevation_score += 3.0

        data_type = str(metadata.get("data_type", "")).lower()
        if data_type in ("health", "biometric", "genetic"):
            elevation_score += 3.0
        elif data_type in ("financial", "payment", "banking"):
            elevation_score += 2.0
        elif data_type in ("personal", "demographic"):
            elevation_score += 1.0

        if elevation_score >= 3.0:
            elevated = self._elevate_level(result.level, 2)
        elif elevation_score >= 1.0:
            elevated = self._elevate_level(result.level, 1)
        else:
            elevated = result.level

        return ClassificationResult(
            level=elevated,
            score=min(1.0, result.score + elevation_score * 0.05),
            matched_rules=result.matched_rules,
            details=result.details,
            is_classified=result.is_classified,
            classified_at=_utc_now_str(),
        )

    # ------------------------------------------------------------------
    # Summary & reporting
    # ------------------------------------------------------------------

    def classify_batch_with_summary(
        self,
        dataset: List[Union[str, Dict[str, Any]]],
    ) -> Tuple[List[ClassificationResult], ClassificationSummary]:
        """Classify a batch and return results plus a summary."""
        results = self.classify_batch(dataset)

        level_counts: Counter[str] = Counter()
        rule_hits: Counter[str] = Counter()
        total_score = 0.0

        for r in results:
            level_counts[r.level] += 1
            total_score += r.score
            for rid in r.matched_rules:
                rule_hits[rid] += 1

        n = len(results) or 1
        level_pcts = {
            level: (count / n * 100.0) for level, count in level_counts.items()
        }

        levels_present = [SensitivityLevel(lvl) for lvl in level_counts]
        highest = max(levels_present, key=lambda x: _LEVEL_RANK.get(x, 0)) if levels_present else SensitivityLevel.PUBLIC
        lowest = min(levels_present, key=lambda x: _LEVEL_RANK.get(x, 0)) if levels_present else SensitivityLevel.PUBLIC

        summary = ClassificationSummary(
            total_items=len(results),
            level_counts=dict(level_counts),
            level_percentages=level_pcts,
            rule_hit_counts=dict(rule_hits),
            average_score=total_score / n,
            highest_level=highest.value,
            lowest_level=lowest.value,
            generated_at=_utc_now_str(),
        )

        return results, summary

    # ------------------------------------------------------------------
    # Internal classification logic
    # ------------------------------------------------------------------

    def _classify_text(
        self,
        text: str,
        context: Dict[str, Any],
    ) -> ClassificationResult:
        """Classify a plain text string."""
        text_lower = text.lower()
        matched_rules: List[str] = []
        details: List[Dict[str, Any]] = []
        max_score = 0.0
        max_level_rank = 0

        for rule in self._rules:
            if not rule.enabled:
                continue

            pattern_matched = False
            keyword_matched = False

            # Check patterns
            compiled = self._compiled_patterns.get(rule.rule_id, [])
            for cp in compiled:
                if cp.search(text):
                    pattern_matched = True
                    break

            # Check keywords (case-insensitive substring)
            for kw in rule.keywords:
                if kw.lower() in text_lower:
                    keyword_matched = True
                    break

            if rule.match_any:
                matched = pattern_matched or keyword_matched
            else:
                matched = pattern_matched and keyword_matched

            if matched:
                matched_rules.append(rule.rule_id)
                rule_level_rank = level_rank(rule.level)
                score = rule.weight / 10.0

                details.append({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "level": rule.level,
                    "score": score,
                    "pattern_match": pattern_matched,
                    "keyword_match": keyword_matched,
                })

                if rule_level_rank > max_level_rank:
                    max_level_rank = rule_level_rank
                    max_score = score
                elif rule_level_rank == max_level_rank:
                    max_score = max(max_score, score)

        if not matched_rules:
            return ClassificationResult(
                level=self._default_level,
                score=0.0,
                matched_rules=[],
                details=[],
                is_classified=False,
                classified_at=_utc_now_str(),
            )

        # Determine final level from max_level_rank
        final_level = _LEVEL_ORDER[max_level_rank].value
        confidence = min(1.0, max_score + len(matched_rules) * 0.05)

        return ClassificationResult(
            level=final_level,
            score=confidence,
            matched_rules=matched_rules,
            details=details,
            is_classified=True,
            classified_at=_utc_now_str(),
        )

    def _classify_dict(
        self,
        data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ClassificationResult:
        """Classify a dictionary by scanning all string values.

        Returns the highest sensitivity level found across all values.
        """
        combined_scores: Dict[str, float] = {}
        all_matched_rules: Set[str] = set()
        all_details: List[Dict[str, Any]] = []

        def _scan(value: Any) -> None:
            if isinstance(value, str):
                result = self._classify_text(value, context)
                if result.is_classified:
                    all_matched_rules.update(result.matched_rules)
                    all_details.extend(result.details)
                    current = level_rank(result.level)
                    combined_scores[result.level] = max(
                        combined_scores.get(result.level, 0.0),
                        result.score,
                    )
            elif isinstance(value, dict):
                for v in value.values():
                    _scan(v)
            elif isinstance(value, list):
                for item in value:
                    _scan(item)

        _scan(data)

        if not all_matched_rules:
            return ClassificationResult(
                level=self._default_level,
                score=0.0,
                matched_rules=[],
                details=[],
                is_classified=False,
                classified_at=_utc_now_str(),
            )

        # Pick the highest level rank
        levels_found = [SensitivityLevel(lvl) for lvl in combined_scores]
        top_level = max(levels_found, key=lambda x: _LEVEL_RANK.get(x, 0))
        top_score = combined_scores.get(top_level.value, 0.0)

        return ClassificationResult(
            level=top_level.value,
            score=min(1.0, top_score + len(all_matched_rules) * 0.02),
            matched_rules=list(all_matched_rules),
            details=all_details,
            is_classified=True,
            classified_at=_utc_now_str(),
        )

    def _elevate_level(self, current_level: str, steps: int = 1) -> str:
        """Raise a sensitivity level by *steps* (max CRITICAL)."""
        try:
            current = SensitivityLevel(current_level)
        except ValueError:
            return current_level
        rank = _LEVEL_RANK.get(current, 0)
        new_rank = min(len(_LEVEL_ORDER) - 1, rank + steps)
        return _LEVEL_ORDER[new_rank].value

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def compare_levels(
        self,
        level_a: Union[str, SensitivityLevel],
        level_b: Union[str, SensitivityLevel],
    ) -> int:
        """Compare two sensitivity levels.

        Returns:
            -1 if level_a < level_b, 0 if equal, 1 if level_a > level_b.
        """
        rank_a = level_rank(level_a)
        rank_b = level_rank(level_b)
        if rank_a < rank_b:
            return -1
        if rank_a > rank_b:
            return 1
        return 0

    def is_at_least(
        self,
        level: Union[str, SensitivityLevel],
        minimum: Union[str, SensitivityLevel],
    ) -> bool:
        """Check if *level* is at least *minimum* on the sensitivity scale."""
        return level_rank(level) >= level_rank(minimum)

    def export_rules_config(self, path: Union[str, Path], fmt: str = "yaml") -> None:
        """Export current rules to a config file."""
        rules_data = []
        for r in self._rules:
            rules_data.append(asdict(r))
        payload = {
            "rules": rules_data,
            "meta": {"exported_at": _utc_now_str(), "default_level": self._default_level},
        }
        path_obj = Path(path).resolve()
        if fmt == "json":
            path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            path_obj.write_text(yaml.dump(payload, default_flow_style=False), encoding="utf-8")
        logger.info("Exported %d rules to %s", len(rules_data), path_obj)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_builtin_rules(self) -> None:
        """Register the built-in classification rules."""
        for entry in _BUILTIN_PATTERNS:
            rule = ClassificationRule(
                rule_id=entry["rule_id"],
                name=entry["name"],
                description=entry["description"],
                level=entry["level"],
                patterns=entry.get("patterns", []),
                keywords=entry.get("keywords", []),
                match_any=entry.get("match_any", True),
                weight=entry.get("weight", 1.0),
                enabled=True,
            )
            self.add_rule(rule)

    def __repr__(self) -> str:
        return f"DataClassifier(rules={len(self._rules)}, default={self._default_level})"


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()
