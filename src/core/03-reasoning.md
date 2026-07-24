# Reasoning & Decision Logic

## Tiered Rule Selection Logic

The core engine evaluates rules in a strict three-tier hierarchy. Each tier has distinct evaluation semantics and early-termination conditions.

```mermaid
flowchart TD
    A["Evaluation Request"] --> B["Load All Applicable Rules"]
    B --> C["Group Rules by Tier"]

    subgraph Safety["SAFETY TIER - Priority: Highest"]
        D1["Apply SafetyRuleEngine"]
        D1 --> D2{"Any Safety Violation?"}
        D2 -->|"Yes (auto_block=True)"| D3["Set valid=False"]
        D2 -->|"Yes (critical)"| D4["Add to critical_violations"]
        D2 -->|"No"| D5["Continue to Operational"]
        D3 --> D6["Early Termination"]
        D4 --> D6
        D6 --> E["Return Result (Blocked)"]
    end

    subgraph Operational["OPERATIONAL TIER - Priority: Medium"]
        F1["Apply OperationalRuleEngine"]
        F1 --> F2{"Quality/Structure Issues?"}
        F2 -->|"Yes (violation)"| F3["Record Violation"]
        F2 -->|"Yes (warning)"| F4["Add Warning"]
        F2 -->|"No"| F5["Continue to Preference"]
        F3 --> F6{"Blocking?"}
        F6 -->|Yes| F7["Set valid=False"]
        F6 -->|No| F8["Continue"]
        F4 --> F8
        F5 --> F8
    end

    subgraph Preference["PREFERENCE TIER - Priority: Lowest"]
        G1["Apply PreferenceRuleEngine"]
        G1 --> G2{"Suggestion Needed?"}
        G2 -->|"Yes"| G3["Add Suggestion"]
        G2 -->|"No"| G4["No Action"]
        G3 --> G5["Continue"]
        G4 --> G5
    end

    C -->|"Safety Rules"| D1
    C -->|"Operational Rules"| F1
    C -->|"Preference Rules"| G1

    D5 --> F1
    F8 --> G1
    G5 --> H["Post-Process: Deduplicate"]
    H --> I["Post-Process: Score Calculation"]
    I --> J["Return Aggregated Result"]

    style Safety fill:#ffcdd2
    style Operational fill:#fff9c4
    style Preference fill:#c8e6c9
```

## Rule Evaluation Decision Tree

The following decision tree shows the branching logic for evaluating a single rule against input content.

```mermaid
flowchart TD
    A["Single Rule Evaluation"] --> B{"Rule Status == ACTIVE?"}
    B -->|No| C["Skip Rule"]
    B -->|Yes| D{"Context Applicable?"}
    D -->|No| E["Skip - Not Applicable"]
    D -->|Yes| F["Iterate Rule Patterns"]

    F --> G{"Pattern Type?"}

    G -->|"Keyword"| H["Convert content to lowercase"]
    H --> I["For each keyword in pattern.keywords"]
    I --> J{"keyword.lower() in content?"}
    J -->|Yes| K["Create Violation: KEYWORD_MATCH"]
    J -->|No| L["Check next keyword"]
    L --> I
    K --> M["Set confidence = 0.8"]
    M --> N["Determine Action from EnforcementLevel"]
    N --> O["Return Violation"]

    G -->|"Regex"| P["For each regex in pattern.regex_patterns"]
    P --> Q{"re.search(regex, content, IGNORECASE)"}
    Q -->|Yes| R["Create Violation: REGEX_MATCH"]
    Q -->|No| S["Check next regex"]
    S --> P
    R --> T["Set confidence = 0.9"]
    T --> N

    G -->|"ML Model"| U["Load ML Model"]
    U --> V["Run inference on content"]
    V --> W{"confidence > threshold?"}
    W -->|Yes| X["Create Violation: SEMANTIC/MODEL"]
    W -->|No| Y["No Violation"]
    X --> N

    C --> Z["Return None"]
    E --> Z
    Y --> Z
    O --> AA["End"]
```

## Action Determination Logic

```mermaid
flowchart TD
    A["Rule Enforcement Level"] --> B{"EnforcementLevel?"}

    B -->|"STRICT"| C["ActionTaken.BLOCK"]
    B -->|"ADVISORY"| D["ActionTaken.WARNING"]
    B -->|"ADAPTIVE"| E["ActionTaken.SUGGESTION"]
    B -->|"FALLBACK"| F["ActionTaken.NONE"]

    C --> G{"rule.auto_block?"}
    G -->|Yes| H["Set Violation.blocked = True"]
    G -->|No| I["Set Violation.blocked = False"]
    D --> J["Add to result.warnings"]
    E --> K["Add to result.suggestions"]

    H --> L{"rule.user_override?"}
    I --> L
    L -->|Yes| M["Set user_override_allowed = True"]
    L -->|No| N["Set user_override_allowed = False"]
    J --> O["Return Violation"]
    K --> O
    F --> O
    M --> O
    N --> O
```

## Conflict Detection & Resolution Reasoning

The `RuleDispatcher` and `ResultAggregator` contain logic for detecting and resolving conflicts between rules and evaluation results.

```mermaid
flowchart TD
    subgraph Detection["Conflict Detection"]
        A["Multiple Evaluation Results"] --> B["Extract All Violations"]
        B --> C["Group by Rule ID + Violation Type"]
        C --> D{"Duplicate Found?"}
        D -->|Yes| E["Conflict: Same Rule Fired Twice"]
        D -->|Yes| F["Conflict: Different Rules, Same Content"]
        D -->|No| G["No Conflict"]
    end

    subgraph Resolution["Conflict Resolution"]
        E --> H{"Conflict Type?"}
        F --> H

        H -->|"Tier Conflict"| I["Higher Tier Wins (Safety > Operational > Preference)"]
        H -->|"Severity Conflict"| J["Higher Severity Wins (Critical > High > Medium > Low)"]
        H -->|"Same Tier + Severity"| K["Higher Confidence Wins"]
        H -->|"Action Conflict"| L["More Restrictive Action Wins (Block > Warn > Suggest)"]

        I --> M["Keep Higher Tier Violation"]
        J --> M
        K --> M
        L --> M
    end

    subgraph Merging["Violation Merging"]
        M --> N["Build Deduplication Key: rule_id:type:content"]
        N --> O{"Key Exists?"}
        O -->|Yes, lower confidence| P["Replace with Higher Confidence"]
        O -->|Yes, not blocked| Q["Upgrade to Blocked"]
        O -->|No| R["Add New Violation"]
        P --> S["Deduplicated Violation List"]
        Q --> S
        R --> S
    end

    G --> T["Pass Through"]
    S --> U["Final Violation Set"]
    T --> U
```

## Pipeline Stage Decision Logic

```mermaid
flowchart TD
    A["Pipeline Execution Start"] --> B["Create PipelineContext"]
    B --> C["Run Global Pre-Hooks"]
    C --> D{"Parallel Mode?"}
    D -->|Yes| E["Group Stages by Order"]
    D -->|No| F["Execute Stages Sequentially"]

    F --> G["For each stage in ordered stages"]
    G --> H{"Stage Enabled?"}
    H -->|No| I["Mark SKIPPED"]
    H -->|Yes| J["Execute Stage Handler"]
    J --> K{"Timeout?"}
    K -->|Yes| L{"Timeout Behavior?"}
    L -->|"skip"| M["Mark TIMEOUT - continue"]
    L -->|"fail"| N["Mark TIMEOUT - abort"]
    L -->|"retry"| O["Retry Stage"]
    O --> K

    J --> P{"Handler Error?"}
    P -->|Yes| Q{"Stage Required?"}
    Q -->|Yes| R["Raise StageExecutionError"]
    Q -->|No| S["Mark FAILED - continue"]

    M --> T["Record Stage Result"]
    N --> U["Abort Pipeline"]
    S --> T
    P -->|No| V["Mark COMPLETED"]
    V --> T

    T --> W{"More Stages?"}
    W -->|Yes| G
    W -->|No| X["Run Global Post-Hooks"]
    X --> Y["Return PipelineContext"]

    E --> Z["Execute Same-Order Stages in Parallel"]
    Z --> AA{"All Succeed?"}
    AA -->|Yes| AB["Advance to Next Order Group"]
    AA -->|No, fail_on_error| AC["Abort Pipeline"]
    AA -->|No, !fail_on_error| AD["Log Errors, Continue"]
    AB --> AE{"More Groups?"}
    AE -->|Yes| Z
    AE -->|No| X
    AD --> AE
```

## Scoring & Aggregation Reasoning

```mermaid
flowchart LR
    subgraph Scoring["Weighted Score Calculation"]
        A["Results List"] --> B["For each result:"]
        B --> C["Compute weight"]
        C --> D["weight_by_confidence: *= result.confidence"]
        D --> E["weight_by_tier: *= tier_weight^(1/count)"]
        E --> F["Apply weight to score"]
        F --> G["Weighted Sum / Total Weight"]
        G --> H["Final Score"]
    end

    subgraph Strategies["Aggregation Strategies"]
        I["WEIGHTED: weighted_score(results)"]
        J["MIN: min(scores)"]
        K["MAX: max(scores)"]
        L["AVERAGE: sum(scores) / N"]
        M["CONSENSUS: valid_count / N"]
        N["SUM: min(total, 1.0)"]
        O["MEDIAN: sorted midpoint"]
    end

    H --> P{"Strategy?"}
    P --> I
    P --> J
    P --> K
    P --> L
    P --> M
    P --> N
    P --> O

    I --> Q["valid = score >= confidence_threshold"]
    J --> Q
    K --> Q
    L --> Q
    M --> Q
    N --> Q
    O --> Q
    Q --> R["AggregatedResult"]
```

## Profiling & Decision Tracing

```mermaid
flowchart TD
    A["Evaluation Start"] --> B["Create ProfilingRecord"]
    B --> C["Record: tier_counts, content_size"]
    C --> D["Record: pre_filter duration"]
    D --> E["Record: evaluate duration by tier"]
    E --> F["Record: post_process duration"]
    F --> G["Record: total_time_ms"]
    G --> H{"Error Occurred?"}
    H -->|Yes| I["Record error message"]
    H -->|No| J["Record success metrics"]
    I --> K["Append to profiling_records"]
    J --> K
    K --> L{"Max Records Reached?"}
    L -->|Yes| M["Trim oldest records"]
    L -->|No| N["Keep all records"]
    M --> O["Available for query via get_statistics()"]
    N --> O
```
