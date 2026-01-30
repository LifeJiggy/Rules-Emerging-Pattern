"""Tests for rule models."""
import pytest
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ActionTaken

class TestRuleModel:
    """Test Rule model."""
    
    def test_rule_creation(self):
        """Test basic rule creation."""
        rule = Rule(
            id="test_001",
            name="Test Rule",
            description="Test",
            tier=RuleTier.OPERATIONAL,
            rule_type=RuleType.CONTENT_FILTERING,
            severity=RuleSeverity.MEDIUM,
            enforcement_level=EnforcementLevel.ADVISORY
        )
        assert rule.id == "test_001"
        assert rule.name == "Test Rule"
    
    def test_validation_result(self):
        """Test validation result."""
        result = ValidationResult(valid=True, total_score=0.9)
        assert result.valid is True
        assert result.total_score == 0.9

if __name__ == "__main__":
    pytest.main([__file__])
