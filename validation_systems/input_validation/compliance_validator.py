"""Compliance validation for legal, regulatory, and policy requirements."""

import logging
import re
import time
import hashlib
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set, Pattern, Callable

logger = logging.getLogger(__name__)


class RegulationType(str, Enum):
    COPYRIGHT = "copyright"
    GDPR = "gdpr"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    COPPA = "coppa"
    SOC2 = "soc2"
    CCPA = "ccpa"
    LGPD = "lgpd"
    PIPEDA = "pipeda"
    ADA = "ada"
    COPPA_CERT = "coppa_cert"
    GDPR_COOKIE = "gdpr_cookie"
    DATA_RETENTION = "data_retention"
    DATA_MINIMIZATION = "data_minimization"


class ComplianceSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceAction(str, Enum):
    NONE = "none"
    WARN = "warn"
    BLOCK = "block"
    REDACT = "redact"
    ESCALATE = "escalate"
    LOG_ONLY = "log_only"
    FLAG_FOR_REVIEW = "flag_for_review"


class RegulationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    MAINTENANCE = "maintenance"


class PIICategory(str, Enum):
    SSN = "ssn"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    DOB = "date_of_birth"
    IP_ADDRESS = "ip_address"
    BIOMETRIC = "biometric"
    MEDICAL_RECORD = "medical_record"
    HEALTH_DATA = "health_data"
    FINANCIAL_INFO = "financial_info"
    TAX_ID = "tax_id"


class PHICategory(str, Enum):
    NAME = "patient_name"
    GEOGRAPHIC = "geographic_info"
    DATES = "dates"
    PHONE = "phone_numbers"
    FAX = "fax_numbers"
    EMAIL = "email_addresses"
    SSN = "social_security"
    MEDICAL_RECORD = "medical_record_numbers"
    HEALTH_PLAN = "health_plan_numbers"
    ACCOUNT_NUMBERS = "account_numbers"
    CERTIFICATE = "certificate_license_numbers"
    VEHICLE = "vehicle_identifiers"
    DEVICE = "device_identifiers"
    URL = "web_urls"
    IP = "ip_addresses"
    BIOMETRIC = "biometric_ids"
    FACE = "face_images"
    ANY_OTHER = "any_other_unique_id"


@dataclass
class ComplianceIssue:
    regulation: str
    issue_type: str
    severity: str
    message: str
    recommendation: str
    category: Optional[str] = None
    matched_text: Optional[str] = None
    position_start: int = 0
    position_end: int = 0
    confidence: float = 1.0
    action: str = "warn"
    code: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regulation": self.regulation,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "recommendation": self.recommendation,
            "category": self.category,
            "matched_text": self.matched_text,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "confidence": self.confidence,
            "action": self.action,
            "code": self.code,
            "timestamp": self.timestamp,
        }


@dataclass
class ComplianceConfig:
    copyright_max_quote_length: int = 100
    copyright_require_attribution: bool = True
    gdpr_require_consent: bool = True
    gdpr_allow_deletion: bool = True
    gdpr_data_portability: bool = True
    hipaa_protect_phi: bool = True
    hipaa_require_authorization: bool = True
    hipaa_breach_notification_days: int = 60
    pci_require_encryption: bool = True
    pci_max_retention_days: int = 365
    pci_require_tokenization: bool = False
    coppa_require_consent: bool = True
    coppa_min_age: int = 13
    coppa_privacy_notice_required: bool = True
    soc2_security_monitoring: bool = True
    soc2_availability_monitoring: bool = True
    soc2_confidentiality: bool = True
    soc2_processing_integrity: bool = True
    ccpa_opt_out_required: bool = True
    ccpa_data_disclosure_required: bool = True
    data_retention_days: int = 90
    max_pii_severity_score: float = 10.0
    strict_mode: bool = False
    auto_remediate: bool = False
    log_all_checks: bool = True


class ComplianceValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = ComplianceConfig()
        self._regulation_status: Dict[str, RegulationStatus] = {
            reg.value: RegulationStatus.ACTIVE for reg in RegulationType
        }
        self._custom_rules: Dict[str, Callable] = {}
        self._pattern_cache: Dict[str, Pattern] = {}
        self._stats: Dict[str, Counter] = defaultdict(Counter)
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_size: int = 1000
        self._exempt_domains: Set[str] = set()
        self._exempt_ips: Set[str] = set()
        self._pii_patterns: Dict[PIICategory, Pattern] = {}
        self._phi_patterns: Dict[PHICategory, Pattern] = {}
        self._severity_scores: Dict[str, float] = {
            "low": 1.0,
            "medium": 2.0,
            "high": 3.0,
            "critical": 5.0,
        }
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._init_patterns()

        if config:
            self._apply_config(config)

        enabled = sum(
            1 for s in self._regulation_status.values()
            if s == RegulationStatus.ACTIVE
        )
        logger.info(
            f"ComplianceValidator initialized with {enabled} active regulations"
        )

    def _init_patterns(self) -> None:
        self._pii_patterns[PIICategory.SSN] = re.compile(
            r"\b\d{3}[-]\d{2}[-]\d{4}\b"
        )
        self._pii_patterns[PIICategory.EMAIL] = re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        )
        self._pii_patterns[PIICategory.PHONE] = re.compile(
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        )
        self._pii_patterns[PIICategory.CREDIT_CARD] = re.compile(
            r"\b(?:\d{4}[-.\s]?){3}\d{4}\b"
        )
        self._pii_patterns[PIICategory.IP_ADDRESS] = re.compile(
            r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        )
        self._pii_patterns[PIICategory.DOB] = re.compile(
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
        )
        self._pii_patterns[PIICategory.PASSPORT] = re.compile(
            r"\b[A-Z]{1,2}\d{6,9}\b"
        )
        self._pii_patterns[PIICategory.BANK_ACCOUNT] = re.compile(
            r"\b\d{8,17}\b"
        )

        self._phi_patterns[PHICategory.SSN] = self._pii_patterns[PIICategory.SSN]
        self._phi_patterns[PHICategory.EMAIL] = self._pii_patterns[PIICategory.EMAIL]
        self._phi_patterns[PHICategory.PHONE] = self._pii_patterns[PIICategory.PHONE]
        self._phi_patterns[PHICategory.IP] = self._pii_patterns[PIICategory.IP_ADDRESS]
        self._phi_patterns[PHICategory.MEDICAL_RECORD] = re.compile(
            r"\b(?:MRN|medical\s*record\s*(?:number|#|id))\s*[:=]?\s*\d{4,10}\b",
            re.IGNORECASE,
        )
        self._phi_patterns[PHICategory.HEALTH_PLAN] = re.compile(
            r"\b(?:health\s*plan|insurance\s*(?:id|number|policy))\s*[:=]?\s*[A-Z]\d{5,15}\b",
            re.IGNORECASE,
        )
        self._phi_patterns[PHICategory.VEHICLE] = re.compile(
            r"\b[A-HJ-NPR-Z0-9]{17}\b"
        )

    def _apply_config(self, config: Dict[str, Any]) -> None:
        for key, value in config.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        if "regulation_status" in config:
            for reg, status in config["regulation_status"].items():
                try:
                    rt = RegulationType(reg) if not isinstance(reg, RegulationType) else reg
                    s = RegulationStatus(status) if not isinstance(status, RegulationStatus) else status
                    self.set_regulation_status(rt, s)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid regulation/status: {reg}/{status}")

    def _compile(self, pattern: str) -> Pattern:
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)
        return self._pattern_cache[pattern]

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Callback '{event}' failed: {e}")

    def _log_check(self, regulation: str, issue_count: int, elapsed_ms: float) -> None:
        self._stats[regulation]["total_checks"] += 1
        self._stats[regulation]["total_issues"] += issue_count
        self._stats[regulation]["total_time_ms"] += elapsed_ms
        if issue_count > 0:
            self._stats[regulation]["failed_checks"] += 1

    def _log_audit(self, issue: ComplianceIssue) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "regulation": issue.regulation,
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "message": issue.message,
            "action": issue.action,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_size:
            self._audit_log = self._audit_log[-self._max_audit_size:]

    def register_callback(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> bool:
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
            return True
        return False

    def set_regulation_status(
        self, regulation: RegulationType, status: RegulationStatus
    ) -> None:
        self._regulation_status[regulation.value] = status
        logger.info(f"Regulation '{regulation.value}' set to '{status.value}'")

    def get_regulation_status(self, regulation: RegulationType) -> RegulationStatus:
        return self._regulation_status.get(regulation.value, RegulationStatus.INACTIVE)

    def is_regulation_active(self, regulation: RegulationType) -> bool:
        return self._regulation_status.get(regulation.value) == RegulationStatus.ACTIVE

    def enable_regulation(self, regulation: RegulationType) -> None:
        self._regulation_status[regulation.value] = RegulationStatus.ACTIVE

    def disable_regulation(self, regulation: RegulationType) -> None:
        self._regulation_status[regulation.value] = RegulationStatus.INACTIVE

    def get_active_regulations(self) -> List[str]:
        return [
            reg for reg, status in self._regulation_status.items()
            if status == RegulationStatus.ACTIVE
        ]

    def register_custom_rule(
        self, name: str, validator_func: Callable
    ) -> None:
        self._custom_rules[name] = validator_func
        logger.info(f"Registered custom compliance rule: {name}")

    def unregister_custom_rule(self, name: str) -> bool:
        if name in self._custom_rules:
            del self._custom_rules[name]
            return True
        return False

    def add_exempt_domain(self, domain: str) -> None:
        self._exempt_domains.add(domain.lower())

    def remove_exempt_domain(self, domain: str) -> bool:
        if domain.lower() in self._exempt_domains:
            self._exempt_domains.discard(domain.lower())
            return True
        return False

    def add_exempt_ip(self, ip: str) -> None:
        self._exempt_ips.add(ip)

    def remove_exempt_ip(self, ip: str) -> bool:
        if ip in self._exempt_ips:
            self._exempt_ips.discard(ip)
            return True
        return False

    def validate(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[ComplianceIssue]]:
        start_time = time.perf_counter()
        metadata = metadata or {}
        issues: List[ComplianceIssue] = []

        if not content:
            return True, issues

        regs_to_check = regulations or self.get_active_regulations()
        if not regs_to_check:
            return True, issues

        self._trigger_callbacks("before_validate", content, regulations, metadata)

        for regulation in regs_to_check:
            if not self.is_regulation_active(RegulationType(regulation)):
                continue

            reg_issues: List[ComplianceIssue] = []

            if regulation == RegulationType.COPYRIGHT.value:
                reg_issues = self._check_copyright(content, metadata)
            elif regulation == RegulationType.GDPR.value:
                reg_issues = self._check_gdpr(content, metadata)
            elif regulation == RegulationType.HIPAA.value:
                reg_issues = self._check_hipaa(content, metadata)
            elif regulation == RegulationType.PCI_DSS.value:
                reg_issues = self._check_pci_dss(content, metadata)
            elif regulation == RegulationType.COPPA.value:
                reg_issues = self._check_coppa(content, metadata)
            elif regulation == RegulationType.SOC2.value:
                reg_issues = self._check_soc2(content, metadata)
            elif regulation == RegulationType.CCPA.value:
                reg_issues = self._check_ccpa(content, metadata)
            elif regulation == RegulationType.LGPD.value:
                reg_issues = self._check_lgpd(content, metadata)
            elif regulation == RegulationType.PIPEDA.value:
                reg_issues = self._check_pipeda(content, metadata)
            elif regulation == RegulationType.ADA.value:
                reg_issues = self._check_ada(content, metadata)
            elif regulation == RegulationType.DATA_RETENTION.value:
                reg_issues = self._check_data_retention(content, metadata)
            elif regulation == RegulationType.DATA_MINIMIZATION.value:
                reg_issues = self._check_data_minimization(content, metadata)

            issues.extend(reg_issues)
            for iss in reg_issues:
                self._log_audit(iss)

        custom_issues = self._run_custom_rules(content, metadata)
        issues.extend(custom_issues)

        elapsed = (time.perf_counter() - start_time) * 1000
        self._log_check("all", len(issues), elapsed)

        error_issues = [
            i for i in issues if i.severity in ("high", "critical")
        ]
        is_valid = len(error_issues) == 0

        self._trigger_callbacks(
            "after_validate", content, regulations, metadata, issues, is_valid
        )

        if not is_valid:
            logger.warning(
                f"Compliance validation failed with {len(issues)} "
                f"issues ({len(error_issues)} high/critical)"
            )

        return is_valid, issues

    def validate_with_score(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        is_valid, issues = self.validate(content, regulations, metadata)
        total_score = sum(
            self._severity_scores.get(i.severity, 1.0) for i in issues
        )
        by_regulation: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for i in issues:
            by_regulation[i.regulation].append(i.to_dict())

        return {
            "is_valid": is_valid,
            "score": total_score,
            "max_score": self._config.max_pii_severity_score,
            "issues_count": len(issues),
            "issues_by_regulation": dict(by_regulation),
            "issues": [i.to_dict() for i in issues],
        }

    def _check_copyright(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        word_count = len(content.split())

        if word_count > self._config.copyright_max_quote_length:
            issues.append(ComplianceIssue(
                regulation="copyright",
                issue_type="excessive_quotation",
                severity="medium",
                message=(
                    f"Content exceeds maximum quotation length "
                    f"({word_count} words, limit: {self._config.copyright_max_quote_length})"
                ),
                recommendation="Reduce quoted content or obtain written permission from the copyright holder",
                category="quotation",
            ))

        attribution_patterns = [
            r"(?:source|credit|attribution|reprinted\s*(with\s*)?permission|cc\s*by)",
            r"(?:copyright|\(c\)|©)",
        ]
        if self._config.copyright_require_attribution:
            has_attribution = any(
                re.search(p, content, re.IGNORECASE)
                for p in attribution_patterns
            )
            if not has_attribution and word_count > 20:
                issues.append(ComplianceIssue(
                    regulation="copyright",
                    issue_type="missing_attribution",
                    severity="low",
                    message="No attribution found for potentially copyrighted content",
                    recommendation="Add source attribution or copyright notice",
                    category="attribution",
                ))

        quote_block_pattern = re.compile(
            r"[\"\'][^\"]{50,}[\"\']", re.UNICODE
        )
        for match in quote_block_pattern.finditer(content):
            quote = match.group()
            if len(quote.split()) > 50:
                issues.append(ComplianceIssue(
                    regulation="copyright",
                    issue_type="long_quotation",
                    severity="low",
                    message=f"Long quotation detected ({len(quote.split())} words)",
                    recommendation="Consider paraphrasing or obtaining reprint permission",
                    category="quotation",
                    matched_text=quote[:80],
                    position_start=match.start(),
                    position_end=match.end(),
                ))

        return issues

    def _check_gdpr(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        found_pii: Dict[PIICategory, List[Tuple[str, int, int]]] = defaultdict(list)
        for pii_cat, pattern in self._pii_patterns.items():
            for match in pattern.finditer(content):
                found_pii[pii_cat].append((match.group(), match.start(), match.end()))

        if found_pii:
            pii_types = [cat.value for cat in found_pii]
            consent_disclosed = metadata.get("consent_disclosed", False)
            legal_basis = metadata.get("legal_basis", "")

            if not consent_disclosed and not legal_basis:
                issues.append(ComplianceIssue(
                    regulation="gdpr",
                    issue_type="pii_without_consent",
                    severity="high",
                    message=(
                        f"PII detected ({', '.join(pii_types)}) "
                        f"without evidence of consent or legal basis"
                    ),
                    recommendation=(
                        "Ensure explicit consent is obtained before processing PII, "
                        "or establish a valid legal basis under GDPR Article 6"
                    ),
                    category="consent",
                ))

            for pii_cat, matches in found_pii.items():
                for match_text, start, end in matches[:3]:
                    issues.append(ComplianceIssue(
                        regulation="gdpr",
                        issue_type="pii_detected",
                        severity="medium",
                        message=f"PII detected: {pii_cat.value}",
                        recommendation=(
                            "Redact or pseudonymize PII. Ensure data minimization "
                            "principles are followed."
                        ),
                        category="pii",
                        matched_text=match_text,
                        position_start=start,
                        position_end=end,
                        confidence=0.9,
                        action="redact",
                        code=pii_cat.value,
                    ))

        deletion_request = metadata.get("deletion_requested", False)
        if deletion_request and not self._config.gdpr_allow_deletion:
            issues.append(ComplianceIssue(
                regulation="gdpr",
                issue_type="deletion_not_supported",
                severity="critical",
                message="Data deletion request cannot be fulfilled (right to erasure)",
                recommendation="Implement the right to erasure (Article 17) by adding data deletion capability",
                category="right_to_erasure",
            ))

        data_portability_request = metadata.get("portability_requested", False)
        if data_portability_request and not self._config.gdpr_data_portability:
            issues.append(ComplianceIssue(
                regulation="gdpr",
                issue_type="portability_not_supported",
                severity="high",
                message="Data portability request cannot be fulfilled (right to data portability)",
                recommendation="Implement data portability (Article 20) to export data in machine-readable format",
                category="data_portability",
            ))

        if not metadata.get("privacy_notice_url"):
            issues.append(ComplianceIssue(
                regulation="gdpr",
                issue_type="missing_privacy_notice",
                severity="medium",
                message="No privacy notice URL provided (Articles 13-14)",
                recommendation="Provide a clear privacy notice detailing data processing purposes",
                category="transparency",
            ))

        retention_period = metadata.get("retention_period_days", 0)
        if retention_period > self._config.data_retention_days:
            issues.append(ComplianceIssue(
                regulation="gdpr",
                issue_type="excessive_retention",
                severity="medium",
                message=f"Data retention period ({retention_period}d) exceeds limit ({self._config.data_retention_days}d)",
                recommendation="Define and enforce data retention limits (Article 5(1)(e))",
                category="data_retention",
            ))

        if self._config.strict_mode:
            cookie_pattern = re.compile(r"document\.cookie|setCookie|createCookie", re.IGNORECASE)
            if cookie_pattern.search(content) and not metadata.get("cookie_consent"):
                issues.append(ComplianceIssue(
                    regulation="gdpr",
                    issue_type="cookie_without_consent",
                    severity="high",
                    message="Cookie implementation found without consent mechanism (e-Privacy Directive / GDPR)",
                    recommendation="Implement cookie consent banner with opt-in mechanism",
                    category="cookie_consent",
                ))

        return issues

    def _check_hipaa(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        found_phi: Dict[PHICategory, List[Tuple[str, int, int]]] = defaultdict(list)
        for phi_cat, pattern in self._phi_patterns.items():
            for match in pattern.finditer(content):
                found_phi[phi_cat].append((match.group(), match.start(), match.end()))

        if found_phi:
            phi_types = [cat.value for cat in found_phi]
            authorization = metadata.get("phi_authorization", False)

            if not authorization and self._config.hipaa_require_authorization:
                issues.append(ComplianceIssue(
                    regulation="hipaa",
                    issue_type="phi_without_authorization",
                    severity="critical",
                    message=(
                        f"PHI detected ({', '.join(phi_types)}) "
                        f"without valid authorization"
                    ),
                    recommendation=(
                        "Obtain valid HIPAA authorization before using/disclosing PHI "
                        "(45 CFR 164.508)"
                    ),
                    category="authorization",
                ))

            for phi_cat, matches in found_phi.items():
                for match_text, start, end in matches[:3]:
                    issues.append(ComplianceIssue(
                        regulation="hipaa",
                        issue_type="phi_detected",
                        severity="high",
                        message=f"PHI detected: {phi_cat.value}",
                        recommendation=(
                            "Ensure PHI is properly de-identified (Safe Harbor or Expert Determination). "
                            "Use minimum necessary standard (45 CFR 164.502(b))."
                        ),
                        category="phi",
                        matched_text=match_text,
                        position_start=start,
                        position_end=end,
                        confidence=0.85,
                        action="redact",
                        code=phi_cat.value,
                    ))

        breach_occurred = metadata.get("breach_occurred", False)
        if breach_occurred:
            notification_days = metadata.get("notification_delay_days", 0)
            if notification_days > self._config.hipaa_breach_notification_days:
                issues.append(ComplianceIssue(
                    regulation="hipaa",
                    issue_type="delayed_breach_notification",
                    severity="critical",
                    message=(
                        f"Breach notification delayed by {notification_days} days "
                        f"(limit: {self._config.hipaa_breach_notification_days})"
                    ),
                    recommendation=(
                        "Notify affected individuals, HHS, and media within 60 days "
                        "(45 CFR 164.404-408)"
                    ),
                    category="breach_notification",
                ))

        if not metadata.get("baa_in_place") and metadata.get("uses_third_party", False):
            issues.append(ComplianceIssue(
                regulation="hipaa",
                issue_type="missing_baa",
                severity="critical",
                message="Business Associate Agreement (BAA) required for third-party PHI processing",
                recommendation="Execute BAA with all business associates (45 CFR 164.504(e))",
                category="business_associates",
            ))

        if not metadata.get("safeguards_implemented", False) and found_phi:
            issues.append(ComplianceIssue(
                regulation="hipaa",
                issue_type="missing_safeguards",
                severity="high",
                message="PHI present without evidence of administrative, physical, or technical safeguards",
                recommendation=(
                    "Implement HIPAA Security Rule safeguards: access controls, "
                    "audit controls, integrity controls, transmission security (45 CFR 164.312)"
                ),
                category="security_safeguards",
            ))

        return issues

    def _check_pci_dss(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        card_data_patterns = {
            "primary_account_number": re.compile(
                r"\b(?:\d{4}[-.\s]?){3}\d{4}\b"
            ),
            "expiration_date": re.compile(
                r"\b(?:0[1-9]|1[0-2])[/-]\d{2,4}\b"
            ),
            "cvv": re.compile(
                r"\b\d{3,4}\b"
            ),
            "track_data": re.compile(
                r"(?:track\s*(?:1|2)\s*data|%[A-Z]\d+\^|\d+\^\d+)",
                re.IGNORECASE,
            ),
        }

        pan_matches = list(card_data_patterns["primary_account_number"].finditer(content))
        if pan_matches:
            if self._config.pci_require_encryption:
                encryption_indicators = [
                    r"encrypted|encryption|aes|tls|ssl|pci\s*encrypt",
                ]
                has_encryption = any(
                    re.search(p, content, re.IGNORECASE)
                    for p in encryption_indicators
                )
                if not has_encryption:
                    issues.append(ComplianceIssue(
                        regulation="pci_dss",
                        issue_type="card_data_without_encryption",
                        severity="critical",
                        message=f"Cardholder data ({len(pan_matches)} PANs) without encryption evidence",
                        recommendation="Encrypt cardholder data at rest and in transit using strong cryptography (Requirement 3-4)",
                        category="encryption",
                    ))

            if self._config.pci_require_tokenization:
                issues.append(ComplianceIssue(
                    regulation="pci_dss",
                    issue_type="pan_not_tokenized",
                    severity="high",
                    message="PAN detected without tokenization",
                    recommendation="Replace PAN with tokens to reduce PCI DSS scope (Requirement 3.4)",
                    category="tokenization",
                ))

            for match in pan_matches[:3]:
                issues.append(ComplianceIssue(
                    regulation="pci_dss",
                    issue_type="pan_detected",
                    severity="high",
                    message="Primary Account Number (PAN) detected",
                    recommendation=(
                        "Do not store sensitive auth data (CVV, track data, PIN). "
                        "Render PAN unreadable (Requirement 3.4). "
                        "Limit retention to business need (Requirement 3.1)."
                    ),
                    category="cardholder_data",
                    matched_text=match.group(),
                    position_start=match.start(),
                    position_end=match.end(),
                    action="redact",
                ))

            retention_days = metadata.get("retention_days", 0)
            if retention_days > self._config.pci_max_retention_days:
                issues.append(ComplianceIssue(
                    regulation="pci_dss",
                    issue_type="excessive_card_data_retention",
                    severity="high",
                    message=f"Cardholder data retention ({retention_days}d) exceeds limit ({self._config.pci_max_retention_days}d)",
                    recommendation="Define and enforce data retention policies for cardholder data (Requirement 3.1)",
                    category="data_retention",
                ))

        for match in card_data_patterns["track_data"].finditer(content):
            issues.append(ComplianceIssue(
                regulation="pci_dss",
                issue_type="track_data_detected",
                severity="critical",
                message="Magnetic stripe track data detected (never store this)",
                recommendation="Delete stored track data immediately. PAN truncation/hashing is not sufficient for track data (Requirement 3.2-3.3)",
                category="cardholder_data",
                matched_text=match.group()[:40],
                position_start=match.start(),
                position_end=match.end(),
                action="block",
            ))

        if not metadata.get("pci_scope_documented", False):
            issues.append(ComplianceIssue(
                regulation="pci_dss",
                issue_type="scope_not_documented",
                severity="medium",
                message="PCI DSS scope not documented",
                recommendation="Define and document the cardholder data environment (CDE) scope (Requirement 1)",
                category="scope",
            ))

        if not metadata.get("quarterly_scan", False):
            issues.append(ComplianceIssue(
                regulation="pci_dss",
                issue_type="missing_quarterly_scan",
                severity="medium",
                message="No evidence of quarterly ASV scan (Requirement 11.2)",
                recommendation="Schedule quarterly external vulnerability scans by Approved Scanning Vendor",
                category="scanning",
            ))

        return issues

    def _check_coppa(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        child_indicators = [
            (r"\b(?:age\s*[<>\d]|birth\s*year|how\s*old\s*are\s*you|date\s*of\s*birth)\b", "age_collection"),
            (r"\b(?:child|kid|teen|minor|under\s*13|under\s*18|student|grade|school)\b", "child_reference"),
            (r"\b(?:game|toy|cartoon|coloring|kids?\s*club|children'?s?\s*content)\b", "child_oriented"),
        ]

        for pattern_str, indicator_type in child_indicators:
            pattern = self._compile(pattern_str)
            matches = list(pattern.finditer(content))
            if matches:
                issues.append(ComplianceIssue(
                    regulation="coppa",
                    issue_type=f"{indicator_type}_detected",
                    severity="medium",
                    message=f"Child-oriented indicator detected: {indicator_type}",
                    recommendation=(
                        "COPPA applies to websites/services directed at children under 13. "
                        "Provide privacy notice, obtain verifiable parental consent "
                        "(16 CFR 312.5), and allow parental review/deletion."
                    ),
                    category="child_indicator",
                ))

        if self._config.coppa_require_consent and not metadata.get("parental_consent"):
            issues.append(ComplianceIssue(
                regulation="coppa",
                issue_type="missing_parental_consent",
                severity="high",
                message="No verifiable parental consent mechanism detected",
                recommendation=(
                    "Implement verifiable parental consent before collecting personal "
                    "information from children under 13 (16 CFR 312.5)"
                ),
                category="consent",
            ))

        if self._config.coppa_privacy_notice_required and not metadata.get("privacy_notice_url"):
            issues.append(ComplianceIssue(
                regulation="coppa",
                issue_type="missing_privacy_notice",
                severity="high",
                message="No children's privacy notice detected",
                recommendation=(
                    "Post a clear privacy notice describing what information is collected "
                    "from children and how it is used (16 CFR 312.4)"
                ),
                category="privacy_notice",
            ))

        min_age = metadata.get("min_age_requirement", 0)
        if 0 < min_age < self._config.coppa_min_age:
            issues.append(ComplianceIssue(
                regulation="coppa",
                issue_type="age_gate_below_threshold",
                severity="high",
                message=f"Age gate sets minimum age at {min_age} (COPPA threshold: {self._config.coppa_min_age})",
                recommendation=(
                    f"If service is directed at children, set age gate to {self._config.coppa_min_age}+ "
                    f"or implement parental consent"
                ),
                category="age_gate",
            ))

        persistent_identifiers = [
            (r"cookie", "cookie_tracking"),
            (r"device\s*(id|fingerprint)", "device_fingerprint"),
            (r"ip\s*address", "ip_logging"),
            (r"analytics|tracking\s*pixel|web\s*beacon", "tracking"),
        ]
        for pattern_str, tracking_type in persistent_identifiers:
            pattern = self._compile(pattern_str)
            if pattern.search(content) and not metadata.get("parental_consent"):
                issues.append(ComplianceIssue(
                    regulation="coppa",
                    issue_type=f"{tracking_type}_without_consent",
                    severity="medium",
                    message=f"Persistent identifier ({tracking_type}) without parental consent",
                    recommendation=(
                        "Cannot use persistent trackers on child-directed services "
                        "without parental consent (16 CFR 312.2)"
                    ),
                    category="tracking",
                ))

        return issues

    def _check_soc2(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        if self._config.soc2_security_monitoring:
            security_controls = [
                r"access\s*control|firewall|authentication|authorization",
                r"encrypt|intrusion\s*detection|vulnerability\s*scan|penetration\s*test",
                r"incident\s*response|security\s*event|monitoring|alert",
            ]
            has_security = any(
                re.search(p, content, re.IGNORECASE) for p in security_controls
            )
            if not has_security:
                issues.append(ComplianceIssue(
                    regulation="soc2",
                    issue_type="missing_security_controls",
                    severity="high",
                    message="No security monitoring controls described (SOC 2 Trust Criteria)",
                    recommendation="Implement and document security controls: access management, intrusion detection, encryption (CC6 series)",
                    category="security",
                ))

        if self._config.soc2_availability_monitoring:
            availability_controls = [
                r"availability|uptime|redundancy|failover|backup|disaster\s*recovery",
                r"business\s*continuity|sla|service\s*level|monitoring|incident\s*response",
            ]
            has_availability = any(
                re.search(p, content, re.IGNORECASE) for p in availability_controls
            )
            if not has_availability:
                issues.append(ComplianceIssue(
                    regulation="soc2",
                    issue_type="missing_availability_controls",
                    severity="medium",
                    message="No availability monitoring controls described",
                    recommendation="Implement availability controls: redundancy, monitoring, incident response (CC7 series)",
                    category="availability",
                ))

        if self._config.soc2_confidentiality:
            confidentiality_controls = [
                r"confidentiality|non[- ]?disclosure|encryption\s*at\s*rest|encryption\s*in\s*transit",
                r"data\s*classification|data\s*loss\s*prevention|dlp|access\s*restriction",
            ]
            has_confidentiality = any(
                re.search(p, content, re.IGNORECASE) for p in confidentiality_controls
            )
            if not has_confidentiality:
                issues.append(ComplianceIssue(
                    regulation="soc2",
                    issue_type="missing_confidentiality_controls",
                    severity="high",
                    message="No confidentiality controls described",
                    recommendation="Implement confidentiality controls: encryption, DLP, access restrictions (CC6 series)",
                    category="confidentiality",
                ))

        if self._config.soc2_processing_integrity:
            integrity_controls = [
                r"integrity|validation|quality\s*assurance|qa|testing|monitoring",
                r"error\s*handling|data\s*validation|input\s*sanitization|audit\s*log",
            ]
            has_integrity = any(
                re.search(p, content, re.IGNORECASE) for p in integrity_controls
            )
            if not has_integrity:
                issues.append(ComplianceIssue(
                    regulation="soc2",
                    issue_type="missing_integrity_controls",
                    severity="medium",
                    message="No processing integrity controls described",
                    recommendation="Implement processing integrity controls: validation, monitoring, error handling (CC8 series)",
                    category="processing_integrity",
                ))

        if not metadata.get("soc2_audit_date"):
            issues.append(ComplianceIssue(
                regulation="soc2",
                issue_type="missing_audit_date",
                severity="low",
                message="No SOC 2 audit date provided",
                recommendation="Schedule annual SOC 2 Type II audit and maintain audit evidence",
                category="audit",
            ))

        return issues

    def _check_ccpa(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        if self._config.ccpa_opt_out_required:
            opt_out_signals = [
                r"(?:do\s*not\s*sell|opt[- ]?out|data\s*sale\s*opt[- ]?out)",
                r"(?:your\s*privacy\s*rights|ccpa|california\s*privacy)",
            ]
            has_opt_out = any(
                re.search(p, content, re.IGNORECASE) for p in opt_out_signals
            )
            if not has_opt_out:
                issues.append(ComplianceIssue(
                    regulation="ccpa",
                    issue_type="missing_opt_out",
                    severity="high",
                    message="No 'Do Not Sell My Personal Information' link or opt-out mechanism detected",
                    recommendation=(
                        "Provide a clear 'Do Not Sell My Personal Information' link on homepage "
                        "(CCPA Section 1798.120, 1798.135)"
                    ),
                    category="opt_out",
                ))

        if self._config.ccpa_data_disclosure_required and not metadata.get("privacy_notice_url"):
            issues.append(ComplianceIssue(
                regulation="ccpa",
                issue_type="missing_data_disclosure",
                severity="medium",
                message="No data collection/disclosure notice detected",
                recommendation=(
                    "Disclose categories of personal information collected, sold, "
                    "and disclosed for business purposes in the past 12 months "
                    "(CCPA Section 1798.110, 1798.115)"
                ),
                category="disclosure",
            ))

        if metadata.get("sells_data", False) and not metadata.get("minor_opt_in", True):
            issues.append(ComplianceIssue(
                regulation="ccpa",
                issue_type="minor_data_sale_without_opt_in",
                severity="critical",
                message="Selling data of minors (<16) requires opt-in consent",
                recommendation="Obtain affirmative authorization before selling personal information of minors (CCPA Section 1798.120)",
                category="minor_protection",
            ))

        return issues

    def _check_lgpd(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        found_pii: Dict[PIICategory, List[Tuple[str, int, int]]] = defaultdict(list)
        for pii_cat, pattern in self._pii_patterns.items():
            for match in pattern.finditer(content):
                found_pii[pii_cat].append((match.group(), match.start(), match.end()))

        if found_pii:
            if not metadata.get("legal_basis"):
                issues.append(ComplianceIssue(
                    regulation="lgpd",
                    issue_type="processing_without_basis",
                    severity="high",
                    message="Personal data processed without legal basis (LGPD Art. 7)",
                    recommendation="Identify and document legal basis for each processing activity (Art. 7-11)",
                    category="legal_basis",
                ))

            if not metadata.get("dpo_appointed"):
                issues.append(ComplianceIssue(
                    regulation="lgpd",
                    issue_type="missing_dpo",
                    severity="medium",
                    message="No Data Protection Officer (DPO) appointed",
                    recommendation="Appoint DPO and publish contact information (Art. 41)",
                    category="governance",
                ))

        return issues

    def _check_pipeda(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        found_pii: Dict[PIICategory, List[Tuple[str, int, int]]] = defaultdict(list)
        for pii_cat, pattern in self._pii_patterns.items():
            for match in pattern.finditer(content):
                found_pii[pii_cat].append((match.group(), match.start(), match.end()))

        if found_pii:
            if not metadata.get("consent_obtained"):
                issues.append(ComplianceIssue(
                    regulation="pipeda",
                    issue_type="missing_consent",
                    severity="high",
                    message="Personal information collected without meaningful consent (PIPEDA Principle 3)",
                    recommendation="Obtain meaningful consent for collection, use, and disclosure of personal information",
                    category="consent",
                ))

            if not metadata.get("privacy_policy_url"):
                issues.append(ComplianceIssue(
                    regulation="pipeda",
                    issue_type="missing_privacy_policy",
                    severity="medium",
                    message="No privacy policy available (PIPEDA Principle 8 - Openness)",
                    recommendation="Make privacy policy readily available describing practices and policies",
                    category="openness",
                ))

        return issues

    def _check_ada(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        img_pattern = re.compile(r"<img[^>]+>", re.IGNORECASE)
        for match in img_pattern.finditer(content):
            img_tag = match.group()
            if 'alt=' not in img_tag and 'alt =' not in img_tag:
                line = content[:match.start()].count("\n") + 1
                issues.append(ComplianceIssue(
                    regulation="ada",
                    issue_type="missing_alt_text",
                    severity="high",
                    message="Image missing alt text (WCAG 2.1 Guideline 1.1.1)",
                    recommendation="Add descriptive alt text to all images for screen reader accessibility",
                    category="accessibility",
                    matched_text=img_tag[:60],
                    position_start=match.start(),
                    position_end=match.end(),
                ))

        aria_pattern = re.compile(r"role\s*=|aria-", re.IGNORECASE)
        interactive_elements = re.findall(
            r"<(button|input|select|textarea|a)[^>]*>", content, re.IGNORECASE
        )
        if interactive_elements and not aria_pattern.search(content):
            issues.append(ComplianceIssue(
                regulation="ada",
                issue_type="missing_aria_attributes",
                severity="medium",
                message=f"Interactive elements ({len(interactive_elements)}) without ARIA attributes",
                recommendation="Add ARIA labels and roles to interactive elements for accessibility",
                category="accessibility",
            ))

        heading_pattern = re.compile(r"<h(\d)[^>]*>", re.IGNORECASE)
        if not heading_pattern.search(content):
            text_matches = re.findall(r"^\s*#{1,6}\s+", content, re.MULTILINE)
            if not text_matches:
                issues.append(ComplianceIssue(
                    regulation="ada",
                    issue_type="missing_headings",
                    severity="low",
                    message="No heading structure detected",
                    recommendation="Use proper heading hierarchy (h1-h6) to organize content for screen readers",
                    category="accessibility",
                ))

        return issues

    def _check_data_retention(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        retention_period = metadata.get("retention_period_days", 0)
        if retention_period > self._config.data_retention_days:
            issues.append(ComplianceIssue(
                regulation="data_retention",
                issue_type="excessive_retention",
                severity="medium",
                message=(
                    f"Data retention period ({retention_period}d) exceeds "
                    f"configured maximum ({self._config.data_retention_days}d)"
                ),
                recommendation="Reduce retention period or document business justification",
                category="retention_policy",
            ))

        if not metadata.get("retention_policy_exists", False):
            issues.append(ComplianceIssue(
                regulation="data_retention",
                issue_type="missing_retention_policy",
                severity="high",
                message="No data retention policy defined",
                recommendation="Create and enforce a data retention policy with schedules for deletion",
                category="retention_policy",
            ))

        if metadata.get("archived_data", False) and not metadata.get("deletion_schedule"):
            issues.append(ComplianceIssue(
                regulation="data_retention",
                issue_type="missing_deletion_schedule",
                severity="medium",
                message="Archived data has no deletion schedule",
                recommendation="Define deletion schedule for archived data and automate purging",
                category="deletion",
            ))

        return issues

    def _check_data_minimization(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []

        found_pii_categories: Set[str] = set()
        for pii_cat, pattern in self._pii_patterns.items():
            if pattern.search(content):
                found_pii_categories.add(pii_cat.value)

        if found_pii_categories:
            purpose = metadata.get("processing_purpose", "")
            if not purpose:
                issues.append(ComplianceIssue(
                    regulation="data_minimization",
                    issue_type="unnecessary_data_collection",
                    severity="medium",
                    message=f"PII ({', '.join(found_pii_categories)}) collected without documented purpose",
                    recommendation="Only collect personal data that is adequate, relevant, and limited to what is necessary",
                    category="minimization",
                ))

            if len(found_pii_categories) > 3:
                issues.append(ComplianceIssue(
                    regulation="data_minimization",
                    issue_type="excessive_data_collection",
                    severity="high",
                    message=f"Multiple PII types collected ({len(found_pii_categories)}) - potential over-collection",
                    recommendation="Review necessity of each data field and eliminate what is not essential",
                    category="minimization",
                ))

        return issues

    def _run_custom_rules(
        self, content: str, metadata: Dict[str, Any]
    ) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        for name, func in self._custom_rules.items():
            try:
                result = func(content, metadata)
                if isinstance(result, list):
                    issues.extend(result)
                elif isinstance(result, ComplianceIssue):
                    issues.append(result)
            except Exception as e:
                logger.warning(f"Custom rule '{name}' failed: {e}")
        return issues

    def update_config(self, config: Dict[str, Any]) -> None:
        self._apply_config(config)

    def get_config(self) -> Dict[str, Any]:
        return {
            "copyright_max_quote_length": self._config.copyright_max_quote_length,
            "copyright_require_attribution": self._config.copyright_require_attribution,
            "gdpr_require_consent": self._config.gdpr_require_consent,
            "gdpr_allow_deletion": self._config.gdpr_allow_deletion,
            "hipaa_protect_phi": self._config.hipaa_protect_phi,
            "hipaa_require_authorization": self._config.hipaa_require_authorization,
            "hipaa_breach_notification_days": self._config.hipaa_breach_notification_days,
            "pci_require_encryption": self._config.pci_require_encryption,
            "pci_max_retention_days": self._config.pci_max_retention_days,
            "pci_require_tokenization": self._config.pci_require_tokenization,
            "coppa_require_consent": self._config.coppa_require_consent,
            "coppa_min_age": self._config.coppa_min_age,
            "soc2_security_monitoring": self._config.soc2_security_monitoring,
            "soc2_availability_monitoring": self._config.soc2_availability_monitoring,
            "soc2_confidentiality": self._config.soc2_confidentiality,
            "soc2_processing_integrity": self._config.soc2_processing_integrity,
            "ccpa_opt_out_required": self._config.ccpa_opt_out_required,
            "data_retention_days": self._config.data_retention_days,
            "max_pii_severity_score": self._config.max_pii_severity_score,
            "strict_mode": self._config.strict_mode,
            "auto_remediate": self._config.auto_remediate,
        }

    def get_stats(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for reg, counter in self._stats.items():
            total = counter.get("total_checks", 0)
            result[reg] = {
                "total_checks": total,
                "total_issues": counter.get("total_issues", 0),
                "failed_checks": counter.get("failed_checks", 0),
                "issue_rate": (
                    round(counter["total_issues"] / total, 4) if total > 0 else 0.0
                ),
                "total_time_ms": round(counter.get("total_time_ms", 0), 2),
                "avg_time_ms": (
                    round(counter["total_time_ms"] / total, 2) if total > 0 else 0.0
                ),
            }
        return result

    def reset_stats(self) -> None:
        self._stats.clear()
        logger.info("Compliance validation stats reset")

    def get_audit_log(
        self,
        limit: int = 100,
        regulation: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        entries = list(self._audit_log)
        if regulation:
            entries = [e for e in entries if e["regulation"] == regulation]
        if severity:
            entries = [e for e in entries if e["severity"] == severity]
        return entries[-limit:]

    def clear_audit_log(self) -> None:
        self._audit_log.clear()

    def generate_report(
        self,
        regulations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        regs = regulations or [r.value for r in RegulationType]
        report: Dict[str, Any] = {
            "generated_at": datetime.utcnow().isoformat(),
            "regulations": {},
        }
        for reg in regs:
            reg_type = RegulationType(reg)
            report["regulations"][reg] = {
                "status": self.get_regulation_status(reg_type).value,
                "stats": self.get_stats().get(reg, {}),
            }
        report["overall_stats"] = self.get_stats().get("all", {})
        return report

    def export_audit_log(self, filepath: str) -> None:
        import json
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._audit_log, f, indent=2)
        logger.info(f"Audit log exported to {filepath}")

    def __repr__(self) -> str:
        active = len(self.get_active_regulations())
        return (
            f"ComplianceValidator(regulations={len(RegulationType)}, "
            f"active={active})"
        )
