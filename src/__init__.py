"""
Rules-Emerging-Pattern: AI Guardrails and Consistency Framework

A comprehensive rules engine providing strict guardrails, consistency enforcement,
and safety boundaries for AI systems through a sophisticated tiered architecture.

The framework is organized into 15 submodules covering:
  - Core: Rule engine, tiered evaluation, orchestration, metrics
  - Models: Rule definitions, validation, conflicts, monitoring, audit
  - Monitoring: Alerting, dashboards, health checks, metrics collection
  - Learning: Pattern recognition, trend analysis, ML model training
  - Memory: Caching, context storage, session management
  - Utils: Validation, serialization, configuration, rate limiting
  - API: REST, WebSocket, GraphQL handlers with auth and middleware
  - CLI: Command-line interface, batch processing, output formatting
  - Compliance: GDPR, HIPAA, PCI, SOX compliance checking
  - Advanced: Age verification, emergency response, intent analysis
  - Privacy: Data redaction, anonymization, consent management
  - Middleware: Validation, logging, auth, rate-limit, audit pipelines
  - Skills: Rule skill definitions, registry, executor, loader
  - Storage: Rule persistence, caching, backup, migration
  - Tools: Analysis, debugging, profiling, visualization, testing
"""

import logging

logger = logging.getLogger(__name__)

__version__ = "1.0.0"
__author__ = "Rules Engine Team"
__email__ = "team@rules-emerging-pattern.com"

# ---------------------------------------------------------------------------
# Core imports
# ---------------------------------------------------------------------------
from .core.rule_engine import RuleEngine
from .core.engine_config import EngineConfig

# Tiered rules
from .core.tiered_rules.safety_engine import SafetyEngine
from .core.tiered_rules.operational_engine import OperationalEngine
from .core.tiered_rules.preference_engine import PreferenceEngine
from .core.tiered_rules.tier_orchestrator import TierOrchestrator
from .core.tiered_rules.tier_metrics_collector import TierMetricsCollector

# ---------------------------------------------------------------------------
# Model imports
# ---------------------------------------------------------------------------
from .models.rule import (
    Rule, RuleSet, RuleTier, RuleType, RuleSeverity, RuleStatus,
    RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
)
from .models.validation import (
    ValidationResult, Violation, ViolationType, ActionTaken, Suggestion,
    BatchValidationRequest, BatchValidationResult
)
from .models.conflict import (
    RuleConflict, ConflictType, ConflictSeverity, ConflictResolution,
    ResolutionStrategy
)
from .models.monitoring import (
    AlertDefinition, AlertEvent, MonitorConfig, MetricsSnapshot,
    DashboardConfig, AlertSeverity, AlertStatus
)
from .models.audit import AuditEvent, AuditTrail, AuditQuery

# ---------------------------------------------------------------------------
# Monitoring imports
# ---------------------------------------------------------------------------
from .monitoring.alerting import AlertManager
from .monitoring.dashboard import MonitoringDashboard
from .monitoring.health_checker import HealthChecker
from .monitoring.metrics_collector import MetricsCollector
from .monitoring.event_bus import EventBus

# ---------------------------------------------------------------------------
# Learning imports
# ---------------------------------------------------------------------------
from .learning.pattern_engine import PatternRecognitionEngine
from .learning.trend_analyzer import TrendAnalyzer
from .learning.feature_extractor import FeatureExtractor
from .learning.model_trainer import ModelTrainer
from .learning.feedback_learner import FeedbackLearner

# ---------------------------------------------------------------------------
# Memory imports
# ---------------------------------------------------------------------------
from .memory.rule_cache import RuleCache
from .memory.context_memory import ContextMemory
from .memory.pattern_cache import PatternCache
from .memory.result_store import ResultStore
from .memory.session_state import SessionState

# ---------------------------------------------------------------------------
# Utils imports
# ---------------------------------------------------------------------------
from .utils.validators import UtilityValidators
from .utils.serializers import Serializers
from .utils.cache_manager import CacheManager
from .utils.config_loader import ConfigLoader
from .utils.rate_limiter import RateLimiter

# ---------------------------------------------------------------------------
# API imports
# ---------------------------------------------------------------------------
from .api.rest_api import RestAPI
from .api.websocket_handler import WebSocketHandler
from .api.graphql_handler import GraphQLHandler
from .api.api_auth import APIAuth
from .api.api_middleware import APIMiddleware

# ---------------------------------------------------------------------------
# CLI imports
# ---------------------------------------------------------------------------
from .cli.cli import app as cli_app, main as cli_main
from .cli.output_formatter import OutputFormatter
from .cli.interactive_shell import InteractiveShell
from .cli.config_commands import ConfigCommands
from .cli.batch_processor import BatchProcessor

# ---------------------------------------------------------------------------
# Compliance imports
# ---------------------------------------------------------------------------
from .compliance.gdpr_compliance import GDPRComplianceChecker
from .compliance.hipaa_compliance import HIPAAComplianceChecker
from .compliance.pci_compliance import PCIComplianceChecker
from .compliance.sox_compliance import SOXComplianceChecker
from .compliance.compliance_orchestrator import ComplianceOrchestrator

# ---------------------------------------------------------------------------
# Advanced imports
# ---------------------------------------------------------------------------
from .advanced.age_verification import AgeVerifier
from .advanced.emergency_response import EmergencyResponse
from .advanced.intent_recognition import IntentAnalyzer
from .advanced.reporting_system import ViolationReporter
from .advanced.sandbox import CodeSandbox

# ---------------------------------------------------------------------------
# Privacy imports
# ---------------------------------------------------------------------------
from .privacy.data_redaction import DataRedactor
from .privacy.consent_manager import ConsentManager
from .privacy.anonymizer import Anonymizer
from .privacy.data_classifier import DataClassifier
from .privacy.privacy_auditor import PrivacyAuditor

# ---------------------------------------------------------------------------
# Middleware imports
# ---------------------------------------------------------------------------
from .middleware.validation_middleware import ValidationMiddleware
from .middleware.logging_middleware import LoggingMiddleware
from .middleware.auth_middleware import AuthMiddleware
from .middleware.rate_limit_middleware import RateLimitMiddleware
from .middleware.audit_middleware import AuditMiddleware

# ---------------------------------------------------------------------------
# Skills imports
# ---------------------------------------------------------------------------
from .skills.rule_skill import RuleSkill
from .skills.skill_registry import SkillRegistry
from .skills.skill_executor import SkillExecutor
from .skills.skill_validator import SkillValidator
from .skills.skill_loader import SkillLoader

# ---------------------------------------------------------------------------
# Storage imports
# ---------------------------------------------------------------------------
from .storage.rule_storage import RuleStorage
from .storage.file_store import FileStore
from .storage.cache_store import CacheStore
from .storage.backup_manager import BackupManager
from .storage.migration_manager import MigrationManager

# ---------------------------------------------------------------------------
# Tools imports
# ---------------------------------------------------------------------------
from .tools.rule_analyzer import RuleAnalyzer
from .tools.debug_tool import DebugTool
from .tools.profiler import Profiler
from .tools.test_runner import TestRunner
from .tools.visualizer import Visualizer

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    # Core
    "RuleEngine", "EngineConfig",
    "SafetyEngine", "OperationalEngine", "PreferenceEngine",
    "TierOrchestrator", "TierMetricsCollector",
    # Models - Rule
    "Rule", "RuleSet", "RuleTier", "RuleType", "RuleSeverity",
    "RuleStatus", "RulePattern", "RuleContext", "RuleEvaluationRequest",
    "EnforcementLevel",
    # Models - Validation
    "ValidationResult", "Violation", "ViolationType", "ActionTaken",
    "Suggestion", "BatchValidationRequest", "BatchValidationResult",
    # Models - Conflict
    "RuleConflict", "ConflictType", "ConflictSeverity",
    "ConflictResolution", "ResolutionStrategy",
    # Models - Monitoring
    "AlertDefinition", "AlertEvent", "MonitorConfig", "MetricsSnapshot",
    "DashboardConfig", "AlertSeverity", "AlertStatus",
    # Models - Audit
    "AuditEvent", "AuditTrail", "AuditQuery",
    # Monitoring
    "AlertManager", "MonitoringDashboard", "HealthChecker",
    "MetricsCollector", "EventBus",
    # Learning
    "PatternRecognitionEngine", "TrendAnalyzer", "FeatureExtractor",
    "ModelTrainer", "FeedbackLearner",
    # Memory
    "RuleCache", "ContextMemory", "PatternCache", "ResultStore", "SessionState",
    # Utils
    "UtilityValidators", "Serializers", "CacheManager",
    "ConfigLoader", "RateLimiter",
    # API
    "RestAPI", "WebSocketHandler", "GraphQLHandler", "APIAuth", "APIMiddleware",
    # CLI
    "cli_app", "cli_main", "OutputFormatter", "InteractiveShell",
    "ConfigCommands", "BatchProcessor",
    # Compliance
    "GDPRComplianceChecker", "HIPAAComplianceChecker", "PCIComplianceChecker",
    "SOXComplianceChecker", "ComplianceOrchestrator",
    # Advanced
    "AgeVerifier", "EmergencyResponse", "IntentAnalyzer",
    "ViolationReporter", "CodeSandbox",
    # Privacy
    "DataRedactor", "ConsentManager", "Anonymizer",
    "DataClassifier", "PrivacyAuditor",
    # Middleware
    "ValidationMiddleware", "LoggingMiddleware", "AuthMiddleware",
    "RateLimitMiddleware", "AuditMiddleware",
    # Skills
    "RuleSkill", "SkillRegistry", "SkillExecutor",
    "SkillValidator", "SkillLoader",
    # Storage
    "RuleStorage", "FileStore", "CacheStore",
    "BackupManager", "MigrationManager",
    # Tools
    "RuleAnalyzer", "DebugTool", "Profiler", "TestRunner", "Visualizer",
]

logger.debug("Rules-Emerging-Pattern package initialized with all 15 submodules")