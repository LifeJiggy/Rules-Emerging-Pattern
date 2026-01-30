# Privacy and PII Protection Rules

## Overview

These rules protect personal information and ensure compliance with privacy regulations (GDPR, CCPA, HIPAA). These are Tier 2 Operational Rules with strict enforcement for PII detection.

## Rule: PII Detection and Redaction

**ID:** operational_pii_protection  
**Tier:** Operational (Tier 2)  
**Enforcement:** Advisory  
**Severity:** High

### Description

Detects and flags personal identifiable information (PII) that should be protected or redacted.

### Patterns

**Keywords:**
- social security number
- credit card number
- personal address
- phone number
- email address
- date of birth

**Regex Patterns:**
- SSN: \b\d{3}-\d{2}-\d{4}\b
- Credit Card: \b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b

### Enforcement

- Action: WARNING
- Auto-block: No
- User Override: Yes (with justification)
- Redaction: Suggested

## Review Schedule

Last Updated: 2024-01-15
Review Cycle: Quarterly
