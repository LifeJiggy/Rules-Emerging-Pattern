# Monitoring Data Flow

## Metrics Collection Sequence

The following sequence diagram shows how a metric is collected, processed through the event bus, and triggers an alert.

```mermaid
sequenceDiagram
    participant System as System Component
    participant MC as MetricsCollector
    participant EB as EventBus
    participant AM as AlertManager
    participant DASH as Dashboard
    participant HC as HealthChecker

    System->>MC: record("evaluation.count", 1, {tier="safety"})
    MC->>MC: acquire lock
    MC->>MC: create DataPoint(value=1, timestamp=now)
    MC->>MC: append to _metrics["evaluation.count"]
    MC->>MC: release lock
    MC-->>System: recorded

    System->>MC: record("evaluation.duration_ms", 150.5, {tier="safety"})
    MC->>MC: create DataPoint(value=150.5, timestamp=now)
    MC->>MC: append to metric list
    MC-->>System: recorded

    MC->>EB: publish(Event(metric.updated, {name, value, labels}))
    EB->>EB: create Event with event_id
    EB->>EB: queue event for delivery

    par Delivery to Subscribers
        EB->>AM: deliver event to AlertManager subscriber
        AM->>AM: evaluate alert conditions

        alt Condition Met
            AM->>AM: create Alert
            AM->>EB: publish(alert.triggered, {alert_id, severity})
            EB->>DASH: deliver alert update
            DASH->>DASH: refresh alert widgets
        end

        EB->>DASH: deliver metric update
        DASH->>DASH: update metric widgets

        EB->>HC: deliver health event
        HC->>HC: update check statistics
    end

    System->>MC: query("evaluation.duration_ms", start, end, "avg")
    MC->>MC: filter data points by time range
    MC->>MC: compute average aggregation
    MC-->>System: AggregatedValue(avg=145.2, count=100)
```

## Health Check Flow

```mermaid
sequenceDiagram
    participant Scheduler as Health Check Scheduler
    participant HC as HealthChecker
    participant Handler as Check Handler
    participant Stats as CheckStatistics
    participant Status as Aggregated Status

    loop Every N seconds (per check)
        Scheduler->>HC: run_check("rule_engine")
        HC->>Handler: execute handler function

        alt Handler Success
            Handler-->>HC: HealthResult(status=HEALTHY, response_time=5ms)
            HC->>Stats: update statistics (success)
            Stats->>Stats: total_runs++
            Stats->>Stats: successful_runs++
            Stats->>Stats: update avg_response_time
            Stats->>Stats: consecutive_failures = 0
        else Handler Failure
            Handler-->>HC: HealthResult(status=UNHEALTHY, error="timeout")
            HC->>Stats: update statistics (failure)
            Stats->>Stats: total_runs++
            Stats->>Stats: failed_runs++
            Stats->>Stats: consecutive_failures++
        else Handler Timeout
            HC->>HC: timeout error
            HC->>Stats: record failure
            Stats->>Stats: total_runs++
            Stats->>Stats: failed_runs++
            Stats->>Stats: consecutive_failures++
        end

        Stats->>Status: check degradation

        alt consecutive_failures >= failure_threshold
            Status->>Status: mark check as UNHEALTHY
            HC->>EB: publish(health.status_changed, {check, status})
        else consecutive_failures >= degradation_threshold
            Status->>Status: mark check as DEGRADED
        else
            Status->>Status: mark check as HEALTHY
        end

        HC-->>Scheduler: HealthResult returned
    end
```

## Metrics Aggregation Pipeline

```mermaid
flowchart LR
    subgraph Raw["Raw Data Points"]
        A["DataPoint(value=10, ts=T1)"]
        B["DataPoint(value=20, ts=T2)"]
        C["DataPoint(value=30, ts=T3)"]
        D["DataPoint(value=40, ts=T4)"]
        E["DataPoint(value=50, ts=T5)"]
    end

    subgraph Filtering["Filtering"]
        F["Select by metric name"]
        G["Filter by time range"]
        H["Filter by labels"]
    end

    subgraph Aggregation["Aggregation Functions"]
        I["AVG: sum(values) / count"]
        J["MIN: min(values)"]
        K["MAX: max(values)"]
        L["SUM: sum(values)"]
        M["COUNT: len(values)"]
        N["P50: median value"]
        O["P95: 95th percentile"]
        P["P99: 99th percentile"]
        Q["RATE: delta / time_delta"]
    end

    subgraph Window["Windowing"]
        R["Tumbling Window\n(fixed intervals)"]
        S["Sliding Window\n(overlapping)"]
        T["Session Window\n(activity-based)"]
    end

    subgraph Output["Aggregated Results"]
        U["AggregatedValue(value, aggregation, count)"]
        V["Time Series Array"]
        W["Statistics Dict\n{mean, min, max, p95, ...}"]
    end

    A --> F
    B --> F
    C --> F
    D --> F
    E --> F

    F --> G --> H

    H --> I
    H --> J
    H --> K
    H --> L
    H --> M
    H --> N
    H --> O
    H --> P
    H --> Q

    I --> R
    J --> R
    K --> R
    L --> S
    M --> S
    N --> T
    O --> T
    P --> T
    Q --> T

    R --> U
    S --> V
    T --> W
```

## Alert Evaluation Data Flow

```mermaid
sequenceDiagram
    participant MC as MetricsCollector
    participant AM as AlertManager
    participant AlertDef as AlertDefinition
    participant AlertObj as Alert Object
    participant Notif as Notification Channel
    participant EB as EventBus

    MC->>AM: new metric value (evaluation.error_rate, 0.15)

    AM->>AM: iterate alert rules

    loop For each AlertRule
        AM->>AlertDef: evaluate_condition(0.15)
        AlertDef->>AlertDef: 0.15 > 0.10 threshold?

        alt Condition Met
            AM->>AM: check cooldown
            AM->>AM: check rate limit
            AM->>AM: check suppression rules

            alt Can Alert
                AM->>AlertObj: create Alert(severity=WARNING)
                AlertObj->>AlertObj: assign alert_id
                AlertObj->>AlertObj: set status = TRIGGERED

                AM->>Notif: send notification

                alt Escalation Configured
                    AM->>AM: schedule escalation check
                end

                AM->>EB: publish(alert.created, {alert_id, severity})
            else Suppressed
                AM->>AM: log skipped alert
            end
        end
    end
```

## Event Bus Message Routing

```mermaid
flowchart TD
    A["Publisher calls publish(event)"] --> B["EventBus receives event"]
    B --> C["Generate unique event_id"]
    C --> D["Timestamp the event"]
    D --> E["Add to internal event queue"]

    E --> F["Event Router iterates subscribers"]
    F --> G["For each subscriber:"]

    G --> H{"Event type matches\nsubscriber.event_types?"}
    H -->|No| I["Skip subscriber"]
    H -->|Yes| J{"Subscriber has\nEventFilter?"}

    J -->|No| K["Deliver event to handler"]
    J -->|Yes| L{"Event passes\nfilter?"}
    L -->|Yes| K
    L -->|No| M["Skip - filtered out"]

    K --> N["Call subscriber.handler(event)"]
    N --> O{"Handler executes\nsuccessfully?"}

    O -->|Yes| P["Record DeliveryRecord(status=delivered)"]
    O -->|No| Q{"Retry count <\nmax retries?"}

    Q -->|Yes| R["Increment retry_count"]
    R --> S["Re-queue event for retry"]
    S --> K

    Q -->|No| T["Record DeliveryRecord(status=failed)"]
    T --> U["Log delivery failure"]

    P --> V["Update SubscriberStatistics"]
    U --> V

    I --> W["Next subscriber"]
    M --> W
    V --> W

    W --> X{"More subscribers?"}
    X -->|Yes| G
    X -->|No| Y["Event delivery complete"]
```
