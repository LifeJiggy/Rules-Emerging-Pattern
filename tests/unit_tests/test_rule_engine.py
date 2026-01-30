"""Production-grade tests for rule engine."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.rule_engines.base.rule_manager import RuleManager
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleEvaluationRequest, RuleContext
from rules_emerging_pattern.models.validation import ValidationResult


class TestRuleEngine:
    """Comprehensive test suite for RuleEngine."""
    
    @pytest.fixture
    async def engine(self):
        """Create a rule engine for testing."""
        rule_manager = RuleManager()
        engine = RuleEngine(rule_manager=rule_manager)
        yield engine
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_evaluate_safe_content(self, engine):
        """Test evaluation of safe content."""
        request = RuleEvaluationRequest(
            content="This is completely safe content",
            context=RuleContext(user_id="test_user")
        )
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert result.total_score >= 0.8
        assert result.violations == []
    
    @pytest.mark.asyncio
    async def test_evaluate_with_violations(self, engine):
        """Test evaluation content with violations."""
        request = RuleEvaluationRequest(
            content="This contains dangerous weapon instructions",
            context=RuleContext(user_id="test_user")
        )
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert len(result.violations) > 0
    
    @pytest.mark.asyncio
    async def test_evaluate_specific_tier(self, engine):
        """Test evaluation with specific tier filter."""
        request = RuleEvaluationRequest(
            content="Test content",
            tier=RuleTier.SAFETY,
            context=RuleContext(user_id="test_user")
        )
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        # Should only evaluate safety tier rules
        assert all(v.rule_tier == RuleTier.SAFETY for v in result.violations)
    
    @pytest.mark.asyncio
    async def test_batch_evaluation(self, engine):
        """Test batch evaluation of multiple content items."""
        contents = [
            "Safe content 1",
            "Safe content 2",
            "Dangerous content with weapons"
        ]
        
        requests = [
            RuleEvaluationRequest(content=c, context=RuleContext())
            for c in contents
        ]
        
        results = await engine.evaluate_batch(requests)
        
        assert len(results) == 3
        assert isinstance(results[0], ValidationResult)
    
    def test_get_statistics(self, engine):
        """Test statistics retrieval."""
        stats = engine.get_statistics()
        
        assert isinstance(stats, dict)
        assert "total_evaluations" in stats
        assert "violations_detected" in stats
        assert "average_time_ms" in stats
    
    @pytest.mark.asyncio
    async def test_concurrent_evaluations(self, engine):
        """Test concurrent rule evaluations."""
        requests = [
            RuleEvaluationRequest(content=f"Content {i}", context=RuleContext())
            for i in range(10)
        ]
        
        # Run evaluations concurrently
        tasks = [engine.evaluate(req) for req in requests]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 10
        assert all(isinstance(r, ValidationResult) for r in results)
    
    @pytest.mark.asyncio
    async def test_evaluation_with_context(self, engine):
        """Test evaluation with detailed context."""
        context = RuleContext(
            user_id="user123",
            domain="medical",
            user_role="doctor",
            content_type="diagnosis",
            organization="hospital_a"
        )
        
        request = RuleEvaluationRequest(
            content="Patient diagnosis content",
            context=context
        )
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert result.processing_time_ms > 0


class TestRuleEngineEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.fixture
    async def engine(self):
        """Create a rule engine for testing."""
        rule_manager = RuleManager()
        engine = RuleEngine(rule_manager=rule_manager)
        yield engine
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_empty_content(self, engine):
        """Test evaluation with empty content."""
        request = RuleEvaluationRequest(content="", context=RuleContext())
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert result.valid is True  # Empty content is safe
    
    @pytest.mark.asyncio
    async def test_very_long_content(self, engine):
        """Test evaluation with very long content."""
        long_content = "Safe word. " * 10000  # Very long content
        
        request = RuleEvaluationRequest(content=long_content, context=RuleContext())
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert result.processing_time_ms > 0
    
    @pytest.mark.asyncio
    async def test_unicode_content(self, engine):
        """Test evaluation with unicode and special characters."""
        unicode_content = "Hello 世界 🌍 ñoño €100 «quotes»"
        
        request = RuleEvaluationRequest(content=unicode_content, context=RuleContext())
        
        result = await engine.evaluate(request)
        
        assert isinstance(result, ValidationResult)
        assert result.valid is True


class TestRuleEnginePerformance:
    """Performance tests for rule engine."""
    
    @pytest.fixture
    async def engine(self):
        """Create a rule engine for testing."""
        rule_manager = RuleManager()
        engine = RuleEngine(rule_manager=rule_manager)
        yield engine
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_evaluation_performance(self, engine):
        """Test that evaluations complete within acceptable time."""
        request = RuleEvaluationRequest(
            content="Test content for performance",
            context=RuleContext()
        )
        
        import time
        start = time.time()
        result = await engine.evaluate(request)
        elapsed = (time.time() - start) * 1000
        
        assert elapsed < 1000  # Should complete in under 1 second
        assert result.processing_time_ms > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
