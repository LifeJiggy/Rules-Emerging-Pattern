"""
Organization rule store for organization-level rule management.

Provides multi-tenant rule storage, organizational policy management,
compliance rule enforcement, versioning, audit, and deployment across
organization members.
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict, OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class OrganizationNotFoundError(Exception):
    """Exception raised when an organization does not exist."""


class OrganizationLimitError(Exception):
    """Exception raised when organization limits are exceeded."""


class ComplianceViolationError(Exception):
    """Exception raised when a compliance check fails."""


class DeploymentError(Exception):
    """Exception raised when rule deployment fails."""


class AuditAction(str, Enum):
    """Actions that can be audited in the organization store."""

    RULE_CREATED = "rule.created"
    RULE_UPDATED = "rule.updated"
    RULE_DELETED = "rule.deleted"
    RULE_DEPLOYED = "rule.deployed"
    RULE_ACTIVATED = "rule.activated"
    RULE_DEACTIVATED = "rule.deactivated"
    POLICY_CREATED = "policy.created"
    POLICY_UPDATED = "policy.updated"
    POLICY_DELETED = "policy.deleted"
    COMPLIANCE_CHECK = "compliance.check"
    MEMBER_ADDED = "member.added"
    MEMBER_REMOVED = "member.removed"
    MEMBER_ROLE_CHANGED = "member.role.changed"
    SETTINGS_CHANGED = "settings.changed"
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_COMPLETED = "deployment.completed"
    DEPLOYMENT_FAILED = "deployment.failed"
    VERSION_TAGGED = "version.tagged"
    VERSION_ROLLED_BACK = "version.rolled_back"


@dataclass
class AuditEntry:
    """An audit log entry for organization actions."""

    action: AuditAction
    organization_id: str
    performed_by: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize audit entry to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEntry":
        """Create audit entry from dictionary."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            try:
                data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            except (ValueError, TypeError):
                data["timestamp"] = datetime.utcnow()
        if "action" in data and isinstance(data["action"], str):
            try:
                data["action"] = AuditAction(data["action"])
            except ValueError:
                pass
        return cls(**data)


@dataclass
class OrganizationProfile:
    """Profile for an organization in the rule store."""

    organization_id: str
    name: str
    description: str = ""
    max_members: int = 100
    max_rules: int = 5000
    max_policies: int = 50
    allowed_tiers: List[str] = field(default_factory=lambda: ["safety", "operational", "preference"])
    compliance_standards: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    parent_org_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize profile to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrganizationProfile":
        """Create profile from dictionary."""
        for key in ("created_at", "updated_at"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = datetime.utcnow()
        return cls(**data)


@dataclass
class OrganizationPolicy:
    """A policy definition for organization rule enforcement."""

    policy_id: str
    name: str
    description: str = ""
    organization_id: str = ""
    rules: List[str] = field(default_factory=list)
    enforcement_level: EnforcementLevel = EnforcementLevel.STRICT
    applicable_tiers: List[RuleTier] = field(default_factory=lambda: [RuleTier.SAFETY, RuleTier.OPERATIONAL])
    conditions: Dict[str, Any] = field(default_factory=dict)
    exceptions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    is_active: bool = True
    priority: int = 100
    tags: List[str] = field(default_factory=list)

    def is_applicable(self, context: Dict[str, Any]) -> bool:
        """Check if this policy is applicable in the given context."""
        if not self.is_active:
            return False
        for key, value in self.conditions.items():
            if key in context and context[key] != value:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize policy to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            elif isinstance(value, list) and value and isinstance(value[0], Enum):
                result[key] = [v.value for v in value]
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrganizationPolicy":
        """Create policy from dictionary."""
        for key in ("created_at", "updated_at"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key])
                except (ValueError, TypeError):
                    data[key] = datetime.utcnow()
        if "enforcement_level" in data and isinstance(data["enforcement_level"], str):
            try:
                data["enforcement_level"] = EnforcementLevel(data["enforcement_level"])
            except ValueError:
                data["enforcement_level"] = EnforcementLevel.STRICT
        if "applicable_tiers" in data:
            data["applicable_tiers"] = [
                RuleTier(t) if isinstance(t, str) else t
                for t in data["applicable_tiers"]
            ]
        return cls(**data)


@dataclass
class DeploymentRecord:
    """Record of a rule deployment to organization members."""

    deployment_id: str
    organization_id: str
    rule_ids: List[str]
    target_groups: List[str]
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    deployed_by: Optional[str] = None
    member_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    rollback_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class OrganizationRuleStore:
    """
    Multi-tenant organization rule store with policy management,
    compliance enforcement, versioning, audit, and deployment.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._storage_path = storage_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "org_rules"
        )
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._profiles: Dict[str, OrganizationProfile] = {}
        self._org_rules: Dict[str, Dict[str, Rule]] = defaultdict(dict)
        self._org_policies: Dict[str, Dict[str, OrganizationPolicy]] = defaultdict(dict)
        self._audit_logs: Dict[str, List[AuditEntry]] = defaultdict(list)
        self._deployment_records: Dict[str, List[DeploymentRecord]] = defaultdict(list)
        self._version_tags: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._member_cache: Dict[str, Set[str]] = defaultdict(set)
        self._compliance_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = RLock()
        self._load_state()
        logger.info(
            "OrganizationRuleStore initialized with %d orgs",
            len(self._profiles),
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the organization rule store."""
        return {
            "max_organizations": 1000,
            "max_rules_per_org": 5000,
            "max_policies_per_org": 50,
            "max_audit_entries_per_org": 10000,
            "audit_retention_days": 365,
            "enable_audit_logging": True,
            "enable_compliance_checking": True,
            "auto_save": True,
            "deployment_batch_size": 100,
            "deployment_timeout_seconds": 300,
            "version_history_limit": 100,
            "strict_compliance": False,
            "allow_hierarchy_inheritance": True,
            "hierarchy_depth_limit": 3,
            "storage_format": "json",
        }

    def register_organization(self, profile: OrganizationProfile) -> OrganizationProfile:
        """Register a new organization in the store."""
        with self._lock:
            if profile.organization_id in self._profiles:
                raise OrganizationLimitError(
                    f"Organization '{profile.organization_id}' already exists"
                )
            if len(self._profiles) >= self._config["max_organizations"]:
                raise OrganizationLimitError(
                    f"Maximum organizations reached ({self._config['max_organizations']})"
                )
            now = datetime.utcnow()
            profile.created_at = now
            profile.updated_at = now
            self._profiles[profile.organization_id] = profile
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.SETTINGS_CHANGED,
                        organization_id=profile.organization_id,
                        performed_by="system",
                        resource_id=profile.organization_id,
                        details={"action": "organization_registered"},
                    )
                )
            if self._config["auto_save"]:
                self._save_organization_profile(profile)
            logger.info("Registered organization: %s (%s)", profile.name, profile.organization_id)
            return deepcopy(profile)

    def get_organization(self, org_id: str) -> Optional[OrganizationProfile]:
        """Get organization profile by ID."""
        with self._lock:
            profile = self._profiles.get(org_id)
            return deepcopy(profile) if profile else None

    def update_organization(self, org_id: str, updates: Dict[str, Any]) -> OrganizationProfile:
        """Update organization profile."""
        with self._lock:
            profile = self._profiles.get(org_id)
            if not profile:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")
            for key, value in updates.items():
                if hasattr(profile, key) and key not in ("organization_id", "created_at"):
                    setattr(profile, key, value)
            profile.updated_at = datetime.utcnow()
            if self._config["auto_save"]:
                self._save_organization_profile(profile)
            logger.info("Updated organization: %s", org_id)
            return deepcopy(profile)

    def deactivate_organization(self, org_id: str) -> bool:
        """Deactivate an organization and all its rules."""
        with self._lock:
            profile = self._profiles.get(org_id)
            if not profile:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")
            profile.is_active = False
            profile.updated_at = datetime.utcnow()
            for rule in self._org_rules.get(org_id, {}).values():
                rule.status = RuleStatus.INACTIVE
            for policy in self._org_policies.get(org_id, {}).values():
                policy.is_active = False
            if self._config["auto_save"]:
                self._save_organization_profile(profile)
            logger.info("Deactivated organization: %s", org_id)
            return True

    def add_organization_rule(self, org_id: str, rule: Rule, user_id: Optional[str] = None) -> Rule:
        """Add a rule at the organization level."""
        with self._lock:
            profile = self._profiles.get(org_id)
            if not profile or not profile.is_active:
                raise OrganizationNotFoundError(f"Active organization not found: {org_id}")
            org_rules = self._org_rules[org_id]
            if len(org_rules) >= min(profile.max_rules, self._config["max_rules_per_org"]):
                raise OrganizationLimitError(
                    f"Organization {org_id} has reached max rules ({profile.max_rules})"
                )
            if rule.id in org_rules:
                raise ValueError(f"Rule {rule.id} already exists in organization {org_id}")
            rule.created_at = datetime.utcnow()
            rule.updated_at = datetime.utcnow()
            rule.created_by = user_id or "system"
            org_rules[rule.id] = rule
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.RULE_CREATED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=rule.id,
                        details={"rule_name": rule.name, "rule_tier": rule.tier.value},
                    )
                )
            if self._config["auto_save"]:
                self._save_organization_rule(org_id, rule)
            logger.info("Added rule '%s' to org %s", rule.name, org_id)
            return deepcopy(rule)

    def get_organization_rule(self, org_id: str, rule_id: str) -> Optional[Rule]:
        """Get an organization-level rule."""
        with self._lock:
            org_rules = self._org_rules.get(org_id, {})
            rule = org_rules.get(rule_id)
            return deepcopy(rule) if rule else None

    def get_organization_rules(
        self,
        org_id: str,
        include_inactive: bool = False,
    ) -> Dict[str, Rule]:
        """Get all rules for an organization."""
        with self._lock:
            rules = self._org_rules.get(org_id, {})
            if not include_inactive:
                rules = {
                    rid: rule for rid, rule in rules.items()
                    if rule.status == RuleStatus.ACTIVE
                }
            return {rid: deepcopy(rule) for rid, rule in rules.items()}

    def update_organization_rule(
        self,
        org_id: str,
        rule_id: str,
        updates: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Rule:
        """Update an organization-level rule."""
        with self._lock:
            org_rules = self._org_rules.get(org_id, {})
            rule = org_rules.get(rule_id)
            if not rule:
                raise KeyError(f"Rule {rule_id} not found in org {org_id}")
            for key, value in updates.items():
                if hasattr(rule, key) and key not in ("id", "created_at", "created_by"):
                    setattr(rule, key, value)
            rule.updated_at = datetime.utcnow()
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.RULE_UPDATED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=rule_id,
                        details={"updates": list(updates.keys())},
                    )
                )
            if self._config["auto_save"]:
                self._save_organization_rule(org_id, rule)
            logger.info("Updated rule '%s' in org %s", rule.name, org_id)
            return deepcopy(rule)

    def delete_organization_rule(
        self,
        org_id: str,
        rule_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Delete an organization-level rule."""
        with self._lock:
            org_rules = self._org_rules.get(org_id, {})
            if rule_id not in org_rules:
                return False
            del org_rules[rule_id]
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.RULE_DELETED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=rule_id,
                    )
                )
            if self._config["auto_save"]:
                self._delete_org_rule_file(org_id, rule_id)
            logger.info("Deleted rule '%s' from org %s", rule_id, org_id)
            return True

    def create_policy(self, org_id: str, policy: OrganizationPolicy, user_id: Optional[str] = None) -> OrganizationPolicy:
        """Create a policy for an organization."""
        with self._lock:
            if org_id not in self._profiles:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")
            policies = self._org_policies[org_id]
            if len(policies) >= self._config["max_policies_per_org"]:
                raise OrganizationLimitError(
                    f"Organization {org_id} has reached max policies "
                    f"({self._config['max_policies_per_org']})"
                )
            policy.organization_id = org_id
            policy.created_at = datetime.utcnow()
            policy.updated_at = datetime.utcnow()
            policy.created_by = user_id
            policies[policy.policy_id] = policy
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.POLICY_CREATED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=policy.policy_id,
                        details={"policy_name": policy.name},
                    )
                )
            if self._config["auto_save"]:
                self._save_org_policy(org_id, policy)
            logger.info("Created policy '%s' for org %s", policy.name, org_id)
            return deepcopy(policy)

    def get_policy(self, org_id: str, policy_id: str) -> Optional[OrganizationPolicy]:
        """Get a policy by ID."""
        with self._lock:
            policies = self._org_policies.get(org_id, {})
            policy = policies.get(policy_id)
            return deepcopy(policy) if policy else None

    def get_organization_policies(self, org_id: str) -> Dict[str, OrganizationPolicy]:
        """Get all policies for an organization."""
        with self._lock:
            policies = self._org_policies.get(org_id, {})
            return {pid: deepcopy(p) for pid, p in policies.items()}

    def update_policy(
        self,
        org_id: str,
        policy_id: str,
        updates: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> OrganizationPolicy:
        """Update an organization policy."""
        with self._lock:
            policies = self._org_policies.get(org_id, {})
            policy = policies.get(policy_id)
            if not policy:
                raise KeyError(f"Policy {policy_id} not found in org {org_id}")
            for key, value in updates.items():
                if hasattr(policy, key) and key not in ("policy_id", "organization_id", "created_at"):
                    setattr(policy, key, value)
            policy.updated_at = datetime.utcnow()
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.POLICY_UPDATED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=policy_id,
                        details={"updates": list(updates.keys())},
                    )
                )
            if self._config["auto_save"]:
                self._save_org_policy(org_id, policy)
            logger.info("Updated policy '%s' in org %s", policy.name, org_id)
            return deepcopy(policy)

    def delete_policy(self, org_id: str, policy_id: str, user_id: Optional[str] = None) -> bool:
        """Delete an organization policy."""
        with self._lock:
            policies = self._org_policies.get(org_id, {})
            if policy_id not in policies:
                return False
            del policies[policy_id]
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.POLICY_DELETED,
                        organization_id=org_id,
                        performed_by=user_id or "system",
                        resource_id=policy_id,
                    )
                )
            logger.info("Deleted policy '%s' from org %s", policy_id, org_id)
            return True

    def check_compliance(
        self,
        org_id: str,
        rule: Rule,
    ) -> List[str]:
        """Check a rule against organization compliance standards."""
        violations: List[str] = []
        profile = self._profiles.get(org_id)
        if not profile:
            raise OrganizationNotFoundError(f"Organization not found: {org_id}")

        if rule.tier.value not in profile.allowed_tiers:
            violations.append(
                f"Rule tier '{rule.tier.value}' not in allowed tiers: "
                f"{profile.allowed_tiers}"
            )

        policies = self._org_policies.get(org_id, {}).values()
        for policy in policies:
            if not policy.is_active:
                continue
            if rule.id in policy.rules:
                allowed_enf_levels = {
                    EnforcementLevel.STRICT,
                    EnforcementLevel.ADVISORY,
                }
                if policy.enforcement_level == EnforcementLevel.STRICT:
                    if rule.enforcement_level != EnforcementLevel.STRICT:
                        violations.append(
                            f"Policy '{policy.name}' requires STRICT enforcement, "
                            f"got {rule.enforcement_level.value}"
                        )

        for handler in self._compliance_handlers.get(org_id, []):
            try:
                result = handler(rule)
                if result:
                    violations.extend(result if isinstance(result, list) else [result])
            except Exception as exc:
                logger.error("Compliance handler failed for org %s: %s", org_id, exc)
                if self._config["strict_compliance"]:
                    violations.append(f"Compliance check error: {exc}")

        if self._config["enable_audit_logging"]:
            self._add_audit_entry(
                AuditEntry(
                    action=AuditAction.COMPLIANCE_CHECK,
                    organization_id=org_id,
                    performed_by="system",
                    resource_id=rule.id,
                    details={
                        "rule_name": rule.name,
                        "violations": violations,
                        "compliant": len(violations) == 0,
                    },
                )
            )
        return violations

    def is_compliant(self, org_id: str, rule: Rule) -> bool:
        """Quick check if a rule is compliant."""
        return len(self.check_compliance(org_id, rule)) == 0

    def register_compliance_handler(
        self,
        org_id: str,
        handler: Callable[[Rule], Optional[Union[str, List[str]]]],
    ) -> None:
        """Register a custom compliance check handler."""
        self._compliance_handlers[org_id].append(handler)
        logger.debug("Registered compliance handler for org %s", org_id)

    def deploy_rules(
        self,
        org_id: str,
        rule_ids: List[str],
        target_groups: Optional[List[str]] = None,
        deployed_by: Optional[str] = None,
    ) -> DeploymentRecord:
        """Deploy rules to organization members or groups."""
        with self._lock:
            if org_id not in self._profiles:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")

            org_rules = self._org_rules.get(org_id, {})
            missing = [rid for rid in rule_ids if rid not in org_rules]
            if missing:
                raise DeploymentError(
                    f"Rules not found in org {org_id}: {missing}"
                )

            deployment = DeploymentRecord(
                deployment_id=str(uuid.uuid4()),
                organization_id=org_id,
                rule_ids=rule_ids,
                target_groups=target_groups or ["all"],
                deployed_by=deployed_by,
                status="in_progress",
            )

            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.DEPLOYMENT_STARTED,
                        organization_id=org_id,
                        performed_by=deployed_by or "system",
                        resource_id=deployment.deployment_id,
                        details={"rule_count": len(rule_ids), "groups": target_groups},
                    )
                )

            members = self._member_cache.get(org_id, set())
            deployment.member_count = len(members)
            deployment.success_count = len(rule_ids)
            deployment.status = "completed"
            deployment.completed_at = datetime.utcnow()

            self._deployment_records[org_id].append(deployment)

            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.DEPLOYMENT_COMPLETED,
                        organization_id=org_id,
                        performed_by=deployed_by or "system",
                        resource_id=deployment.deployment_id,
                        details={
                            "member_count": deployment.member_count,
                            "success_count": deployment.success_count,
                            "failure_count": deployment.failure_count,
                        },
                    )
                )

            logger.info(
                "Deployed %d rules to org %s (%d members)",
                len(rule_ids), org_id, len(members),
            )
            return deployment

    def add_members(self, org_id: str, user_ids: List[str]) -> int:
        """Add members to an organization."""
        with self._lock:
            profile = self._profiles.get(org_id)
            if not profile:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")
            members = self._member_cache[org_id]
            added = 0
            for uid in user_ids:
                if uid not in members:
                    members.add(uid)
                    added += 1
            if added > 0 and self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.MEMBER_ADDED,
                        organization_id=org_id,
                        performed_by="system",
                        details={"added_count": added, "total_members": len(members)},
                    )
                )
            return added

    def remove_members(self, org_id: str, user_ids: List[str]) -> int:
        """Remove members from an organization."""
        with self._lock:
            members = self._member_cache.get(org_id, set())
            removed = 0
            for uid in user_ids:
                if uid in members:
                    members.remove(uid)
                    removed += 1
            if removed > 0 and self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.MEMBER_REMOVED,
                        organization_id=org_id,
                        performed_by="system",
                        details={"removed_count": removed, "total_members": len(members)},
                    )
                )
            return removed

    def get_members(self, org_id: str) -> Set[str]:
        """Get all members of an organization."""
        with self._lock:
            return set(self._member_cache.get(org_id, set()))

    def get_audit_logs(
        self,
        org_id: str,
        limit: int = 100,
        offset: int = 0,
        action_filter: Optional[AuditAction] = None,
    ) -> List[AuditEntry]:
        """Get audit logs for an organization."""
        with self._lock:
            logs = self._audit_logs.get(org_id, [])
            if action_filter:
                logs = [e for e in logs if e.action == action_filter]
            logs.sort(key=lambda e: e.timestamp, reverse=True)
            return [deepcopy(e) for e in logs[offset:offset + limit]]

    def create_version_tag(self, org_id: str, tag_name: str, description: Optional[str] = None) -> str:
        """Create a version tag for the current state of organization rules."""
        with self._lock:
            org_rules = self._org_rules.get(org_id, {})
            snapshot_id = str(uuid.uuid4())
            snapshot = {
                rid: rule.dict() for rid, rule in org_rules.items()
            }
            self._version_tags[org_id][tag_name] = json.dumps({
                "snapshot_id": snapshot_id,
                "tag_name": tag_name,
                "description": description,
                "timestamp": datetime.utcnow().isoformat(),
                "rules": snapshot,
            })
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.VERSION_TAGGED,
                        organization_id=org_id,
                        performed_by="system",
                        resource_id=tag_name,
                        details={"description": description, "rule_count": len(snapshot)},
                    )
                )
            return snapshot_id

    def rollback_to_tag(self, org_id: str, tag_name: str) -> int:
        """Rollback organization rules to a version tag."""
        with self._lock:
            if tag_name not in self._version_tags.get(org_id, {}):
                raise ValueError(f"Version tag '{tag_name}' not found for org {org_id}")
            tag_data = json.loads(self._version_tags[org_id][tag_name])
            rules_snapshot = tag_data["rules"]
            org_rules = self._org_rules[org_id]
            org_rules.clear()
            for rid, rule_dict in rules_snapshot.items():
                for key in ("created_at", "updated_at"):
                    if key in rule_dict and isinstance(rule_dict[key], str):
                        try:
                            rule_dict[key] = datetime.fromisoformat(rule_dict[key])
                        except (ValueError, TypeError):
                            rule_dict[key] = datetime.utcnow()
                org_rules[rid] = Rule(**rule_dict)
            if self._config["enable_audit_logging"]:
                self._add_audit_entry(
                    AuditEntry(
                        action=AuditAction.VERSION_ROLLED_BACK,
                        organization_id=org_id,
                        performed_by="system",
                        resource_id=tag_name,
                        details={"rule_count": len(rules_snapshot)},
                    )
                )
            logger.info("Rolled back org %s to tag '%s' (%d rules)", org_id, tag_name, len(rules_snapshot))
            return len(rules_snapshot)

    def prune_audit_logs(self, retention_days: Optional[int] = None) -> int:
        """Remove audit logs older than the retention period."""
        days = retention_days or self._config["audit_retention_days"]
        cutoff = datetime.utcnow() - timedelta(days=days)
        total = 0
        with self._lock:
            for org_id in list(self._audit_logs.keys()):
                original = len(self._audit_logs[org_id])
                self._audit_logs[org_id] = [
                    e for e in self._audit_logs[org_id]
                    if e.timestamp >= cutoff
                ]
                pruned = original - len(self._audit_logs[org_id])
                total += pruned
        logger.info("Pruned %d audit log entries older than %d days", total, days)
        return total

    def get_organization_statistics(self, org_id: str) -> Dict[str, Any]:
        """Get statistics for an organization."""
        with self._lock:
            profile = self._profiles.get(org_id)
            if not profile:
                raise OrganizationNotFoundError(f"Organization not found: {org_id}")
            rules = self._org_rules.get(org_id, {})
            policies = self._org_policies.get(org_id, {})
            members = self._member_cache.get(org_id, set())
            return {
                "organization_id": org_id,
                "name": profile.name,
                "is_active": profile.is_active,
                "rule_count": len(rules),
                "active_rule_count": sum(
                    1 for r in rules.values() if r.status == RuleStatus.ACTIVE
                ),
                "policy_count": len(policies),
                "active_policy_count": sum(1 for p in policies.values() if p.is_active),
                "member_count": len(members),
                "audit_log_count": len(self._audit_logs.get(org_id, [])),
                "deployment_count": len(self._deployment_records.get(org_id, [])),
                "version_tag_count": len(self._version_tags.get(org_id, {})),
            }

    def get_global_statistics(self) -> Dict[str, Any]:
        """Get global statistics across all organizations."""
        with self._lock:
            total_rules = sum(len(rules) for rules in self._org_rules.values())
            total_policies = sum(len(pol) for pol in self._org_policies.values())
            total_members = sum(len(m) for m in self._member_cache.values())
            total_audit = sum(len(l) for l in self._audit_logs.values())
            return {
                "total_organizations": len(self._profiles),
                "active_organizations": sum(
                    1 for p in self._profiles.values() if p.is_active
                ),
                "total_rules": total_rules,
                "total_policies": total_policies,
                "total_members": total_members,
                "total_audit_entries": total_audit,
            }

    def _add_audit_entry(self, entry: AuditEntry) -> None:
        """Add an audit log entry."""
        logs = self._audit_logs[entry.organization_id]
        logs.append(entry)
        limit = self._config["max_audit_entries_per_org"]
        if len(logs) > limit:
            self._audit_logs[entry.organization_id] = logs[-limit:]

    def _load_state(self) -> None:
        """Load all organization data from storage."""
        self._load_org_profiles()
        self._load_org_rules()
        self._load_org_policies()
        self._load_audit_logs()
        self._load_version_tags()

    def _load_org_profiles(self) -> None:
        """Load organization profiles from storage."""
        profiles_path = Path(self._storage_path) / "profiles"
        if not profiles_path.exists():
            profiles_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in profiles_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = OrganizationProfile.from_dict(data)
                self._profiles[profile.organization_id] = profile
            except Exception as exc:
                logger.error("Failed to load org profile from %s: %s", file_path, exc)

    def _load_org_rules(self) -> None:
        """Load organization rules from storage."""
        rules_path = Path(self._storage_path) / "rules"
        if not rules_path.exists():
            rules_path.mkdir(parents=True, exist_ok=True)
            return
        for org_dir in rules_path.iterdir():
            if not org_dir.is_dir():
                continue
            org_id = org_dir.name
            for file_path in org_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    rule = Rule(**data)
                    self._org_rules[org_id][rule.id] = rule
                except Exception as exc:
                    logger.error("Failed to load org rule from %s: %s", file_path, exc)

    def _load_org_policies(self) -> None:
        """Load organization policies from storage."""
        policies_path = Path(self._storage_path) / "policies"
        if not policies_path.exists():
            policies_path.mkdir(parents=True, exist_ok=True)
            return
        for org_dir in policies_path.iterdir():
            if not org_dir.is_dir():
                continue
            org_id = org_dir.name
            for file_path in org_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    policy = OrganizationPolicy.from_dict(data)
                    self._org_policies[org_id][policy.policy_id] = policy
                except Exception as exc:
                    logger.error("Failed to load org policy from %s: %s", file_path, exc)

    def _load_audit_logs(self) -> None:
        """Load audit logs from storage."""
        audit_path = Path(self._storage_path) / "audit"
        if not audit_path.exists():
            audit_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in audit_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries = [AuditEntry.from_dict(e) for e in data.get("entries", [])]
                org_id = data.get("organization_id", file_path.stem)
                self._audit_logs[org_id] = entries
            except Exception as exc:
                logger.error("Failed to load audit log from %s: %s", file_path, exc)

    def _load_version_tags(self) -> None:
        """Load version tags from storage."""
        tags_path = Path(self._storage_path) / "version_tags"
        if not tags_path.exists():
            tags_path.mkdir(parents=True, exist_ok=True)
            return
        for file_path in tags_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                org_id = data.get("organization_id", file_path.stem)
                tags = data.get("tags", {})
                self._version_tags[org_id] = tags
            except Exception as exc:
                logger.error("Failed to load version tags from %s: %s", file_path, exc)

    def _save_organization_profile(self, profile: OrganizationProfile) -> None:
        """Save organization profile to storage."""
        profiles_path = Path(self._storage_path) / "profiles"
        profiles_path.mkdir(parents=True, exist_ok=True)
        file_path = profiles_path / f"{profile.organization_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2, default=str)

    def _save_organization_rule(self, org_id: str, rule: Rule) -> None:
        """Save organization rule to storage."""
        rules_path = Path(self._storage_path) / "rules" / org_id
        rules_path.mkdir(parents=True, exist_ok=True)
        file_path = rules_path / f"{rule.id}.json"
        rule_dict = rule.dict()
        for key in ("created_at", "updated_at"):
            if key in rule_dict and isinstance(rule_dict[key], datetime):
                rule_dict[key] = rule_dict[key].isoformat()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rule_dict, f, indent=2, default=str)

    def _save_org_policy(self, org_id: str, policy: OrganizationPolicy) -> None:
        """Save organization policy to storage."""
        policies_path = Path(self._storage_path) / "policies" / org_id
        policies_path.mkdir(parents=True, exist_ok=True)
        file_path = policies_path / f"{policy.policy_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(policy.to_dict(), f, indent=2, default=str)

    def _delete_org_rule_file(self, org_id: str, rule_id: str) -> None:
        """Delete an organization rule file from storage."""
        file_path = Path(self._storage_path) / "rules" / org_id / f"{rule_id}.json"
        if file_path.exists():
            file_path.unlink()
