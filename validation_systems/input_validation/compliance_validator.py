"""Compliance validation for legal and policy requirements."""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ComplianceIssue:
    """Represents a compliance issue."""
    regulation: str
    issue_type: str
    severity: str
    message: str
    recommendation: str


class ComplianceValidator:
    """Validates content for compliance with regulations."""
    
    def __init__(self):
        self.regulations = {
            "copyright": {"max_quote_length": 100, "require_attribution": True},
            "gdpr": {"require_consent": True, "allow_deletion": True},
            "hipaa": {"protect_phi": True}
        }
        logger.info("ComplianceValidator initialized")
    
    def validate(
        self,
        content: str,
        regulations: Optional[List[str]] = None
    ) -> Tuple[bool, List[ComplianceIssue]]:
        """Validate content against compliance regulations."""
        issues = []
        regs_to_check = regulations or list(self.regulations.keys())
        
        for regulation in regs_to_check:
            if regulation == "copyright":
                issue = self._check_copyright(content)
                if issue:
                    issues.append(issue)
            elif regulation == "gdpr":
                issue = self._check_gdpr(content)
                if issue:
                    issues.append(issue)
        
        return len(issues) == 0, issues
    
    def _check_copyright(self, content: str) -> Optional[ComplianceIssue]:
        """Check copyright compliance."""
        word_count = len(content.split())
        if word_count > self.regulations["copyright"]["max_quote_length"]:
            return ComplianceIssue(
                regulation="copyright",
                issue_type="excessive_quotation",
                severity="medium",
                message=f"Content exceeds maximum quotation length ({word_count} words)",
                recommendation="Reduce quoted content or obtain permission"
            )
        return None
    
    def _check_gdpr(self, content: str) -> Optional[ComplianceIssue]:
        """Check GDPR compliance."""
        # Check for potential PII
        pii_patterns = [
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"  # Email
        ]
        
        for pattern in pii_patterns:
            if re.search(pattern, content):
                return ComplianceIssue(
                    regulation="gdpr",
                    issue_type="potential_pii",
                    severity="high",
                    message="Potential personally identifiable information detected",
                    recommendation="Review and redact PII or ensure proper consent"
                )
        return None
