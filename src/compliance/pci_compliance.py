"""
PCI DSS compliance checker module.
Implements cardholder data detection, encryption requirements, access control
validation, network segmentation rules, and vendor management
in accordance with the Payment Card Industry Data Security Standard.
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


class CardholderDataType(Enum):
    """Types of cardholder data under PCI DSS."""
    PAN = "pan"
    CARDHOLDER_NAME = "cardholder_name"
    EXPIRATION_DATE = "expiration_date"
    SERVICE_CODE = "service_code"
    CVV_CVV2 = "cvv_cvv2"
    PIN = "pin"
    MAGNETIC_STRIPE = "magnetic_stripe"
    CHIP_DATA = "chip_data"


class EncryptionStandard(Enum):
    """Encryption standards for data protection."""
    AES_128 = "aes_128"
    AES_256 = "aes_256"
    TDES = "tdes"
    RSA_2048 = "rsa_2048"
    RSA_4096 = "rsa_4096"
    TLS_1_2 = "tls_1_2"
    TLS_1_3 = "tls_1_3"


class AccessRole(Enum):
    """Access roles for PCI DSS compliance."""
    ADMINISTRATOR = "administrator"
    DEVELOPER = "developer"
    AUDITOR = "auditor"
    OPERATOR = "operator"
    SUPPORT = "support"
    READONLY = "readonly"


class NetworkSegment(Enum):
    """Network segmentation types."""
    CDE = "cde"
    DMZ = "dmz"
    CORPORATE = "corporate"
    PARTNER = "partner"
    GUEST = "guest"
    MANAGEMENT = "management"


class TestingFrequency(Enum):
    """Testing frequencies for PCI DSS requirements."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"
    CONTINUOUS = "continuous"


class VendorStatus(Enum):
    """Vendor/service provider status."""
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNDER_REVIEW = "under_review"


@dataclass
class CardholderDataRecord:
    """Record of detected cardholder data."""
    record_id: str
    data_type: CardholderDataType
    content_preview: str
    source: str
    detected_at: datetime
    storage_location: str
    is_encrypted: bool = False
    encryption_standard: Optional[EncryptionStandard] = None
    is_tokenized: bool = False
    token_reference: Optional[str] = None
    is_truncated: bool = False
    truncation_format: Optional[str] = None
    risk_score: float = 1.0

    def is_stored_permissibly(self) -> bool:
        if self.data_type in (CardholderDataType.CVV_CVV2, CardholderDataType.PIN,
                               CardholderDataType.MAGNETIC_STRIPE, CardholderDataType.CHIP_DATA):
            return False
        if self.data_type == CardholderDataType.PAN and not (self.is_encrypted or self.is_tokenized):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "data_type": self.data_type.value,
            "source": self.source,
            "detected_at": self.detected_at.isoformat(),
            "is_encrypted": self.is_encrypted,
            "is_tokenized": self.is_tokenized,
            "is_truncated": self.is_truncated,
            "stored_permissibly": self.is_stored_permissibly(),
            "risk_score": self.risk_score
        }


@dataclass
class AccessControlRecord:
    """Access control record for PCI DSS."""
    access_id: str
    user_id: str
    role: AccessRole
    resource: str
    granted_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    needs_review: bool = False
    mfa_enabled: bool = False
    last_used_at: Optional[datetime] = None
    is_active: bool = True

    def is_current(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def days_since_last_use(self) -> Optional[int]:
        if not self.last_used_at:
            return None
        return (datetime.utcnow() - self.last_used_at).days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_id": self.access_id,
            "user_id": self.user_id,
            "role": self.role.value,
            "resource": self.resource,
            "is_current": self.is_current(),
            "mfa_enabled": self.mfa_enabled,
            "days_since_last_use": self.days_since_last_use(),
            "needs_review": self.needs_review
        }


@dataclass
class NetworkSegmentRecord:
    """Network segment configuration for PCI DSS."""
    segment_id: str
    name: str
    segment_type: NetworkSegment
    cidr: str
    is_cde: bool = False
    firewall_rules: List[str] = field(default_factory=list)
    allows_inbound_cde: bool = False
    allows_outbound_cde: bool = False
    segmentation_verified: bool = False
    last_verified_at: Optional[datetime] = None
    is_active: bool = True

    def is_properly_segmented(self) -> bool:
        if self.is_cde:
            return True
        if self.allows_inbound_cde or self.allows_outbound_cde:
            return False
        return True

    def days_since_verification(self) -> Optional[int]:
        if not self.last_verified_at:
            return None
        return (datetime.utcnow() - self.last_verified_at).days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "name": self.name,
            "type": self.segment_type.value,
            "cidr": self.cidr,
            "is_cde": self.is_cde,
            "properly_segmented": self.is_properly_segmented(),
            "days_since_verification": self.days_since_verification(),
            "firewall_rules_count": len(self.firewall_rules)
        }


@dataclass
class TestResult:
    """Security testing result record."""
    test_id: str
    test_type: str
    frequency: TestingFrequency
    conducted_at: datetime
    conducted_by: str
    scope: str
    findings: List[Dict[str, Any]]
    passed: bool
    next_due_at: Optional[datetime] = None
    remediation_required: bool = False
    remediation_deadline: Optional[datetime] = None

    def is_next_test_overdue(self) -> bool:
        if not self.next_due_at:
            return False
        return datetime.utcnow() > self.next_due_at

    def days_until_next_test(self) -> Optional[int]:
        if not self.next_due_at:
            return None
        delta = self.next_due_at - datetime.utcnow()
        return max(0, delta.days)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "test_type": self.test_type,
            "frequency": self.frequency.value,
            "conducted_at": self.conducted_at.isoformat(),
            "passed": self.passed,
            "findings_count": len(self.findings),
            "remediation_required": self.remediation_required,
            "next_due_at": self.next_due_at.isoformat() if self.next_due_at else None,
            "is_overdue": self.is_next_test_overdue()
        }


@dataclass
class VendorRecord:
    """Service provider / vendor record for PCI DSS."""
    vendor_id: str
    name: str
    service_description: str
    status: VendorStatus
    pci_compliant: bool = False
    attesting_asaq: bool = False
    contract_signed: bool = False
    contract_expires_at: Optional[datetime] = None
    last_assessed_at: Optional[datetime] = None
    assessment_frequency_days: int = 365
    handles_cardholder_data: bool = False
    incident_response_plan_reviewed: bool = False
    is_active: bool = True

    def needs_assessment(self) -> bool:
        if not self.last_assessed_at:
            return True
        days_since = (datetime.utcnow() - self.last_assessed_at).days
        return days_since > self.assessment_frequency_days

    def contract_is_valid(self) -> bool:
        if not self.contract_signed:
            return False
        if self.contract_expires_at and datetime.utcnow() > self.contract_expires_at:
            return False
        return self.is_active

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vendor_id": self.vendor_id,
            "name": self.name,
            "status": self.status.value,
            "pci_compliant": self.pci_compliant,
            "contract_valid": self.contract_is_valid(),
            "needs_assessment": self.needs_assessment(),
            "handles_cardholder_data": self.handles_cardholder_data
        }


@dataclass
class PCIRequirement:
    """Individual PCI DSS requirement."""
    requirement_id: str
    number: str
    name: str
    description: str
    control_objective: str
    testing_procedure: str
    is_applicable: bool = True
    is_compliant: bool = False
    evidence: Optional[str] = None
    notes: Optional[str] = None
    last_validated_at: Optional[datetime] = None
    remediation_plan: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "number": self.number,
            "name": self.name,
            "is_applicable": self.is_applicable,
            "is_compliant": self.is_compliant,
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "has_remediation": self.remediation_plan is not None
        }


@dataclass
class PCIConfig:
    """Configuration for PCI DSS compliance checking."""
    enabled: bool = True
    pci_version: str = "4.0"
    saq_type: str = "D"
    merchant_level: str = "2"
    transaction_volume_annual: int = 1000000
    encryption_required: bool = True
    encryption_standard: EncryptionStandard = EncryptionStandard.AES_256
    key_rotation_days: int = 365
    mfa_required: bool = True
    mfa_for_remote_access: bool = True
    mfa_for_admin_access: bool = True
    password_complexity_required: bool = True
    password_min_length: int = 12
    session_timeout_minutes: int = 15
    lockout_threshold: int = 6
    lockout_duration_minutes: int = 30
    audit_log_retention_days: int = 365
    vulnerability_scan_frequency: TestingFrequency = TestingFrequency.QUARTERLY
    penetration_test_frequency: TestingFrequency = TestingFrequency.ANNUALLY
    asv_scan_required: bool = True
    network_segmentation_required: bool = True
    cardholder_data_discovery_required: bool = True
    file_integrity_monitoring_required: bool = True
    incident_response_plan_required: bool = True
    security_awareness_program_required: bool = True
    vendor_assessment_required: bool = True
    bg_checks_required: bool = True
    physical_security_required: bool = True


class PCIComplianceChecker:
    """
    PCI DSS compliance checker implementing cardholder data detection,
    encryption requirements, access control validation, network segmentation,
    testing requirements, and vendor management.
    """

    def __init__(self, config: Optional[PCIConfig] = None):
        self.config = config or PCIConfig()
        self.cardholder_records: List[CardholderDataRecord] = []
        self.access_controls: List[AccessControlRecord] = []
        self.network_segments: List[NetworkSegmentRecord] = []
        self.test_results: List[TestResult] = []
        self.vendors: List[VendorRecord] = []
        self.requirements: List[PCIRequirement] = self._init_requirements()
        self.cardholder_patterns: List[Dict[str, Any]] = self._init_patterns()
        self.encryption_keys: List[Dict[str, Any]] = []
        self.incident_responses: List[Dict[str, Any]] = []
        self.policies: List[Dict[str, Any]] = []
        self.firewall_rules: List[Dict[str, Any]] = []
        self.changelog: List[Dict[str, Any]] = []
        logger.info("PCIComplianceChecker initialized (PCI DSS %s)", self.config.pci_version)

    def _init_patterns(self) -> List[Dict[str, Any]]:
        return [
            {"name": "pan", "pattern": r"\b\d{13,19}\b", "type": CardholderDataType.PAN, "risk": 1.0},
            {"name": "pan_formatted", "pattern": r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b", "type": CardholderDataType.PAN, "risk": 1.0},
            {"name": "pan_masked", "pattern": r"\b(?:XXXX|xxxx|\*{4})[-.\s]?\d{4}\b", "type": CardholderDataType.PAN, "risk": 0.3},
            {"name": "cvv", "pattern": r"\b\d{3,4}\b", "type": CardholderDataType.CVV_CVV2, "risk": 1.0},
            {"name": "expiration", "pattern": r"\b(?:0[1-9]|1[0-2])[-/](?:2[4-9]|[3-9]\d)\b", "type": CardholderDataType.EXPIRATION_DATE, "risk": 0.7},
            {"name": "expiration_full", "pattern": r"\b(?:exp|expires|expiry|valid.thru)[:. ]+(?:0[1-9]|1[0-2])[-/]\d{2,4}\b", "type": CardholderDataType.EXPIRATION_DATE, "risk": 0.8},
            {"name": "cardholder_name", "pattern": r"\b(?:cardholder|card.holder|name.on.card)[:. ]+[A-Z][a-z]+ [A-Z][a-z]+\b", "type": CardholderDataType.CARDHOLDER_NAME, "risk": 0.6},
            {"name": "service_code", "pattern": r"\b\d{3}\b", "type": CardholderDataType.SERVICE_CODE, "risk": 0.5},
            {"name": "track_data", "pattern": r"%[A-Z]\d{6}\^[A-Za-z]+/[A-Za-z]+\^", "type": CardholderDataType.MAGNETIC_STRIPE, "risk": 1.0},
            {"name": "pin_block", "pattern": r"(?i)\b(pin|pin.block|encrypted.pin)\s*[:=].+", "type": CardholderDataType.PIN, "risk": 1.0},
        ]

    def _init_requirements(self) -> List[PCIRequirement]:
        return [
            PCIRequirement(requirement_id="req_1", number="1.1", name="Firewall Configuration",
                           description="Install and maintain firewall configuration to protect cardholder data",
                           control_objective="Network security controls"),
            PCIRequirement(requirement_id="req_2", number="2.1", name="Vendor Defaults",
                           description="Change vendor-supplied defaults for system passwords and security parameters",
                           control_objective="Configuration management"),
            PCIRequirement(requirement_id="req_3", number="3.1", name="CHD Protection",
                           description="Protect stored cardholder data at rest",
                           control_objective="Data at rest protection"),
            PCIRequirement(requirement_id="req_4", number="4.1", name="CHD in Transit",
                           description="Encrypt cardholder data transmission across open, public networks",
                           control_objective="Data in transit protection"),
            PCIRequirement(requirement_id="req_5", number="5.1", name="Malware Protection",
                           description="Use and regularly update anti-malware software",
                           control_objective="Malware protection"),
            PCIRequirement(requirement_id="req_6", number="6.1", name="Secure Systems",
                           description="Develop and maintain secure systems and applications",
                           control_objective="Application security"),
            PCIRequirement(requirement_id="req_7", number="7.1", name="Access by Need-to-Know",
                           description="Restrict access to cardholder data by business need-to-know",
                           control_objective="Access control"),
            PCIRequirement(requirement_id="req_8", number="8.1", name="User Identification",
                           description="Identify and authenticate access to system components",
                           control_objective="Authentication"),
            PCIRequirement(requirement_id="req_9", number="9.1", name="Physical Access",
                           description="Restrict physical access to cardholder data",
                           control_objective="Physical security"),
            PCIRequirement(requirement_id="req_10", number="10.1", name="Network Monitoring",
                           description="Track and monitor all access to network resources and cardholder data",
                           control_objective="Logging and monitoring"),
            PCIRequirement(requirement_id="req_11", number="11.1", name="Security Testing",
                           description="Regularly test security systems and processes",
                           control_objective="Testing"),
            PCIRequirement(requirement_id="req_12", number="12.1", name="Information Security Policy",
                           description="Maintain a policy that addresses information security for all personnel",
                           control_objective="Policy management"),
        ]

    def detect_cardholder_data(self, content: str, source: str = "unknown",
                                 storage_location: str = "unknown") -> List[CardholderDataRecord]:
        detected = []
        for pattern in self.cardholder_patterns:
            compiled = re.compile(pattern["pattern"], re.IGNORECASE)
            matches = compiled.findall(content)
            for match in matches[:3]:
                record = CardholderDataRecord(
                    record_id=str(uuid.uuid4()),
                    data_type=pattern["type"],
                    content_preview=match.strip()[:50],
                    source=source,
                    detected_at=datetime.utcnow(),
                    storage_location=storage_location,
                    risk_score=pattern["risk"]
                )
                if pattern["type"] == CardholderDataType.PAN and len(match.replace("-", "").replace(" ", "").replace(".", "")) >= 13:
                    masked = match[:6] + "******" + match[-4:]
                    record.content_preview = masked
                detected.append(record)
                self.cardholder_records.append(record)
                logger.warning("Cardholder data detected: type=%s, source=%s", pattern["type"].value, source)
        return detected

    def validate_encryption(self, content: str, expected_standard: Optional[EncryptionStandard] = None) -> Tuple[bool, List[str]]:
        violations = []
        standard = expected_standard or self.config.encryption_standard

        detected = self.detect_cardholder_data(content)
        unencrypted_pan = [d for d in detected if d.data_type == CardholderDataType.PAN and not d.is_encrypted]

        if unencrypted_pan:
            violations.append(f"Unencrypted PAN data detected: {len(unencrypted_pan)} instances")

        sensitive_types = [d for d in detected if d.data_type in (CardholderDataType.CVV_CVV2,
                            CardholderDataType.PIN, CardholderDataType.MAGNETIC_STRIPE, CardholderDataType.CHIP_DATA)]
        if sensitive_types:
            violations.append(f"Sensitive authentication data detected (not storable post-authorization): {len(sensitive_types)}")

        if self.config.encryption_required and standard == EncryptionStandard.TDES:
            violations.append("TDES encryption is deprecated; AES-128 or stronger recommended")

        return len(violations) == 0, violations

    def validate_cardholder_storage(self, content: str) -> Tuple[bool, List[str]]:
        violations = []
        detected = self.detect_cardholder_data(content)

        for record in detected:
            if not record.is_stored_permissibly():
                if record.data_type == CardholderDataType.CVV_CVV2:
                    violations.append(f"CVV/CVV2 stored at {record.storage_location}: prohibited after authorization")
                elif record.data_type == CardholderDataType.PIN:
                    violations.append(f"PIN data stored at {record.storage_location}: prohibited")
                elif record.data_type in (CardholderDataType.MAGNETIC_STRIPE, CardholderDataType.CHIP_DATA):
                    violations.append(f"Full track data stored at {record.storage_location}: prohibited")
                elif record.data_type == CardholderDataType.PAN:
                    if not record.is_encrypted:
                        violations.append(f"Unencrypted PAN stored at {record.storage_location}: encryption required")
                    elif not record.is_truncated and not record.is_tokenized:
                        violations.append(f"PAN stored without truncation/tokenization at {record.storage_location}: render unreadable")

        return len(violations) == 0, violations

    def validate_access_control(self, user_id: str, role: AccessRole, resource: str) -> Tuple[bool, Optional[str]]:
        for ac in self.access_controls:
            if ac.user_id == user_id and ac.resource == resource:
                if not ac.is_current():
                    return False, f"Access control {ac.access_id} is expired or inactive"
                if ac.role != role:
                    return False, f"User {user_id} has role {ac.role.value}, not {role.value}"
                if role == AccessRole.ADMINISTRATOR and not ac.mfa_enabled and self.config.mfa_for_admin_access:
                    return False, f"Administrator {user_id} does not have MFA enabled"
                return True, None

        return False, f"No access control found for user {user_id}, resource {resource}"

    def grant_access(self, user_id: str, role: AccessRole, resource: str,
                      expires_in_days: Optional[int] = 365,
                      mfa_enabled: bool = True) -> AccessControlRecord:
        ac = AccessControlRecord(
            access_id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            resource=resource,
            granted_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
            mfa_enabled=mfa_enabled,
            last_used_at=datetime.utcnow()
        )
        self.access_controls.append(ac)
        logger.info("Access granted: user=%s, role=%s, resource=%s", user_id, role.value, resource)
        return ac

    def revoke_access(self, access_id: str) -> bool:
        for ac in self.access_controls:
            if ac.access_id == access_id:
                ac.is_active = False
                ac.revoked_at = datetime.utcnow()
                logger.info("Access revoked: %s (user=%s)", access_id, ac.user_id)
                return True
        return False

    def review_access_controls(self) -> Tuple[bool, List[str]]:
        violations = []
        for ac in self.access_controls:
            if ac.needs_review:
                violations.append(f"Access control {ac.access_id}: marked for review")

            if ac.days_since_last_use() and ac.days_since_last_use() > 90:
                violations.append(f"Access control {ac.access_id}: unused for {ac.days_since_last_use()} days")

            if ac.role == AccessRole.ADMINISTRATOR and not ac.mfa_enabled:
                violations.append(f"Admin {ac.user_id}: MFA not enabled")

        return len(violations) == 0, violations

    def add_network_segment(self, name: str, segment_type: NetworkSegment, cidr: str,
                              is_cde: bool = False,
                              firewall_rules: Optional[List[str]] = None) -> NetworkSegmentRecord:
        segment = NetworkSegmentRecord(
            segment_id=str(uuid.uuid4()),
            name=name,
            segment_type=segment_type,
            cidr=cidr,
            is_cde=is_cde,
            firewall_rules=firewall_rules or []
        )
        self.network_segments.append(segment)
        logger.info("Network segment added: name=%s, type=%s, cidr=%s", name, segment_type.value, cidr)
        return segment

    def verify_segmentation(self, segment_id: str) -> bool:
        for segment in self.network_segments:
            if segment.segment_id == segment_id:
                segment.segmentation_verified = True
                segment.last_verified_at = datetime.utcnow()
                logger.info("Segmentation verified: %s", segment.name)
                return True
        return False

    def check_network_segmentation(self) -> Tuple[bool, List[str]]:
        violations = []
        cde_segments = [s for s in self.network_segments if s.is_cde]
        non_cde_segments = [s for s in self.network_segments if not s.is_cde]

        if not cde_segments:
            violations.append("No CDE (Cardholder Data Environment) segments defined")

        for segment in non_cde_segments:
            if not segment.is_properly_segmented():
                violations.append(f"Non-CDE segment {segment.name} ({segment.cidr}) may access CDE: segmentation required")
            if segment.days_since_verification() and segment.days_since_verification() > 365:
                violations.append(f"Segment {segment.name} verification is {segment.days_since_verification()} days old")

        return len(violations) == 0, violations

    def record_test_result(self, test_type: str, frequency: TestingFrequency,
                            conducted_by: str, scope: str,
                            findings: List[Dict[str, Any]],
                            passed: bool) -> TestResult:
        frequency_days = {
            TestingFrequency.DAILY: 1,
            TestingFrequency.WEEKLY: 7,
            TestingFrequency.MONTHLY: 30,
            TestingFrequency.QUARTERLY: 90,
            TestingFrequency.ANNUALLY: 365,
            TestingFrequency.CONTINUOUS: 1
        }
        next_due = datetime.utcnow() + timedelta(days=frequency_days.get(frequency, 365))

        result = TestResult(
            test_id=str(uuid.uuid4()),
            test_type=test_type,
            frequency=frequency,
            conducted_at=datetime.utcnow(),
            conducted_by=conducted_by,
            scope=scope,
            findings=findings,
            passed=passed,
            next_due_at=next_due,
            remediation_required=not passed and len(findings) > 0
        )
        self.test_results.append(result)
        logger.info("Test recorded: type=%s, passed=%s, next_due=%s", test_type, passed, next_due.date())
        return result

    def check_testing_compliance(self) -> Tuple[bool, List[str]]:
        violations = []

        vuln_scans = [t for t in self.test_results if t.test_type == "vulnerability_scan"]
        if not vuln_scans:
            violations.append("No vulnerability scans recorded")
        elif vuln_scans[-1].is_next_test_overdue():
            violations.append(f"Vulnerability scan overdue: last was {vuln_scans[-1].conducted_at.date()}")

        pen_tests = [t for t in self.test_results if t.test_type == "penetration_test"]
        if not pen_tests:
            violations.append("No penetration tests recorded")
        elif pen_tests[-1].is_next_test_overdue():
            violations.append(f"Penetration test overdue: last was {pen_tests[-1].conducted_at.date()}")

        asv_scans = [t for t in self.test_results if t.test_type == "asv_scan"]
        if self.config.asv_scan_required and not asv_scans:
            violations.append("No ASV (Approved Scanning Vendor) scans recorded")

        overdue_scan = [t for t in self.test_results if t.is_next_test_overdue()]
        for test in overdue_scan:
            violations.append(f"{test.test_type} overdue (was due: {test.next_due_at.date()})")

        return len(violations) == 0, violations

    def add_vendor(self, name: str, service_description: str,
                    handles_cardholder_data: bool = False,
                    pci_compliant: bool = False) -> VendorRecord:
        vendor = VendorRecord(
            vendor_id=str(uuid.uuid4()),
            name=name,
            service_description=service_description,
            status=VendorStatus.PENDING,
            handles_cardholder_data=handles_cardholder_data,
            pci_compliant=pci_compliant
        )
        self.vendors.append(vendor)
        logger.info("Vendor added: %s (handles CHD: %s)", name, handles_cardholder_data)
        return vendor

    def approve_vendor(self, vendor_id: str, pci_compliant: bool = True) -> bool:
        for vendor in self.vendors:
            if vendor.vendor_id == vendor_id:
                vendor.status = VendorStatus.APPROVED
                vendor.pci_compliant = pci_compliant
                vendor.last_assessed_at = datetime.utcnow()
                logger.info("Vendor approved: %s (PCI compliant: %s)", vendor.name, pci_compliant)
                return True
        return False

    def assess_vendor(self, vendor_id: str, compliant: bool, asaq_completed: bool = False) -> bool:
        for vendor in self.vendors:
            if vendor.vendor_id == vendor_id:
                vendor.pci_compliant = compliant
                vendor.attesting_asaq = asaq_completed
                vendor.last_assessed_at = datetime.utcnow()
                if compliant:
                    vendor.status = VendorStatus.APPROVED
                logger.info("Vendor assessed: %s, compliant=%s", vendor.name, compliant)
                return True
        return False

    def check_vendor_compliance(self) -> Tuple[bool, List[str]]:
        violations = []
        for vendor in self.vendors:
            if vendor.handles_cardholder_data and not vendor.pci_compliant:
                violations.append(f"Vendor {vendor.name} handles CHD but is not PCI compliant")
            if vendor.needs_assessment():
                violations.append(f"Vendor {vendor.name} needs assessment (last: {vendor.last_assessed_at.date() if vendor.last_assessed_at else 'never'})")
            if not vendor.contract_is_valid():
                violations.append(f"Vendor {vendor.name} contract is not valid")
        return len(violations) == 0, violations

    def record_encryption_key(self, key_id: str, algorithm: EncryptionStandard,
                                created_at: datetime, expires_at: datetime,
                                owner: str) -> Dict[str, Any]:
        key_record = {
            "key_record_id": str(uuid.uuid4()),
            "key_id": key_id,
            "algorithm": algorithm.value,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "owner": owner,
            "is_compromised": False,
            "rotation_due": (created_at + timedelta(days=self.config.key_rotation_days)).isoformat()
        }
        self.encryption_keys.append(key_record)
        logger.info("Encryption key recorded: key_id=%s, algorithm=%s", key_id, algorithm.value)
        return key_record

    def check_key_rotation(self) -> List[str]:
        violations = []
        for key in self.encryption_keys:
            rotation_due = datetime.fromisoformat(key["rotation_due"])
            if datetime.utcnow() > rotation_due:
                violations.append(f"Key {key['key_id']} rotation overdue (was due: {key['rotation_due']})")
            if key["is_compromised"]:
                violations.append(f"Key {key['key_id']} is compromised and needs immediate replacement")
        return violations

    def record_incident_response(self, incident_type: str, description: str,
                                  response_team: List[str],
                                  containment_actions: List[str]) -> Dict[str, Any]:
        incident = {
            "incident_id": str(uuid.uuid4()),
            "incident_type": incident_type,
            "description": description,
            "response_team": response_team,
            "containment_actions": containment_actions,
            "discovered_at": datetime.utcnow().isoformat(),
            "contained_at": None,
            "resolved_at": None,
            "status": "open",
            "lessons_learned": None
        }
        self.incident_responses.append(incident)
        logger.info("Incident response recorded: type=%s", incident_type)
        return incident

    def resolve_incident(self, incident_id: str, lessons_learned: str) -> bool:
        for incident in self.incident_responses:
            if incident["incident_id"] == incident_id:
                incident["status"] = "resolved"
                incident["resolved_at"] = datetime.utcnow().isoformat()
                incident["lessons_learned"] = lessons_learned
                logger.info("Incident resolved: %s", incident_id)
                return True
        return False

    def add_policy(self, policy_name: str, policy_type: str, content: str,
                    effective_date: datetime, review_interval_days: int = 365) -> Dict[str, Any]:
        policy = {
            "policy_id": str(uuid.uuid4()),
            "name": policy_name,
            "type": policy_type,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "effective_date": effective_date.isoformat(),
            "approved_at": datetime.utcnow().isoformat(),
            "last_reviewed_at": datetime.utcnow().isoformat(),
            "review_interval_days": review_interval_days,
            "is_current": True,
            "version": "1.0"
        }
        self.policies.append(policy)
        logger.info("Policy added: %s (type: %s)", policy_name, policy_type)
        return policy

    def check_policy_reviews(self) -> List[str]:
        violations = []
        for policy in self.policies:
            if policy.get("last_reviewed_at"):
                last_review = datetime.fromisoformat(policy["last_reviewed_at"])
                days_since = (datetime.utcnow() - last_review).days
                if days_since > policy.get("review_interval_days", 365):
                    violations.append(f"Policy '{policy['name']}' needs review ({days_since} days since last review)")
        return violations

    def check_requirement(self, requirement_id: str) -> Tuple[bool, Optional[str]]:
        for req in self.requirements:
            if req.requirement_id == requirement_id:
                return req.is_compliant, req.remediation_plan
        return False, "Requirement not found"

    def update_requirement_compliance(self, requirement_id: str, compliant: bool,
                                       evidence: Optional[str] = None,
                                       remediation_plan: Optional[str] = None) -> bool:
        for req in self.requirements:
            if req.requirement_id == requirement_id:
                req.is_compliant = compliant
                req.last_validated_at = datetime.utcnow()
                if evidence:
                    req.evidence = evidence
                if remediation_plan:
                    req.remediation_plan = remediation_plan
                logger.info("Requirement %s updated: compliant=%s", requirement_id, compliant)
                return True
        return False

    def check_all_requirements(self) -> Dict[str, Any]:
        results = {}
        compliant_count = 0
        for req in self.requirements:
            if req.is_applicable:
                results[req.number] = {
                    "name": req.name,
                    "compliant": req.is_compliant,
                    "remediation": req.remediation_plan
                }
                if req.is_compliant:
                    compliant_count += 1

        applicable_count = sum(1 for r in self.requirements if r.is_applicable)
        compliance_rate = round(compliant_count / applicable_count * 100, 1) if applicable_count > 0 else 0.0

        return {
            "requirements": results,
            "compliant_count": compliant_count,
            "applicable_count": applicable_count,
            "compliance_rate": compliance_rate,
            "passed": compliance_rate >= 80.0
        }

    def run_all_pci_checks(self, content: str) -> Dict[str, Any]:
        results = {}

        chd_ok, chd_violations = self.validate_cardholder_storage(content)
        results["cardholder_storage"] = {"passed": chd_ok, "violations": chd_violations}

        enc_ok, enc_violations = self.validate_encryption(content)
        results["encryption"] = {"passed": enc_ok, "violations": enc_violations}

        access_ok, access_violations = self.review_access_controls()
        results["access_control"] = {"passed": access_ok, "violations": access_violations}

        seg_ok, seg_violations = self.check_network_segmentation()
        results["network_segmentation"] = {"passed": seg_ok, "violations": seg_violations}

        test_ok, test_violations = self.check_testing_compliance()
        results["testing"] = {"passed": test_ok, "violations": test_violations}

        vendor_ok, vendor_violations = self.check_vendor_compliance()
        results["vendors"] = {"passed": vendor_ok, "violations": vendor_violations}

        policy_violations = self.check_policy_reviews()
        results["policies"] = {"violations": policy_violations}

        key_violations = self.check_key_rotation()
        results["key_rotation"] = {"violations": key_violations}

        req_results = self.check_all_requirements()
        results["requirements"] = req_results

        passed_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("passed"))
        total_checks = sum(1 for r in results.values() if isinstance(r, dict) and "passed" in r)

        results["overall"] = {
            "passed": passed_count == total_checks,
            "passed_checks": passed_count,
            "total_checks": total_checks,
            "compliance_rate": round(passed_count / total_checks * 100, 1) if total_checks > 0 else 100.0,
            "requirements_compliance_rate": req_results.get("compliance_rate", 0.0)
        }

        return results

    def get_compliance_summary(self) -> Dict[str, Any]:
        return {
            "cardholder_records": len(self.cardholder_records),
            "access_controls_active": sum(1 for a in self.access_controls if a.is_active),
            "network_segments": len(self.network_segments),
            "tests_conducted": len(self.test_results),
            "overdue_tests": sum(1 for t in self.test_results if t.is_next_test_overdue()),
            "vendors": len(self.vendors),
            "vendors_approved": sum(1 for v in self.vendors if v.status == VendorStatus.APPROVED),
            "vendors_needing_assessment": sum(1 for v in self.vendors if v.needs_assessment()),
            "encryption_keys": len(self.encryption_keys),
            "keys_needing_rotation": len(self.check_key_rotation()),
            "incidents_open": sum(1 for i in self.incident_responses if i["status"] == "open"),
            "policies": len(self.policies),
            "applicable_requirements": sum(1 for r in self.requirements if r.is_applicable),
            "compliant_requirements": sum(1 for r in self.requirements if r.is_applicable and r.is_compliant)
        }

    def validate_pan_format(self, pan: str) -> Dict[str, Any]:
        cleaned = pan.replace("-", "").replace(" ", "").replace(".", "")
        if not cleaned.isdigit():
            return {"valid": False, "reason": "PAN contains non-numeric characters"}

        if len(cleaned) < 13 or len(cleaned) > 19:
            return {"valid": False, "reason": f"PAN length {len(cleaned)} outside valid range (13-19)"}

        digits = [int(d) for d in cleaned]
        checksum = 0
        alt = False
        for d in reversed(digits):
            if alt:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
            alt = not alt

        if checksum % 10 != 0:
            return {"valid": False, "reason": "PAN fails Luhn algorithm check"}

        issuer = self._identify_issuer(cleaned)
        return {"valid": True, "length": len(cleaned), "issuer": issuer, "masked": cleaned[:6] + "******" + cleaned[-4:]}

    def _identify_issuer(self, pan: str) -> str:
        if pan.startswith("4"):
            return "Visa"
        elif pan.startswith(("51", "52", "53", "54", "55")):
            return "Mastercard"
        elif pan.startswith(("34", "37")):
            return "American Express"
        elif pan.startswith(("6011", "65")):
            return "Discover"
        elif pan.startswith(("36", "38")):
            return "Diners Club"
        elif pan.startswith(("3528", "3529", "353", "354", "355", "356", "357", "358")):
            return "JCB"
        return "Unknown"

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("PCI config updated: %s = %s", key, value)
            else:
                logger.warning("Unknown PCI config key: %s", key)
