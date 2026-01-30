# Dangerous Content Rules

## Overview

These rules prevent the dissemination of dangerous information that could cause physical harm, violence, or illegal activities. These are **Tier 1 Safety Rules** with **strict enforcement**.

## Rule: Weapons and Explosives Prevention

**ID:** `safety_weapons`  
**Tier:** Safety (Tier 1)  
**Enforcement:** Strict (Auto-block)  
**Severity:** Critical

### Description

Prevents content related to weapons manufacturing, explosives creation, and dangerous device instructions.

### Patterns

**Keywords:**
- how to make a bomb
- build explosive device
- weapon instructions
- gun manufacturing
- homemade weapons
- explosive materials
- dangerous chemicals weapon

**Regex Patterns:**
- `(?i)how\s+to\s+(make|build|create)\s+(bomb|explosive|weapon)`
- `(?i)(anarchist|cookbook|terrorist)\s+(manual|guide)`

### Enforcement

- **Action:** BLOCK
- **Auto-block:** Yes
- **User Override:** No
- **Escalation:** Immediate security review

---

## Rule: Dangerous Substances

**ID:** `safety_substances`  
**Tier:** Safety (Tier 1)  
**Enforcement:** Strict  
**Severity:** Critical

### Description

Blocks instructions for creating dangerous chemical substances, drugs, or toxins.

### Patterns

**Keywords:**
- drug synthesis
- methamphetamine production
- chemical weapons
- poison creation
- dangerous drug recipes

---

## Rule: Self-Harm Prevention

**ID:** `safety_self_harm`  
**Tier:** Safety (Tier 1)  
**Enforcement:** Strict  
**Severity:** Critical

### Description

Prevents content that encourages or instructs self-harm or suicide.

### Patterns

**Keywords:**
- suicide instructions
- self-harm guide
- how to kill yourself
- suicide methods
- self-injury techniques

---

## Compliance Notes

These rules comply with:
- Public safety regulations
- Counter-terrorism laws
- Platform safety policies
- International security standards

## Review Schedule

**Last Updated:** 2024-01-15  
**Review Cycle:** Monthly  
**Next Review:** 2024-02-15
