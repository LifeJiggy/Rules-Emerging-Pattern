"""
Compliance orchestrator module.
Coordinates multiple compliance checks (GDPR, HIPAA, PCI, SOX),
manages regulation enable/disable per tenant, detects cross-regulation
conflicts, computes compliance scoring, and tracks remediation.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .gdpr_compliance import GDPRComplianceChecker, GDPRConfig, GDPRReport
from .hipaa_compliance import HIPAAComplianceChecker, HIPAAConfig
from .pci_compliance import PCIComplianceChecker, PCIConfig
from .sox_compliance import SOXComplianceChecker, SOXConfig

logger = logging.getLogger(__name__)


class Regulation(Enum):
    """Supported compliance regulations."""
    GDPR = "gdpr"
    HIPAA = "hipaa"
    PCI = "pci"
    SOX = "sox"


class ComplianceStatus(Enum):
    """Overall compliance status."""
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_ASSESSED = "not_assessed"
    IN_PROGRESS = "in_progress"


class ConflictSeverity(Enum):
    """Severity of cross-regulation conflicts."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RemediationPriority(Enum):
    """Priority of remediation items."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RemediationStatus(Enum):
    """Status of remediation tracking."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"
    VERIFIED = "verified"


@dataclass
class TenantRegulationConfig:
    """Per-tenant regulation configuration."""
    tenant_id: str
    enabled_regulations: Set[Regulation]
    regulation_configs: Dict[Regulation, Dict[str, Any]] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    def is_enabled(self, regulation: Regulation) -> bool:
        return regulation in self.enabled_regulations

    def enable(self, regulation: Regulation) -> None:
        self.enabled_regulations.add(regulation)
        logger.info("Regulation %s enabled for tenant %s", regulation.value, self.tenant_id)

    def disable(self, regulation: Regulation) -> None:
        self.enabled_regulations.discard(regulation)
        logger.info("Regulation %s disabled for tenant %s", regulation.value, self.tenant_id)

    def get_config(self, regulation: Regulation) -> Dict[str, Any]:
        return self.regulation_configs.get(regulation, {})

    def set_config(self, regulation: Regulation, config: Dict[str, Any]) -> None:
        self.regulation_configs[regulation] = config

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "enabled_regulations": [r.value for r in self.enabled_regulations],
            "is_active": self.is_active
        }


@dataclass
class CrossRegulationConflict:
    """Conflict between requirements of different regulations."""
    conflict_id: str
    regulations: List[Regulation]
    description: str
    severity: ConflictSeverity
    gdpr_requirement: Optional[str] = None
    hipaa_requirement: Optional[str] = None
    pci_requirement: Optional[str] = None
    sox_requirement: Optional[str] = None
    recommended_resolution: Optional[str] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "regulations": [r.value for r in self.regulations],
            "description": self.description,
            "severity": self.severity.value,
            "recommended_resolution": self.recommended_resolution,
            "resolved": self.resolved,
            "detected_at": self.detected_at.isoformat()
        }


@dataclass
class ComplianceScore:
    """Compliance score across regulations."""
    regulation: Regulation
    score: float
    compliant: bool
    violations_count: int
    passed_checks: int
    total_checks: int
    last_assessed: datetime = field(default_factory=datetime.utcnow)

    def get_grade(self) -> str:
        if self.score >= 0.95:
            return "A"
        elif self.score >= 0.85:
            return "B"
        elif self.score >= 0.70:
            return "C"
        elif self.score >= 0.50:
            return "D"
        return "F"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regulation": self.regulation.value,
            "score": round(self.score, 3),
            "grade": self.get_grade(),
            "compliant": self.compliant,
            "violations_count": self.violations_count,
            "passed_checks": self.passed_checks,
            "total_checks": self.total_checks,
            "last_assessed": self.last_assessed.isoformat()
        }


@dataclass
class RemediationItem:
    """Tracked remediation action item."""
    item_id: str
    regulation: Regulation
    description: str
    priority: RemediationPriority
    status: RemediationStatus = RemediationStatus.OPEN
    assigned_to: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    verification_notes: Optional[str] = None
    source_check: Optional[str] = None
    evidence: Optional[str] = None

    def is_overdue(self) -> bool:
        if not self.due_date:
            return False
        if self.status in (RemediationStatus.RESOLVED, RemediationStatus.VERIFIED):
            return False
        return datetime.utcnow() > self.due_date

    def days_until_due(self) -> Optional[int]:
        if not self.due_date:
            return None
        delta = self.due_date - datetime.utcnow()
        return max(0, delta.days)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "regulation": self.regulation.value,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "is_overdue": self.is_overdue(),
            "days_until_due": self.days_until_due()
        }


@dataclass
class ComplianceDashboard:
    """Dashboard data for compliance overview."""
    overall_status: ComplianceStatus
    overall_score: float
    regulation_scores: Dict[str, ComplianceScore]
    active_violations: int
    open_remediations: int
    overdue_remediations: int
    active_conflicts: int
    last_updated: datetime = field(default_factory=datetime.utcnow)
    trending: str = "stable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "overall_score": round(self.overall_score, 3),
            "regulation_scores": {k: v.to_dict() for k, v in self.regulation_scores.items()},
            "active_violations": self.active_violations,
            "open_remediations": self.open_remediations,
            "overdue_remediations": self.overdue_remediations,
            "active_conflicts": self.active_conflicts,
            "last_updated": self.last_updated.isoformat(),
            "trending": self.trending
        }


@dataclass
class OrchestratorConfig:
    """Configuration for the compliance orchestrator."""
    enabled: bool = True
    auto_check_on_content: bool = True
    conflict_detection_enabled: bool = True
    remediation_tracking_enabled: bool = True
    scoring_enabled: bool = True
    dashboard_refresh_minutes: int = 60
    max_regulation_checks_per_run: int = 4
    default_tenant_id: str = "default"
    global_enabled_regulations: List[str] = field(default_factory=lambda: ["gdpr", "hipaa", "pci", "sox"])
    cross_border_dataflow_detection: bool = True
    report_retention_days: int = 730


class ComplianceOrchestrator:
    """
    Orchestrates compliance checks across multiple regulations (GDPR, HIPAA, PCI, SOX).
    Manages per-tenant regulation configuration, detects cross-regulation conflicts,
    computes compliance scoring, generates dashboard data, and tracks remediation.
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self.checkers: Dict[Regulation, Any] = {}
        self.tenant_configs: Dict[str, TenantRegulationConfig] = {}
        self.conflicts: List[CrossRegulationConflict] = []
        self.scores: Dict[str, Dict[Regulation, ComplianceScore]] = {}
        self.remediation_items: List[RemediationItem] = []
        self.audit_log: List[Dict[str, Any]] = []
        self.check_history: List[Dict[str, Any]] = []
        self.assessment_batches: Dict[str, Dict[str, Any]] = {}
        self._init_default_checkers()
        self._init_default_tenant()
        logger.info("ComplianceOrchestrator initialized with %d checkers", len(self.checkers))

    def _init_default_checkers(self) -> None:
        if Regulation.GDPR in self._get_global_regulations():
            self.checkers[Regulation.GDPR] = GDPRComplianceChecker()
        if Regulation.HIPAA in self._get_global_regulations():
            self.checkers[Regulation.HIPAA] = HIPAAComplianceChecker()
        if Regulation.PCI in self._get_global_regulations():
            self.checkers[Regulation.PCI] = PCIComplianceChecker()
        if Regulation.SOX in self._get_global_regulations():
            self.checkers[Regulation.SOX] = SOXComplianceChecker()

    def _get_global_regulations(self) -> Set[Regulation]:
        return {Regulation(r) for r in self.config.global_enabled_regulations}

    def _init_default_tenant(self) -> None:
        tenant_id = self.config.default_tenant_id
        if tenant_id not in self.tenant_configs:
            enabled = self._get_global_regulations()
            self.tenant_configs[tenant_id] = TenantRegulationConfig(
                tenant_id=tenant_id,
                enabled_regulations=enabled
            )
            logger.info("Default tenant '%s' initialized with %d regulations", tenant_id, len(enabled))

    def get_checker(self, regulation: Regulation) -> Optional[Any]:
        return self.checkers.get(regulation)

    def register_tenant(self, tenant_id: str,
                         enabled_regulations: Optional[List[Regulation]] = None) -> TenantRegulationConfig:
        if tenant_id in self.tenant_configs:
            logger.warning("Tenant %s already registered, returning existing config", tenant_id)
            return self.tenant_configs[tenant_id]

        enabled = set(enabled_regulations or [])
        if not enabled:
            enabled = self._get_global_regulations()

        config = TenantRegulationConfig(
            tenant_id=tenant_id,
            enabled_regulations=enabled
        )
        self.tenant_configs[tenant_id] = config
        logger.info("Tenant '%s' registered with regulations: %s", tenant_id, [r.value for r in enabled])
        return config

    def remove_tenant(self, tenant_id: str) -> bool:
        if tenant_id in self.tenant_configs:
            del self.tenant_configs[tenant_id]
            logger.info("Tenant '%s' removed", tenant_id)
            return True
        return False

    def enable_regulation_for_tenant(self, tenant_id: str, regulation: Regulation) -> bool:
        config = self.tenant_configs.get(tenant_id)
        if not config:
            logger.warning("Tenant %s not found", tenant_id)
            return False
        config.enable(regulation)
        if regulation not in self.checkers:
            self._create_checker(regulation)
        return True

    def disable_regulation_for_tenant(self, tenant_id: str, regulation: Regulation) -> bool:
        config = self.tenant_configs.get(tenant_id)
        if not config:
            logger.warning("Tenant %s not found", tenant_id)
            return False
        config.disable(regulation)
        return True

    def _create_checker(self, regulation: Regulation) -> None:
        if regulation == Regulation.GDPR:
            self.checkers[regulation] = GDPRComplianceChecker()
        elif regulation == Regulation.HIPAA:
            self.checkers[regulation] = HIPAAComplianceChecker()
        elif regulation == Regulation.PCI:
            self.checkers[regulation] = PCIComplianceChecker()
        elif regulation == Regulation.SOX:
            self.checkers[regulation] = SOXComplianceChecker()
        logger.info("Checker created for regulation: %s", regulation.value)

    def run_compliance_check(self, tenant_id: str, regulation: Regulation,
                              content: Optional[str] = None,
                              context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = self.tenant_configs.get(tenant_id)
        if not config or not config.is_enabled(regulation):
            logger.warning("Regulation %s not enabled for tenant %s", regulation.value, tenant_id)
            return {"error": f"Regulation {regulation.value} not enabled for tenant {tenant_id}"}

        checker = self.checkers.get(regulation)
        if not checker:
            self._create_checker(regulation)
            checker = self.checkers[regulation]

        result = {}
        if regulation == Regulation.GDPR and content is not None:
            check_result = checker.run_all_checks(content, context)
            report = checker.generate_compliance_report()
            result = check_result
            result["compliance_report"] = report.get_summary()
        elif regulation == Regulation.GDPR:
            report = checker.generate_compliance_report()
            result = {"compliance_report": report.get_summary()}
        elif regulation == Regulation.HIPAA:
            if content:
                result = checker.check_overall_compliance()
            else:
                result = checker.check_overall_compliance()
        elif regulation == Regulation.PCI:
            if content:
                result = checker.run_all_pci_checks(content)
            else:
                result = {"status": "no_content_provided"}
        elif regulation == Regulation.SOX:
            result = checker.run_all_sox_checks()

        self.audit_log.append({
            "event": "compliance_check",
            "tenant_id": tenant_id,
            "regulation": regulation.value,
            "timestamp": datetime.utcnow().isoformat(),
            "details": result
        })

        score = self._extract_score(result, regulation)
        tenant_scores = self.scores.setdefault(tenant_id, {})
        tenant_scores[regulation] = ComplianceScore(
            regulation=regulation,
            score=score,
            compliant=score >= 0.8,
            violations_count=len(result.get("violations", [])),
            passed_checks=result.get("overall", {}).get("passed_checks", 0),
            total_checks=result.get("overall", {}).get("total_checks", 1)
        )

        logger.info("Compliance check complete: tenant=%s, regulation=%s, score=%.3f", tenant_id, regulation.value, score)
        return result

    def _extract_score(self, result: Dict[str, Any], regulation: Regulation) -> float:
        overall = result.get("overall", {})
        if "score" in overall:
            return overall["score"]
        if "compliance_rate" in overall:
            return overall["compliance_rate"] / 100.0
        if regulation == Regulation.GDPR:
            report = result.get("compliance_report", {})
            return report.get("overall_score", 0.0)
        return 0.0

    def run_all_regulations(self, tenant_id: str, content: Optional[str] = None,
                             context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = self.tenant_configs.get(tenant_id)
        if not config:
            return {"error": f"Tenant {tenant_id} not found"}

        results = {}
        for regulation in Regulation:
            if config.is_enabled(regulation):
                results[regulation.value] = self.run_compliance_check(tenant_id, regulation, content, context)

        if self.config.conflict_detection_enabled:
            conflicts = self.detect_cross_regulation_conflicts(tenant_id, content or "")
            results["conflicts"] = [c.to_dict() for c in conflicts]

        overall_score = self.calculate_overall_score(tenant_id)
        results["overall"] = overall_score.to_dict()

        self.check_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "tenant_id": tenant_id,
            "results": results,
            "overall_score": overall_score.overall_score
        })

        return results

    def calculate_overall_score(self, tenant_id: str) -> ComplianceScore:
        tenant_scores = self.scores.get(tenant_id, {})
        if not tenant_scores:
            return ComplianceScore(
                regulation=Regulation.GDPR,
                score=0.0,
                compliant=False,
                violations_count=0,
                passed_checks=0,
                total_checks=0
            )

        scores = [s.score for s in tenant_scores.values()]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        total_passed = sum(s.passed_checks for s in tenant_scores.values())
        total_checks = sum(s.total_checks for s in tenant_scores.values())

        return ComplianceScore(
            regulation=Regulation.GDPR,
            score=avg_score,
            compliant=avg_score >= 0.8,
            violations_count=sum(s.violations_count for s in tenant_scores.values()),
            passed_checks=total_passed,
            total_checks=total_checks
        )

    def detect_cross_regulation_conflicts(self, tenant_id: str, content: str) -> List[CrossRegulationConflict]:
        conflicts = []
        config = self.tenant_configs.get(tenant_id)
        if not config:
            return conflicts

        enabled = config.enabled_regulations

        if Regulation.GDPR in enabled and Regulation.PCI in enabled:
            self._check_gdpr_pci_conflicts(content, conflicts)

        if Regulation.GDPR in enabled and Regulation.HIPAA in enabled:
            self._check_gdpr_hipaa_conflicts(content, conflicts)

        if Regulation.HIPAA in enabled and Regulation.SOX in enabled:
            self._check_hipaa_sox_conflicts(content, conflicts)

        if Regulation.PCI in enabled and Regulation.SOX in enabled:
            self._check_pci_sox_conflicts(content, conflicts)

        for conflict in conflicts:
            self.conflicts.append(conflict)

        return conflicts

    def _check_gdpr_pci_conflicts(self, content: str, conflicts: List[CrossRegulationConflict]) -> None:
        conflict = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.GDPR, Regulation.PCI],
            description="GDPR right to erasure vs PCI data retention requirements for cardholder data",
            severity=ConflictSeverity.HIGH,
            gdpr_requirement="Data subjects have the right to erasure ('right to be forgotten')",
            pci_requirement="Cardholder data must be retained for compliance evidence but PAN must be rendered unreadable",
            recommended_resolution="Tokenize or truncate PAN data. Use anonymization to fulfill GDPR erasure while maintaining PCI audit trail with irreversible hashing."
        )
        conflicts.append(conflict)

        conflict2 = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.GDPR, Regulation.PCI],
            description="GDPR consent withdrawal vs PCI access logging requirements",
            severity=ConflictSeverity.MEDIUM,
            gdpr_requirement="Processing must stop when consent is withdrawn",
            pci_requirement="Access logs must be retained for at least 1 year",
            recommended_resolution="Retain access logs with minimal data. Restrict future processing without deleting historical audit trails."
        )
        conflicts.append(conflict2)

    def _check_gdpr_hipaa_conflicts(self, content: str, conflicts: List[CrossRegulationConflict]) -> None:
        conflict = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.GDPR, Regulation.HIPAA],
            description="GDPR data portability vs HIPAA minimum necessary standard",
            severity=ConflictSeverity.MEDIUM,
            gdpr_requirement="Data subjects can request data portability in a structured, commonly used format",
            hipaa_requirement="Minimum necessary standard limits PHI disclosure to the minimum needed",
            recommended_resolution="Implement granular data portability with tiered access. Export only the data the patient is entitled to under both regulations."
        )
        conflicts.append(conflict)

        conflict2 = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.GDPR, Regulation.HIPAA],
            description="GDPR Data Protection Officer vs HIPAA Privacy Officer designation",
            severity=ConflictSeverity.LOW,
            gdpr_requirement="DPO must be appointed for certain processing activities",
            hipaa_requirement="Privacy Officer must be designated",
            recommended_resolution="Combine roles into a single Privacy & Data Protection Officer role fulfilling both requirements."
        )
        conflicts.append(conflict2)

    def _check_hipaa_sox_conflicts(self, content: str, conflicts: List[CrossRegulationConflict]) -> None:
        conflict = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.HIPAA, Regulation.SOX],
            description="HIPAA privacy restrictions vs SOX access to financial records for audits",
            severity=ConflictSeverity.HIGH,
            hipaa_requirement="PHI access restricted to minimum necessary",
            sox_requirement="Auditors must have full access to financial records including healthcare payment data",
            recommended_resolution="Establish a controlled audit access protocol. Use de-identified data where possible. Log all auditor PHI access with explicit authorization."
        )
        conflicts.append(conflict)

    def _check_pci_sox_conflicts(self, content: str, conflicts: List[CrossRegulationConflict]) -> None:
        conflict = CrossRegulationConflict(
            conflict_id=str(uuid.uuid4()),
            regulations=[Regulation.PCI, Regulation.SOX],
            description="PCI access control vs SOX segregation of duties in payment systems",
            severity=ConflictSeverity.MEDIUM,
            pci_requirement="Access to cardholder data must be restricted on a need-to-know basis",
            sox_requirement="Segregation of duties must prevent conflicts in financial processing",
            recommended_resolution="Implement role-based access with clear separation. Payment processing, reconciliation, and audit roles must be distinct under both standards."
        )
        conflicts.append(conflict)

    def resolve_conflict(self, conflict_id: str, resolution_notes: str) -> bool:
        for conflict in self.conflicts:
            if conflict.conflict_id == conflict_id:
                conflict.resolved = True
                conflict.resolved_at = datetime.utcnow()
                conflict.resolution_notes = resolution_notes
                logger.info("Conflict resolved: %s", conflict_id)
                return True
        return False

    def get_active_conflicts(self) -> List[CrossRegulationConflict]:
        return [c for c in self.conflicts if not c.resolved]

    def add_remediation_item(self, regulation: Regulation, description: str,
                               priority: RemediationPriority,
                               assigned_to: Optional[str] = None,
                               due_date: Optional[datetime] = None,
                               source_check: Optional[str] = None) -> RemediationItem:
        item = RemediationItem(
            item_id=str(uuid.uuid4()),
            regulation=regulation,
            description=description,
            priority=priority,
            assigned_to=assigned_to,
            due_date=due_date,
            source_check=source_check
        )
        self.remediation_items.append(item)
        logger.info("Remediation item added: %s (priority: %s)", description[:50], priority.value)
        return item

    def update_remediation_status(self, item_id: str, status: RemediationStatus,
                                    completed_by: Optional[str] = None,
                                    verification_notes: Optional[str] = None) -> bool:
        for item in self.remediation_items:
            if item.item_id == item_id:
                item.status = status
                if status in (RemediationStatus.RESOLVED, RemediationStatus.VERIFIED):
                    item.completed_at = datetime.utcnow()
                    item.completed_by = completed_by
                if verification_notes:
                    item.verification_notes = verification_notes
                logger.info("Remediation %s status updated to %s", item_id, status.value)
                return True
        return False

    def get_open_remediations(self) -> List[RemediationItem]:
        return [r for r in self.remediation_items if r.status in (RemediationStatus.OPEN, RemediationStatus.IN_PROGRESS)]

    def get_overdue_remediations(self) -> List[RemediationItem]:
        return [r for r in self.get_open_remediations() if r.is_overdue()]

    def get_remediation_by_priority(self, priority: RemediationPriority) -> List[RemediationItem]:
        return [r for r in self.remediation_items if r.priority == priority]

    def generate_dashboard(self, tenant_id: str) -> ComplianceDashboard:
        config = self.tenant_configs.get(tenant_id)
        if not config:
            return ComplianceDashboard(
                overall_status=ComplianceStatus.NOT_ASSESSED,
                overall_score=0.0,
                regulation_scores={},
                active_violations=0,
                open_remediations=0,
                overdue_remediations=0,
                active_conflicts=0
            )

        tenant_scores = self.scores.get(tenant_id, {})
        regulation_scores = {reg.value: score for reg, score in tenant_scores.items()}

        scores = [s.score for s in tenant_scores.values()]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        open_rems = len(self.get_open_remediations())
        overdue_rems = len(self.get_overdue_remediations())
        active_conflicts = len(self.get_active_conflicts())
        total_violations = sum(s.violations_count for s in tenant_scores.values())

        if overall_score >= 0.8:
            status = ComplianceStatus.COMPLIANT
        elif overall_score >= 0.5:
            status = ComplianceStatus.PARTIALLY_COMPLIANT
        else:
            status = ComplianceStatus.NON_COMPLIANT

        dashboard = ComplianceDashboard(
            overall_status=status,
            overall_score=overall_score,
            regulation_scores=regulation_scores,
            active_violations=total_violations,
            open_remediations=open_rems,
            overdue_remediations=overdue_rems,
            active_conflicts=active_conflicts,
            trending=self._calculate_trend(tenant_id)
        )

        logger.info("Dashboard generated for tenant %s: status=%s, score=%.3f",
                     tenant_id, status.value, overall_score)
        return dashboard

    def _calculate_trend(self, tenant_id: str) -> str:
        if len(self.check_history) < 2:
            return "stable"

        recent = self.check_history[-2:]
        if len(recent) < 2:
            return "stable"

        try:
            prev_score = recent[0].get("overall_score", 0.0)
            curr_score = recent[1].get("overall_score", 0.0)
            diff = curr_score - prev_score
            if diff > 0.05:
                return "improving"
            elif diff < -0.05:
                return "declining"
            return "stable"
        except (KeyError, IndexError, TypeError):
            return "stable"

    def get_audit_trail(self, tenant_id: Optional[str] = None,
                         regulation: Optional[Regulation] = None,
                         limit: int = 100) -> List[Dict[str, Any]]:
        results = self.audit_log
        if tenant_id:
            results = [e for e in results if e.get("tenant_id") == tenant_id]
        if regulation:
            results = [e for e in results if e.get("regulation") == regulation.value]
        return sorted(results, key=lambda e: e.get("timestamp", ""), reverse=True)[:limit]

    def get_compliance_summary(self, tenant_id: str) -> Dict[str, Any]:
        config = self.tenant_configs.get(tenant_id)
        if not config:
            return {"error": f"Tenant {tenant_id} not found"}

        dashboard = self.generate_dashboard(tenant_id)
        open_rems = self.get_open_remediations()
        overdue_rems = self.get_overdue_remediations()
        active_conflicts = self.get_active_conflicts()

        return {
            "tenant_id": tenant_id,
            "enabled_regulations": [r.value for r in config.enabled_regulations],
            "dashboard": dashboard.to_dict(),
            "open_remediation_count": len(open_rems),
            "overdue_remediation_count": len(overdue_rems),
            "active_conflict_count": len(active_conflicts),
            "assessment_history_count": len(self.check_history),
            "remediation_by_priority": {
                "critical": len(self.get_remediation_by_priority(RemediationPriority.CRITICAL)),
                "high": len(self.get_remediation_by_priority(RemediationPriority.HIGH)),
                "medium": len(self.get_remediation_by_priority(RemediationPriority.MEDIUM)),
                "low": len(self.get_remediation_by_priority(RemediationPriority.LOW))
            },
            "conflicts_by_severity": {
                "critical": sum(1 for c in active_conflicts if c.severity == ConflictSeverity.CRITICAL),
                "high": sum(1 for c in active_conflicts if c.severity == ConflictSeverity.HIGH),
                "medium": sum(1 for c in active_conflicts if c.severity == ConflictSeverity.MEDIUM),
                "low": sum(1 for c in active_conflicts if c.severity == ConflictSeverity.LOW)
            }
        }

    def export_compliance_report(self, tenant_id: str, format: str = "json") -> Optional[str]:
        summary = self.get_compliance_summary(tenant_id)
        if "error" in summary:
            return None

        report_data = {
            "report_id": str(uuid.uuid4()),
            "generated_at": datetime.utcnow().isoformat(),
            "tenant": summary["tenant_id"],
            "enabled_regulations": summary["enabled_regulations"],
            "dashboard": summary["dashboard"],
            "remediation_summary": {
                "open": summary["open_remediation_count"],
                "overdue": summary["overdue_remediation_count"],
                "by_priority": summary["remediation_by_priority"]
            },
            "conflicts": {
                "active": summary["active_conflict_count"],
                "by_severity": summary["conflicts_by_severity"]
            },
            "assessment_history_count": summary["assessment_history_count"]
        }

        if format == "json":
            return json.dumps(report_data, indent=2, default=str)
        elif format == "text":
            lines = []
            lines.append(f"Compliance Report for {report_data['tenant']}")
            lines.append(f"Generated: {report_data['generated_at']}")
            lines.append(f"Overall Status: {report_data['dashboard']['overall_status']}")
            lines.append(f"Overall Score: {report_data['dashboard']['overall_score']}")
            lines.append(f"Active Violations: {report_data['dashboard']['active_violations']}")
            lines.append(f"Open Remediations: {report_data['dashboard']['open_remediations']}")
            lines.append(f"Overdue Remediations: {report_data['dashboard']['overdue_remediations']}")
            return "\n".join(lines)

        return json.dumps(report_data, indent=2, default=str)

    def update_checker_config(self, regulation: Regulation, config_updates: Dict[str, Any]) -> bool:
        checker = self.checkers.get(regulation)
        if not checker:
            logger.warning("No checker for regulation %s", regulation.value)
            return False

        if hasattr(checker, "update_config"):
            checker.update_config(config_updates)
            logger.info("Config updated for regulation %s", regulation.value)
            return True
        return False

    def update_orchestrator_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("Orchestrator config updated: %s = %s", key, value)
            else:
                logger.warning("Unknown orchestrator config key: %s", key)

    def batch_assess(self, tenant_id: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
        batch = batch_id or str(uuid.uuid4())
        if batch not in self.assessment_batches:
            self.assessment_batches[batch] = {
                "batch_id": batch,
                "tenant_id": tenant_id,
                "started_at": datetime.utcnow().isoformat(),
                "completed_at": None,
                "regulations_assessed": [],
                "overall_score": None,
                "status": "in_progress"
            }

        results = self.run_all_regulations(tenant_id)
        overall = results.get("overall", {})
        self.assessment_batches[batch].update({
            "completed_at": datetime.utcnow().isoformat(),
            "regulations_assessed": [r for r in results.keys() if r != "conflicts"],
            "overall_score": overall.get("score", 0.0) if hasattr(overall, 'get') else 0.0,
            "status": "completed"
        })

        return self.assessment_batches[batch]

    def get_batch_result(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return self.assessment_batches.get(batch_id)

    def reset_tenant(self, tenant_id: str) -> bool:
        if tenant_id in self.scores:
            del self.scores[tenant_id]
        self.audit_log = [e for e in self.audit_log if e.get("tenant_id") != tenant_id]
        self.check_history = [h for h in self.check_history if h.get("tenant_id") != tenant_id]
        logger.info("Compliance data reset for tenant %s", tenant_id)
        return True

    def get_orchestrator_summary(self) -> Dict[str, Any]:
        return {
            "tenants_registered": len(self.tenant_configs),
            "active_checkers": len(self.checkers),
            "total_conflicts_detected": len(self.conflicts),
            "active_conflicts": len(self.get_active_conflicts()),
            "total_remediation_items": len(self.remediation_items),
            "open_remediation_items": len(self.get_open_remediations()),
            "overdue_remediation_items": len(self.get_overdue_remediations()),
            "total_audit_entries": len(self.audit_log),
            "total_assessment_batches": len(self.assessment_batches),
            "check_history_count": len(self.check_history),
            "dashboard_refresh_minutes": self.config.dashboard_refresh_minutes,
            "conflict_detection_enabled": self.config.conflict_detection_enabled
        }
