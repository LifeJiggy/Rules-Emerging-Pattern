# Compliance Decision Logic

## Data Classification Flowchart

The first step in any compliance check is classifying the incoming data. The classification determines which regulations apply and which rules to evaluate.

```mermaid
flowchart TD
    Start(["Data Received"]) --> IdentifyFields["Identify All Data Fields<br/>from schema + sample"]

    IdentifyFields --> ClassifyField{"Classify Each<br/>Data Field"}

    ClassifyField -->|email, phone, name, address| PII["PII - Personal Identifiable Info"]
    ClassifyField -->|medical_record, diagnosis, lab_result| PHI["PHI - Protected Health Info"]
    ClassifyField -->|credit_card, cvv, cardholder_name| CHD["CHD - Cardholder Data"]
    ClassifyField -->|revenue, balance, transaction| FIN["Financial Data"]
    ClassifyField -->|ip_address, device_id, cookie| TECH["Technical Data<br/>Not PII Alone"]

    PII --> PII_Regs{"Data Subject<br/>Jurisdiction?"}
    PHI --> PHI_Regs{"Data Subject<br/>Jurisdiction?"}
    CHD --> CHD_Regs{"CHD<br/>Present?"}
    FIN --> FIN_Regs{"Public Company<br/>Subject to SOX?"}
    TECH --> TECH_Regs{"Any PII<br/>Present?"}

    PII_Regs -->|EU/EEA| GDPR_Apply["GDPR Applies"]
    PII_Regs -->|California| CCPA_Apply["CCPA Applies<br/>(future)"]
    PII_Regs -->|Other| DefaultPrivacy["Local Privacy Laws"]

    PHI_Regs -->|USA| HIPAA_Apply["HIPAA Applies"]
    PHI_Regs -->|Non-USA| LocalHealthRegs["Local Health Regs"]

    CHD_Regs -->|Yes| PCI_Apply["PCI DSS Applies"]
    CHD_Regs -->|No| NoPCI["PCI Not Required"]

    FIN_Regs -->|Yes| SOX_Apply["SOX Applies"]
    FIN_Regs -->|No| NoSOX["SOX Not Required<br/>May still need GAAP"]

    TECH_Regs -->|Yes| PII_Regs
    TECH_Regs -->|No| MinimalRisk["Minimal Compliance Risk"]

    GDPR_Apply --> BuildScope["Build Compliance Scope"]
    HIPAA_Apply --> BuildScope
    PCI_Apply --> BuildScope
    SOX_Apply --> BuildScope
    CCPA_Apply --> BuildScope
    LocalHealthRegs --> BuildScope
    DefaultPrivacy --> BuildScope
    NoPCI --> BuildScope
    NoSOX --> BuildScope
    MinimalRisk --> BuildScope

    BuildScope --> ReturnScope(["Return: Applicable Regulations + Data Map"])

    style Start fill:#1565C0,color:#fff
    style ReturnScope fill:#2E7D32,color:#fff
    style GDPR_Apply fill:#1976D2,color:#fff
    style HIPAA_Apply fill:#388E3C,color:#fff
    style PCI_Apply fill:#F57C00,color:#fff
    style SOX_Apply fill:#7B1FA2,color:#fff
```

## Regulation Applicability Decision Tree

Not all regulations apply to all data. The decision tree below determines which regulations to activate based on data type, jurisdiction, and entity type.

```mermaid
flowchart TD
    Start(["What Data<br/>Do You Process?"]) --> DataTypes{"Data Types?"}

    DataTypes -->|Personal Data| PersonalQ["Personal Data:<br/>Names, emails, IPs, cookies"]
    DataTypes -->|Health Data| HealthQ["Health Data:<br/>Medical records, diagnoses"]
    DataTypes -->|Payment Data| PaymentQ["Payment Data:<br/>Card numbers, bank accounts"]
    DataTypes -->|Financial Data| FinancialQ["Financial Data:<br/>Revenue, expenses, reports"]

    PersonalQ --> Subjects{"Data Subjects<br/>Located In?"}
    Subjects -->|EU/EEA| GDPR_L1["GDPR Art 1-99"]
    Subjects -->|California| CCPA["CCPA / CPRA"]
    Subjects -->|Brazil| LGPD["LGPD"]
    Subjects -->|Global| MultiNational["Multiple Privacy Laws<br/>Apply strictest"]

    HealthQ --> Entity{"Entity Type?"}
    Entity -->|Covered Entity<br/>Healthcare Provider| HIPAA_L1["HIPAA Privacy Rule<br/>164.500-534"]
    Entity -->|Business Associate<br/>Vendor| HIPAA_L2["HIPAA Security Rule<br/>164.302-318"]
    Entity -->|Not USA| LocalHealth["Local Health Regulations"]

    PaymentQ --> Card{"Card Brand?"}
    Card -->|Visa/MC/Amex/Discover| PCI_L1["PCI DSS 4.0<br/>All 12 Requirements"]
    Card -->|Other| NonBrand["Not PCI-regulated<br/>Check local laws"]
    PCI_L1 --> Volume{"Transaction Volume?"}
    Volume -->|>6M/yr| Level1["Level 1: Full assessment"]
    Volume -->|1M-6M/yr| Level2["Level 2: SAQ + scan"]
    Volume -->|20K-1M/yr| Level3["Level 3: SAQ"]
    Volume -->|<20K/yr| Level4["Level 4: SAQ"]

    FinancialQ --> Public{"Publicly Traded<br/>Company?"}
    Public -->|Yes| SOX_L1["SOX Sections<br/>302, 404, 409, 802"]
    Public -->|No| NonPublic["Not SOX-regulated<br/>May need GAAP compliance"]

    GDPR_L1 --> CheckAll["Check All Applicable"]
    CCPA --> CheckAll
    LGPD --> CheckAll
    MultiNational --> CheckAll
    HIPAA_L1 --> CheckAll
    HIPAA_L2 --> CheckAll
    LocalHealth --> CheckAll
    PCI_L1 --> CheckAll
    Level1 --> CheckAll
    Level2 --> CheckAll
    Level3 --> CheckAll
    Level4 --> CheckAll
    SOX_L1 --> CheckAll

    CheckAll --> ReturnRegs(["Return Active Regulations"])

    style Start fill:#1565C0,color:#fff
    style ReturnRegs fill:#2E7D32,color:#fff
    style GDPR_L1 fill:#1976D2,color:#fff
    style HIPAA_L1 fill:#388E3C,color:#fff
    style PCI_L1 fill:#F57C00,color:#fff
    style SOX_L1 fill:#7B1FA2,color:#fff
```

## Compliance Severity Scoring Logic

```mermaid
flowchart TD
    Start(["Violation Detected"]) --> ClassifyType{"Violation<br/>Category?"}

    ClassifyType -->|Data Breach| Breach["Potential Data Breach"]
    ClassifyType -->|Missing Consent| Consent["Missing/Lapsed Consent"]
    ClassifyType -->|Unencrypted Data| Encrypt["Unencrypted Sensitive Data"]
    ClassifyType -->|Access Control| Access["Improper Access Control"]
    ClassifyType -->|Retention| Retention["Data Retained Beyond Policy"]
    ClassifyType -->|Audit Trail| Audit["Missing Audit Trail"]
    ClassifyType -->|BAA/Contract| BAA["Missing BAA/DPA"]
    ClassifyType -->|Transfer| Transfer["Unauthorized Data Transfer"]

    Breach --> BreachReg{"Affected<br/>Regulation?"}
    BreachReg -->|GDPR| G_Breach["Art 33/34<br/>Notify within 72h"]
    BreachReg -->|HIPAA| H_Breach["164.400-414<br/>Notify within 60 days"]
    BreachReg -->|PCI| P_Breach["Req 12.10<br/>Incident response"]

    G_Breach --> CriticalScore["Severity: CRITICAL<br/>Score Penalty: -40"]
    H_Breach --> CriticalScore
    P_Breach --> CriticalScore

    Consent --> ConsentReg{"Affected<br/>Regulation?"}
    ConsentReg -->|GDPR| G_Consent["Art 6/7<br/>Lawful basis required"]
    G_Consent --> HighScore["Severity: HIGH<br/>Score Penalty: -20"]

    Encrypt --> EncryptReg{"Affected<br/>Regulation?"}
    EncryptReg -->|GDPR| G_Encrypt["Art 32<br/>Security of processing"]
    EncryptReg -->|HIPAA| H_Encrypt["164.312(a)(2)(iv)<br/>Encryption required"]
    EncryptReg -->|PCI| P_Encrypt["Req 3.4/4.1<br/>CHD must be encrypted"]

    G_Encrypt --> HighScore
    H_Encrypt --> CriticalScore
    P_Encrypt --> CriticalScore

    Access --> AccessReg{"Affected<br/>Regulation?"}
    AccessReg -->|HIPAA| H_Access["164.312(a)(1)<br/>Unique user IDs"]
    AccessReg -->|PCI| P_Access["Req 7.1/7.2<br/>Need-to-know access"]
    AccessReg -->|SOX| S_Access["§302<br/>Access controls over financial data"]

    H_Access --> MediumScore["Severity: MEDIUM<br/>Score Penalty: -10"]
    P_Access --> MediumScore
    S_Access --> MediumScore

    Retention --> RetentionReg{"Affected<br/>Regulation?"}
    RetentionReg -->|GDPR| G_Retention["Art 5(1)(e)<br/>Storage limitation"]
    RetentionReg -->|PCI| P_Retention["Req 3.1<br/>Dispose when not needed"]

    G_Retention --> MediumScore
    P_Retention --> MediumScore

    Audit --> AuditReg{"Affected<br/>Regulation?"}
    AuditReg -->|HIPAA| H_Audit["164.312(b)<br/>Audit controls"]
    AuditReg -->|PCI| P_Audit["Req 10.2/10.3<br/>Audit trails"]
    AuditReg -->|SOX| S_Audit["§404<br/>Internal controls"]
    H_Audit --> LowScore["Severity: LOW<br/>Score Penalty: -5"]
    P_Audit --> LowScore
    S_Audit --> LowScore

    BAA --> BAA_Reg{"Affected<br/>Regulation?"}
    BAA_Reg -->|HIPAA| H_BAA["164.314(a)(1)<br/>BAA required"]
    H_BAA --> HighScore

    Transfer --> TransferReg{"Affected<br/>Regulation?"}
    TransferReg -->|GDPR| G_Transfer["Art 44-49<br/>International transfers"]
    G_Transfer --> HighScore

    CriticalScore --> FinalScore["Final Score = Max(0, 100 - total_penalty)"]
    HighScore --> FinalScore
    MediumScore --> FinalScore
    LowScore --> FinalScore

    FinalScore --> ReturnScore(["Return Score + Severity Map"])

    style Start fill:#C62828,color:#fff
    style CriticalScore fill:#C62828,color:#fff
    style HighScore fill:#E65100,color:#fff
    style MediumScore fill:#F57F17,color:#fff
    style LowScore fill:#F9A825,color:#fff
    style ReturnScore fill:#2E7D32,color:#fff
```

## Remediation Priority Logic

```mermaid
flowchart TD
    Start(["Violations Identified"]) --> GroupBySeverity["Group by Severity"]

    GroupBySeverity --> Prioritize{"Priority<br/>Based On?"}

    Prioritize --> SeverityFirst["Severity: CRITICAL first"]
    Prioritize --> OverlapFirst["Overlap: Violations affecting<br/>multiple regulations first"]
    Prioritize --> EaseFirst["Ease: Quick wins first"]

    SeverityFirst --> CriticalViolations["Critical Violations"]
    CriticalViolations --> AssignImmediate["Assign: Fix within 24h<br/>Escalate to CISO"]

    OverlapFirst --> OverlapViolations["Violations in 2+ Regulations"]
    OverlapViolations --> AssignHigh["Assign: Fix within 7 days<br/>Single fix covers multiple regs"]

    EaseFirst --> EasyViolations["Low effort,<br/>High impact violations"]
    EasyViolations --> AssignMedium["Assign: Fix within 30 days<br/>Configuration changes"]

    AssignImmediate --> RemainingViolations["Remaining Violations"]
    AssignHigh --> RemainingViolations
    AssignMedium --> RemainingViolations

    RemainingViolations --> CategorizeRemaining{"Severity of<br/>Remaining?"}

    CategorizeRemaining -->|HIGH| AssignHighRemaining["Assign: Fix within 14 days"]
    CategorizeRemaining -->|MEDIUM| AssignMediumRemaining["Assign: Fix within 60 days"]
    CategorizeRemaining -->|LOW| AssignLowRemaining["Assign: Fix within 90 days<br/>Or accept risk"]

    AssignHighRemaining --> BuildRemediationPlan["Build Remediation Plan<br/>with Deadlines + Owners"]
    AssignMediumRemaining --> BuildRemediationPlan
    AssignLowRemaining --> BuildRemediationPlan

    BuildRemediationPlan --> ReturnPlan(["Return: Prioritized Remediation Plan"])

    style Start fill:#1565C0,color:#fff
    style CriticalViolations fill:#C62828,color:#fff
    style OverlapViolations fill:#E65100,color:#fff
    style AssignImmediate fill:#C62828,color:#fff
    style ReturnPlan fill:#2E7D32,color:#fff
```

## Rule Evaluation Engine Logic

```mermaid
flowchart TD
    Start(["Evaluate Rule"]) --> GetRuleDef["Get Rule Definition<br/>from RequirementRegistry"]

    GetRuleDef --> ParseRule["Parse Rule Expression<br/>e.g., encryption == 'AES-256'"]

    ParseRule --> ExtractRefs["Extract Data References<br/>from rule expression"]

    ExtractRefs --> ResolveRefs["Resolve References<br/>against input data"]

    ResolveRefs --> AllFound{"All References<br/>Resolved?"}

    AllFound -->|No| MissingRefError["Error: Missing data field"]
    MissingRefError --> MarkError["Mark rule as error<br/>Include in violations"]

    AllFound -->|Yes| EvalCondition["Evaluate Condition<br/>Apply operators, comparators"]

    EvalCondition --> ConditionResult{"Condition<br/>Met?"}

    ConditionResult -->|Yes| RecordPass["Record: Rule Passed<br/>No action needed"]
    ConditionResult -->|No| DetermineSeverity["Determine Severity<br/>from requirement config"]

    DetermineSeverity --> BuildViolation["Build Violation Record"]
    BuildViolation --> GetRemediation["Get Remediation Steps<br/>from requirement"]
    GetRemediation --> AddToViolationList["Add to Violation List"]

    RecordPass --> ReturnResult["Return RuleResult"]
    AddToViolationList --> ReturnResult

    MarkError --> ReturnResult

    style Start fill:#1565C0,color:#fff
    style RecordPass fill:#2E7D32,color:#fff
    style BuildViolation fill:#C62828,color:#fff
    style ReturnResult fill:#F57F17,color:#fff
```

## Sample Rule Definitions

```python
GDPR_RULES = [
    {
        "id": "GDPR-ART5-1C",
        "regulation": "GDPR",
        "article": "Art 5(1)(c)",
        "description": "Data minimization - only collect data necessary for purpose",
        "expression": "len(data.fields) <= data.stated_purpose.required_fields_count",
        "severity": "HIGH",
        "remediation": "Remove unnecessary data fields from collection forms"
    },
    {
        "id": "GDPR-ART17",
        "regulation": "GDPR",
        "article": "Art 17",
        "description": "Right to erasure ('right to be forgotten')",
        "expression": "data.erasure_requests.all(r.processed_within_30_days for r in requests)",
        "severity": "HIGH",
        "remediation": "Implement automated erasure workflow with 30-day SLA"
    },
    {
        "id": "GDPR-ART32",
        "regulation": "GDPR",
        "article": "Art 32",
        "description": "Security of processing - encryption at rest and in transit",
        "expression": "data.encryption.at_rest == 'AES-256' AND data.encryption.in_transit == 'TLS-1.3'",
        "severity": "CRITICAL",
        "remediation": "Upgrade encryption to AES-256 and TLS 1.3"
    }
]

HIPAA_RULES = [
    {
        "id": "HIPAA-164312A1",
        "regulation": "HIPAA",
        "article": "164.312(a)(1)",
        "description": "Unique user identification for PHI systems",
        "expression": "all(u.unique_id for u in data.users_with_phi_access)",
        "severity": "MEDIUM",
        "remediation": "Implement unique user IDs for all PHI system accounts"
    },
    {
        "id": "HIPAA-164312A2IV",
        "regulation": "HIPAA",
        "article": "164.312(a)(2)(iv)",
        "description": "Encryption and decryption of PHI at rest",
        "expression": "data.encryption.at_rest in ['AES-256', 'AES-128']",
        "severity": "CRITICAL",
        "remediation": "Encrypt all PHI at rest using AES-256"
    }
]
```

## Score Calculation Algorithm

The overall compliance score is calculated as:

```
base_score = 100
for each violation:
    severity_weight = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1}[violation.severity]
    penalty = severity_weight * 2
    base_score -= penalty

final_score = max(0, base_score)
```

| Violations | Severity Mix | Score |
|---|---|---|
| 0 | — | 100 (Perfect) |
| 2 | 1 CRITICAL, 1 LOW | 79 |
| 5 | 2 HIGH, 3 MEDIUM | 64 |
| 10 | 3 CRITICAL, 3 HIGH, 2 MEDIUM, 2 LOW | 20 |
| 12+ | Various | 0 (Non-compliant) |