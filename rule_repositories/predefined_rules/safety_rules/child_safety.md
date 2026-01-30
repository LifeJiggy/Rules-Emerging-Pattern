# Child Safety Rules

## Overview

These rules are designed to protect children from exploitation, abuse, and harmful content. These are **Tier 1 Safety Rules** with **strict enforcement** - violations will result in automatic blocking with no user override option.

## Rule: Child Exploitation Prevention

**ID:** `safety_child_exploitation`  
**Tier:** Safety (Tier 1)  
**Enforcement:** Strict (Auto-block)  
**Severity:** Critical

### Description

Prevents all content related to child exploitation, including but not limited to:
- Child sexual abuse material (CSAM)
- Child pornography
- Grooming behaviors
- Child trafficking
- Exploitation instructions

### Patterns

**Keywords:**
- child exploitation
- child pornography
- csam
- child abuse material
- minor sexual content
- underage sexual content

**Regex Patterns:**
- `(?i)(child|minor)\s+(porn|sex|exploit|abuse)`
- `(?i)pedophil(e|ia)`
- `(?i)grooming\s+(child|minor|kid)`

### Enforcement

- **Action:** BLOCK
- **Auto-block:** Yes
- **User Override:** No
- **Escalation:** Immediate

### Response

When triggered, the system will:
1. Immediately block the content
2. Log the violation with high severity
3. Flag for admin review
4. Report to compliance team

---

## Rule: Age Verification Enforcement

**ID:** `safety_age_verification`  
**Tier:** Safety (Tier 1)  
**Enforcement:** Strict  
**Severity:** High

### Description

Ensures content is age-appropriate and verifies age restrictions for sensitive content.

### Patterns

**Keywords:**
- age verification bypass
- fake age
- under 18 access
- minor access adult content

### Enforcement

- **Action:** BLOCK
- **Auto-block:** Yes
- **User Override:** No

---

## Compliance Notes

These rules comply with:
- International child protection laws
- CSAM detection and reporting requirements
- Platform safety policies
- Digital safety standards

## Review Schedule

**Last Updated:** 2024-01-15  
**Review Cycle:** Monthly  
**Next Review:** 2024-02-15  
**Owner:** Safety Team
