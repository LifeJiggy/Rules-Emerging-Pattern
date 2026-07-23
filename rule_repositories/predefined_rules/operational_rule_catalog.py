"""
Operational rule catalog - high-priority operational rules for workflow validation,
quality assessment, and structural validation.

Provides predefined operational rule definitions with config-driven parameters
for enforcing production-grade workflow, quality, and structural standards.
"""

import hashlib
import json
import logging
import os
import re
import time
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


class OperationalCategory(str, Enum):
    """Categories of operational rules."""
    WORKFLOW_VALIDATION = "workflow_validation"
    QUALITY_ASSESSMENT = "quality_assessment"
    STRUCTURAL_VALIDATION = "structural_validation"
    PERFORMANCE_MONITORING = "performance_monitoring"
    CONSISTENCY_CHECK = "consistency_check"
    CONFIGURATION_VALIDATION = "configuration_validation"
    DEPENDENCY_CHECK = "dependency_check"
    DATA_INTEGRITY = "data_integrity"
    STYLE_ENFORCEMENT = "style_enforcement"
    COMPLETENESS_CHECK = "completeness_check"


class QualityDimension(str, Enum):
    """Dimensions of quality assessment."""
    READABILITY = "readability"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    SECURITY = "security"
    RELIABILITY = "reliability"
    TESTABILITY = "testability"
    SCALABILITY = "scalability"
    PORTABILITY = "portability"
    ACCESSIBILITY = "accessibility"
    USABILITY = "usability"


class StructuralScope(str, Enum):
    """Scopes for structural validation rules."""
    SCHEMA = "schema"
    INTERFACE = "interface"
    ARCHITECTURE = "architecture"
    NAMING = "naming"
    FORMAT = "format"
    COMPOSITION = "composition"
    HIERARCHY = "hierarchy"
    PROTOCOL = "protocol"


@dataclass
class OperationalRuleDefinition:
    """Definition of a predefined operational rule."""

    rule_id: str
    name: str
    description: str
    category: OperationalCategory
    severity: RuleSeverity
    enforcement: EnforcementLevel
    patterns: List[RulePattern]
    version: str = "1.0.0"
    auto_block: bool = False
    user_override: bool = True
    override_justification_required: bool = False
    tags: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    priority: int = 100
    conditions: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    enabled_by_default: bool = True

    def to_rule(self) -> Rule:
        """Convert definition to a Rule model instance."""
        rule_type = self._determine_rule_type()
        return Rule(
            id=self.rule_id,
            name=self.name,
            description=self.description,
            tier=RuleTier.OPERATIONAL,
            rule_type=rule_type,
            severity=self.severity,
            status=RuleStatus.ACTIVE if self.enabled_by_default else RuleStatus.INACTIVE,
            patterns=self.patterns,
            conditions={**self.conditions, **self.parameters},
            exceptions=self.exceptions,
            enforcement_level=self.enforcement,
            auto_block=self.auto_block,
            user_override=self.user_override,
            override_justification_required=self.override_justification_required,
            version=self.version,
            tags=self.tags,
            priority=self.priority,
        )

    def _determine_rule_type(self) -> RuleType:
        """Determine the RuleType based on category."""
        type_map = {
            OperationalCategory.WORKFLOW_VALIDATION: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.QUALITY_ASSESSMENT: RuleType.QUALITY_ASSESSMENT,
            OperationalCategory.STRUCTURAL_VALIDATION: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.PERFORMANCE_MONITORING: RuleType.QUALITY_ASSESSMENT,
            OperationalCategory.CONSISTENCY_CHECK: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.CONFIGURATION_VALIDATION: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.DEPENDENCY_CHECK: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.DATA_INTEGRITY: RuleType.STRUCTURAL_VALIDATION,
            OperationalCategory.STYLE_ENFORCEMENT: RuleType.QUALITY_ASSESSMENT,
            OperationalCategory.COMPLETENESS_CHECK: RuleType.QUALITY_ASSESSMENT,
        }
        return type_map.get(self.category, RuleType.CUSTOM)


@dataclass
class OperationalParameter:
    """Configurable parameter for an operational rule."""

    name: str
    display_name: str
    description: str
    parameter_type: str
    default_value: Any
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    allowed_values: Optional[List[Any]] = None
    required: bool = False

    def validate(self, value: Any) -> Optional[str]:
        """Validate a parameter value, returning error message if invalid."""
        if self.parameter_type == "int":
            if not isinstance(value, int):
                return f"Parameter '{self.name}' must be an integer"
            if self.min_value is not None and value < self.min_value:
                return f"Parameter '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return f"Parameter '{self.name}' must be <= {self.max_value}"
        elif self.parameter_type == "float":
            if not isinstance(value, (int, float)):
                return f"Parameter '{self.name}' must be a number"
            if self.min_value is not None and value < self.min_value:
                return f"Parameter '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return f"Parameter '{self.name}' must be <= {self.max_value}"
        elif self.parameter_type == "string":
            if not isinstance(value, str):
                return f"Parameter '{self.name}' must be a string"
        elif self.parameter_type == "bool":
            if not isinstance(value, bool):
                return f"Parameter '{self.name}' must be a boolean"
        elif self.parameter_type == "list":
            if not isinstance(value, list):
                return f"Parameter '{self.name}' must be a list"
        elif self.parameter_type == "enum":
            if self.allowed_values and value not in self.allowed_values:
                return f"Parameter '{self.name}' must be one of {self.allowed_values}"
        return None


class OperationalRuleCatalog:
    """Catalog of high-priority operational rules.

    Provides predefined operational rule definitions for workflow validation,
    quality assessment, and structural validation with config-driven parameters.
    """

    DEFAULT_PARAMETERS: Dict[str, OperationalParameter] = {
        "min_quality_score": OperationalParameter(
            name="min_quality_score",
            display_name="Minimum Quality Score",
            description="Minimum acceptable quality score (0.0-1.0)",
            parameter_type="float",
            default_value=0.6,
            min_value=0.0,
            max_value=1.0,
        ),
        "max_line_length": OperationalParameter(
            name="max_line_length",
            display_name="Maximum Line Length",
            description="Maximum allowed line length in characters",
            parameter_type="int",
            default_value=100,
            min_value=40,
            max_value=200,
        ),
        "min_coverage_pct": OperationalParameter(
            name="min_coverage_pct",
            display_name="Minimum Coverage Percentage",
            description="Minimum required test coverage percentage",
            parameter_type="int",
            default_value=80,
            min_value=0,
            max_value=100,
        ),
        "max_complexity": OperationalParameter(
            name="max_complexity",
            display_name="Maximum Cyclomatic Complexity",
            description="Maximum allowed cyclomatic complexity score",
            parameter_type="int",
            default_value=15,
            min_value=1,
            max_value=50,
        ),
        "max_nesting_depth": OperationalParameter(
            name="max_nesting_depth",
            display_name="Maximum Nesting Depth",
            description="Maximum allowed level of nesting",
            parameter_type="int",
            default_value=4,
            min_value=1,
            max_value=10,
        ),
        "min_docstring_ratio": OperationalParameter(
            name="min_docstring_ratio",
            display_name="Minimum Docstring Ratio",
            description="Minimum ratio of documented functions (0.0-1.0)",
            parameter_type="float",
            default_value=0.7,
            min_value=0.0,
            max_value=1.0,
        ),
        "max_function_length": OperationalParameter(
            name="max_function_length",
            display_name="Maximum Function Length",
            description="Maximum number of lines per function",
            parameter_type="int",
            default_value=50,
            min_value=5,
            max_value=200,
        ),
        "max_file_length": OperationalParameter(
            name="max_file_length",
            display_name="Maximum File Length",
            description="Maximum number of lines per file",
            parameter_type="int",
            default_value=500,
            min_value=10,
            max_value=5000,
        ),
        "max_parameters": OperationalParameter(
            name="max_parameters",
            display_name="Maximum Parameters",
            description="Maximum number of function parameters",
            parameter_type="int",
            default_value=5,
            min_value=1,
            max_value=20,
        ),
        "min_comment_ratio": OperationalParameter(
            name="min_comment_ratio",
            display_name="Minimum Comment Ratio",
            description="Minimum ratio of comments to code (0.0-1.0)",
            parameter_type="float",
            default_value=0.1,
            min_value=0.0,
            max_value=1.0,
        ),
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._rules: Dict[str, Rule] = {}
        self._definitions: Dict[str, OperationalRuleDefinition] = {}
        self._parameters: Dict[str, OperationalParameter] = dict(self.DEFAULT_PARAMETERS)
        self._category_enabled: Dict[OperationalCategory, bool] = {
            cat: True for cat in OperationalCategory
        }
        self._parameter_values: Dict[str, Any] = {
            name: param.default_value
            for name, param in self._parameters.items()
        }
        self._version: str = "1.0.0"
        self._changelog: List[Dict[str, Any]] = []
        self._lock = RLock()

        self._initialize_catalog()
        logger.info(
            "OperationalRuleCatalog initialized (version=%s, %d rules)",
            self._version,
            len(self._definitions),
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the operational catalog."""
        return {
            "enable_workflow_validation": True,
            "enable_quality_assessment": True,
            "enable_structural_validation": True,
            "enable_performance_monitoring": True,
            "enable_consistency_check": True,
            "enable_configuration_validation": True,
            "enable_dependency_check": True,
            "enable_data_integrity": True,
            "enable_style_enforcement": True,
            "enable_completeness_check": True,
            "strict_mode": False,
            "auto_register_rules": True,
            "parameter_overrides": {},
            "version_check_enabled": True,
            "rule_tags_prefix": "operational",
        }

    def _initialize_catalog(self) -> None:
        """Initialize the catalog with predefined operational rule definitions."""
        self._add_workflow_validation_rules()
        self._add_quality_assessment_rules()
        self._add_structural_validation_rules()
        self._add_consistency_check_rules()
        self._add_configuration_validation_rules()
        self._add_dependency_check_rules()
        self._add_data_integrity_rules()
        self._add_style_enforcement_rules()
        self._add_completeness_check_rules()

    def _add_workflow_validation_rules(self) -> None:
        """Add workflow validation rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_workflow_001",
                name="Required Step Validation",
                description="Validates that all required workflow steps are present",
                category=OperationalCategory.WORKFLOW_VALIDATION,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "validation", "processing", "output",
                        ],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={"min_steps": 3, "max_steps": 20},
                auto_block=True,
                user_override=False,
                priority=30,
                tags=["workflow", "validation", "steps", "high"],
            ),
            OperationalRuleDefinition(
                rule_id="op_workflow_002",
                name="Workflow Completion Validation",
                description="Verifies workflow has proper completion and error handling",
                category=OperationalCategory.WORKFLOW_VALIDATION,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "complete", "error", "exception", "rollback",
                            "finally", "cleanup", "timeout",
                        ],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={"require_error_handling": True, "require_cleanup": True},
                priority=35,
                tags=["workflow", "completion", "error_handling"],
            ),
            OperationalRuleDefinition(
                rule_id="op_workflow_003",
                name="Workflow Dependency Ordering",
                description="Ensures workflow dependencies are ordered correctly",
                category=OperationalCategory.WORKFLOW_VALIDATION,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "depends_on", "requires", "after", "before",
                        ],
                        confidence_threshold=0.65,
                        action="warn",
                    ),
                ],
                parameters={"check_cycles": True},
                priority=80,
                tags=["workflow", "dependencies", "ordering"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_quality_assessment_rules(self) -> None:
        """Add quality assessment rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_quality_001",
                name="Code Readability Check",
                description="Assesses code readability based on naming and structure",
                category=OperationalCategory.QUALITY_ASSESSMENT,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=[
                            "readability", "naming", "convention",
                            "consistent", "clear", "understandable",
                        ],
                        confidence_threshold=0.6,
                        action="suggest",
                    ),
                ],
                parameters={
                    "min_score": self._parameter_values["min_quality_score"],
                    "check_naming": True,
                    "check_structure": True,
                },
                priority=100,
                tags=["quality", "readability", "medium"],
            ),
            OperationalRuleDefinition(
                rule_id="op_quality_002",
                name="Complexity Threshold Check",
                description="Validates code complexity stays within acceptable limits",
                category=OperationalCategory.QUALITY_ASSESSMENT,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=[
                            "complexity", "cyclomatic", "nesting",
                            "branch", "conditional",
                        ],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={
                    "max_complexity": self._parameter_values["max_complexity"],
                    "max_nesting": self._parameter_values["max_nesting_depth"],
                },
                priority=90,
                tags=["quality", "complexity", "maintainability"],
            ),
            OperationalRuleDefinition(
                rule_id="op_quality_003",
                name="Documentation Completeness Check",
                description="Checks that code is adequately documented",
                category=OperationalCategory.QUALITY_ASSESSMENT,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=[
                            "documentation", "docstring", "comment",
                            "description", "explain",
                        ],
                        confidence_threshold=0.6,
                        action="suggest",
                    ),
                ],
                parameters={
                    "min_docstring_ratio": self._parameter_values["min_docstring_ratio"],
                    "min_comment_ratio": self._parameter_values["min_comment_ratio"],
                },
                priority=150,
                tags=["quality", "documentation", "low"],
            ),
            OperationalRuleDefinition(
                rule_id="op_quality_004",
                name="Performance Pattern Check",
                description="Detects common performance anti-patterns",
                category=OperationalCategory.QUALITY_ASSESSMENT,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=[
                            "n+1", "inefficient", "slow", "bottleneck",
                            "unbounded", "memory leak", "cpu intensive",
                        ],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={"detect_n_plus_one": True, "detect_leaks": True},
                priority=85,
                tags=["quality", "performance", "optimization"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_structural_validation_rules(self) -> None:
        """Add structural validation rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_structure_001",
                name="Schema Conformance Check",
                description="Validates content conforms to expected schema",
                category=OperationalCategory.STRUCTURAL_VALIDATION,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "schema", "validate", "conform", "required field",
                            "type check", "format",
                        ],
                        confidence_threshold=0.8,
                        action="warn",
                    ),
                ],
                parameters={
                    "strict_type_checking": True,
                    "allow_extra_fields": True,
                },
                auto_block=True,
                user_override=False,
                priority=40,
                tags=["structural", "schema", "validation", "high"],
            ),
            OperationalRuleDefinition(
                rule_id="op_structure_002",
                name="Interface Contract Validation",
                description="Validates that interfaces follow defined contracts",
                category=OperationalCategory.STRUCTURAL_VALIDATION,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "interface", "contract", "signature", "method",
                            "parameter", "return type",
                        ],
                        confidence_threshold=0.75,
                        action="warn",
                    ),
                ],
                parameters={
                    "require_type_hints": True,
                    "check_return_types": True,
                },
                priority=45,
                tags=["structural", "interface", "contract", "high"],
            ),
            OperationalRuleDefinition(
                rule_id="op_structure_003",
                name="Architecture Pattern Compliance",
                description="Ensures architecture follows defined patterns",
                category=OperationalCategory.STRUCTURAL_VALIDATION,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "architecture", "pattern", "layered", "modular",
                            "separation", "concern", "dependency direction",
                        ],
                        confidence_threshold=0.65,
                        action="warn",
                    ),
                ],
                parameters={
                    "allowed_patterns": ["layered", "hexagonal", "clean"],
                    "enforce_layer_boundaries": True,
                },
                priority=110,
                tags=["structural", "architecture", "pattern"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_consistency_check_rules(self) -> None:
        """Add consistency check rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_consistency_001",
                name="Naming Convention Consistency",
                description="Ensures consistent naming conventions across codebase",
                category=OperationalCategory.CONSISTENCY_CHECK,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        keywords=[
                            "naming", "convention", "snake_case", "camelCase",
                            "PascalCase", "kebab-case",
                        ],
                        confidence_threshold=0.6,
                        action="suggest",
                    ),
                ],
                parameters={
                    "convention": "snake_case",
                    "check_classes": True,
                    "check_functions": True,
                    "check_variables": True,
                },
                priority=120,
                tags=["consistency", "naming", "convention"],
            ),
            OperationalRuleDefinition(
                rule_id="op_consistency_002",
                name="Format Style Consistency",
                description="Ensures consistent formatting style across files",
                category=OperationalCategory.CONSISTENCY_CHECK,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        keywords=[
                            "formatting", "indentation", "spacing",
                            "line length", "quotes",
                        ],
                        confidence_threshold=0.5,
                        action="suggest",
                    ),
                ],
                parameters={
                    "indent_size": 4,
                    "max_line_length": self._parameter_values["max_line_length"],
                    "quote_style": "double",
                },
                priority=160,
                tags=["consistency", "formatting", "style"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_configuration_validation_rules(self) -> None:
        """Add configuration validation rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_config_001",
                name="Required Configuration Check",
                description="Validates that all required configuration is present",
                category=OperationalCategory.CONFIGURATION_VALIDATION,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "configuration", "settings", "environment",
                            "variable", "required config",
                        ],
                        confidence_threshold=0.8,
                        action="block",
                    ),
                ],
                parameters={
                    "required_fields": ["api_key", "endpoint", "timeout"],
                },
                auto_block=True,
                user_override=False,
                priority=18,
                tags=["config", "validation", "required", "critical"],
            ),
            OperationalRuleDefinition(
                rule_id="op_config_002",
                name="Configuration Value Range Check",
                description="Validates configuration values are within acceptable ranges",
                category=OperationalCategory.CONFIGURATION_VALIDATION,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "range", "limit", "threshold", "maximum",
                            "minimum", "timeout", "retry",
                        ],
                        confidence_threshold=0.75,
                        action="warn",
                    ),
                ],
                parameters={
                    "check_timeout_range": True,
                    "max_timeout_seconds": 300,
                    "min_timeout_seconds": 1,
                },
                priority=50,
                tags=["config", "validation", "ranges", "high"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_dependency_check_rules(self) -> None:
        """Add dependency check rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_dep_001",
                name="Circular Dependency Detection",
                description="Detects circular dependencies between components",
                category=OperationalCategory.DEPENDENCY_CHECK,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "circular", "cyclic", "dependency cycle",
                            "mutual dependency",
                        ],
                        confidence_threshold=0.85,
                        action="block",
                    ),
                ],
                parameters={"max_dependency_depth": 10},
                auto_block=True,
                user_override=False,
                priority=19,
                tags=["dependencies", "circular", "critical"],
            ),
            OperationalRuleDefinition(
                rule_id="op_dep_002",
                name="Missing Dependency Check",
                description="Detects missing or unresolved dependencies",
                category=OperationalCategory.DEPENDENCY_CHECK,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "missing", "unresolved", "not found",
                            "unknown reference", "undefined",
                        ],
                        confidence_threshold=0.8,
                        action="block",
                    ),
                ],
                parameters={"fail_on_missing": True},
                auto_block=True,
                user_override=False,
                priority=25,
                tags=["dependencies", "missing", "high"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_data_integrity_rules(self) -> None:
        """Add data integrity rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_integrity_001",
                name="Data Type Validation",
                description="Validates data types match expected schemas",
                category=OperationalCategory.DATA_INTEGRITY,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "type", "data type", "type mismatch",
                            "expected type", "type error",
                        ],
                        confidence_threshold=0.8,
                        action="warn",
                    ),
                ],
                parameters={"strict_type_checking": True},
                auto_block=True,
                user_override=False,
                priority=55,
                tags=["integrity", "types", "validation"],
            ),
            OperationalRuleDefinition(
                rule_id="op_integrity_002",
                name="Required Field Completeness",
                description="Checks that all required fields have values",
                category=OperationalCategory.DATA_INTEGRITY,
                severity=RuleSeverity.CRITICAL,
                enforcement=EnforcementLevel.STRICT,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "required", "mandatory", "must have",
                            "cannot be empty", "non-null",
                        ],
                        confidence_threshold=0.9,
                        action="block",
                    ),
                ],
                parameters={"check_nulls": True, "check_empty": True},
                auto_block=True,
                user_override=False,
                priority=22,
                tags=["integrity", "required", "completeness", "critical"],
            ),
            OperationalRuleDefinition(
                rule_id="op_integrity_003",
                name="Data Consistency Check",
                description="Ensures data consistency across related fields",
                category=OperationalCategory.DATA_INTEGRITY,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.STRUCTURAL_VALIDATION,
                        keywords=[
                            "consistency", "mismatch", "conflict",
                            "contradict", "inconsistent",
                        ],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={"cross_validate": True},
                priority=60,
                tags=["integrity", "consistency", "correlation"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_style_enforcement_rules(self) -> None:
        """Add style enforcement rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_style_001",
                name="Line Length Enforcement",
                description="Ensures lines do not exceed maximum length",
                category=OperationalCategory.STYLE_ENFORCEMENT,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        keywords=["line length", "wrap", "overflow"],
                        confidence_threshold=0.5,
                        action="suggest",
                    ),
                ],
                parameters={
                    "max_length": self._parameter_values["max_line_length"],
                    "hard_limit": 120,
                },
                priority=170,
                tags=["style", "formatting", "line_length"],
            ),
            OperationalRuleDefinition(
                rule_id="op_style_002",
                name="Import Organization Check",
                description="Validates imports follow standard organization",
                category=OperationalCategory.STYLE_ENFORCEMENT,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.PATTERN_MATCHING,
                        keywords=["import", "ordering", "group", "section"],
                        confidence_threshold=0.5,
                        action="suggest",
                    ),
                ],
                parameters={
                    "groups": ["stdlib", "third_party", "local"],
                    "alphabetical": True,
                },
                priority=180,
                tags=["style", "imports", "organization"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_completeness_check_rules(self) -> None:
        """Add completeness check rules to the catalog."""
        definitions = [
            OperationalRuleDefinition(
                rule_id="op_complete_001",
                name="Implementation Completeness",
                description="Checks that all required implementations exist",
                category=OperationalCategory.COMPLETENESS_CHECK,
                severity=RuleSeverity.HIGH,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=[
                            "todo", "implement", "stub", "placeholder",
                            "not implemented", "pass",
                        ],
                        confidence_threshold=0.8,
                        action="warn",
                    ),
                ],
                parameters={"detect_stubs": True, "detect_todos": True},
                priority=65,
                tags=["completeness", "implementation", "todo"],
            ),
            OperationalRuleDefinition(
                rule_id="op_complete_002",
                name="Test Coverage Check",
                description="Validates that code has sufficient test coverage",
                category=OperationalCategory.COMPLETENESS_CHECK,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADVISORY,
                patterns=[
                    RulePattern(
                        type=RuleType.QUALITY_ASSESSMENT,
                        keywords=["test", "coverage", "unittest", "spec"],
                        confidence_threshold=0.7,
                        action="warn",
                    ),
                ],
                parameters={
                    "min_coverage": self._parameter_values["min_coverage_pct"],
                    "check_unit_tests": True,
                },
                priority=95,
                tags=["completeness", "testing", "coverage"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _register_definition(self, definition: OperationalRuleDefinition) -> None:
        """Register an operational rule definition in the catalog."""
        if definition.rule_id in self._definitions:
            logger.warning("Overwriting existing rule definition: %s", definition.rule_id)
        self._definitions[definition.rule_id] = definition
        if self._config.get("auto_register_rules", True):
            rule = definition.to_rule()
            self._rules[definition.rule_id] = rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get an operational rule by ID."""
        return self._rules.get(rule_id)

    def get_definition(self, rule_id: str) -> Optional[OperationalRuleDefinition]:
        """Get an operational rule definition by ID."""
        return self._definitions.get(rule_id)

    def get_rules(
        self,
        category: Optional[OperationalCategory] = None,
        severity: Optional[RuleSeverity] = None,
        enabled_only: bool = False,
    ) -> List[Rule]:
        """Get operational rules with optional filtering."""
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if self._rule_matches_category(r, category)]
        if severity:
            rules = [r for r in rules if r.severity == severity]
        if enabled_only:
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
        return rules

    def _rule_matches_category(self, rule: Rule, category: OperationalCategory) -> bool:
        """Check if a rule matches an operational category."""
        for definition in self._definitions.values():
            if definition.rule_id == rule.id and definition.category == category:
                return True
        return False

    def get_definitions(
        self,
        category: Optional[OperationalCategory] = None,
    ) -> List[OperationalRuleDefinition]:
        """Get rule definitions with optional filtering."""
        definitions = list(self._definitions.values())
        if category:
            definitions = [d for d in definitions if d.category == category]
        return definitions

    def get_parameter(self, name: str) -> Optional[Any]:
        """Get the current value of a named parameter."""
        return self._parameter_values.get(name)

    def get_parameter_definition(self, name: str) -> Optional[OperationalParameter]:
        """Get the definition of a named parameter."""
        return self._parameters.get(name)

    def set_parameter(self, name: str, value: Any) -> List[str]:
        """Set a parameter value, returning validation errors if any."""
        errors: List[str] = []
        param = self._parameters.get(name)
        if not param:
            errors.append(f"Unknown parameter: {name}")
            return errors
        error = param.validate(value)
        if error:
            errors.append(error)
            return errors
        self._parameter_values[name] = value
        self._update_affected_rules(name, value)
        logger.debug("Parameter '%s' set to %s", name, value)
        return errors

    def set_parameters(self, values: Dict[str, Any]) -> Dict[str, List[str]]:
        """Set multiple parameter values, returning per-parameter errors."""
        all_errors: Dict[str, List[str]] = {}
        for name, value in values.items():
            errors = self.set_parameter(name, value)
            if errors:
                all_errors[name] = errors
        return all_errors

    def get_all_parameters(self) -> Dict[str, Any]:
        """Get all current parameter values."""
        return dict(self._parameter_values)

    def _update_affected_rules(self, param_name: str, value: Any) -> None:
        """Update rules that reference a changed parameter."""
        for definition in self._definitions.values():
            if param_name in definition.parameters:
                definition.parameters[param_name] = value
                if definition.rule_id in self._rules:
                    rule = self._rules[definition.rule_id]
                    rule.conditions[param_name] = value

    def enable_category(self, category: OperationalCategory) -> None:
        """Enable all rules in an operational category."""
        self._category_enabled[category] = True
        for definition in self._definitions.values():
            if definition.category == category and definition.rule_id in self._rules:
                self._rules[definition.rule_id].status = RuleStatus.ACTIVE
        logger.info("Enabled operational category: %s", category.value)

    def disable_category(self, category: OperationalCategory) -> None:
        """Disable all rules in an operational category."""
        self._category_enabled[category] = False
        for definition in self._definitions.values():
            if definition.category == category and definition.rule_id in self._rules:
                self._rules[definition.rule_id].status = RuleStatus.INACTIVE
        logger.info("Disabled operational category: %s", category.value)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the operational catalog."""
        total = len(self._rules)
        active = sum(1 for r in self._rules.values() if r.status == RuleStatus.ACTIVE)
        by_severity: Dict[str, int] = defaultdict(int)
        by_category: Dict[str, int] = defaultdict(int)
        for definition in self._definitions.values():
            by_category[definition.category.value] += 1
        for rule in self._rules.values():
            by_severity[rule.severity.value] += 1
        return {
            "total_rules": total,
            "active_rules": active,
            "inactive_rules": total - active,
            "version": self._version,
            "rules_by_severity": dict(by_severity),
            "rules_by_category": dict(by_category),
            "enabled_categories": {k.value: v for k, v in self._category_enabled.items()},
            "parameters": dict(self._parameter_values),
        }

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a specific operational rule."""
        if rule_id in self._rules:
            self._rules[rule_id].status = RuleStatus.ACTIVE
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a specific operational rule."""
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
        logger.info("Operational catalog updated to version %s (%d changes)", version, len(changes))

    def get_version(self) -> str:
        """Get the current catalog version."""
        return self._version

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the catalog to a dictionary."""
        return {
            "version": self._version,
            "rules": [d.to_rule().dict() for d in self._definitions.values()],
            "category_enabled": {k.value: v for k, v in self._category_enabled.items()},
            "parameters": dict(self._parameter_values),
            "changelog": self._changelog,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperationalRuleCatalog":
        """Create a catalog from a dictionary."""
        catalog = cls()
        catalog._version = data.get("version", "1.0.0")
        category_enabled = data.get("category_enabled", {})
        for cat_value, enabled in category_enabled.items():
            try:
                cat = OperationalCategory(cat_value)
                catalog._category_enabled[cat] = enabled
            except ValueError:
                pass
        parameters = data.get("parameters", {})
        for name, value in parameters.items():
            if name in catalog._parameter_values:
                catalog._parameter_values[name] = value
        catalog._changelog = data.get("changelog", [])
        return catalog

    def to_json(self) -> str:
        """Serialize the catalog to JSON."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "OperationalRuleCatalog":
        """Create a catalog from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_yaml(self) -> str:
        """Serialize the catalog to YAML."""
        return yaml.dump(self.to_dict(), default_flow_style=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "OperationalRuleCatalog":
        """Create a catalog from a YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)
