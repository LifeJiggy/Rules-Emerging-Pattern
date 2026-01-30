"""Example: Context-Aware Rules."""
import asyncio
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleEvaluationRequest, RuleContext

async def main():
    engine = RuleEngine()
    print("Context-Aware Rules Demo")
    
    # Medical context
    medical_context = RuleContext(
        user_id="doc123",
        domain="medical",
        user_role="doctor",
        content_type="diagnosis"
    )
    
    request = RuleEvaluationRequest(
        content="Patient presents with symptoms",
        context=medical_context
    )
    
    result = await engine.evaluate(request)
    print(f"Medical context - Violations: {len(result.violations)}")
    
    await engine.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
