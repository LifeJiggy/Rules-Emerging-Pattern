"""
Remediation handler for automated error recovery with safety checks,
rollback support, verification, and full audit tracking.
"""

import logging
import uuid
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class RemediationActionType(str, Enum):
    """Types of remediation actions."""
    BLOCK = "block"
    REDACT = "redact"
    QUARANTINE = "quarantine"
    WARN = "warn"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    ROLLBACK = "rollback"
    RETRY = "retry"
    FALLBACK = "fallback"
    BYPASS = "bypass"
    CORRECT = "correct"
    SANITIZE = "sanitize"
    RECONFIGURE = "reconfigure"
    RESTART = "restart"
    CUSTOM = "custom"


class RemediationStatus(str, Enum):
    """Status of a remediation action."""
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class SafetyCheckResult(str, Enum):
    """Result of a safety check before remediation."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class RemediationAction:
    """Definition of a single remediation action."""
    action_id: str
    action_type: RemediationActionType
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    requires_approval: bool = False
    auto_remediate: bool = False
    priority: int = 100
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "action_type": self.action_type.value,
        }


@dataclass
class RemediationRecord:
    """Complete record of a remediation attempt."""
    remediation_id: str
    action_id: str
    action_type: RemediationActionType
    status: RemediationStatus
    source: str
    source_id: str
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    initiated_by: str = "system"
    approved_by: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    safety_checks: List[Dict[str, Any]] = field(default_factory=list)
    rollback_id: Optional[str] = None
    duration_ms: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "action_type": self.action_type.value,
            "status": self.status.value,
            "initiated_at": self.initiated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class RollbackRecord:
    """Record of a rollback operation."""
    rollback_id: str
    original_remediation_id: str
    status: RemediationStatus
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "status": self.status.value,
            "initiated_at": self.initiated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class RemediationWorkflow:
    """Config-driven remediation workflow definition."""
    workflow_id: str
    name: str
    description: str = ""
    error_types: List[str] = field(default_factory=list)
    severity_threshold: str = "medium"
    actions: List[RemediationAction] = field(default_factory=list)
    safety_checks: List[Dict[str, Any]] = field(default_factory=list)
    rollback_action: Optional[RemediationAction] = None
    auto_remediate: bool = False
    require_approval_for: List[str] = field(default_factory=list)
    max_retries: int = 3
    cooldown_seconds: int = 60
    enabled: bool = True
    version: str = "1.0.0"

    def matches_error_type(self, error_type: str) -> bool:
        return error_type in self.error_types or not self.error_types

    def matches_severity(self, severity: str) -> bool:
        order = ["low", "medium", "high", "critical"]
        threshold_idx = order.index(self.severity_threshold) if self.severity_threshold in order else 1
        sev_idx = order.index(severity) if severity in order else 0
        return sev_idx >= threshold_idx

    def add_action(self, action: RemediationAction) -> None:
        self.actions.append(action)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "error_types": self.error_types,
            "severity_threshold": self.severity_threshold,
            "actions": [a.to_dict() for a in self.actions],
            "safety_checks": self.safety_checks,
            "rollback_action": self.rollback_action.to_dict() if self.rollback_action else None,
            "auto_remediate": self.auto_remediate,
            "require_approval_for": self.require_approval_for,
            "max_retries": self.max_retries,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "version": self.version,
        }


class RemediationHandler:
    """Automated remediation execution with safety checks, rollback, and verification."""

    def __init__(self) -> None:
        self.logger = logger
        self._workflows: Dict[str, RemediationWorkflow] = {}
        self._remediations: Dict[str, RemediationRecord] = {}
        self._rollbacks: Dict[str, RollbackRecord] = {}
        self._action_handlers: Dict[str, Callable] = {}
        self._safety_checkers: List[Callable] = []
        self._verification_handlers: Dict[str, Callable] = {}
        self._cooldowns: Dict[str, datetime] = {}
        self._handlers: Dict[str, List[Callable]] = {
            "before_remediate": [],
            "after_remediate": [],
            "on_failure": [],
            "on_rollback": [],
            "on_verification": [],
        }
        self._init_default_workflows()
        self._register_default_handlers()

    # ------------------------------------------------------------------
    # Default Workflows
    # ------------------------------------------------------------------

    def _init_default_workflows(self) -> None:
        validation_workflow = RemediationWorkflow(
            workflow_id="validation_remediation",
            name="Validation Error Remediation",
            description="Standard remediation for validation errors",
            error_types=["validation", "data_quality"],
            severity_threshold="low",
            actions=[
                RemediationAction(
                    action_id="block_content",
                    action_type=RemediationActionType.BLOCK,
                    name="Block violating content",
                    description="Block content that violates validation rules",
                    auto_remediate=True,
                    priority=10,
                ),
                RemediationAction(
                    action_id="warn_user",
                    action_type=RemediationActionType.WARN,
                    name="Warn user",
                    description="Notify user of validation violation",
                    auto_remediate=True,
                    priority=20,
                ),
                RemediationAction(
                    action_id="suggest_correction",
                    action_type=RemediationActionType.CORRECT,
                    name="Suggest correction",
                    description="Provide correction suggestions to user",
                    auto_remediate=False,
                    priority=30,
                ),
            ],
            safety_checks=[
                {"check": "is_block_safe", "on_fail": "warn"},
                {"check": "has_user_context", "on_fail": "skip"},
            ],
        )
        security_workflow = RemediationWorkflow(
            workflow_id="security_remediation",
            name="Security Error Remediation",
            description="Remediation for security violations",
            error_types=["security"],
            severity_threshold="medium",
            actions=[
                RemediationAction(
                    action_id="quarantine_content",
                    action_type=RemediationActionType.QUARANTINE,
                    name="Quarantine content",
                    description="Quarantine content for security review",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=10,
                ),
                RemediationAction(
                    action_id="block_source",
                    action_type=RemediationActionType.BLOCK,
                    name="Block source",
                    description="Block the source of the security violation",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=20,
                ),
                RemediationAction(
                    action_id="notify_security_team",
                    action_type=RemediationActionType.NOTIFY,
                    name="Notify security team",
                    description="Alert security team of the violation",
                    auto_remediate=True,
                    priority=5,
                ),
                RemediationAction(
                    action_id="escalate_incident",
                    action_type=RemediationActionType.ESCALATE,
                    name="Escalate as incident",
                    description="Create security incident",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=30,
                ),
            ],
            safety_checks=[
                {"check": "is_quarantine_safe", "on_fail": "block"},
                {"check": "has_admin_context", "on_fail": "escalate"},
            ],
            rollback_action=RemediationAction(
                action_id="rollback_quarantine",
                action_type=RemediationActionType.ROLLBACK,
                name="Rollback quarantine",
                description="Release content from quarantine",
            ),
            auto_remediate=False,
            require_approval_for=["block_source", "quarantine_content"],
        )
        compliance_workflow = RemediationWorkflow(
            workflow_id="compliance_remediation",
            name="Compliance Error Remediation",
            description="Remediation for compliance violations",
            error_types=["compliance"],
            severity_threshold="medium",
            actions=[
                RemediationAction(
                    action_id="redact_content",
                    action_type=RemediationActionType.REDACT,
                    name="Redact sensitive content",
                    description="Redact content that violates compliance rules",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=10,
                ),
                RemediationAction(
                    action_id="notify_compliance_team",
                    action_type=RemediationActionType.NOTIFY,
                    name="Notify compliance team",
                    description="Alert compliance team",
                    auto_remediate=True,
                    priority=5,
                ),
                RemediationAction(
                    action_id="log_audit_event",
                    action_type=RemediationActionType.CUSTOM,
                    name="Log audit event",
                    description="Record compliance violation in audit log",
                    auto_remediate=True,
                    priority=20,
                ),
            ],
            safety_checks=[
                {"check": "is_redact_safe", "on_fail": "escalate"},
                {"check": "has_compliance_review", "on_fail": "warn"},
            ],
            auto_remediate=False,
        )
        system_workflow = RemediationWorkflow(
            workflow_id="system_remediation",
            name="System Error Remediation",
            description="Remediation for system-level errors",
            error_types=["system", "performance", "integration"],
            severity_threshold="medium",
            actions=[
                RemediationAction(
                    action_id="retry_operation",
                    action_type=RemediationActionType.RETRY,
                    name="Retry operation",
                    description="Retry the failed operation",
                    auto_remediate=True,
                    priority=10,
                    parameters={"max_retries": 3, "backoff_ms": 1000},
                ),
                RemediationAction(
                    action_id="fallback_procedure",
                    action_type=RemediationActionType.FALLBACK,
                    name="Execute fallback",
                    description="Execute fallback procedure",
                    auto_remediate=False,
                    priority=20,
                ),
                RemediationAction(
                    action_id="restart_component",
                    action_type=RemediationActionType.RESTART,
                    name="Restart component",
                    description="Restart the affected component",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=30,
                ),
                RemediationAction(
                    action_id="reconfigure_settings",
                    action_type=RemediationActionType.RECONFIGURE,
                    name="Reconfigure settings",
                    description="Adjust configuration to mitigate issue",
                    requires_approval=True,
                    auto_remediate=False,
                    priority=40,
                ),
            ],
            rollback_action=RemediationAction(
                action_id="restore_config",
                action_type=RemediationActionType.ROLLBACK,
                name="Restore configuration",
                description="Restore previous configuration",
            ),
        )
        for wf in [validation_workflow, security_workflow, compliance_workflow, system_workflow]:
            self._workflows[wf.workflow_id] = wf

    def _register_default_handlers(self) -> None:
        self.register_action_handler(RemediationActionType.BLOCK, self._handle_block)
        self.register_action_handler(RemediationActionType.REDACT, self._handle_redact)
        self.register_action_handler(RemediationActionType.QUARANTINE, self._handle_quarantine)
        self.register_action_handler(RemediationActionType.WARN, self._handle_warn)
        self.register_action_handler(RemediationActionType.NOTIFY, self._handle_notify)
        self.register_action_handler(RemediationActionType.ESCALATE, self._handle_escalate)
        self.register_action_handler(RemediationActionType.RETRY, self._handle_retry)
        self.register_action_handler(RemediationActionType.FALLBACK, self._handle_fallback)
        self.register_action_handler(RemediationActionType.CORRECT, self._handle_correct)
        self.register_action_handler(RemediationActionType.SANITIZE, self._handle_sanitize)
        self.register_action_handler(RemediationActionType.RECONFIGURE, self._handle_reconfigure)
        self.register_action_handler(RemediationActionType.RESTART, self._handle_restart)
        self.register_action_handler(RemediationActionType.ROLLBACK, self._handle_rollback_action)
        self.register_action_handler(RemediationActionType.CUSTOM, self._handle_custom)

        self.register_safety_checker(self._check_safety_block)
        self.register_safety_checker(self._check_safety_quarantine)
        self.register_safety_checker(self._check_safety_redact)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_workflow(self, workflow: RemediationWorkflow) -> None:
        self._workflows[workflow.workflow_id] = workflow

    def get_workflow(self, workflow_id: str) -> Optional[RemediationWorkflow]:
        return self._workflows.get(workflow_id)

    def register_action_handler(self, action_type: RemediationActionType, handler: Callable) -> None:
        self._action_handlers[action_type.value] = handler

    def register_safety_checker(self, checker: Callable) -> None:
        self._safety_checkers.append(checker)

    def register_verification_handler(self, action_type: str, handler: Callable) -> None:
        self._verification_handlers[action_type] = handler

    def register_handler(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].append(handler)

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def before_remediate(self, handler: Callable) -> None:
        self._handlers["before_remediate"].append(handler)

    def after_remediate(self, handler: Callable) -> None:
        self._handlers["after_remediate"].append(handler)

    def on_failure(self, handler: Callable) -> None:
        self._handlers["on_failure"].append(handler)

    def on_rollback(self, handler: Callable) -> None:
        self._handlers["on_rollback"].append(handler)

    def on_verification(self, handler: Callable) -> None:
        self._handlers["on_verification"].append(handler)

    def _fire_event(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception as exc:
                self.logger.error("Event handler %s failed: %s", event, exc)

    # ------------------------------------------------------------------
    # Core Remediation
    # ------------------------------------------------------------------

    def remediate(
        self,
        violation: Violation,
        error_type: str = "validation",
        context: Optional[Dict[str, Any]] = None,
        initiated_by: str = "system",
    ) -> List[RemediationRecord]:
        context = context or {}
        records: List[RemediationRecord] = []
        workflow = self._resolve_workflow(error_type, violation.rule_severity.value)
        if not workflow:
            self.logger.warning("No workflow found for error_type=%s severity=%s", error_type, violation.rule_severity.value)
            return records
        if not workflow.enabled:
            self.logger.info("Workflow %s is disabled, skipping", workflow.workflow_id)
            return records
        if self._in_cooldown(violation.rule_id):
            self.logger.info("In cooldown for source %s, skipping auto-remediation", violation.rule_id)
            return records

        for action in sorted(workflow.actions, key=lambda a: a.priority):
            if not action.enabled:
                continue
            if action.requires_approval and workflow.auto_remediate:
                self.logger.info("Action %s requires approval, skipping auto-remediate", action.action_id)
                continue

            remediation_id = self._generate_remediation_id(action)
            record = RemediationRecord(
                remediation_id=remediation_id,
                action_id=action.action_id,
                action_type=action.action_type,
                status=RemediationStatus.PENDING,
                source=error_type,
                source_id=violation.rule_id,
                initiated_at=datetime.utcnow(),
                initiated_by=initiated_by,
                parameters=action.parameters,
                context=context,
                metadata={"violation": violation.dict()},
            )
            self._remediations[remediation_id] = record
            self._fire_event("before_remediate", record=record, violation=violation, action=action)

            safety_result = self._run_safety_checks(action, violation, context)
            record.safety_checks = safety_result
            if any(s["result"] == SafetyCheckResult.FAILED.value for s in safety_result):
                record.status = RemediationStatus.FAILED
                record.error_message = "Safety checks failed"
                record.completed_at = datetime.utcnow()
                self._fire_event("on_failure", record=record, reason="safety_check_failed")
                records.append(record)
                continue

            if not action.auto_remediate and not action.requires_approval:
                record.status = RemediationStatus.SKIPPED
                record.completed_at = datetime.utcnow()
                records.append(record)
                continue

            record.status = RemediationStatus.IN_PROGRESS
            start = datetime.utcnow()
            try:
                result = self._execute_action(action, violation, context)
                record.result = result
                record.completed_at = datetime.utcnow()
                record.duration_ms = int((record.completed_at - start).total_seconds() * 1000)
                if result.get("success", False):
                    record.status = RemediationStatus.COMPLETED
                    verification = self._verify_remediation(action, record, violation)
                    record.metadata["verification"] = verification
                    self._fire_event("after_remediate", record=record, action=action, result=result)
                else:
                    record.status = RemediationStatus.FAILED
                    record.error_message = result.get("error", "Action execution failed")
                    self._fire_event("on_failure", record=record, error=record.error_message)
            except Exception as exc:
                record.status = RemediationStatus.FAILED
                record.error_message = str(exc)
                record.completed_at = datetime.utcnow()
                record.duration_ms = int((record.completed_at - start).total_seconds() * 1000)
                self.logger.error("Remediation action %s failed: %s", action.action_id, exc)
                self._fire_event("on_failure", record=record, error=str(exc))
            records.append(record)

        if workflow.auto_remediate and records:
            self._set_cooldown(violation.rule_id, workflow.cooldown_seconds)
        return records

    def remediate_batch(
        self,
        violations: List[Violation],
        error_type: str = "validation",
        context: Optional[Dict[str, Any]] = None,
        initiated_by: str = "system",
    ) -> Dict[str, List[RemediationRecord]]:
        results: Dict[str, List[RemediationRecord]] = {}
        for violation in violations:
            records = self.remediate(violation, error_type, context, initiated_by)
            results[violation.rule_id] = records
        return results

    def remediate_result(
        self,
        result: ValidationResult,
        error_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        initiated_by: str = "system",
    ) -> Dict[str, List[RemediationRecord]]:
        results: Dict[str, List[RemediationRecord]] = {}
        all_violations = result.violations + result.warnings
        for violation in all_violations:
            et = error_type or violation.violation_type.value
            records = self.remediate(violation, et, context, initiated_by)
            results[violation.rule_id] = results.get(violation.rule_id, []) + records
        return results

    # ------------------------------------------------------------------
    # Action Execution
    # ------------------------------------------------------------------

    def _execute_action(
        self,
        action: RemediationAction,
        violation: Violation,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        handler = self._action_handlers.get(action.action_type.value)
        if not handler:
            self.logger.warning("No handler registered for action type %s", action.action_type.value)
            return {"success": False, "error": f"No handler for {action.action_type.value}"}
        return handler(action, violation, context)

    def _handle_block(self, action: RemediationAction, violation: Violation,
                      context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("BLOCK action: rule=%s content_len=%d",
                         violation.rule_id, len(violation.matched_content or ""))
        return {
            "success": True,
            "action": "block",
            "rule_id": violation.rule_id,
            "blocked": True,
        }

    def _handle_redact(self, action: RemediationAction, violation: Violation,
                       context: Dict[str, Any]) -> Dict[str, Any]:
        content = violation.matched_content or ""
        redacted = f"[REDACTED - {violation.rule_name}]"
        self.logger.info("REDACT action: rule=%s redacted_len=%d", violation.rule_id, len(content))
        return {
            "success": True,
            "action": "redact",
            "original_length": len(content),
            "redacted_content": redacted,
        }

    def _handle_quarantine(self, action: RemediationAction, violation: Violation,
                           context: Dict[str, Any]) -> Dict[str, Any]:
        quarantine_id = f"q_{uuid.uuid4().hex[:12]}"
        self.logger.info("QUARANTINE action: id=%s rule=%s", quarantine_id, violation.rule_id)
        return {
            "success": True,
            "action": "quarantine",
            "quarantine_id": quarantine_id,
            "status": "quarantined",
        }

    def _handle_warn(self, action: RemediationAction, violation: Violation,
                     context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("WARN action: rule=%s user=%s", violation.rule_id, context.get("user_id"))
        return {
            "success": True,
            "action": "warn",
            "message": violation.explanation or "Rule violation detected",
        }

    def _handle_notify(self, action: RemediationAction, violation: Violation,
                       context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("NOTIFY action: rule=%s target=%s",
                         violation.rule_id, action.parameters.get("target", "admin"))
        return {
            "success": True,
            "action": "notify",
            "notification_sent": True,
        }

    def _handle_escalate(self, action: RemediationAction, violation: Violation,
                         context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("ESCALATE action: rule=%s severity=%s",
                         violation.rule_id, violation.rule_severity.value)
        return {
            "success": True,
            "action": "escalate",
            "escalation_level": violation.rule_severity.value,
        }

    def _handle_retry(self, action: RemediationAction, violation: Violation,
                      context: Dict[str, Any]) -> Dict[str, Any]:
        max_retries = action.parameters.get("max_retries", 3)
        backoff_ms = action.parameters.get("backoff_ms", 1000)
        attempts = 0
        last_error: Optional[str] = None
        while attempts < max_retries:
            attempts += 1
            try:
                self.logger.info("RETRY attempt %d/%d for %s", attempts, max_retries, violation.rule_id)
                return {
                    "success": True,
                    "action": "retry",
                    "attempts": attempts,
                    "max_retries": max_retries,
                }
            except Exception as exc:
                last_error = str(exc)
                if attempts < max_retries:
                    time.sleep(backoff_ms * attempts / 1000)
        return {
            "success": False,
            "action": "retry",
            "error": last_error or "Max retries exceeded",
            "attempts": attempts,
        }

    def _handle_fallback(self, action: RemediationAction, violation: Violation,
                         context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("FALLBACK action: rule=%s", violation.rule_id)
        return {
            "success": True,
            "action": "fallback",
            "fallback_triggered": True,
        }

    def _handle_correct(self, action: RemediationAction, violation: Violation,
                        context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("CORRECT action: rule=%s", violation.rule_id)
        return {
            "success": True,
            "action": "correct",
            "correction_suggested": True,
            "suggestion": violation.suggestions[0] if violation.suggestions else None,
        }

    def _handle_sanitize(self, action: RemediationAction, violation: Violation,
                         context: Dict[str, Any]) -> Dict[str, Any]:
        content = violation.matched_content or ""
        sanitized = content
        self.logger.info("SANITIZE action: rule=%s original_len=%d", violation.rule_id, len(content))
        return {
            "success": True,
            "action": "sanitize",
            "original_length": len(content),
            "sanitized_length": len(sanitized),
        }

    def _handle_reconfigure(self, action: RemediationAction, violation: Violation,
                            context: Dict[str, Any]) -> Dict[str, Any]:
        config_changes = action.parameters.get("changes", {})
        self.logger.info("RECONFIGURE action: changes=%s", config_changes)
        return {
            "success": True,
            "action": "reconfigure",
            "changes_applied": config_changes,
            "requires_restart": action.parameters.get("requires_restart", False),
        }

    def _handle_restart(self, action: RemediationAction, violation: Violation,
                        context: Dict[str, Any]) -> Dict[str, Any]:
        component = action.parameters.get("component", "unknown")
        self.logger.info("RESTART action: component=%s", component)
        return {
            "success": True,
            "action": "restart",
            "component": component,
            "restart_initiated": True,
        }

    def _handle_rollback_action(self, action: RemediationAction, violation: Violation,
                                context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("ROLLBACK action: rule=%s", violation.rule_id)
        return {
            "success": True,
            "action": "rollback",
            "rolled_back": True,
        }

    def _handle_custom(self, action: RemediationAction, violation: Violation,
                       context: Dict[str, Any]) -> Dict[str, Any]:
        custom_handler = action.parameters.get("handler")
        if custom_handler:
            try:
                return custom_handler(action, violation, context)
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        self.logger.info("CUSTOM action: id=%s (no handler)", action.action_id)
        return {"success": True, "action": "custom", "handler_not_implemented": True}

    # ------------------------------------------------------------------
    # Safety Checks
    # ------------------------------------------------------------------

    def _run_safety_checks(
        self,
        action: RemediationAction,
        violation: Violation,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for checker in self._safety_checkers:
            try:
                check_result = checker(action, violation, context)
                results.append(check_result)
            except Exception as exc:
                results.append({
                    "check": checker.__name__,
                    "result": SafetyCheckResult.FAILED.value,
                    "error": str(exc),
                })
        return results

    def _check_safety_block(self, action: RemediationAction, violation: Violation,
                            context: Dict[str, Any]) -> Dict[str, Any]:
        if action.action_type != RemediationActionType.BLOCK:
            return {"check": "is_block_safe", "result": SafetyCheckResult.SKIPPED.value}
        if violation.is_critical():
            return {"check": "is_block_safe", "result": SafetyCheckResult.PASSED.value}
        if context.get("user_role") == "admin":
            return {"check": "is_block_safe", "result": SafetyCheckResult.WARNING.value}
        return {"check": "is_block_safe", "result": SafetyCheckResult.PASSED.value}

    def _check_safety_quarantine(self, action: RemediationAction, violation: Violation,
                                 context: Dict[str, Any]) -> Dict[str, Any]:
        if action.action_type != RemediationActionType.QUARANTINE:
            return {"check": "is_quarantine_safe", "result": SafetyCheckResult.SKIPPED.value}
        if violation.rule_tier == RuleTier.SAFETY:
            return {"check": "is_quarantine_safe", "result": SafetyCheckResult.PASSED.value}
        if context.get("has_backup", False):
            return {"check": "is_quarantine_safe", "result": SafetyCheckResult.PASSED.value}
        return {"check": "is_quarantine_safe", "result": SafetyCheckResult.WARNING.value}

    def _check_safety_redact(self, action: RemediationAction, violation: Violation,
                             context: Dict[str, Any]) -> Dict[str, Any]:
        if action.action_type != RemediationActionType.REDACT:
            return {"check": "is_redact_safe", "result": SafetyCheckResult.SKIPPED.value}
        content_len = len(violation.matched_content or "")
        if content_len > 100000:
            return {"check": "is_redact_safe", "result": SafetyCheckResult.FAILED.value, "reason": "Content too large"}
        if violation.rule_tier == RuleTier.SAFETY:
            return {"check": "is_redact_safe", "result": SafetyCheckResult.PASSED.value}
        return {"check": "is_redact_safe", "result": SafetyCheckResult.PASSED.value}

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _verify_remediation(
        self,
        action: RemediationAction,
        record: RemediationRecord,
        violation: Violation,
    ) -> Dict[str, Any]:
        handler = self._verification_handlers.get(action.action_type.value)
        if handler:
            try:
                result = handler(action, record, violation)
                self._fire_event("on_verification", action=action, record=record, result=result)
                return result
            except Exception as exc:
                self.logger.error("Verification handler failed: %s", exc)
                return {"verified": False, "error": str(exc)}
        return {"verified": True, "method": "no_handler"}

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, remediation_id: str, initiated_by: str = "system") -> Optional[RollbackRecord]:
        record = self._remediations.get(remediation_id)
        if not record:
            self.logger.warning("Remediation not found: %s", remediation_id)
            return None
        workflow = self._resolve_workflow(record.source, None)
        rollback_action = workflow.rollback_action if workflow else None
        if not rollback_action:
            self.logger.warning("No rollback action defined for remediation %s", remediation_id)
            return None

        rollback_id = f"rb_{uuid.uuid4().hex[:12]}"
        rb_record = RollbackRecord(
            rollback_id=rollback_id,
            original_remediation_id=remediation_id,
            status=RemediationStatus.IN_PROGRESS,
            initiated_at=datetime.utcnow(),
            action=rollback_action.action_type.value,
            parameters=record.parameters,
        )
        self._rollbacks[rollback_id] = rb_record
        start = datetime.utcnow()
        try:
            result = self._execute_rollback(rollback_action, record)
            rb_record.result = result
            rb_record.completed_at = datetime.utcnow()
            rb_record.duration_ms = int((rb_record.completed_at - start).total_seconds() * 1000)
            if result.get("success", False):
                rb_record.status = RemediationStatus.COMPLETED
                record.status = RemediationStatus.ROLLED_BACK
                record.rollback_id = rollback_id
                self._fire_event("on_rollback", rollback=rb_record, original=record)
            else:
                rb_record.status = RemediationStatus.FAILED
                rb_record.error_message = result.get("error", "Rollback failed")
        except Exception as exc:
            rb_record.status = RemediationStatus.FAILED
            rb_record.error_message = str(exc)
            rb_record.completed_at = datetime.utcnow()
            rb_record.duration_ms = int((rb_record.completed_at - start).total_seconds() * 1000)
        self.logger.info("Rollback %s for remediation %s: %s", rollback_id, remediation_id, rb_record.status.value)
        return rb_record

    def _execute_rollback(self, action: RemediationAction, record: RemediationRecord) -> Dict[str, Any]:
        self.logger.info("Executing rollback for remediation %s", record.remediation_id)
        return {
            "success": True,
            "action": "rollback",
            "remediation_id": record.remediation_id,
            "original_action": record.action_type.value,
            "rolled_back": True,
        }

    def rollback_by_source(self, source_id: str, initiated_by: str = "system") -> List[RollbackRecord]:
        rollbacks: List[RollbackRecord] = []
        for record in self._remediations.values():
            if record.source_id == source_id and record.status == RemediationStatus.COMPLETED:
                rb = self.rollback(record.remediation_id, initiated_by)
                if rb:
                    rollbacks.append(rb)
        return rollbacks

    # ------------------------------------------------------------------
    # Workflow Resolution
    # ------------------------------------------------------------------

    def _resolve_workflow(self, error_type: str, severity: Optional[str]) -> Optional[RemediationWorkflow]:
        candidates: List[RemediationWorkflow] = []
        for wf in self._workflows.values():
            if not wf.enabled:
                continue
            if not wf.matches_error_type(error_type):
                continue
            if severity and not wf.matches_severity(severity):
                continue
            candidates.append(wf)
        if not candidates:
            return None
        candidates.sort(key=lambda w: len(w.error_types), reverse=True)
        return candidates[0]

    def find_workflows_for_error(self, error_type: str, severity: str) -> List[RemediationWorkflow]:
        return [
            wf for wf in self._workflows.values()
            if wf.enabled and wf.matches_error_type(error_type) and wf.matches_severity(severity)
        ]

    # ------------------------------------------------------------------
    # Cooldown
    # ------------------------------------------------------------------

    def _in_cooldown(self, source_id: str) -> bool:
        if source_id in self._cooldowns:
            return datetime.utcnow() < self._cooldowns[source_id]
        return False

    def _set_cooldown(self, source_id: str, seconds: int) -> None:
        self._cooldowns[source_id] = datetime.utcnow() + timedelta(seconds=seconds)

    def clear_cooldowns(self) -> None:
        self._cooldowns.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_remediation(self, remediation_id: str) -> Optional[RemediationRecord]:
        return self._remediations.get(remediation_id)

    def get_rollback(self, rollback_id: str) -> Optional[RollbackRecord]:
        return self._rollbacks.get(rollback_id)

    def get_remediations_by_source(self, source_id: str, limit: int = 100) -> List[RemediationRecord]:
        results = [r for r in self._remediations.values() if r.source_id == source_id]
        results.sort(key=lambda r: r.initiated_at, reverse=True)
        return results[:limit]

    def get_remediations_by_status(self, status: RemediationStatus, limit: int = 100) -> List[RemediationRecord]:
        results = [r for r in self._remediations.values() if r.status == status]
        results.sort(key=lambda r: r.initiated_at, reverse=True)
        return results[:limit]

    def get_remediations_by_action(self, action_type: RemediationActionType, limit: int = 100) -> List[RemediationRecord]:
        results = [r for r in self._remediations.values() if r.action_type == action_type]
        results.sort(key=lambda r: r.initiated_at, reverse=True)
        return results[:limit]

    def get_failed_remediations(self, limit: int = 100) -> List[RemediationRecord]:
        return self.get_remediations_by_status(RemediationStatus.FAILED, limit)

    def search_remediations(
        self,
        query: Optional[str] = None,
        action_type: Optional[RemediationActionType] = None,
        status: Optional[RemediationStatus] = None,
        source: Optional[str] = None,
        source_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RemediationRecord]:
        results = list(self._remediations.values())
        if query:
            q = query.lower()
            results = [r for r in results if q in r.source_id.lower() or q in r.action_id.lower()]
        if action_type:
            results = [r for r in results if r.action_type == action_type]
        if status:
            results = [r for r in results if r.status == status]
        if source:
            results = [r for r in results if r.source == source]
        if source_id:
            results = [r for r in results if r.source_id == source_id]
        if start_time:
            results = [r for r in results if r.initiated_at >= start_time]
        if end_time:
            results = [r for r in results if r.initiated_at <= end_time]
        results.sort(key=lambda r: r.initiated_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._remediations)
        if total == 0:
            return {"total_remediations": 0}
        by_status: Dict[str, int] = {}
        by_action: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        completed = 0
        failed = 0
        total_duration = 0
        for record in self._remediations.values():
            by_status[record.status.value] = by_status.get(record.status.value, 0) + 1
            by_action[record.action_type.value] = by_action.get(record.action_type.value, 0) + 1
            by_source[record.source] = by_source.get(record.source, 0) + 1
            if record.status == RemediationStatus.COMPLETED:
                completed += 1
            if record.status == RemediationStatus.FAILED:
                failed += 1
            total_duration += record.duration_ms
        return {
            "total_remediations": total,
            "by_status": by_status,
            "by_action_type": by_action,
            "by_source": by_source,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 2) if total else 0.0,
            "failure_rate": round(failed / total * 100, 2) if total else 0.0,
            "avg_duration_ms": round(total_duration / total, 2) if total else 0.0,
            "total_rollbacks": len(self._rollbacks),
            "active_workflows": sum(1 for w in self._workflows.values() if w.enabled),
        }

    def get_workflow_statistics(self, workflow_id: str) -> Dict[str, Any]:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return {"workflow_id": workflow_id, "error": "not_found"}
        wf_remediations = [
            r for r in self._remediations.values()
            if self._remediation_in_workflow(r, workflow)
        ]
        total = len(wf_remediations)
        if total == 0:
            return {"workflow_id": workflow_id, "name": workflow.name, "total": 0}
        completed = sum(1 for r in wf_remediations if r.status == RemediationStatus.COMPLETED)
        failed = sum(1 for r in wf_remediations if r.status == RemediationStatus.FAILED)
        return {
            "workflow_id": workflow_id,
            "name": workflow.name,
            "total_remediations": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 2) if total else 0.0,
            "actions_count": len(workflow.actions),
            "auto_remediate": workflow.auto_remediate,
            "has_rollback": workflow.rollback_action is not None,
        }

    @staticmethod
    def _remediation_in_workflow(record: RemediationRecord, workflow: RemediationWorkflow) -> bool:
        return any(a.action_id == record.action_id for a in workflow.actions)

    def get_effectiveness_report(self, days: int = 30) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [r for r in self._remediations.values() if r.initiated_at >= cutoff]
        total = len(recent)
        if total == 0:
            return {"period_days": days, "total": 0}
        completed = sum(1 for r in recent if r.status == RemediationStatus.COMPLETED)
        failed = sum(1 for r in recent if r.status == RemediationStatus.FAILED)
        rolled_back = sum(1 for r in recent if r.status == RemediationStatus.ROLLED_BACK)
        by_action_effectiveness: Dict[str, Dict[str, int]] = {}
        for r in recent:
            at = r.action_type.value
            if at not in by_action_effectiveness:
                by_action_effectiveness[at] = {"total": 0, "completed": 0, "failed": 0}
            by_action_effectiveness[at]["total"] += 1
            if r.status == RemediationStatus.COMPLETED:
                by_action_effectiveness[at]["completed"] += 1
            elif r.status == RemediationStatus.FAILED:
                by_action_effectiveness[at]["failed"] += 1
        return {
            "period_days": days,
            "total_remediations": total,
            "completed": completed,
            "failed": failed,
            "rolled_back": rolled_back,
            "success_rate": round(completed / total * 100, 2) if total else 0.0,
            "failure_rate": round(failed / total * 100, 2) if total else 0.0,
            "rollback_rate": round(rolled_back / total * 100, 2) if total else 0.0,
            "by_action_effectiveness": by_action_effectiveness,
            "avg_duration_ms": round(sum(r.duration_ms for r in recent) / total, 2) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def approve_remediation(self, remediation_id: str, approved_by: str) -> bool:
        record = self._remediations.get(remediation_id)
        if not record:
            return False
        if record.status != RemediationStatus.PENDING:
            return False
        record.status = RemediationStatus.APPROVED
        record.approved_by = approved_by
        return True

    def reject_remediation(self, remediation_id: str, rejected_by: str, reason: str = "") -> bool:
        record = self._remediations.get(remediation_id)
        if not record:
            return False
        if record.status != RemediationStatus.PENDING:
            return False
        record.status = RemediationStatus.CANCELLED
        record.metadata["rejected_by"] = rejected_by
        record.metadata["rejection_reason"] = reason
        return True

    def get_pending_approvals(self) -> List[RemediationRecord]:
        return self.get_remediations_by_status(RemediationStatus.PENDING)

    def get_pending_approvals_for_user(self, user_id: str) -> List[RemediationRecord]:
        return [
            r for r in self._remediations.values()
            if r.status == RemediationStatus.PENDING
            and user_id in r.metadata.get("approvers", [])
        ]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def export_workflows(self) -> List[Dict[str, Any]]:
        return [wf.to_dict() for wf in self._workflows.values()]

    def import_workflow(self, data: Dict[str, Any]) -> RemediationWorkflow:
        actions_data = data.pop("actions", [])
        rollback_data = data.pop("rollback_action", None)
        workflow = RemediationWorkflow(**data)
        for ad in actions_data:
            workflow.add_action(RemediationAction(**ad))
        if rollback_data:
            workflow.rollback_action = RemediationAction(**rollback_data)
        self.register_workflow(workflow)
        return workflow

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_remediation_id(action: RemediationAction) -> str:
        h = hashlib.sha256(f"{action.action_id}:{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
        return f"rem_{h}"

    def __len__(self) -> int:
        return len(self._remediations)

    def __contains__(self, remediation_id: str) -> bool:
        return remediation_id in self._remediations
