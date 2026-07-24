"""Data redaction module for privacy protection.

Provides the DataRedactor class for detecting and redacting
personally identifiable information (PII) from text, dictionaries,
and batch data sources. Supports regex-based pattern matching,
Luhn algorithm validation for credit cards, custom rule registration,
audit logging, and config-driven pattern loading.
"""
import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)

_REDACTED_PLACEHOLDER = "[REDACTED]"

_COMMON_SENSITIVE_KEYS: Set[str] = {
    "ssn", "social_security", "socialsecurity",
    "email", "e_mail", "mail",
    "password", "passwd", "secret",
    "credit_card", "creditcard", "cc_number", "ccn",
    "phone", "telephone", "mobile", "cell",
    "address", "street", "zip", "zipcode",
    "passport", "passport_number",
    "drivers_license", "driver_license", "dl",
    "bank_account", "bankaccount", "account_number",
    "medical_record", "medicalrecord", "mrn",
    "api_key", "apikey", "token", "auth_token",
    "dob", "date_of_birth", "birth_date",
    "full_name", "first_name", "last_name",
    "ip_address", "ip",
}

_DEFAULT_REDACTION_LABELS: Dict[str, str] = {
    "ssn": "[REDACTED_SSN]",
    "email": "[REDACTED_EMAIL]",
    "credit_card": "[REDACTED_CC]",
    "phone": "[REDACTED_PHONE]",
    "ip": "[REDACTED_IP]",
    "passport": "[REDACTED_PASSPORT]",
    "drivers_license": "[REDACTED_DL]",
    "bank_account": "[REDACTED_BANK]",
    "medical_record": "[REDACTED_MEDICAL]",
    "dob": "[REDACTED_DOB]",
}


@dataclass
class RedactionRule:
    """Rule for redacting sensitive data.

    Attributes:
        pattern: Compiled regex pattern to match.
        replacement: Replacement string for matched text.
        description: Human-readable description of the pattern.
        label: Machine-readable label for statistics grouping.
        enabled: Whether the rule is active.
    """
    pattern: Pattern
    replacement: str
    description: str
    label: str = ""
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern.pattern,
            "replacement": self.replacement,
            "description": self.description,
            "label": self.label,
            "enabled": self.enabled,
        }


@dataclass
class RedactionAuditEntry:
    """A single redaction event recorded for audit purposes.

    Attributes:
        timestamp: ISO-format timestamp of the event.
        rule_label: The label of the rule that fired.
        match_count: Number of matches redacted.
        source: Description of the source being redacted (e.g. 'text', 'dict').
        context: Optional free-form context string.
    """
    timestamp: str
    rule_label: str
    match_count: int
    source: str
    context: str = ""


@dataclass
class RedactionReport:
    """Aggregated redaction statistics returned by generate_report()."""
    total_rules: int
    active_rules: int
    total_redactions_lifetime: int
    redactions_by_label: Dict[str, int]
    redactions_by_source: Dict[str, int]
    audit_log_size: int
    most_active_rules: List[Dict[str, Any]]
    report_time: str


def _luhn_check(digits: str) -> bool:
    """Validate a numeric string using the Luhn algorithm.

    Used to reduce false-positive credit-card matches by confirming
    that the detected number passes the checksum.
    """
    if not digits.isdigit():
        return False
    total = 0
    reverse_digits = digits[::-1]
    for i, ch in enumerate(reverse_digits):
        n = ord(ch) - 48
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _build_default_patterns() -> List[Tuple[str, str, str, str]]:
    """Return a list of (regex, replacement, description, label) tuples.

    Patterns cover common US / international PII formats.  The credit-card
    pattern is conservative (16-digit groups); the actual Luhn filter is
    applied at match time inside redact().
    """
    return [
        # --- SSN ---
        (r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
         _REDACTED_PLACEHOLDER, "Social Security Number", "ssn"),

        # --- Email ---
        (r"\b[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@"
         r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}\.[A-Za-z]{2,}\b",
         _REDACTED_PLACEHOLDER, "Email Address", "email"),

        # --- Credit Card (generic 16-digit format; Luhn applied at runtime) ---
        (r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
         _REDACTED_PLACEHOLDER, "Credit Card Number", "credit_card"),

        # --- Phone (US-centric but covers international with country code) ---
        (r"\b(?:\+?1[-.\s]?)?"             # optional country code
         r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
         _REDACTED_PLACEHOLDER, "Phone Number", "phone"),

        # --- IP address (IPv4) ---
        (r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
         r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
         _REDACTED_PLACEHOLDER, "IP Address (IPv4)", "ip"),

        # --- IPv6 (simplified) ---
        (r"\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b",
         _REDACTED_PLACEHOLDER, "IP Address (IPv6)", "ip"),

        # --- Passport (US letter+8digits; simplified international) ---
        (r"\b[A-Z]{1,2}\d{6,9}\b",
         _REDACTED_PLACEHOLDER, "Passport Number", "passport"),

        # --- US Driver's License (state-specific patterns) ---
        (r"\b[A-Z]{1,2}\d{5,9}\b",
         _REDACTED_PLACEHOLDER, "Driver's License Number", "drivers_license"),

        # --- Bank Account (8-17 digits, often with routing prefix) ---
        (r"\b\d{8,17}\b",
         _REDACTED_PLACEHOLDER, "Bank Account Number", "bank_account"),

        # --- Medical Record Number (alphanumeric, 6-12 chars) ---
        (r"\b(?:MRN|MR|RECORD)[-:.]?\d{4,10}\b",
         _REDACTED_PLACEHOLDER, "Medical Record Number", "medical_record"),

        # --- Date of Birth (common formats) ---
        (r"\b\d{1,2}[/-]\d{1,2}[/-](?:\d{2}|\d{4})\b",
         _REDACTED_PLACEHOLDER, "Date of Birth", "dob"),

        # --- Credit card with AMEX (15-digit, starts 34/37) ---
        (r"\b3[47]\d{13}\b",
         _REDACTED_PLACEHOLDER, "American Express Card", "credit_card"),
    ]


def _coerce_to_pattern(pattern_or_str: Union[str, Pattern]) -> Pattern:
    if isinstance(pattern_or_str, Pattern):
        return pattern_or_str
    return re.compile(pattern_or_str)


def _flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """Recursively flatten a nested dictionary.

    {"a": {"b": 1}} -> {"a.b": 1}
    """
    items: Dict[str, Any] = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items


class DataRedactor:
    """Redacts sensitive personally identifiable information from data.

    Supports:
    - Regex-based PII matching with compiled patterns
    - Custom rule registration from YAML / JSON configuration files
    - Luhn validation for credit-card numbers to reduce false positives
    - Dict redaction with sensitive-key awareness
    - Batch redaction for lists / iterables
    - Audit logging of every redaction event with timestamps
    - Statistics and report generation
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        enable_luhn_filter: bool = True,
        auto_load_config: bool = True,
    ) -> None:
        """Initialise the redactor with default rules and optional config.

        Args:
            config_path: Path to a YAML or JSON configuration file containing
                custom / override redaction rules.
            enable_luhn_filter: When True, credit-card patterns are validated
                with the Luhn algorithm before redacting.
            auto_load_config: If True and *config_path* is provided, rules
                are loaded automatically.
        """
        self._rules: List[RedactionRule] = []
        self._rules_by_label: Dict[str, List[RedactionRule]] = defaultdict(list)
        self._total_redactions: int = 0
        self._redactions_by_label: Dict[str, int] = defaultdict(int)
        self._redactions_by_source: Dict[str, int] = defaultdict(int)
        self._audit_log: List[RedactionAuditEntry] = []
        self._enable_luhn_filter = enable_luhn_filter
        self._config_path: Optional[Path] = (
            Path(config_path).resolve() if config_path else None
        )

        self._setup_default_rules()

        if auto_load_config and self._config_path is not None:
            if self._config_path.exists():
                self.load_rules_from_config(self._config_path)
            else:
                logger.warning(
                    "Config path %s does not exist; skipping load",
                    self._config_path,
                )

        logger.info(
            "DataRedactor initialized with %d default rules (luhn=%s)",
            len(self._rules), self._enable_luhn_filter,
        )

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(
        self,
        pattern: Union[str, Pattern],
        replacement: str = _REDACTED_PLACEHOLDER,
        description: str = "",
        label: str = "",
        enabled: bool = True,
    ) -> RedactionRule:
        """Compile and register a single redaction rule.

        Args:
            pattern: A regex string or compiled Pattern object.
            replacement: The text to substitute for matches.
            description: Human-readable description.
            label: Machine label for grouping in statistics.
            enabled: Whether the rule is active at creation time.

        Returns:
            The newly created RedactionRule instance.
        """
        compiled = _coerce_to_pattern(pattern)
        rule = RedactionRule(
            pattern=compiled,
            replacement=replacement,
            description=description or f"Custom rule #{len(self._rules) + 1}",
            label=label,
            enabled=enabled,
        )
        self._rules.append(rule)
        if label:
            self._rules_by_label[label].append(rule)
        logger.debug("Added rule: %s / %s", pattern, description)
        return rule

    def remove_rule(self, index: int) -> Optional[RedactionRule]:
        """Remove a rule by its list index.

        Args:
            index: Zero-based index into the internal rule list.

        Returns:
            The removed rule, or None if the index is out of range.
        """
        if index < 0 or index >= len(self._rules):
            logger.warning("remove_rule index %d out of range (size %d)",
                           index, len(self._rules))
            return None
        rule = self._rules.pop(index)
        for label, rules_for_label in self._rules_by_label.items():
            if rule in rules_for_label:
                rules_for_label.remove(rule)
        logger.debug("Removed rule at index %d: %s", index, rule.description)
        return rule

    def enable_rule(self, index: int, enabled: bool = True) -> bool:
        """Enable or disable a rule by index.

        Returns True on success, False if index is invalid.
        """
        if index < 0 or index >= len(self._rules):
            return False
        self._rules[index].enabled = enabled
        return True

    def get_rules(self, include_disabled: bool = False) -> List[RedactionRule]:
        """Return the current list of rules."""
        if include_disabled:
            return list(self._rules)
        return [r for r in self._rules if r.enabled]

    def get_rule_count(self, only_enabled: bool = True) -> int:
        if only_enabled:
            return sum(1 for r in self._rules if r.enabled)
        return len(self._rules)

    def clear_rules(self) -> None:
        """Remove all registered rules."""
        self._rules.clear()
        self._rules_by_label.clear()
        logger.info("All redaction rules cleared")

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    def load_rules_from_config(self, path: Union[str, Path]) -> int:
        """Load redaction rules from a YAML or JSON configuration file.

        Expected format (YAML):
        ```yaml
        rules:
          - pattern: "\\\\b\\\\d{3}-\\\\d{2}-\\\\d{4}\\\\b"
            replacement: "[REDACTED]"
            description: "SSN"
            label: ssn
            enabled: true
        ```

        Args:
            path: Path to the configuration file.

        Returns:
            Number of rules loaded.
        """
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            logger.error("Config file not found: %s", path_obj)
            return 0

        raw: str = path_obj.read_text(encoding="utf-8")
        suffix = path_obj.suffix.lower()

        try:
            if suffix in (".yaml", ".yml"):
                data = yaml.safe_load(raw)
            elif suffix == ".json":
                data = json.loads(raw)
            else:
                raise ValueError(f"Unsupported config format: {suffix}")
        except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse config %s: %s", path_obj, exc)
            return 0

        if not isinstance(data, dict) or "rules" not in data:
            logger.warning("Config %s has no 'rules' key", path_obj)
            return 0

        count = 0
        for entry in data["rules"]:
            if not isinstance(entry, dict) or "pattern" not in entry:
                continue
            try:
                self.add_rule(
                    pattern=entry["pattern"],
                    replacement=entry.get("replacement", _REDACTED_PLACEHOLDER),
                    description=entry.get("description", ""),
                    label=entry.get("label", ""),
                    enabled=entry.get("enabled", True),
                )
                count += 1
            except re.error as exc:
                logger.warning("Skipping invalid pattern in config: %s", exc)
        logger.info("Loaded %d rules from %s", count, path_obj)
        return count

    def export_rules_config(self, path: Union[str, Path], fmt: str = "yaml") -> None:
        """Export current rules to a configuration file.

        Args:
            path: Destination file path.
            fmt: Output format – ``"yaml"`` or ``"json"``.
        """
        rules_data = []
        for r in self._rules:
            rules_data.append({
                "pattern": r.pattern.pattern,
                "replacement": r.replacement,
                "description": r.description,
                "label": r.label,
                "enabled": r.enabled,
            })
        payload = {"rules": rules_data, "meta": {"exported_at": datetime.now(timezone.utc).isoformat()}}
        path_obj = Path(path).resolve()
        if fmt == "json":
            path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            path_obj.write_text(yaml.dump(payload, default_flow_style=False), encoding="utf-8")
        logger.info("Exported %d rules to %s", len(rules_data), path_obj)

    # ------------------------------------------------------------------
    # Core redaction
    # ------------------------------------------------------------------

    def redact(
        self,
        text: str,
        additional_rules: Optional[List[RedactionRule]] = None,
        context: str = "",
    ) -> str:
        """Redact sensitive information from *text*.

        Each enabled rule is applied in registration order.  Credit-card
        patterns are additionally validated with Luhn when
        ``enable_luhn_filter`` is True.

        Args:
            text: The input string to redact.
            additional_rules: Ephemeral rules applied only for this call.
            context: Optional context string recorded in the audit log.

        Returns:
            The redacted string.
        """
        if not text:
            return text

        redacted = text
        rules = self._rules + (additional_rules or [])
        local_counts: Dict[str, int] = defaultdict(int)

        for rule in rules:
            if not rule.enabled:
                continue

            # Find all matches first (needed for auditing and Luhn filter)
            matches = list(rule.pattern.finditer(redacted))
            if not matches:
                continue

            # If this is a credit-card rule and Luhn is enabled, filter
            # out matches that fail the checksum.
            if self._enable_luhn_filter and rule.label == "credit_card":
                valid_matches = []
                for m in matches:
                    # Strip separators for Luhn check
                    cleaned = re.sub(r"[-\s]", "", m.group())
                    if cleaned.isdigit() and len(cleaned) in (15, 16) and _luhn_check(cleaned):
                        valid_matches.append(m)
                matches = valid_matches
                if not matches:
                    continue

            # Apply substitution (process in reverse to preserve indices)
            for m in reversed(matches):
                start, end = m.start(), m.end()
                redacted = redacted[:start] + rule.replacement + redacted[end:]

            self._total_redactions += len(matches)
            self._redactions_by_label[rule.label] += len(matches)
            local_counts[rule.label] += len(matches)

            logger.debug(
                "Redacted %d instance(s) of '%s' via rule '%s'",
                len(matches), rule.description, rule.label,
            )

        source_tag = "text"
        self._redactions_by_source[source_tag] += sum(local_counts.values())

        if local_counts and not context.startswith("_noaudit"):
            self._audit_log.append(RedactionAuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                rule_label=",".join(f"{k}:{v}" for k, v in local_counts.items()),
                match_count=sum(local_counts.values()),
                source=source_tag,
                context=context,
            ))

        return redacted

    def redact_dict(
        self,
        data: Dict[str, Any],
        sensitive_keys: Optional[Set[str]] = None,
        recursive: bool = True,
        context: str = "dict",
    ) -> Dict[str, Any]:
        """Redact sensitive values inside a dictionary.

        Two-phase approach:
        1. If a key matches *sensitive_keys*, replace its entire value.
        2. For remaining string values, run the regex redactor.

        Args:
            data: The dictionary to redact.
            sensitive_keys: Set of key name substrings to treat as sensitive.
                Defaults to a comprehensive set of PII-related key names.
            recursive: Whether to recurse into nested dicts and lists.
            context: Audit-log context string.

        Returns:
            A new dictionary with redacted values (original is untouched).
        """
        keys = sensitive_keys or _COMMON_SENSITIVE_KEYS
        redacted: Dict[str, Any] = {}
        local_count = 0

        for key, value in data.items():
            key_lower = key.lower().replace(" ", "_")
            is_sensitive_key = any(s in key_lower for s in keys)

            if isinstance(value, dict) and recursive:
                redacted[key] = self.redact_dict(value, sensitive_keys=keys,
                                                  recursive=True, context=f"{context}.{key}")
            elif isinstance(value, list) and recursive:
                new_list: List[Any] = []
                for item in value:
                    if isinstance(item, dict):
                        new_list.append(self.redact_dict(item, sensitive_keys=keys,
                                                          recursive=True, context=f"{context}.{key}"))
                    elif isinstance(item, str):
                        if is_sensitive_key:
                            new_list.append(_REDACTED_PLACEHOLDER)
                            local_count += 1
                        else:
                            new_list.append(self.redact(item, context="_noaudit"))
                    else:
                        new_list.append(item)
                redacted[key] = new_list
            elif isinstance(value, str):
                if is_sensitive_key:
                    redacted[key] = _REDACTED_PLACEHOLDER
                    local_count += 1
                else:
                    redacted[key] = self.redact(value, context="_noaudit")
            else:
                redacted[key] = value

        if local_count:
            self._total_redactions += local_count
            self._redactions_by_label["_key_match"] += local_count
            self._redactions_by_source["dict_key_match"] += local_count
            self._audit_log.append(RedactionAuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                rule_label=f"key_match:{local_count}",
                match_count=local_count,
                source=context,
                context="sensitive_key_replacement",
            ))

        return redacted

    def redact_batch(
        self,
        items: List[Union[str, Dict[str, Any]]],
        context: str = "batch",
    ) -> List[Union[str, Dict[str, Any]]]:
        """Redact a batch of items (strings or dicts).

        Args:
            items: A list of strings or dictionaries to redact.
            context: Audit-log context string.

        Returns:
            A new list with each item redacted.
        """
        results: List[Union[str, Dict[str, Any]]] = []
        for idx, item in enumerate(items):
            if isinstance(item, str):
                results.append(self.redact(item, context=f"{context}[{idx}]"))
            elif isinstance(item, dict):
                results.append(self.redact_dict(item, context=f"{context}[{idx}]"))
            else:
                results.append(item)
        return results

    # ------------------------------------------------------------------
    # PII analysis (detect without redacting)
    # ------------------------------------------------------------------

    def analyze_for_pii(self, text: str) -> Dict[str, Any]:
        """Scan *text* for potential PII without modifying it.

        Returns a structured report containing:
        - has_pii: bool
        - findings: list of {type, count, sample, pattern}
        - total_pii_instances: int
        - risk_level: 'low' / 'medium' / 'high' / 'critical'
        - risk_score: float (0-100)
        - timestamp: ISO-8601
        """
        findings: List[Dict[str, Any]] = []
        total = 0

        for rule in self._rules:
            if not rule.enabled:
                continue
            matches = list(rule.pattern.finditer(text))
            if not matches:
                continue

            samples = set()
            filtered = matches
            if self._enable_luhn_filter and rule.label == "credit_card":
                filtered = []
                for m in matches:
                    cleaned = re.sub(r"[-\s]", "", m.group())
                    if cleaned.isdigit() and len(cleaned) in (15, 16) and _luhn_check(cleaned):
                        filtered.append(m)
                        samples.add(cleaned)

            if not filtered:
                continue

            count = len(filtered)
            total += count
            if not samples:
                samples = {m.group() for m in filtered[:3]}

            findings.append({
                "type": rule.description,
                "label": rule.label,
                "count": count,
                "sample": list(samples)[:3],
                "pattern": rule.pattern.pattern,
            })

        risk_score = min(100.0, total * 5.0 + len(findings) * 10.0)

        if risk_score >= 70:
            risk_level = "critical"
        elif risk_score >= 40:
            risk_level = "high"
        elif risk_score >= 15:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "has_pii": total > 0,
            "findings": findings,
            "total_pii_instances": total,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def analyze_dict_for_pii(
        self,
        data: Dict[str, Any],
        sensitive_keys: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Analyse a dictionary for PII presence without redacting.

        Combines key-based heuristics with value-based regex scanning.
        """
        keys = sensitive_keys or _COMMON_SENSITIVE_KEYS
        findings: List[Dict[str, Any]] = []
        total = 0
        sensitive_key_hits: List[str] = []

        flat = _flatten_dict(data)
        for flat_key, value in flat.items():
            key_lower = flat_key.lower().replace(" ", "_")
            if any(s in key_lower for s in keys):
                sensitive_key_hits.append(flat_key)
                total += 1

            if isinstance(value, str):
                analysis = self.analyze_for_pii(value)
                total += analysis["total_pii_instances"]
                findings.extend(analysis["findings"])

        risk_score = min(100.0, total * 3.0 + len(sensitive_key_hits) * 8.0)
        if risk_score >= 70:
            risk_level = "critical"
        elif risk_score >= 40:
            risk_level = "high"
        elif risk_score >= 15:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "has_pii": total > 0,
            "sensitive_key_hits": sensitive_key_hits,
            "findings": findings,
            "total_pii_instances": total,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Audit & statistics
    # ------------------------------------------------------------------

    def clear_audit_log(self) -> int:
        """Remove all audit entries.

        Returns:
            Number of entries cleared.
        """
        n = len(self._audit_log)
        self._audit_log.clear()
        logger.info("Audit log cleared (%d entries)", n)
        return n

    def get_audit_log(
        self,
        since: Optional[str] = None,
        label_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return audit entries, optionally filtered.

        Args:
            since: ISO-format timestamp; only entries after this time.
            label_filter: Only include entries whose rule_label contains this.
            limit: Maximum number of entries to return (most recent first).

        Returns:
            List of audit entry dicts.
        """
        entries = list(self._audit_log)
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if label_filter:
            entries = [e for e in entries if label_filter in e.rule_label]
        entries.reverse()
        return [asdict(e) for e in entries[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        """Return a snapshot of current redaction statistics.

        Returns:
            Dictionary with counts, rule details, and audit-log size.
        """
        enabled = [r for r in self._rules if r.enabled]
        return {
            "total_rules": len(self._rules),
            "active_rules": len(enabled),
            "total_redactions": self._total_redactions,
            "redactions_by_label": dict(self._redactions_by_label),
            "redactions_by_source": dict(self._redactions_by_source),
            "audit_log_size": len(self._audit_log),
            "rules": [r.to_dict() for r in self._rules],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def generate_report(self) -> RedactionReport:
        """Generate a comprehensive RedactionReport object."""
        enabled = [r for r in self._rules if r.enabled]

        label_counts = dict(self._redactions_by_label)
        sorted_labels = sorted(label_counts.items(), key=lambda x: -x[1])

        most_active = [
            {"label": lbl, "count": cnt}
            for lbl, cnt in sorted_labels[:10]
        ]

        return RedactionReport(
            total_rules=len(self._rules),
            active_rules=len(enabled),
            total_redactions_lifetime=self._total_redactions,
            redactions_by_label=label_counts,
            redactions_by_source=dict(self._redactions_by_source),
            audit_log_size=len(self._audit_log),
            most_active_rules=most_active,
            report_time=datetime.now(timezone.utc).isoformat(),
        )

    def export_report_json(self) -> str:
        """Export the current report as a JSON string (indented)."""
        report = self.generate_report()
        return json.dumps(asdict(report), indent=2, default=str)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup_default_rules(self) -> None:
        """Register the default PII patterns shipped with the library."""
        for regex, replacement, description, label in _build_default_patterns():
            self.add_rule(
                pattern=regex,
                replacement=replacement,
                description=description,
                label=label,
                enabled=True,
            )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "DataRedactor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def __repr__(self) -> str:
        return (
            f"DataRedactor(rules={len(self._rules)}, "
            f"active={sum(1 for r in self._rules if r.enabled)}, "
            f"total_redactions={self._total_redactions})"
        )
