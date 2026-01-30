"""Tests for enforcement handlers."""
import pytest
from rule_engines.enforcement.strict_enforcer import StrictEnforcer
from rules_emerging_pattern.models.rule import Rule

class TestStrictEnforcer:
    """Test strict enforcer."""
    
    def test_enforcer_creation(self):
        """Test enforcer creation."""
        enforcer = StrictEnforcer()
        assert enforcer is not None

if __name__ == "__main__":
    pytest.main([__file__])
