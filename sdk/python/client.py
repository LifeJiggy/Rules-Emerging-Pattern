"""Main SDK Client class for the Rules-Emerging-Pattern API.

Provides synchronous and asynchronous methods for validation, rule management,
evaluation, monitoring, and health checks with automatic retry logic,
session management, and request/response logging.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from urllib.parse import urljoin

from .exceptions import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    RateLimitError,
    RuleNotFoundError,
    SDKError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from .models import (
    AlertDefinition,
    AlertEvent,
    BatchValidationRequest,
    BatchValidationResult,
    MetricsSnapshot,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSet,
    RuleSeverity,
    RuleTier,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class Client:
    """Main SDK client for interacting with the Rules-Emerging-Pattern API.

    Provides synchronous methods for all API operations, with automatic
    retry, session management, and comprehensive error handling.

    Args:
        api_key: API key for authentication.
        base_url: Base URL for the API server.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_backoff: Base backoff factor in seconds for retry delay.
        max_connections: Maximum connection pool size.
        verify_ssl: Whether to verify SSL certificates.
        user_agent: Custom user agent string.

    Example:
        client = Client(api_key="sk-...")
        result = client.validate("Some content")
        print(result.passed)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.rules-emerging-pattern.io/v1",
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        max_connections: int = 10,
        verify_ssl: bool = True,
        user_agent: Optional[str] = None,
    ):
        if not api_key:
            raise ConfigurationError("api_key is required")
        if timeout < 1:
            raise ConfigurationError("timeout must be >= 1 second")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.max_connections = max_connections
        self.verify_ssl = verify_ssl
        self._user_agent = user_agent or f"RulesEmergingPatternSDK/1.0"

        self._session: Optional[Any] = None
        self._async_session: Optional[Any] = None
        self._request_id: Optional[str] = None
        self._request_count: int = 0
        self._total_latency_ms: float = 0.0
        self._rate_limit_remaining: int = 1000
        self._rate_limit_reset: float = 0.0
        self._retryable_statuses: set = {429, 500, 502, 503, 504}
        self._endpoints: Dict[str, str] = {
            "validate": "/validate",
            "evaluate": "/evaluate",
            "rules": "/rules",
            "rule": "/rules/{rule_id}",
            "metrics": "/metrics",
            "alerts": "/alerts",
            "alert": "/alerts/{alert_id}",
            "health": "/health",
            "batch_validate": "/validate/batch",
            "compliance": "/validate/compliance",
            "safety": "/validate/safety",
            "format": "/validate/format",
            "quality": "/validate/quality",
            "hallucination": "/validate/hallucination",
            "citations": "/validate/citations",
            "dashboard": "/monitoring/dashboard",
            "export": "/metrics/export",
            "rule_sets": "/rule-sets",
            "rule_set": "/rule-sets/{rule_set_id}",
        }
        self._closed = False

        logger.info(
            "Client initialized (base_url=%s, timeout=%d, max_retries=%d)",
            self.base_url,
            self.timeout,
            self.max_retries,
        )

    def _get_session(self) -> Any:
        import requests
        if self._session is None or self._closed:
            session = requests.Session()
            session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": self._user_agent,
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=self.max_connections,
                pool_maxsize=self.max_connections,
                max_retries=0,
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._session = session
        return self._session

    def _get_async_session(self) -> Any:
        if self._async_session is None or self._closed:
            try:
                import aiohttp
            except ImportError:
                raise ImportError(
                    "aiohttp is required for async operations. "
                    "Install it with: pip install aiohttp"
                )
            self._async_session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": self._user_agent,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                connector=aiohttp.TCPConnector(
                    limit=self.max_connections,
                    verify_ssl=self.verify_ssl,
                ),
            )
        return self._async_session

    def _build_url(self, endpoint: str, **path_params: str) -> str:
        path = self._endpoints.get(endpoint, endpoint)
        if path_params:
            for key, value in path_params.items():
                path = path.replace(f"{{{key}}}", str(value))
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _generate_request_id(self) -> str:
        return str(uuid.uuid4())

    def _log_request(self, method: str, url: str, body: Optional[dict] = None) -> str:
        req_id = self._generate_request_id()
        self._request_id = req_id
        truncated_body = None
        if body and isinstance(body, dict) and "content" in body:
            c = body["content"]
            if isinstance(c, str) and len(c) > 200:
                truncated_body = {**body, "content": c[:200] + "..."}
            else:
                truncated_body = body
        logger.debug(
            "Request [%s] %s %s body=%s",
            req_id[:8],
            method,
            url,
            json.dumps(truncated_body) if truncated_body else None,
        )
        return req_id

    def _log_response(
        self, req_id: str, status_code: int, latency_ms: float, body_size: int
    ) -> None:
        logger.debug(
            "Response [%s] status=%d latency=%.1fms size=%d",
            req_id[:8],
            status_code,
            latency_ms,
            body_size,
        )

    def _handle_response(self, response: Any, endpoint: str) -> dict:
        status = response.status_code if hasattr(response, "status_code") else response.status
        latency = response.elapsed.total_seconds() * 1000 if hasattr(response, "elapsed") else 0
        self._request_count += 1
        self._total_latency_ms += latency

        rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
        if rate_limit_remaining is not None:
            self._rate_limit_remaining = int(rate_limit_remaining)
        rate_limit_reset = response.headers.get("X-RateLimit-Reset")
        if rate_limit_reset is not None:
            self._rate_limit_reset = float(rate_limit_reset)

        body = response.text if hasattr(response, "text") else ""
        body_size = len(body)

        if hasattr(self, "_request_id") and self._request_id:
            self._log_response(self._request_id, status, latency, body_size)

        if status == 200:
            try:
                return response.json() if body else {}
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to parse response JSON: %s", e)
                return {"raw": body}

        if status == 401:
            raise AuthenticationError(status_code=401)
        if status == 403:
            raise AuthenticationError(
                "Access denied. Check your API key permissions.", status_code=403
            )
        if status == 404:
            raise RuleNotFoundError(
                rule_id=endpoint,
                message=f"Resource not found at {endpoint}",
            )
        if status == 422:
            try:
                err_data = response.json()
                errors = err_data.get("errors", err_data.get("detail", []))
            except (json.JSONDecodeError, ValueError):
                errors = [body]
            raise ValidationError(
                message="Validation failed",
                errors=errors if isinstance(errors, list) else [errors],
            )
        if status == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            raise RateLimitError(
                retry_after=retry_after,
            )
        if 500 <= status < 600:
            raise ServerError(
                message=f"Server error ({status}) at {endpoint}",
                status_code=status,
                response_body=body[:500] if body else None,
            )

        raise APIError(
            message=f"Unexpected status {status}",
            status_code=status,
            response_body=body[:500] if body else None,
            endpoint=endpoint,
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        path_params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        url = self._build_url(endpoint, **(path_params or {}))
        effective_timeout = timeout or self.timeout
        session = self._get_session()
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            req_id = self._log_request(method, url, json_body)
            self._request_id = req_id
            try:
                response = session.request(
                    method=method,
                    url=url,
                    json=json_body,
                    params=params,
                    timeout=effective_timeout,
                )
                return self._handle_response(response, endpoint)
            except (RateLimitError, ServerError, ConnectionError) as e:
                last_exception = e
                if attempt < self.max_retries and self._should_retry(e):
                    delay = self._compute_retry_delay(attempt, e)
                    logger.warning(
                        "Retry %d/%d for %s after %.1fs: %s",
                        attempt + 1,
                        self.max_retries,
                        endpoint,
                        delay,
                        str(e),
                    )
                    time.sleep(delay)
                    continue
                raise
            except (requests.exceptions.Timeout, asyncio.TimeoutError) as e:
                last_exception = TimeoutError(
                    message=f"Request timed out after {effective_timeout}s",
                    timeout_seconds=float(effective_timeout),
                    operation=endpoint,
                )
                if attempt < self.max_retries:
                    delay = self._compute_retry_delay(attempt, None)
                    logger.warning(
                        "Retry %d/%d for %s after timeout: %.1fs",
                        attempt + 1,
                        self.max_retries,
                        endpoint,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise last_exception
            except requests.exceptions.ConnectionError as e:
                raise ConnectionError(
                    message=f"Failed to connect: {e}",
                    host=self.base_url,
                ) from e
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._compute_retry_delay(attempt, None)
                    logger.warning(
                        "Retry %d/%d for %s after error: %s",
                        attempt + 1,
                        self.max_retries,
                        endpoint,
                        str(e),
                    )
                    time.sleep(delay)
                    continue
                raise SDKError(
                    message=f"Request failed: {e}",
                    original_exception=e if isinstance(e, Exception) else None,
                ) from e

        if last_exception:
            raise last_exception
        return {}

    def _should_retry(self, error: Exception) -> bool:
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, ServerError):
            return error.status_code is not None and error.status_code in self._retryable_statuses
        if isinstance(error, ConnectionError):
            return True
        if isinstance(error, TimeoutError):
            return True
        return False

    def _compute_retry_delay(self, attempt: int, error: Optional[Exception] = None) -> float:
        if isinstance(error, RateLimitError) and error.retry_after:
            return min(float(error.retry_after), 30.0)
        jitter = (hash(f"{attempt}:{time.time()}") % 100) / 1000.0
        delay = self.retry_backoff * (2 ** attempt) + jitter
        return min(delay, 60.0)

    def validate(
        self,
        content: str,
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids
        if context:
            body["context"] = context
        if options:
            body["options"] = options

        response = self._request("POST", "validate", json_body=body)
        return ValidationResult.from_dict(response)

    def evaluate_rules(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids

        response = self._request("POST", "evaluate", json_body=body)
        return ValidationResult.from_dict(response)

    def get_rules(
        self,
        tier: Optional[RuleTier] = None,
        rule_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Rule]:
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if tier:
            params["tier"] = tier.value
        if rule_type:
            params["rule_type"] = rule_type
        if status:
            params["status"] = status

        response = self._request("GET", "rules", params=params)
        rules_data = response.get("rules", response.get("data", []))
        if isinstance(rules_data, list):
            return [Rule.from_dict(r) for r in rules_data]
        return []

    def get_rule(self, rule_id: str) -> Rule:
        response = self._request("GET", "rule", path_params={"rule_id": rule_id})
        return Rule.from_dict(response)

    def create_rule(self, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        if isinstance(rule_data, Rule):
            body = rule_data.to_dict()
        else:
            body = rule_data
        response = self._request("POST", "rules", json_body=body)
        return Rule.from_dict(response)

    def update_rule(self, rule_id: str, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        if isinstance(rule_data, Rule):
            body = rule_data.to_dict()
        else:
            body = rule_data
        response = self._request("PUT", "rule", json_body=body, path_params={"rule_id": rule_id})
        return Rule.from_dict(response)

    def delete_rule(self, rule_id: str) -> bool:
        try:
            self._request("DELETE", "rule", path_params={"rule_id": rule_id})
            return True
        except RuleNotFoundError:
            return False
        except APIError as e:
            logger.error("Failed to delete rule %s: %s", rule_id, e)
            return False

    def get_metrics(self) -> Dict[str, Any]:
        response = self._request("GET", "metrics")
        return response

    def get_alerts(
        self,
        severity: Optional[RuleSeverity] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[AlertEvent]:
        params: Dict[str, Any] = {"limit": limit}
        if severity:
            params["severity"] = severity.value
        if status:
            params["status"] = status
        if source:
            params["source"] = source

        response = self._request("GET", "alerts", params=params)
        alerts_data = response.get("alerts", response.get("data", []))
        if isinstance(alerts_data, list):
            return [AlertEvent.from_dict(a) for a in alerts_data]
        return []

    def health_check(self) -> Dict[str, Any]:
        response = self._request("GET", "health")
        return response

    def batch_validate(
        self,
        contents: List[str],
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
    ) -> BatchValidationResult:
        body: Dict[str, Any] = {"contents": contents, "parallel": parallel}
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids
        if context:
            body["context"] = context

        response = self._request("POST", "batch_validate", json_body=body)
        return BatchValidationResult.from_dict(response)

    def check_compliance(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if regulations:
            body["regulations"] = regulations
        if context:
            body["context"] = context

        response = self._request("POST", "compliance", json_body=body)
        return ValidationResult.from_dict(response)

    def check_safety(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        response = self._request("POST", "safety", json_body=body)
        return ValidationResult.from_dict(response)

    def check_format(
        self,
        content: str,
        format_type: str = "text",
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content, "format_type": format_type}
        if context:
            body["context"] = context

        response = self._request("POST", "format", json_body=body)
        return ValidationResult.from_dict(response)

    def check_quality(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        response = self._request("POST", "quality", json_body=body)
        return ValidationResult.from_dict(response)

    def detect_hallucinations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        response = self._request("POST", "hallucination", json_body=body)
        return ValidationResult.from_dict(response)

    def validate_citations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        response = self._request("POST", "citations", json_body=body)
        return ValidationResult.from_dict(response)

    def get_rule_sets(
        self,
        tier: Optional[RuleTier] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[RuleSet]:
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if tier:
            params["tier"] = tier.value

        response = self._request("GET", "rule_sets", params=params)
        sets_data = response.get("rule_sets", response.get("data", []))
        if isinstance(sets_data, list):
            return [RuleSet.from_dict(s) for s in sets_data]
        return []

    def get_rule_set(self, rule_set_id: str) -> RuleSet:
        response = self._request("GET", "rule_set", path_params={"rule_set_id": rule_set_id})
        return RuleSet.from_dict(response)

    def trigger_alert(
        self,
        name: str,
        severity: RuleSeverity,
        message: str,
        metric_value: float = 0.0,
        threshold: float = 0.0,
        source: str = "sdk",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertEvent:
        body: Dict[str, Any] = {
            "name": name,
            "severity": severity.value,
            "message": message,
            "metric_value": metric_value,
            "threshold": threshold,
            "source": source,
        }
        if metadata:
            body["metadata"] = metadata

        response = self._request("POST", "alerts", json_body=body)
        return AlertEvent.from_dict(response)

    def resolve_alert(self, alert_id: str) -> bool:
        try:
            self._request("POST", "alert", json_body={"status": "resolved"}, path_params={"alert_id": alert_id})
            return True
        except APIError as e:
            logger.error("Failed to resolve alert %s: %s", alert_id, e)
            return False

    def get_dashboard(self) -> Dict[str, Any]:
        response = self._request("GET", "dashboard")
        return response

    def export_metrics(self, format: str = "prometheus") -> str:
        response = self._request("GET", "export", params={"format": format})
        if isinstance(response, dict):
            return response.get("data", response.get("metrics", str(response)))
        return str(response)

    def get_statistics(self) -> Dict[str, Any]:
        avg_latency = self._total_latency_ms / max(self._request_count, 1)
        return {
            "total_requests": self._request_count,
            "avg_latency_ms": round(avg_latency, 2),
            "total_latency_ms": round(self._total_latency_ms, 2),
            "rate_limit_remaining": self._rate_limit_remaining,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "session_active": self._session is not None and not self._closed,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._session:
            try:
                self._session.close()
            except Exception as e:
                logger.warning("Error closing session: %s", e)
            self._session = None
        if self._async_session:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._async_session.close())
                else:
                    loop.run_until_complete(self._async_session.close())
            except Exception as e:
                logger.warning("Error closing async session: %s", e)
            self._async_session = None
        logger.info("Client closed")

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    async def async_validate(
        self,
        content: str,
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids
        if context:
            body["context"] = context
        if options:
            body["options"] = options

        url = self._build_url("validate")
        req_id = self._log_request("POST", url, body)
        self._request_id = req_id

        async with session.post(url, json=body) as response:
            data = await response.json()
            self._handle_response(response, "validate")
            return ValidationResult.from_dict(data)

    async def async_evaluate_rules(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids

        url = self._build_url("evaluate")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_get_rules(
        self,
        tier: Optional[RuleTier] = None,
        rule_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Rule]:
        session = self._get_async_session()
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if tier:
            params["tier"] = tier.value
        if rule_type:
            params["rule_type"] = rule_type
        if status:
            params["status"] = status

        url = self._build_url("rules")
        async with session.get(url, params=params) as response:
            data = await response.json()
            rules_data = data.get("rules", data.get("data", []))
            if isinstance(rules_data, list):
                return [Rule.from_dict(r) for r in rules_data]
            return []

    async def async_get_rule(self, rule_id: str) -> Rule:
        session = self._get_async_session()
        url = self._build_url("rule", rule_id=rule_id)
        async with session.get(url) as response:
            data = await response.json()
            return Rule.from_dict(data)

    async def async_create_rule(self, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        session = self._get_async_session()
        body = rule_data.to_dict() if isinstance(rule_data, Rule) else rule_data
        url = self._build_url("rules")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return Rule.from_dict(data)

    async def async_update_rule(self, rule_id: str, rule_data: Union[Rule, Dict[str, Any]]) -> Rule:
        session = self._get_async_session()
        body = rule_data.to_dict() if isinstance(rule_data, Rule) else rule_data
        url = self._build_url("rule", rule_id=rule_id)
        async with session.put(url, json=body) as response:
            data = await response.json()
            return Rule.from_dict(data)

    async def async_delete_rule(self, rule_id: str) -> bool:
        try:
            session = self._get_async_session()
            url = self._build_url("rule", rule_id=rule_id)
            async with session.delete(url) as response:
                return response.status == 200
        except SDKError:
            return False

    async def async_get_metrics(self) -> Dict[str, Any]:
        session = self._get_async_session()
        url = self._build_url("metrics")
        async with session.get(url) as response:
            return await response.json()

    async def async_get_alerts(
        self,
        severity: Optional[RuleSeverity] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[AlertEvent]:
        session = self._get_async_session()
        params: Dict[str, Any] = {"limit": limit}
        if severity:
            params["severity"] = severity.value
        if status:
            params["status"] = status
        if source:
            params["source"] = source

        url = self._build_url("alerts")
        async with session.get(url, params=params) as response:
            data = await response.json()
            alerts_data = data.get("alerts", data.get("data", []))
            if isinstance(alerts_data, list):
                return [AlertEvent.from_dict(a) for a in alerts_data]
            return []

    async def async_health_check(self) -> Dict[str, Any]:
        session = self._get_async_session()
        url = self._build_url("health")
        async with session.get(url) as response:
            return await response.json()

    async def async_batch_validate(
        self,
        contents: List[str],
        tier: Optional[RuleTier] = None,
        rule_ids: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
    ) -> BatchValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"contents": contents, "parallel": parallel}
        if tier:
            body["tier"] = tier.value
        if rule_ids:
            body["rule_ids"] = rule_ids
        if context:
            body["context"] = context

        url = self._build_url("batch_validate")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return BatchValidationResult.from_dict(data)

    async def async_check_compliance(
        self,
        content: str,
        regulations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if regulations:
            body["regulations"] = regulations
        if context:
            body["context"] = context

        url = self._build_url("compliance")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_check_safety(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        url = self._build_url("safety")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_check_format(
        self,
        content: str,
        format_type: str = "text",
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content, "format_type": format_type}
        if context:
            body["context"] = context

        url = self._build_url("format")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_check_quality(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        url = self._build_url("quality")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_detect_hallucinations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        url = self._build_url("hallucination")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_validate_citations(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        session = self._get_async_session()
        body: Dict[str, Any] = {"content": content}
        if context:
            body["context"] = context

        url = self._build_url("citations")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return ValidationResult.from_dict(data)

    async def async_trigger_alert(
        self,
        name: str,
        severity: RuleSeverity,
        message: str,
        metric_value: float = 0.0,
        threshold: float = 0.0,
        source: str = "sdk",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertEvent:
        session = self._get_async_session()
        body: Dict[str, Any] = {
            "name": name,
            "severity": severity.value,
            "message": message,
            "metric_value": metric_value,
            "threshold": threshold,
            "source": source,
        }
        if metadata:
            body["metadata"] = metadata

        url = self._build_url("alerts")
        async with session.post(url, json=body) as response:
            data = await response.json()
            return AlertEvent.from_dict(data)

    async def async_resolve_alert(self, alert_id: str) -> bool:
        try:
            session = self._get_async_session()
            url = self._build_url("alert", alert_id=alert_id)
            async with session.post(url, json={"status": "resolved"}) as response:
                return response.status == 200
        except SDKError:
            return False

    async def async_get_dashboard(self) -> Dict[str, Any]:
        session = self._get_async_session()
        url = self._build_url("dashboard")
        async with session.get(url) as response:
            return await response.json()

    async def async_get_rule_sets(
        self,
        tier: Optional[RuleTier] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[RuleSet]:
        session = self._get_async_session()
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if tier:
            params["tier"] = tier.value

        url = self._build_url("rule_sets")
        async with session.get(url, params=params) as response:
            data = await response.json()
            sets_data = data.get("rule_sets", data.get("data", []))
            if isinstance(sets_data, list):
                return [RuleSet.from_dict(s) for s in sets_data]
            return []

    async def async_get_rule_set(self, rule_set_id: str) -> RuleSet:
        session = self._get_async_session()
        url = self._build_url("rule_set", rule_set_id=rule_set_id)
        async with session.get(url) as response:
            data = await response.json()
            return RuleSet.from_dict(data)
