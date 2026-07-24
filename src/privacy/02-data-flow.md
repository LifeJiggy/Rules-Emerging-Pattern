# Privacy Module Data Flow

## 1. PII Redaction Flow

When a user submits data containing personally identifiable information, the `DataRedactor` processes it through pattern matching, Luhn validation, and substitution.

```mermaid
sequenceDiagram
    participant Client as Client App
    participant DR as DataRedactor
    participant Audit as PrivacyAuditor
    participant Log as Audit Log

    Client->>DR: redact(text="Contact: john@example.com, CC: 4111-1111-1111-1111")

    activate DR
    DR->>DR: Iterate enabled rules in order

    Note over DR: Rule 1: SSN pattern
    DR->>DR: finditer(ssn_pattern) → no match

    Note over DR: Rule 2: Email pattern
    DR->>DR: finditer(email_pattern) → match: "john@example.com"
    DR->>DR: Substitution → "[REDACTED]"

    Note over DR: Rule 3: CC pattern (16-digit)
    DR->>DR: finditer(cc_pattern) → match: "4111-1111-1111-1111"
    DR->>DR: Luhn check on "4111111111111111" → pass
    DR->>DR: Substitution → "[REDACTED]"

    Note over DR: Rule 4: Phone pattern
    DR->>DR: finditer(phone_pattern) → no match

    DR->>DR:_total_redactions += 2
    DR->>DR:_redactions_by_label["email"] += 1
    DR->>DR:_redactions_by_label["credit_card"] += 1
    DR->>DR:_audit_log.append(RedactionAuditEntry)

    DR->>Audit: log_event(event_type=REDACTION_APPLIED, details="Redacted 2 PII instances")
    deactivate DR

    DR-->>Client: "Contact: [REDACTED], CC: [REDACTED]"

    Client->>Client: Use redacted text safely
```

## 2. Sensitivity Classification Flow

The `DataClassifier` assigns a sensitivity level by scanning data against compiled regex patterns and keyword lists, then computing a weighted score.

```mermaid
sequenceDiagram
    participant App as Application
    participant DC as DataClassifier
    participant Rules as Rule Engine
    participant Audit as PrivacyAuditor

    App->>DC: classify({"name": "John", "email": "john@example.com", "ssn": "123-45-6789"})

    activate DC
    DC->>DC: _classify_dict() → _scan() recursively

    Note over DC: Scanning field "email" = "john@example.com"
    DC->>Rules: _classify_text("john@example.com")
    Rules->>Rules: Match rule: confidential_email (level=confidential, weight=5.0)
    Rules-->>DC: matched: email, score=0.5

    Note over DC: Scanning field "ssn" = "123-45-6789"
    DC->>Rules: _classify_text("123-45-6789")
    Rules->>Rules: Match rule: critical_ssn (level=critical, weight=10.0)
    Rules-->>DC: matched: ssn, score=1.0

    Note over DC: Scanning field "name" = "John"
    DC->>Rules: _classify_text("John")
    Rules-->>DC: no match (default: internal, score=0.0)

    DC->>DC: Aggregate: max level rank = critical (rank 4)
    DC->>DC: final_level = "critical", score = min(1.0, 1.0 + 2 * 0.05) = 1.0

    Note over DC: Metadata-aware elevation
    DC->>Audit: log_event(CLASSIFICATION_APPLIED, level=critical)
    deactivate DC

    DC-->>App: ClassificationResult(level="critical", score=1.0, matched_rules=["critical_ssn", "confidential_email"])

    App->>App: Route critical data to redaction pipeline
```

## 3. Consent Check and Recording Flow

The `ConsentManager` handles the full lifecycle: grant, check, expire, and audit.

```mermaid
sequenceDiagram
    participant User as Data Subject
    participant UI as Web Form
    participant CM as ConsentManager
    participant Index as In-Memory Index
    participant Auditor as PrivacyAuditor

    User->>UI: Accept marketing cookies
    UI->>CM: record_consent(user_id="u1", category=ConsentCategory.MARKETING, granted=True, source="web_form")

    activate CM
    CM->>CM: _generate_consent_id() → "cns-a1b2c3d4e5f6g7h8"
    CM->>CM: _make_expiry(365) → "2027-07-24T..."
    CM->>CM: Create ConsentRecord(status=GRANTED, granted=True)

    CM->>Index: Append to _records
    CM->>Index: Append to _index_by_user["u1"]
    CM->>Index: Append to _index_by_category["marketing"]

    CM->>Auditor: log_consent_change("u1", "marketing", granted=True, source="web_form")
    deactivate CM

    CM-->>UI: ConsentRecord(consent_id="cns-...", status="granted")
    UI-->>User: ✅ Consent saved

    Note over User,UI: Later...

    App->>CM: check_consent(user_id="u1", category=ConsentCategory.MARKETING)

    activate CM
    CM->>Index: _index_by_user["u1"] → [record0, record1, ...]
    CM->>CM: Filter by category="marketing"
    CM->>CM: latest = max(records, key=recorded_at)
    CM->>CM: latest.granted=True, latest.expiry="2027-07-24T..." > now

    CM-->>App: True (consent active)
    deactivate CM

    Note over User,App: After expiry date passes...

    App->>CM: expire_all_expired()
    activate CM
    CM->>CM: Scan all records → record.expiry <= now
    CM->>CM: Mark as EXPIRED, granted=False
    CM-->>App: count=1

    App->>CM: check_consent(user_id="u1", category=ConsentCategory.MARKETING)
    CM-->>App: False (consent expired)
    deactivate CM
```

## 4. Anonymization Pipeline Flow

The `Anonymizer` applies multiple field-level strategies in a single pass using dispatch functions.

```mermaid
sequenceDiagram
    participant Client as Client App
    participant AN as Anonymizer
    participant Dispatch as Strategy Dispatch
    participant Audit as PrivacyAuditor

    Client->>AN: anonymize(record)

    activate AN
    Note over AN: record = {"email": "john@example.com", "salary": 85000, "name": "John Doe", "age": 42}

    AN->>AN: Build field_strategies from registered rules

    Note over AN: Field strategies:
    Note over AN:   "email" → pseudonymize(salt="s1", prefix="anon_", length=12)
    Note over AN:   "salary" → generalize_bin(bin_size=10000, label_format="range")
    Note over AN:   "name" → suppress_partial(show_first=2, mask_char="*")

    AN->>Dispatch: _apply_strategy_to_field(result, "email", strategy)
    Dispatch->>Dispatch: _strategy_pseudonymize("john@example.com", {salt:"s1", prefix:"anon_", length:12})
    Dispatch-->>AN: "anon_a1b2c3d4e5f6"

    AN->>Dispatch: _apply_strategy_to_field(result, "salary", strategy)
    Dispatch->>Dispatch: _strategy_generalize_bin(85000, {bin_size:10000, label_format:"range"})
    Dispatch->>Dispatch: lower = floor(85000/10000)*10000 = 80000, upper = 90000
    Dispatch-->>AN: "80000-90000"

    AN->>Dispatch: _apply_strategy_to_field(result, "name", strategy)
    Dispatch->>Dispatch: _strategy_suppress_partial("John Doe", {show_first:2, mask_char:"*"})
    Dispatch-->>AN: "Jo*****"

    AN->>Audit: log_event(ANONYMIZATION_APPLIED, fields=["email", "salary", "name"])
    deactivate AN

    AN-->>Client: {"email": "anon_a1b2c3d4e5f6", "salary": "80000-90000", "name": "Jo*****", "age": 42}

    Client->>Client: age=42 unchanged (no matching rule, no default strategy)
```

## 5. DSAR Fulfillment Flow

The `PrivacyAuditor` handles Data Subject Access Requests from creation through fulfillment.

```mermaid
sequenceDiagram
    participant DSub as Data Subject
    participant API as DSAR API
    participant PA as PrivacyAuditor
    participant CM as ConsentManager
    participant DC as DataClassifier
    participant DR as DataRedactor

    DSub->>API: Request my data (GDPR Art. 15)
    API->>PA: create_dsar(user_id="u1", request_type="access", fulfillment_format="json")

    activate PA
    PA->>PA: Create DSARRequest(status="open", regulatory_deadline=T+30d)
    PA->>PA: log_event(DSAR_REQUEST, user_id="u1")
    PA-->>API: DSARRequest(dsar_id="dsar-...", status="open")
    deactivate PA

    API->>PA: fulfill_dsar(dsar_id="dsar-...")

    activate PA
    PA->>PA: dsar_fulfillment_package(user_id="u1")

    Note over PA: Package includes:
    Note over PA:   - All privacy events for user u1
    Note over PA:   - Consent grant/withdraw events
    Note over PA:   - Full audit trail

    PA->>CM: get_consent_proof(user_id="u1", category="marketing")
    CM-->>PA: proof_payload with hash chain

    PA->>DC: classify_with_metadata(events, metadata={"regulatory": ["gdpr"]})
    DC-->>PA: sensitivity classification

    PA->>DR: redact_dict(events) → strip PII from exported data
    DR-->>PA: redacted event package

    PA->>PA: DSAR.status = "fulfilled"
    PA->>PA: log_event(DSAR_FULFILLMENT, user_id="u1")
    deactivate PA

    PA-->>API: fulfillment_package (JSON, redacted)
    API-->>DSub: 📋 Your data package (within 30 days)
```

## 6. Cross-Component Privacy Pipeline

End-to-end flow showing how all five components collaborate:

```mermaid
sequenceDiagram
    participant SRC as Data Source
    participant DC as DataClassifier
    participant DR as DataRedactor
    participant AN as Anonymizer
    participant CM as ConsentManager
    participant PA as PrivacyAuditor
    participant DST as Output

    SRC->>DC: Raw data arrives
    activate DC
    DC->>DC: classify(data) → level="confidential" (PII detected)
    DC->>PA: log_event(CLASSIFICATION_APPLIED, "confidential")
    deactivate DC

    DC-->>DR: Forward classified data + metadata

    activate DR
    DR->>DR: redact_dict(data) → 3 PII instances redacted
    DR->>PA: log_event(REDACTION_APPLIED, "3 instances")
    deactivate DR

    DR-->>AN: Forward redacted data

    activate AN
    AN->>CM: check_consent(user_id, "processing")
    activate CM
    CM-->>AN: True (processing consented)
    deactivate CM

    AN->>AN: anonymize(data) → pseudonymize email, bin salary
    AN->>PA: log_event(ANONYMIZATION_APPLIED, "2 fields")
    deactivate AN

    AN-->>DST: Clean, anonymized data ready for use

    PA-->>DST: Export full audit trail
```
