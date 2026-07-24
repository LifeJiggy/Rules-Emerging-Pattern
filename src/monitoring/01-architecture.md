# Monitoring Architecture

## Component Diagram

The following diagram shows how the monitoring components connect: metrics flow from collectors through the event bus to consumers.

```mermaid
flowchart LR
    subgraph DataSources["Data Sources"]
        RE["RuleEngine\nMetrics"]
        EP["EvaluationPipeline\nMetrics"]
        RD["RuleDispatcher\nMetrics"]
        RA["ResultAggregator\nMetrics"]
        EC["EngineConfig\nMetrics"]
        SYS["System\nMetrics"]
    end

    subgraph Collection["Collection Layer"]
        MC["MetricsCollector\n- record()\n- query()\n- aggregate()\n- export()"]
    end

    subgraph Transport["Transport Layer"]
        EB["EventBus\n- publish()\n- subscribe()\n- filter()\n- deliver()"]
    end

    subgraph Processing["Processing Layer"]
        AM["AlertManager\n- evaluate()\n- escalate()\n- suppress()\n- notify()"]
        HC["HealthChecker\n- register()\n- run_check()\n- get_status()"]
    end

    subgraph Presentation["Presentation Layer"]
        DASH["MonitoringDashboard\n- widgets\n- trends\n- snapshots\n- export"]
    end

    subgraph Storage["Storage Layer"]
        MEM["In-Memory\nTime Series"]
        CSV["CSV Export"]
        JSON["JSON Export"]
        PROM["Prometheus\nFormat"]
    end

    RE -->|"record metrics"| MC
    EP -->|"record metrics"| MC
    RD -->|"record metrics"| MC
    RA -->|"record metrics"| MC
    EC -->|"record metrics"| MC
    SYS -->|"record metrics"| MC

    MC -->|"publish data points"| EB
    MC -->|"direct feed"| DASH

    EB -->|"alert events"| AM
    EB -->|"metric updates"| DASH
    EB -->|"health events"| HC

    AM -->|"alert status"| DASH
    HC -->|"health status"| DASH

    MC -->|"export"| MEM
    MC -->|"export"| CSV
    MC -->|"export"| JSON
    MC -->|"export"| PROM

    DASH -->|"render"| MEM
```

## Alert Lifecycle Flow

The following flowchart illustrates the complete lifecycle of an alert from creation through resolution.

```mermaid
flowchart TD
    A["Metric Data Point"] --> B["Evaluate Against AlertRules"]

    B --> C{"Condition Met?"}
    C -->|No| D["No Alert - Continue Monitoring"]
    C -->|Yes| E{"In Cooldown Period?"}
    E -->|Yes| F["Skip - Cooldown Active"]
    E -->|No| G{"Max Alerts/Hour Reached?"}
    G -->|Yes| H["Skip - Rate Limited"]
    G -->|No| I["Create Alert: Status = TRIGGERED"]

    I --> J["Assign Severity"]
    J --> K["Assign to Alert Group (if configured)"]

    K --> L{"Group Window Active?"}
    L -->|Yes| M["Add to existing group"]
    L -->|No| N["Create new alert group"]

    M --> O["Notify via Notification Channels"]
    N --> O

    O --> P["Alert is ACTIVE"]
    P --> Q{"Acknowledged?"}
    Q -->|Yes| R["Status = ACKNOWLEDGED"]
    Q -->|No| S{"Auto-Escalate Time?"}

    S -->|Yes| T["Run Escalation Policy"]
    T --> U["Increment escalation_level"]
    U --> V["Notify escalation targets"]
    V --> W["Status = ESCALATED"]
    W --> Q

    S -->|No| X{"Auto-Resolve Time?"}
    X -->|Yes| Y["Status = RESOLVED"]
    X -->|No| AA{"Manual Resolve?"}
    AA -->|Yes| Y

    R --> AB{"Issue Resolved?"}
    AB -->|Yes| AC["Status = RESOLVED"]
    AB -->|No| AD["Keep ACKNOWLEDGED"]

    Y --> AE["Record resolution time"]
    AE --> AF["Log to audit trail"]
    AF --> AG["Alert lifecycle complete"]

    AD --> Q
    Q --> S

    style I fill:#ffcdd2
    style Y fill:#c8e6c9
    style W fill:#fff3e0
```

## Dashboard Data Flow Diagram

```mermaid
flowchart TD
    subgraph Sources["Metric Sources"]
        M1["Real-time metrics\nfrom MetricsCollector"]
        M2["Historical data\nfrom storage"]
        M3["Alert status\nfrom AlertManager"]
        M4["Health status\nfrom HealthChecker"]
    end

    subgraph Dashboard["MonitoringDashboard"]
        W1["Widget: Line Chart"]
        W2["Widget: Gauge"]
        W3["Widget: Table"]
        W4["Widget: Heatmap"]
        W5["Widget: Status Indicator"]
        W6["Widget: Alert List"]

        TW["Trend Analyzer"]
        SW["Snapshot Manager"]
        EW["Export Engine"]
    end

    subgraph Queries["Query Types"]
        Q1["get_metric_history(name, duration)"]
        Q2["analyze_trend(name, window)"]
        Q3["get_alerts(status, severity, limit)"]
        Q4["get_summary()"]
        Q5["export_data(format, metrics)"]
    end

    subgraph Output["Output Formats"]
        O1["JSON API Response"]
        O2["CSV Download"]
        O3["JSON Export"]
        O4["Snapshot Archive"]
        O5["Real-time Push"]
    end

    M1 --> W1
    M1 --> W2
    M1 --> W3
    M2 --> W1
    M2 --> W4
    M3 --> W6
    M4 --> W5

    W1 --> TW
    W2 --> SW
    W3 --> EW

    TW --> Q2
    SW --> Q4
    EW --> Q5
    W6 --> Q3
    W5 --> Q4

    Q1 --> O1
    Q2 --> O1
    Q3 --> O1
    Q4 --> O1
    Q5 --> O2
    Q5 --> O3
    SW --> O4
    M1 --> O5
```

## Event Bus Architecture

```mermaid
flowchart LR
    subgraph Publishers["Event Publishers"]
        P1["RuleEngine"]
        P2["MetricsCollector"]
        P3["AlertManager"]
        P4["HealthChecker"]
        P5["External Services"]
    end

    subgraph Bus["EventBus"]
        IN["Ingress Queue"]
        FILTER["Event Filter"]
        ROUTE["Event Router"]
        DELIVERY["Delivery Manager"]
        RECORDS["Delivery Records"]
        STATS["Subscriber Statistics"]
    end

    subgraph Subscribers["Event Subscribers"]
        S1["AlertManager"]
        S2["Dashboard"]
        S3["Audit Logger"]
        S4["Webhook Sender"]
        S5["Custom Handlers"]
    end

    subgraph Guarantees["Delivery Guarantees"]
        G1["AT_MOST_ONCE"]
        G2["AT_LEAST_ONCE"]
        G3["EXACTLY_ONCE"]
    end

    P1 -->|"publish(event)"| IN
    P2 -->|"publish(event)"| IN
    P3 -->|"publish(event)"| IN
    P4 -->|"publish(event)"| IN
    P5 -->|"publish(event)"| IN

    IN --> FILTER
    FILTER --> ROUTE

    ROUTE --> DELIVERY
    DELIVERY --> G1
    DELIVERY --> G2
    DELIVERY --> G3

    G1 --> S1
    G2 --> S2
    G2 --> S3
    G3 --> S4
    G2 --> S5

    DELIVERY --> RECORDS
    DELIVERY --> STATS
```

## Health Check Architecture

```mermaid
flowchart TD
    subgraph Checks["Registered Health Checks"]
        C1["rule_engine_health"]
        C2["dispatcher_health"]
        C3["pipeline_health"]
        C4["aggregator_health"]
        C5["database_connectivity"]
        C6["cache_connectivity"]
    end

    subgraph Runner["Health Check Runner"]
        SCHED["Scheduler\n(interval per check)"]
        EXEC["Executor\n(runs check handler)"]
        TIMEOUT["Timeout Monitor"]
        RESULT["Result Collector"]
    end

    subgraph Analysis["Analysis"]
        STATS["CheckStatistics\n- total_runs\n- avg_response_time\n- uptime_percentage"]
        STATUS["HealthStatus\n- HEALTHY\n- DEGRADED\n- UNHEALTHY"]
        DEGRADE["Degradation Detection\n- consecutive_failures\n- failure_threshold"]
    end

    subgraph Output["Output"]
        SUM["get_summary()"]
        ALL["get_status()"]
        CHECK["run_check(name)"]
        PROM["Prometheus Export"]
    end

    C1 --> SCHED
    C2 --> SCHED
    C3 --> SCHED
    C4 --> SCHED
    C5 --> SCHED
    C6 --> SCHED

    SCHED --> EXEC
    EXEC --> TIMEOUT
    TIMEOUT --> RESULT

    RESULT --> STATS
    STATS --> STATUS
    STATS --> DEGRADE

    DEGRADE -->|"failures >= threshold"| STATUS

    STATUS --> SUM
    STATUS --> ALL
    STATUS --> CHECK
    STATUS --> PROM
```
