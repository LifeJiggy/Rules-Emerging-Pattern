# Compliance Module

## Overview

The Compliance module provides multi-regulatory compliance checking across four major frameworks: GDPR, HIPAA, PCI DSS, and SOX. The ComplianceOrchestrator coordinates all checkers, aggregates results, and produces consolidated compliance reports.

### Components

- **GDPRComplianceChecker** — Evaluates data processing against General Data Protection Regulation requirements (consent management, data minimization, right to erasure, breach notification)
- **HIPAAComplianceChecker** — Validates protected health information (PHI) handling per HIPAA Privacy, Security, and Breach Notification Rules
- **PCIComplianceChecker** — Assesses cardholder data environment against PCI DSS 4.0 requirements (encryption, access control, logging)
- **SOXComplianceChecker** — Checks financial reporting controls per Sarbanes-Oxley Act requirements (audit trails, segregation of duties)
- **ComplianceOrchestrator** — Coordinates multi-regulatory checks, manages check lifecycle, deduplicates overlapping requirements, and generates unified reports

## Class Diagram

```mermaid
classDiagram
    class ComplianceChecker {
        <<abstract>>
        +str name
        +str version
        +List~str~ regulations
        +check(data) CheckResult
        +get_requirements() List~Requirement~
        +get_violations(data) List~Violation~
        +validate_scope(data) bool
        -evaluate_rules(data, rules) List~RuleResult~
        -score_severity(violation) int
    }

    class GDPRComplianceChecker {
        +check(data) CheckResult
        +get_requirements() List~Requirement~
        +check_consent(processing_record) ConsentResult
        +check_data_minimization(data_collection) DataMinResult
        +check_right_to_erasure(user_request) ErasureResult
        +check_breach_notification(breach_event) BreachResult
        +check_dpia(processing_activity) DPIAResult
        +check_data_transfer(transfer_record) TransferResult
        -consent_validator ConsentValidator
        -data_inventory DataInventory
        -legal_bases LegalBasisRegistry
    }

    class HIPAAComplianceChecker {
        +check(data) CheckResult
        +get_requirements() List~Requirement~
        +check_phi_access(records) PHIAccessResult
        +check_encryption(data_store) EncryptionResult
        +check_baa(contracts) BAResult
        +check_audit_controls(system_logs) AuditResult
        +check_breach_notification(breach) BreachResult
        +check_security_policies(policies) PolicyResult
        -phi_scanner PHIScanner
        -encryption_validator EncryptionValidator
        -baa_manager BAManager
    }

    class PCIComplianceChecker {
        +check(data) CheckResult
        +get_requirements() List~Requirement~
        +check_network_security(config) NetworkResult
        +check_cardholder_data(storage) CHDResult
        +check_access_control(users) AccessResult
        +check_encryption(keys) EncryptionResult
        +check_logging(logs) LoggingResult
        +check_vulnerability_scan(scan) ScanResult
        +check_asm(procedures) ASMResult
        -network_scanner NetworkScanner
        -chd_detector CHDDetector
        -key_manager KeyManager
    }

    class SOXComplianceChecker {
        +check(data) CheckResult
        +get_requirements() List~Requirement~
        +check_access_controls(users) AccessResult
        +check_audit_trail(logs) AuditTrailResult
        +check_segregation_of_duties(roles) SoDResult
        +check_financial_reporting(reports) ReportingResult
        +check_change_management(changes) ChangeResult
        -role_analyzer RoleAnalyzer
        -audit_trail_validator AuditTrailValidator
        -financial_controls FinancialControls
    }

    class ComplianceOrchestrator {
        +List~ComplianceChecker~ checkers
        +Dict~str, object~ config
        +check(data, regulations) OrchestratedResult
        +add_checker(checker) void
        +remove_checker(name) void
        +get_applicable_regulations(data) List~str~
        +aggregate_results(results) OrchestratedResult
        +generate_report(result, format) Report
        +schedule_check(interval, data, regulations) void
        -result_aggregator ResultAggregator
        -report_generator ReportGenerator
        -overlap_detector OverlapDetector
    }

    class CheckResult {
        +str checker_name
        +bool passed
        +int score
        +List~Violation~ violations
        +List~Requirement~ requirements_checked
        +float duration_ms
        +Dict metadata
    }

    class Violation {
        +str id
        +str regulation
        +str requirement_id
        +str description
        +str severity
        +str status
        +str remediation
        +datetime detected_at
    }

    class OrchestratedResult {
        +str id
        +datetime timestamp
        +float overall_score
        +Dict~str, CheckResult~ results
        +List~Violation~ all_violations
        +List~str~ overlapping_requirements
        +Dict~str, int~ severity_distribution
        +Report generated_report
    }

    ComplianceChecker <|-- GDPRComplianceChecker
    ComplianceChecker <|-- HIPAAComplianceChecker
    ComplianceChecker <|-- PCIComplianceChecker
    ComplianceChecker <|-- SOXComplianceChecker
    ComplianceChecker --> CheckResult : returns
    CheckResult --> Violation : contains
    ComplianceOrchestrator --> ComplianceChecker : coordinates
    ComplianceOrchestrator --> OrchestratedResult : produces
    OrchestratedResult --> CheckResult : aggregates
    OrchestratedResult --> Violation : collects
```

## Quick Start

```python
from src.compliance.compliance_orchestrator import ComplianceOrchestrator
from src.compliance.gdpr_compliance import GDPRComplianceChecker
from src.compliance.hipaa_compliance import HIPAAComplianceChecker

# Initialize orchestrator
orchestrator = ComplianceOrchestrator()
orchestrator.add_checker(GDPRComplianceChecker())
orchestrator.add_checker(HIPAAComplianceChecker())

# Run compliance check
data = {
    "records": [
        {
            "type": "user_profile",
            "fields": ["name", "email", "phone", "medical_history"],
            "consent_status": "granted",
            "processing_purpose": "service_delivery"
        }
    ],
    "data_subjects": ["EU", "US"],
    "data_retention_days": 365
}

result = orchestrator.check(data, regulations=["GDPR", "HIPAA"])

# Generate report
report = orchestrator.generate_report(result, format="json")
print(report)

# Check specific requirements
if not result.passed:
    for violation in result.all_violations:
        print(f"[{violation.severity}] {violation.regulation}: {violation.description}")
        print(f"  Remediation: {violation.remediation}")
```

## Regulation Support Table

| Regulation | Domain | Jurisdiction | Requirements | Severity Tiers |
|---|---|---|---|---|
| GDPR | Data Privacy | EU/EEA | 99 articles across 11 chapters | Critical (Art 5), High (Art 17), Medium (Art 30), Low (Art 32) |
| HIPAA | Healthcare | USA | Privacy Rule, Security Rule, Breach Notification Rule | Critical (Breach), High (Encryption), Medium (BAAs), Low (Policies) |
| PCI DSS | Payment Cards | Global | 12 requirements, 6 goals, 4.0 standard | Critical (CHD), High (Network), Medium (Access), Low (Logging) |
| SOX | Financial | USA | 11 titles, Sections 302, 404, 409, 802 | Critical (Fraud), High (Controls), Medium (Audit Trail), Low (Disclosure) |

## Architecture Principles

- **Pluggable**: Add new regulation checkers without modifying existing code
- **Stateless**: Each check is independent; state is managed by the caller
- **Idempotent**: Running the same check twice produces the same result
- **Overlap-aware**: The orchestrator detects when multiple regulations require the same control and reports it
- **Severity-weighted**: Overall score is weighted by violation severity, not a simple pass/fail count

## Configuration

```python
COMPLIANCE_CONFIG = {
    "gdpr": {
        "consent_required": True,
        "data_minimization_enabled": True,
        "max_retention_days": 365,
        "breach_notification_hours": 72
    },
    "hipaa": {
        "phi_detection_strict": True,
        "encryption_required": "AES-256",
        "baa_required": True,
        "audit_log_retention_days": 1825
    },
    "pci": {
        "version": "4.0",
        "chd_scan_enabled": True,
        "vulnerability_scan_frequency_days": 90,
        "asm_frequency_days": 365
    },
    "sox": {
        "audit_trail_required": True,
        "segregation_of_duties": True,
        "review_frequency_days": 90
    },
    "orchestrator": {
        "parallel_execution": True,
        "max_concurrent_checkers": 4,
        "timeout_per_checker_ms": 30000,
        "report_formats": ["json", "html", "pdf"]
    }
}
```

## Dependencies

- `pydantic` — Data validation and schema enforcement
- `cryptography` — Encryption validation
- `phoner` — Phone/email regex for PII detection
- `jinja2` — HTML report templates
- `weasyprint` — PDF report generation