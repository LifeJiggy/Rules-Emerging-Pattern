# Compliance Architecture

## System Architecture Flowchart

Every compliance check flows through the ComplianceOrchestrator, which dispatches to individual regulation checkers, aggregates results, and generates reports. The flowchart below shows the complete lifecycle.

```mermaid
flowchart TD
    Start(["Compliance Check Requested"]) --> IdentifyData["Identify Data Scope<br/>Records, Subjects, Jurisdictions"]

    IdentifyData --> ClassifyData["Classify Data Types<br/>PII, PHI, CHD, Financial"]

    ClassifyData --> DetermineRegs["Determine Applicable<br/>Regulations"]

    DetermineRegs --> RegDecision{"Which Regulations<br/>Apply?"}

    RegDecision -->|PII + EU| AddGDPR["Include GDPR"]
    RegDecision -->|PHI + USA| AddHIPAA["Include HIPAA"]
    RegDecision -->|CHD| AddPCI["Include PCI DSS"]
    RegDecision -->|Financial + USA| AddSOX["Include SOX"]
    RegDecision -->|Multiple| AddAll["Include All Applicable"]

    AddGDPR --> InitCheckers["Initialize Checkers<br/>with Config"]
    AddHIPAA --> InitCheckers
    AddPCI --> InitCheckers
    AddSOX --> InitCheckers
    AddAll --> InitCheckers

    InitCheckers --> OrchestratorCheck["Orchestrator.check()"]

    OrchestratorCheck --> Parallel{"Parallel<br/>Execution?"}

    Parallel -->|Yes| RunGDPR_P["Run GDPR Checker"]
    Parallel -->|Yes| RunHIPAA_P["Run HIPAA Checker"]
    Parallel -->|Yes| RunPCI_P["Run PCI Checker"]
    Parallel -->|Yes| RunSOX_P["Run SOX Checker"]

    Parallel -->|No| SequentialRun["Run Checkers Sequentially"]

    SequentialRun --> RunGDPR_S["Run GDPR Checker"]
    RunGDPR_S --> RunHIPAA_S["Run HIPAA Checker"]
    RunHIPAA_S --> RunPCI_S["Run PCI Checker"]
    RunPCI_S --> RunSOX_S["Run SOX Checker"]

    RunGDPR_P --> GDPRResult{"GDPR<br/>Result"}
    RunHIPAA_P --> HIPAResult{"HIPAA<br/>Result"}
    RunPCI_P --> PCIResult{"PCI<br/>Result"}
    RunSOX_P --> SOXResult{"SOX<br/>Result"}

    RunGDPR_S --> GDPRResult
    RunHIPAA_S --> HIPAResult
    RunPCI_S --> PCIResult
    RunSOX_S --> SOXResult

    GDPRResult -->|Pass| CollectGDPR["Collect GDPR Results"]
    GDPRResult -->|Violations| CollectGDPR
    HIPAResult -->|Pass| CollectHIPAA["Collect HIPAA Results"]
    HIPAResult -->|Violations| CollectHIPAA
    PCIResult -->|Pass| CollectPCI["Collect PCI Results"]
    PCIResult -->|Violations| CollectPCI
    SOXResult -->|Pass| CollectSOX["Collect SOX Results"]
    SOXResult -->|Violations| CollectSOX

    CollectGDPR --> DetectOverlaps["Detect Overlapping<br/>Requirements"]
    CollectHIPAA --> DetectOverlaps
    CollectPCI --> DetectOverlaps
    CollectSOX --> DetectOverlaps

    DetectOverlaps --> AggregateResults["Aggregate Results<br/>Score, Violations, Overlaps"]

    AggregateResults --> ScoreCalc{"Calculate<br/>Overall Score"}

    ScoreCalc --> Score["Weighted Score<br/>based on severity"]

    Score --> GenerateReport["Generate Report<br/>JSON / HTML / PDF"]

    GenerateReport --> ReportType{"Report<br/>Format?"}

    ReportType -->|JSON| BuildJSON["Serialize to JSON"]
    ReportType -->|HTML| BuildHTML["Render Jinja2 Template"]
    ReportType -->|PDF| BuildPDF["Render + Convert<br/>to PDF with WeasyPrint"]

    BuildJSON --> ReturnResult["Return OrchestratedResult"]
    BuildHTML --> ReturnResult
    BuildPDF --> ReturnResult

    ReturnResult --> End(["Compliance Check Complete"])

    style Start fill:#1565C0,color:#fff
    style End fill:#2E7D32,color:#fff
    style RunGDPR_P fill:#1976D2,color:#fff
    style RunHIPAA_P fill:#388E3C,color:#fff
    style RunPCI_P fill:#F57C00,color:#fff
    style RunSOX_P fill:#7B1FA2,color:#fff
    style BuildJSON fill:#F57F17,color:#fff
    style BuildHTML fill:#F57F17,color:#fff
    style BuildPDF fill:#F57F17,color:#fff
```

## Class Diagram

```mermaid
classDiagram
    class ComplianceOrchestrator {
        -Dict~str, ComplianceChecker~ checkers
        -Dict config
        -ResultAggregator aggregator
        -ReportGenerator report_gen
        -OverlapDetector overlap_detector
        +__init__(config) void
        +add_checker(name, checker) void
        +remove_checker(name) void
        +check(data, regulations) OrchestratedResult
        +check_all(data) OrchestratedResult
        +get_applicable_regulations(data) List~str~
        +aggregate_results(results) OrchestratedResult
        +generate_report(result, format) Report
        +schedule_check(interval, data, regulations) SchedulerJob
        +cancel_scheduled_check(job_id) void
        +list_available_checkers() List~str~
        +get_checker_info(name) Dict
        -validate_data(data) bool
        -filter_checkers(regulations) List~ComplianceChecker~
        -run_checkers(checkers, data) Dict~str, CheckResult~
        -calculate_overall_score(results) float
        -build_report_data(orchestrated_result) Dict
    }

    class ComplianceChecker {
        <<abstract>>
        #str name
        #str version
        #List~str~ supported_regulations
        #Dict config
        +__init__(config) void
        +check(data) CheckResult*
        +get_requirements() List~Requirement~*
        +validate_scope(data) bool
        +get_regulation() str
        +configure(config) void
        -evaluate_rules(data, rules) List~RuleResult~
        -calculate_score(rule_results) float
        -build_violations(rule_results) List~Violation~
        -score_severity(violation) int
    }

    class Requirement {
        +str id
        +str regulation
        +str category
        +str description
        +bool mandatory
        +List~str~ depends_on
        +str severity_if_violated
        +validate(data) ValidationResult
    }

    class Violation {
        +str id
        +str requirement_id
        +str regulation
        +str description
        +str severity
        +str category
        +str affected_entity
        +str remediation
        +datetime detected_at
        +Dict evidence
        +to_dict() Dict
    }

    class CheckResult {
        +str checker_name
        +str regulation
        +bool passed
        +int score
        +List~Requirement~ requirements_checked
        +List~Violation~ violations
        +int total_requirements
        +int passed_requirements
        +int failed_requirements
        +float duration_ms
        +Dict metadata
        +to_dict() Dict
        +merge(other) CheckResult
    }

    class OrchestratedResult {
        +str id
        +datetime timestamp
        +float overall_score
        +Dict~str, CheckResult~ per_regulation
        +List~Violation~ all_violations
        +int total_violations
        +int critical_violations
        +int high_violations
        +int medium_violations
        +int low_violations
        +List~str~ overlapping_requirements
        +Dict~str, int~ severity_distribution
        +Report report
        +bool passed
        +to_dict() Dict
        +to_json() str
        +summary() str
    }

    class Report {
        +str title
        +str format
        +str content
        +datetime generated_at
        +int page_count
        +List~str~ sections
        +save(path) void
        +send(recipients) void
    }

    class ResultAggregator {
        +aggregate(results) OrchestratedResult
        +merge_results(r1, r2) CheckResult
        +calculate_weighted_score(results) float
        -weight_by_severity(violations) float
    }

    class OverlapDetector {
        +find_overlaps(results) List~str~
        +deduplicate_violations(violations) List~Violation~
        -regulatory_mapping Dict
        -build_overlap_matrix() Matrix
    }

    class ReportGenerator {
        +generate(result, format) Report
        +generate_json(result) Report
        +generate_html(result, template) Report
        +generate_pdf(result, template) Report
        -html_renderer HTMLRenderer
        -pdf_converter PDFConverter
        -template_engine TemplateEngine
    }

    ComplianceOrchestrator --> ComplianceChecker : coordinates
    ComplianceOrchestrator --> ResultAggregator : uses
    ComplianceOrchestrator --> ReportGenerator : uses
    ComplianceOrchestrator --> OverlapDetector : uses
    ComplianceOrchestrator --> OrchestratedResult : produces
    ComplianceChecker --> CheckResult : returns
    CheckResult --> Requirement : references
    CheckResult --> Violation : contains
    OrchestratedResult --> CheckResult : aggregates
    OrchestratedResult --> Violation : collects
    OrchestratedResult --> Report : includes
    ComplianceOrchestrator --> ComplianceChecker : dispatches to
```

## Multi-Regulatory Orchestration

```mermaid
graph TB
    subgraph "Input Data"
        D1["System Configuration"]
        D2["Data Flow Map"]
        D3["User Records"]
        D4["Access Logs"]
        D5["Encryption Keys"]
        D6["Third-party Contracts"]
    end

    subgraph "Orchestrator"
        ORCH["ComplianceOrchestrator"]
        FILTER["Regulation Filter"]
        DISPATCH["Dispatch to Checkers"]
        COLLECT["Collect Results"]
        OVERLAP["Overlap Detection"]
        SCORE["Score Calculation"]
        REPORT["Report Generation"]
    end

    subgraph "Checker Layer"
        G["GDPR<br/>ComplianceChecker"]
        H["HIPAA<br/>ComplianceChecker"]
        P["PCI<br/>ComplianceChecker"]
        S["SOX<br/>ComplianceChecker"]
    end

    subgraph "Checker Internals"
        G1["Consent Check"]
        G2["Data Minimization"]
        G3["Right to Erasure"]
        G4["Breach Notification"]
        G5["Data Transfer"]

        H1["PHI Access Control"]
        H2["Encryption Validation"]
        H3["BAA Verification"]
        H4["Audit Controls"]
        H5["Security Policies"]

        P1["Network Security"]
        P2["CHD Protection"]
        P3["Access Control"]
        P4["Encryption Keys"]
        P5["Logging/Monitoring"]
        P6["Vulnerability Mgmt"]
        P7["ASM Testing"]

        S1["Access Controls"]
        S2["Audit Trail"]
        S3["Segregation of Duties"]
        S4["Financial Reporting"]
        S5["Change Management"]
    end

    D1 --> ORCH
    D2 --> ORCH
    D3 --> ORCH
    D4 --> ORCH
    D5 --> ORCH
    D6 --> ORCH

    ORCH --> FILTER
    FILTER --> DISPATCH

    DISPATCH --> G
    DISPATCH --> H
    DISPATCH --> P
    DISPATCH --> S

    G --> G1
    G --> G2
    G --> G3
    G --> G4
    G --> G5

    H --> H1
    H --> H2
    H --> H3
    H --> H4
    H --> H5

    P --> P1
    P --> P2
    P --> P3
    P --> P4
    P --> P5
    P --> P6
    P --> P7

    S --> S1
    S --> S2
    S --> S3
    S --> S4
    S --> S5

    G1 --> COLLECT
    G2 --> COLLECT
    G3 --> COLLECT
    G4 --> COLLECT
    G5 --> COLLECT

    H1 --> COLLECT
    H2 --> COLLECT
    H3 --> COLLECT
    H4 --> COLLECT
    H5 --> COLLECT

    P1 --> COLLECT
    P2 --> COLLECT
    P3 --> COLLECT
    P4 --> COLLECT
    P5 --> COLLECT
    P6 --> COLLECT
    P7 --> COLLECT

    S1 --> COLLECT
    S2 --> COLLECT
    S3 --> COLLECT
    S4 --> COLLECT
    S5 --> COLLECT

    COLLECT --> OVERLAP
    OVERLAP --> SCORE
    SCORE --> REPORT

    style ORCH fill:#1565C0,color:#fff
    style G fill:#1976D2,color:#fff
    style H fill:#388E3C,color:#fff
    style P fill:#F57C00,color:#fff
    style S fill:#7B1FA2,color:#fff
    style REPORT fill:#2E7D32,color:#fff
```

## Checker Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Idle : checker registered

    Idle --> ValidatingScope : check() called
    ValidatingScope --> DataInScope : data matches regulation scope
    ValidatingScope --> OutOfScope : data does not match
    OutOfScope --> Idle : return skip result

    DataInScope --> LoadingRules : load requirement definitions
    LoadingRules --> RulesLoaded : rules loaded from registry
    RulesLoaded --> Evaluating : evaluate each rule against data

    Evaluating --> RulePassed : condition satisfied
    Evaluating --> RuleFailed : condition violated

    RulePassed --> MoreRules : more rules to check
    RuleFailed --> MoreRules
    MoreRules --> Evaluating : next rule

    MoreRules --> AllEvaluated : no more rules

    AllEvaluated --> Scoring : calculate compliance score
    Scoring --> ScoreCalculated : weighted severity score

    ScoreCalculated --> BuildingViolations : collect failed rules
    BuildingViolations --> ViolationsBuilt : violation list created

    ViolationsBuilt --> BuildingResult : construct CheckResult
    BuildingResult --> ResultReady : CheckResult complete

    ResultReady --> Reporting : return to orchestrator
    Reporting --> Idle : orchestrator collects result

    note right of Idle : Checker ready for<br/>next invocation
    note right of Evaluating : Configurable timeout<br/>per rule evaluation
```

## Deployment Topology

```mermaid
graph LR
    subgraph "Compliance Service"
        API_G["API Gateway"]
        ORCH["Orchestrator<br/>Container"]
        G["GDPR Checker<br/>Container"]
        H["HIPAA Checker<br/>Container"]
        P["PCI Checker<br/>Container"]
        S["SOX Checker<br/>Container"]
        RPT["Report Generator<br/>Container"]
    end

    subgraph "Data Stores"
        REDIS["Redis Cache<br/>Rule Definitions"]
        PG["PostgreSQL<br/>Check History"]
        S3["S3 Bucket<br/>Generated Reports"]
    end

    subgraph "External Integrations"
        LEGAL["Legal Database<br/>Regulation Updates"]
        NOTIFY["Notification Service<br/>Alert on Violations"]
        AUDIT["External Auditor<br/>API Access"]
    end

    API_G --> ORCH
    ORCH --> G
    ORCH --> H
    ORCH --> P
    ORCH --> S
    ORCH --> RPT

    G --> REDIS
    H --> REDIS
    P --> REDIS
    S --> REDIS

    ORCH --> PG
    RPT --> S3

    ORCH --> LEGAL
    ORCH --> NOTIFY
    API_G --> AUDIT

    style ORCH fill:#1565C0,color:#fff
    style G fill:#1976D2,color:#fff
    style H fill:#388E3C,color:#fff
    style P fill:#F57C00,color:#fff
    style S fill:#7B1FA2,color:#fff
```