"""Data redaction module for privacy protection."""
import logging
import re
from typing import Dict, List, Optional, Pattern
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RedactionRule:
    """Rule for redacting sensitive data."""
    pattern: Pattern
    replacement: str
    description: str


class DataRedactor:
    """Redacts sensitive information from data."""
    
    def __init__(self):
        """Initialize the data redactor."""
        self.redaction_rules: List[RedactionRule] = []
        self.redaction_count = 0
        self._setup_default_rules()
        logger.info("DataRedactor initialized with default rules")
    
    def _setup_default_rules(self) -> None:
        """Set up default redaction rules for common PII."""
        default_patterns = [
            (r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', 'Social Security Number'),
            (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REDACTED_EMAIL]', 'Email Address'),
            (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[REDACTED_CC]', 'Credit Card Number'),
            (r'\b\d{3}-\d{3}-\d{4}\b', '[REDACTED_PHONE]', 'Phone Number'),
            (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]', 'IP Address'),
        ]
        
        for pattern, replacement, description in default_patterns:
            self.add_redaction_rule(pattern, replacement, description)
    
    def add_redaction_rule(
        self,
        pattern: str,
        replacement: str,
        description: str
    ) -> None:
        """Add a custom redaction rule.
        
        Args:
            pattern: Regular expression pattern to match
            replacement: Replacement string
            description: Description of what this rule redacts
        """
        try:
            compiled_pattern = re.compile(pattern)
            rule = RedactionRule(compiled_pattern, replacement, description)
            self.redaction_rules.append(rule)
            logger.info(f"Added redaction rule: {description}")
        except re.error as e:
            logger.error(f"Invalid regex pattern: {e}")
    
    def redact(self, text: str, additional_rules: Optional[List[RedactionRule]] = None) -> str:
        """Redact sensitive information from text.
        
        Args:
            text: Text to redact
            additional_rules: Optional additional rules to apply
            
        Returns:
            Redacted text
        """
        redacted_text = text
        rules_to_apply = self.redaction_rules + (additional_rules or [])
        
        for rule in rules_to_apply:
            matches = rule.pattern.findall(redacted_text)
            if matches:
                redacted_text = rule.pattern.sub(rule.replacement, redacted_text)
                self.redaction_count += len(matches)
                logger.debug(f"Redacted {len(matches)} instances of {rule.description}")
        
        return redacted_text
    
    def redact_dict(
        self,
        data: Dict,
        sensitive_keys: Optional[List[str]] = None
    ) -> Dict:
        """Redact sensitive fields in a dictionary.
        
        Args:
            data: Dictionary to redact
            sensitive_keys: List of keys to redact (if None, redacts all string values)
            
        Returns:
            Dictionary with redacted values
        """
        redacted = {}
        default_sensitive = ['ssn', 'email', 'password', 'credit_card', 'phone', 'address']
        keys_to_redact = sensitive_keys or default_sensitive
        
        for key, value in data.items():
            if isinstance(value, str):
                if any(sensitive in key.lower() for sensitive in keys_to_redact):
                    redacted[key] = '[REDACTED]'
                    self.redaction_count += 1
                else:
                    redacted[key] = self.redact(value)
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value, keys_to_redact)
            elif isinstance(value, list):
                redacted[key] = [
                    self.redact(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                redacted[key] = value
        
        return redacted
    
    def analyze_for_pii(self, text: str) -> Dict:
        """Analyze text for potential PII without redacting.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with PII findings
        """
        findings = []
        
        for rule in self.redaction_rules:
            matches = rule.pattern.findall(text)
            if matches:
                findings.append({
                    'type': rule.description,
                    'count': len(matches),
                    'pattern': rule.pattern.pattern
                })
        
        return {
            'has_pii': len(findings) > 0,
            'findings': findings,
            'total_pii_instances': sum(f['count'] for f in findings),
            'risk_level': 'high' if len(findings) > 3 else 'medium' if len(findings) > 0 else 'low',
            'timestamp': datetime.now().isoformat()
        }
    
    def get_stats(self) -> Dict:
        """Get redaction statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_rules': len(self.redaction_rules),
            'total_redactions': self.redaction_count,
            'rule_descriptions': [rule.description for rule in self.redaction_rules]
        }
