"""Content validation for input data."""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error."""
    field: str
    message: str
    severity: str = "error"


class ContentValidator:
    """Validates content for safety, format, and compliance."""
    
    def __init__(self):
        self.max_content_length = 100000
        self.min_content_length = 1
        self.forbidden_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
        ]
        logger.info("ContentValidator initialized")
    
    def validate_content(
        self,
        content: str,
        content_type: str = "text",
        options: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate content against all validation rules.
        
        Args:
            content: The content to validate
            content_type: Type of content (text, html, markdown, etc.)
            options: Additional validation options
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        options = options or {}
        
        # Check if content is empty
        if not content or not content.strip():
            errors.append(ValidationError(
                field="content",
                message="Content cannot be empty",
                severity="error"
            ))
            return False, errors
        
        # Check length constraints
        length_valid, length_errors = self._validate_length(content, options)
        errors.extend(length_errors)
        
        # Check for forbidden patterns
        pattern_valid, pattern_errors = self._validate_forbidden_patterns(content)
        errors.extend(pattern_errors)
        
        # Content type specific validation
        if content_type == "html":
            html_valid, html_errors = self._validate_html(content)
            errors.extend(html_errors)
        elif content_type == "json":
            json_valid, json_errors = self._validate_json(content)
            errors.extend(json_errors)
        
        is_valid = len([e for e in errors if e.severity == "error"]) == 0
        
        if not is_valid:
            logger.warning(f"Content validation failed with {len(errors)} errors")
        
        return is_valid, errors
    
    def _validate_length(
        self,
        content: str,
        options: Dict[str, Any]
    ) -> Tuple[bool, List[ValidationError]]:
        """Validate content length."""
        errors = []
        
        max_length = options.get('max_length', self.max_content_length)
        min_length = options.get('min_length', self.min_content_length)
        
        content_length = len(content)
        
        if content_length < min_length:
            errors.append(ValidationError(
                field="content",
                message=f"Content too short: {content_length} chars (min: {min_length})",
                severity="error"
            ))
        
        if content_length > max_length:
            errors.append(ValidationError(
                field="content",
                message=f"Content too long: {content_length} chars (max: {max_length})",
                severity="error"
            ))
        
        return len(errors) == 0, errors
    
    def _validate_forbidden_patterns(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """Check for forbidden patterns in content."""
        errors = []
        
        for pattern in self.forbidden_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                errors.append(ValidationError(
                    field="content",
                    message=f"Forbidden pattern detected: {match.group()[:50]}...",
                    severity="error"
                ))
        
        return len(errors) == 0, errors
    
    def _validate_html(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """Validate HTML content."""
        errors = []
        
        # Check for unclosed tags
        # Simple check for common unclosed tags
        open_tags = len(re.findall(r'<[a-zA-Z][^/>]*>', content))
        close_tags = len(re.findall(r'</[a-zA-Z][^>]*>', content))
        self_closing = len(re.findall(r'<[a-zA-Z][^>]*/>', content))
        
        if open_tags > (close_tags + self_closing):
            errors.append(ValidationError(
                field="content",
                message="Potentially unclosed HTML tags detected",
                severity="warning"
            ))
        
        return len(errors) == 0, errors
    
    def _validate_json(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """Validate JSON content."""
        errors = []
        
        try:
            import json
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(ValidationError(
                field="content",
                message=f"Invalid JSON: {str(e)}",
                severity="error"
            ))
        
        return len(errors) == 0, errors
    
    def validate_batch(
        self,
        contents: List[str],
        content_type: str = "text",
        options: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[bool, List[ValidationError]]]:
        """
        Validate multiple content items.
        
        Args:
            contents: List of content strings to validate
            content_type: Type of content
            options: Validation options
            
        Returns:
            List of validation results
        """
        results = []
        for i, content in enumerate(contents):
            logger.debug(f"Validating content item {i+1}/{len(contents)}")
            is_valid, errors = self.validate_content(content, content_type, options)
            results.append((is_valid, errors))
        
        return results
    
    def add_forbidden_pattern(self, pattern: str) -> None:
        """Add a custom forbidden pattern."""
        self.forbidden_patterns.append(pattern)
        logger.info(f"Added forbidden pattern: {pattern[:50]}...")
    
    def get_validation_summary(self, errors: List[ValidationError]) -> Dict[str, Any]:
        """Get a summary of validation errors."""
        error_count = len([e for e in errors if e.severity == "error"])
        warning_count = len([e for e in errors if e.severity == "warning"])
        
        return {
            "total_issues": len(errors),
            "errors": error_count,
            "warnings": warning_count,
            "fields_affected": list(set(e.field for e in errors))
        }
