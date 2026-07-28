# Rules-Emerging-Pattern: AI Guardrails and Consistency Framework

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-100%25-brightgreen.svg)]()

A production-grade, modular rules engine providing strict guardrails, consistency enforcement, and safety boundaries for AI systems through a sophisticated tiered architecture with **15 modular subsystems**, **Python + TypeScript SDKs**, and full compliance support.

```mermaid
flowchart TB
    subgraph External
        SDK_PY["Python SDK"]
        SDK_TS["TypeScript SDK"]
        CLI["CLI"]
    end

    subgraph API_Layer
        REST["REST API"]
        WS["WebSocket"]
        GQL["GraphQL"]
        AUTH["API Auth"]
        MW["Middleware"]
    end

    subgraph Core
        RE["Rule Engine"]
        ED["Rule Dispatcher"]
        EP["Evaluation Pipeline"]
        RA["Result Aggregator"]
        TIER["Tier Orchestrator"]
    end

    subgraph Models
        RM["Rule Models"]
        VM["Validation Models"]
        CM["Conflict Models"]
        MM["Monitor Models"]
        AM["Audit Models"]
    end

    subgraph Services
        LEARN["Learning Engine"]
        COMP["Compliance"]
        PRIV["Privacy"]
        SKILL["Skills"]
        MEM["Memory"]
        STORE["Storage"]
    end

    subgraph Observability
        METRICS["Metrics Collector"]
        ALERTS["Alert Manager"]
        DASH["Dashboard"]
        HEALTH["Health Checker"]
        EVENTS["Event Bus"]
    end

    subgraph Tools
        ANALYZER["Rule Analyzer"]
        DEBUG["Debug Tool"]
        PROFILER["Profiler"]
        TEST["Test Runner"]
        VIZ["Visualizer"]
    end

    subgraph Utils
        VALIDATORS["Validators"]
        SERIALIZERS["Serializers"]
        CACHE["Cache Manager"]
        CONFIG["Config Loader"]
        RATELIMIT["Rate Limiter"]
    end

    External --> API_Layer
    API_Layer --> Core
    Core --> Models
    Core --> Services
    Services --> Models
    Core --> Observability
    Services --> Observability
    Tools --> Core
    Tools --> Services
    Utils -.-> API_Layer
    Utils -.-> Core
    Utils -.-> Services
```

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Module Overview](#module-overview)
- [Core Engine Flow](#core-engine-flow)
- [Quick Start](#quick-start)
- [SDKs](#sdks)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Installation](#installation)
- [License](#license)

---

## System Architecture

### High-Level Component Interaction

```mermaid
sequenceDiagram
    participant C as Client (SDK/CLI)
    participant API as API Layer
    participant MW as Middleware
    participant RE as Rule Engine
    participant LEARN as Learning
    participant COMP as Compliance
    participant PRIV as Privacy
    participant MON as Monitoring
    participant STORE as Storage

    C->>API: Request
    API->>MW: Process
    MW->>RE: Evaluate
    RE->>PRIV: Check Privacy
    PRIV-->>RE: Privacy Result
    RE->>COMP: Check Compliance
    COMP-->>RE: Compliance Result
    RE->>LEARN: Analyze Pattern
    LEARN-->>RE: Pattern Match
    RE->>STORE: Store Result
    STORE-->>RE: Stored
    RE-->>MW: Result
    MW->>MON: Log Metrics
    MW-->>API: Response
    API-->>C: Validation Result
```

### Tiered Rule Evaluation

```mermaid
flowchart TD
    Input["Input Content"] --> Safety{"Safety Tier - Strict"}
    Safety -->|Pass| Operational{"Operational Tier - Advisory"}
    Safety -->|Fail| Block["Block Content - Violation"]
    Operational -->|Pass| Preference{"Preference Tier - Adaptive"}
    Operational -->|Warning| Flag["Flag + Continue"]
    Preference -->|Match| Apply["Apply User Preferences"]
    Preference -->|No Match| Default["Use Default Behavior"]
    Flag --> Preference
    Apply --> Output["Validated Output"]
    Default --> Output
    Block --> Response["Error Response"]
```

---

## Module Overview

### Core Engine (`src/core/`)

```mermaid
classDiagram
    class RuleEngine {
        +evaluate(request) ValidationResult
        +evaluate_tiered(content, tier) ValidationResult
        +get_statistics() dict
        +shutdown() void
    }
    class RuleDispatcher {
        +dispatch(content, context) list
        +get_applicable_rules(context) list
    }
    class EvaluationPipeline {
        +run(content, rules) PipelineResult
        +run_batch(contents) list
    }
    class ResultAggregator {
        +aggregate(results) ValidationResult
        +score_results(results) float
    }
    class EngineConfig {
        +safety_rules string
        +operational_rules string
        +preference_rules string
    }
    class TierOrchestrator {
        +evaluate_tier(content, tier) TierResult
        +get_tier_metrics() dict
    }

    RuleEngine --> RuleDispatcher
    RuleEngine --> EngineConfig
    RuleEngine --> TierOrchestrator
    RuleDispatcher --> EvaluationPipeline
    EvaluationPipeline --> ResultAggregator
```

### Compliance (`src/compliance/`)

```mermaid
flowchart LR
    Input["Content"] --> Orchestrator["Compliance Orchestrator"]
    Orchestrator --> GDPR["GDPR Checker - Data Protection"]
    Orchestrator --> HIPAA["HIPAA Checker - Health Data"]
    Orchestrator --> PCI["PCI Checker - Payment Data"]
    Orchestrator --> SOX["SOX Checker - Financial Data"]
    GDPR --> Report["Compliance Report"]
    HIPAA --> Report
    PCI --> Report
    SOX --> Report
    Report --> Action{"Action Required?"}
    Action -->|Yes| Remediate["Remediate"]
    Action -->|No| Pass["Pass - Clear"]
```

### Monitoring (`src/monitoring/`)

```mermaid
flowchart TD
    S["System Events"] --> MC["Metrics Collector"]
    S --> HC["Health Checker"]
    MC --> EB["Event Bus"]
    HC --> EB
    EB --> AM["Alert Manager"]
    EB --> DASH["Dashboard"]
    AM -->|Critical| PAGER["PagerDuty"]
    AM -->|Warning| SLACK["Slack"]
    AM -->|Info| LOG["Log"]
    DASH --> GRAFANA["Grafana/Prometheus"]
```

### Learning (`src/learning/`)

```mermaid
sequenceDiagram
    participant FE as Feature Extractor
    participant PE as Pattern Engine
    participant TA as Trend Analyzer
    participant FL as Feedback Learner
    participant MT as Model Trainer

    Content->>FE: Extract Features
    FE->>PE: Feature Vector
    PE->>PE: Match Patterns
    PE->>TA: Pattern Data
    TA->>TA: Analyze Trends
    TA-->>FL: Trend Insights
    Feedback->>FL: User Feedback
    FL->>MT: Training Data
    MT->>MT: Train Model
    MT-->>PE: Updated Patterns
```

### Privacy (`src/privacy/`)

```mermaid
flowchart LR
    Input["Raw Content"] --> Classifier["Data Classifier - PII Detection"]
    Classifier -->|PII Found| Redact["Data Redactor - Masking"]
    Classifier -->|No PII| Pass["Pass Through"]
    Redact --> Consent["Consent Manager - Verify Consent"]
    Consent --> Anonymize["Anonymizer - Generalize/Suppress"]
    Anonymize --> Auditor["Privacy Auditor - Audit Trail"]
    Pass --> Output["Safe Output"]
    Auditor --> Output
```

### Skills (`src/skills/`)

```mermaid
flowchart TD
    Load["Skill Loader"] --> Registry["Skill Registry"]
    Registry --> Validator["Skill Validator"]
    Validator --> Executor["Skill Executor"]
    Executor -->|Execute| Skill1["Rule Skill 1"]
    Executor -->|Execute| Skill2["Rule Skill 2"]
    Executor -->|Execute| SkillN["Rule Skill N"]
    Skill1 --> Result["Aggregated Result"]
    Skill2 --> Result
    SkillN --> Result
```

### Storage (`src/storage/`)

```mermaid
flowchart LR
    subgraph Cache_Layer
        CS["Cache Store (Redis/Mem)"]
    end
    subgraph Persistent_Layer
        FS["File Store (Disk/S3)"]
        RS["Rule Storage (DB)"]
    end
    subgraph Operations
        BM["Backup Manager"]
        MM["Migration Manager"]
    end

    App["Application"] --> RS
    App --> CS
    CS -->|Miss| FS
    BM --> FS
    MM --> RS
```

### API Layer (`src/api/`)

```mermaid
sequenceDiagram
    participant Client
    participant MW as Middleware
    participant Auth as API Auth
    participant REST as REST API
    participant WS as WebSocket
    participant GQL as GraphQL

    Client->>MW: HTTP Request
    MW->>Auth: Authenticate
    Auth-->>MW: Token Valid
    MW->>REST: Route
    REST->>REST: Process
    REST-->>MW: JSON Response
    MW-->>Client: Response

    Client->>WS: Connect
    WS->>WS: Upgrade
    WS-->>Client: Bidirectional

    Client->>GQL: Query
    GQL->>GQL: Resolve
    GQL-->>Client: Data
```

### CLI (`src/cli/`)

```mermaid
flowchart LR
    User["User"] --> CLI["CLI Entry"]
    CLI --> Parser["Command Parser"]
    Parser --> Validate["Validate"]
    Parser --> ConfigCMD["Config Commands"]
    Parser --> Batch["Batch Processor"]
    Parser --> Interactive["Interactive Shell"]
    Interactive --> Output["Output Formatter"]
    Validate --> Output
    ConfigCMD --> Output
    Batch --> Output
    Output --> Console["Console"]
```

### Middleware (`src/middleware/`)

```mermaid
flowchart LR
    Req["Request"] --> VM["Validation Middleware"]
    VM --> AuthM["Auth Middleware"]
    AuthM --> RL["Rate Limit Middleware"]
    RL --> Log["Logging Middleware"]
    Log --> Handler["Route Handler"]
    Handler --> Audit["Audit Middleware"]
    Audit --> Resp["Response"]
```

### Advanced Features (`src/advanced/`)

```mermaid
flowchart TD
    Input["Content"] --> IA["Intent Analyzer - Classify Intent"]
    IA --> AV["Age Verifier - Age Check"]
    IA --> ER["Emergency Response - Safety Check"]
    AV --> Sandbox["Code Sandbox - Isolated Execution"]
    ER --> Reporter["Violation Reporter - Generate Report"]
    Sandbox --> Output
    Reporter --> Output
    Output["Safe Output"]
```

### Memory (`src/memory/`)

```mermaid
flowchart LR
    subgraph Cache
        RC["Rule Cache - L1 Hot"]
        PM["Pattern Cache - L2 Warm"]
        CM["Context Memory - L3 Cold"]
    end
    subgraph State["State Management"]
        RS["Result Store"]
        SS["Session State"]
    end
    App["Application"] --> RC
    RC -->|Miss| PM
    PM -->|Miss| CM
    App --> RS
    App --> SS
```

### Tools (`src/tools/`)

```mermaid
flowchart LR
    Rules["Rules"] --> Analyzer["Rule Analyzer - Structure"]
    Analyzer --> Debug["Debug Tool - Breakpoints"]
    Debug --> Profiler["Profiler - Performance"]
    Profiler --> Test["Test Runner - Unit/Integration"]
    Test --> VIZ["Visualizer - Graph"]
```

### Utilities (`src/utils/`)

```mermaid
flowchart LR
    subgraph Utils
        V["Validators - Input/Type/Format"]
        S["Serializers - JSON/YAML/Protobuf"]
        CM["Cache Manager - TTL/LRU"]
        CL["Config Loader - Env/File/Remote"]
        RL["Rate Limiter - Token Bucket"]
    end
    All["All Modules"] --> V
    All --> S
    All --> CM
    All --> CL
    API["API Layer"] --> RL
```

---

## Core Engine Flow

The complete end-to-end rule evaluation flow:

```mermaid
sequenceDiagram
    participant Client
    participant API as API Gateway
    participant MW as Middleware Stack
    participant RE as Rule Engine
    participant TD as Tier Dispatcher
    participant EP as Eval Pipeline
    participant RA as Result Aggregator
    participant MON as Monitoring
    participant STORE as Storage

    Client->>API: POST /api/v1/validate
    API->>MW: Request Pipeline
    MW->>MW: Validate Request
    MW->>MW: Authenticate User
    MW->>MW: Rate Limit Check
    MW->>MW: Log Request
    MW->>RE: RuleEvaluationRequest

    RE->>RE: Parse Request
    RE->>TD: Dispatch by Tier

    TD->>TD: Safety Tier Check
    TD->>TD: Operational Tier Check
    TD->>TD: Preference Tier Check

    TD->>EP: Evaluation Pipeline
    EP->>EP: Run Safety Rules
    EP->>EP: Run Operational Rules
    EP->>EP: Run Preference Rules

    EP->>RA: Raw Results
    RA->>RA: Aggregate Results
    RA->>RA: Resolve Conflicts
    RA->>RA: Generate Suggestions

    RE->>MON: Record Metrics
    RE->>STORE: Store Validation

    RE-->>MW: ValidationResult
    MW->>MW: Audit Trail
    MW-->>API: JSON Response
    API-->>Client: 200 OK
```

---

## Quick Start

### Python

```python
from src.core.rule_engine import RuleEngine
from src.models.rule import RuleEvaluationRequest

engine = RuleEngine()

request = RuleEvaluationRequest(
    content="Sample AI-generated content to validate",
    tier="safety",
    context={"domain": "general", "user_role": "end_user"},
    options={"strict_mode": True}
)

result = engine.evaluate(request)

print(f"Valid: {result.valid}")
print(f"Score: {result.score}")
for v in result.violations:
    print(f"  - {v.type}: {v.message}")
```

### Python SDK

```python
from sdk.python import Client

client = Client(api_key="your-key", base_url="http://localhost:8000")

# Single validation
result = client.validate("Check this content", tier="safety")

# Batch validation
results = client.validate_batch([
    "Content one",
    "Content two",
    "Content three",
])

# Get system metrics
metrics = client.get_metrics()
```

### TypeScript SDK

```typescript
import { Client } from './sdk/typescript';

const client = new Client({ apiKey: 'your-key', baseUrl: 'http://localhost:8000' });

// Single validation
const result = await client.validate('Check this content', { tier: 'safety' });

// Batch validation
const results = await client.validateBatch(['Content one', 'Content two']);

// Get metrics
const metrics = await client.getMetrics();
```

### CLI

```bash
# Validate content
python -m src.cli validate "Content to check" --tier safety

# List active rules
python -m src.cli rules list --tier operational

# Check compliance
python -m src.cli compliance check --regulations gdpr,hipaa

# Monitor system
python -m src.cli monitor metrics --interval 5
```

### API

```bash
# Health check
curl http://localhost:8000/health

# Validate content
curl -X POST http://localhost:8000/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"content": "Test content", "tier": "safety"}'

# Get rules
curl http://localhost:8000/api/v1/rules?tier=operational

# Check compliance
curl -X POST http://localhost:8000/api/v1/compliance/check \
  -H "Content-Type: application/json" \
  -d '{"content": "Data to check", "regulations": ["gdpr", "hipaa"]}'

# Get metrics
curl http://localhost:8000/api/v1/metrics
```

---

## SDKs

### Python SDK (`sdk/python/`)

| File | Lines | Description |
|------|-------|-------------|
| `client.py` | 928 | Main SDK client — CRUD, validate, evaluate, metrics, alerts |
| `models.py` | 944 | All data models with serialization |
| `rule_client.py` | 721 | Rule evaluation client with caching and batching |
| `validation_client.py` | 917 | Content validation, compliance, safety, hallucination detection |
| `monitoring_client.py` | 717 | Metrics, alerts, health, Prometheus export |
| `exceptions.py` | 169 | Custom exception types |

### TypeScript SDK (`sdk/typescript/`)

| File | Lines | Description |
|------|-------|-------------|
| `client.ts` | 696 | Main SDK client — full API surface |
| `models.ts` | 1,416 | Complete type definitions and interfaces |
| `rule-client.ts` | 678 | Rule evaluation with caching |
| `validation-client.ts` | 747 | Content and compliance validation |
| `monitoring-client.ts` | 700 | Metrics and alerting client |

---

## Project Structure

```
Rules-Emerging-Pattern/
├── sdk/                           # SDK implementations
│   ├── python/                    #   Python SDK (4,775 lines)
│   └── typescript/                #   TypeScript SDK (4,385 lines)
├── src/                           # Main source (75+ production files)
│   ├── __init__.py                #   Package exports
│   ├── main.py                    #   FastAPI application (841 lines)
│   ├── advanced/                  #   Age verification, emergency, sandbox
│   ├── api/                       #   REST, WebSocket, GraphQL, auth
│   ├── cli/                       #   CLI, shell, batch processor
│   ├── compliance/                #   GDPR, HIPAA, PCI, SOX
│   ├── core/                      #   Rule engine, dispatcher, pipeline
│   │   └── tiered_rules/          #     Safety/Operational/Preference tiers
│   ├── learning/                  #   Pattern recognition, trends, ML
│   ├── memory/                    #   Cache, context, session state
│   ├── middleware/                 #   Validation, auth, rate-limit, audit
│   ├── models/                    #   Rule, validation, conflict, audit models
│   ├── monitoring/                #   Metrics, alerts, dashboards
│   ├── privacy/                   #   Redaction, anonymization, consent
│   ├── skills/                    #   Skill system, registry, executor
│   ├── storage/                   #   File, cache, backup, migration
│   ├── tools/                     #   Analyzer, debugger, profiler
│   └── utils/                     #   Validators, serializers, config
├── rule_engines/                  # Engine plugins and extensions
├── rule_learning/                 # Adaptive rule learning
├── rule_repositories/             # Predefined and custom rules
├── validation_systems/            # Content filtering, I/O validation
├── config/                        # Configuration files
├── tests/                         # Test suite
├── docs/                          # Documentation
├── Dockerfile                     # Docker build
├── docker-compose.yml             # Docker compose
├── pyproject.toml                 # Python project config
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

---

## API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | System health check |
| `POST` | `/api/v1/validate` | Validate content |
| `POST` | `/api/v1/tiered/evaluate` | Tiered evaluation |
| `GET` | `/api/v1/rules` | List rules |
| `GET` | `/api/v1/metrics` | Get system metrics |

### Monitoring Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/alerts` | List alerts |
| `POST` | `/api/v1/alerts` | Trigger alert |
| `PUT` | `/api/v1/alerts/{id}/resolve` | Resolve alert |
| `GET` | `/api/v1/dashboard` | Dashboard data |

### Compliance Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/compliance/check` | Full compliance check |
| `POST` | `/api/v1/compliance/gdpr` | GDPR check |
| `POST` | `/api/v1/compliance/hipaa` | HIPAA check |
| `POST` | `/api/v1/compliance/pci` | PCI check |
| `POST` | `/api/v1/compliance/sox` | SOX check |

### Privacy Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/privacy/redact` | Redact sensitive data |
| `POST` | `/api/v1/privacy/anonymize` | Anonymize data |
| `POST` | `/api/v1/privacy/classify` | Classify data sensitivity |
| `POST` | `/api/v1/privacy/consent/check` | Check consent |
| `GET` | `/api/v1/privacy/audit` | Privacy audit log |

### Learning Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/patterns/analyze` | Analyze patterns |
| `POST` | `/api/v1/trends/analyze` | Analyze trends |
| `POST` | `/api/v1/feedback` | Submit feedback |
| `GET` | `/api/v1/models` | List trained models |

### Advanced Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/advanced/age-verify` | Age verification |
| `POST` | `/api/v1/advanced/emergency` | Emergency response |
| `POST` | `/api/v1/advanced/intent` | Intent analysis |
| `POST` | `/api/v1/advanced/sandbox/execute` | Sandbox execution |

### Skills Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/skills/execute` | Execute skill |
| `GET` | `/api/v1/skills` | List skills |
| `POST` | `/api/v1/skills/validate` | Validate skill |

### Storage Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/storage/rules/{id}` | Get stored rule |
| `POST` | `/api/v1/storage/rules` | Store rules |
| `POST` | `/api/v1/storage/backup` | Trigger backup |
| `POST` | `/api/v1/storage/migrate` | Trigger migration |

### Tools Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/tools/analyze` | Analyze rules |
| `POST` | `/api/v1/tools/visualize` | Visualize patterns |
| `POST` | `/api/v1/tools/profile` | Profile performance |

---

## Installation

### Docker

```bash
git clone https://github.com/LifeJiggy/Rules-Emerging-Pattern.git
cd Rules-Emerging-Pattern
cp .env.example .env
docker-compose up -d
```

### Local

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Documentation

Each module has dedicated Mermaid documentation in its subfolder:

| Module | Documentation |
|--------|---------------|
| Core Engine | [`src/core/README.md`](src/core/README.md) |
| Models | [`src/models/README.md`](src/models/README.md) |
| Monitoring | [`src/monitoring/README.md`](src/monitoring/README.md) |
| Learning | [`src/learning/README.md`](src/learning/README.md) |
| Memory | [`src/memory/README.md`](src/memory/README.md) |
| API | [`src/api/README.md`](src/api/README.md) |
| CLI | [`src/cli/README.md`](src/cli/README.md) |
| Compliance | [`src/compliance/README.md`](src/compliance/README.md) |
| Privacy | [`src/privacy/README.md`](src/privacy/README.md) |
| Middleware | [`src/middleware/README.md`](src/middleware/README.md) |
| Skills | [`src/skills/README.md`](src/skills/README.md) |
| Storage | [`src/storage/README.md`](src/storage/README.md) |
| Tools | [`src/tools/README.md`](src/tools/README.md) |
| Utilities | [`src/utils/README.md`](src/utils/README.md) |
| Advanced | [`src/advanced/README.md`](src/advanced/README.md) |
| Python SDK | [`sdk/python/README.md`](sdk/python/README.md) |
| TypeScript SDK | [`sdk/typescript/README.md`](sdk/typescript/README.md) |

---

## License

MIT License — see [LICENSE](LICENSE) for details.
