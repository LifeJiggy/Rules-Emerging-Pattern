# Model Reasoning & Validation

## Validation Decision Logic

The `ValidationResult` and `Violation` models encapsulate the decision logic for content validation. The following flowchart shows how individual violations combine to produce a final validation outcome.

```mermaid
flowchart TD
    A["Content Evaluation Request"] --> B["Evaluate Against Rule"]
    B --> C{"Pattern Match Found?"}

    C -->|"Keyword Match"| D["ViolationType.KEYWORD_MATCH"]
    C -->|"Regex Match"| E["ViolationType.REGEX_MATCH"]
    C -->|"ML Model Trigger"| F["ViolationType.SEMANTIC_VIOLATION"]
    C -->|"No Match"| G["No Violation - Return None"]

    D --> H["Set confidence = 0.8"]
    E --> I["Set confidence = 0.9"]
    F --> J["Set confidence = ml_model.confidence"]

    H --> K["Determine ActionTaken"]
    I --> K
    J --> K

    K --> L{"Enforcement Level?"}

    L -->|"STRICT"| M["ActionTaken.BLOCK"]
    L -->|"ADVISORY"| N["ActionTaken.WARNING"]
    L -->|"ADAPTIVE"| O["ActionTaken.SUGGESTION"]
    L -->|"FALLBACK"| P["ActionTaken.NONE"]

    M --> Q["Set blocked = rule.auto_block"]
    N --> R["Add to result.warnings list"]
    O --> S["Add to result.suggestions list"]
    P --> T["No action recorded"]

    Q --> U{"blocked = True?"}
    U -->|Yes| V["result.valid = False"]
    U -->|No| W["result.valid stays True"]

    R --> X{"Any blocked violation?"}
    S --> X
    T --> X

    V --> Y["is_critical()?"]
    Y -->|Yes| Z["Add to critical_violations"]
    Y -->|No| AA["Add to violations list"]

    X -->|Yes| AB["result.valid = False"]
    X -->|No| AC["result.valid remains"]

    Z --> AD["Aggregate into ValidationResult"]
    AA --> AD
    AB --> AD
    AC --> AD

    AD --> AE{"Final valid?"}
    AE -->|"valid=False, has violations"| AF["Return BLOCKED result"]
    AE -->|"valid=True, has warnings"| AG["Return WARNING result"]
    AE -->|"valid=True, no issues"| AH["Return PASS result"]
```

## Conflict Detection & Resolution Decision Diagram

The Conflict Detection model uses a multi-stage analysis to identify and resolve rule conflicts.

```mermaid
flowchart TD
    subgraph DetectionPhase["Conflict Detection Phase"]
        A["Rule Set / Result Set"] --> B{"Detect by Type?"}

        B -->|"Priority Conflict"| C["Compare rule.priority values"]
        C --> D{"Same priority,\ncontradictory actions?"}
        D -->|Yes| E["Create RuleConflict: PRIORITY_CONFLICT"]

        B -->|"Semantic Conflict"| F["Analyze rule descriptions & patterns"]
        F --> G{"Overlapping patterns,\nopposite outcomes?"}
        G -->|Yes| H["Create RuleConflict: SEMANTIC_CONFLICT"]

        B -->|"Logical Contradiction"| I["Analyze logical conditions"]
        I --> J{"rule.conditions contradict\nanother rule.conditions?"}
        J -->|Yes| K["Create RuleConflict: LOGICAL_CONTRADICTION"]

        B -->|"Mutual Exclusivity"| L["Check mutual exclusion markers"]
        L --> M{"Rules marked\nas mutually exclusive?"}
        M -->|Yes| N["Create RuleConflict: MUTUAL_EXCLUSIVITY"]

        B -->|"Context Conflict"| O["Compare context applicability"]
        O --> P{"Same context,\ndifferent outcomes?"}
        P -->|Yes| Q["Create RuleConflict: CONTEXT_CONFLICT"]
    end

    subgraph SeverityPhase["Severity Assessment"]
        E --> R["Assess Conflict Severity"]
        H --> R
        K --> R
        N --> R
        Q --> R

        R --> S{"Involves Safety Tier?"}
        S -->|Yes| T["ConflictSeverity.CRITICAL"]
        S -->|No| U{"Involves HIGH severity rules?"}
        U -->|Yes| V["ConflictSeverity.HIGH"]
        U -->|No| W{"Involves MEDIUM severity?"}
        W -->|Yes| X["ConflictSeverity.MEDIUM"]
        W -->|No| Y["ConflictSeverity.LOW"]
    end

    subgraph ResolutionPhase["Resolution Phase"]
        T --> Z{"Resolution Strategy?"}
        V --> Z
        X --> Z
        Y --> Z

        Z -->|"PRIORITY_BASED"| AA["Higher priority rule wins"]
        Z -->|"CONTEXT_AWARE"| AB["Rule matching current context wins"]
        Z -->|"USER_PREFERENCE"| AC["User's preferred rule wins"]
        Z -->|"FALLBACK"| AD["Apply default fallback rule"]
        Z -->|"HYBRID"| AE["Combine multiple strategies"]
        Z -->|"HUMAN_REVIEW"| AF["Escalate for manual resolution"]

        AA --> AG["Create ConflictResolution"]
        AB --> AG
        AC --> AG
        AD --> AG
        AE --> AG
        AF --> AG

        AG --> AH["Mark conflict as resolved = True"]
        AH --> AI["Record resolution outcome"]
    end

    subgraph Outcome["Resolution Outcome"]
        AI --> AJ["Suppress losing rule"]
        AI --> AK["Adjust rule priority"]
        AI --> AL["Modify rule conditions"]
        AI --> AM["Flag for human review"]
        AI --> AN["Log to audit trail"]
    end
```

## Audit Trail Reasoning

The Audit model provides a comprehensive trail of all system actions. The following diagram shows how audit events are generated and correlated.

```mermaid
flowchart TD
    subgraph Triggers["Audit Event Triggers"]
        A1["Rule CRUD operations"]
        A2["Violation detection"]
        A3["Conflict resolution"]
        A4["Configuration changes"]
        A5["User actions"]
        A6["System events"]
    end

    subgraph EventCreation["Audit Event Creation"]
        B1["Determine AuditCategory"]
        B2["Determine AuditAction"]
        B3["Record actor information"]
        B4["Capture resource details"]
        B5["Record before/after state"]
        B6["Add correlation context"]
    end

    subgraph Enrichment["Enrichment"]
        C1["Attach session context"]
        C2["Attach IP/user-agent"]
        C3["Link to parent event"]
        C4["Compute severity"]
    end

    subgraph Storage["Storage & Indexing"]
        D1["Append to AuditTrail"]
        D2["Index by category"]
        D3["Index by actor"]
        D4["Index by time range"]
        D5["Index by resource"]
    end

    subgraph Analysis["Analysis & Reporting"]
        E1["Query by action type"]
        E2["Query by time range"]
        E3["Query by actor"]
        E4["Generate compliance report"]
        E5["Detect anomalous patterns"]
        E6["Forensic investigation"]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B1
    A5 --> B1
    A6 --> B1

    B1 --> B2 --> B3 --> B4 --> B5 --> B6
    B6 --> C1 --> C2 --> C3 --> C4

    C4 --> D1
    D1 --> D2
    D1 --> D3
    D1 --> D4
    D1 --> D5

    D2 --> E1
    D3 --> E2
    D4 --> E3
    D5 --> E4
    E4 --> E5
    E5 --> E6
```

## Violation Escalation Decision Tree

```mermaid
flowchart TD
    A["Violation Detected"] --> B{"is_critical()?"}
    B -->|Yes| C["Add to critical_violations list"]
    B -->|No| D{"requires_escalation()?"}

    D -->|Yes| E{"Reason for escalation?"}
    D -->|No| F["Add to standard violations"]

    E -->|"rule_severity == CRITICAL"| G["Escalate immediately"]
    E -->|"action_taken == ESCALATE"| H["Trigger escalation flow"]
    E -->|"rule_tier == SAFETY"| I["Notify safety team"]

    G --> J["Set alert severity to CRITICAL"]
    H --> J
    I --> J

    J --> K["Create escalation event"]
    K --> L["Notify on-call engineer"]
    L --> M["Log to audit trail"]

    F --> N{"action_taken?"}
    N -->|"BLOCK"| O["blocked = True, valid = False"]
    N -->|"WARNING"| P["Add to warnings list"]
    N -->|"SUGGESTION"| Q["Add suggestion to result"]
    N -->|"REDACT"| R["Add redaction marker"]
    N -->|"QUARANTINE"| S["Flag for quarantine"]
    N -->|"NONE"| T["Record but take no action"]

    O --> U["result.valid = False"]
    P --> V["User alerted"]
    Q --> W["Suggestion presented"]
    R --> X["Content redacted"]
    S --> Y["Content quarantined"]
    T --> Z["Logged only"]

    U --> AA["Final result compiled"]
    V --> AA
    W --> AA
    X --> AA
    Y --> AA
    Z --> AA
```

## Override Reasoning

```mermaid
flowchart TD
    A["Violation with user_override_allowed"] --> B{"Override Justification\nRequired?"}
    B -->|Yes| C["User must provide reason"]
    B -->|No| D["User can dismiss without reason"]

    C --> E{"Justification\nProvided?"}
    E -->|Yes| F["Log override with justification"]
    E -->|No| G["Override rejected"]

    D --> H["Log override dismissal"]

    F --> I{"Override approved?"}
    H --> I
    I -->|Yes| J["Set override_justification"]
    J --> K["Violation is suppressed"]
    K --> L["Update result: remove violation"]
    L --> M["Log to audit trail: OVERRIDE action"]

    I -->|No| N["Violation stands"]
    N --> O["Alert user: override denied"]

    M --> P{"Violation was blocking?"}
    P -->|Yes| Q["Re-evaluate result.valid"]
    Q --> R{"Other blocking violations?"}
    R -->|No| S["result.valid = True"]
    R -->|Yes| T["result.valid remains False"]
    P -->|No| U["No change to valid flag"]
```
