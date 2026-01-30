"""Example: Creating Custom Rules."""
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, EnforcementLevel

def main():
    print("Custom Rule Creation Demo")
    
    # Create custom rule
    rule = Rule(
        id="custom_rule_001",
        name="Custom Business Rule",
        description="Custom rule for business logic",
        tier=RuleTier.OPERATIONAL,
        rule_type=RuleType.CUSTOM,
        severity=RuleSeverity.MEDIUM,
        enforcement_level=EnforcementLevel.ADVISORY
    )
    
    print(f"Created rule: {rule.name}")
    print(f"Tier: {rule.tier.value}")
    print(f"Enforcement: {rule.enforcement_level.value}")

if __name__ == "__main__":
    main()
