"""Consent management module for privacy compliance.

Provides the ConsentManager class for tracking, validating, and
auditing user consent across multiple processing categories.
Supports the full consent lifecycle (granted, withdrawn, expired),
config-driven consent policies, statistics/reporting, and GDPR / CCPA
compliance primitives.
"""
import csv
import hashlib
import io
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class ConsentStatus(Enum):
    """Possible states in the consent lifecycle."""
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    PENDING = "pending"


class ConsentCategory(Enum):
    """Categories of consent that can be independently managed."""
    PROCESSING = "processing"
    MARKETING = "marketing"
    SHARING = "sharing"
    ANALYTICS = "analytics"
    COMMUNICATIONS = "communications"
    LOCATION = "location"
    COOKIES_FUNCTIONAL = "cookies_functional"
    COOKIES_ANALYTICS = "cookies_analytics"
    COOKIES_MARKETING = "cookies_marketing"
    BIOMETRIC = "biometric"
    HEALTH = "health"
    THIRD_PARTY = "third_party"


@dataclass
class ConsentRecord:
    """A single consent event stored in the audit trail.

    Attributes:
        consent_id: Unique identifier for this record.
        user_id: Identifier of the data subject.
        category: ConsentCategory value.
        status: ConsentStatus value.
        granted: True if granted, False if withdrawn/expired.
        source: Origin of the consent action (e.g. 'web_form', 'api', 'admin').
        ip_address: IP address at time of consent (optional).
        user_agent: User-agent string (optional).
        policy_version: Version identifier of the consent policy in effect.
        expiry: Optional datetime after which consent automatically expires.
        recorded_at: ISO-8601 timestamp of when this record was created.
        metadata: Free-form extras stored with the record.
    """
    consent_id: str
    user_id: str
    category: str
    status: str
    granted: bool
    source: str
    ip_address: str = ""
    user_agent: str = ""
    policy_version: str = ""
    expiry: Optional[str] = None
    recorded_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsentPolicy:
    """A consent policy that governs how consent is managed.

    Attributes:
        policy_id: Unique policy identifier.
        description: Human-readable description.
        categories: Set of category names this policy covers.
        default_duration_days: Default consent duration before expiry.
        require_explicit: If True, opt-out is not sufficient.
        version: Policy version string.
        valid_from: ISO-8601 date from which this policy is active.
    """
    policy_id: str
    description: str
    categories: Set[str]
    default_duration_days: int = 365
    require_explicit: bool = True
    version: str = "1.0"
    valid_from: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsentSummary:
    """Aggregated consent statistics for reporting."""
    total_users: int
    total_records: int
    records_by_category: Dict[str, int]
    records_by_status: Dict[str, int]
    active_consents: int
    withdrawn_consents: int
    expired_consents: int
    pending_consents: int
    consent_rate_by_category: Dict[str, float]
    users_with_multiple_categories: int
    generated_at: str


def _generate_consent_id() -> str:
    """Generate a unique consent record identifier."""
    raw = f"{uuid.uuid4().hex}-{time.time_ns()}"
    return f"cns-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_expiry(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class ConsentManager:
    """Tracks, validates, and audits user consent across categories.

    Features:
    - Record consent grants and withdrawals per user per category.
    - Automatic consent expiry based on configurable duration.
    - Audit trail with full history for every consent action.
    - Config-driven consent policies loaded from YAML/JSON.
    - Summary statistics and per-user consent profiles.
    - GDPR Art. 7 compliance helpers (demonstration of consent).
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        default_expiry_days: int = 365,
        policy_version: str = "1.0",
    ) -> None:
        """Initialise the consent manager.

        Args:
            config_path: Optional path to a YAML/JSON policy config file.
            default_expiry_days: Default consent duration when a policy
                does not specify one.
            policy_version: Global policy version stamped on new records
                when no policy-specific version is provided.
        """
        self._records: List[ConsentRecord] = []
        self._policies: Dict[str, ConsentPolicy] = {}
        self._default_expiry_days = default_expiry_days
        self._policy_version = policy_version
        self._config_path: Optional[Path] = (
            Path(config_path).resolve() if config_path else None
        )

        self._index_by_user: Dict[str, List[ConsentRecord]] = defaultdict(list)
        self._index_by_category: Dict[str, List[ConsentRecord]] = defaultdict(list)

        self._load_default_policies()

        if self._config_path and self._config_path.exists():
            self.load_policies_from_config(self._config_path)

        logger.info(
            "ConsentManager initialized (default_expiry=%dd, policies=%d)",
            default_expiry_days, len(self._policies),
        )

    # ------------------------------------------------------------------
    # Consent recording
    # ------------------------------------------------------------------

    def record_consent(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
        granted: bool = True,
        source: str = "api",
        ip_address: str = "",
        user_agent: str = "",
        policy_version: Optional[str] = None,
        expiry_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConsentRecord:
        """Record a single consent action.

        Args:
            user_id: Identifier of the data subject.
            category: The consent category (string or enum value).
            granted: True if consent was given, False if withdrawn.
            source: Origin of the action (e.g. 'web_form', 'api').
            ip_address: Optional IP address of the user.
            user_agent: Optional user agent string.
            policy_version: Override the default policy version.
            expiry_days: Override the default expiry duration.
            metadata: Free-form extras stored with the record.

        Returns:
            The newly created ConsentRecord.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        status = ConsentStatus.GRANTED if granted else ConsentStatus.WITHDRAWN

        policy_ver = policy_version or self._policy_version

        expiry: Optional[str] = None
        if granted and (expiry_days or self._default_expiry_days) > 0:
            days = expiry_days if expiry_days is not None else self._default_expiry_days
            expiry = _make_expiry(days)

        record = ConsentRecord(
            consent_id=_generate_consent_id(),
            user_id=user_id,
            category=cat,
            status=status.value,
            granted=granted,
            source=source,
            ip_address=ip_address,
            user_agent=user_agent,
            policy_version=policy_ver,
            expiry=expiry,
            recorded_at=_utc_now_str(),
            metadata=metadata or {},
        )

        self._records.append(record)
        self._index_by_user[user_id].append(record)
        self._index_by_category[cat].append(record)

        verb = "granted" if granted else "withdrawn"
        logger.info("Consent %s for user=%s category=%s source=%s",
                     verb, user_id, cat, source)
        return record

    def withdraw_consent(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
        source: str = "api",
        ip_address: str = "",
        user_agent: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConsentRecord:
        """Convenience method to withdraw (revoke) consent for a user/category.

        Shortcut for ``record_consent(…, granted=False)``.

        Returns:
            The withdrawal ConsentRecord.
        """
        return self.record_consent(
            user_id=user_id,
            category=category,
            granted=False,
            source=source,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Consent checking
    # ------------------------------------------------------------------

    def check_consent(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
        check_expiry: bool = True,
    ) -> bool:
        """Check whether *user_id* currently has active consent for *category*.

        The most recent record for this user/category pair determines the
        result.  If the most recent record is a grant that has not expired,
        returns True.  Otherwise returns False.

        Args:
            user_id: Data subject identifier.
            category: Consent category to check.
            check_expiry: If True, expired grants are treated as "no consent".

        Returns:
            True if consent is currently active.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        records = self._index_by_user.get(user_id, [])
        relevant = [r for r in records if r.category == cat]
        if not relevant:
            return False

        latest = max(relevant, key=lambda r: r.recorded_at)

        if not latest.granted:
            return False

        if check_expiry and latest.expiry:
            now = _utc_now_str()
            if latest.expiry <= now:
                return False

        return True

    def has_ever_consented(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
    ) -> bool:
        """Check if a user has ever granted consent for a category.

        Unlike *check_consent*, this ignores withdrawals and expiry.
        Useful for audit / reporting purposes.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        records = self._index_by_user.get(user_id, [])
        return any(r.category == cat and r.granted for r in records)

    def get_consent_status(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
    ) -> Dict[str, Any]:
        """Return detailed consent status for a user/category pair.

        Returns:
            Dictionary with keys: has_consent, status, latest_record,
            granted_at, withdrawn_at, expires_at.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        records = self._index_by_user.get(user_id, [])
        relevant = [r for r in records if r.category == cat]
        if not relevant:
            return {
                "has_consent": False,
                "status": "no_records",
                "latest_record": None,
                "granted_at": None,
                "withdrawn_at": None,
                "expires_at": None,
            }

        latest = max(relevant, key=lambda r: r.recorded_at)
        has_consent = self.check_consent(user_id, cat)

        granted = [r for r in relevant if r.granted]
        withdrawn = [r for r in relevant if not r.granted]

        return {
            "has_consent": has_consent,
            "status": latest.status,
            "latest_record": asdict(latest),
            "granted_at": max(r.recorded_at for r in granted) if granted else None,
            "withdrawn_at": max(r.recorded_at for r in withdrawn) if withdrawn else None,
            "expires_at": latest.expiry,
        }

    # ------------------------------------------------------------------
    # Audit trail & history
    # ------------------------------------------------------------------

    def get_consent_history(
        self,
        user_id: str,
        category: Optional[Union[str, ConsentCategory]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return the full consent audit trail for a user.

        Args:
            user_id: Data subject identifier.
            category: Optional category filter.
            limit: Maximum number of records (most recent first).

        Returns:
            List of ConsentRecord dicts.
        """
        records = list(self._index_by_user.get(user_id, []))
        if category:
            cat = category.value if isinstance(category, ConsentCategory) else category
            records = [r for r in records if r.category == cat]
        records.sort(key=lambda r: r.recorded_at, reverse=True)
        return [asdict(r) for r in records[:limit]]

    def get_consent_proof(self, user_id: str, category: Union[str, ConsentCategory]) -> Dict[str, Any]:
        """Return a consent proof package for GDPR Art. 7 compliance.

        Includes the raw consent record, a hash chain, and metadata
        needed to demonstrate that consent was obtained.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        records = self._index_by_user.get(user_id, [])
        relevant = [r for r in records if r.category == cat and r.granted]
        if not relevant:
            return {"user_id": user_id, "category": cat, "proof": None}

        latest = max(relevant, key=lambda r: r.recorded_at)

        proof_payload = {
            "user_id": user_id,
            "category": cat,
            "consent_id": latest.consent_id,
            "granted": latest.granted,
            "source": latest.source,
            "policy_version": latest.policy_version,
            "recorded_at": latest.recorded_at,
            "expiry": latest.expiry,
            "ip_address": latest.ip_address,
            "metadata": latest.metadata,
        }

        proof_payload["proof_hash"] = hashlib.sha256(
            json.dumps(proof_payload, sort_keys=True, default=str).encode()
        ).hexdigest()

        return {"user_id": user_id, "category": cat, "proof": proof_payload}

    # ------------------------------------------------------------------
    # Expiry management
    # ------------------------------------------------------------------

    def expire_consent(
        self,
        user_id: str,
        category: Union[str, ConsentCategory],
    ) -> Optional[ConsentRecord]:
        """Manually mark the latest consent grant as expired.

        Returns the expiry record, or None if no active grant exists.
        """
        cat = category.value if isinstance(category, ConsentCategory) else category
        records = self._index_by_user.get(user_id, [])
        relevant = [r for r in records if r.category == cat and r.granted]
        if not relevant:
            return None

        latest = max(relevant, key=lambda r: r.recorded_at)
        latest.status = ConsentStatus.EXPIRED.value
        latest.granted = False

        logger.info("Consent expired for user=%s category=%s", user_id, cat)
        return latest

    def expire_all_expired(self) -> int:
        """Scan all records and mark grants whose expiry has passed.

        Returns:
            Number of records expired.
        """
        now = _utc_now_str()
        count = 0
        for record in self._records:
            if record.granted and record.expiry and record.expiry <= now:
                record.status = ConsentStatus.EXPIRED.value
                record.granted = False
                count += 1
        if count:
            logger.info("Auto-expired %d consent records", count)
        return count

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def record_consent_batch(
        self,
        entries: List[Dict[str, Any]],
    ) -> List[ConsentRecord]:
        """Record multiple consent actions in one call.

        Each entry in *entries* should be a dict with the same keys
        as :meth:`record_consent` (at minimum 'user_id' and 'category').

        Returns:
            List of created ConsentRecord objects.
        """
        results: List[ConsentRecord] = []
        for entry in entries:
            rec = self.record_consent(
                user_id=entry["user_id"],
                category=entry["category"],
                granted=entry.get("granted", True),
                source=entry.get("source", "batch"),
                ip_address=entry.get("ip_address", ""),
                user_agent=entry.get("user_agent", ""),
                policy_version=entry.get("policy_version"),
                expiry_days=entry.get("expiry_days"),
                metadata=entry.get("metadata"),
            )
            results.append(rec)
        return results

    # ------------------------------------------------------------------
    # Summary & reporting
    # ------------------------------------------------------------------

    def get_consent_summary(self) -> ConsentSummary:
        """Generate aggregate consent statistics.

        Returns:
            A ConsentSummary dataclass instance.
        """
        self.expire_all_expired()

        unique_users = set(r.user_id for r in self._records)
        records_by_category: Dict[str, int] = defaultdict(int)
        records_by_status: Dict[str, int] = defaultdict(int)
        active = withdrawn = expired = pending = 0

        for r in self._records:
            records_by_category[r.category] += 1
            records_by_status[r.status] += 1
            if r.status == ConsentStatus.GRANTED.value:
                active += 1
            elif r.status == ConsentStatus.WITHDRAWN.value:
                withdrawn += 1
            elif r.status == ConsentStatus.EXPIRED.value:
                expired += 1
            elif r.status == ConsentStatus.PENDING.value:
                pending += 1

        consent_rate_by_category: Dict[str, float] = {}
        for cat in records_by_category:
            total_for_cat = len(self._index_by_category.get(cat, []))
            granted_for_cat = sum(
                1 for r in self._index_by_category.get(cat, []) if r.granted
            )
            consent_rate_by_category[cat] = (
                (granted_for_cat / total_for_cat * 100.0) if total_for_cat > 0 else 0.0
            )

        users_with_multiple = sum(
            1 for uid in unique_users
            if len(set(r.category for r in self._index_by_user.get(uid, []) if r.granted)) > 1
        )

        return ConsentSummary(
            total_users=len(unique_users),
            total_records=len(self._records),
            records_by_category=dict(records_by_category),
            records_by_status=dict(records_by_status),
            active_consents=active,
            withdrawn_consents=withdrawn,
            expired_consents=expired,
            pending_consents=pending,
            consent_rate_by_category=consent_rate_by_category,
            users_with_multiple_categories=users_with_multiple,
            generated_at=_utc_now_str(),
        )

    def get_user_consent_profile(self, user_id: str) -> Dict[str, Any]:
        """Return a full consent profile for a single user.

        Includes current consent status for every known category,
        plus audit history summary.
        """
        categories = set(r.category for r in self._index_by_user.get(user_id, []))
        if not categories:
            return {"user_id": user_id, "has_any_consent": False, "categories": {}}

        profile: Dict[str, Any] = {}
        all_categories = list(ConsentCategory) if not self._policies else \
            set(ConsentCategory).union(self._policies.keys())

        for cat in categories:
            status = self.get_consent_status(user_id, cat)
            profile[cat] = {
                "has_consent": status["has_consent"],
                "status": status["status"],
                "granted_at": status["granted_at"],
                "expires_at": status["expires_at"],
            }

        return {
            "user_id": user_id,
            "has_any_consent": any(v["has_consent"] for v in profile.values()),
            "categories": profile,
        }

    # ------------------------------------------------------------------
    # Policy management
    # ------------------------------------------------------------------

    def add_policy(self, policy: ConsentPolicy) -> None:
        """Register a consent policy.

        If a policy with the same policy_id already exists it is replaced.
        """
        self._policies[policy.policy_id] = policy
        logger.info("Added policy: %s (version=%s, categories=%s)",
                     policy.policy_id, policy.version, policy.categories)

    def remove_policy(self, policy_id: str) -> bool:
        """Remove a consent policy by ID.

        Returns True on success, False if the policy was not found.
        """
        if policy_id in self._policies:
            del self._policies[policy_id]
            logger.info("Removed policy: %s", policy_id)
            return True
        return False

    def get_policy(self, policy_id: str) -> Optional[ConsentPolicy]:
        return self._policies.get(policy_id)

    def get_all_policies(self) -> List[ConsentPolicy]:
        return list(self._policies.values())

    def load_policies_from_config(self, path: Union[str, Path]) -> int:
        """Load consent policies from a YAML or JSON config file.

        Expected YAML format:
        ```yaml
        policies:
          - policy_id: marketing_v2
            description: Marketing consent policy
            categories: [marketing, communications]
            default_duration_days: 180
            require_explicit: true
            version: "2.0"
        ```
        Returns the number of policies loaded.
        """
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            logger.error("Policy config not found: %s", path_obj)
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
            logger.error("Failed to parse policy config: %s", exc)
            return 0

        if not isinstance(data, dict) or "policies" not in data:
            logger.warning("No 'policies' key in %s", path_obj)
            return 0

        count = 0
        for entry in data["policies"]:
            try:
                policy = ConsentPolicy(
                    policy_id=entry["policy_id"],
                    description=entry.get("description", ""),
                    categories=set(entry.get("categories", [])),
                    default_duration_days=entry.get("default_duration_days", self._default_expiry_days),
                    require_explicit=entry.get("require_explicit", True),
                    version=entry.get("version", "1.0"),
                    valid_from=entry.get("valid_from", ""),
                    metadata=entry.get("metadata", {}),
                )
                self.add_policy(policy)
                count += 1
            except KeyError as exc:
                logger.warning("Skipping policy entry missing key: %s", exc)
        logger.info("Loaded %d policies from %s", count, path_obj)
        return count

    # ------------------------------------------------------------------
    # Data export & import
    # ------------------------------------------------------------------

    def export_records_csv(self) -> str:
        """Export all consent records as a CSV string.

        Returns:
            CSV-formatted string with a header row.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "consent_id", "user_id", "category", "status", "granted",
            "source", "ip_address", "user_agent", "policy_version",
            "expiry", "recorded_at",
        ])
        for r in self._records:
            writer.writerow([
                r.consent_id, r.user_id, r.category, r.status, r.granted,
                r.source, r.ip_address, r.user_agent, r.policy_version,
                r.expiry or "", r.recorded_at,
            ])
        return output.getvalue()

    def export_records_json(self, indent: int = 2) -> str:
        """Export all consent records as a JSON string.

        Returns:
            JSON-formatted string.
        """
        return json.dumps(
            {"records": [asdict(r) for r in self._records]},
            indent=indent,
            default=str,
        )

    def import_records_json(self, json_str: str) -> int:
        """Import consent records from a JSON string.

        Returns the number of records imported.
        """
        data = json.loads(json_str)
        entries = data if isinstance(data, list) else data.get("records", [])
        count = 0
        for entry in entries:
            record = ConsentRecord(
                consent_id=entry.get("consent_id", _generate_consent_id()),
                user_id=entry["user_id"],
                category=entry["category"],
                status=entry.get("status", ConsentStatus.GRANTED.value),
                granted=entry.get("granted", True),
                source=entry.get("source", "import"),
                ip_address=entry.get("ip_address", ""),
                user_agent=entry.get("user_agent", ""),
                policy_version=entry.get("policy_version", ""),
                expiry=entry.get("expiry"),
                recorded_at=entry.get("recorded_at", _utc_now_str()),
                metadata=entry.get("metadata", {}),
            )
            self._records.append(record)
            self._index_by_user[record.user_id].append(record)
            self._index_by_category[record.category].append(record)
            count += 1
        logger.info("Imported %d consent records", count)
        return count

    # ------------------------------------------------------------------
    # GDPR / CCPA compliance helpers
    # ------------------------------------------------------------------

    def gdpr_compliance_report(self) -> Dict[str, Any]:
        """Generate a GDPR compliance overview.

        Returns structured data suitable for internal compliance dashboards.
        """
        self.expire_all_expired()
        summary = self.get_consent_summary()

        users_without_consent: List[str] = []
        all_users = set(r.user_id for r in self._records)
        for uid in all_users:
            has_any = any(
                self.check_consent(uid, cat)
                for cat in set(r.category for r in self._records if r.user_id == uid)
            )
            if not has_any:
                users_without_consent.append(uid)

        return {
            "framework": "GDPR",
            "report_generated_at": _utc_now_str(),
            "total_data_subjects": summary.total_users,
            "total_consent_records": summary.total_records,
            "active_consents": summary.active_consents,
            "withdrawn_consents": summary.withdrawn_consents,
            "expired_consents": summary.expired_consents,
            "consent_rate_by_category": summary.consent_rate_by_category,
            "users_without_active_consent_count": len(users_without_consent),
            "users_without_active_consent_sample": users_without_consent[:20],
            "policies_active": list(self._policies.keys()),
        }

    def ccpa_compliance_report(self) -> Dict[str, Any]:
        """Generate a CCPA compliance overview.

        CCPA focuses on the right to opt out of sale/sharing and
        the right to delete.  This report shows opt-out rates.
        """
        self.expire_all_expired()
        summary = self.get_consent_summary()

        sharing_consents = self._index_by_category.get("sharing", [])
        opted_out_of_sharing = sum(
            1 for r in sharing_consents if not r.granted
        )
        total_sharing_records = len(sharing_consents)

        return {
            "framework": "CCPA",
            "report_generated_at": _utc_now_str(),
            "total_data_subjects": summary.total_users,
            "sharing_category_records": total_sharing_records,
            "opted_out_of_sharing": opted_out_of_sharing,
            "opt_out_rate_pct": (
                (opted_out_of_sharing / total_sharing_records * 100.0)
                if total_sharing_records > 0 else 0.0
            ),
            "marketing_opt_out_count": sum(
                1 for r in self._index_by_category.get("marketing", []) if not r.granted
            ),
            "policies_active": list(self._policies.keys()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_default_policies(self) -> None:
        """Register a sensible set of built-in consent policies."""
        defaults = [
            ConsentPolicy(
                policy_id="processing_default",
                description="Core data processing required for service delivery",
                categories={"processing"},
                default_duration_days=365,
                require_explicit=True,
                version="1.0",
            ),
            ConsentPolicy(
                policy_id="marketing_default",
                description="Marketing and promotional communications",
                categories={"marketing", "communications"},
                default_duration_days=180,
                require_explicit=True,
                version="1.0",
            ),
            ConsentPolicy(
                policy_id="sharing_default",
                description="Data sharing with third-party partners",
                categories={"sharing", "third_party"},
                default_duration_days=90,
                require_explicit=True,
                version="1.0",
            ),
            ConsentPolicy(
                policy_id="analytics_default",
                description="Usage analytics and product improvement",
                categories={"analytics"},
                default_duration_days=365,
                require_explicit=False,
                version="1.0",
            ),
        ]
        for p in defaults:
            self.add_policy(p)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear_records(self) -> int:
        """Remove all consent records.

        Returns the number of records removed.
        """
        n = len(self._records)
        self._records.clear()
        self._index_by_user.clear()
        self._index_by_category.clear()
        logger.warning("All consent records cleared (%d removed)", n)
        return n

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return (
            f"ConsentManager(records={len(self._records)}, "
            f"users={len(self._index_by_user)}, "
            f"policies={len(self._policies)})"
        )
