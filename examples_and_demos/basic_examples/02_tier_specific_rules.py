"""
Example: Using Tier-Specific Rules
Demonstrates how to use Safety, Operational, and Preference rule tiers.
"""
import asyncio
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleContext

async def demonstrate_tier_rules():
    """Demonstrate rules for each tier."""
    engine = RuleEngine()
    
    print("=" * 60)
    print("TIER-SPECIFIC RULES DEMONSTRATION")
    print("=" * 60)
    
    # Test 1: Safety Tier (strict enforcement)
    print("\n1. SAFETY TIER RULES (Tier 1 - Strict)")
    print("-" * 60)
    
    safety_request = RuleEvaluationRequest(
        content="This contains dangerous weapon instructions and explosives",
        tier=RuleTier.SAFETY,
        context=RuleContext(user_id="user123", domain="general")
    )
    
    result = await engine.evaluate(safety_request)
    print(f"Content: {safety_request.content[:50]}...")
    print(f"Valid: {result.valid}")
    print(f"Violations: {len(result.violations)}")
    print(f"Blocked: {result.is_blocked()}")
    
    for v in result.violations:
        print(f"  - {v.rule_name}: {v.action_taken}")
    
    # Test 2: Operational Tier (advisory)
    print("\n2. OPERATIONAL TIER RULES (Tier 2 - Advisory)")
    print("-" * 60)
    
    operational_request = RuleEvaluationRequest(
        content="This quote from a book is very long and exceeds fair use limits. " * 10,
        tier=RuleTier.OPERATIONAL,
        context=RuleContext(user_id="user123", domain="publishing")
    )
    
    result = await engine.evaluate(operational_request)
    print(f"Content length: {len(operational_request.content)} chars")
    print(f"Valid: {result.valid}")
    print(f"Violations: {len(result.violations)}")
    print(f"Warnings: {len(result.warnings)}")
    
    for v in result.violations:
        print(f"  - {v.rule_name}: {v.action_taken}")
    
    # Test 3: Preference Tier (adaptive)
    print("\n3. PREFERENCE TIER RULES (Tier 3 - Adaptive)")
    print("-" * 60)
    
    preference_request = RuleEvaluationRequest(
        content="hey this is informal text with no formatting or structure",
        tier=RuleTier.PREFERENCE,
        context=RuleContext(user_id="user123", domain="business")
    )
    
    result = await engine.evaluate(preference_request)
    print(f"Content: {preference_request.content}")
    print(f"Valid: {result.valid}")
    print(f"Suggestions: {len(result.suggestions)}")
    
    for s in result.suggestions:
        print(f"  - {s.title}: {s.description}")
    
    # Test 4: All Tiers Together
    print("\n4. ALL TIERS COMBINED")
    print("-" * 60)
    
    mixed_request = RuleEvaluationRequest(
        content="This has dangerous content and also improper formatting",
        context=RuleContext(user_id="user123")
    )
    
    result = await engine.evaluate(mixed_request)
    print(f"Total violations: {len(result.violations)}")
    print(f"By tier: {result.get_violations_by_tier()}")
    
    await engine.shutdown()
    
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(demonstrate_tier_rules())
