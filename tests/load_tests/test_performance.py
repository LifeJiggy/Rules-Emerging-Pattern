"""Performance and load tests."""
import pytest
import asyncio
import time
from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import RuleEvaluationRequest, RuleContext

class TestPerformance:
    """Test performance."""
    
    @pytest.mark.asyncio
    async def test_evaluation_performance(self):
        """Test evaluation completes within time limit."""
        engine = RuleEngine()
        
        request = RuleEvaluationRequest(
            content="Test content",
            context=RuleContext()
        )
        
        start = time.time()
        result = await engine.evaluate(request)
        elapsed = time.time() - start
        
        assert elapsed < 1.0  # Should complete in under 1 second
        
        await engine.shutdown()

if __name__ == "__main__":
    pytest.main([__file__])
