"""
SOX compliance checker module.
Implements financial data controls, audit trail requirements, segregation of duties,
access control validation, and change management tracking
in accordance with the Sarbanes-Oxley Act.
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


class FinancialControlType(Enum):
    """Types of financial controls under SOX."""
    PREVENTIVE = "preventive"
    DETECTIVE = "detective"
    CORRECTIVE = "corrective"
    DIRECTIVE = "directive"
    COMPENSATING = "compensating"


class ControlFrequency(Enum):
    """Frequency of control operation."""
    CONTINUOUS = "continuous"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class ControlEffectiveness(Enum):
    """Effectiveness ratings for financial controls."""
    EFFECTIVE = "effective"
    PARTIALLY_EFFECTIVE = "partially_effective"
    INEFFECTIVE = "ineffective"
    NOT_TESTED = "not_tested"
    NOT_APPLICABLE = "not_applicable"


class SegregationDutyType(Enum):
    """Types of segregated duties."""
    AUTHORIZATION = "authorization"
    CUSTODY = "custody"
    RECORD_KEEPING = "record_keeping"
    RECONCILIATION = "reconciliation"
    APPROVAL = "approval"
    EXECUTION = "execution"
    REVIEW = "review"


class ChangeType(Enum):
    """Types of changes in change management."""
    EMERGENCY = "emergency"
    STANDARD = "standard"
    NORMAL = "normal"
    MINOR = "minor"
    MAJOR = "major"


class ChangeStatus(Enum):
    """Status of a change request."""
    REQUESTED = "requested"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    TESTED = "tested"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    BACKED_OUT = "backed_out"


@dataclass
class FinancialControl:
    """Financial control record for SOX compliance."""
    control_id: str
    control_name: str
    control_type: FinancialControlType
    frequency: ControlFrequency
    owner: str
    description: str
    risk_area: str
    process_area: str
    is_key_control: bool = False
    effectiveness: ControlEffectiveness = ControlEffectiveness.NOT_TESTED
    last_tested_at: Optional[datetime] = None
    last_effective_at: Optional[datetime] = None
    evidence_required: bool = True
    evidence_location: Optional[str] = None
    is_automated: bool = False
    is_active: bool = True
    remediation_plan: Optional[str] = None
    risk_rating: str = "medium"

    def is_overdue_for_testing(self, test_interval_days: int = 365) -> bool:
        if not self.last_tested_at:
            return True
        return (datetime.utcnow() - self.last_tested_at).days > test_interval_days

    def days_since_last_test(self) -> Optional[int]:
        if not self.last_tested_at:
            return None
        return (datetime.utcnow() - self.last_tested_at).days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_name": self.control_name,
            "type": self.control_type.value,
            "frequency": self.frequency.value,
            "owner": self.owner,
            "effectiveness": self.effectiveness.value,
            "is_key_control": self.is_key_control,
            "is_automated": self.is_automated,
            "is_active": self.is_active,
            "overdue_for_testing": self.is_overdue_for_testing(),
            "days_since_last_test": self.days_since_last_test()
        }


@dataclass
class AuditTrailEntry:
    """Audit trail entry for financial transactions."""
    entry_id: str
    transaction_id: str
    user_id: str
    action: str
    timestamp: datetime
    details: Dict[str, Any]
    ip_address: Optional[str] = None
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    system_component: str = "financial"
    integrity_hash: Optional[str] = None

    def verify_integrity(self) -> bool:
        if not self.integrity_hash:
            return True
        content = f"{self.transaction_id}:{self.user_id}:{self.action}:{self.timestamp.isoformat()}:{self.previous_value}:{self.new_value}"
        computed = hashlib.sha256(content.encode()).hexdigest()[:16]
        return computed == self.integrity_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "integrity_verified": self.verify_integrity(),
            "system_component": self.system_component
        }


@dataclass
class SegregationRecord:
    """Record of duty segregation."""
    seg_id: str
    user_id: str
    role: str
    allowed_duties: List[SegregationDutyType]
    prohibited_duties: List[SegregationDutyType]
    conflicts: List[str] = field(default_factory=list)
    last_reviewed_at: Optional[datetime] = None
    is_compliant: bool = True
    override_approved: bool = False
    override_reason: Optional[str] = None

    def has_conflict(self, duty: SegregationDutyType) -> bool:
        return duty in self.prohibited_duties

    def check_conflict(self, assigned_duties: List[SegregationDutyType]) -> List[str]:
        conflicts = []
        for duty in assigned_duties:
            if self.has_conflict(duty) and not self.override_approved:
                conflicts.append(f"User {self.user_id}: duty {duty.value} conflicts with role {self.role}")
        self.conflicts = conflicts
        self.is_compliant = len(conflicts) == 0
        return conflicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seg_id": self.seg_id,
            "user_id": self.user_id,
            "role": self.role,
            "allowed_duties": [d.value for d in self.allowed_duties],
            "conflicts": self.conflicts,
            "is_compliant": self.is_compliant,
            "last_reviewed": self.last_reviewed_at.isoformat() if self.last_reviewed_at else None
        }


@dataclass
class ChangeRequest:
    """Change request record for SOX change management."""
    change_id: str
    title: str
    description: str
    change_type: ChangeType
    status: ChangeStatus
    requester: str
    reviewer: Optional[str] = None
    approver: Optional[str] = None
    implemented_by: Optional[str] = None
    risk_assessment: Optional[str] = None
    test_results: Optional[str] = None
    backout_plan: Optional[str] = None
    financial_impact: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    tested_at: Optional[datetime] = None
    implemented_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    affected_controls: List[str] = field(default_factory=list)
    is_emergency: bool = False

    def requires_segregation_check(self) -> bool:
        return self.change_type in (ChangeType.MAJOR, ChangeType.STANDARD)

    def is_overdue(self, sla_hours: int = 48) -> bool:
        if self.status in (ChangeStatus.IMPLEMENTED, ChangeStatus.VERIFIED, ChangeStatus.BACKED_OUT, ChangeStatus.REJECTED):
            return False
        return (datetime.utcnow() - self.created_at).total_seconds() > sla_hours * 3600

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "title": self.title,
            "type": self.change_type.value,
            "status": self.status.value,
            "requester": self.requester,
            "created_at": self.created_at.isoformat(),
            "is_overdue": self.is_overdue(),
            "requires_segregation_check": self.requires_segregation_check()
        }


@dataclass
class FinancialReport:
    """Financial report record for SOX."""
    report_id: str
    report_name: str
    report_type: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    generated_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    controls_tested: List[str] = field(default_factory=list)
    controls_passed: int = 0
    controls_failed: int = 0
    adjustments: List[Dict[str, Any]] = field(default_factory=list)
    is_final: bool = False
    integrity_hash: Optional[str] = None
    notes: Optional[str] = None

    def verify_report_integrity(self) -> bool:
        if not self.integrity_hash:
            return True
        content = f"{self.report_id}:{self.period_start}:{self.period_end}:{self.controls_passed}:{self.controls_failed}"
        computed = hashlib.sha256(content.encode()).hexdigest()[:16]
        return computed == self.integrity_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_name": self.report_name,
            "report_type": self.report_type,
            "period": f"{self.period_start.date()} to {self.period_end.date()}",
            "is_final": self.is_final,
            "approved": self.approved_by is not None,
            "controls_passed": self.controls_passed,
            "controls_failed": self.controls_failed,
            "integrity_verified": self.verify_report_integrity()
        }


@dataclass
class SOXConfig:
    """Configuration for SOX compliance checking."""
    enabled: bool = True
    sox_section: str = "404"
    fiscal_year_start: str = "01-01"
    materiality_threshold: float = 500000.0
    control_testing_interval_days: int = 365
    audit_trail_retention_years: int = 7
    segregation_of_duties_required: bool = True
    dual_approval_required: bool = True
    change_management_required: bool = True
    financial_report_controls_required: bool = True
    disclosure_controls_required: bool = True
    internal_control_framework: str = "COSO_2013"
    independent_auditor_required: bool = True
    audit_committee_oversight: bool = True
    whistleblower_program_required: bool = True
    document_retention_policy_required: bool = True
    anti_fraud_program_required: bool = True
    code_of_ethics_required: bool = True
    conflict_of_interest_policy_required: bool = True
    related_party_transaction_review: bool = True
    management_review_controls_required: bool = True
    it_general_controls_required: bool = True
    access_management_required: bool = True
    change_management_controls_required: bool = True


class SOXComplianceChecker:
    """
    SOX compliance checker implementing financial data controls, audit trails,
    segregation of duties, access control, change management, and financial
    reporting controls in accordance with the Sarbanes-Oxley Act.
    """

    def __init__(self, config: Optional[SOXConfig] = None):
        self.config = config or SOXConfig()
        self.controls: List[FinancialControl] = []
        self.audit_trail: List[AuditTrailEntry] = []
        self.segregation_records: List[SegregationRecord] = []
        self.change_requests: List[ChangeRequest] = []
        self.financial_reports: List[FinancialReport] = []
        self.financial_patterns: List[Dict[str, Any]] = self._init_financial_patterns()
        self.whistleblower_reports: List[Dict[str, Any]] = []
        self.disclosure_controls: List[Dict[str, Any]] = []
        self.itgc_records: List[Dict[str, Any]] = []
        self.fraud_indicators: List[Dict[str, Any]] = []
        self.reconciliation_records: List[Dict[str, Any]] = []
        logger.info("SOXComplianceChecker initialized (Section %s, framework: %s)", self.config.sox_section, self.config.internal_control_framework)

    def _init_financial_patterns(self) -> List[Dict[str, Any]]:
        return [
            {"name": "revenue", "pattern": r"(?i)\b(revenue|income|sales|turnover)\s*[:=]?\s*\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", "type": "revenue", "risk": 0.6},
            {"name": "expense", "pattern": r"(?i)\b(expense|cost|spending|expenditure)\s*[:=]?\s*\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", "type": "expense", "risk": 0.5},
            {"name": "asset", "pattern": r"(?i)\b(asset|property|equipment|inventory)\s*[:=]?\s*\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", "type": "asset", "risk": 0.5},
            {"name": "liability", "pattern": r"(?i)\b(liability|debt|obligation|payable)\s*[:=]?\s*\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", "type": "liability", "risk": 0.5},
            {"name": "material_amount", "pattern": r"\$?\d{1,3}(?:,\d{3}){2,}(?:\.\d{2})?\b", "type": "material", "risk": 0.8},
            {"name": "journal_entry", "pattern": r"(?i)\b(journal|adjustment|accrual|deferral|provision)\b", "type": "adjustment", "risk": 0.4},
            {"name": "related_party", "pattern": r"(?i)\b(related.party|affiliate|subsidiary|parent|intercompany)\b", "type": "related_party", "risk": 0.7},
            {"name": "fraud_indicator", "pattern": r"(?i)\b(irregularity|restate|restatement|fraud|misstatement|error)\b", "type": "fraud_indicator", "risk": 0.9},
            {"name": "estimate", "pattern": r"(?i)\b(estimate|assumption|projection|forecast)\b", "type": "estimate", "risk": 0.4},
            {"name": "reserve", "pattern": r"(?i)\b(reserve|allowance|warranty|contingency)\s*[:=]?\s*\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", "type": "reserve", "risk": 0.6},
        ]

    def add_financial_control(self, control_name: str, control_type: FinancialControlType,
                                frequency: ControlFrequency, owner: str,
                                description: str, risk_area: str,
                                process_area: str,
                                is_key_control: bool = False,
                                is_automated: bool = False) -> FinancialControl:
        control = FinancialControl(
            control_id=str(uuid.uuid4()),
            control_name=control_name,
            control_type=control_type,
            frequency=frequency,
            owner=owner,
            description=description,
            risk_area=risk_area,
            process_area=process_area,
            is_key_control=is_key_control,
            is_automated=is_automated
        )
        self.controls.append(control)
        logger.info("Financial control added: %s (type: %s, risk: %s)", control_name, control_type.value, risk_area)
        return control

    def test_control(self, control_id: str, effective: bool,
                      tested_by: str, evidence: Optional[str] = None) -> bool:
        for control in self.controls:
            if control.control_id == control_id:
                control.effectiveness = ControlEffectiveness.EFFECTIVE if effective else ControlEffectiveness.INEFFECTIVE
                control.last_tested_at = datetime.utcnow()
                if effective:
                    control.last_effective_at = datetime.utcnow()
                if evidence:
                    control.evidence_location = evidence
                if not effective:
                    control.remediation_plan = control.remediation_plan or "Remediation plan needed"
                logger.info("Control %s tested: effective=%s by %s", control.control_name, effective, tested_by)
                return True
        return False

    def add_remediation_plan(self, control_id: str, plan: str) -> bool:
        for control in self.controls:
            if control.control_id == control_id:
                control.remediation_plan = plan
                logger.info("Remediation plan added for control %s: %s", control.control_name, plan[:50])
                return True
        return False

    def check_control_effectiveness(self) -> Tuple[bool, List[str], float]:
        violations = []
        total = len(self.controls)
        effective = 0

        for control in self.controls:
            if not control.is_active:
                continue
            if control.is_overdue_for_testing(self.config.control_testing_interval_days):
                violations.append(f"Control {control.control_name}: overdue for testing ({control.days_since_last_test()} days)")
            if control.effectiveness == ControlEffectiveness.INEFFECTIVE:
                violations.append(f"Control {control.control_name}: ineffective (risk: {control.risk_rating}, area: {control.risk_area})")
                if not control.remediation_plan:
                    violations.append(f"Control {control.control_name}: no remediation plan")
            if control.effectiveness == ControlEffectiveness.EFFECTIVE:
                effective += 1

        score = effective / total if total > 0 else 1.0
        return len(violations) == 0, violations, score

    def log_audit_entry(self, transaction_id: str, user_id: str, action: str,
                         details: Dict[str, Any],
                         previous_value: Optional[str] = None,
                         new_value: Optional[str] = None,
                         system_component: str = "financial") -> AuditTrailEntry:
        entry = AuditTrailEntry(
            entry_id=str(uuid.uuid4()),
            transaction_id=transaction_id,
            user_id=user_id,
            action=action,
            timestamp=datetime.utcnow(),
            details=details,
            previous_value=previous_value,
            new_value=new_value,
            system_component=system_component
        )
        content = f"{entry.transaction_id}:{entry.user_id}:{entry.action}:{entry.timestamp.isoformat()}:{previous_value}:{new_value}"
        entry.integrity_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        self.audit_trail.append(entry)
        logger.debug("Audit entry logged: tx=%s, user=%s, action=%s", transaction_id, user_id, action)
        return entry

    def query_audit_trail(self, transaction_id: Optional[str] = None,
                           user_id: Optional[str] = None,
                           action: Optional[str] = None,
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> List[AuditTrailEntry]:
        results = self.audit_trail
        if transaction_id:
            results = [e for e in results if e.transaction_id == transaction_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action:
            results = [e for e in results if e.action == action]
        if start_date:
            results = [e for e in results if e.timestamp >= start_date]
        if end_date:
            results = [e for e in results if e.timestamp <= end_date]
        return sorted(results, key=lambda e: e.timestamp, reverse=True)

    def verify_audit_integrity(self) -> List[str]:
        violations = []
        for entry in self.audit_trail:
            if not entry.verify_integrity():
                violations.append(f"Audit entry {entry.entry_id}: integrity hash mismatch")
        return violations

    def register_segregation(self, user_id: str, role: str,
                               allowed_duties: List[SegregationDutyType],
                               prohibited_duties: List[SegregationDutyType]) -> SegregationRecord:
        record = SegregationRecord(
            seg_id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            allowed_duties=allowed_duties,
            prohibited_duties=prohibited_duties,
            last_reviewed_at=datetime.utcnow()
        )
        self.segregation_records.append(record)
        logger.info("Segregation registered: user=%s, role=%s, allowed=%s", user_id, role, [d.value for d in allowed_duties])
        return record

    def check_segregation_conflicts(self, user_id: str, assigned_duties: List[SegregationDutyType]) -> List[str]:
        for record in self.segregation_records:
            if record.user_id == user_id:
                return record.check_conflict(assigned_duties)
        return [f"No segregation record found for user {user_id}"]

    def validate_segregation_of_duties(self) -> Tuple[bool, List[str]]:
        violations = []
        for record in self.segregation_records:
            if not record.is_compliant:
                violations.extend(record.conflicts)
            if record.last_reviewed_at and (datetime.utcnow() - record.last_reviewed_at).days > 365:
                violations.append(f"Segregation review overdue for user {record.user_id}")

        post_users = [r for r in self.segregation_records if "posting" in r.role.lower()]
        approval_users = [r for r in self.segregation_records if "approval" in r.role.lower()]
        reconciliation_users = [r for r in self.segregation_records if "reconciliation" in r.role.lower()]

        for pu in post_users:
            if pu.role in [a.role for a in approval_users]:
                violations.append(f"User {pu.user_id} in both posting and approval roles")

        return len(violations) == 0, violations

    def create_change_request(self, title: str, description: str, change_type: ChangeType,
                                requester: str, risk_assessment: Optional[str] = None,
                                backout_plan: Optional[str] = None,
                                financial_impact: Optional[str] = None) -> ChangeRequest:
        cr = ChangeRequest(
            change_id=str(uuid.uuid4()),
            title=title,
            description=description,
            change_type=change_type,
            status=ChangeStatus.REQUESTED,
            requester=requester,
            risk_assessment=risk_assessment,
            backout_plan=backout_plan,
            financial_impact=financial_impact,
            created_at=datetime.utcnow(),
            is_emergency=change_type == ChangeType.EMERGENCY
        )
        self.change_requests.append(cr)
        logger.info("Change request created: %s (type: %s, requester: %s)", title, change_type.value, requester)
        return cr

    def review_change_request(self, change_id: str, reviewer: str, status: ChangeStatus) -> bool:
        for cr in self.change_requests:
            if cr.change_id == change_id:
                cr.reviewer = reviewer
                cr.status = status
                cr.reviewed_at = datetime.utcnow()
                logger.info("Change %s reviewed by %s: status=%s", cr.title, reviewer, status.value)
                return True
        return False

    def approve_change_request(self, change_id: str, approver: str) -> bool:
        for cr in self.change_requests:
            if cr.change_id == change_id:
                cr.approver = approver
                cr.status = ChangeStatus.APPROVED
                cr.approved_at = datetime.utcnow()
                logger.info("Change %s approved by %s", cr.title, approver)
                return True
        return False

    def implement_change(self, change_id: str, implementer: str, test_results: Optional[str] = None) -> bool:
        for cr in self.change_requests:
            if cr.change_id == change_id:
                cr.implemented_by = implementer
                cr.status = ChangeStatus.IMPLEMENTED
                cr.implemented_at = datetime.utcnow()
                cr.test_results = test_results
                logger.info("Change %s implemented by %s", cr.title, implementer)
                return True
        return False

    def verify_change(self, change_id: str, verifier: str) -> bool:
        for cr in self.change_requests:
            if cr.change_id == change_id:
                cr.status = ChangeStatus.VERIFIED
                cr.verified_at = datetime.utcnow()
                logger.info("Change %s verified by %s", cr.title, verifier)
                return True
        return False

    def check_change_management(self) -> Tuple[bool, List[str]]:
        violations = []
        for cr in self.change_requests:
            if cr.is_overdue():
                violations.append(f"Change {cr.title}: overdue (type: {cr.change_type.value}, status: {cr.status.value})")
            if cr.requires_segregation_check():
                if cr.requester == cr.implemented_by and cr.implemented_by is not None:
                    violations.append(f"Change {cr.title}: requester and implementer are same person (segregation issue)")
                if cr.approver == cr.implemented_by and cr.implemented_by is not None:
                    violations.append(f"Change {cr.title}: approver and implementer are same person (segregation issue)")
            if cr.is_emergency and not cr.backout_plan:
                violations.append(f"Emergency change {cr.title}: no backout plan")
            if not cr.financial_impact and cr.change_type in (ChangeType.MAJOR, ChangeType.NORMAL):
                violations.append(f"Change {cr.title}: no financial impact assessment")

        returned_count = len(self.change_requests)
        emergency_count = sum(1 for c in self.change_requests if c.is_emergency)
        if emergency_count > returned_count * 0.2 and returned_count > 10:
            violations.append(f"High proportion of emergency changes ({emergency_count}/{returned_count}): may indicate bypassing controls")

        return len(violations) == 0, violations

    def generate_financial_report(self, report_name: str, report_type: str,
                                    period_start: datetime, period_end: datetime,
                                    generated_by: str,
                                    controls_tested: Optional[List[str]] = None) -> FinancialReport:
        tested = controls_tested or [c.control_id for c in self.controls if c.last_tested_at and c.last_tested_at >= period_start]
        passed = sum(1 for c in self.controls if c.control_id in tested and c.effectiveness == ControlEffectiveness.EFFECTIVE)
        failed = sum(1 for c in self.controls if c.control_id in tested and c.effectiveness == ControlEffectiveness.INEFFECTIVE)

        report = FinancialReport(
            report_id=str(uuid.uuid4()),
            report_name=report_name,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            controls_tested=tested,
            controls_passed=passed,
            controls_failed=failed
        )
        content = f"{report.report_id}:{report.period_start}:{report.period_end}:{passed}:{failed}"
        report.integrity_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        self.financial_reports.append(report)
        logger.info("Financial report generated: %s (period: %s to %s)", report_name, period_start.date(), period_end.date())
        return report

    def approve_financial_report(self, report_id: str, approver: str) -> bool:
        for report in self.financial_reports:
            if report.report_id == report_id:
                report.approved_by = approver
                report.approved_at = datetime.utcnow()
                report.is_final = True
                logger.info("Financial report %s approved by %s", report.report_name, approver)
                return True
        return False

    def check_financial_report_controls(self) -> Tuple[bool, List[str]]:
        violations = []
        for report in self.financial_reports:
            if report.is_final and not report.verify_report_integrity():
                violations.append(f"Report {report.report_name}: integrity verification failed")
            if report.controls_failed > 0:
                violations.append(f"Report {report.report_name}: {report.controls_failed} controls failed testing")
        return len(violations) == 0, violations

    def detect_financial_fraud_indicators(self, content: str) -> List[Dict[str, Any]]:
        indicators = []
        for pattern in self.financial_patterns:
            if pattern["type"] == "fraud_indicator":
                compiled = re.compile(pattern["pattern"], re.IGNORECASE)
                matches = compiled.findall(content)
                if matches:
                    indicators.append({
                        "pattern": pattern["name"],
                        "risk": pattern["risk"],
                        "matches": matches[:5]
                    })
        return indicators

    def record_fraud_indicator(self, indicator_type: str, description: str,
                                 severity: str, source: str) -> Dict[str, Any]:
        record = {
            "fraud_id": str(uuid.uuid4()),
            "type": indicator_type,
            "description": description,
            "severity": severity,
            "source": source,
            "detected_at": datetime.utcnow().isoformat(),
            "investigation_status": "open",
            "investigation_result": None
        }
        self.fraud_indicators.append(record)
        logger.warning("Fraud indicator recorded: type=%s, severity=%s", indicator_type, severity)
        return record

    def close_fraud_indicator(self, fraud_id: str, result: str) -> bool:
        for indicator in self.fraud_indicators:
            if indicator["fraud_id"] == fraud_id:
                indicator["investigation_status"] = "closed"
                indicator["investigation_result"] = result
                logger.info("Fraud indicator closed: %s, result: %s", fraud_id, result)
                return True
        return False

    def record_reconciliation(self, account: str, period: str,
                                book_balance: float, system_balance: float,
                                difference: float, reconciled_by: str,
                                cleared: bool = False) -> Dict[str, Any]:
        record = {
            "reconciliation_id": str(uuid.uuid4()),
            "account": account,
            "period": period,
            "book_balance": book_balance,
            "system_balance": system_balance,
            "difference": difference,
            "reconciled_by": reconciled_by,
            "reconciled_at": datetime.utcnow().isoformat(),
            "cleared": cleared,
            "difference_percentage": round(abs(difference) / book_balance * 100, 2) if book_balance != 0 else 0.0,
            "notes": None
        }
        self.reconciliation_records.append(record)
        logger.info("Reconciliation recorded: account=%s, period=%s, diff=%.2f", account, period, difference)
        return record

    def check_reconciliations(self) -> List[str]:
        violations = []
        for rec in self.reconciliation_records:
            if not rec["cleared"] and rec["difference"] >= self.config.materiality_threshold:
                violations.append(f"Reconciliation {rec['reconciliation_id']}: material difference {rec['difference']:.2f} not cleared")
            if rec["difference_percentage"] > 5.0 and not rec["cleared"]:
                violations.append(f"Reconciliation {rec['reconciliation_id']}: difference {rec['difference_percentage']:.2f}% exceeds 5% threshold")
        return violations

    def submit_whistleblower_report(self, reporter_type: str, category: str,
                                      description: str, anonymous: bool = True) -> Dict[str, Any]:
        report = {
            "report_id": str(uuid.uuid4()),
            "reporter_type": reporter_type if not anonymous else "anonymous",
            "category": category,
            "description": description,
            "anonymous": anonymous,
            "submitted_at": datetime.utcnow().isoformat(),
            "status": "received",
            "investigation_status": "pending",
            "findings": None,
            "resolution": None
        }
        self.whistleblower_reports.append(report)
        logger.info("Whistleblower report submitted: category=%s", category)
        return report

    def investigate_whistleblower_report(self, report_id: str, investigator: str,
                                           findings: str) -> bool:
        for report in self.whistleblower_reports:
            if report["report_id"] == report_id:
                report["investigation_status"] = "investigated"
                report["findings"] = findings
                report["investigated_by"] = investigator
                report["investigated_at"] = datetime.utcnow().isoformat()
                logger.info("Whistleblower report investigated: %s", report_id)
                return True
        return False

    def add_disclosure_control(self, control_name: str, description: str,
                                 owner: str, effectiveness: ControlEffectiveness = ControlEffectiveness.NOT_TESTED) -> Dict[str, Any]:
        control = {
            "dc_id": str(uuid.uuid4()),
            "name": control_name,
            "description": description,
            "owner": owner,
            "effectiveness": effectiveness.value,
            "last_tested_at": datetime.utcnow().isoformat(),
            "is_active": True
        }
        self.disclosure_controls.append(control)
        logger.info("Disclosure control added: %s", control_name)
        return control

    def check_disclosure_controls(self) -> List[str]:
        violations = []
        ineffective = [c for c in self.disclosure_controls if c["effectiveness"] == ControlEffectiveness.INEFFECTIVE.value]
        for c in ineffective:
            violations.append(f"Disclosure control {c['name']} is ineffective")
        return violations

    def add_itgc(self, control_name: str, category: str, description: str,
                  owner: str, effectiveness: ControlEffectiveness = ControlEffectiveness.NOT_TESTED) -> Dict[str, Any]:
        record = {
            "itgc_id": str(uuid.uuid4()),
            "name": control_name,
            "category": category,
            "description": description,
            "owner": owner,
            "effectiveness": effectiveness.value,
            "last_tested_at": datetime.utcnow().isoformat(),
            "is_active": True
        }
        self.itgc_records.append(record)
        logger.info("ITGC added: %s (category: %s)", control_name, category)
        return record

    def check_it_general_controls(self) -> List[str]:
        violations = []
        for itgc in self.itgc_records:
            if itgc["effectiveness"] == ControlEffectiveness.INEFFECTIVE.value:
                violations.append(f"ITGC {itgc['name']} is ineffective")
        if not self.itgc_records and self.config.it_general_controls_required:
            violations.append("No IT General Controls (ITGC) recorded")
        return violations

    def run_all_sox_checks(self) -> Dict[str, Any]:
        results = {}

        ctrl_ok, ctrl_violations, ctrl_score = self.check_control_effectiveness()
        results["control_effectiveness"] = {"passed": ctrl_ok, "score": ctrl_score, "violations": ctrl_violations}

        seg_ok, seg_violations = self.validate_segregation_of_duties()
        results["segregation_of_duties"] = {"passed": seg_ok, "violations": seg_violations}

        cm_ok, cm_violations = self.check_change_management()
        results["change_management"] = {"passed": cm_ok, "violations": cm_violations}

        fr_ok, fr_violations = self.check_financial_report_controls()
        results["financial_reporting"] = {"passed": fr_ok, "violations": fr_violations}

        audit_violations = self.verify_audit_integrity()
        results["audit_integrity"] = {"violations": audit_violations}

        reconc_violations = self.check_reconciliations()
        results["reconciliations"] = {"violations": reconc_violations}

        dc_violations = self.check_disclosure_controls()
        results["disclosure_controls"] = {"violations": dc_violations}

        itgc_violations = self.check_it_general_controls()
        results["it_general_controls"] = {"violations": itgc_violations}

        passed_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("passed"))
        total_checks = sum(1 for r in results.values() if isinstance(r, dict) and "passed" in r)

        scores = [r.get("score", 1.0) for r in results.values() if isinstance(r, dict) and "score" in r]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        results["overall"] = {
            "passed": passed_count == total_checks,
            "score": round(overall_score, 3),
            "passed_checks": passed_count,
            "total_checks": total_checks,
            "compliance_rate": round(passed_count / total_checks * 100, 1) if total_checks > 0 else 100.0
        }

        return results

    def get_compliance_summary(self) -> Dict[str, Any]:
        return {
            "financial_controls": len(self.controls),
            "controls_effective": sum(1 for c in self.controls if c.effectiveness == ControlEffectiveness.EFFECTIVE),
            "controls_ineffective": sum(1 for c in self.controls if c.effectiveness == ControlEffectiveness.INEFFECTIVE),
            "controls_overdue": sum(1 for c in self.controls if c.is_overdue_for_testing()),
            "audit_trail_entries": len(self.audit_trail),
            "segregation_records": len(self.segregation_records),
            "segregation_conflicts": sum(1 for s in self.segregation_records if not s.is_compliant),
            "change_requests_total": len(self.change_requests),
            "change_requests_open": sum(1 for c in self.change_requests if c.status in (ChangeStatus.REQUESTED, ChangeStatus.REVIEWED, ChangeStatus.APPROVED)),
            "change_requests_overdue": sum(1 for c in self.change_requests if c.is_overdue()),
            "financial_reports": len(self.financial_reports),
            "reports_approved": sum(1 for r in self.financial_reports if r.is_final),
            "fraud_indicators_open": sum(1 for f in self.fraud_indicators if f["investigation_status"] == "open"),
            "whistleblower_reports": len(self.whistleblower_reports),
            "disclosure_controls": len(self.disclosure_controls),
            "it_general_controls": len(self.itgc_records)
        }

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("SOX config updated: %s = %s", key, value)
            else:
                logger.warning("Unknown SOX config key: %s", key)
