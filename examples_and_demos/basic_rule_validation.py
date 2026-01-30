"""
Basic Rule Validation Example

This example demonstrates the fundamental usage of the Rules-Emerging-Pattern
framework for validating content against safety and operational rules.
"""

import asyncio
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleEvaluationRequest, RuleContext


async def basic_validation_example():
    """Demonstrate basic content validation."""
    print("=" * 60)
    print("Basic Rule Validation Example")
    print("=" * 60)
    
    # Initialize the rule engine
    engine = RuleEngine()
    
    # Example 1: Validating safe content
    print("\n1. Validating safe content...")
    safe_request = RuleEvaluationRequest(
        content="This is a perfectly safe piece of content about machine learning.",
        context=RuleContext(user_id="user_001", domain="education")
    )
    
    result = await engine.evaluate(safe_request)
    print(f"   Content: {safe_request.content[:50]}...")
    print(f"   Valid: {result.valid}")
    print(f"   Score: {result.total_score:.2f}")
    print(f"   Violations: {len(result.violations)}")
    
    # Example 2: Validating content with potential violations
    print("\n2. Validating content with potential violations...")
    risky_request = RuleEvaluationRequest(
        content="Instructions for creating dangerous weapons and explosives.",
        context=RuleContext(user_id="user_002", domain="general")
    )
    
    result = await engine.evaluate(risky_request)
    print(f"   Content: {risky_request.content[:50]}...")
    print(f"   Valid: {result.valid}")
    print(f"   Score: {result.total_score:.2f}")
    print(f"   Violations: {len(result.violations)}")
    
    if result.violations:
        for violation in result.violations:
            print(f"   - Rule: {violation.rule_name} (Tier: {violation.rule_tier})")
            print(f"     Severity: {violation.severity}, Score: {violation.score:.2f}")
    
    # Example 3: Validating with specific tier focus
    print("\n3. Validating with safety tier focus only...")
    from rules_emerging_pattern.models.rule import RuleTier
    
    tiered_request = RuleEvaluationRequest(
        content="Content with various issues across different tiers.",
        tier=RuleTier.SAFETY,
        context=RuleContext(user_id="user_003")
    )
    
    result = await engine.evaluate(tiered_request)
    print(f"   Valid: {result.valid}")
    print(f"   Safety Violations Only: {len(result.violations)}")
    
    # Example 4: Batch validation
    print("\n4. Batch validation example...")
    contents = [
        "Safe educational content about AI.",
        "Another safe piece about technology.",
        "Content with dangerous weapon instructions."
    ]
    
    requests = [
        RuleEvaluationRequest(content=c, context=RuleContext())
        for c in contents
    ]
    
    results = await engine.evaluate_batch(requests)
    
    for i, (content, result) in enumerate(zip(contents, results)):
        print(f"   Item {i+1}: Valid={result.valid}, Violations={len(result.violations)}")
    
    # Cleanup
    await engine.shutdown()
    
    print("\n" + "=" * 60)
    print("Basic validation example completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(basic_validation_example())
