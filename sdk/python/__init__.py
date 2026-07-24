"""Rules-Emerging-Pattern Python SDK.

A production-grade SDK for interacting with the Rules-Emerging-Pattern
rule validation, evaluation, and monitoring system.

This SDK provides:
- Client: Main API client with sync/async methods for all operations
- RuleEngineClient: Specialized rule evaluation with caching and batching
- ValidationClient: Content validation with compliance, safety, quality checks
- MonitoringClient: Metrics, alerts, dashboards, and health monitoring
- models: Data models mirroring the project's internal models
- exceptions: Comprehensive error hierarchy

Usage:
    from rules_emerging_pattern import Client
    client = Client(api_key="your-api-key")
    result = client.validate("Some content to validate")
    print(f"Passed: {result.passed}, Score: {result.score}")

    # Advanced usage with specialized clients
    from rules_emerging_pattern import (
        RuleEngineClient, ValidationClient, MonitoringClient
    )
    engine = RuleEngineClient(client)
    validator = ValidationClient(client)
    monitor = MonitoringClient(client)

    # Batch validation
    results = validator.validate_batch(["content1", "content2"])

    # Rule evaluation with caching
    result = engine.evaluate("content", tier=RuleTier.SAFETY)

    # Monitoring
    metrics = monitor.get_metrics()
    alerts = monitor.get_alerts(severity=RuleSeverity.CRITICAL)
"""

import logging
from typing import Any, Dict, List, Optional, Union

from .client import Client
from .exceptions import (
    APIError,
    AuthenticationError,
    BatchOperationError,
    ConfigurationError,
    ConflictError,
    ConnectionError,
    RateLimitError,
    RuleNotFoundError,
    SDKError,
    SerializationError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from .models import (
    ActionTaken,
    AlertDefinition,
    AlertEvent,
    AuditEvent,
    AuditTrail,
    BatchValidationRequest,
    BatchValidationResult,
    ConflictResolution,
    ConflictType,
    EnforcementLevel,
    MetricsSnapshot,
    ResolutionStrategy,
    Rule,
    RuleConflict,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSet,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
    Suggestion,
    Violation,
    ViolationType,
    ValidationResult,
    json_deserialize,
    json_serialize,
)
from .monitoring_client import MonitoringClient
from .rule_client import RuleEngineClient
from .validation_client import ValidationClient

logger = logging.getLogger(__name__)

__version__ = "1.0.0"
__author__ = "Rules-Emerging-Pattern Team"
__all__: List[str] = [
    "Client",
    "RuleEngineClient",
    "ValidationClient",
    "MonitoringClient",
    "RuleTier",
    "RuleType",
    "RuleSeverity",
    "RuleStatus",
    "EnforcementLevel",
    "RulePattern",
    "Rule",
    "RuleSet",
    "RuleContext",
    "RuleEvaluationRequest",
    "ViolationType",
    "ActionTaken",
    "Violation",
    "Suggestion",
    "ValidationResult",
    "ConflictType",
    "ResolutionStrategy",
    "RuleConflict",
    "ConflictResolution",
    "BatchValidationRequest",
    "BatchValidationResult",
    "AlertDefinition",
    "AlertEvent",
    "MetricsSnapshot",
    "AuditEvent",
    "AuditTrail",
    "SDKError",
    "ConfigurationError",
    "AuthenticationError",
    "APIError",
    "RateLimitError",
    "TimeoutError",
    "ValidationError",
    "RuleNotFoundError",
    "ConflictError",
    "ServerError",
    "ConnectionError",
    "BatchOperationError",
    "SerializationError",
    "json_serialize",
    "json_deserialize",
    "create_client",
    "health_check",
    "configure_logging",
]


def create_client(
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    timeout: int = 30,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
    enable_logging: bool = True,
    log_level: str = "INFO",
    **kwargs: Any,
) -> Client:
    """Create a fully configured Client instance with sensible defaults.

    This factory function simplifies client creation by combining common
    configuration options into a single call. Additional keyword arguments
    are forwarded to the Client constructor.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_backoff: Base backoff factor in seconds for retry delay.
        enable_logging: Whether to enable SDK logging with basicConfig.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        **kwargs: Additional arguments passed to Client constructor.

    Returns:
        Configured Client instance.

    Example:
        client = create_client(
            api_key="sk-...",
            base_url="https://api.example.com/v1",
            timeout=60,
            max_retries=5,
        )
    """
    if enable_logging:
        configure_logging(level=log_level)

    return Client(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        **kwargs,
    )


def health_check(
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    api_key: str = "",
    timeout: int = 10,
) -> Dict[str, Any]:
    """Perform a quick health check against the API endpoint.

    This is a convenience function that creates a temporary client,
    performs the health check, and closes the client.

    Args:
        base_url: Base URL for the API server.
        api_key: Optional API key for authenticated health checks.
        timeout: Request timeout in seconds.

    Returns:
        Health check response as a dictionary.

    Example:
        status = health_check()
        if status.get("status") == "healthy":
            print("API is healthy")
    """
    client = Client(
        api_key=api_key or "temp_health_check_key",
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )
    try:
        return client.health_check()
    finally:
        client.close()


def configure_logging(
    level: str = "INFO",
    format_string: Optional[str] = None,
    log_file: Optional[str] = None,
) -> None:
    """Configure SDK logging with a standard format.

    Sets up logging with a consistent format that includes timestamps,
    log levels, logger names, and messages. Can optionally write to a file.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        format_string: Custom format string for log messages.
        log_file: Optional file path to write logs to.

    Example:
        configure_logging(level="DEBUG", log_file="sdk.log")
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    fmt = format_string or (
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=numeric_level,
        format=fmt,
        handlers=handlers,
    )
    logger.info("Logging configured: level=%s, file=%s", level, log_file or "stdout")


def validate_content(
    content: str,
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    tier: Optional[RuleTier] = None,
    rule_ids: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> ValidationResult:
    """Quick one-shot content validation.

    Creates a temporary client, validates the content, and returns the result.
    Useful for simple validation tasks without managing a client lifecycle.

    Args:
        content: Content to validate.
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        tier: Rule tier to validate against.
        rule_ids: Specific rule IDs to apply.
        context: Optional context dictionary.
        timeout: Request timeout in seconds.

    Returns:
        Validation result.

    Example:
        result = validate_content("Some user input", api_key="sk-...")
        if not result.passed:
            for v in result.violations:
                print(f"Violation: {v.message}")
    """
    client = create_client(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        return client.validate(content, tier=tier, rule_ids=rule_ids, context=context)
    finally:
        client.close()


def batch_validate(
    contents: List[str],
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    tier: Optional[RuleTier] = None,
    parallel: bool = False,
    timeout: int = 60,
) -> BatchValidationResult:
    """Quick one-shot batch content validation.

    Creates a temporary client, validates multiple contents, and returns
    aggregated results. Useful for batch processing without managing
    a client lifecycle.

    Args:
        contents: List of content strings to validate.
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        tier: Rule tier to validate against.
        parallel: Whether to validate items in parallel.
        timeout: Request timeout in seconds.

    Returns:
        Batch validation result with aggregated statistics.

    Example:
        results = batch_validate(
            ["content1", "content2"],
            api_key="sk-...",
            parallel=True,
        )
        print(f"Pass rate: {results.pass_rate():.1%}")
    """
    client = create_client(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        return client.batch_validate(contents, tier=tier, parallel=parallel)
    finally:
        client.close()


def get_rule(
    rule_id: str,
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
) -> Rule:
    """Quick one-shot rule retrieval.

    Creates a temporary client, fetches a single rule by ID, and returns it.

    Args:
        rule_id: ID of the rule to retrieve.
        api_key: API key for authentication.
        base_url: Base URL for the API server.

    Returns:
        Rule object.

    Raises:
        RuleNotFoundError: If the rule does not exist.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.get_rule(rule_id)
    finally:
        client.close()


def list_rules(
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    tier: Optional[RuleTier] = None,
    rule_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> List[Rule]:
    """Quick one-shot rule listing.

    Creates a temporary client, fetches a list of rules matching the
    specified filters, and returns them.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        tier: Filter by rule tier.
        rule_type: Filter by rule type.
        status: Filter by rule status.
        page: Page number for pagination.
        page_size: Number of rules per page.

    Returns:
        List of Rule objects.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.get_rules(tier=tier, rule_type=rule_type, status=status, page=page, page_size=page_size)
    finally:
        client.close()


def get_metrics(
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
) -> Dict[str, Any]:
    """Quick one-shot metrics retrieval.

    Creates a temporary client, fetches system metrics, and returns them.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.

    Returns:
        Metrics dictionary.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.get_metrics()
    finally:
        client.close()


def check_safety(
    content: str,
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
) -> ValidationResult:
    """Quick one-shot safety check.

    Creates a temporary client, performs a safety check on the content,
    and returns the result.

    Args:
        content: Content to check for safety.
        api_key: API key for authentication.
        base_url: Base URL for the API server.

    Returns:
        Validation result with safety-specific violations.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.check_safety(content)
    finally:
        client.close()


def check_compliance(
    content: str,
    regulations: Optional[List[str]] = None,
    api_key: str = "",
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
) -> ValidationResult:
    """Quick one-shot compliance check.

    Creates a temporary client, performs a compliance check against
    specified regulations, and returns the result.

    Args:
        content: Content to check for compliance.
        regulations: List of regulation identifiers to check.
        api_key: API key for authentication.
        base_url: Base URL for the API server.

    Returns:
        Validation result with compliance-specific violations.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.check_compliance(content, regulations=regulations)
    finally:
        client.close()


def detect_hallucinations(
    content: str,
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
) -> ValidationResult:
    """Quick one-shot hallucination detection.

    Creates a temporary client, performs hallucination detection on the
    content, and returns the result.

    Args:
        content: Content to check for hallucinations.
        api_key: API key for authentication.
        base_url: Base URL for the API server.

    Returns:
        Validation result with hallucination-specific violations.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.detect_hallucinations(content)
    finally:
        client.close()


def get_alerts(
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    severity: Optional[RuleSeverity] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[AlertEvent]:
    """Quick one-shot alert retrieval.

    Creates a temporary client, fetches alerts matching the specified
    filters, and returns them.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        severity: Filter by alert severity.
        status: Filter by alert status.
        limit: Maximum number of alerts to return.

    Returns:
        List of AlertEvent objects.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.get_alerts(severity=severity, status=status, limit=limit)
    finally:
        client.close()


def trigger_alert(
    name: str,
    severity: RuleSeverity,
    message: str,
    api_key: str,
    base_url: str = "https://api.rules-emerging-pattern.io/v1",
    metric_value: float = 0.0,
    threshold: float = 0.0,
    source: str = "sdk",
    metadata: Optional[Dict[str, Any]] = None,
) -> AlertEvent:
    """Quick one-shot alert triggering.

    Creates a temporary client, triggers an alert with the specified
    parameters, and returns the created alert event.

    Args:
        name: Alert name.
        severity: Alert severity level.
        message: Alert message.
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        metric_value: Value that triggered the alert.
        threshold: Threshold that was exceeded.
        source: Source system identifier.
        metadata: Additional metadata.

    Returns:
        Created AlertEvent.
    """
    client = create_client(api_key=api_key, base_url=base_url)
    try:
        return client.trigger_alert(
            name=name,
            severity=severity,
            message=message,
            metric_value=metric_value,
            threshold=threshold,
            source=source,
            metadata=metadata,
        )
    finally:
        client.close()


class SDK:
    """High-level SDK wrapper providing convenient access to all functionality.

    Combines the Client, RuleEngineClient, ValidationClient, and MonitoringClient
    into a single unified interface for simplified usage.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        enable_cache: Whether to enable rule caching.

    Example:
        sdk = SDK(api_key="sk-...")
        result = sdk.validate("Some content")
        metrics = sdk.metrics()
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.rules-emerging-pattern.io/v1",
        timeout: int = 30,
        max_retries: int = 3,
        enable_cache: bool = True,
    ):
        self._client = Client(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._rule_engine = RuleEngineClient(self._client, cache_enabled=enable_cache)
        self._validator = ValidationClient(self._client)
        self._monitor = MonitoringClient(self._client)

    @property
    def client(self) -> Client:
        return self._client

    @property
    def rules(self) -> RuleEngineClient:
        return self._rule_engine

    @property
    def validate(self) -> ValidationClient:
        return self._validator

    @property
    def monitor(self) -> MonitoringClient:
        return self._monitor

    def metrics(self) -> Dict[str, Any]:
        return self._monitor.get_metrics()

    def health(self) -> Dict[str, Any]:
        return self._client.health_check()

    def close(self) -> None:
        self._rule_engine.close()
        self._validator.close()
        self._monitor.close()
        self._client.close()

    def evaluate(self, content: str, tier: Optional[RuleTier] = None,
                 context: Optional[Dict[str, Any]] = None) -> ValidationResult:
        return self._rule_engine.evaluate(content, context=context, tier=tier)

    def validate_content(self, content: str, rules: Optional[List[str]] = None,
                         context: Optional[Dict[str, Any]] = None) -> ValidationResult:
        return self._validator.validate_content(content, rules=rules, context=context)

    def validate_batch(self, contents: List[str], parallel: bool = False) -> BatchValidationResult:
        return self._validator.validate_batch(contents, parallel=parallel)

    def check_safety(self, content: str) -> ValidationResult:
        return self._validator.check_safety(content)

    def check_compliance(self, content: str, regulations: Optional[List[str]] = None) -> ValidationResult:
        return self._validator.check_compliance(content, regulations=regulations)

    def check_quality(self, content: str) -> ValidationResult:
        return self._validator.check_quality(content)

    def detect_hallucinations(self, content: str) -> ValidationResult:
        return self._validator.detect_hallucinations(content)

    def validate_citations(self, content: str) -> ValidationResult:
        return self._validator.validate_citations(content)

    def get_rules(self, tier: Optional[RuleTier] = None, rule_type: Optional[str] = None,
                  status: Optional[str] = None) -> List[Rule]:
        return self._client.get_rules(tier=tier, rule_type=rule_type, status=status)

    def get_rule(self, rule_id: str) -> Rule:
        return self._client.get_rule(rule_id)

    def create_rule(self, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        return self._client.create_rule(rule_data)

    def update_rule(self, rule_id: str, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        return self._client.update_rule(rule_id, rule_data)

    def delete_rule(self, rule_id: str) -> bool:
        return self._client.delete_rule(rule_id)

    def get_alerts(self, severity: Optional[RuleSeverity] = None,
                   status: Optional[str] = None, limit: int = 50) -> List[AlertEvent]:
        return self._monitor.get_alerts(severity=severity, status=status, limit=limit)

    def trigger_alert(self, name: str, severity: RuleSeverity, message: str,
                      metric_value: float = 0.0, threshold: float = 0.0,
                      source: str = "sdk") -> AlertEvent:
        return self._monitor.trigger_alert(
            name=name, severity=severity, message=message,
            metric_value=metric_value, threshold=threshold, source=source,
        )

    def resolve_alert(self, alert_id: str) -> bool:
        return self._monitor.resolve_alert(alert_id)

    def export_prometheus(self) -> str:
        return self._monitor.export_prometheus()

    def get_dashboard(self) -> Dict[str, Any]:
        return self._monitor.get_dashboard()

    def get_metrics_history(self, metric_name: Optional[str] = None, limit: int = 100) -> List[MetricsSnapshot]:
        return self._monitor.get_metrics_history(metric_name=metric_name, limit=limit)

    def clear_metrics_history(self) -> None:
        self._monitor.clear_metrics_history()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "client": self._client.get_statistics(),
            "rules": self._rule_engine.get_statistics(),
            "validation": self._validator.get_statistics(),
            "monitoring": self._monitor.get_statistics(),
        }

    def __enter__(self) -> "SDK":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
