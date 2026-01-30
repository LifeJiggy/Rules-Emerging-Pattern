"""Format validation for structured data."""
import logging
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FormatType(Enum):
    """Supported format types."""
    JSON = "json"
    XML = "xml"
    YAML = "yaml"
    MARKDOWN = "markdown"
    HTML = "html"
    CSV = "csv"


@dataclass
class FormatError:
    """Represents a format validation error."""
    format_type: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None


class FormatValidator:
    """Validates various data formats."""
    
    def __init__(self):
        self.supported_formats = [fmt.value for fmt in FormatType]
        logger.info("FormatValidator initialized")
    
    def validate(self, content: str, format_type: str) -> Tuple[bool, List[FormatError]]:
        """Validate content against a specific format."""
        errors = []
        
        if format_type == "json":
            return self._validate_json(content)
        elif format_type == "yaml":
            return self._validate_yaml(content)
        elif format_type == "xml":
            return self._validate_xml(content)
        else:
            errors.append(FormatError(format_type=format_type, message="Unsupported format"))
        
        return len(errors) == 0, errors
    
    def _validate_json(self, content: str) -> Tuple[bool, List[FormatError]]:
        """Validate JSON format."""
        errors = []
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(FormatError(format_type="json", message=str(e)))
        return len(errors) == 0, errors
    
    def _validate_yaml(self, content: str) -> Tuple[bool, List[FormatError]]:
        """Validate YAML format."""
        errors = []
        try:
            import yaml
            yaml.safe_load(content)
        except Exception as e:
            errors.append(FormatError(format_type="yaml", message=str(e)))
        return len(errors) == 0, errors
    
    def _validate_xml(self, content: str) -> Tuple[bool, List[FormatError]]:
        """Validate XML format."""
        errors = []
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(content)
        except Exception as e:
            errors.append(FormatError(format_type="xml", message=str(e)))
        return len(errors) == 0, errors
