# Compliance Integration

## System Integration Overview

The Compliance module integrates with the API layer (incoming check requests), Validation module (data quality checks), and Privacy module (consent and data subject rights). Each integration follows a defined contract.

```mermaid
graph TB
    subgraph "External Callers"
        API["API Module<br/>/v1/compliance/check"]
        SCHED["Scheduler<br/>Cron / Celery Beat"]
        MANUAL["Manual Trigger<br/>Admin Dashboard"]
    end

    subgraph "Compliance Module"
        ORCH["ComplianceOrchestrator"]
        G["GDPRChecker"]
        H["HIPIAChecker"]
        P["PCIChecker"]
        S["SOXChecker"]
        AGG["ResultAggregator"]
        RPT["ReportGenerator"]
        OVER["OverlapDetector"]
    end

    subgraph "Internal Dependencies"
        VAL["Validation Module<br/>Data Quality Checks"]
        PRIV["Privacy Module<br/>Consent / Erasure"]
        CORE["Core Engine<br/>Rule Evaluation"]
        CACHE["Cache Layer<br/>Redis"]
    end

    subgraph "Data Stores"
        DB["PostgreSQL<br/>Check History"]
        S3["S3 / Object Store<br/>Reports Archive"]
        ES["Elasticsearch<br/>Audit Logs"]
        KM["Keycloak / IAM<br/>User Permissions"]
    end

    subgraph "Notification"
        EMAIL["Email Service<br/>Violation Alerts"]
        SLACK["Slack Webhook<br/>Real-time Alerts"]
        PAGER["PagerDuty<br/>Critical Escalation"]
    end

    API --> ORCH
    SCHED --> ORCH
    MANUAL --> ORCH

    ORCH --> G
    ORCH --> H
    ORCH --> P
    ORCH --> S
    ORCH --> AGG
    ORCH --> RPT
    ORCH --> OVER

    G --> VAL
    G --> PRIV
    G --> CORE

    H --> VAL
    H --> CORE

    P --> VAL
    P --> CORE

    S --> VAL
    S --> CORE

    ORCH --> DB
    RPT --> S3
    ORCH --> ES
    ORCH --> KM

    AGG --> CACHE

    G --> SLACK
    H --> SLACK
    P --> EMAIL
    S --> EMAIL
    OVER --> PAGER

    style ORCH fill:#1565C0,color:#fff
    style G fill:#1976D2,color:#fff
    style H fill:#388E3C,color:#fff
    style P fill:#F57C00,color:#fff
    style S fill:#7B1FA2,color:#fff
    style API fill:#0D47A1,color:#fff
    style VAL fill:#4CAF50,color:#fff
    style PRIV fill:#FF9800,color:#fff
    style PAGER fill:#C62828,color:#fff
```

## API to Compliance Integration Sequence

When a compliance check is triggered via the API, the request flows through the ComplianceOrchestrator, which coordinates all checkers and returns a structured result.

```mermaid
sequenceDiagram
    participant Client
    participant API as API Handler
    participant Auth as APIAuth
    participant Orch as ComplianceOrchestrator
    participant GDPR as GDPRComplianceChecker
    participant HIPAA as HIPAAComplianceChecker
    participant PCI as PCIComplianceChecker
    participant SOX as SOXComplianceChecker
    participant DB as PostgreSQL
    participant S3 as Report Store
    participant Notify as Notification

    Client->>API: POST /v1/compliance/check
    Note over Client,API: {"data": {...}, "regulations": ["GDPR", "HIPAA"]}

    API->>Auth: authenticate(request)
    Auth-->>API: AuthResult(user=compliance_officer, roles=["admin"])

    API->>API: authorize("compliance:check", user)
    API->>API: validate_request_body(data, regulations)

    API->>Orch: check(data, regulations=["GDPR", "HIPAA"])

    rect rgb(230, 242, 255)
        Note over Orch,Orch: Orchestration
        Orch->>Orch: validate_scope(data)
        Orch->>Orch: filter_checkers(["GDPR", "HIPAA"])
        Orch-->>Orch: checkers = [GDPRChecker, HIPAAChecker]
    end

    par Run GDPR and HIPAA in parallel
        Orch->>GDPR: check(data)

        rect rgb(255, 235, 200)
            Note over GDPR,GDPR: GDPR Evaluation
            GDPR->>GDPR: load_requirements("GDPR", "2.0")
            GDPR->>GDPR: evaluate_rules(data)
            GDPR->>GDPR: calculate_score()
            GDPR-->>Orch: CheckResult(passed=true, score=92, violations=[...])
        end

        Orch->>HIPAA: check(data)

        rect rgb(200, 255, 200)
            Note over HIPAA,HIPAA: HIPAA Evaluation
            HIPAA->>HIPAA: load_requirements("HIPAA", "2.0")
            HIPAA->>HIPAA: scan_for_phi(data)
            HIPAA->>HIPAA: evaluate_rules(data)
            HIPAA->>HIPAA: calculate_score()
            HIPAA-->>Orch: CheckResult(passed=false, score=65, violations=[...])
        end
    end

    rect rgb(245, 245, 255)
        Note over Orch,Orch: Aggregation
        Orch->>Orch: aggregate([gdrp_res, hipaa_res])
        Orch->>Orch: detect_overlaps([gdrp_res, hipaa_res])
        Orch->>Orch: calculate_overall_score(92, 65)
        Orch-->>Orch: OrchestratedResult(overall_score=78.5)
    end

    Orch->>DB: store_check_history(orchestrated_result)
    DB-->>Orch: stored

    Orch->>Orch: check_alert_thresholds(orchestrated_result)

    alt Score < 70
        Orch->>Notify: send_alert("Compliance score below threshold: 65")
        Notify-->>Orch: alert sent
    end

    Orch->>S3: archive_report(orchestrated_result)
    S3-->>Orch: archived

    Orch-->>API: OrchestratedResult
    API-->>Client: 200 OK

    Note over Client,Client: Response:
    Note over Client,Client: {
    Note over Client,Client:   "overall_score": 78.5,
    Note over Client,Client:   "per_regulation": {...},
    Note over Client,Client:   "violations": [...],
    Note over Client,Client:   "report_url": "/reports/abc-123.pdf"
    Note over Client,Client: }
```

## Validation to Compliance Integration

The Validation module pre-processes data before compliance checks, ensuring data quality and completeness. This prevents false positives from malformed input.

```mermaid
sequenceDiagram
    participant Comp as ComplianceOrchestrator
    participant Valid as Validation Module
    participant Schema as Schema Validator
    participant Rule as Validation Rules
    participant Checker as ComplianceChecker

    Comp->>Valid: validate_input(data, regulations)

    rect rgb(230, 242, 255)
        Note over Valid,Rule: Data Quality Checks
        Valid->>Schema: validate_schema(data, compliance_schema)
        Schema->>Schema: check_required_fields(data)
        Schema->>Schema: check_field_types(data)
        Schema-->>Valid: SchemaResult(valid=true, errors=[])
    end

    Valid->>Rule: apply_validation_rules(data, regulations)

    Rule->>Rule: check_data_completeness()
    Note over Rule,Rule: All required fields present for selected regulations

    Rule->>Rule: check_data_format()
    Note over Rule,Rule: Emails valid, dates in ISO 8601, phones formatted

    Rule->>Rule: check_data_consistency()
    Note over Rule,Rule: No contradictory fields (e.g., "consent: none" + "data: medical")

    Rule-->>Valid: ValidationResult(passed=true, warnings=["Field 'phone' format normalized"])

    Valid-->>Comp: ValidationResult(passed=true, data=cleaned_data)

    alt Validation Failed
        Comp-->>Comp: return early with validation errors
        Note over Comp,Comp: Compliance check not executed
    end

    Comp->>Checker: check(cleaned_data)
    Checker-->>Comp: CheckResult
```

## Privacy to GDPR Integration

The Privacy module handles consent management, data subject requests (DSARs), and right to erasure. The GDPR checker queries the privacy module for consent records and erasure status.

```mermaid
sequenceDiagram
    participant GDPR as GDPRComplianceChecker
    participant Privacy as Privacy Module
    participant Consent as ConsentManager
    participant DSAR as DSARHandler
    participant Erasure as ErasureManager
    participant DB as Database

    GDPR->>GDPR: check_consent(data.records)

    GDPR->>Privacy: verify_consent(record_id, purpose)

    Privacy->>Consent: get_consent_status(user_id, processing_purpose)
    Consent->>DB: SELECT * FROM consents WHERE user_id = ? AND purpose = ?
    DB-->>Consent: {status: "granted", granted_at: "2026-01-15", expires_at: "2027-01-15"}
    Consent-->>Privacy: ConsentRecord(status="granted", valid=true)

    Privacy->>Consent: check_consent_validity(consent_record)
    Consent->>Consent: is_within_validity_period(consent_record)
    Consent->>Consent: has_been_withdrawn(consent_record)
    Consent-->>Privacy: ValidityResult(valid=true, days_remaining=175)

    Privacy-->>GDPR: ConsentResult(valid=true, consent_record={...})

    GDPR->>GDPR: record_consent_status(record_id, valid=true)

    GDPR->>GDPR: check_right_to_erasure(data.erasure_requests)

    GDPR->>DSAR: get_pending_erasure_requests()
    DSAR->>DB: SELECT * FROM erasure_requests WHERE status = 'pending'
    DB-->>DSAR: [{id: 1, user_id: 123, requested_at: "2026-07-20"}, ...]

    DSAR-->>GDPR: [ErasureRequest(id=1, user=123, days_pending=4)]

    GDPR->>GDPR: evaluate_erasure_compliance(request)
    Note over GDPR,GDPR: Art 17 requires processing within 30 days
    Note over GDPR,GDPR: Request #1: 4 days pending → within SLA → PASS

    GDPR->>Erasure: check_erasure_completeness(user_id=123)
    Erasure->>DB: Verify data removal across all systems
    DB-->>Erasure: {primary_db: true, cache: true, backups: false, logs: true}
    Erasure-->>GDPR: ErasureResult(complete=false, remaining=["backups"])
    Note over GDPR,GDPR: Backups require Art 17(3)(a) exemption or separate erasure

    GDPR->>GDPR: build_violation("GDPR-ART17", "Backup data not erased within SLA")
```

## Report Distribution Flow

```mermaid
sequenceDiagram
    participant Orch as ComplianceOrchestrator
    participant RPT as ReportGenerator
    participant S3 as Report Store
    participant Email as Email Service
    participant Slack as Slack Webhook
    participant Archive as Long-term Archive

    Orch->>RPT: generate_report(orchestrated_result, format="pdf")

    RPT->>RPT: build_report_data(result)
    Note over RPT,RPT: Header: Executive Summary
    Note over RPT,RPT: Section 1: Overall Score + Trend
    Note over RPT,RPT: Section 2: Per-Regulation Breakdown
    Note over RPT,RPT: Section 3: Violation Details (by severity)
    Note over RPT,RPT: Section 4: Overlapping Requirements
    Note over RPT,RPT: Section 5: Remediation Plan
    Note over RPT,RPT: Appendix: Raw Data, Config, Timestamps

    RPT->>RPT: render_html(template="compliance_report.html")
    RPT->>RPT: convert_to_pdf(html)
    RPT-->>Orch: Report(format="pdf", content=binary, page_count=24)

    Orch->>S3: upload_report(report, path="reports/2026/07/check-abc123.pdf")
    S3-->>Orch: URL: https://reports.example.com/check-abc123.pdf

    alt Score < 70 OR Critical Violations
        Orch->>Email: send_report(recipients=["compliance@example.com", "ciso@example.com"], report)
        Email-->>Orch: sent

        Orch->>Slack: post_message("#compliance-alerts", "Compliance check failed: 65/100")
        Slack-->>Orch: posted
    else Passing Score
        Orch->>Email: send_summary(recipients=["compliance@example.com"], report_url)
        Email-->>Orch: sent
    end

    Orch->>Archive: archive_report(report, retention_years=7)
    Archive-->>Orch: archived
```

## Configuration Integration

```python
COMPLIANCE_INTEGRATION_CONFIG = {
    "api": {
        "endpoint": "/v1/compliance",
        "auth_required": True,
        "rate_limit": 10,
        "timeout_ms": 60000
    },
    "validation": {
        "enabled": True,
        "strict_mode": False,
        "pre_checks": ["schema", "format", "consistency"]
    },
    "privacy": {
        "consent_api_url": "http://privacy-service:8000/v1/consent",
        "dsar_api_url": "http://privacy-service:8000/v1/dsar",
        "erasure_api_url": "http://privacy-service:8000/v1/erasure",
        "timeout_ms": 5000
    },
    "notifications": {
        "email": {
            "enabled": True,
            "recipients": ["compliance-team@example.com"],
            "critical_recipients": ["ciso@example.com", "legal@example.com"],
            "threshold_score": 70
        },
        "slack": {
            "enabled": True,
            "webhook_url": "https://hooks.slack.com/services/xxx",
            "channel": "#compliance-alerts",
            "notify_on": ["critical_violation", "score_below_70"]
        },
        "pagerduty": {
            "enabled": True,
            "integration_key": "pd-key-xxx",
            "severity_threshold": "CRITICAL"
        }
    },
    "storage": {
        "history": {
            "backend": "postgresql",
            "retention_days": 1825
        },
        "reports": {
            "backend": "s3",
            "bucket": "compliance-reports",
            "prefix": "reports/",
            "retention_years": 7
        },
        "audit_log": {
            "backend": "elasticsearch",
            "index_pattern": "compliance-audit-*"
        }
    }
}
```

## Integration Health Check

```mermaid
flowchart TD
    Start(["Integration Health"]) --> CheckDeps["Check All Dependencies"]

    CheckDeps --> APIDep["API Module<br/>Reachable?"]
    CheckDeps --> ValidDep["Validation Module<br/>Reachable?"]
    CheckDeps --> PrivacyDep["Privacy Module<br/>Reachable?"]
    CheckDeps --> DBDep["Database<br/>Connected?"]
    CheckDeps --> S3Dep["Report Store<br/>Writeable?"]

    APIDep -->|No| Degraded["Degraded: API unavailable"]
    ValidDep -->|No| Warning1["Warning: Validation unavailable<br/>Compliance checks continue without pre-validation"]
    PrivacyDep -->|No| Warning2["Warning: Privacy unavailable<br/>GDPR consent checks disabled"]
    DBDep -->|No| Critical1["Critical: Database unavailable<br/>History not stored"]
    S3Dep -->|No| Warning3["Warning: Report store unavailable<br/>Reports not archived"]

    APIDep -->|Yes| AllGood["Checking next..."]
    ValidDep -->|Yes| AllGood
    PrivacyDep -->|Yes| AllGood
    DBDep -->|Yes| AllGood
    S3Dep -->|Yes| AllGood

    style Start fill:#1565C0,color:#fff
    style Degraded fill:#F57F17,color:#fff
    style Warning1 fill:#F57F17,color:#fff
    style Warning2 fill:#F57F17,color:#fff
    style Critical1 fill:#C62828,color:#fff
    style Warning3 fill:#F57F17,color:#fff
```