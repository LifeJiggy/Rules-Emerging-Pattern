# Build Prompts for Rules-Emerging-Pattern System

This document contains specialized prompts designed to assist in building, configuring, and optimizing rules engines for AI systems. These prompts focus on creating strict guardrails, consistency enforcement, and safety boundaries through tiered rule architectures.

## 1. Rule Architecture Prompts

### Tiered Rule System Design Prompt
```
Create a comprehensive tiered rule system with three distinct levels:

- **Tier 1 (Safety Rules)**: Non-negotiable rules with automatic enforcement
  - Child safety and protection
  - Dangerous information prevention
  - Malicious code blocking
  - Content safety filtering

- **Tier 2 (Operational Rules)**: High-priority rules with conflict resolution
  - Copyright compliance and fair use
  - Privacy protection and PII handling
  - Content quality standards
  - Regulatory compliance requirements

- **Tier 3 (Preference Rules)**: Adjustable rules with user adaptation
  - Formatting and style preferences
  - Tone and communication guidelines
  - Domain-specific preferences
  - User-specific customizations

Design the architecture with clear priorities, enforcement mechanisms, and conflict resolution strategies.
```

### Rule Configuration System Prompt
```
Build a flexible rule configuration system that supports:

- YAML-based rule definitions with version control
- Environment-specific configurations (development, staging, production)
- Rule prioritization and tier assignment
- Enforcement level configuration (strict, advisory, adaptive)
- Conflict resolution strategy selection
- Monitoring and logging configuration

Include validation, error handling, and automatic configuration testing.
```

## 2. Rule Engine Implementation Prompts

### Base Rule Manager Prompt
```
Create a base rule management class that provides:

- Rule loading and parsing from multiple sources
- Rule validation and conflict detection
- Rule prioritization and tier management
- Rule enforcement with multiple strategies
- Performance monitoring and metrics
- Error handling and fallback mechanisms

Implement the class with extensibility for different rule types and enforcement strategies.
```

### Safety Rule Engine Prompt
```
Implement a Tier 1 safety rule engine with:

- Automatic enforcement without user override
- Real-time content scanning and filtering
- Pattern matching for dangerous content
- Context-aware safety analysis
- Immediate blocking of violations
- Comprehensive audit logging

Include safety rule templates and predefined rule sets for common safety concerns.
```

### Operational Rule Engine Prompt
```
Build a Tier 2 operational rule engine featuring:

- Conflict detection and resolution
- Context-aware rule application
- User notification for rule violations
- Override capabilities with justification
- Compliance tracking and reporting
- Integration with business processes

Implement operational rule templates for copyright, privacy, and content quality.
```

### Preference Rule Engine Prompt
```
Create a Tier 3 preference rule engine that supports:

- User preference learning and adaptation
- Context-based rule application
- User override capabilities
- Preference pattern recognition
- Adaptive rule adjustment
- User feedback integration

Include preference rule templates for formatting, tone, and domain-specific preferences.
```

## 3. Validation and Filtering Prompts

### Input Validation System Prompt
```
Design a comprehensive input validation system with:

- Content validation (safety, quality, relevance)
- Format validation (structure, syntax, completeness)
- Safety validation (child safety, dangerous content)
- Compliance validation (copyright, privacy, regulations)

Implement validation pipelines with configurable severity levels and enforcement strategies.
```

### Content Filtering Framework Prompt
```
Build a content filtering framework that includes:

- Profanity and offensive content filtering
- Personal information detection and redaction
- Copyright violation detection
- Sensitive content filtering
- Context-aware filtering strategies
- User-configurable filter thresholds

Create filtering algorithms with performance optimization and false positive reduction.
```

### Exception Handling System Prompt
```
Implement a comprehensive exception handling system with:

- Rule violation exception handling
- Fallback response strategies
- User notification mechanisms
- Escalation protocols for critical violations
- Recovery procedures
- Incident logging and analysis

Design the system with graceful degradation and user experience preservation.
```

## 4. Conflict Resolution Prompts

### Conflict Detection System Prompt
```
Create a conflict detection system that identifies:

- Rule conflicts (competing rule requirements)
- Priority conflicts (tier conflicts)
- Semantic conflicts (meaning conflicts)
- Context conflicts (situational conflicts)

Implement detection algorithms with performance optimization and comprehensive logging.
```

### Conflict Resolution Engine Prompt
```
Build a conflict resolution engine with multiple strategies:

- Priority-based resolution (higher tier rules win)
- Context-aware resolution (situation-based decisions)
- User preference resolution (user-defined priorities)
- Fallback resolution (default strategies)
- Hybrid resolution (combination strategies)

Include resolution effectiveness tracking and pattern analysis.
```

### Conflict Logging System Prompt
```
Design a comprehensive conflict logging system that:

- Records all detected conflicts
- Tracks resolution strategies used
- Logs resolution outcomes
- Analyzes conflict patterns
- Generates conflict reports
- Provides conflict resolution metrics

Implement the system with privacy protection and performance optimization.
```

## 5. Rule Learning and Adaptation Prompts

### Pattern Recognition System Prompt
```
Create a pattern recognition system for rule learning that:

- Detects rule usage patterns
- Identifies conflict patterns
- Recognizes exception patterns
- Analyzes user override patterns
- Tracks rule effectiveness patterns

Implement machine learning-based pattern detection with performance optimization.
```

### Adaptive Rule Engine Prompt
```
Build an adaptive rule engine that:

- Adjusts rule enforcement based on context
- Learns from user feedback and behavior
- Adapts to changing requirements
- Optimizes rule performance
- Balances safety and user experience

Include adaptive learning algorithms with safety constraints and performance monitoring.
```

### Rule Optimization Framework Prompt
```
Design a rule optimization framework that:

- Analyzes rule performance metrics
- Identifies optimization opportunities
- Implements performance improvements
- Balances effectiveness and efficiency
- Maintains safety constraints
- Provides optimization recommendations

Create optimization algorithms with automated testing and validation.
```

## 6. Integration Layer Prompts

### System Integration Prompt
```
Create integration layers for rule system with:

- System prompt integration (core identity rules)
- Skills framework integration (procedural rules)
- RAG system integration (context-aware rules)
- API integration (external rule enforcement)

Implement integration frameworks with performance optimization and error handling.
```

### API Integration Framework Prompt
```
Build API integration for rule enforcement that supports:

- REST API rule validation
- GraphQL rule integration
- WebSocket rule enforcement
- Real-time rule checking
- Batch rule validation
- Performance optimization

Include API documentation, testing, and monitoring capabilities.
```

### External System Integration Prompt
```
Design external system integration for rules that includes:

- Database rule integration
- Cloud service rule enforcement
- Third-party service rule validation
- Legacy system rule compatibility
- Cross-platform rule consistency

Implement integration adapters with error handling and performance monitoring.
```

## 7. Evaluation and Compliance Prompts

### Rule Effectiveness Metrics Prompt
```
Create a rule effectiveness measurement system that tracks:

- Rule coverage metrics
- Rule enforcement rates
- Conflict resolution effectiveness
- User satisfaction metrics
- Performance impact metrics
- Compliance metrics

Implement comprehensive metrics collection with visualization and reporting.
```

### Compliance Testing Framework Prompt
```
Build a compliance testing framework that includes:

- Safety compliance testing
- Operational compliance testing
- Regulatory compliance testing
- Automated test generation
- Compliance reporting
- Audit trail generation

Design the framework with industry standards and regulatory requirements.
```

### Performance Benchmarking Prompt
```
Create a performance benchmarking system for rules that:

- Measures rule evaluation latency
- Tracks throughput and scalability
- Analyzes memory usage
- Monitors CPU utilization
- Tests conflict resolution performance
- Evaluates adaptive learning performance

Implement benchmarking with automated testing and comparative analysis.
```

## 8. Production and Scalability Prompts

### Distributed Rule Processing Prompt
```
Design a distributed rule processing system with:

- Multi-node rule evaluation
- Load balancing strategies
- Fault tolerance mechanisms
- Consistent rule enforcement
- Performance optimization
- Scalability testing

Implement distributed processing with automatic scaling and monitoring.
```

### Monitoring and Observability Prompt
```
Build comprehensive monitoring for rule systems that includes:

- Real-time rule monitoring
- Performance metrics tracking
- Conflict detection monitoring
- Rule effectiveness tracking
- User experience monitoring
- Alerting and notification systems

Create monitoring dashboards with visualization and historical analysis.
```

### Security and Compliance Prompt
```
Implement security and compliance features for rule systems:

- Data encryption and protection
- Access control and authentication
- Audit logging and tracking
- Privacy protection mechanisms
- Regulatory compliance features
- Security monitoring and alerting

Design security-first architecture with comprehensive compliance capabilities.
```

## 9. Domain-Specific Rule Prompts

### Safety Rule Templates Prompt
```
Create comprehensive safety rule templates for:

- Child safety and protection
- Dangerous information prevention
- Malicious code blocking
- Content safety filtering
- Ethical guidelines enforcement
- Legal compliance rules

Include rule definitions, enforcement strategies, and testing frameworks.
```

### Operational Rule Templates Prompt
```
Build operational rule templates covering:

- Copyright compliance and fair use
- Privacy protection and PII handling
- Content quality standards
- Regulatory compliance requirements
- Business process rules
- Industry-specific operational rules

Create templates with configurable parameters and enforcement options.
```

### Preference Rule Templates Prompt
```
Design preference rule templates for:

- Formatting and style preferences
- Tone and communication guidelines
- Domain-specific preferences
- User-specific customizations
- Organization-specific rules
- Industry-specific preferences

Implement templates with user adaptation and learning capabilities.
```

These prompts provide a comprehensive framework for building, deploying, and maintaining production-grade rules engines that provide strict guardrails, consistency enforcement, and safety boundaries for AI systems.