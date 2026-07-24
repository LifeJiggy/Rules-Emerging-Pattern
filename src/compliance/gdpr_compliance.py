"""
GDPR compliance checker module.
Implements data protection checks, consent management, and compliance reporting
in accordance with the General Data Protection Regulation (GDPR).
"""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DataCategory(Enum):
    """Categories of personal data under GDPR."""
    BASIC = "basic"
    SENSITIVE = "sensitive"
    BIOMETRIC = "biometric"
    HEALTH = "health"
    FINANCIAL = "financial"
    CRIMINAL = "criminal"
    CHILDREN = "children"


class ConsentStatus(Enum):
    """Status of consent for data processing."""
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    PENDING = "pending"


class DataSubjectRightType(Enum):
    """Types of data subject rights under GDPR."""
    ACCESS = "access"
    RECTIFICATION = "rectification"
    ERASURE = "erasure"
    RESTRICTION = "restriction"
    PORTABILITY = "portability"
    OBJECTION = "objection"
    AUTOMATED_DECISION = "automated_decision"


class BreachSeverity(Enum):
    """Severity levels for data breaches."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProcessingBasis(Enum):
    """Lawful bases for processing under GDPR."""
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"


@dataclass
class ConsentRecord:
    """Record of user consent for data processing."""
    consent_id: str
    user_id: str
    purpose: str
    category: DataCategory
    status: ConsentStatus
    granted_at: datetime
    expires_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    consent_version: str = "1.0"
    processing_basis: ProcessingBasis = ProcessingBasis.CONSENT

    def is_valid(self) -> bool:
        if self.status != ConsentStatus.GRANTED:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def days_until_expiry(self) -> Optional[int]:
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consent_id": self.consent_id,
            "user_id": self.user_id,
            "purpose": self.purpose,
            "category": self.category.value,
            "status": self.status.value,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "consent_version": self.consent_version,
            "processing_basis": self.processing_basis.value
        }


@dataclass
class DataProcessingRecord:
    """Record of data processing activity."""
    record_id: str
    controller: str
    processor: str
    purpose: str
    data_categories: List[DataCategory]
    processing_basis: ProcessingBasis
    data_subjects: List[str]
    retention_period_days: int
    has_dpa: bool
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    cross_border_transfer: bool = False
    safeguards_in_place: bool = False
    third_country: Optional[str] = None

    def days_until_review(self) -> int:
        days_active = (datetime.utcnow() - self.created_at).days
        review_interval = 365
        return max(0, review_interval - days_active)

    def needs_review(self) -> bool:
        return self.days_until_review() <= 0

    def is_compliant(self) -> bool:
        if not self.has_dpa:
            return False
        if self.cross_border_transfer and not self.safeguards_in_place:
            return False
        return self.is_active

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "controller": self.controller,
            "processor": self.processor,
            "purpose": self.purpose,
            "data_categories": [c.value for c in self.data_categories],
            "processing_basis": self.processing_basis.value,
            "data_subjects": self.data_subjects,
            "retention_period_days": self.retention_period_days,
            "has_dpa": self.has_dpa,
            "cross_border_transfer": self.cross_border_transfer,
            "safeguards_in_place": self.safeguards_in_place,
            "third_country": self.third_country,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "needs_review": self.needs_review(),
            "is_compliant": self.is_compliant()
        }


@dataclass
class DataSubjectRequest:
    """Record of a data subject rights request."""
    request_id: str
    user_id: str
    right_type: DataSubjectRightType
    status: str
    requested_at: datetime
    completed_at: Optional[datetime] = None
    response_data: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    extended_deadline: bool = False
    rejection_reason: Optional[str] = None

    def deadline(self) -> datetime:
        base = self.requested_at + timedelta(days=30)
        if self.extended_deadline:
            base += timedelta(days=30)
        return base

    def is_overdue(self) -> bool:
        return datetime.utcnow() > self.deadline() and self.status != "completed"

    def days_remaining(self) -> int:
        remaining = (self.deadline() - datetime.utcnow()).days
        return max(0, remaining)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "right_type": self.right_type.value,
            "status": self.status,
            "requested_at": self.requested_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "deadline": self.deadline().isoformat(),
            "is_overdue": self.is_overdue(),
            "days_remaining": self.days_remaining(),
            "rejection_reason": self.rejection_reason
        }


@dataclass
class BreachNotification:
    """Record of a data breach notification."""
    breach_id: str
    detected_at: datetime
    notified_supervisory_at: Optional[datetime] = None
    notified_subjects_at: Optional[datetime] = None
    breach_type: str
    severity: BreachSeverity
    affected_data_categories: List[DataCategory]
    affected_users_count: int
    description: str
    containment_measures: str
    root_cause: str
    notified_within_72h: bool = False
    supervisory_authority: Optional[str] = None
    remediation_completed: bool = False
    remediation_notes: Optional[str] = None

    def notification_deadline(self) -> datetime:
        return self.detected_at + timedelta(hours=72)

    def is_notification_overdue(self) -> bool:
        return datetime.utcnow() > self.notification_deadline() and not self.notified_supervisory_at

    def hours_until_deadline(self) -> float:
        remaining = (self.notification_deadline() - datetime.utcnow()).total_seconds() / 3600
        return max(0.0, remaining)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "breach_id": self.breach_id,
            "detected_at": self.detected_at.isoformat(),
            "severity": self.severity.value,
            "affected_users_count": self.affected_users_count,
            "notified_within_72h": self.notified_within_72h,
            "notification_deadline": self.notification_deadline().isoformat(),
            "is_overdue": self.is_notification_overdue(),
            "hours_until_deadline": round(self.hours_until_deadline(), 1),
            "remediation_completed": self.remediation_completed
        }


@dataclass
class DPARecord:
    """Data Processing Agreement record."""
    dpa_id: str
    controller: str
    processor: str
    signed_at: datetime
    valid_until: Optional[datetime] = None
    scope: str
    data_categories: List[DataCategory]
    security_measures: List[str]
    sub_processors_allowed: bool = False
    sub_processors: List[str] = field(default_factory=list)
    breach_notification_period_hours: int = 24
    data_erasure_procedure: Optional[str] = None
    audit_rights: bool = True
    is_active: bool = True

    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        if self.valid_until and datetime.utcnow() > self.valid_until:
            return False
        return True

    def days_until_expiry(self) -> Optional[int]:
        if not self.valid_until:
            return None
        delta = self.valid_until - datetime.utcnow()
        return max(0, delta.days)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dpa_id": self.dpa_id,
            "controller": self.controller,
            "processor": self.processor,
            "signed_at": self.signed_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "scope": self.scope,
            "is_valid": self.is_valid(),
            "days_until_expiry": self.days_until_expiry(),
            "sub_processors": self.sub_processors,
            "audit_rights": self.audit_rights
        }


@dataclass
class PIIPattern:
    """Pattern for detecting personally identifiable information."""
    name: str
    pattern: str
    category: DataCategory
    risk_weight: float
    description: str

    def compile(self) -> re.Pattern:
        return re.compile(self.pattern, re.IGNORECASE)


@dataclass
class GDPRConfig:
    """Configuration for GDPR compliance checking."""
    enabled: bool = True
    consent_required: bool = True
    consent_max_age_days: int = 365
    breach_notification_hours: int = 72
    data_subject_request_days: int = 30
    data_retention_max_days: int = 730
    cross_border_transfer_allowed: bool = False
    adequate_countries: List[str] = field(default_factory=lambda: [
        "EU", "EEA", "UK", "Switzerland", "Canada", "Japan", "South Korea",
        "New Zealand", "Israel", "Argentina", "Uruguay"
    ])
    dpia_required_for: List[DataCategory] = field(default_factory=lambda: [
        DataCategory.SENSITIVE, DataCategory.BIOMETRIC, DataCategory.HEALTH,
        DataCategory.CRIMINAL, DataCategory.CHILDREN
    ])
    dpa_required: bool = True
    audit_logging_enabled: bool = True
    consent_withdrawal_must_be_easy: bool = True
    data_portability_formats: List[str] = field(default_factory=lambda: ["csv", "json", "xml"])
    processing_record_retention_days: int = 1825
    children_data_minimum_age: int = 16
    automated_decision_explanation_required: bool = True
    risk_scoring_enabled: bool = True
    notification_threshold: str = "medium"


@dataclass
class GDPRReport:
    """GDPR compliance report."""
    compliant: bool
    violations: List[str]
    recommendations: List[str]
    timestamp: datetime
    overall_score: float = 1.0
    consent_compliance: float = 1.0
    data_protection_compliance: float = 1.0
    subject_rights_compliance: float = 1.0
    breach_readiness: float = 1.0
    dpa_compliance: float = 1.0
    total_checks_passed: int = 0
    total_checks_failed: int = 0

    def get_summary(self) -> Dict[str, Any]:
        return {
            "compliant": self.compliant,
            "overall_score": round(self.overall_score, 3),
            "consent_compliance": round(self.consent_compliance, 3),
            "data_protection_compliance": round(self.data_protection_compliance, 3),
            "subject_rights_compliance": round(self.subject_rights_compliance, 3),
            "breach_readiness": round(self.breach_readiness, 3),
            "dpa_compliance": round(self.dpa_compliance, 3),
            "violations_count": len(self.violations),
            "recommendations_count": len(self.recommendations),
            "checks_passed": self.total_checks_passed,
            "checks_failed": self.total_checks_failed
        }


class GDPRComplianceChecker:
    """
    GDPR compliance checker implementing data protection checks,
    consent management, data subject rights handling, breach notification
    tracking, and DPA validation.
    """

    def __init__(self, config: Optional[GDPRConfig] = None):
        self.config = config or GDPRConfig()
        self.consent_registry: Dict[str, ConsentRecord] = {}
        self.data_processing_log: List[DataProcessingRecord] = []
        self.processing_records: List[DataProcessingRecord] = []
        self.subject_requests: List[DataSubjectRequest] = []
        self.breach_notifications: List[BreachNotification] = []
        self.dpa_records: List[DPARecord] = []
        self.pii_patterns: List[PIIPattern] = self._init_pii_patterns()
        self.check_history: List[GDPRReport] = []
        self.data_inventory: Dict[str, Dict[str, Any]] = {}
        self.ropar: List[Dict[str, Any]] = []
        self.dpia_records: List[Dict[str, Any]] = []
        logger.info("GDPRComplianceChecker initialized with config: enabled=%s", config.enabled if config else True)

    def _init_pii_patterns(self) -> List[PIIPattern]:
        return [
            PIIPattern("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", DataCategory.BASIC, 0.6, "Email address"),
            PIIPattern("phone", r"\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b", DataCategory.BASIC, 0.5, "Phone number"),
            PIIPattern("ssn", r"\b\d{3}-\d{2}-\d{4}\b", DataCategory.SENSITIVE, 0.9, "Social Security Number"),
            PIIPattern("credit_card", r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b", DataCategory.FINANCIAL, 0.9, "Credit card number"),
            PIIPattern("ip_address", r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", DataCategory.BASIC, 0.4, "IP address"),
            PIIPattern("dob", r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", DataCategory.SENSITIVE, 0.7, "Date of birth"),
            PIIPattern("bank_account", r"\b\d{8,17}\b", DataCategory.FINANCIAL, 0.8, "Bank account number"),
            PIIPattern("passport", r"\b[A-Z]\d{6,9}\b", DataCategory.SENSITIVE, 0.85, "Passport number"),
            PIIPattern("drivers_license", r"\b[A-Z]{1,3}\d{4,8}\b", DataCategory.SENSITIVE, 0.75, "Driver license number"),
            PIIPattern("address", r"\b\d{1,5}\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b", DataCategory.BASIC, 0.6, "Street address"),
            PIIPattern("national_id", r"\b\d{6,12}\b", DataCategory.SENSITIVE, 0.7, "National ID number"),
            PIIPattern("health_insurance", r"\b[A-Z]{2}\d{6,10}\b", DataCategory.HEALTH, 0.85, "Health insurance number"),
            PIIPattern("biometric", r"(?i)\b(fingerprint|facial|retina|iris|dna|voiceprint)\b", DataCategory.BIOMETRIC, 0.8, "Biometric data"),
            PIIPattern("children_data", r"(?i)\b(child|minor|under\s*18)\b", DataCategory.CHILDREN, 0.7, "Children's data"),
            PIIPattern("criminal_record", r"(?i)\b(convict|criminal|offense|felony|misdemeanor|arrest)\b", DataCategory.CRIMINAL, 0.85, "Criminal record data"),
            PIIPattern("postal_code", r"\b\d{5}(?:-\d{4})?\b", DataCategory.BASIC, 0.3, "Postal code"),
            PIIPattern("full_name", r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", DataCategory.BASIC, 0.5, "Full name"),
            PIIPattern("personal_id_eu", r"\b[A-Z]{1,2}\s?\d{6,8}[A-Z]?\b", DataCategory.SENSITIVE, 0.75, "European personal ID"),
            PIIPattern("medical_record", r"(?i)\b(patient|diagnosis|treatment|prescription|medical\s*record)\b", DataCategory.HEALTH, 0.8, "Medical record reference"),
            PIIPattern("gender", r"(?i)\b(male|female|non.binary|gender)\b", DataCategory.BASIC, 0.3, "Gender information"),
        ]

    def check_data_protection(self, content: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
        violations = []
        detected_pii = []

        for pii in self.pii_patterns:
            compiled = pii.compile()
            matches = compiled.findall(content)
            if matches:
                detected_pii.append({"pattern": pii.name, "count": len(matches), "category": pii.category.value})
                risk_level = pii.risk_weight * len(matches)
                if pii.category in self.config.dpia_required_for:
                    violations.append(f"Sensitive PII detected: {pii.name} ({pii.description}), requires DPIA")
                elif risk_level > 1.5:
                    violations.append(f"High-risk PII detected: {pii.name} ({pii.description})")

        if detected_pii and context and not context.get("has_consent", False):
            violations.append("PII detected without documented consent")

        if context and context.get("children_data", False) and not context.get("parental_consent", False):
            violation_entry = "Children's data processed without parental consent"
            if violation_entry not in violations:
                violations.append(violation_entry)

        if context and context.get("purpose"):
            purpose = context["purpose"]
            data_category_detected = set(d["category"] for d in detected_pii)
            if DataCategory.SENSITIVE in data_category_detected or DataCategory.HEALTH in data_category_detected:
                if purpose not in ["healthcare", "legal_obligation", "vital_interest"]:
                    violations.append(f"Sensitive data processing for purpose '{purpose}' may not have valid legal basis")

        return len(violations) == 0, violations

    def detect_pii_types(self, content: str) -> List[Dict[str, Any]]:
        detected = []
        for pii in self.pii_patterns:
            compiled = pii.compile()
            matches = compiled.findall(content)
            if matches:
                detected.append({
                    "name": pii.name,
                    "category": pii.category.value,
                    "risk_weight": pii.risk_weight,
                    "count": len(matches),
                    "examples": list(set(matches))[:3]
                })
        return detected

    def validate_consent(self, user_id: str, purpose: str, category: Optional[DataCategory] = None) -> Tuple[bool, Optional[ConsentRecord]]:
        consent_key = f"{user_id}:{purpose}"
        record = self.consent_registry.get(consent_key)

        if not record:
            logger.warning("No consent record found for user %s, purpose %s", user_id, purpose)
            return False, None

        if record.status != ConsentStatus.GRANTED:
            logger.warning("Consent not granted for user %s, purpose %s (status: %s)", user_id, purpose, record.status.value)
            return False, record

        if record.expires_at and datetime.utcnow() > record.expires_at:
            logger.warning("Consent expired for user %s, purpose %s (expired: %s)", user_id, purpose, record.expires_at.isoformat())
            record.status = ConsentStatus.EXPIRED
            return False, record

        if category and record.category != category:
            logger.warning("Category mismatch for user %s: expected %s, got %s", user_id, category.value, record.category.value)
            return False, record

        return True, record

    def record_consent(self, user_id: str, purpose: str, granted: bool, category: DataCategory = DataCategory.BASIC,
                       processing_basis: ProcessingBasis = ProcessingBasis.CONSENT,
                       expires_in_days: Optional[int] = None,
                       ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> ConsentRecord:
        consent_key = f"{user_id}:{purpose}"
        consent_id = str(uuid.uuid4())
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        elif self.config.consent_max_age_days:
            expires_at = datetime.utcnow() + timedelta(days=self.config.consent_max_age_days)

        record = ConsentRecord(
            consent_id=consent_id,
            user_id=user_id,
            purpose=purpose,
            category=category,
            status=ConsentStatus.GRANTED if granted else ConsentStatus.DENIED,
            granted_at=datetime.utcnow(),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            processing_basis=processing_basis
        )
        self.consent_registry[consent_key] = record
        logger.info("Consent recorded for user %s, purpose %s (granted: %s, expires: %s)", user_id, purpose, granted, expires_at)
        return record

    def withdraw_consent(self, user_id: str, purpose: str) -> bool:
        consent_key = f"{user_id}:{purpose}"
        record = self.consent_registry.get(consent_key)
        if record and record.status == ConsentStatus.GRANTED:
            record.status = ConsentStatus.WITHDRAWN
            record.withdrawn_at = datetime.utcnow()
            logger.info("Consent withdrawn for user %s, purpose %s", user_id, purpose)
            for proc in self.processing_records:
                if user_id in proc.data_subjects and proc.purpose == purpose:
                    proc.data_subjects.remove(user_id)
                    logger.info("Stopped processing for user %s, purpose %s", user_id, purpose)
            return True
        logger.warning("Cannot withdraw consent for user %s, purpose %s", user_id, purpose)
        return False

    def get_consent_history(self, user_id: str) -> List[ConsentRecord]:
        return [r for r in self.consent_registry.values() if r.user_id == user_id]

    def record_data_processing(self, controller: str, processor: str, purpose: str,
                                data_categories: List[DataCategory],
                                processing_basis: ProcessingBasis,
                                data_subjects: List[str],
                                retention_period_days: int,
                                has_dpa: bool = True,
                                cross_border_transfer: bool = False,
                                third_country: Optional[str] = None) -> DataProcessingRecord:
        record = DataProcessingRecord(
            record_id=str(uuid.uuid4()),
            controller=controller,
            processor=processor,
            purpose=purpose,
            data_categories=data_categories,
            processing_basis=processing_basis,
            data_subjects=data_subjects,
            retention_period_days=retention_period_days,
            has_dpa=has_dpa,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            cross_border_transfer=cross_border_transfer,
            third_country=third_country
        )
        if cross_border_transfer and third_country:
            if third_country not in self.config.adequate_countries:
                record.safeguards_in_place = False
                logger.warning("Cross-border transfer to non-adequate country: %s", third_country)
            else:
                record.safeguards_in_place = True

        self.processing_records.append(record)
        logger.info("Data processing recorded: controller=%s, purpose=%s", controller, purpose)
        return record

    def log_data_processing(self, user_id: str, action: str, data_type: str, purpose: str) -> None:
        entry = {
            "user_id": user_id,
            "action": action,
            "data_type": data_type,
            "purpose": purpose,
            "timestamp": datetime.utcnow().isoformat(),
            "log_id": str(uuid.uuid4())
        }
        self.data_processing_log.append(entry)
        logger.debug("Data processing logged: user=%s, action=%s", user_id, action)

    def get_processing_log(self, user_id: Optional[str] = None, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
        results = self.data_processing_log
        if user_id:
            results = [e for e in results if e["user_id"] == user_id]
        if purpose:
            results = [e for e in results if e["purpose"] == purpose]
        return results

    def check_processing_records_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.processing_records)
        compliant = 0
        for record in self.processing_records:
            if not record.is_compliant():
                issues = []
                if not record.has_dpa:
                    issues.append("missing DPA")
                if record.cross_border_transfer and not record.safeguards_in_place:
                    issues.append("cross-border transfer without safeguards")
                if record.needs_review():
                    issues.append("needs review")
                if record.retention_period_days > self.config.data_retention_max_days:
                    issues.append(f"retention period {record.retention_period_days}d exceeds max {self.config.data_retention_max_days}d")
                violations.append(f"Processing record {record.record_id}: {', '.join(issues)}")
            elif record.is_compliant():
                compliant += 1

        score = compliant / total if total > 0 else 1.0
        return len(violations) == 0, violations, score

    def handle_subject_request(self, user_id: str, right_type: DataSubjectRightType,
                                request_data: Optional[Dict[str, Any]] = None) -> DataSubjectRequest:
        request = DataSubjectRequest(
            request_id=str(uuid.uuid4()),
            user_id=user_id,
            right_type=right_type,
            status="received",
            requested_at=datetime.utcnow(),
            response_data=request_data
        )
        self.subject_requests.append(request)
        logger.info("Data subject request received: user=%s, right=%s", user_id, right_type.value)
        return request

    def fulfill_subject_request(self, request_id: str, response_data: Dict[str, Any]) -> bool:
        for req in self.subject_requests:
            if req.request_id == request_id:
                req.status = "completed"
                req.completed_at = datetime.utcnow()
                req.response_data = response_data
                logger.info("Subject request fulfilled: %s", request_id)
                return True
        logger.warning("Subject request not found: %s", request_id)
        return False

    def reject_subject_request(self, request_id: str, reason: str) -> bool:
        for req in self.subject_requests:
            if req.request_id == request_id:
                req.status = "rejected"
                req.completed_at = datetime.utcnow()
                req.rejection_reason = reason
                logger.info("Subject request rejected: %s - %s", request_id, reason)
                return True
        return False

    def get_pending_subject_requests(self) -> List[DataSubjectRequest]:
        return [r for r in self.subject_requests if r.status not in ("completed", "rejected")]

    def get_overdue_subject_requests(self) -> List[DataSubjectRequest]:
        return [r for r in self.get_pending_subject_requests() if r.is_overdue()]

    def check_subject_rights_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.subject_requests)
        timely = 0

        for req in self.subject_requests:
            if req.is_overdue():
                violations.append(f"Overdue request {req.request_id}: {req.right_type.value} for user {req.user_id}")
            elif req.status == "completed" and not req.is_overdue():
                timely += 1
            if req.status == "rejected" and not req.rejection_reason:
                violations.append(f"Rejected request {req.request_id} without reason")

        score = timely / total if total > 0 else 1.0
        return len(violations) == 0, violations, score

    def report_breach(self, breach_type: str, severity: BreachSeverity,
                       affected_categories: List[DataCategory],
                       affected_count: int, description: str,
                       containment: str, root_cause: str) -> BreachNotification:
        breach = BreachNotification(
            breach_id=str(uuid.uuid4()),
            detected_at=datetime.utcnow(),
            breach_type=breach_type,
            severity=severity,
            affected_data_categories=affected_categories,
            affected_users_count=affected_count,
            description=description,
            containment_measures=containment,
            root_cause=root_cause
        )
        self.breach_notifications.append(breach)
        logger.critical("Breach reported: type=%s, severity=%s, affected=%d", breach_type, severity.value, affected_count)

        if severity in (BreachSeverity.HIGH, BreachSeverity.CRITICAL):
            self._auto_notify_supervisory(breach)

        return breach

    def _auto_notify_supervisory(self, breach: BreachNotification) -> None:
        if datetime.utcnow() <= breach.notification_deadline():
            breach.notified_supervisory_at = datetime.utcnow()
            breach.notified_within_72h = True
            logger.info("Supervisory authority auto-notified for breach %s", breach.breach_id)
        else:
            logger.error("Breach %s notification past 72-hour deadline", breach.breach_id)

    def notify_supervisory_authority(self, breach_id: str, authority: str) -> bool:
        for breach in self.breach_notifications:
            if breach.breach_id == breach_id:
                breach.notified_supervisory_at = datetime.utcnow()
                breach.supervisory_authority = authority
                breach.notified_within_72h = breach.notified_supervisory_at <= breach.notification_deadline()
                logger.info("Supervisory authority %s notified for breach %s", authority, breach_id)
                return True
        return False

    def notify_affected_subjects(self, breach_id: str) -> bool:
        for breach in self.breach_notifications:
            if breach.breach_id == breach_id:
                breach.notified_subjects_at = datetime.utcnow()
                logger.info("Affected subjects notified for breach %s", breach_id)
                return True
        return False

    def complete_breach_remediation(self, breach_id: str, notes: str) -> bool:
        for breach in self.breach_notifications:
            if breach.breach_id == breach_id:
                breach.remediation_completed = True
                breach.remediation_notes = notes
                logger.info("Breach remediation completed: %s", breach_id)
                return True
        return False

    def check_breach_readiness(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.breach_notifications)
        compliant = 0

        for breach in self.breach_notifications:
            if breach.is_notification_overdue():
                violations.append(f"Breach {breach.breach_id} notification overdue (severity: {breach.severity.value})")
            elif breach.notified_within_72h:
                compliant += 1
            if breach.severity in (BreachSeverity.HIGH, BreachSeverity.CRITICAL) and not breach.notified_subjects_at:
                violations.append(f"High-severity breach {breach.breach_id} subjects not notified")

        score = compliant / total if total > 0 else 1.0
        self.breach_readiness = score
        return len(violations) == 0, violations, score

    def add_dpa(self, controller: str, processor: str, scope: str,
                 data_categories: List[DataCategory],
                 security_measures: List[str],
                 valid_until: Optional[datetime] = None,
                 sub_processors_allowed: bool = False) -> DPARecord:
        dpa = DPARecord(
            dpa_id=str(uuid.uuid4()),
            controller=controller,
            processor=processor,
            signed_at=datetime.utcnow(),
            valid_until=valid_until,
            scope=scope,
            data_categories=data_categories,
            security_measures=security_measures,
            sub_processors_allowed=sub_processors_allowed
        )
        self.dpa_records.append(dpa)
        logger.info("DPA added: controller=%s, processor=%s", controller, processor)
        return dpa

    def validate_dpa(self, dpa_id: str) -> Tuple[bool, List[str]]:
        violations = []
        dpa = next((d for d in self.dpa_records if d.dpa_id == dpa_id), None)
        if not dpa:
            return False, ["DPA not found"]

        if not dpa.is_valid():
            violations.append("DPA is expired or inactive")
        if not dpa.audit_rights:
            violations.append("DPA does not include audit rights")
        if dpa.sub_processors_allowed and not dpa.sub_processors:
            violations.append("DPA allows sub-processors but none are listed")
        if not dpa.data_erasure_procedure:
            violations.append("DPA missing data erasure procedure")
        if dpa.breach_notification_period_hours > 24:
            violations.append(f"Breach notification period ({dpa.breach_notification_period_hours}h) exceeds 24h standard")
        if DataCategory.SENSITIVE in dpa.data_categories and "encryption" not in str(dpa.security_measures).lower():
            violations.append("Sensitive data processing without encryption requirement")

        return len(violations) == 0, violations

    def check_dpa_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        compliant_count = 0
        for dpa in self.dpa_records:
            is_valid, dpa_violations = self.validate_dpa(dpa.dpa_id)
            if not is_valid:
                violations.extend(f"DPA {dpa.dpa_id}: {v}" for v in dpa_violations)
            else:
                compliant_count += 1

        if not self.dpa_records and self.config.dpa_required:
            violations.append("No DPAs exist but DPA is required by config")

        score = compliant_count / len(self.dpa_records) if self.dpa_records else (1.0 if not self.config.dpa_required else 0.0)
        return len(violations) == 0, violations, score

    def create_ropar_entry(self, controller: str, processing_activities: List[Dict[str, Any]]) -> Dict[str, Any]:
        entry = {
            "ropar_id": str(uuid.uuid4()),
            "controller": controller,
            "activities": processing_activities,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        self.ropar.append(entry)
        logger.info("ROPAR entry created for controller: %s", controller)
        return entry

    def create_dpia(self, project_name: str, data_categories: List[DataCategory],
                     processing_purpose: str, risk_assessment: Dict[str, Any]) -> Dict[str, Any]:
        dpia = {
            "dpia_id": str(uuid.uuid4()),
            "project_name": project_name,
            "data_categories": [c.value for c in data_categories],
            "purpose": processing_purpose,
            "risk_assessment": risk_assessment,
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
            "reviewed_at": None,
            "approved_by": None
        }
        self.dpia_records.append(dpia)
        logger.info("DPIA created for project: %s", project_name)
        return dpia

    def approve_dpia(self, dpia_id: str, approver: str) -> bool:
        for dpia in self.dpia_records:
            if dpia["dpia_id"] == dpia_id:
                dpia["status"] = "approved"
                dpia["reviewed_at"] = datetime.utcnow().isoformat()
                dpia["approved_by"] = approver
                logger.info("DPIA %s approved by %s", dpia_id, approver)
                return True
        return False

    def assess_data_protection_impact(self, content: str, purpose: str) -> Dict[str, Any]:
        detected = self.detect_pii_types(content)
        risk_score = 0.0
        high_risk_categories = []
        for item in detected:
            score = item["risk_weight"] * item["count"]
            risk_score += score
            if item["category"] in {c.value for c in self.config.dpia_required_for}:
                high_risk_categories.append(item["name"])

        needs_dpia = len(high_risk_categories) > 0 or risk_score > 5.0

        return {
            "purpose": purpose,
            "risk_score": round(risk_score, 2),
            "risk_level": "high" if risk_score > 10 else "medium" if risk_score > 5 else "low",
            "pii_detected": detected,
            "high_risk_categories": high_risk_categories,
            "dpia_required": needs_dpia,
            "recommendation": "DPIA required" if needs_dpia else "Standard processing, no DPIA required"
        }

    def assess_cross_border_transfer(self, target_country: str, data_categories: List[DataCategory]) -> Dict[str, Any]:
        is_adequate = target_country in self.config.adequate_countries
        safeguards_needed = []
        if not is_adequate:
            if DataCategory.SENSITIVE in data_categories or DataCategory.HEALTH in data_categories:
                safeguards_needed.append("SCCs (Standard Contractual Clauses)")
            if DataCategory.CHILDREN in data_categories:
                safeguards_needed.append("Parental consent verification")
            if DataCategory.CRIMINAL in data_categories:
                safeguards_needed.append("Specific legal authorization")
            safeguards_needed.append("Data transfer impact assessment")

        return {
            "target_country": target_country,
            "is_adequate": is_adequate,
            "data_categories": [c.value for c in data_categories],
            "safeguards_required": safeguards_needed,
            "transfer_allowed": is_adequate or len(safeguards_needed) > 0,
            "recommendation": "Transfer allowed" if is_adequate else f"SCCs and safeguards required: {', '.join(safeguards_needed)}"
        }

    def validate_retention_periods(self) -> List[str]:
        violations = []
        for record in self.processing_records:
            if record.retention_period_days > self.config.data_retention_max_days:
                violations.append(
                    f"Record {record.record_id} ({record.purpose}): retention {record.retention_period_days}d "
                    f"exceeds max {self.config.data_retention_max_days}d"
                )
            if record.retention_period_days <= 0:
                violations.append(f"Record {record.record_id}: invalid retention period {record.retention_period_days}")
        return violations

    def check_data_minimization(self, content: str, required_fields: List[str]) -> Tuple[bool, List[str]]:
        violations = []
        detected = self.detect_pii_types(content)
        detected_names = {d["name"] for d in detected}

        extra_fields = detected_names - set(required_fields)
        if extra_fields:
            violations.append(f"Data minimization violation: extra fields collected: {', '.join(sorted(extra_fields))}")

        return len(violations) == 0, violations

    def generate_compliance_report(self, detailed: bool = False) -> GDPRReport:
        violations = []
        recommendations = []

        consent_ok, consent_violations, consent_score = self._check_consent_compliance()
        violations.extend(consent_violations)

        dp_ok, dp_violations, dp_score = self.check_data_protection("", {})
        violations.extend(dp_violations)

        sr_ok, sr_violations, sr_score = self.check_subject_rights_compliance()
        violations.extend(sr_violations)

        br_ok, br_violations, br_score = self.check_breach_readiness()
        violations.extend(br_violations)

        dpa_ok, dpa_violations_list, dpa_score = self.check_dpa_compliance()
        violations.extend(dpa_violations_list)

        retention_violations = self.validate_retention_periods()
        violations.extend(retention_violations)

        overall_score = (consent_score + dp_score + sr_score + br_score + dpa_score) / 5.0

        if consent_score < 0.8:
            recommendations.append("Review and refresh consent records")
        if dp_score < 0.8:
            recommendations.append("Implement additional data protection measures")
        if sr_score < 0.8:
            recommendations.append("Improve data subject request handling process")
        if br_score < 0.8:
            recommendations.append("Enhance breach notification procedures")
        if dpa_score < 0.8:
            recommendations.append("Review and update Data Processing Agreements")

        if not self.ropar:
            recommendations.append("Create Record of Processing Activities (ROPAR)")

        overdue_requests = self.get_overdue_subject_requests()
        if overdue_requests:
            recommendations.append(f"Address {len(overdue_requests)} overdue subject access requests")

        if self.config.cross_border_transfer_allowed and self.processing_records:
            recommendations.append("Review cross-border data transfer mechanisms")

        recommendations.append("Schedule regular data protection training for staff")
        recommendations.append("Review data retention and deletion schedules")
        recommendations.append("Update privacy notice to reflect current processing activities")

        report = GDPRReport(
            compliant=overall_score >= 0.8,
            violations=violations,
            recommendations=recommendations,
            timestamp=datetime.utcnow(),
            overall_score=overall_score,
            consent_compliance=consent_score,
            data_protection_compliance=dp_score,
            subject_rights_compliance=sr_score,
            breach_readiness=br_score,
            dpa_compliance=dpa_score,
            total_checks_passed=sum(1 for s in [consent_score, dp_score, sr_score, br_score, dpa_score] if s >= 0.8),
            total_checks_failed=sum(1 for s in [consent_score, dp_score, sr_score, br_score, dpa_score] if s < 0.8)
        )

        self.check_history.append(report)
        logger.info("GDPR compliance report generated: score=%.3f, compliant=%s", overall_score, report.compliant)
        return report

    def _check_consent_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.consent_registry)
        valid = 0
        for key, record in self.consent_registry.items():
            if not record.is_valid():
                reason = "expired" if record.expires_at and datetime.utcnow() > record.expires_at else record.status.value
                violations.append(f"Consent {record.consent_id} ({key}): {reason}")
            else:
                valid += 1

        if self.config.consent_required and not self.consent_registry:
            violations.append("No consents recorded but consent is required")

        score = valid / total if total > 0 else (1.0 if not self.config.consent_required else 0.0)
        return len(violations) == 0, violations, score

    def get_compliance_summary(self) -> Dict[str, Any]:
        return {
            "total_consents": len(self.consent_registry),
            "total_processing_records": len(self.processing_records),
            "total_subject_requests": len(self.subject_requests),
            "pending_requests": len(self.get_pending_subject_requests()),
            "overdue_requests": len(self.get_overdue_subject_requests()),
            "total_breaches": len(self.breach_notifications),
            "open_breaches": sum(1 for b in self.breach_notifications if not b.remediation_completed),
            "total_dpas": len(self.dpa_records),
            "expiring_dpas": sum(1 for d in self.dpa_records if d.is_valid() and d.days_until_expiry() and d.days_until_expiry() <= 90),
            "dpia_count": len(self.dpia_records),
            "ropar_count": len(self.ropar),
            "last_report": self.check_history[-1].get_summary() if self.check_history else None
        }

    def run_all_checks(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        results = {}
        protection_ok, protection_violations = self.check_data_protection(content, context)
        results["data_protection"] = {
            "passed": protection_ok,
            "violations": protection_violations
        }
        if context and context.get("user_id") and context.get("purpose"):
            consent_ok, consent_record = self.validate_consent(context["user_id"], context["purpose"])
            results["consent"] = {
                "passed": consent_ok,
                "consent_record": consent_record.to_dict() if consent_record else None
            }
        proc_ok, proc_violations, proc_score = self.check_processing_records_compliance()
        results["processing_records"] = {
            "passed": proc_ok,
            "score": proc_score,
            "violations": proc_violations
        }
        sr_ok, sr_violations, sr_score = self.check_subject_rights_compliance()
        results["subject_rights"] = {
            "passed": sr_ok,
            "score": sr_score,
            "violations": sr_violations
        }
        br_ok, br_violations, br_score = self.check_breach_readiness()
        results["breach_readiness"] = {
            "passed": br_ok,
            "score": br_score,
            "violations": br_violations
        }
        dpa_ok, dpa_violations, dpa_score = self.check_dpa_compliance()
        results["dpa"] = {
            "passed": dpa_ok,
            "score": dpa_score,
            "violations": dpa_violations
        }
        results["retention"] = {
            "violations": self.validate_retention_periods()
        }
        passed_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("passed"))
        total_checks = sum(1 for r in results.values() if isinstance(r, dict) and "passed" in r)
        results["overall"] = {
            "passed": passed_count == total_checks,
            "passed_checks": passed_count,
            "total_checks": total_checks,
            "compliance_rate": round(passed_count / total_checks * 100, 1) if total_checks > 0 else 100.0
        }
        return results

    def get_audit_trail(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        audit = []
        for record in self.consent_registry.values():
            if not user_id or record.user_id == user_id:
                audit.append({"type": "consent", **record.to_dict()})
        for req in self.subject_requests:
            if not user_id or req.user_id == user_id:
                audit.append({"type": "subject_request", **req.to_dict()})
        for breach in self.breach_notifications:
            audit.append({"type": "breach", **breach.to_dict()})
        for entry in self.data_processing_log:
            if not user_id or entry["user_id"] == user_id:
                audit.append({"type": "processing", **entry})
        return sorted(audit, key=lambda x: x.get("timestamp", x.get("requested_at", x.get("detected_at", ""))), reverse=True)

    def export_data_portability(self, user_id: str, format: str = "json") -> Optional[str]:
        if format not in self.config.data_portability_formats:
            logger.warning("Unsupported portability format: %s", format)
            return None
        consent_data = [r.to_dict() for r in self.consent_registry.values() if r.user_id == user_id]
        processing_data = [e for e in self.data_processing_log if e["user_id"] == user_id]
        portability_data = {
            "user_id": user_id,
            "exported_at": datetime.utcnow().isoformat(),
            "consent_records": consent_data,
            "processing_history": processing_data
        }
        if format == "json":
            return json.dumps(portability_data, indent=2, default=str)
        elif format == "csv":
            lines = ["user_id,action,data_type,purpose,timestamp"]
            for entry in processing_data:
                lines.append(f"{entry['user_id']},{entry['action']},{entry['data_type']},{entry['purpose']},{entry['timestamp']}")
            return "\n".join(lines)
        return json.dumps(portability_data, indent=2, default=str)

    def erase_user_data(self, user_id: str) -> bool:
        removed_consents = 0
        keys_to_remove = [k for k, r in self.consent_registry.items() if r.user_id == user_id]
        for key in keys_to_remove:
            del self.consent_registry[key]
            removed_consents += 1
        self.data_processing_log = [e for e in self.data_processing_log if e["user_id"] != user_id]
        for record in self.processing_records:
            if user_id in record.data_subjects:
                record.data_subjects.remove(user_id)
        logger.info("User data erased for user %s: %d consents removed", user_id, removed_consents)
        return True

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("GDPR config updated: %s = %s", key, value)
            else:
                logger.warning("Unknown config key: %s", key)
