"""
Safety rule catalog - non-negotiable safety rules for content filtering,
security, and compliance enforcement.

Provides predefined safety rule definitions, content filtering patterns,
security patterns, and compliance patterns for GDPR, HIPAA, and PCI.
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class SafetyCategory(str, Enum):
    """Categories of safety rules."""
    CONTENT_FILTERING = "content_filtering"
    PROFANITY = "profanity"
    PII = "pii"
    SENSITIVE_DATA = "sensitive_data"
    SECURITY_INJECTION = "security_injection"
    XSS = "xss"
    PATH_TRAVERSAL = "path_traversal"
    COMPLIANCE_GDPR = "compliance_gdpr"
    COMPLIANCE_HIPAA = "compliance_hipaa"
    COMPLIANCE_PCI = "compliance_pci"
    COMPLIANCE_SOX = "compliance_sox"
    HARMFUL_CONTENT = "harmful_content"
    MALICIOUS_CODE = "malicious_code"
    DATA_EXFILTRATION = "data_exfiltration"
    AUTH_BYPASS = "auth_bypass"


class SafetyLevel(str, Enum):
    """Enforcement levels specific to safety rules."""
    CRITICAL_BLOCK = "critical_block"
    HIGH_BLOCK = "high_block"
    MEDIUM_WARN = "medium_warn"
    LOW_MONITOR = "low_monitor"
    INFORMATIONAL = "informational"


class ComplianceFramework(str, Enum):
    """Compliance frameworks supported by safety rules."""
    GDPR = "gdpr"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    SOX = "sox"
    SOC2 = "soc2"
    ISO_27001 = "iso_27001"
    CUSTOM = "custom"


@dataclass
class SafetyRuleDefinition:
    """Definition of a predefined safety rule."""

    rule_id: str
    name: str
    description: str
    category: SafetyCategory
    severity: RuleSeverity
    enforcement: EnforcementLevel
    patterns: List[RulePattern]
    compliance_frameworks: List[ComplianceFramework] = field(default_factory=list)
    version: str = "1.0.0"
    auto_block: bool = True
    user_override: bool = False
    override_justification_required: bool = True
    tags: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    priority: int = 10
    conditions: Dict[str, Any] = field(default_factory=dict)
    enabled_by_default: bool = True

    def to_rule(self) -> Rule:
        """Convert definition to a Rule model instance."""
        return Rule(
            id=self.rule_id,
            name=self.name,
            description=self.description,
            tier=RuleTier.SAFETY,
            rule_type=RuleType.CONTENT_FILTERING if self.category in (
                SafetyCategory.CONTENT_FILTERING, SafetyCategory.PROFANITY,
                SafetyCategory.PII, SafetyCategory.SENSITIVE_DATA,
                SafetyCategory.HARMFUL_CONTENT,
            ) else RuleType.PATTERN_MATCHING if self.category in (
                SafetyCategory.SECURITY_INJECTION, SafetyCategory.XSS,
                SafetyCategory.PATH_TRAVERSAL, SafetyCategory.MALICIOUS_CODE,
            ) else RuleType.COMPLIANCE_CHECK,
            severity=self.severity,
            status=RuleStatus.ACTIVE if self.enabled_by_default else RuleStatus.INACTIVE,
            patterns=self.patterns,
            conditions=self.conditions,
            exceptions=self.exceptions,
            enforcement_level=self.enforcement,
            auto_block=self.auto_block,
            user_override=self.user_override,
            override_justification_required=self.override_justification_required,
            version=self.version,
            tags=self.tags,
            priority=self.priority,
        )


class SafetyRuleCatalog:
    """Catalog of non-negotiable safety rules.

    Provides predefined safety rule definitions across content filtering,
    security, and compliance domains with versioning and config-driven enable/disable.
    """

    PROFANITY_KEYWORDS = [
        "profanity_1", "profanity_2", "profanity_3",
        "profanity_4", "profanity_5", "profanity_6",
        "profanity_7", "profanity_8", "profanity_9",
        "profanity_10",
    ]

    PII_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "phone_us": r"\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
        "driver_license": r"\b[A-Z]{1,3}\d{4,8}\b",
        "bank_account": r"\b\d{8,17}\b",
        "routing_number": r"\b\d{9}\b",
        "date_of_birth": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    }

    SQL_INJECTION_PATTERNS = [
        r"'.*OR.*'.*'.*",
        r"'.*--",
        r"\bUNION\b.*\bSELECT\b",
        r"\bDROP\b.*\bTABLE\b",
        r"\bDELETE\b.*\bFROM\b",
        r"\bINSERT\b.*\bINTO\b",
        r"\bEXEC\b.*\(.*\)",
        r"\bxp_cmdshell\b",
        r"\bWAITFOR\b.*\bDELAY\b",
        r"'.*OR\s+\d+\s*=\s*\d+.*",
        r"'.*OR\s+'[^']*'\s*=\s*'[^']*'.*",
        r"\bALTER\s+TABLE\b",
        r"\bCREATE\s+TABLE\b",
        r"\bTRUNCATE\b",
        r"\bLOAD_FILE\b",
        r"\bINTO\s+OUTFILE\b",
        r"\bINFORMATION_SCHEMA\b",
        r"\bSLEEP\s*\(\s*\d+\s*\)",
        r"\bBENCHMARK\s*\(.*,.*\)",
    ]

    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript\s*:",
        r"onerror\s*=",
        r"onclick\s*=",
        r"onload\s*=",
        r"onmouseover\s*=",
        r"onfocus\s*=",
        r"onblur\s*=",
        r"onsubmit\s*=",
        r"onchange\s*=",
        r"onkeydown\s*=",
        r"onkeypress\s*=",
        r"<iframe[^>]*>",
        r"<embed[^>]*>",
        r"<object[^>]*>",
        r"<svg[^>]*>.*?<script",
        r"document\.cookie",
        r"document\.location",
        r"window\.location",
        r"eval\s*\(.*\)",
        r"<img[^>]*onerror\s*=",
        r"<body[^>]*onload\s*=",
        r"<input[^>]*onfocus\s*=",
        r"alert\s*\(.*\)",
        r"prompt\s*\(.*\)",
        r"confirm\s*\(.*\)",
        r"<marquee[^>]*on",
    ]

    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"\.\.%2f",
        r"\.\.%5c",
        r"%2e%2e%2f",
        r"%2e%2e%5c",
        r"\.\./\.\./",
        r"\.\.\\\.\.\\",
        r"~root",
        r"~\w+",
        r"/etc/passwd",
        r"/etc/shadow",
        r"/etc/hosts",
        r"/proc/self/",
        r"/sys/class/",
        r"\\\\\\w+\\\\\\w+",
        r"\$\(\.\.\)",
        r"%00",
        r"\\x00",
    ]

    GDPR_KEYWORDS = [
        "gdpr", "personal data", "data subject", "data controller",
        "data processor", "consent", "right to erasure", "right to access",
        "data portability", "privacy notice", "data breach",
        "processing activity", "data protection officer", "dpo",
        "legitimate interest", "purpose limitation", "data minimization",
    ]

    HIPAA_KEYWORDS = [
        "phi", "protected health information", "hipaa", "medical record",
        "patient data", "health information", "ephi", "electronic phi",
        "covered entity", "business associate", "baa", "notice of privacy",
        "treatment payment operations", "tpo", "minimum necessary",
        "healthcare provider", "health plan", "clearinghouse",
    ]

    PCI_KEYWORDS = [
        "pci", "pci dss", "cardholder data", "pan", "primary account number",
        "track data", "cvv", "cvv2", "cvc", "pin block", "chip data",
        "card verification", "merchant id", "acquirer", "tokenization",
        "encryption key", "key rotation", "quarterly scan", "asv scan",
        "self-assessment questionnaire", "saq",
    ]

    SENSITIVE_DATA_PATTERNS = {
        "api_key": r"(?i)(api[_-]?key|apikey|api_secret|api_secret_key)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]",
        "aws_key": r"(?i)(AKIA[0-9A-Z]{16})",
        "private_key_header": r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        "jwt": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "password_var": r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}['\"]",
        "token_var": r"(?i)(token|auth_token|access_token|refresh_token)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{8,}['\"]",
        "connection_string": r"(?i)(connection_string|connstr|conn_string)\s*[:=]\s*['\"].*['\"]",
        "secret_var": r"(?i)(secret|secret_key|client_secret|app_secret)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{8,}['\"]",
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._rules: Dict[str, Rule] = {}
        self._definitions: Dict[str, SafetyRuleDefinition] = {}
        self._category_enabled: Dict[SafetyCategory, bool] = {
            cat: True for cat in SafetyCategory
        }
        self._compliance_enabled: Dict[ComplianceFramework, bool] = {
            cf: True for cf in ComplianceFramework
        }
        self._version: str = "1.0.0"
        self._changelog: List[Dict[str, Any]] = []
        self._lock = RLock()
        self._update_history: List[Dict[str, Any]] = []
        self._test_results: Dict[str, Dict[str, Any]] = {}

        self._initialize_catalog()
        logger.info(
            "SafetyRuleCatalog initialized (version=%s, %d rules)",
            self._version,
            len(self._definitions),
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the safety catalog."""
        return {
            "enable_content_filtering": True,
            "enable_profanity": True,
            "enable_pii_detection": True,
            "enable_sensitive_data": True,
            "enable_security_injection": True,
            "enable_xss": True,
            "enable_path_traversal": True,
            "enable_compliance_gdpr": True,
            "enable_compliance_hipaa": True,
            "enable_compliance_pci": True,
            "enable_compliance_sox": True,
            "enable_harmful_content": True,
            "enable_malicious_code": True,
            "enable_data_exfiltration": True,
            "enable_auth_bypass": True,
            "strict_mode": True,
            "auto_register_rules": True,
            "pii_redaction_enabled": True,
            "pii_redaction_char": "*",
            "max_rule_patterns": 50,
            "version_check_enabled": True,
            "rule_tags_prefix": "safety",
            "log_all_violations": True,
        }

    def _initialize_catalog(self) -> None:
        """Initialize the catalog with predefined safety rule definitions."""
        self._add_content_filtering_rules()
        self._add_profanity_rules()
        self._add_pii_rules()
        self._add_sensitive_data_rules()
        self._add_security_injection_rules()
        self._add_xss_rules()
        self._add_path_traversal_rules()
        self._add_compliance_rules()
        self._add_harmful_content_rules()
        self._add_malicious_code_rules()
        self._add_data_exfiltration_rules()
        self._add_auth_bypass_rules()

    def _add_content_filtering_rules(self) -> None:
        """Add content filtering rules to the catalog."""
        definitions = [
            SafetyRuleDefinition(
                rule_id="safety_content_001",
                name="Harmful Content Detection",
                description="Detects and blocks harmful, abusive, or dangerous content",
                category=SafetyCategory.CONTENT_FILTERING,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.CONTENT_FILTERING,
                        keywords=[
                            "self-harm", "suicide", "self-destruct",
                            "violence", "abuse", "harassment",
                        ],
                        confidence_threshold=0.7,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                priority=1,
                tags=["content_filtering", "harmful_content", "critical"],
            ),
            SafetyRuleDefinition(
                rule_id="safety_content_002",
                name="Hate Speech Detection",
                description="Detects and blocks hate speech and discriminatory content",
                category=SafetyCategory.CONTENT_FILTERING,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.SEMANTIC_ANALYSIS,
                        keywords=[
                            "hate", "discrimination", "racial slur",
                            "incitement", "intolerance",
                        ],
                        confidence_threshold=0.8,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                priority=2,
                tags=["content_filtering", "hate_speech", "critical"],
            ),
            SafetyRuleDefinition(
                rule_id="safety_content_003",
                name="Harassment and Bullying Prevention",
                description="Detects content that harasses, bullies, or intimidates",
                category=SafetyCategory.CONTENT_FILTERING,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.CONTENT_FILTERING,
                        keywords=[
                            "harass", "bully", "intimidate",
                            "threaten", "abuse", "stalking",
                        ],
                        confidence_threshold=0.75,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                priority=5,
                tags=["content_filtering", "harassment", "high"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_profanity_rules(self) -> None:
        """Add profanity filtering rules to the catalog."""
        definition = SafetyRuleDefinition(
            rule_id="safety_profanity_001",
            name="Profanity Detection",
            description="Detects and filters profanity and inappropriate language",
            category=SafetyCategory.PROFANITY,
            severity=RuleSeverity.MEDIUM,
            enforcement=EnforcementLevel.ADVISORY,
            patterns=[
                RulePattern(
                    type=RuleType.CONTENT_FILTERING,
                    keywords=self.PROFANITY_KEYWORDS,
                    confidence_threshold=0.8,
                    action="warn",
                ),
            ],
            auto_block=False,
            user_override=True,
            override_justification_required=True,
            priority=50,
            tags=["profanity", "language_filtering", "medium"],
        )
        self._register_definition(definition)

    def _add_pii_rules(self) -> None:
        """Add PII detection rules to the catalog."""
        definitions = [
            SafetyRuleDefinition(
                rule_id="safety_pii_001",
                name="Email Address Detection",
                description="Detects email addresses in content",
                category=SafetyCategory.PII,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.PII_PATTERNS["email"]],
                        confidence_threshold=0.9,
                        action="redact",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["pii", "email", "gdpr", "hippa"],
                compliance_frameworks=[ComplianceFramework.GDPR],
                priority=20,
            ),
            SafetyRuleDefinition(
                rule_id="safety_pii_002",
                name="Phone Number Detection",
                description="Detects US phone numbers in content",
                category=SafetyCategory.PII,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.PII_PATTERNS["phone_us"]],
                        confidence_threshold=0.85,
                        action="redact",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["pii", "phone", "gdpr"],
                compliance_frameworks=[ComplianceFramework.GDPR],
                priority=21,
            ),
            SafetyRuleDefinition(
                rule_id="safety_pii_003",
                name="SSN Detection",
                description="Detects Social Security Numbers in content",
                category=SafetyCategory.PII,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.PII_PATTERNS["ssn"]],
                        confidence_threshold=0.95,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                tags=["pii", "ssn", "critical", "gdpr", "hippa", "pci"],
                compliance_frameworks=[ComplianceFramework.GDPR, ComplianceFramework.HIPAA],
                priority=3,
            ),
            SafetyRuleDefinition(
                rule_id="safety_pii_004",
                name="Credit Card Number Detection",
                description="Detects credit card numbers in content for PCI compliance",
                category=SafetyCategory.PII,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.PII_PATTERNS["credit_card"]],
                        confidence_threshold=0.9,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                tags=["pii", "credit_card", "pci", "critical"],
                compliance_frameworks=[ComplianceFramework.PCI_DSS],
                priority=4,
            ),
            SafetyRuleDefinition(
                rule_id="safety_pii_005",
                name="Date of Birth Detection",
                description="Detects dates of birth in content",
                category=SafetyCategory.PII,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.PII_PATTERNS["date_of_birth"]],
                        confidence_threshold=0.7,
                        action="redact",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["pii", "dob", "gdpr"],
                compliance_frameworks=[ComplianceFramework.GDPR],
                priority=40,
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_sensitive_data_rules(self) -> None:
        """Add sensitive data detection rules to the catalog."""
        definitions = [
            SafetyRuleDefinition(
                rule_id="safety_sensitive_001",
                name="API Key Detection",
                description="Detects exposed API keys and secrets in content",
                category=SafetyCategory.SENSITIVE_DATA,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[
                            self.SENSITIVE_DATA_PATTERNS["api_key"],
                            self.SENSITIVE_DATA_PATTERNS["aws_key"],
                        ],
                        confidence_threshold=0.9,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                tags=["sensitive", "api_key", "secret", "critical"],
                priority=6,
            ),
            SafetyRuleDefinition(
                rule_id="safety_sensitive_002",
                name="Private Key Detection",
                description="Detects exposed private keys and certificates",
                category=SafetyCategory.SENSITIVE_DATA,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.SENSITIVE_DATA_PATTERNS["private_key_header"]],
                        confidence_threshold=0.95,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                tags=["sensitive", "private_key", "certificate", "critical"],
                priority=7,
            ),
            SafetyRuleDefinition(
                rule_id="safety_sensitive_003",
                name="Password Detection",
                description="Detects exposed passwords and credentials",
                category=SafetyCategory.SENSITIVE_DATA,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.SENSITIVE_DATA_PATTERNS["password_var"]],
                        confidence_threshold=0.85,
                        action="block",
                    ),
                ],
                auto_block=True,
                user_override=False,
                tags=["sensitive", "password", "credentials", "critical"],
                priority=8,
            ),
            SafetyRuleDefinition(
                rule_id="safety_sensitive_004",
                name="JWT Token Detection",
                description="Detects JWT tokens that may contain sensitive claims",
                category=SafetyCategory.SENSITIVE_DATA,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        regex_patterns=[self.SENSITIVE_DATA_PATTERNS["jwt"]],
                        confidence_threshold=0.8,
                        action="warn",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["sensitive", "jwt", "token", "high"],
                priority=30,
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_security_injection_rules(self) -> None:
        """Add security injection detection rules to the catalog."""
        definition = SafetyRuleDefinition(
            rule_id="safety_injection_001",
            name="SQL Injection Detection",
            description="Detects SQL injection patterns in content",
            category=SafetyCategory.SECURITY_INJECTION,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    regex_patterns=self.SQL_INJECTION_PATTERNS,
                    confidence_threshold=0.8,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "injection", "sql", "critical"],
            priority=9,
        )
        self._register_definition(definition)

    def _add_xss_rules(self) -> None:
        """Add XSS detection rules to the catalog."""
        definition = SafetyRuleDefinition(
            rule_id="safety_xss_001",
            name="Cross-Site Scripting Detection",
            description="Detects XSS attack patterns in content",
            category=SafetyCategory.XSS,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    regex_patterns=self.XSS_PATTERNS,
                    confidence_threshold=0.8,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "xss", "injection", "critical"],
            priority=10,
        )
        self._register_definition(definition)

    def _add_path_traversal_rules(self) -> None:
        """Add path traversal detection rules to the catalog."""
        definition = SafetyRuleDefinition(
            rule_id="safety_path_001",
            name="Path Traversal Detection",
            description="Detects path traversal attack patterns in content",
            category=SafetyCategory.PATH_TRAVERSAL,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    regex_patterns=self.PATH_TRAVERSAL_PATTERNS,
                    confidence_threshold=0.85,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "path_traversal", "filesystem", "critical"],
            priority=11,
        )
        self._register_definition(definition)

    def _add_compliance_rules(self) -> None:
        """Add compliance-related safety rules to the catalog."""
        definitions = [
            SafetyRuleDefinition(
                rule_id="safety_compliance_gdpr_001",
                name="GDPR Personal Data Detection",
                description="Detects potential GDPR personal data in content",
                category=SafetyCategory.COMPLIANCE_GDPR,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.COMPLIANCE_CHECK,
                        keywords=self.GDPR_KEYWORDS,
                        confidence_threshold=0.6,
                        action="warn",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["compliance", "gdpr", "personal_data"],
                compliance_frameworks=[ComplianceFramework.GDPR],
                priority=60,
            ),
            SafetyRuleDefinition(
                rule_id="safety_compliance_hipaa_001",
                name="HIPAA Protected Health Information Detection",
                description="Detects potential HIPAA PHI in content",
                category=SafetyCategory.COMPLIANCE_HIPAA,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.COMPLIANCE_CHECK,
                        keywords=self.HIPAA_KEYWORDS,
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["compliance", "hipaa", "phi", "health"],
                compliance_frameworks=[ComplianceFramework.HIPAA],
                priority=15,
            ),
            SafetyRuleDefinition(
                rule_id="safety_compliance_pci_001",
                name="PCI DSS Cardholder Data Detection",
                description="Detects potential PCI DSS cardholder data in content",
                category=SafetyCategory.COMPLIANCE_PCI,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.COMPLIANCE_CHECK,
                        keywords=self.PCI_KEYWORDS,
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                auto_block=False,
                user_override=False,
                tags=["compliance", "pci", "cardholder", "payment"],
                compliance_frameworks=[ComplianceFramework.PCI_DSS],
                priority=12,
            ),
            SafetyRuleDefinition(
                rule_id="safety_compliance_sox_001",
                name="SOX Financial Data Detection",
                description="Detects potential SOX-regulated financial data",
                category=SafetyCategory.COMPLIANCE_SOX,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.COMPLIANCE_CHECK,
                        keywords=[
                            "financial report", "audit trail", "internal control",
                            "disclosure", "financial statement", "sox compliance",
                            "sarbanes-oxley", "financial control",
                        ],
                        confidence_threshold=0.6,
                        action="warn",
                    ),
                ],
                auto_block=False,
                user_override=True,
                override_justification_required=True,
                tags=["compliance", "sox", "financial"],
                compliance_frameworks=[ComplianceFramework.SOX],
                priority=70,
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_harmful_content_rules(self) -> None:
        """Add harmful content detection rules."""
        definition = SafetyRuleDefinition(
            rule_id="safety_harmful_001",
            name="Dangerous Instruction Detection",
            description="Detects requests for dangerous or illegal instructions",
            category=SafetyCategory.HARMFUL_CONTENT,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.SEMANTIC_ANALYSIS,
                    keywords=[
                        "bomb", "explosive", "weapon", "illegal drug",
                        "manufacture", "synthesize", "toxic", "poison",
                    ],
                    confidence_threshold=0.85,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["harmful", "dangerous", "illegal", "critical"],
            priority=13,
        )
        self._register_definition(definition)

    def _add_malicious_code_rules(self) -> None:
        """Add malicious code detection rules."""
        definition = SafetyRuleDefinition(
            rule_id="safety_malicious_001",
            name="Malicious Code Pattern Detection",
            description="Detects potentially malicious code patterns",
            category=SafetyCategory.MALICIOUS_CODE,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    keywords=[
                        "eval(", "exec(", "system(", "popen(",
                        "subprocess.call", "os.system", "base64.b64decode",
                        "pickle.loads", "__import__", "__builtins__",
                    ],
                    regex_patterns=[
                        r"base64\.(b64decode|decodestring)\s*\(",
                        r"exec\s*\(.*['\"].*\)",
                        r"eval\s*\(.*['\"].*\)",
                        r"pickle\.loads\s*\(",
                    ],
                    confidence_threshold=0.8,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "malicious", "code_execution", "critical"],
            priority=14,
        )
        self._register_definition(definition)

    def _add_data_exfiltration_rules(self) -> None:
        """Add data exfiltration detection rules."""
        definition = SafetyRuleDefinition(
            rule_id="safety_exfil_001",
            name="Data Exfiltration Pattern Detection",
            description="Detects patterns indicative of data exfiltration",
            category=SafetyCategory.DATA_EXFILTRATION,
            severity=RuleSeverity.HIGH,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    keywords=[
                        "exfiltrate", "exfil", "data leak", "data theft",
                        "download all", "dump database", "export all",
                    ],
                    regex_patterns=[
                        r"(?i)SELECT\s+\*\s+FROM\s+\w+",
                        r"(?i)COPY\s+\w+\s+TO\s+",
                        r"(?i)mysqldump\s+.*--all-databases",
                        r"(?i)pg_dump\s+.*-a\s+-h",
                    ],
                    confidence_threshold=0.75,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "exfiltration", "data_theft", "high"],
            priority=16,
        )
        self._register_definition(definition)

    def _add_auth_bypass_rules(self) -> None:
        """Add authentication bypass detection rules."""
        definition = SafetyRuleDefinition(
            rule_id="safety_auth_001",
            name="Authentication Bypass Pattern Detection",
            description="Detects auth bypass and privilege escalation patterns",
            category=SafetyCategory.AUTH_BYPASS,
            severity=RuleSeverity.CRITICAL,
            enforcement=EnforcementLevel.STRICT,
            patterns=[
                RulePattern(
                    type=RuleType.PATTERN_MATCHING,
                    keywords=[
                        "bypass authentication", "privilege escalation", "admin bypass",
                        "role escalation", "token bypass", "session hijack",
                    ],
                    regex_patterns=[
                        r"(?i)admin\s*=\s*true",
                        r"(?i)is_admin\s*=\s*1",
                        r"(?i)role\s*=\s*['\"]admin['\"]",
                        r"(?i)\.setAttribute\(\s*['\"]admin['\"]",
                    ],
                    confidence_threshold=0.8,
                    action="block",
                ),
            ],
            auto_block=True,
            user_override=False,
            tags=["security", "auth", "bypass", "privilege", "critical"],
            priority=17,
        )
        self._register_definition(definition)

    def _register_definition(self, definition: SafetyRuleDefinition) -> None:
        """Register a safety rule definition in the catalog."""
        if definition.rule_id in self._definitions:
            logger.warning("Overwriting existing rule definition: %s", definition.rule_id)
        self._definitions[definition.rule_id] = definition
        if self._config.get("auto_register_rules", True):
            rule = definition.to_rule()
            self._rules[definition.rule_id] = rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a safety rule by ID."""
        return self._rules.get(rule_id)

    def get_definition(self, rule_id: str) -> Optional[SafetyRuleDefinition]:
        """Get a safety rule definition by ID."""
        return self._definitions.get(rule_id)

    def get_rules(
        self,
        category: Optional[SafetyCategory] = None,
        severity: Optional[RuleSeverity] = None,
        enabled_only: bool = False,
    ) -> List[Rule]:
        """Get safety rules with optional filtering."""
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if category.value in r.tags or category == self._get_rule_category(r)]
        if severity:
            rules = [r for r in rules if r.severity == severity]
        if enabled_only:
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
        return rules

    def _get_rule_category(self, rule: Rule) -> Optional[SafetyCategory]:
        """Determine the safety category of a rule."""
        for definition in self._definitions.values():
            if definition.rule_id == rule.id:
                return definition.category
        return None

    def get_definitions(
        self,
        category: Optional[SafetyCategory] = None,
        compliance_framework: Optional[ComplianceFramework] = None,
    ) -> List[SafetyRuleDefinition]:
        """Get rule definitions with optional filtering."""
        definitions = list(self._definitions.values())
        if category:
            definitions = [d for d in definitions if d.category == category]
        if compliance_framework:
            definitions = [
                d for d in definitions
                if compliance_framework in d.compliance_frameworks
            ]
        return definitions

    def enable_category(self, category: SafetyCategory) -> None:
        """Enable all rules in a safety category."""
        self._category_enabled[category] = True
        for definition in self._definitions.values():
            if definition.category == category:
                if definition.rule_id in self._rules:
                    self._rules[definition.rule_id].status = RuleStatus.ACTIVE
        logger.info("Enabled safety category: %s", category.value)

    def disable_category(self, category: SafetyCategory) -> None:
        """Disable all rules in a safety category."""
        self._category_enabled[category] = False
        for definition in self._definitions.values():
            if definition.category == category:
                if definition.rule_id in self._rules:
                    self._rules[definition.rule_id].status = RuleStatus.INACTIVE
        logger.info("Disabled safety category: %s", category.value)

    def is_category_enabled(self, category: SafetyCategory) -> bool:
        """Check if a safety category is enabled."""
        return self._category_enabled.get(category, True)

    def enable_compliance_framework(self, framework: ComplianceFramework) -> None:
        """Enable all rules for a compliance framework."""
        self._compliance_enabled[framework] = True
        for definition in self._definitions.values():
            if framework in definition.compliance_frameworks:
                if definition.rule_id in self._rules:
                    self._rules[definition.rule_id].status = RuleStatus.ACTIVE
        logger.info("Enabled compliance framework: %s", framework.value)

    def disable_compliance_framework(self, framework: ComplianceFramework) -> None:
        """Disable all rules for a compliance framework."""
        self._compliance_enabled[framework] = False
        for definition in self._definitions.values():
            if framework in definition.compliance_frameworks:
                if definition.rule_id in self._rules:
                    self._rules[definition.rule_id].status = RuleStatus.INACTIVE
        logger.info("Disabled compliance framework: %s", framework.value)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the safety catalog."""
        total = len(self._rules)
        active = sum(1 for r in self._rules.values() if r.status == RuleStatus.ACTIVE)
        by_severity: Dict[str, int] = defaultdict(int)
        by_category: Dict[str, int] = defaultdict(int)
        by_compliance: Dict[str, int] = defaultdict(int)
        for definition in self._definitions.values():
            by_category[definition.category.value] += 1
            for cf in definition.compliance_frameworks:
                by_compliance[cf.value] += 1
        for rule in self._rules.values():
            by_severity[rule.severity.value] += 1
        return {
            "total_rules": total,
            "active_rules": active,
            "inactive_rules": total - active,
            "version": self._version,
            "rules_by_severity": dict(by_severity),
            "rules_by_category": dict(by_category),
            "rules_by_compliance": dict(by_compliance),
            "enabled_categories": {k.value: v for k, v in self._category_enabled.items()},
            "enabled_frameworks": {k.value: v for k, v in self._compliance_enabled.items()},
        }

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a specific safety rule."""
        if rule_id in self._rules:
            self._rules[rule_id].status = RuleStatus.ACTIVE
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a specific safety rule."""
        if rule_id in self._rules:
            self._rules[rule_id].status = RuleStatus.INACTIVE
            return True
        return False

    def update_catalog(self, version: str, changes: List[Dict[str, Any]]) -> None:
        """Update the catalog version with a list of changes."""
        self._version = version
        self._changelog.append({
            "version": version,
            "timestamp": datetime.utcnow().isoformat(),
            "changes": changes,
        })
        self._update_history.append({
            "version": version,
            "changes": changes,
            "applied_at": datetime.utcnow().isoformat(),
        })
        logger.info("Safety catalog updated to version %s (%d changes)", version, len(changes))

    def get_changelog(self) -> List[Dict[str, Any]]:
        """Get the catalog changelog."""
        return list(self._changelog)

    def get_version(self) -> str:
        """Get the current catalog version."""
        return self._version

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the catalog to a dictionary."""
        return {
            "version": self._version,
            "rules": [d.to_rule().dict() for d in self._definitions.values()],
            "category_enabled": {k.value: v for k, v in self._category_enabled.items()},
            "compliance_enabled": {k.value: v for k, v in self._compliance_enabled.items()},
            "changelog": self._changelog,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafetyRuleCatalog":
        """Create a catalog from a dictionary."""
        catalog = cls()
        catalog._version = data.get("version", "1.0.0")
        category_enabled = data.get("category_enabled", {})
        for cat_value, enabled in category_enabled.items():
            try:
                cat = SafetyCategory(cat_value)
                catalog._category_enabled[cat] = enabled
            except ValueError:
                pass
        catalog._changelog = data.get("changelog", [])
        return catalog

    def to_json(self) -> str:
        """Serialize the catalog to JSON."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "SafetyRuleCatalog":
        """Create a catalog from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_yaml(self) -> str:
        """Serialize the catalog to YAML."""
        return yaml.dump(self.to_dict(), default_flow_style=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "SafetyRuleCatalog":
        """Create a catalog from a YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)
