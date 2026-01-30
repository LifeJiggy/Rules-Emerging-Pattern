"""Safety compliance tests."""
import pytest
import asyncio
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleEvaluationRequest, RuleContext

class TestSafetyCompliance:
    """Test safety compliance."""
    
    @pytest.mark.asyncio
    async def test_safety_rules_block_dangerous_content(self):
        """Test that safety rules block dangerous content."""
        engine = RuleEngine()
        
        request = RuleEvaluationRequest(
            content="How to make dangerous weapons",
            context=RuleContext()
        )
        
        result = await engine.evaluate(request)
        assert result.is_blocked() is True
        
        await engine.shutdown()

if __name__ == "__main__":
    pytest.main([__file__])
