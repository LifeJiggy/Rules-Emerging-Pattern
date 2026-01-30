# Copyright Compliance Rules

## Overview

These rules ensure compliance with copyright laws and intellectual property protection. These are **Tier 2 Operational Rules** with **advisory enforcement** - users can override with justification.

## Rule: Fair Use Compliance

**ID:** `operational_fair_use`  
**Tier:** Operational (Tier 2)  
**Enforcement:** Advisory (Warning)  
**Severity:** Medium

### Description

Ensures content respects fair use guidelines and copyright law, preventing excessive quotation or unauthorized use of copyrighted material.

### Patterns

**Keywords:**
- copyright violation
- unauthorized copy
- plagiarism
- excessive quotation
- unlicensed content
- pirated material

**Regex Patterns:**
- `(?i)(copyright|trademark)\s+(violation|infringement)`
- `(?i)copied\s+from\s+(book|article|website)`

### Parameters

- `max_quote_length`: Maximum allowed quotation length in words (default: 100)
- `require_attribution`: Whether source attribution is required (default: true)
- `allowed_sources`: List of sources that can be freely quoted

### Enforcement

- **Action:** WARNING
- **Auto-block:** No
- **User Override:** Yes (with justification)
- **Suggestion:** Provide proper attribution or reduce quoted content

### Example Violations

1. Quoting more than 100 words without attribution
2. Copying entire paragraphs from copyrighted sources
3. Using copyrighted images without license

---

## Rule: Source Attribution

**ID:** `operational_attribution`  
**Tier:** Operational (Tier 2)  
**Enforcement:** Advisory  
**Severity:** Low

### Description

Ensures proper attribution and citation of sources.

### Patterns

**Keywords:**
- missing citation
- no source
- unattributed quote
- source required

---

## Rule: Content Originality

**ID:** `operational_originality`  
**Tier:** Operational (Tier 2)  
**Enforcement:** Advisory  
**Severity:** Medium

### Description

Detects potential plagiarism and ensures content originality.

### Patterns

- Text similarity detection
- Duplicate content identification
- Unattributed paraphrasing

---

## Compliance Notes

These rules comply with:
- DMCA (Digital Millennium Copyright Act)
- International copyright treaties
- Fair use doctrine
- Platform content policies

## Review Schedule

**Last Updated:** 2024-01-15  
**Review Cycle:** Quarterly  
**Next Review:** 2024-04-15
