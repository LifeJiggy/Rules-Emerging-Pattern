"""Example: Conflict Resolution."""
import asyncio
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleEvaluationRequest, RuleContext

async def main():
    engine = RuleEngine()
    print("Conflict Resolution Demo")
    
    # Content that might trigger conflicting rules
    request = RuleEvaluationRequest(
        content="Test content that may have conflicts",
        context=RuleContext()
    )
    
    result = await engine.evaluate(request)
    print(f"Conflicts resolved: {result.valid}")
    
    await engine.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
