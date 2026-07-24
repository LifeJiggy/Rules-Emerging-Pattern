"""
HIPAA compliance checker module.
Implements Protected Health Information detection, authorization validation,
minimum necessary rule enforcement, and patient rights management
in accordance with the Health Insurance Portability and Accountability Act.
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


class PHICategory(Enum):
    """Categories of Protected Health Information."""
    DEMOGRAPHIC = "demographic"
    MEDICAL_RECORD = "medical_record"
    PAYMENT = "payment"
    INSURANCE = "insurance"
    GENETIC = "genetic"
    BIOMETRIC = "biometric"
    CLINICAL = "clinical"
    PRESCRIPTION = "prescription"
    LAB_RESULT = "lab_result"
    COMMUNICATION = "communication"


class AuthorizationStatus(Enum):
    """Status of authorization for PHI access."""
    GRANTED = "granted"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PENDING = "pending"


class AccessPurpose(Enum):
    """Permitted purposes for PHI access under HIPAA."""
    TREATMENT = "treatment"
    PAYMENT = "payment"
    HEALTHCARE_OPERATIONS = "healthcare_operations"
    RESEARCH = "research"
    PUBLIC_HEALTH = "public_health"
    LAW_ENFORCEMENT = "law_enforcement"
    JUDICIAL = "judicial"
    PATIENT_REQUEST = "patient_request"
    BREACH_NOTIFICATION = "breach_notification"
    OTHER = "other"


class MinimumNecessaryLevel(Enum):
    """Levels of minimum necessary data access."""
    FULL = "full"
    LIMITED = "limited"
    MINIMUM = "minimum"
    DENIED = "denied"


class AuditEventType(Enum):
    """Types of audit events for HIPAA compliance."""
    ACCESS = "access"
    MODIFICATION = "modification"
    DELETION = "deletion"
    DISCLOSURE = "disclosure"
    AUTHORIZATION = "authorization"
    BREACH = "breach"
    PATIENT_REQUEST = "patient_request"
    SYSTEM_ACCESS = "system_access"
    EXPORT = "export"
    PRINT = "print"


@dataclass
class PHIRecord:
    """Record of detected Protected Health Information."""
    phi_id: str
    category: PHICategory
    content_preview: str
    detection_pattern: str
    confidence: float
    detected_at: datetime
    source: str
    context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phi_id": self.phi_id,
            "category": self.category.value,
            "content_preview": self.content_preview[:100] + "..." if len(self.content_preview) > 100 else self.content_preview,
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat(),
            "source": self.source
        }


@dataclass
class AuthorizationRecord:
    """Record of authorization for PHI access."""
    auth_id: str
    patient_id: str
    requester: str
    purpose: AccessPurpose
    status: AuthorizationStatus
    phi_categories: List[PHICategory]
    granted_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    auth_form_version: str = "1.0"
    is_valid: bool = True
    restricted_to: Optional[str] = None
    data_use_agreement: Optional[str] = None

    def is_current(self) -> bool:
        if self.status != AuthorizationStatus.GRANTED:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        if not self.is_valid:
            return False
        return True

    def days_until_expiry(self) -> Optional[int]:
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)

    def covers_category(self, category: PHICategory) -> bool:
        return category in self.phi_categories

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auth_id": self.auth_id,
            "patient_id": self.patient_id,
            "requester": self.requester,
            "purpose": self.purpose.value,
            "status": self.status.value,
            "phi_categories": [c.value for c in self.phi_categories],
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_current": self.is_current(),
            "days_until_expiry": self.days_until_expiry()
        }


@dataclass
class AuditLogEntry:
    """Individual audit log entry for HIPAA compliance."""
    entry_id: str
    event_type: AuditEventType
    user_id: str
    patient_id: Optional[str] = None
    action: str
    resource: str
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[str] = None
    phi_accessed: bool = False
    authorization_id: Optional[str] = None
    outcome: str = "success"
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "patient_id": self.patient_id,
            "action": self.action,
            "resource": self.resource,
            "timestamp": self.timestamp.isoformat(),
            "phi_accessed": self.phi_accessed,
            "outcome": self.outcome
        }


@dataclass
class PatientRightsRequest:
    """Record of a patient rights request under HIPAA."""
    request_id: str
    patient_id: str
    right_type: str
    status: str
    requested_at: datetime
    completed_at: Optional[datetime] = None
    response: Optional[str] = None
    denial_reason: Optional[str] = None
    extended_deadline_used: bool = False
    documents_provided: Optional[List[str]] = None
    fee_charged: Optional[float] = None

    def deadline(self) -> datetime:
        base = self.requested_at + timedelta(days=30)
        if self.extended_deadline_used:
            base += timedelta(days=30)
        return base

    def is_overdue(self) -> bool:
        return datetime.utcnow() > self.deadline() and self.status not in ("completed", "denied")

    def days_remaining(self) -> int:
        remaining = (self.deadline() - datetime.utcnow()).days
        return max(0, remaining)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "patient_id": self.patient_id,
            "right_type": self.right_type,
            "status": self.status,
            "requested_at": self.requested_at.isoformat(),
            "deadline": self.deadline().isoformat(),
            "is_overdue": self.is_overdue(),
            "days_remaining": self.days_remaining()
        }


@dataclass
class BreachReport:
    """HIPAA breach notification record."""
    report_id: str
    discovered_at: datetime
    breach_type: str
    affected_patients_count: int
    phi_categories_compromised: List[PHICategory]
    description: str
    containment: str
    notified_patients_at: Optional[datetime] = None
    notified_hhs_at: Optional[datetime] = None
    notified_media_at: Optional[datetime] = None
    risk_assessment_completed: bool = False
    risk_level: str = "unknown"
    remediation_completed: bool = False
    reported_to_ocr: bool = False

    def notification_deadline_for_patients(self) -> datetime:
        return self.discovered_at + timedelta(days=60)

    def notification_deadline_for_hhs(self) -> datetime:
        return self.discovered_at + timedelta(days=60)

    def notification_deadline_for_media(self) -> datetime:
        return self.discovered_at + timedelta(days=60)

    def requires_media_notification(self) -> bool:
        return self.affected_patients_count > 500

    def is_patient_notification_overdue(self) -> bool:
        return datetime.utcnow() > self.notification_deadline_for_patients() and not self.notified_patients_at

    def is_hhs_notification_overdue(self) -> bool:
        return datetime.utcnow() > self.notification_deadline_for_hhs() and not self.notified_hhs_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "discovered_at": self.discovered_at.isoformat(),
            "affected_count": self.affected_patients_count,
            "risk_level": self.risk_level,
            "patients_notified": self.notified_patients_at is not None,
            "hhs_notified": self.notified_hhs_at is not None,
            "media_notified": self.notified_media_at is not None,
            "remediation_completed": self.remediation_completed,
            "patient_deadline": self.notification_deadline_for_patients().isoformat(),
            "patient_overdue": self.is_patient_notification_overdue(),
            "hhs_overdue": self.is_hhs_notification_overdue()
        }


@dataclass
class HIPAAConfig:
    """Configuration for HIPAA compliance checking."""
    enabled: bool = True
    audit_log_retention_days: int = 2190
    breach_notification_patient_days: int = 60
    breach_notification_hhs_days: int = 60
    patient_access_deadline_days: int = 30
    accounting_of_disclosures_years: int = 6
    minimum_necessary_enabled: bool = True
    authorization_required: bool = True
    encryption_required: bool = True
    backup_required: bool = True
    contingency_plan_required: bool = True
    workforce_training_required: bool = True
    sanction_policy_required: bool = True
    password_expiry_days: int = 90
    session_timeout_minutes: int = 15
    unique_user_id_required: bool = True
    emergency_access_procedure_required: bool = True
    automatic_logoff_required: bool = True
    integrity_controls_required: bool = True
    person_authentication_required: bool = True
    transmission_security_required: bool = True
    facility_access_controls_required: bool = True
    device_and_media_controls_required: bool = True
    workforce_clearance_procedure_required: bool = True
    workforce_security_required: bool = True
    information_access_management_required: bool = True
    security_awareness_training_required: bool = True
    security_incident_procedures_required: bool = True
    evaluation_required: bool = True
    business_associate_contracts_required: bool = True
    group_health_plan_disclosure_required: bool = True


@dataclass
class BusinessAssociate:
    """Business Associate record for HIPAA compliance."""
    ba_id: str
    name: str
    contact: str
    contract_signed: bool
    contract_signed_at: Optional[datetime] = None
    contract_expires_at: Optional[datetime] = None
    services_provided: List[str]
    phi_access: bool
    safeguards_confirmed: bool = False
    breach_history: List[str] = field(default_factory=list)
    is_active: bool = True

    def has_valid_contract(self) -> bool:
        if not self.contract_signed:
            return False
        if self.contract_expires_at and datetime.utcnow() > self.contract_expires_at:
            return False
        return self.is_active

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ba_id": self.ba_id,
            "name": self.name,
            "contact": self.contact,
            "contract_valid": self.has_valid_contract(),
            "phi_access": self.phi_access,
            "safeguards_confirmed": self.safeguards_confirmed,
            "breach_count": len(self.breach_history),
            "is_active": self.is_active
        }


@dataclass
class PrivacyNotice:
    """Privacy notice record for HIPAA."""
    notice_id: str
    version: str
    published_at: datetime
    effective_date: datetime
    last_reviewed_at: Optional[datetime] = None
    changes_summary: Optional[str] = None
    patient_acknowledgement_required: bool = True
    is_current: bool = True
    content_hash: Optional[str] = None

    def needs_review(self) -> bool:
        if not self.last_reviewed_at:
            return True
        days_since_review = (datetime.utcnow() - self.last_reviewed_at).days
        return days_since_review > 365

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "version": self.version,
            "effective_date": self.effective_date.isoformat(),
            "is_current": self.is_current,
            "needs_review": self.needs_review()
        }


class HIPAAComplianceChecker:
    """
    HIPAA compliance checker implementing PHI detection, authorization validation,
    minimum necessary rule enforcement, audit logging, breach notification,
    and patient rights management.
    """

    def __init__(self, config: Optional[HIPAAConfig] = None):
        self.config = config or HIPAAConfig()
        self.phi_records: List[PHIRecord] = []
        self.authorizations: List[AuthorizationRecord] = []
        self.audit_log: List[AuditLogEntry] = []
        self.patient_requests: List[PatientRightsRequest] = []
        self.breach_reports: List[BreachReport] = []
        self.business_associates: List[BusinessAssociate] = []
        self.privacy_notices: List[PrivacyNotice] = []
        self.phi_patterns: List[Dict[str, Any]] = self._init_phi_patterns()
        self.access_control_list: Dict[str, List[str]] = {}
        self.security_incidents: List[Dict[str, Any]] = []
        self.workforce_members: Dict[str, Dict[str, Any]] = {}
        self.risk_assessments: List[Dict[str, Any]] = []
        self.contingency_plans: List[Dict[str, Any]] = []
        self.sanctions: List[Dict[str, Any]] = []
        logger.info("HIPAAComplianceChecker initialized")

    def _init_phi_patterns(self) -> List[Dict[str, Any]]:
        return [
            {"name": "medical_record_number", "pattern": r"\bMRN[-: ]?\d{6,10}\b", "category": PHICategory.MEDICAL_RECORD, "risk": 0.9},
            {"name": "patient_name", "pattern": r"\b(?:Patient|Pt)[:. ]+[A-Z][a-z]+ [A-Z][a-z]+\b", "category": PHICategory.DEMOGRAPHIC, "risk": 0.8},
            {"name": "ssn", "pattern": r"\b\d{3}-\d{2}-\d{4}\b", "category": PHICategory.DEMOGRAPHIC, "risk": 1.0},
            {"name": "diagnosis_code", "pattern": r"\b[A-Z]\d{2}\.\d{1,4}\b", "category": PHICategory.CLINICAL, "risk": 0.7},
            {"name": "procedure_code", "pattern": r"\b\d{5}\b", "category": PHICategory.CLINICAL, "risk": 0.6},
            {"name": "prescription", "pattern": r"\b(?:Rx|RX|Prescription)[:. ]+[A-Z][a-z]+\b", "category": PHICategory.PRESCRIPTION, "risk": 0.8},
            {"name": "lab_result", "pattern": r"(?i)\b(?:hemoglobin|glucose|cholesterol|creatinine|potassium|sodium|wbc|rbc|plt)\s*\d+\.?\d*\b", "category": PHICategory.LAB_RESULT, "risk": 0.7},
            {"name": "insurance_id", "pattern": r"\b(?:ID|Policy)[:. ]+[A-Z]{2}\d{6,10}\b", "category": PHICategory.INSURANCE, "risk": 0.8},
            {"name": "date_of_birth", "pattern": r"\b(?:DOB|Birth|Born)[:. ]+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", "category": PHICategory.DEMOGRAPHIC, "risk": 0.7},
            {"name": "phone", "pattern": r"\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b", "category": PHICategory.DEMOGRAPHIC, "risk": 0.6},
            {"name": "email", "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "category": PHICategory.COMMUNICATION, "risk": 0.6},
            {"name": "address", "pattern": r"\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct)\b", "category": PHICategory.DEMOGRAPHIC, "risk": 0.5},
            {"name": "biometric", "pattern": r"(?i)\b(?:fingerprint|facial.scan|retina|iris|DNA|genetic.marker)\b", "category": PHICategory.BIOMETRIC, "risk": 0.9},
            {"name": "genetic_data", "pattern": r"(?i)\b(?:genome|gene.sequence|genetic.test|BRCA|genetic.marker)\b", "category": PHICategory.GENETIC, "risk": 1.0},
            {"name": "payment_info", "pattern": r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b", "category": PHICategory.PAYMENT, "risk": 0.9},
            {"name": "health_plan", "pattern": r"\b(?:HMO|PPO|EPO|POS|HDHP|CDHP)\b", "category": PHICategory.INSURANCE, "risk": 0.5},
            {"name": "allergy", "pattern": r"(?i)\b(?:allergy|allergic)\s+to\s+[A-Za-z]+\b", "category": PHICategory.CLINICAL, "risk": 0.6},
            {"name": "medication", "pattern": r"(?i)\b(?:medication|medicine|drug|dosage)\s*[:. ]+[A-Za-z]+\b", "category": PHICategory.PRESCRIPTION, "risk": 0.7},
            {"name": "clinical_note", "pattern": r"(?i)\b(?:history|assessment|plan|diagnosis|impression|recommendation)[:. ]", "category": PHICategory.CLINICAL, "risk": 0.5},
        ]

    def detect_phi(self, content: str, source: str = "unknown") -> List[PHIRecord]:
        detected = []
        for pattern in self.phi_patterns:
            compiled = re.compile(pattern["pattern"], re.IGNORECASE)
            matches = compiled.findall(content)
            for match in matches[:5]:
                record = PHIRecord(
                    phi_id=str(uuid.uuid4()),
                    category=pattern["category"],
                    content_preview=match.strip(),
                    detection_pattern=pattern["name"],
                    confidence=pattern["risk"],
                    detected_at=datetime.utcnow(),
                    source=source
                )
                detected.append(record)
                self.phi_records.append(record)
        return detected

    def check_phi_disclosure(self, content: str, purpose: AccessPurpose) -> Tuple[bool, List[str]]:
        violations = []
        detected_phi = self.detect_phi(content)

        if not detected_phi:
            return True, violations

        if purpose == AccessPurpose.RESEARCH:
            limited_data = all(
                phi.category in (PHICategory.DEMOGRAPHIC, PHICategory.CLINICAL)
                for phi in detected_phi
            )
            if not limited_data:
                violations.append("Research disclosure contains non-limited PHI categories")

        if purpose == AccessPurpose.PUBLIC_HEALTH:
            minimal_phi = all(
                phi.category in (PHICategory.DEMOGRAPHIC, PHICategory.CLINICAL)
                for phi in detected_phi
            )
            if not minimal_phi:
                violations.append("Public health disclosure exceeds minimum necessary")

        return len(violations) == 0, violations

    def validate_authorization(self, patient_id: str, requester: str,
                                purpose: AccessPurpose,
                                phi_categories: List[PHICategory]) -> Tuple[bool, Optional[str]]:
        for auth in self.authorizations:
            if auth.patient_id == patient_id and auth.requester == requester:
                if not auth.is_current():
                    return False, f"Authorization {auth.auth_id} is not current (status: {auth.status.value})"
                missing = [cat for cat in phi_categories if not auth.covers_category(cat)]
                if missing:
                    return False, f"Authorization does not cover PHI categories: {[m.value for m in missing]}"
                if purpose != auth.purpose:
                    return False, f"Authorization is for {auth.purpose.value}, not {purpose.value}"
                return True, None

        return False, f"No authorization found for patient {patient_id}, requester {requester}"

    def grant_authorization(self, patient_id: str, requester: str, purpose: AccessPurpose,
                             phi_categories: List[PHICategory],
                             expires_in_days: Optional[int] = 365,
                             restricted_to: Optional[str] = None) -> AuthorizationRecord:
        auth = AuthorizationRecord(
            auth_id=str(uuid.uuid4()),
            patient_id=patient_id,
            requester=requester,
            purpose=purpose,
            status=AuthorizationStatus.GRANTED,
            phi_categories=phi_categories,
            granted_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
            restricted_to=restricted_to
        )
        self.authorizations.append(auth)
        logger.info("Authorization granted: patient=%s, requester=%s, purpose=%s", patient_id, requester, purpose.value)

        self._log_audit_event(AuditEventType.AUTHORIZATION, "system", patient_id,
                               f"Authorization granted to {requester} for {purpose.value}",
                               phi_accessed=False, authorization_id=auth.auth_id)
        return auth

    def revoke_authorization(self, auth_id: str, reason: str) -> bool:
        for auth in self.authorizations:
            if auth.auth_id == auth_id:
                auth.status = AuthorizationStatus.REVOKED
                auth.revoked_at = datetime.utcnow()
                auth.revocation_reason = reason
                auth.is_valid = False
                logger.info("Authorization revoked: %s, reason: %s", auth_id, reason)
                return True
        return False

    def enforce_minimum_necessary(self, user_role: str, requested_categories: List[PHICategory]) -> Tuple[List[PHICategory], List[str]]:
        role_access_map = {
            "physician": [PHICategory.DEMOGRAPHIC, PHICategory.MEDICAL_RECORD, PHICategory.CLINICAL,
                          PHICategory.LAB_RESULT, PHICategory.PRESCRIPTION, PHICategory.COMMUNICATION,
                          PHICategory.INSURANCE, PHICategory.BIOMETRIC],
            "nurse": [PHICategory.DEMOGRAPHIC, PHICategory.MEDICAL_RECORD, PHICategory.CLINICAL,
                      PHICategory.LAB_RESULT, PHICategory.PRESCRIPTION],
            "billing": [PHICategory.DEMOGRAPHIC, PHICategory.PAYMENT, PHICategory.INSURANCE],
            "administrator": [PHICategory.DEMOGRAPHIC],
            "researcher": [PHICategory.DEMOGRAPHIC, PHICategory.CLINICAL],
            "pharmacist": [PHICategory.DEMOGRAPHIC, PHICategory.PRESCRIPTION],
            "lab_technician": [PHICategory.LAB_RESULT, PHICategory.DEMOGRAPHIC],
            "case_manager": [PHICategory.DEMOGRAPHIC, PHICategory.MEDICAL_RECORD, PHICategory.CLINICAL,
                             PHICategory.INSURANCE],
        }

        violations = []
        allowed = role_access_map.get(user_role, [PHICategory.DEMOGRAPHIC])

        filtered = [cat for cat in requested_categories if cat in allowed]
        rejected = [cat for cat in requested_categories if cat not in allowed]

        if rejected:
            violations.append(f"Minimum necessary rule: role '{user_role}' denied access to {[r.value for r in rejected]}")

        if self.config.minimum_necessary_enabled and not filtered:
            violations.append(f"Minimum necessary rule: no PHI categories accessible for role '{user_role}'")

        return filtered, violations

    def log_audit_event(self, event_type: AuditEventType, user_id: str, action: str,
                         resource: str, patient_id: Optional[str] = None,
                         phi_accessed: bool = False,
                         authorization_id: Optional[str] = None,
                         ip_address: Optional[str] = None) -> AuditLogEntry:
        entry = AuditLogEntry(
            entry_id=str(uuid.uuid4()),
            event_type=event_type,
            user_id=user_id,
            patient_id=patient_id,
            action=action,
            resource=resource,
            timestamp=datetime.utcnow(),
            ip_address=ip_address,
            phi_accessed=phi_accessed,
            authorization_id=authorization_id
        )
        self.audit_log.append(entry)
        logger.debug("Audit event logged: type=%s, user=%s, action=%s", event_type.value, user_id, action)
        return entry

    def _log_audit_event(self, event_type: AuditEventType, user_id: str, patient_id: Optional[str],
                          action: str, phi_accessed: bool = False,
                          authorization_id: Optional[str] = None) -> AuditLogEntry:
        entry = AuditLogEntry(
            entry_id=str(uuid.uuid4()),
            event_type=event_type,
            user_id=user_id,
            patient_id=patient_id,
            action=action,
            resource="system",
            timestamp=datetime.utcnow(),
            phi_accessed=phi_accessed,
            authorization_id=authorization_id
        )
        self.audit_log.append(entry)
        return entry

    def query_audit_log(self, patient_id: Optional[str] = None, user_id: Optional[str] = None,
                         event_type: Optional[AuditEventType] = None,
                         start_date: Optional[datetime] = None,
                         end_date: Optional[datetime] = None) -> List[AuditLogEntry]:
        results = self.audit_log
        if patient_id:
            results = [e for e in results if e.patient_id == patient_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if start_date:
            results = [e for e in results if e.timestamp >= start_date]
        if end_date:
            results = [e for e in results if e.timestamp <= end_date]
        return sorted(results, key=lambda e: e.timestamp, reverse=True)

    def generate_access_report(self, patient_id: str, years: int = 6) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=365 * years)
        relevant_entries = [e for e in self.audit_log if e.patient_id == patient_id and e.timestamp >= cutoff]

        disclosures = [e for e in relevant_entries if e.event_type == AuditEventType.DISCLOSURE]
        access_events = [e for e in relevant_entries if e.event_type == AuditEventType.ACCESS]

        return {
            "patient_id": patient_id,
            "report_period": f"{cutoff.date().isoformat()} to {datetime.utcnow().date().isoformat()}",
            "total_access_events": len(access_events),
            "total_disclosures": len(disclosures),
            "unique_requester": len(set(e.user_id for e in relevant_entries)),
            "disclosures_by_purpose": self._count_by_field(disclosures, "action"),
            "access_by_user": self._count_by_field(access_events, "user_id"),
            "phi_access_count": sum(1 for e in relevant_entries if e.phi_accessed)
        }

    def _count_by_field(self, entries: List[AuditLogEntry], field: str) -> Dict[str, int]:
        counts = {}
        for entry in entries:
            val = getattr(entry, field, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    def report_breach(self, breach_type: str, affected_count: int,
                       phi_categories: List[PHICategory], description: str,
                       containment: str) -> BreachReport:
        report = BreachReport(
            report_id=str(uuid.uuid4()),
            discovered_at=datetime.utcnow(),
            breach_type=breach_type,
            affected_patients_count=affected_count,
            phi_categories_compromised=phi_categories,
            description=description,
            containment=containment
        )
        self.breach_reports.append(report)

        if affected_count >= 500:
            report.requires_media_notification()

        logger.critical("HIPAA breach reported: type=%s, affected=%d, categories=%s",
                        breach_type, affected_count, [c.value for c in phi_categories])
        return report

    def notify_patients_of_breach(self, report_id: str) -> bool:
        for report in self.breach_reports:
            if report.report_id == report_id:
                report.notified_patients_at = datetime.utcnow()
                logger.info("Patients notified of breach %s", report_id)
                return True
        return False

    def notify_hhs_of_breach(self, report_id: str) -> bool:
        for report in self.breach_reports:
            if report.report_id == report_id:
                report.notified_hhs_at = datetime.utcnow()
                report.reported_to_ocr = True
                logger.info("HHS notified of breach %s", report_id)
                return True
        return False

    def notify_media_of_breach(self, report_id: str) -> bool:
        for report in self.breach_reports:
            if report.report_id == report_id:
                if report.requires_media_notification():
                    report.notified_media_at = datetime.utcnow()
                    logger.info("Media notified of breach %s", report_id)
                    return True
                else:
                    logger.warning("Media notification not required for breach %s (affected: %d)", report_id, report.affected_patients_count)
                    return False
        return False

    def complete_breach_remediation(self, report_id: str) -> bool:
        for report in self.breach_reports:
            if report.report_id == report_id:
                report.remediation_completed = True
                logger.info("Breach remediation completed: %s", report_id)
                return True
        return False

    def handle_patient_request(self, patient_id: str, right_type: str) -> PatientRightsRequest:
        request = PatientRightsRequest(
            request_id=str(uuid.uuid4()),
            patient_id=patient_id,
            right_type=right_type,
            status="received",
            requested_at=datetime.utcnow()
        )
        self.patient_requests.append(request)
        logger.info("Patient rights request received: patient=%s, type=%s", patient_id, right_type)
        return request

    def fulfill_patient_request(self, request_id: str, response: str, documents: Optional[List[str]] = None) -> bool:
        for req in self.patient_requests:
            if req.request_id == request_id:
                req.status = "completed"
                req.completed_at = datetime.utcnow()
                req.response = response
                req.documents_provided = documents
                logger.info("Patient request fulfilled: %s", request_id)
                return True
        return False

    def deny_patient_request(self, request_id: str, reason: str) -> bool:
        for req in self.patient_requests:
            if req.request_id == request_id:
                req.status = "denied"
                req.completed_at = datetime.utcnow()
                req.denial_reason = reason
                logger.info("Patient request denied: %s - %s", request_id, reason)
                return True
        return False

    def get_pending_patient_requests(self) -> List[PatientRightsRequest]:
        return [r for r in self.patient_requests if r.status == "received"]

    def get_overdue_patient_requests(self) -> List[PatientRightsRequest]:
        return [r for r in self.get_pending_patient_requests() if r.is_overdue()]

    def add_business_associate(self, name: str, contact: str, services: List[str],
                                phi_access: bool = True,
                                contract_signed: bool = True) -> BusinessAssociate:
        ba = BusinessAssociate(
            ba_id=str(uuid.uuid4()),
            name=name,
            contact=contact,
            contract_signed=contract_signed,
            contract_signed_at=datetime.utcnow() if contract_signed else None,
            services_provided=services,
            phi_access=phi_access,
            safeguards_confirmed=phi_access
        )
        self.business_associates.append(ba)
        logger.info("Business Associate added: %s, phi_access=%s", name, phi_access)
        return ba

    def validate_business_associate_contracts(self) -> Tuple[bool, List[str]]:
        violations = []
        for ba in self.business_associates:
            if not ba.has_valid_contract():
                violations.append(f"BA {ba.name} ({ba.ba_id}): contract is not valid")
            if ba.phi_access and not ba.safeguards_confirmed:
                violations.append(f"BA {ba.name}: PHI access without safeguards confirmation")
        if not self.business_associates and self.config.business_associate_contracts_required:
            violations.append("No business associate contracts exist")
        return len(violations) == 0, violations

    def add_privacy_notice(self, version: str, effective_date: datetime,
                            changes_summary: Optional[str] = None) -> PrivacyNotice:
        for notice in self.privacy_notices:
            notice.is_current = False

        notice = PrivacyNotice(
            notice_id=str(uuid.uuid4()),
            version=version,
            published_at=datetime.utcnow(),
            effective_date=effective_date,
            changes_summary=changes_summary
        )
        self.privacy_notices.append(notice)
        logger.info("Privacy notice published: version=%s, effective=%s", version, effective_date.date())
        return notice

    def validate_privacy_notice(self) -> Tuple[bool, List[str]]:
        violations = []
        current = [n for n in self.privacy_notices if n.is_current]

        if not current:
            violations.append("No current privacy notice")
            return False, violations

        notice = current[0]
        if not notice.last_reviewed_at:
            violations.append("Privacy notice has not been reviewed")
        elif notice.needs_review():
            violations.append(f"Privacy notice needs review (last reviewed: {notice.last_reviewed_at.date()})")

        if notice.effective_date > datetime.utcnow():
            violations.append("Privacy notice is not yet effective")

        return len(violations) == 0, violations

    def check_security_rule_compliance(self) -> Dict[str, Any]:
        results = {}

        admin_safeguards = {
            "security_management_process": self._check_security_management(),
            "assigned_security_responsibility": True,
            "workforce_security": self.config.workforce_security_required,
            "information_access_management": self.config.information_access_management_required,
            "security_awareness_training": self.config.security_awareness_training_required,
            "security_incident_procedures": self.config.security_incident_procedures_required,
            "contingency_plan": self.config.contingency_plan_required,
            "evaluation": self.config.evaluation_required,
            "business_associate_contracts": self.config.business_associate_contracts_required
        }
        results["administrative_safeguards"] = admin_safeguards

        physical_safeguards = {
            "facility_access_controls": self.config.facility_access_controls_required,
            "workstation_use": True,
            "workstation_security": True,
            "device_and_media_controls": self.config.device_and_media_controls_required
        }
        results["physical_safeguards"] = physical_safeguards

        technical_safeguards = {
            "access_control": self.config.unique_user_id_required,
            "audit_controls": self.config.audit_log_retention_days > 0,
            "integrity_controls": self.config.integrity_controls_required,
            "person_authentication": self.config.person_authentication_required,
            "transmission_security": self.config.transmission_security_required
        }
        results["technical_safeguards"] = technical_safeguards

        all_checks = list(admin_safeguards.values()) + list(physical_safeguards.values()) + list(technical_safeguards.values())
        passed = sum(1 for c in all_checks if c)
        total = len(all_checks)
        results["compliance_rate"] = round(passed / total * 100, 1) if total > 0 else 100.0
        results["passed"] = results["compliance_rate"] >= 80.0

        return results

    def _check_security_management(self) -> bool:
        has_risk_assessment = len(self.risk_assessments) > 0
        has_sanctions = len(self.sanctions) > 0
        has_contingency = len(self.contingency_plans) > 0
        return has_risk_assessment or has_sanctions or has_contingency

    def record_security_incident(self, incident_type: str, description: str,
                                  affected_patients: Optional[List[str]] = None) -> Dict[str, Any]:
        incident = {
            "incident_id": str(uuid.uuid4()),
            "incident_type": incident_type,
            "description": description,
            "affected_patients": affected_patients or [],
            "discovered_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
            "resolution": None,
            "status": "open"
        }
        self.security_incidents.append(incident)
        logger.info("Security incident recorded: type=%s", incident_type)
        return incident

    def resolve_security_incident(self, incident_id: str, resolution: str) -> bool:
        for incident in self.security_incidents:
            if incident["incident_id"] == incident_id:
                incident["resolved_at"] = datetime.utcnow().isoformat()
                incident["resolution"] = resolution
                incident["status"] = "resolved"
                logger.info("Security incident resolved: %s", incident_id)
                return True
        return False

    def conduct_risk_assessment(self, assessor: str, findings: List[Dict[str, Any]],
                                 overall_risk: str) -> Dict[str, Any]:
        assessment = {
            "assessment_id": str(uuid.uuid4()),
            "assessor": assessor,
            "conducted_at": datetime.utcnow().isoformat(),
            "findings": findings,
            "overall_risk": overall_risk,
            "findings_count": len(findings),
            "high_risk_count": sum(1 for f in findings if f.get("risk", "").lower() == "high")
        }
        self.risk_assessments.append(assessment)
        logger.info("Risk assessment conducted: assessor=%s, risk=%s", assessor, overall_risk)
        return assessment

    def create_contingency_plan(self, plan_type: str, details: Dict[str, Any]) -> Dict[str, Any]:
        plan = {
            "plan_id": str(uuid.uuid4()),
            "plan_type": plan_type,
            "details": details,
            "created_at": datetime.utcnow().isoformat(),
            "tested_at": None,
            "last_updated_at": datetime.utcnow().isoformat(),
            "is_active": True
        }
        self.contingency_plans.append(plan)
        logger.info("Contingency plan created: type=%s", plan_type)
        return plan

    def record_sanction(self, workforce_member: str, violation: str, action_taken: str) -> Dict[str, Any]:
        sanction = {
            "sanction_id": str(uuid.uuid4()),
            "workforce_member": workforce_member,
            "violation": violation,
            "action_taken": action_taken,
            "applied_at": datetime.utcnow().isoformat(),
            "status": "active"
        }
        self.sanctions.append(sanction)
        logger.info("Sanction recorded: member=%s, action=%s", workforce_member, action_taken)
        return sanction

    def check_patient_rights_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.patient_requests)
        timely = 0

        for req in self.patient_requests:
            if req.is_overdue():
                violations.append(f"Overdue patient request {req.request_id}: {req.right_type}")
            elif req.status == "completed" and not req.is_overdue():
                timely += 1
            if req.status == "denied" and not req.denial_reason:
                violations.append(f"Denied request {req.request_id} without reason")

        score = timely / total if total > 0 else 1.0
        return len(violations) == 0, violations, score

    def check_breach_notification_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.breach_reports)
        compliant = 0

        for report in self.breach_reports:
            if report.is_patient_notification_overdue():
                violations.append(f"Breach {report.report_id}: patient notification overdue")
            elif report.notified_patients_at:
                compliant += 1

            if report.is_hhs_notification_overdue():
                violations.append(f"Breach {report.report_id}: HHS notification overdue")

            if report.requires_media_notification() and not report.notified_media_at:
                violations.append(f"Breach {report.report_id}: media notification required ({report.affected_patients_count} patients affected)")

        score = compliant / total if total > 0 else 1.0
        return len(violations) == 0, violations, score

    def check_phi_protection_compliance(self, content: str) -> Tuple[bool, List[str], float]:
        violations = []
        detected = self.detect_phi(content)

        if detected:
            high_risk = [p for p in detected if p.confidence >= 0.9]
            if high_risk:
                violations.append(f"High-risk PHI detected: {[(h.detection_pattern, h.category.value) for h in high_risk]}")

            phi_by_category = {}
            for phi in detected:
                cat = phi.category.value
                phi_by_category.setdefault(cat, 0)
                phi_by_category[cat] += 1
            violations.append(f"PHI detected across categories: {phi_by_category}")

        score = 1.0 - (len(detected) * 0.05)
        score = max(0.0, score)
        return len(detected) == 0, violations, score

    def check_authorization_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.authorizations)
        valid = 0

        for auth in self.authorizations:
            if not auth.is_current():
                violations.append(f"Authorization {auth.auth_id}: expired or invalid (status: {auth.status.value})")
            else:
                valid += 1

        score = valid / total if total > 0 else (1.0 if not self.config.authorization_required else 0.0)
        return len(violations) == 0, violations, score

    def check_audit_log_compliance(self) -> Tuple[bool, List[str], float]:
        violations = []
        if not self.audit_log:
            violations.append("No audit log entries exist")

        retention_cutoff = datetime.utcnow() - timedelta(days=self.config.audit_log_retention_days)
        old_entries = [e for e in self.audit_log if e.timestamp < retention_cutoff]
        if old_entries:
            violations.append(f"Audit log contains {len(old_entries)} entries past retention period")

        phi_access_entries = [e for e in self.audit_log if e.phi_accessed]
        unauthorized_phi = [e for e in phi_access_entries if not e.authorization_id]
        if unauthorized_phi:
            violations.append(f"PHI access events without authorization: {len(unauthorized_phi)}")

        score = 1.0 if self.audit_log else 0.0
        return len(violations) == 0, violations, score

    def check_overall_compliance(self) -> Dict[str, Any]:
        results = {}

        phi_ok, phi_violations, phi_score = self.check_phi_protection_compliance("")
        results["phi_protection"] = {"passed": phi_ok, "score": phi_score, "violations": phi_violations}

        auth_ok, auth_violations, auth_score = self.check_authorization_compliance()
        results["authorization"] = {"passed": auth_ok, "score": auth_score, "violations": auth_violations}

        audit_ok, audit_violations, audit_score = self.check_audit_log_compliance()
        results["audit_log"] = {"passed": audit_ok, "score": audit_score, "violations": audit_violations}

        pr_ok, pr_violations, pr_score = self.check_patient_rights_compliance()
        results["patient_rights"] = {"passed": pr_ok, "score": pr_score, "violations": pr_violations}

        br_ok, br_violations, br_score = self.check_breach_notification_compliance()
        results["breach_notification"] = {"passed": br_ok, "score": br_score, "violations": br_violations}

        ba_ok, ba_violations = self.validate_business_associate_contracts()
        results["business_associates"] = {"passed": ba_ok, "violations": ba_violations}

        pn_ok, pn_violations = self.validate_privacy_notice()
        results["privacy_notice"] = {"passed": pn_ok, "violations": pn_violations}

        security_results = self.check_security_rule_compliance()
        results["security_rule"] = {
            "passed": security_results["passed"],
            "compliance_rate": security_results["compliance_rate"]
        }

        passed_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("passed"))
        scores = [r.get("score", 1.0) for r in results.values() if isinstance(r, dict) and "score" in r]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        results["overall"] = {
            "score": round(overall_score, 3),
            "passed_checks": passed_count,
            "total_checks": len(results),
            "compliant": overall_score >= 0.8
        }

        return results

    def get_compliance_summary(self) -> Dict[str, Any]:
        return {
            "total_phi_records": len(self.phi_records),
            "authorizations_active": sum(1 for a in self.authorizations if a.is_current()),
            "audit_log_entries": len(self.audit_log),
            "patient_requests_pending": len(self.get_pending_patient_requests()),
            "patient_requests_overdue": len(self.get_overdue_patient_requests()),
            "breaches_open": sum(1 for b in self.breach_reports if not b.remediation_completed),
            "business_associates": len(self.business_associates),
            "privacy_notices": len(self.privacy_notices),
            "security_incidents_open": len([i for i in self.security_incidents if i["status"] == "open"]),
            "contingency_plans": len(self.contingency_plans),
            "risk_assessments": len(self.risk_assessments)
        }

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("HIPAA config updated: %s = %s", key, value)
            else:
                logger.warning("Unknown HIPAA config key: %s", key)
