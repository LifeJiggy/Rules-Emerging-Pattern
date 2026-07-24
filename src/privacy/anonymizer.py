"""Data anonymization module for privacy-preserving transformations.

Provides the Anonymizer class that applies field-level anonymization
strategies including generalization (rounding, binning, range replacement),
suppression (masking, partial show), and perturbation (noise addition,
value swapping).  Supports k-anonymity checks on tabular datasets and
config-driven anonymization rules loaded from YAML/JSON files.
"""
import copy
import csv
import io
import json
import logging
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class AnonymizationTechnique(Enum):
    """Supported anonymization techniques."""
    SUPPRESS_ALL = "suppress_all"
    SUPPRESS_MASK = "suppress_mask"
    SUPPRESS_PARTIAL = "suppress_partial"
    GENERALIZE_ROUND = "generalize_round"
    GENERALIZE_BIN = "generalize_bin"
    GENERALIZE_RANGE = "generalize_range"
    PERTURB_NOISE = "perturb_noise"
    PERTURB_SWAP = "perturb_swap"
    PSEUDONYMIZE = "pseudonymize"
    REDACT = "redact"


@dataclass
class AnonymizationStrategy:
    """Describes how a single field should be anonymized.

    Attributes:
        field: The field name (or nested key path) this strategy applies to.
        technique: An AnonymizationTechnique value.
        params: Technique-specific parameters (see class docs).
    """
    field: str
    technique: AnonymizationTechnique
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnonymizationRule:
    """A complete rule that combines a strategy with match conditions.

    Attributes:
        rule_id: Unique identifier for the rule.
        description: Human-readable description.
        strategies: List of AnonymizationStrategy for fields matched.
        match_pattern: Optional regex pattern; if set the rule only
            applies when the field value matches this pattern.
        enabled: Whether the rule is active.
    """
    rule_id: str
    description: str
    strategies: List[AnonymizationStrategy] = field(default_factory=list)
    match_pattern: str = ""
    enabled: bool = True


@dataclass
class KAnonymityReport:
    """Result of a k-anonymity check on a tabular dataset.

    Attributes:
        is_satisfied: True if all equivalence classes have size >= k.
        k: The target k value.
        dataset_size: Total rows in the dataset.
        equivalence_classes: Count of each equivalence class (quasi-id tuples).
        smallest_class_size: Size of the smallest equivalence class.
        num_violations: Number of rows in classes smaller than k.
        violation_rows: Indices of rows that violate k-anonymity.
        quasi_identifiers: The column names used as quasi-identifiers.
    """
    is_satisfied: bool
    k: int
    dataset_size: int
    equivalence_classes: Dict[str, int]
    smallest_class_size: int
    num_violations: int
    violation_rows: List[int]
    quasi_identifiers: List[str]


@dataclass
class AnonymizationReport:
    """Aggregated statistics from an anonymization run."""
    total_rows: int
    total_fields_anonymized: int
    strategies_applied: Dict[str, int]
    fields_anonymized: Dict[str, int]
    started_at: str
    completed_at: str
    duration_ms: float


# ---------------------------------------------------------------------------
# Built-in strategy implementations
# ---------------------------------------------------------------------------

def _strategy_suppress_all(value: Any, params: Dict[str, Any]) -> Any:
    """Replace the value entirely with a placeholder."""
    placeholder = params.get("placeholder", "[ANONYMIZED]")
    return placeholder


def _strategy_suppress_mask(value: Any, params: Dict[str, Any]) -> Any:
    """Replace characters with a mask character, preserving length."""
    if not isinstance(value, str):
        value = str(value)
    mask_char = params.get("mask_char", "*")
    preserve_first = params.get("preserve_first", 0)
    preserve_last = params.get("preserve_last", 0)
    if preserve_first + preserve_last >= len(value):
        return value
    masked = (
        value[:preserve_first]
        + mask_char * (len(value) - preserve_first - preserve_last)
        + value[-preserve_last:] if preserve_last > 0 else ""
    )
    return masked


def _strategy_suppress_partial(value: Any, params: Dict[str, Any]) -> Any:
    """Show only the first/last N characters, masking the rest."""
    if not isinstance(value, str):
        value = str(value)
    show_first = params.get("show_first", 2)
    show_last = params.get("show_last", 2)
    mask_char = params.get("mask_char", "*")
    if show_first + show_last >= len(value):
        return value
    masked = (
        value[:show_first]
        + mask_char * (len(value) - show_first - show_last)
        + value[-show_last:] if show_last > 0 else ""
    )
    return masked


def _strategy_generalize_round(value: Any, params: Dict[str, Any]) -> Any:
    """Round a numeric value to a given precision."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    precision = params.get("precision", 0)
    factor = 10 ** precision
    return round(num / factor) * factor


def _strategy_generalize_bin(value: Any, params: Dict[str, Any]) -> Any:
    """Assign a numeric value to a bin (range bucket).

    Params:
        bin_size: Width of each bin (default 10).
        label_format: 'lower', 'upper', 'range' (default 'range').
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    bin_size = params.get("bin_size", 10)
    lower = math.floor(num / bin_size) * bin_size
    upper = lower + bin_size
    fmt = params.get("label_format", "range")
    if fmt == "lower":
        return lower
    if fmt == "upper":
        return upper
    return f"{lower}-{upper}"


def _strategy_generalize_range(value: Any, params: Dict[str, Any]) -> Any:
    """Replace a value with a broader range.

    Params:
        ranges: List of tuples [(low, high, label), ...].
        If the value falls within a range, the range label is returned.
        If no range matches, the value is returned unchanged.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    ranges: List[Tuple[float, float, str]] = params.get("ranges", [])
    if not ranges:
        return value
    for low, high, label in ranges:
        if low <= num < high:
            return label
    return value


def _strategy_perturb_noise(value: Any, params: Dict[str, Any]) -> Any:
    """Add random noise to a numeric value.

    Params:
        noise_std: Standard deviation of the Gaussian noise (default 1.0).
        min_value: Optional floor for the result.
        max_value: Optional ceiling for the result.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    std = params.get("noise_std", 1.0)
    noisy = num + random.gauss(0, std)
    min_val = params.get("min_value")
    max_val = params.get("max_value")
    if min_val is not None:
        noisy = max(noisy, float(min_val))
    if max_val is not None:
        noisy = min(noisy, float(max_val))
    if isinstance(value, int):
        return int(round(noisy))
    return noisy


def _strategy_perturb_swap(value: Any, params: Dict[str, Any]) -> Any:
    """Swap the value with another from a pool.

    Params:
        pool: List of possible replacement values.
        deterministic: If True, use hash-based selection (default False).
    """
    pool: List[Any] = params.get("pool", [])
    if not pool:
        return value
    deterministic = params.get("deterministic", False)
    if deterministic:
        idx = hash(str(value)) % len(pool)
    else:
        idx = random.randint(0, len(pool) - 1)
    return pool[idx]


def _strategy_pseudonymize(value: Any, params: Dict[str, Any]) -> Any:
    """Replace the value with a deterministic pseudonym (hash-based).

    Params:
        salt: An optional salt string added before hashing.
        prefix: Optional prefix for the pseudonym (default 'anon_').
        length: Length of the hash prefix to use (default 12).
    """
    raw = str(value)
    salt = params.get("salt", "")
    prefix = params.get("prefix", "anon_")
    length = params.get("length", 12)
    import hashlib
    digest = hashlib.sha256((salt + raw).encode()).hexdigest()[:length]
    return f"{prefix}{digest}"


_STRATEGY_DISPATCH: Dict[AnonymizationTechnique, Callable[[Any, Dict[str, Any]], Any]] = {
    AnonymizationTechnique.SUPPRESS_ALL: _strategy_suppress_all,
    AnonymizationTechnique.SUPPRESS_MASK: _strategy_suppress_mask,
    AnonymizationTechnique.SUPPRESS_PARTIAL: _strategy_suppress_partial,
    AnonymizationTechnique.GENERALIZE_ROUND: _strategy_generalize_round,
    AnonymizationTechnique.GENERALIZE_BIN: _strategy_generalize_bin,
    AnonymizationTechnique.GENERALIZE_RANGE: _strategy_generalize_range,
    AnonymizationTechnique.PERTURB_NOISE: _strategy_perturb_noise,
    AnonymizationTechnique.PERTURB_SWAP: _strategy_perturb_swap,
    AnonymizationTechnique.PSEUDONYMIZE: _strategy_pseudonymize,
    AnonymizationTechnique.REDACT: _strategy_suppress_all,
}


class Anonymizer:
    """Anonymizes structured data using configurable per-field strategies.

    Supports three families of anonymization techniques:

    *Suppression* – replace values with placeholders or masked strings.
    *Generalization* – round, bin, or replace with broader ranges.
    *Perturbation* – add noise or swap with pool values.
    *Pseudonymization* – deterministic hash-based replacement.

    Tabular data (list of dicts) can be checked for k-anonymity to
    measure re-identification risk.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        default_strategy: Optional[AnonymizationTechnique] = None,
        seed: Optional[int] = None,
    ) -> None:
        """Initialise the anonymizer.

        Args:
            config_path: Optional YAML/JSON file with anonymization rules.
            default_strategy: Strategy applied when a field has no explicit rule.
            seed: Random seed for reproducible perturbation.
        """
        self._rules: List[AnonymizationRule] = []
        self._default_strategy = default_strategy
        self._config_path = Path(config_path).resolve() if config_path else None

        if seed is not None:
            random.seed(seed)

        if self._config_path and self._config_path.exists():
            self.load_rules_from_config(self._config_path)

        logger.info(
            "Anonymizer initialized (rules=%d, default=%s)",
            len(self._rules), self._default_strategy,
        )

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: AnonymizationRule) -> None:
        """Register an anonymization rule."""
        self._rules.append(rule)
        logger.debug("Added rule: %s", rule.rule_id)

    def add_strategy(
        self,
        field: str,
        technique: Union[str, AnonymizationTechnique],
        params: Optional[Dict[str, Any]] = None,
        rule_id: str = "auto",
        description: str = "",
    ) -> AnonymizationRule:
        """Convenience method: create a single-strategy rule.

        Args:
            field: Target field name.
            technique: AnonymizationTechnique or its string name.
            params: Technique parameters.
            rule_id: Optional rule identifier.
            description: Optional description.

        Returns:
            The created AnonymizationRule.
        """
        if isinstance(technique, str):
            technique = AnonymizationTechnique(technique)
        strategy = AnonymizationStrategy(
            field=field,
            technique=technique,
            params=params or {},
        )
        rule = AnonymizationRule(
            rule_id=rule_id or f"rule_{len(self._rules) + 1}",
            description=description or f"Anonymize {field} via {technique.value}",
            strategies=[strategy],
            enabled=True,
        )
        self.add_rule(rule)
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by its ID.

        Returns True if found and removed.
        """
        for i, r in enumerate(self._rules):
            if r.rule_id == rule_id:
                self._rules.pop(i)
                logger.debug("Removed rule: %s", rule_id)
                return True
        return False

    def get_rules(self, include_disabled: bool = False) -> List[AnonymizationRule]:
        if include_disabled:
            return list(self._rules)
        return [r for r in self._rules if r.enabled]

    def clear_rules(self) -> None:
        self._rules.clear()
        logger.info("All anonymization rules cleared")

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    def load_rules_from_config(self, path: Union[str, Path]) -> int:
        """Load anonymization rules from YAML or JSON.

        Expected YAML format:
        ```yaml
        rules:
          - rule_id: mask_email
            description: Mask email addresses
            strategies:
              - field: email
                technique: suppress_partial
                params:
                  show_first: 2
                  show_last: 0
                  mask_char: "*"
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
                strategies = []
                for s in entry.get("strategies", []):
                    technique = AnonymizationTechnique(s["technique"])
                    strategies.append(AnonymizationStrategy(
                        field=s["field"],
                        technique=technique,
                        params=s.get("params", {}),
                    ))
                rule = AnonymizationRule(
                    rule_id=entry["rule_id"],
                    description=entry.get("description", ""),
                    strategies=strategies,
                    match_pattern=entry.get("match_pattern", ""),
                    enabled=entry.get("enabled", True),
                )
                self.add_rule(rule)
                count += 1
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping rule entry: %s", exc)
        logger.info("Loaded %d rules from %s", count, path_obj)
        return count

    # ------------------------------------------------------------------
    # Core anonymization
    # ------------------------------------------------------------------

    def anonymize(
        self,
        data: Dict[str, Any],
        strategy_map: Optional[Dict[str, Dict[str, Any]]] = None,
        in_place: bool = False,
    ) -> Dict[str, Any]:
        """Anonymize a single record (dictionary).

        Two sources of strategies are merged:
        1.  Registered rules (self._rules) whose field paths apply.
        2.  The *strategy_map* argument, keyed by field name, where
            each value is ``{"technique": "...", "params": {...}}``.

        Args:
            data: The record to anonymize.
            strategy_map: Inline strategies that override registered rules.
            in_place: If True, modify *data* in place; otherwise return a copy.

        Returns:
            The anonymized dictionary.
        """
        result = data if in_place else copy.deepcopy(data)

        # Build field->strategy lookup from registered rules
        field_strategies: Dict[str, AnonymizationStrategy] = {}
        for rule in self._rules:
            if not rule.enabled:
                continue
            for s in rule.strategies:
                if s.field not in field_strategies:
                    field_strategies[s.field] = s

        # Merge / override with inline strategy_map
        if strategy_map:
            for field_name, spec in strategy_map.items():
                technique = spec.get("technique")
                if isinstance(technique, str):
                    technique = AnonymizationTechnique(technique)
                field_strategies[field_name] = AnonymizationStrategy(
                    field=field_name,
                    technique=technique,
                    params=spec.get("params", {}),
                )

        for field_path, strategy in field_strategies.items():
            self._apply_strategy_to_field(result, field_path, strategy)

        return result

    def anonymize_batch(
        self,
        dataset: List[Dict[str, Any]],
        strategy_map: Optional[Dict[str, Dict[str, Any]]] = None,
        in_place: bool = False,
    ) -> List[Dict[str, Any]]:
        """Anonymize a batch of records (tabular dataset).

        Args:
            dataset: List of dictionaries.
            strategy_map: Optional inline strategies.
            in_place: If True, modify dataset in place.

        Returns:
            The anonymized list of records.
        """
        if in_place:
            for row in dataset:
                self.anonymize(row, strategy_map=strategy_map, in_place=True)
            return dataset

        return [self.anonymize(row, strategy_map=strategy_map) for row in dataset]

    def anonymize_value(
        self,
        value: Any,
        technique: Union[str, AnonymizationTechnique],
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Anonymize a single value using a given technique.

        Useful when you want to apply a technique directly without
        building a full rule or strategy map.

        Args:
            value: The value to anonymize.
            technique: AnonymizationTechnique or string name.
            params: Technique-specific parameters.

        Returns:
            The anonymized value.
        """
        if isinstance(technique, str):
            technique = AnonymizationTechnique(technique)
        handler = _STRATEGY_DISPATCH.get(technique)
        if handler is None:
            logger.warning("Unknown technique: %s", technique)
            return value
        return handler(value, params or {})

    # ------------------------------------------------------------------
    # k-Anonymity
    # ------------------------------------------------------------------

    def check_k_anonymity(
        self,
        dataset: List[Dict[str, Any]],
        quasi_identifiers: List[str],
        k: int = 5,
    ) -> KAnonymityReport:
        """Check whether *dataset* satisfies k-anonymity on the given
        quasi-identifiers.

        An equivalence class is a set of rows that share identical values
        for all quasi-identifier columns.  k-anonymity is satisfied when
        every equivalence class has at least *k* members.

        Args:
            dataset: Tabular data as a list of dictionaries.
            quasi_identifiers: Column names used as quasi-identifiers.
            k: Minimum equivalence class size.

        Returns:
            A KAnonymityReport with detailed findings.
        """
        if not dataset:
            return KAnonymityReport(
                is_satisfied=(k <= 0),
                k=k,
                dataset_size=0,
                equivalence_classes={},
                smallest_class_size=0,
                num_violations=0,
                violation_rows=[],
                quasi_identifiers=quasi_identifiers,
            )

        eq_classes: Dict[str, List[int]] = defaultdict(list)

        for idx, row in enumerate(dataset):
            key_parts: List[str] = []
            for qi in quasi_identifiers:
                val = row.get(qi, "<MISSING>")
                key_parts.append(str(val))
            key = "|".join(key_parts)
            eq_classes[key].append(idx)

        class_sizes = {k: len(v) for k, v in eq_classes.items()}
        smallest = min(class_sizes.values()) if class_sizes else 0
        violation_rows: List[int] = []
        for cls_key, members in eq_classes.items():
            if len(members) < k:
                violation_rows.extend(members)

        return KAnonymityReport(
            is_satisfied=smallest >= k,
            k=k,
            dataset_size=len(dataset),
            equivalence_classes=class_sizes,
            smallest_class_size=smallest,
            num_violations=len(violation_rows),
            violation_rows=sorted(violation_rows),
            quasi_identifiers=quasi_identifiers,
        )

    # ------------------------------------------------------------------
    # Statistics & reporting
    # ------------------------------------------------------------------

    def generate_report(self) -> AnonymizationReport:
        """Generate a report describing the current configuration.

        Note: This reports on the ruleset configuration, not on a
        specific anonymization run (call :meth:`anonymize_batch` and
        then use this to describe configuration).
        """
        strategy_counts: Dict[str, int] = defaultdict(int)
        field_counts: Dict[str, int] = defaultdict(int)
        for rule in self._rules:
            if not rule.enabled:
                continue
            for s in rule.strategies:
                strategy_counts[s.technique.value] += 1
                field_counts[s.field] += 1

        now = _utc_now_str()
        return AnonymizationReport(
            total_rows=0,
            total_fields_anonymized=len(field_counts),
            strategies_applied=dict(strategy_counts),
            fields_anonymized=dict(field_counts),
            started_at=now,
            completed_at=now,
            duration_ms=0.0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_strategy_to_field(
        self,
        data: Dict[str, Any],
        field_path: str,
        strategy: AnonymizationStrategy,
    ) -> None:
        """Resolve *field_path* (dot-separated) in *data* and apply *strategy*.

        Handles nested paths like ``"address.zip"`` and list-indexed paths
        like ``"items.*.price"`` where ``*`` means "apply to each element".
        """
        parts = field_path.split(".")

        current = data
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)

            if part == "*":
                if isinstance(current, list):
                    remaining = ".".join(parts[i + 1:]) if not is_last else ""
                    for item in current:
                        if isinstance(item, dict):
                            if remaining:
                                self._apply_strategy_to_field(item, remaining, strategy)
                            else:
                                self._apply_field_value(item, strategy)
                return

            if is_last:
                self._apply_field_value(current, strategy, part)
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return

    def _apply_field_value(
        self,
        container: Dict[str, Any],
        strategy: AnonymizationStrategy,
        key: Optional[str] = None,
    ) -> None:
        """Apply the strategy to ``container[key]`` (or to all values if
        key is None)."""
        if key is not None:
            if key not in container:
                return
            handler = _STRATEGY_DISPATCH.get(strategy.technique)
            if handler is None:
                logger.warning("No handler for technique %s", strategy.technique)
                return
            container[key] = handler(container[key], strategy.params)
            return

        for k in list(container.keys()):
            handler = _STRATEGY_DISPATCH.get(strategy.technique)
            if handler:
                container[k] = handler(container[k], strategy.params)

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_rules_config(self, path: Union[str, Path], fmt: str = "yaml") -> None:
        """Export current rules to a config file."""
        rules_data = []
        for r in self._rules:
            strategies = []
            for s in r.strategies:
                strategies.append({
                    "field": s.field,
                    "technique": s.technique.value,
                    "params": s.params,
                })
            rules_data.append({
                "rule_id": r.rule_id,
                "description": r.description,
                "strategies": strategies,
                "match_pattern": r.match_pattern,
                "enabled": r.enabled,
            })
        payload = {
            "rules": rules_data,
            "meta": {"exported_at": _utc_now_str()},
        }
        path_obj = Path(path).resolve()
        if fmt == "json":
            path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            path_obj.write_text(yaml.dump(payload, default_flow_style=False), encoding="utf-8")
        logger.info("Exported %d rules to %s", len(rules_data), path_obj)

    def __repr__(self) -> str:
        return f"Anonymizer(rules={len(self._rules)})"


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()
