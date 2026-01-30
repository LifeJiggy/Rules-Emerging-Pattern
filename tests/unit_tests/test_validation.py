"""Tests for validation systems."""
import pytest
from validation_systems.input_validation.content_validator import ContentValidator

class TestContentValidator:
    """Test content validator."""
    
    def test_validate_safe_content(self):
        """Test safe content validation."""
        validator = ContentValidator()
        is_valid, errors = validator.validate_content("Safe content")
        assert is_valid is True
        assert len(errors) == 0

if __name__ == "__main__":
    pytest.main([__file__])
