"""Regulatory compliance testing - GDPR, HIPAA, SOC2, PCI-DSS, CCPA frameworks."""
import logging
import re
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class RegulatoryFramework(str, Enum):
    GDPR = "gdpr"
    HIPAA = "hipaa"
    SOC2 = "soc2"
    PCI_DSS = "pci_dss"
    CCPA = "ccpa"
    COPPA = "coppa"


class ComplianceRequirement(str, Enum):
    DATA_MINIMIZATION = "data_minimization"
    CONSENT_MANAGEMENT = "consent_management"
    RIGHT_TO_ERASURE = "right_to_erasure"
    DATA_ENCRYPTION = "data_encryption"
    ACCESS_CONTROL = "access_control"
    AUDIT_LOGGING = "audit_logging"
    DATA_RETENTION = "data_retention"
    BREACH_NOTIFICATION = "breach_notification"
    DATA_PORTABILITY = "data_portability"
    THIRD_PARTY_OVERSIGHT = "third_party_oversight"
    ANONYMIZATION = "anonymization"


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    NOT_TESTED = "not_tested"


@dataclass
class RegulationCheck:
    framework: RegulatoryFramework
    requirement: ComplianceRequirement
    status: ComplianceStatus
    description: str
    evidence: Optional[str] = None
    remediation: Optional[str] = None


@dataclass
class RegulatoryComplianceResult:
    framework: RegulatoryFramework
    compliant: bool
    checks: List[RegulationCheck]
    score: float
    summary: Dict[str, Any]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


FRAMEWORK_REQUIREMENTS: Dict[RegulatoryFramework, List[Dict[str, Any]]] = {
    RegulatoryFramework.GDPR: [
        {"requirement": ComplianceRequirement.DATA_MINIMIZATION,
         "description": "Only collect data necessary for specified purpose",
         "patterns": [r"collect.*all", r"store.*everything", r"log.*everything"]},
        {"requirement": ComplianceRequirement.CONSENT_MANAGEMENT,
         "description": "Obtain explicit consent before data processing",
         "patterns": [r"without\s+consent", r"opt.?out\s+default", r"auto.+(collect|process)"]},
        {"requirement": ComplianceRequirement.RIGHT_TO_ERASURE,
         "description": "Support user data deletion requests",
         "patterns": [r"cannot\s+delete", r"permanent(ly|)\s+store", r"never\s+remove"]},
        {"requirement": ComplianceRequirement.DATA_ENCRYPTION,
         "description": "Encrypt personal data in transit and at rest",
         "patterns": [r"plaintext", r"unencrypted", r"http://"]},
        {"requirement": ComplianceRequirement.BREACH_NOTIFICATION,
         "description": "Notify authorities within 72 hours of breach",
         "patterns": [r"no\s+breach\s+notification", r"delayed\s+reporting"]},
    ],
    RegulatoryFramework.HIPAA: [
        {"requirement": ComplianceRequirement.ACCESS_CONTROL,
         "description": "Unique user IDs and emergency access procedures",
         "patterns": [r"shared\s+account", r"no\s+auth", r"public\s+access"]},
        {"requirement": ComplianceRequirement.AUDIT_LOGGING,
         "description": "Record all ePHI access and activities",
         "patterns": [r"no\s+logging", r"disable\s+audit", r"skip\s+log"]},
        {"requirement": ComplianceRequirement.DATA_ENCRYPTION,
         "description": "Encrypt ePHI at rest and in transit",
         "patterns": [r"plaintext\s+(phi|health)", r"unencrypted\s+medical"]},
    ],
    RegulatoryFramework.SOC2: [
        {"requirement": ComplianceRequirement.ACCESS_CONTROL,
         "description": "Logical and physical access controls",
         "patterns": [r"no\s+access\s+control", r"public\s+by\s+default"]},
        {"requirement": ComplianceRequirement.AUDIT_LOGGING,
         "description": "Monitor and log system activities",
         "patterns": [r"no\s+monitoring", r"disable\s+logging"]},
        {"requirement": ComplianceRequirement.THIRD_PARTY_OVERSIGHT,
         "description": "Vendor risk management and oversight",
         "patterns": [r"unvetted\s+(vendor|third.?party)"]},
    ],
    RegulatoryFramework.PCI_DSS: [
        {"requirement": ComplianceRequirement.DATA_ENCRYPTION,
         "description": "Encrypt cardholder data over public networks",
         "patterns": [r"plaintext\s+(cc|card|credit)", r"unencrypted\s+payment"]},
        {"requirement": ComplianceRequirement.ACCESS_CONTROL,
         "description": "Restrict cardholder data access by need-to-know",
         "patterns": [r"all\s+users?\s+can\s+(view|access|read)\s+(cc|card|payment)"]},
    ],
    RegulatoryFramework.CCPA: [
        {"requirement": ComplianceRequirement.RIGHT_TO_ERASURE,
         "description": "Support consumer data deletion requests",
         "patterns": [r"cannot\s+delete", r"retain\s+forever"]},
        {"requirement": ComplianceRequirement.DATA_PORTABILITY,
         "description": "Provide data in portable format upon request",
         "patterns": [r"no\s+export", r"proprietary\s+format\s+only"]},
    ],
}


class RegulatoryCompliance:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._frameworks: Set[RegulatoryFramework] = {
            RegulatoryFramework(fw) for fw in self.config.get(
                "frameworks", ["gdpr", "hipaa", "soc2"]
            )
        }
        self._history: List[RegulatoryComplianceResult] = []
        self._custom_checks: Dict[RegulatoryFramework, List[Dict[str, Any]]] = {
            fw: self.config.get(f"custom_checks_{fw.value}", [])
            for fw in RegulatoryFramework
        }
        logger.info("RegulatoryCompliance initialized (frameworks=%s)",
                     [fw.value for fw in self._frameworks])

    def check_compliance(self, data: Dict[str, Any]) -> List[RegulatoryComplianceResult]:
        results: List[RegulatoryComplianceResult] = []
        for framework in self._frameworks:
            result = self._check_framework(framework, data)
            results.append(result)
            self._history.append(result)
            logger.info(
                "Framework %s: %s (score=%.2f, checks=%d)",
                framework.value, "PASS" if result.compliant else "FAIL",
                result.score, len(result.checks)
            )
        return results

    def check_single_framework(
        self,
        framework: RegulatoryFramework,
        data: Dict[str, Any]
    ) -> RegulatoryComplianceResult:
        result = self._check_framework(framework, data)
        self._history.append(result)
        return result

    def get_statistics(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_checks": 0}

        by_framework: Dict[str, List[float]] = defaultdict(list)
        for r in self._history:
            by_framework[r.framework.value].append(r.score)

        return {
            "frameworks_tested": list(by_framework.keys()),
            "avg_scores": {
                fw: sum(scores) / len(scores)
                for fw, scores in by_framework.items()
            },
            "lowest_framework": min(by_framework, key=lambda f: sum(by_framework[f]) / len(by_framework[f])),
            "highest_framework": max(by_framework, key=lambda f: sum(by_framework[f]) / len(by_framework[f])),
        }

    def _check_framework(
        self,
        framework: RegulatoryFramework,
        data: Dict[str, Any]
    ) -> RegulatoryComplianceResult:
        content = data.get("content", data.get("text", str(data)))
        checks: List[RegulationCheck] = []

        requirements = FRAMEWORK_REQUIREMENTS.get(framework, [])
        custom = self._custom_checks.get(framework, [])
        all_requirements = requirements + custom

        for req in all_requirements:
            requirement = req["requirement"]
            description = req["description"]
            patterns = req.get("patterns", [])

            violations_found = self._check_patterns(patterns, content)
            has_evidence = data.get(f"evidence_{requirement.value}")

            if violations_found:
                status = ComplianceStatus.NON_COMPLIANT
            elif has_evidence:
                status = ComplianceStatus.COMPLIANT
            else:
                status = ComplianceStatus.NOT_TESTED

            checks.append(RegulationCheck(
                framework=framework,
                requirement=requirement,
                status=status,
                description=description,
                evidence=has_evidence,
                remediation=req.get("remediation", f"Implement {requirement.value} controls") if status == ComplianceStatus.NON_COMPLIANT else None,
            ))

        score = self._compute_score(checks)
        compliant = score >= 0.8

        summary = {
            "framework": framework.value,
            "compliant": compliant,
            "score": score,
            "total_checks": len(checks),
            "compliant_count": sum(1 for c in checks if c.status == ComplianceStatus.COMPLIANT),
            "non_compliant_count": sum(1 for c in checks if c.status == ComplianceStatus.NON_COMPLIANT),
            "not_tested_count": sum(1 for c in checks if c.status == ComplianceStatus.NOT_TESTED),
        }

        return RegulatoryComplianceResult(
            framework=framework,
            compliant=compliant,
            checks=checks,
            score=score,
            summary=summary,
        )

    def _check_patterns(self, patterns: List[str], content: str) -> bool:
        for pattern in patterns:
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    return True
            except re.error:
                logger.warning("Invalid regex: %s", pattern)
        return False

    def _compute_score(self, checks: List[RegulationCheck]) -> float:
        if not checks:
            return 1.0

        status_scores = {
            ComplianceStatus.COMPLIANT: 1.0,
            ComplianceStatus.PARTIALLY_COMPLIANT: 0.5,
            ComplianceStatus.NOT_APPLICABLE: 1.0,
            ComplianceStatus.NOT_TESTED: 0.0,
            ComplianceStatus.NON_COMPLIANT: 0.0,
        }

        applicable = [c for c in checks if c.status != ComplianceStatus.NOT_APPLICABLE]
        if not applicable:
            return 1.0

        return sum(status_scores.get(c.status, 0.0) for c in applicable) / len(applicable)
