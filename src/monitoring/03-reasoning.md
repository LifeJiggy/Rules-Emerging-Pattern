# Alert & Health Reasoning

## Alert Condition Evaluation Flow

The following flowchart shows the complete decision process for evaluating alert conditions, determining severity, and routing notifications.

```mermaid
flowchart TD
    A["Metric Value Received"] --> B["Load AlertRule for metric"]
    B --> C["comparison_operator?"]

    C -->|"greater_than"| D["value > threshold?"]
    C -->|"less_than"| E["value < threshold?"]
    C -->|"equal_to"| F["value == threshold?"]
    C -->|"not_equal_to"| G["value != threshold?"]
    C -->|"greater_than_or_equal"| H["value >= threshold?"]
    C -->|"less_than_or_equal"| I["value <= threshold?"]
    C -->|"percentage_change"| J["abs(value - threshold) / threshold > 0.1?"]

    D -->|No| K["Condition NOT Met - No Alert"]
    E -->|No| K
    F -->|No| K
    G -->|No| K
    H -->|No| K
    I -->|No| K
    J -->|No| K

    D -->|Yes| L["Condition Met"]
    E -->|Yes| L
    F -->|Yes| L
    G -->|Yes| L
    H -->|Yes| L
    I -->|Yes| L
    J -->|Yes| L

    L --> M{"In Cooldown Period?"}
    M -->|Yes, cooldown_minutes remaining| N["Skip - Cooldown Active"]
    M -->|No| O{"Max Alerts/Hour Reached?"}
    O -->|Yes, >= max_alerts_per_hour| P["Skip - Rate Limited"]
    O -->|No| Q{"Alert Suppressed?"}
    Q -->|Yes| R["Skip - Suppressed"]
    Q -->|No| S["Proceed to Create Alert"]

    S --> T["Determine Alert Severity"]
    T --> U{"Severity based on:"}

    U -->|"Rule severity"| V["Use AlertRule.severity"]
    U -->|"Value magnitude"| W{"value vs threshold ratio?"}
    W -->|"ratio >= 3x"| X["UPGRADE to CRITICAL"]
    W -->|"ratio >= 2x"| Y["UPGRADE to ERROR"]
    W -->|"ratio >= 1.5x"| Z["UPGRADE to WARNING"]
    W -->|"ratio < 1.5x"| AA["Keep base severity"]

    V --> AB["Create Alert object"]
    X --> AB
    Y --> AB
    Z --> AB
    AA --> AB

    AB --> AC["Assign status = TRIGGERED"]
    AC --> AD["Set alert_id, timestamp, source"]

    AD --> AE{"Group Window?"}
    AE -->|"Yes, group_window_seconds > 0"| AF{"Existing Group\nfor Same Condition?"}
    AF -->|Yes| AG["Add to existing AlertGroup"]
    AF -->|No| AH["Create new AlertGroup"]
    AE -->|No| AI["Standalone alert"]

    AG --> AJ["Notify via notification_channels"]
    AH --> AJ
    AI --> AJ

    AJ --> AK["Log alert creation"]
    AK --> AL["Publish alert.created event"]
    AL --> AM["Alert is now ACTIVE"]
```

## Health Status Determination

The following decision tree shows how the HealthChecker determines aggregate system health based on individual check results.

```mermaid
flowchart TD
    A["Health Check Request"] --> B["Run all registered checks"]
    B --> C["Collect individual HealthResults"]

    C --> D{"Any check UNHEALTHY?"}
    D -->|Yes| E{"Number of UNHEALTHY checks?"}

    E -->|">= 50% of total"| F["Overall Status: UNHEALTHY"]
    E -->|"< 50% but >= 1"| G["Overall Status: DEGRADED"]

    D -->|No| H{"Any check DEGRADED?"}
    H -->|Yes, >= 1| G
    H -->|No| I{"Any check UNKNOWN?"}
    I -->|Yes| J["Overall Status: DEGRADED\n(with unknown checks note)"]
    I -->|No| K["Overall Status: HEALTHY"]

    F --> L["Trigger UNHEALTHY notification"]
    G --> M["Trigger DEGRADED notification"]
    K --> N["System healthy - no notification"]

    L --> O["Update check statistics"]
    M --> O
    J --> O
    N --> O

    subgraph PerCheck["Per-Check Status Logic"]
        P["Check executed"] --> Q{"Handler returned\nsuccessfully?"}
        Q -->|No| R["Status = UNKNOWN"]
        Q -->|Yes| S{"Response time <\ntimeout_seconds?"}
        S -->|No| T["Status = UNHEALTHY"]
        S -->|Yes| U{"consecutive_failures >=\nfailure_threshold?"}
        U -->|Yes| V["Status = UNHEALTHY"]
        U -->|No| W{"consecutive_failures >=\ndegradation_threshold?"}
        W -->|Yes| X["Status = DEGRADED"]
        W -->|No| Y["Status = HEALTHY"]
    end

    B --> P
    R --> C
    T --> C
    V --> C
    X --> C
    Y --> C
```

## Trend Detection Logic

The dashboard's trend analyzer uses statistical methods to detect anomalies and compute trend directions.

```mermaid
flowchart TD
    A["Metric History Data"] --> B["Compute baseline statistics"]

    B --> C["Calculate historical_avg\n(mean of values in window)"]
    C --> D["Calculate historical_std\n(standard deviation)"]
    D --> E["Get current_value\n(latest data point)"]

    E --> F["Compute change_percent\n= (current - avg) / avg * 100"]

    F --> G{"change_percent > 0?"}
    G -->|Yes| H["trend_direction = UP"]
    G -->|No, < 0| I["trend_direction = DOWN"]
    G -->|"== 0"| J["trend_direction = STABLE"]

    H --> K{"|change_percent| > threshold?"}
    I --> K
    J --> L["is_anomalous = False"]

    K -->|"Yes, > anomaly_threshold"| M["is_anomalous = True"]
    K -->|"No"| L

    M --> N{"Current outside\n2 std deviations?"}
    N -->|Yes| O["confidence = HIGH (0.95)"]
    N -->|No, outside 1 std| P["confidence = MEDIUM (0.75)"]
    N -->|No, within 1 std| Q["confidence = LOW (0.50)"]

    L --> R["confidence = HIGH (0.95)"]

    O --> S["Build TrendResult"]
    P --> S
    Q --> S
    R --> S

    S --> T{"Anomalous + Significant?"}
    T -->|Yes| U["Trigger trend alert"]
    T -->|No| V["Log trend for dashboard"]

    U --> W["Publish trend.anomaly event"]
    W --> X["AlertManager may create alert"]

    subgraph ThresholdConfig["Configurable Thresholds"]
        TA["anomaly_threshold: 10%"]
        TD["deviation_threshold: 2 std"]
        TW["window_size: 60 minutes"]
    end

    K --> TA
    N --> TD
    C --> TW
```

## Suppression Logic

```mermaid
flowchart TD
    A["Alert about to be created"] --> B{"Match suppression rules?"}

    B --> C{"Suppression Type?"}

    C -->|"maintenance_window"| D{"Current time within\nmaintenance window?"}
    D -->|Yes| E["SUPPRESS alert"]
    D -->|No| F["Allow alert"]

    C -->|"alert_deduplication"| G{"Identical alert already\nACTIVE/ACKNOWLEDGED?"}
    G -->|Yes| H["SUPPRESS - deduplicate"]
    G -->|No| I["Allow alert"]

    C -->|"component_suppression"| J{"Suppressed component\nmatches alert source?"}
    J -->|Yes| K["SUPPRESS - component muted"]
    J -->|No| L["Allow alert"]

    C -->|"rate_limiting"| M{"Alerts/hour >\nmax_alerts_per_hour?"}
    M -->|Yes| N["SUPPRESS - rate limited"]
    M -->|No| O["Allow alert"]

    E --> P["Log suppressed alert"]
    H --> P
    K --> P
    N --> P

    P --> Q["Update suppression counter"]
    Q --> R["No notification sent"]

    F --> S["Create alert normally"]
    I --> S
    L --> S
    O --> S

    S --> T["Send notification"]
    T --> U["Alert lifecycle proceeds"]
```

## Escalation Policy Reasoning

```mermaid
flowchart TD
    A["Alert CREATED / ACKNOWLEDGED"] --> B["Load EscalationPolicy"]
    B --> C["Check escalation_level"]

    C --> D{"escalation_level >= max_level?"}
    D -->|Yes| E["No further escalation possible"]
    D -->|No| F{"Delay elapsed since\nlast escalation?"}

    F -->|"No, delay_minutes not elapsed"| G["Wait for delay period"]
    G --> F

    F -->|Yes| H["Execute escalation step"]

    H --> I["Increment escalation_level"]
    I --> J["Notify escalation targets:"]

    J --> K{"target_role?"}
    K -->|"engineer"| L["Notify on-call engineer"]
    K -->|"team_lead"| M["Notify team lead"]
    K -->|"manager"| N["Notify engineering manager"]
    K -->|"director"| O["Notify director"]
    K -->|"all"| P["Notify all above"]

    L --> Q["Use message_template for context"]
    M --> Q
    N --> Q
    O --> Q
    P --> Q

    Q --> R["Record escalation in alert"]
    R --> S["Update AlertStatus = ESCALATED"]
    S --> T["Publish alert.escalated event"]

    T --> U{"Repeat escalation?"}
    U -->|Yes| C
    U -->|No| V["Escalation complete"]
```

## Data Pruning & Retention Logic

```mermaid
flowchart TD
    A["Pruning Cycle Triggered"] --> B["Iterate all metric definitions"]
    B --> C["For each metric:"]

    C --> D{"retention_days\nconfigured?"}
    D -->|Yes| E["Calculate cutoff timestamp\n= now - retention_days"]
    E --> F["Remove DataPoints\nwhere timestamp < cutoff"]

    F --> G{"Data points >\nmax_data_points?"}
    D -->|No| G

    G -->|Yes| H["Sort by timestamp (ascending)"]
    H --> I["Remove oldest data points\nuntil under max_data_points"]
    I --> J["Log pruning summary"]
    G -->|No| K["No pruning needed"]

    J --> L["Update pruning statistics"]
    L --> M{"Next check in\nprune_interval_minutes?"}

    M -->|Wait for interval| N["Sleep until next cycle"]
    N --> A

    subgraph RetentionConfig["Configuration"]
        R1["default_retention_days: 30"]
        R2["default_max_points: 100000"]
        R3["prune_interval_minutes: 60"]
    end

    E --> R1
    H --> R2
    M --> R3
```
