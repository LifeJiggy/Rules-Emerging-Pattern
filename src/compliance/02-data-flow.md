# Compliance Data Flow

## Multi-Regulation Compliance Check Sequence

The ComplianceOrchestrator coordinates all regulation checkers in a structured pipeline. Each checker runs independently (in parallel when configured) and the orchestrator aggregates results.

```mermaid
sequenceDiagram
    participant Client
    participant Orch as ComplianceOrchestrator
    participant GDPR as GDPRComplianceChecker
    participant HIPAA as HIPAAComplianceChecker
    participant PCI as PCIComplianceChecker
    participant SOX as SOXComplianceChecker
    participant Agg as ResultAggregator
    participant Overlap as OverlapDetector
    participant Report as ReportGenerator

    Client->>Orch: check(data, regulations=["GDPR", "HIPAA", "PCI", "SOX"])

    rect rgb(230, 242, 255)
        Note over Orch,Orch: Validation Phase
        Orch->>Orch: validate_data_structure(data)
        Orch->>Orch: check_required_fields(data)
        Orch->>Orch: deterime_applicable_regulations(data)
        Orch-->>Orch: regulations = ["GDPR", "HIPAA", "PCI", "SOX"]
    end

    rect rgb(200, 255, 200)
        Note over Orch,Orch: Dispatch Phase
        Orch->>Orch: filter_checkers(["GDPR", "HIPAA", "PCI", "SOX"])
        Orch-->>Orch: checkers = [g, h, p, s]

        par Parallel Execution
            Orch->>GDPR: check(data)
            Orch->>HIPAA: check(data)
            Orch->>PCI: check(data)
            Orch->>SOX: check(data)
        end
    end

    rect rgb(255, 235, 200)
        Note over GDPR,GDPR: GDPR Check
        GDPR->>GDPR: validate_scope(data)
        GDPR->>GDPR: load_requirements()
        GDPR->>GDPR: check_consent(data.records)
        GDPR->>GDPR: check_data_minimization(data.records)
        GDPR->>GDPR: check_right_to_erasure(data)
        GDPR->>GDPR: check_breach_notification(data)
        GDPR->>GDPR: check_data_transfer(data)
        GDPR->>GDPR: calculate_score()
        GDPR-->>Orch: CheckResult(passed=false, score=72, violations=[...])
    end

    rect rgb(245, 245, 255)
        Note over HIPAA,HIPAA: HIPAA Check
        HIPAA->>HIPAA: validate_scope(data)
        HIPAA->>HIPAA: scan_for_phi(data.records)
        HIPAA->>HIPAA: check_encryption(data)
        HIPAA->>HIPAA: verify_baas(data.contracts)
        HIPAA->>HIPAA: check_audit_controls(data.logs)
        HIPAA->>HIPAA: check_security_policies(data)
        HIPAA-->>Orch: CheckResult(passed=true, score=95, violations=[])
    end

    rect rgb(255, 255, 230)
        Note over PCI,PCI: PCI Check
        PCI->>PCI: validate_scope(data)
        PCI->>PCI: scan_for_chd(data.records)
        PCI->>PCI: check_network_security(data.network)
        PCI->>PCI: check_access_controls(data.users)
        PCI->>PCI: check_encryption_keys(data.keys)
        PCI->>PCI: check_logging(data.logs)
        PCI->>PCI: check_vulnerability_scan(data)
        PCI-->>Orch: CheckResult(passed=false, score=61, violations=[...])
    end

    rect rgb(230, 255, 230)
        Note over SOX,SOX: SOX Check
        SOX->>SOX: validate_scope(data)
        SOX->>SOX: check_access_controls(data.users)
        SOX->>SOX: check_audit_trail(data.logs)
        SOX->>SOX: check_segregation_of_duties(data.roles)
        SOX->>SOX: check_financial_reports(data.reports)
        SOX-->>Orch: CheckResult(passed=true, score=88, violations=[...])
    end

    rect rgb(255, 235, 235)
        Note over Orch,Report: Aggregation Phase
        Orch->>Agg: aggregate([gdrp_res, hipaa_res, pci_res, sox_res])

        Agg->>Agg: merge_results()
        Agg->>Agg: calculate_weighted_score()
        Agg-->>Orch: OrchestratedResult(overall_score=79, violations=[...])

        Orch->>Overlap: find_overlaps(orchestrated_result)
        Overlap->>Overlap: check_cross_regulation_requirements()
        Overlap-->>Orch: {"PCI req 3.4 ↔ GDPR Art 32": "Encryption at rest requirements overlap"}

        Orch->>Orch: categorize_severities(violations)

        Orch->>Report: generate(result, format="json")
        Report->>Report: build_report_data(result)
        Report->>Report: serialize_json(data)
        Report-->>Orch: Report(format="json", content="...")
    end

    Orch-->>Client: OrchestratedResult
    Note over Client,Client: Overall: 79/100, 14 violations (3 critical, 5 high, 4 medium, 2 low)
```

## Cross-Regulation Overlap Detection

```mermaid
flowchart TD
    Start(["Overlap Detection"]) --> CollectRegs["Collect All Requirements<br/>from all checkers"]

    CollectRegs --> BuildMatrix["Build Requirement<br/>Overlap Matrix"]

    BuildMatrix --> CheckPair{"Check Each<br/>Pair of Regulations?"}

    CheckPair -->|GDPR vs HIPAA| GDPR_HIPAA{"Overlapping<br/>Requirements?"}

    GDPR_HIPAA -->|Yes| O1["Log: Art 32 (GDPR) ↔164.312(a)(2)(iv) (HIPAA)<br/>Both require encryption of personal data"]

    CheckPair -->|GDPR vs PCI| GDPR_PCI{"Overlapping<br/>Requirements?"}
    GDPR_PCI -->|Yes| O2["Log: Art 5(1)(c) (GDPR) ↔ Req 3.1 (PCI)<br/>Both require data minimization / retention limits"]

    CheckPair -->|HIPAA vs PCI| HIPAA_PCI{"Overlapping<br/>Requirements?"}
    HIPAA_PCI -->|Yes| O3["Log: 164.312(a)(1) (HIPAA) ↔ Req 7.1 (PCI)<br/>Both require access control with need-to-know"]

    CheckPair -->|SOX vs PCI| SOX_PCI{"Overlapping<br/>Requirements?"}
    SOX_PCI -->|Yes| O4["Log: §302 (SOX) ↔ Req 10.2 (PCI)<br/>Both require audit trails for financial/card data"]

    CheckPair -->|SOX vs HIPAA| SOX_HIPAA{"Overlapping<br/>Requirements?"}
    SOX_HIPAA -->|Yes| O5["Log: §404 (SOX) ↔ 164.312(b) (HIPAA)<br/>Both require audit controls"]

    CheckPair -->|SOX vs GDPR| SOX_GDPR{"Overlapping<br/>Requirements?"}
    SOX_GDPR -->|Yes| O6["Log: §802 (SOX) ↔ Art 30 (GDPR)<br/>Both require records of processing activities"]

    O1 --> Dedupe["Deduplicate Violations<br/>Map to Combined Requirements"]
    O2 --> Dedupe
    O3 --> Dedupe
    O4 --> Dedupe
    O5 --> Dedupe
    O6 --> Dedupe

    Dedupe --> ReduceCount["Reduce Violation Count<br/>from overlapping sources"]
    ReduceCount --> AddNote["Add Cross-Regulation<br/>Notes to Report"]
    AddNote --> ReturnOverlaps["Return Overlap Map"]

    GDPR_HIPAA -->|No| CheckPair
    GDPR_PCI -->|No| CheckPair
    HIPAA_PCI -->|No| CheckPair
    SOX_PCI -->|No| CheckPair
    SOX_HIPAA -->|No| CheckPair
    SOX_GDPR -->|No| CheckPair

    style Start fill:#1565C0,color:#fff
    style Dedupe fill:#2E7D32,color:#fff
    style O1 fill:#F57F17,color:#fff
    style O2 fill:#F57F17,color:#fff
    style O3 fill:#F57F17,color:#fff
    style O4 fill:#F57F17,color:#fff
    style O5 fill:#F57F17,color:#fff
    style O6 fill:#F57F17,color:#fff
```

## Individual Checker Internal Flow

```mermaid
sequenceDiagram
    participant Orch as Orchestrator
    participant Checker as ComplianceChecker
    participant Registry as RequirementRegistry
    participant Engine as RuleEngine
    participant Violation as ViolationBuilder
    participant Score as ScoreCalculator

    Orch->>Checker: check(data)

    Checker->>Checker: validate_scope(data)
    alt Out of Scope
        Checker-->>Orch: CheckResult(skipped=true)
    end

    Checker->>Registry: load_requirements(regulation, version)
    Registry-->>Checker: List[Requirement] (47 requirements)

    loop For Each Requirement
        Checker->>Checker: get_requirement_rule(req)
        Checker->>Engine: evaluate_rule(rule, data)

        rect rgb(230, 242, 255)
            Note over Engine,Engine: Rule Evaluation
            Engine->>Engine: parse_rule_expression()
            Engine->>Engine: extract_data_refs(rule, data)
            Engine->>Engine: apply_condition()
            Engine-->>Checker: RuleResult(passed=bool, details={...})
        end

        alt Rule Passed
            Checker->>Checker: record_passed_requirement(req)
        else Rule Failed
            Checker->>Violation: build_violation(req, details)
            Violation->>Violation: set_severity(req.severity_if_violated)
            Violation->>Violation: set_remediation(req.remediation)
            Violation-->>Checker: Violation(id, description, severity, remediation)
        end
    end

    Checker->>Score: calculate_score(passed, failed, severities)
    Score->>Score: weight_by_severity(critical=10, high=5, medium=2, low=1)
    Score->>Score: compute_percentage(weighted_score / max_score * 100)
    Score-->>Checker: score (0-100)

    Checker-->>Orch: CheckResult(regulation, passed, score, violations)
```

## Report Data Flow

```mermaid
flowchart LR
    subgraph "Data Sources"
        D1["Check Results<br/>per Regulation"]
        D2["Violation Lists<br/>with Severity"]
        D3["Overlap Map"]
        D4["Score Breakdown"]
    end

    subgraph "Report Builder"
        R1["Header Builder<br/>Title, Date, Summary"]
        R2["Score Visualization<br/>Radar / Bar Chart"]
        R3["Violation Table<br/>Sorted by Severity"]
        R4["Per-Regulation<br/>Deep Dive Sections"]
        R5["Overlap Section<br/>Cross-Regulation Notes"]
        R6["Remediation Plan<br/>Prioritized Actions"]
        R7["Appendix<br/>Raw Data, Config Used"]
    end

    subgraph "Output Formats"
        O1["JSON<br/>machine-readable"]
        O2["HTML<br/>interactive dashboard"]
        O3["PDF<br/>printable report"]
        O4["Email<br/>summary digest"]
    end

    D1 --> R1
    D1 --> R2
    D2 --> R3
    D2 --> R6
    D3 --> R5
    D4 --> R2
    D4 --> R4

    R1 --> O1
    R1 --> O2
    R1 --> O3
    R2 --> O2
    R3 --> O1
    R3 --> O2
    R3 --> O3
    R4 --> O1
    R4 --> O2
    R4 --> O3
    R5 --> O1
    R5 --> O2
    R5 --> O3
    R6 --> O1
    R6 --> O2
    R6 --> O3
    R7 --> O1
    R7 --> O2
    R7 --> O3

    O1 --> E1["API Consumer"]
    O2 --> E2["Dashboard User"]
    O3 --> E3["Auditor / Regulator"]
    O4 --> E4["Compliance Team"]

    style O1 fill:#1976D2,color:#fff
    style O2 fill:#388E3C,color:#fff
    style O3 fill:#F57C00,color:#fff
    style O4 fill:#7B1FA2,color:#fff
```

## Error Handling Flow

```mermaid
flowchart TD
    Start(["Error During Check"]) --> Classify{"Error<br/>Category?"}

    Classify -->|Data Error| DataErr["Invalid Input Data<br/>Missing required fields"]
    Classify -->|Config Error| CfgErr["Checker Configuration<br/>Invalid or Missing"]
    Classify -->|Runtime Error| RunErr["Rule Evaluation<br/>Exception"]
    Classify -->|Timeout| TimeErr["Checker Exceeded<br/>Timeout Limit"]

    DataErr --> LogDataErr["Log: Invalid data for checker X"]
    LogDataErr --> SkipChecker["Skip Checker X<br/>Mark as error in result"]

    CfgErr --> LogCfgErr["Log: Config error for checker X"]
    LogCfgErr --> UseDefaults["Use default configuration"]
    UseDefaults --> RetryCheck["Retry Check"]

    RunErr --> LogRunErr["Log: Rule Y failed with exception"]
    LogRunErr --> MarkRuleFailed["Mark Rule Y as error<br/>Include in violations"]
    MarkRuleFailed --> ContinueRules["Continue with remaining rules"]

    TimeErr --> LogTimeErr["Log: Checker X timed out"]
    LogTimeErr --> PartialResult["Return partial results<br/>collected so far"]
    PartialResult --> FlagIncomplete["Flag result as incomplete"]

    SkipChecker --> ContinueOther["Continue with other checkers"]
    RetryCheck --> ContinueOther
    ContinueRules --> ContinueOther
    FlagIncomplete --> ContinueOther

    ContinueOther --> EndCheckers["All checkers processed"]
    EndCheckers --> BuildPartialResult["Build OrchestratedResult<br/>with error annotations"]

    BuildPartialResult --> ReturnResult["Return to caller<br/>with error metadata"]

    style Start fill:#C62828,color:#fff
    style SkipChecker fill:#E65100,color:#fff
    style ContinueOther fill:#F57F17,color:#fff
    style ReturnResult fill:#1565C0,color:#fff
```