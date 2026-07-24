# Monitoring Integration

## Component Diagram

The following diagram shows how the monitoring module integrates with the core engine, models, API layer, and external systems.

```mermaid
flowchart TD
    subgraph Core["Core Module (src/core/)"]
        RE["RuleEngine"]
        EP["EvaluationPipeline"]
        RD["RuleDispatcher"]
        RA["ResultAggregator"]
        EC["EngineConfig"]
    end

    subgraph Monitoring["Monitoring Module (src/monitoring/)"]
        MC["MetricsCollector"]
        EB["EventBus"]
        AM["AlertManager"]
        DASH["MonitoringDashboard"]
        HC["HealthChecker"]
    end

    subgraph Models["Model Layer (src/models/)"]
        MonM["Monitoring Model\nAlertDefinition\nMetricData\nHealthStatus"]
        AuditM["Audit Model\nAuditEvent\nAuditTrail"]
    end

    subgraph API["API / Integration Layer"]
        REST["REST Endpoints"]
        WS["WebSocket Push"]
        PROM["Prometheus Scraper"]
        WEBHOOK["Webhook Dispatcher"]
    end

    subgraph External["External Systems"]
        PROM_SRV["Prometheus Server"]
        GRAFANA["Grafana Dashboard"]
        PAGER["PagerDuty / OpsGenie"]
        SLACK["Slack / Teams"]
        EMAIL["Email Notifications"]
        LOGS["Log Aggregator"]
    end

    RE -->|"record('evaluation.count', ...)"| MC
    RE -->|"record('evaluation.duration_ms', ...)"| MC
    EP -->|"record('pipeline.duration_ms', ...)"| MC
    RD -->|"record('dispatcher.count', ...)"| MC
    RA -->|"record('aggregation.count', ...)"| MC
    EC -->|"record('config.reloads', ...)"| MC

    MC -->|"publish metric updates"| EB

    EB -->|"alert evaluation events"| AM
    EB -->|"metric data for display"| DASH
    EB -->|"health status events"| HC

    AM -->|"create Alert from"| MonM
    DASH -->|"query metrics from"| MC
    HC -->|"update HealthStatus"| MonM

    AM -->|"audit log events"| AuditM
    HC -->|"audit log events"| AuditM

    MC -->|"export_data('prometheus', ...)"| PROM
    PROM -->|"GET /metrics"| PROM_SRV
    PROM_SRV --> GRAFANA

    AM -->|"notify"| PAGER
    AM -->|"notify"| SLACK
    AM -->|"notify"| EMAIL

    DASH -->|"REST API"| REST
    DASH -->|"WebSocket"| WS
    REST --> GRAFANA

    HC -->|"health check probes"| RE
    HC -->|"health check probes"| RD
    HC -->|"health check probes"| EP
    HC -->|"health check probes"| RA
    HC -->|"health check probes"| MC
    HC -->|"health check probes"| EB
    HC -->|"health check probes"| AM
```

## Cross-Module Monitoring Integration Sequence

The following sequence diagram shows how the monitoring module interacts with core components during a complete monitoring lifecycle.

```mermaid
sequenceDiagram
    participant Core as Core Component
    participant MC as MetricsCollector
    participant EB as EventBus
    participant AM as AlertManager
    participant DASH as Dashboard
    participant HC as HealthChecker
    participant EXT as External Systems

    Core->>MC: record("evaluation.duration_ms", 150.5)
    MC->>MC: store DataPoint
    MC->>EB: publish("metric.updated", {name, value})

    EB->>DASH: deliver metric update
    DASH->>DASH: update metric widgets
    DASH-->>EXT: WebSocket push to Grafana

    EB->>AM: deliver metric for alert evaluation
    AM->>AM: evaluate_condition(150.5)

    alt Threshold Exceeded
        AM->>AM: create Alert(severity=WARNING)
        AM->>AM: check escalation policy
        AM->>EB: publish("alert.created", {alert_id})

        EB->>DASH: deliver alert
        DASH->>DASH: update alert list

        AM->>EXT: send notification (Slack)
        AM->>EXT: send notification (Email)
    end

    loop Periodic Health Checks
        HC->>Core: health_check()
        Core-->>HC: HealthResult(HEALTHY, 5ms)

        HC->>HC: update CheckStatistics
        HC->>EB: publish("health.checked", {status})
        EB->>DASH: deliver health status
    end

    loop Metric Export Cycle
        MC->>MC: export_data("prometheus", ...)
        MC-->>EXT: Prometheus metrics endpoint
        EXT->>PROM_SRV: scrape /metrics
        PROM_SRV->>GRAFANA: render dashboard
    end

    alt System DEGRADED
        HC->>EB: publish("health.degraded", {checks})
        EB->>AM: evaluate for alert
        AM->>AM: create Alert(severity=ERROR)
        AM->>EXT: page on-call engineer
    end
```

## Prometheus Export Integration

The monitoring module exports metrics in Prometheus-compatible text format, allowing direct integration with Prometheus servers and Grafana dashboards.

```mermaid
flowchart LR
    subgraph Collectors["Internal Collectors"]
        MC["MetricsCollector\n(in-memory time series)"]
        RE["RuleEngine\n(Prometheus format)"]
        RD["RuleDispatcher\n(Prometheus format)"]
        EP["EvaluationPipeline\n(Prometheus format)"]
        RA["ResultAggregator\n(Prometheus format)"]
    end

    subgraph Aggregation["Prometheus Aggregation"]
        PROM["Prometheus Server\nscrape /metrics endpoint"]
    end

    subgraph Visualization["Visualization"]
        GRAF["Grafana Dashboards"]
    end

    subgraph Alerting["Alerting"]
        PROM_ALERT["Prometheus AlertManager"]
    end

    MC -->|"export_data('prometheus')"| PROM
    RE -->|"export_statistics_prometheus()"| PROM
    RD -->|"to_prometheus()"| PROM
    EP -->|"to_prometheus()"| PROM
    RA -->|"to_prometheus()"| PROM

    PROM --> GRAF
    PROM --> PROM_ALERT

    subgraph Metrics["Exported Metrics (examples)"]
        M1["rule_engine_total_evaluations 1234"]
        M2["rule_engine_average_time_ms 45.2"]
        M3["rule_engine_cache_hits 567"]
        M4["rule_dispatcher_total_dispatched 890"]
        M5["evaluation_pipeline_total 456"]
        M6["result_aggregator_total 234"]
        M7["rule_engine_config_load_count 12"]
    end

    PROM --- M1
    PROM --- M2
    PROM --- M3
    PROM --- M4
    PROM --- M5
    PROM --- M6
    PROM --- M7
```

## Webhook Notification Integration

```mermaid
sequenceDiagram
    participant Core as Core Engine
    participant AM as AlertManager
    participant WH as Webhook Dispatcher
    participant Target as External Webhook Target

    Core->>AM: critical violation detected
    AM->>AM: create Alert(severity=CRITICAL)
    AM->>AM: lookup notification_channels

    alt channel == "webhook"
        AM->>WH: dispatch(alert, webhook_urls)
        WH->>WH: build JSON payload

        loop For each webhook URL
            WH->>WH: apply rate limiting

            loop Retry up to max_retries
                WH->>Target: HTTP POST (JSON)
                alt 2xx Success
                    Target-->>WH: OK
                    WH->>WH: mark delivered
                else 4xx/5xx
                    Target-->>WH: Error
                    WH->>WH: log warning, backoff
                end
            end

            alt All retries failed
                WH->>AM: notify delivery failure
                AM->>AM: log alert delivery error
            end
        end
    end
```

## Event Bus Integration Patterns

```mermaid
flowchart TD
    subgraph Events["Event Types Published"]
        E1["metric.updated"]
        E2["alert.created"]
        E3["alert.acknowledged"]
        E4["alert.resolved"]
        E5["alert.escalated"]
        E6["health.checked"]
        E7["health.changed"]
        E8["evaluation.completed"]
    end

    subgraph Producers["Event Producers"]
        P1["MetricsCollector"]
        P2["AlertManager"]
        P3["HealthChecker"]
        P4["RuleEngine"]
        P5["Dashboard"]
    end

    subgraph Consumers["Event Consumers"]
        C1["AlertManager\n(monitors metric events)"]
        C2["Dashboard\n(refreshes on events)"]
        C3["Audit Logger\n(logs all events)"]
        C4["Webhook Sender\n(forwards critical events)"]
        C5["External Integrations\n(connects via adapter)"]
    end

    P1 -->|publishes| E1
    P2 -->|publishes| E2
    P2 -->|publishes| E3
    P2 -->|publishes| E4
    P2 -->|publishes| E5
    P3 -->|publishes| E6
    P3 -->|publishes| E7
    P4 -->|publishes| E8
    P5 -->|publishes| E1

    E1 -->|subscribed by| C1
    E1 -->|subscribed by| C2
    E1 -->|subscribed by| C3
    E2 -->|subscribed by| C2
    E2 -->|subscribed by| C3
    E2 -->|subscribed by| C4
    E2 -->|subscribed by| C5
    E3 -->|subscribed by| C3
    E4 -->|subscribed by| C3
    E4 -->|subscribed by| C5
    E5 -->|subscribed by| C3
    E5 -->|subscribed by| C4
    E5 -->|subscribed by| C5
    E6 -->|subscribed by| C2
    E6 -->|subscribed by| C3
    E7 -->|subscribed by| C2
    E7 -->|subscribed by| C3
    E7 -->|subscribed by| C5
    E8 -->|subscribed by| C3
    E8 -->|subscribed by| C5
```

## Data Export Integration

```mermaid
flowchart LR
    subgraph Collect["Data Collection"]
        MC["MetricsCollector\nDataPoints in memory"]
    end

    subgraph Formats["Export Formats"]
        F1["CSV\ncomma-separated\nwith headers"]
        F2["JSON\nstructured\narray of objects"]
        F3["Prometheus\nHELP/TYPE format\nfor scraping"]
        F4["Internal Dict\nin-memory\nsnapshot"]
    end

    subgraph Destinations["Export Destinations"]
        D1["File System\n(.csv, .json files)"]
        D2["HTTP Endpoint\n(Prometheus /metrics)"]
        D3["Database\n(historical storage)"]
        D4["API Response\n(live dashboard data)"]
    end

    subgraph UseCases["Use Cases"]
        U1["Historical Analysis"]
        U2["Real-time Monitoring"]
        U3["Compliance Reporting"]
        U4["Capacity Planning"]
        U5["Billing/Usage Stats"]
    end

    MC --> F1
    MC --> F2
    MC --> F3
    MC --> F4

    F1 --> D1
    F1 --> U1
    F2 --> D1
    F2 --> D3
    F2 --> D4
    F2 --> U3
    F3 --> D2
    F3 -->|"Prometheus scrapes"| U2
    F3 --> U4
    F4 --> D4
    F4 --> U5
```
