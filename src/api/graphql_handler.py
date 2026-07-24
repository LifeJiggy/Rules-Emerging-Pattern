"""
GraphQL handler providing schema definitions and resolvers for rules,
validations, metrics, and subscriptions.
"""

import asyncio
import hashlib
import json
import logging
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RuleEvaluationRequest,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import (
    ActionTaken,
    ValidationResult,
    Violation,
    ViolationType,
    Suggestion,
    ValidationProfile,
    ValidationThreshold,
)
from rules_emerging_pattern.models.conflict import (
    ConflictType,
    RuleConflict,
)

logger = logging.getLogger(__name__)


class GraphQLTypeKind(str, Enum):
    """GraphQL type system kinds."""
    SCALAR = "SCALAR"
    OBJECT = "OBJECT"
    INPUT_OBJECT = "INPUT_OBJECT"
    ENUM = "ENUM"
    INTERFACE = "INTERFACE"
    UNION = "UNION"
    LIST = "LIST"
    NON_NULL = "NON_NULL"


class GraphQLDirectiveLocation(str, Enum):
    """Valid locations for GraphQL directives."""
    QUERY = "QUERY"
    MUTATION = "MUTATION"
    SUBSCRIPTION = "SUBSCRIPTION"
    FIELD = "FIELD"
    FRAGMENT_DEFINITION = "FRAGMENT_DEFINITION"
    FRAGMENT_SPREAD = "FRAGMENT_SPREAD"
    INLINE_FRAGMENT = "INLINE_FRAGMENT"
    VARIABLE_DEFINITION = "VARIABLE_DEFINITION"
    SCHEMA = "SCHEMA"
    SCALAR = "SCALAR"
    OBJECT = "OBJECT"
    FIELD_DEFINITION = "FIELD_DEFINITION"
    ARGUMENT_DEFINITION = "ARGUMENT_DEFINITION"
    INTERFACE = "INTERFACE"
    UNION = "UNION"
    ENUM = "ENUM"
    ENUM_VALUE = "ENUM_VALUE"
    INPUT_OBJECT = "INPUT_OBJECT"
    INPUT_FIELD_DEFINITION = "INPUT_FIELD_DEFINITION"


@dataclass
class GraphQLField:
    """Definition of a GraphQL field."""
    name: str
    type_name: str
    description: str = ""
    args: List[Dict[str, Any]] = field(default_factory=list)
    resolver: Optional[str] = None
    deprecation_reason: Optional[str] = None
    is_required: bool = False
    is_list: bool = False


@dataclass
class GraphQLType:
    """Definition of a GraphQL type."""
    name: str
    kind: GraphQLTypeKind
    fields: List[GraphQLField] = field(default_factory=list)
    description: str = ""
    enum_values: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)


@dataclass
class GraphQLSchema:
    """Complete GraphQL schema definition."""
    query_type: str = "Query"
    mutation_type: str = "Mutation"
    subscription_type: str = "Subscription"
    types: Dict[str, GraphQLType] = field(default_factory=dict)
    directives: List[Dict[str, Any]] = field(default_factory=list)
    description: str = ""

    def add_type(self, type_def: GraphQLType) -> None:
        self.types[type_def.name] = type_def

    def get_type(self, name: str) -> Optional[GraphQLType]:
        return self.types.get(name)

    def has_type(self, name: str) -> bool:
        return name in self.types


@dataclass
class GraphQLRequest:
    """Parsed GraphQL request."""
    query: str
    operation_name: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)
    extensions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphQLError:
    """Formatted GraphQL error."""
    message: str
    locations: Optional[List[Dict[str, int]]] = None
    path: Optional[List[str]] = None
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"message": self.message}
        if self.locations:
            error["locations"] = self.locations
        if self.path:
            error["path"] = self.path
        if self.extensions:
            error["extensions"] = self.extensions
        return error


@dataclass
class GraphQLResponse:
    """Formatted GraphQL response."""
    data: Optional[Dict[str, Any]] = None
    errors: Optional[List[GraphQLError]] = None
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.data is not None:
            result["data"] = self.data
        if self.errors:
            result["errors"] = [e.to_dict() for e in self.errors]
        if self.extensions:
            result["extensions"] = self.extensions
        return result

    def has_errors(self) -> bool:
        return bool(self.errors)

    def add_error(self, message: str, path: Optional[List[str]] = None,
                  locations: Optional[List[Dict[str, int]]] = None) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(GraphQLError(message=message, path=path, locations=locations))


class GraphQLSchemaBuilder:
    """Builds the GraphQL schema for the rules engine."""

    def __init__(self) -> None:
        self._schema = GraphQLSchema(description="Rules Engine GraphQL API")

    def build(self) -> GraphQLSchema:
        self._add_scalar_types()
        self._add_enum_types()
        self._add_input_types()
        self._add_object_types()
        self._add_query_type()
        self._add_mutation_type()
        self._add_subscription_type()
        return self._schema

    def _add_scalar_types(self) -> None:
        for scalar in ["String", "Int", "Float", "Boolean", "ID", "DateTime", "JSON"]:
            self._schema.add_type(GraphQLType(
                name=scalar,
                kind=GraphQLTypeKind.SCALAR,
                description=f"The {scalar} scalar type"
            ))

    def _add_enum_types(self) -> None:
        enums = [
            ("RuleTier", [e.value for e in RuleTier], "Rule tier levels"),
            ("RuleType", [e.value for e in RuleType], "Types of rules"),
            ("RuleSeverity", [e.value for e in RuleSeverity], "Severity levels"),
            ("RuleStatus", [e.value for e in RuleStatus], "Rule status"),
            ("EnforcementLevel", [e.value for e in EnforcementLevel], "Enforcement levels"),
            ("ViolationType", [e.value for e in ViolationType], "Violation types"),
            ("ActionTaken", [e.value for e in ActionTaken], "Actions taken"),
            ("ConflictType", [e.value for e in ConflictType], "Conflict types"),
        ]
        for name, values, desc in enums:
            self._schema.add_type(GraphQLType(
                name=name,
                kind=GraphQLTypeKind.ENUM,
                enum_values=values,
                description=desc
            ))

    def _add_input_types(self) -> None:
        rule_input = GraphQLType(
            name="RuleInput",
            kind=GraphQLTypeKind.INPUT_OBJECT,
            description="Input fields for creating/updating a rule",
            fields=[
                GraphQLField("name", "String", "Rule name", is_required=True),
                GraphQLField("description", "String", "Rule description", is_required=True),
                GraphQLField("tier", "RuleTier", "Rule tier", is_required=True),
                GraphQLField("ruleType", "RuleType", "Rule type", is_required=True),
                GraphQLField("severity", "RuleSeverity", "Rule severity", is_required=True),
                GraphQLField("enforcementLevel", "EnforcementLevel", "Enforcement level", is_required=True),
                GraphQLField("status", "RuleStatus", "Rule status"),
                GraphQLField("autoBlock", "Boolean", "Auto-block on violation"),
                GraphQLField("userOverride", "Boolean", "Allow user override"),
                GraphQLField("tags", "String", "Rule tags", is_list=True),
                GraphQLField("priority", "Int", "Rule priority"),
                GraphQLField("timeoutMs", "Int", "Evaluation timeout"),
            ]
        )
        self._schema.add_type(rule_input)

        rule_filter = GraphQLType(
            name="RuleFilter",
            kind=GraphQLTypeKind.INPUT_OBJECT,
            description="Filter criteria for listing rules",
            fields=[
                GraphQLField("tier", "RuleTier", "Filter by tier"),
                GraphQLField("status", "RuleStatus", "Filter by status"),
                GraphQLField("ruleType", "RuleType", "Filter by rule type"),
                GraphQLField("severity", "RuleSeverity", "Filter by severity"),
                GraphQLField("search", "String", "Search in name/description"),
                GraphQLField("tags", "String", "Filter by tags", is_list=True),
            ]
        )
        self._schema.add_type(rule_filter)

        context_input = GraphQLType(
            name="RuleContextInput",
            kind=GraphQLTypeKind.INPUT_OBJECT,
            description="Context for rule evaluation",
            fields=[
                GraphQLField("userId", "String", "User ID"),
                GraphQLField("sessionId", "String", "Session ID"),
                GraphQLField("domain", "String", "Content domain"),
                GraphQLField("userRole", "String", "User role"),
                GraphQLField("contentType", "String", "Content type"),
                GraphQLField("language", "String", "Content language"),
            ]
        )
        self._schema.add_type(context_input)

        validation_input = GraphQLType(
            name="ValidationInput",
            kind=GraphQLTypeKind.INPUT_OBJECT,
            description="Input for content validation",
            fields=[
                GraphQLField("content", "String", "Content to validate", is_required=True),
                GraphQLField("context", "RuleContextInput", "Validation context"),
                GraphQLField("ruleIds", "String", "Specific rule IDs", is_list=True),
                GraphQLField("tier", "RuleTier", "Filter by tier"),
                GraphQLField("options", "JSON", "Additional options"),
            ]
        )
        self._schema.add_type(validation_input)

        pagination_input = GraphQLType(
            name="PaginationInput",
            kind=GraphQLTypeKind.INPUT_OBJECT,
            description="Pagination parameters",
            fields=[
                GraphQLField("page", "Int", "Page number"),
                GraphQLField("perPage", "Int", "Items per page"),
            ]
        )
        self._schema.add_type(pagination_input)

    def _add_object_types(self) -> None:
        rule_type = GraphQLType(
            name="Rule",
            kind=GraphQLTypeKind.OBJECT,
            description="A rule definition",
            fields=[
                GraphQLField("id", "ID", "Rule ID", is_required=True),
                GraphQLField("name", "String", "Rule name", is_required=True),
                GraphQLField("description", "String", "Rule description", is_required=True),
                GraphQLField("tier", "RuleTier", "Rule tier", is_required=True),
                GraphQLField("ruleType", "RuleType", "Rule type", is_required=True),
                GraphQLField("severity", "RuleSeverity", "Rule severity", is_required=True),
                GraphQLField("status", "RuleStatus", "Rule status", is_required=True),
                GraphQLField("enforcementLevel", "EnforcementLevel", "Enforcement level", is_required=True),
                GraphQLField("autoBlock", "Boolean", "Auto-block flag"),
                GraphQLField("userOverride", "Boolean", "User override flag"),
                GraphQLField("version", "String", "Rule version"),
                GraphQLField("tags", "String", "Rule tags", is_list=True),
                GraphQLField("priority", "Int", "Rule priority"),
                GraphQLField("timeoutMs", "Int", "Evaluation timeout"),
                GraphQLField("createdAt", "DateTime", "Creation timestamp"),
                GraphQLField("updatedAt", "DateTime", "Last update timestamp"),
                GraphQLField("createdBy", "String", "Creator"),
            ]
        )
        self._schema.add_type(rule_type)

        pagination_type = GraphQLType(
            name="PaginationInfo",
            kind=GraphQLTypeKind.OBJECT,
            description="Pagination information",
            fields=[
                GraphQLField("page", "Int", "Current page", is_required=True),
                GraphQLField("perPage", "Int", "Items per page", is_required=True),
                GraphQLField("total", "Int", "Total items", is_required=True),
                GraphQLField("totalPages", "Int", "Total pages", is_required=True),
                GraphQLField("hasNext", "Boolean", "Has next page", is_required=True),
                GraphQLField("hasPrevious", "Boolean", "Has previous page", is_required=True),
            ]
        )
        self._schema.add_type(pagination_type)

        rule_list_type = GraphQLType(
            name="RuleListResult",
            kind=GraphQLTypeKind.OBJECT,
            description="Paginated rule list",
            fields=[
                GraphQLField("items", "Rule", "Rule items", is_list=True, is_required=True),
                GraphQLField("pagination", "PaginationInfo", "Pagination info", is_required=True),
            ]
        )
        self._schema.add_type(rule_list_type)

        violation_type = GraphQLType(
            name="Violation",
            kind=GraphQLTypeKind.OBJECT,
            description="A rule violation",
            fields=[
                GraphQLField("ruleId", "ID", "Rule ID", is_required=True),
                GraphQLField("ruleName", "String", "Rule name", is_required=True),
                GraphQLField("ruleTier", "RuleTier", "Rule tier", is_required=True),
                GraphQLField("ruleSeverity", "RuleSeverity", "Rule severity", is_required=True),
                GraphQLField("violationType", "ViolationType", "Violation type", is_required=True),
                GraphQLField("confidenceScore", "Float", "Confidence score"),
                GraphQLField("actionTaken", "ActionTaken", "Action taken", is_required=True),
                GraphQLField("blocked", "Boolean", "Was blocked"),
                GraphQLField("explanation", "String", "Explanation"),
                GraphQLField("detectedAt", "DateTime", "Detection timestamp"),
            ]
        )
        self._schema.add_type(violation_type)

        validation_result_type = GraphQLType(
            name="ValidationResult",
            kind=GraphQLTypeKind.OBJECT,
            description="Result of content validation",
            fields=[
                GraphQLField("valid", "Boolean", "Whether content is valid", is_required=True),
                GraphQLField("totalScore", "Float", "Total score"),
                GraphQLField("confidence", "Float", "Overall confidence"),
                GraphQLField("totalRulesEvaluated", "Int", "Rules evaluated"),
                GraphQLField("rulesTriggered", "Int", "Rules triggered"),
                GraphQLField("rulesViolated", "Int", "Rules violated"),
                GraphQLField("violations", "Violation", "Violations", is_list=True),
                GraphQLField("processingTimeMs", "Int", "Processing time"),
                GraphQLField("evaluatedAt", "DateTime", "Evaluation timestamp"),
            ]
        )
        self._schema.add_type(validation_result_type)

        stats_type = GraphQLType(
            name="RuleStats",
            kind=GraphQLTypeKind.OBJECT,
            description="Rule statistics",
            fields=[
                GraphQLField("totalRules", "Int", "Total rules", is_required=True),
                GraphQLField("activeRules", "Int", "Active rules", is_required=True),
                GraphQLField("inactiveRules", "Int", "Inactive rules"),
                GraphQLField("byTier", "JSON", "Rules by tier"),
                GraphQLField("byStatus", "JSON", "Rules by status"),
                GraphQLField("bySeverity", "JSON", "Rules by severity"),
            ]
        )
        self._schema.add_type(stats_type)

        validation_stats_type = GraphQLType(
            name="ValidationStats",
            kind=GraphQLTypeKind.OBJECT,
            description="Validation statistics",
            fields=[
                GraphQLField("totalEvaluations", "Int", "Total evaluations", is_required=True),
                GraphQLField("validCount", "Int", "Valid count", is_required=True),
                GraphQLField("invalidCount", "Int", "Invalid count", is_required=True),
                GraphQLField("validRate", "Float", "Valid rate"),
                GraphQLField("averageProcessingTimeMs", "Float", "Average processing time"),
            ]
        )
        self._schema.add_type(validation_stats_type)

        alert_type = GraphQLType(
            name="Alert",
            kind=GraphQLTypeKind.OBJECT,
            description="System alert",
            fields=[
                GraphQLField("id", "ID", "Alert ID", is_required=True),
                GraphQLField("title", "String", "Alert title", is_required=True),
                GraphQLField("severity", "String", "Alert severity", is_required=True),
                GraphQLField("description", "String", "Alert description"),
                GraphQLField("source", "String", "Alert source"),
                GraphQLField("resolved", "Boolean", "Is resolved"),
                GraphQLField("createdAt", "DateTime", "Creation timestamp"),
                GraphQLField("resolvedAt", "DateTime", "Resolution timestamp"),
            ]
        )
        self._schema.add_type(alert_type)

        health_type = GraphQLType(
            name="SystemHealth",
            kind=GraphQLTypeKind.OBJECT,
            description="System health information",
            fields=[
                GraphQLField("status", "String", "System status", is_required=True),
                GraphQLField("activeRules", "Int", "Active rules"),
                GraphQLField("totalEvaluations", "Int", "Total evaluations"),
                GraphQLField("metricsCount", "Int", "Metrics count"),
                GraphQLField("alertsCount", "Int", "Alerts count"),
                GraphQLField("timestamp", "DateTime", "Health check timestamp", is_required=True),
            ]
        )
        self._schema.add_type(health_type)

    def _add_query_type(self) -> None:
        query = GraphQLType(
            name="Query",
            kind=GraphQLTypeKind.OBJECT,
            description="Root query type",
            fields=[
                GraphQLField(
                    name="rules",
                    type_name="RuleListResult",
                    description="List rules with filtering and pagination",
                    args=[
                        {"name": "filter", "type": "RuleFilter"},
                        {"name": "page", "type": "Int"},
                        {"name": "perPage", "type": "Int"},
                    ],
                    resolver="resolve_rules",
                    is_required=True,
                ),
                GraphQLField(
                    name="rule",
                    type_name="Rule",
                    description="Get a single rule by ID",
                    args=[{"name": "id", "type": "ID", "is_required": True}],
                    resolver="resolve_rule",
                ),
                GraphQLField(
                    name="validationResult",
                    type_name="ValidationResult",
                    description="Get a validation result by request ID",
                    args=[{"name": "requestId", "type": "ID", "is_required": True}],
                    resolver="resolve_validation_result",
                ),
                GraphQLField(
                    name="violations",
                    type_name="Violation",
                    description="Get violations for a result",
                    args=[{"name": "requestId", "type": "ID", "is_required": True}],
                    resolver="resolve_violations",
                    is_list=True,
                ),
                GraphQLField(
                    name="ruleStats",
                    type_name="RuleStats",
                    description="Get rule statistics",
                    resolver="resolve_rule_stats",
                    is_required=True,
                ),
                GraphQLField(
                    name="validationStats",
                    type_name="ValidationStats",
                    description="Get validation statistics",
                    resolver="resolve_validation_stats",
                    is_required=True,
                ),
                GraphQLField(
                    name="alerts",
                    type_name="Alert",
                    description="List alerts",
                    args=[
                        {"name": "severity", "type": "String"},
                        {"name": "resolved", "type": "Boolean"},
                        {"name": "page", "type": "Int"},
                        {"name": "perPage", "type": "Int"},
                    ],
                    resolver="resolve_alerts",
                    is_list=True,
                ),
                GraphQLField(
                    name="systemHealth",
                    type_name="SystemHealth",
                    description="Get system health",
                    resolver="resolve_system_health",
                    is_required=True,
                ),
                GraphQLField(
                    name="schema",
                    type_name="String",
                    description="Get the GraphQL schema definition",
                    resolver="resolve_schema",
                    is_required=True,
                ),
            ]
        )
        self._schema.add_type(query)

    def _add_mutation_type(self) -> None:
        mutation = GraphQLType(
            name="Mutation",
            kind=GraphQLTypeKind.OBJECT,
            description="Root mutation type",
            fields=[
                GraphQLField(
                    name="createRule",
                    type_name="Rule",
                    description="Create a new rule",
                    args=[{"name": "input", "type": "RuleInput", "is_required": True}],
                    resolver="resolve_create_rule",
                    is_required=True,
                ),
                GraphQLField(
                    name="updateRule",
                    type_name="Rule",
                    description="Update an existing rule",
                    args=[
                        {"name": "id", "type": "ID", "is_required": True},
                        {"name": "input", "type": "RuleInput", "is_required": True},
                    ],
                    resolver="resolve_update_rule",
                    is_required=True,
                ),
                GraphQLField(
                    name="deleteRule",
                    type_name="Boolean",
                    description="Delete a rule by ID",
                    args=[{"name": "id", "type": "ID", "is_required": True}],
                    resolver="resolve_delete_rule",
                    is_required=True,
                ),
                GraphQLField(
                    name="validate",
                    type_name="ValidationResult",
                    description="Validate content against rules",
                    args=[{"name": "input", "type": "ValidationInput", "is_required": True}],
                    resolver="resolve_validate",
                    is_required=True,
                ),
                GraphQLField(
                    name="toggleRuleStatus",
                    type_name="Rule",
                    description="Toggle rule status",
                    args=[
                        {"name": "id", "type": "ID", "is_required": True},
                        {"name": "status", "type": "RuleStatus", "is_required": True},
                    ],
                    resolver="resolve_toggle_rule_status",
                    is_required=True,
                ),
                GraphQLField(
                    name="createAlert",
                    type_name="Alert",
                    description="Create a new alert",
                    args=[
                        {"name": "title", "type": "String", "is_required": True},
                        {"name": "severity", "type": "String", "is_required": True},
                        {"name": "description", "type": "String"},
                    ],
                    resolver="resolve_create_alert",
                    is_required=True,
                ),
                GraphQLField(
                    name="resolveAlert",
                    type_name="Alert",
                    description="Resolve an alert by ID",
                    args=[{"name": "id", "type": "ID", "is_required": True}],
                    resolver="resolve_resolve_alert",
                    is_required=True,
                ),
                GraphQLField(
                    name="recordMetric",
                    type_name="Boolean",
                    description="Record a metric data point",
                    args=[
                        {"name": "name", "type": "String", "is_required": True},
                        {"name": "value", "type": "Float", "is_required": True},
                    ],
                    resolver="resolve_record_metric",
                    is_required=True,
                ),
            ]
        )
        self._schema.add_type(mutation)

    def _add_subscription_type(self) -> None:
        subscription = GraphQLType(
            name="Subscription",
            kind=GraphQLTypeKind.OBJECT,
            description="Root subscription type",
            fields=[
                GraphQLField(
                    name="validationEvents",
                    type_name="ValidationResult",
                    description="Subscribe to validation result events",
                    resolver="subscribe_validation_events",
                    is_required=True,
                ),
                GraphQLField(
                    name="alertEvents",
                    type_name="Alert",
                    description="Subscribe to alert events",
                    resolver="subscribe_alert_events",
                    is_required=True,
                ),
                GraphQLField(
                    name="ruleEvents",
                    type_name="Rule",
                    description="Subscribe to rule change events",
                    resolver="subscribe_rule_events",
                    is_required=True,
                ),
                GraphQLField(
                    name="metricsEvents",
                    type_name="JSON",
                    description="Subscribe to metrics update events",
                    resolver="subscribe_metrics_events",
                    is_required=True,
                ),
            ]
        )
        self._schema.add_type(subscription)


class GraphQLResolver:
    """Base class for GraphQL resolvers."""

    def __init__(self) -> None:
        self._rules_store: Dict[str, Rule] = {}
        self._validation_results: Dict[str, ValidationResult] = {}
        self._alerts: List[Dict[str, Any]] = []
        self._metrics_data: Dict[str, List[float]] = defaultdict(list)

    def resolve_rules(self, args: Dict[str, Any]) -> Dict[str, Any]:
        filter_args = args.get("filter", {})
        page = args.get("page", 1)
        per_page = args.get("perPage", 20)
        filtered = list(self._rules_store.values())
        if filter_args:
            if "tier" in filter_args:
                filtered = [r for r in filtered if r.tier.value == filter_args["tier"]]
            if "status" in filter_args:
                filtered = [r for r in filtered if r.status.value == filter_args["status"]]
            if "ruleType" in filter_args:
                filtered = [r for r in filtered if r.rule_type.value == filter_args["ruleType"]]
            if "severity" in filter_args:
                filtered = [r for r in filtered if r.severity.value == filter_args["severity"]]
            if "search" in filter_args:
                s = filter_args["search"].lower()
                filtered = [r for r in filtered if s in r.name.lower() or s in r.description.lower()]
            if "tags" in filter_args:
                tags = filter_args["tags"]
                filtered = [r for r in filtered if any(t in r.tags for t in tags)]
        sorted_rules = sorted(filtered, key=lambda r: r.created_at, reverse=True)
        total = len(sorted_rules)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        items = [r.to_dict() for r in sorted_rules[start:end]]
        return {
            "items": items,
            "pagination": {
                "page": page,
                "perPage": per_page,
                "total": total,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrevious": page > 1,
            }
        }

    def resolve_rule(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rule_id = args.get("id")
        rule = self._rules_store.get(rule_id)
        if rule:
            return rule.to_dict()
        return None

    def resolve_validation_result(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        request_id = args.get("requestId")
        result = self._validation_results.get(request_id)
        if result:
            return result.get_summary()
        return None

    def resolve_violations(self, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        request_id = args.get("requestId")
        result = self._validation_results.get(request_id)
        if result:
            return [v.to_summary() for v in result.violations]
        return []

    def resolve_rule_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        total = len(self._rules_store)
        active = sum(1 for r in self._rules_store.values() if r.status == RuleStatus.ACTIVE)
        inactive = total - active
        by_tier = defaultdict(int)
        by_status = defaultdict(int)
        by_severity = defaultdict(int)
        for rule in self._rules_store.values():
            by_tier[rule.tier.value] += 1
            by_status[rule.status.value] += 1
            by_severity[rule.severity.value] += 1
        return {
            "totalRules": total,
            "activeRules": active,
            "inactiveRules": inactive,
            "byTier": dict(by_tier),
            "byStatus": dict(by_status),
            "bySeverity": dict(by_severity),
        }

    def resolve_validation_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        total = len(self._validation_results)
        valid_count = sum(1 for r in self._validation_results.values() if r.valid)
        invalid_count = total - valid_count
        avg_time = 0
        if total > 0:
            avg_time = sum(r.processing_time_ms for r in self._validation_results.values()) / total
        return {
            "totalEvaluations": total,
            "validCount": valid_count,
            "invalidCount": invalid_count,
            "validRate": round((valid_count / total * 100) if total > 0 else 0, 2),
            "averageProcessingTimeMs": round(avg_time, 2),
        }

    def resolve_alerts(self, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        severity = args.get("severity")
        resolved = args.get("resolved")
        page = args.get("page", 1)
        per_page = args.get("perPage", 20)
        filtered = list(self._alerts)
        if severity:
            filtered = [a for a in filtered if a.get("severity") == severity]
        if resolved is not None:
            filtered = [a for a in filtered if a.get("resolved") == resolved]
        sorted_alerts = sorted(filtered, key=lambda a: a.get("createdAt", ""), reverse=True)
        start = (page - 1) * per_page
        end = start + per_page
        return sorted_alerts[start:end]

    def resolve_system_health(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "activeRules": sum(1 for r in self._rules_store.values() if r.status == RuleStatus.ACTIVE),
            "totalEvaluations": len(self._validation_results),
            "metricsCount": len(self._metrics_data),
            "alertsCount": len(self._alerts),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def resolve_schema(self, args: Dict[str, Any]) -> str:
        return "GraphQL schema definition (SDL)"

    def resolve_create_rule(self, args: Dict[str, Any]) -> Dict[str, Any]:
        import uuid
        input_data = args.get("input", {})
        rule = Rule(
            id=input_data.get("id", str(uuid.uuid4())),
            name=input_data["name"],
            description=input_data["description"],
            tier=RuleTier(input_data["tier"]),
            rule_type=RuleType(input_data["ruleType"]),
            severity=RuleSeverity(input_data["severity"]),
            enforcement_level=EnforcementLevel(input_data.get("enforcementLevel", EnforcementLevel.ADVISORY.value)),
            status=RuleStatus(input_data.get("status", RuleStatus.ACTIVE.value)),
            auto_block=input_data.get("autoBlock", False),
            user_override=input_data.get("userOverride", True),
            tags=input_data.get("tags", []),
            priority=input_data.get("priority", 100),
            timeout_ms=input_data.get("timeoutMs", 1000),
        )
        self._rules_store[rule.id] = rule
        return rule.to_dict()

    def resolve_update_rule(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rule_id = args.get("id")
        input_data = args.get("input", {})
        existing = self._rules_store.get(rule_id)
        if not existing:
            return None
        if "name" in input_data:
            existing.name = input_data["name"]
        if "description" in input_data:
            existing.description = input_data["description"]
        if "tier" in input_data:
            existing.tier = RuleTier(input_data["tier"])
        if "ruleType" in input_data:
            existing.rule_type = RuleType(input_data["ruleType"])
        if "severity" in input_data:
            existing.severity = RuleSeverity(input_data["severity"])
        if "enforcementLevel" in input_data:
            existing.enforcement_level = EnforcementLevel(input_data["enforcementLevel"])
        if "status" in input_data:
            existing.status = RuleStatus(input_data["status"])
        if "autoBlock" in input_data:
            existing.auto_block = input_data["autoBlock"]
        if "userOverride" in input_data:
            existing.user_override = input_data["userOverride"]
        if "tags" in input_data:
            existing.tags = input_data["tags"]
        if "priority" in input_data:
            existing.priority = input_data["priority"]
        if "timeoutMs" in input_data:
            existing.timeout_ms = input_data["timeoutMs"]
        existing.updated_at = datetime.utcnow()
        self._rules_store[rule_id] = existing
        return existing.to_dict()

    def resolve_delete_rule(self, args: Dict[str, Any]) -> bool:
        rule_id = args.get("id")
        if rule_id in self._rules_store:
            del self._rules_store[rule_id]
            return True
        return False

    def resolve_validate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        input_data = args.get("input", {})
        content = input_data.get("content", "")
        start = time.time()
        validation_result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
        )
        processing_time = int((time.time() - start) * 1000)
        validation_result.processing_time_ms = processing_time
        request_id = hashlib.md5(content.encode()).hexdigest()[:16]
        self._validation_results[request_id] = validation_result
        return validation_result.get_summary()

    def resolve_toggle_rule_status(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rule_id = args.get("id")
        new_status = args.get("status")
        existing = self._rules_store.get(rule_id)
        if not existing:
            return None
        existing.status = RuleStatus(new_status)
        existing.updated_at = datetime.utcnow()
        return existing.to_dict()

    def resolve_create_alert(self, args: Dict[str, Any]) -> Dict[str, Any]:
        import uuid
        alert = {
            "id": str(uuid.uuid4()),
            "title": args["title"],
            "severity": args["severity"],
            "description": args.get("description", ""),
            "source": "graphql",
            "resolved": False,
            "createdAt": datetime.utcnow().isoformat(),
            "resolvedAt": None,
        }
        self._alerts.append(alert)
        return alert

    def resolve_resolve_alert(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        alert_id = args.get("id")
        for alert in self._alerts:
            if alert["id"] == alert_id:
                alert["resolved"] = True
                alert["resolvedAt"] = datetime.utcnow().isoformat()
                return alert
        return None

    def resolve_record_metric(self, args: Dict[str, Any]) -> bool:
        name = args.get("name")
        value = args.get("value")
        if not name or value is None:
            return False
        self._metrics_data[name].append(float(value))
        return True

    def subscribe_validation_events(self, args: Dict[str, Any]) -> str:
        return "Subscription to validation events"

    def subscribe_alert_events(self, args: Dict[str, Any]) -> str:
        return "Subscription to alert events"

    def subscribe_rule_events(self, args: Dict[str, Any]) -> str:
        return "Subscription to rule events"

    def subscribe_metrics_events(self, args: Dict[str, Any]) -> str:
        return "Subscription to metrics events"


class GraphQLQueryParser:
    """Minimal GraphQL query parser."""

    def parse(self, query: str) -> Dict[str, Any]:
        return {"operation": "unknown", "fields": []}

    def extract_operation_type(self, query: str) -> str:
        query_stripped = query.strip()
        if query_stripped.startswith("subscription"):
            return "subscription"
        elif query_stripped.startswith("mutation"):
            return "mutation"
        return "query"

    def extract_operation_name(self, query: str) -> Optional[str]:
        import re
        match = re.search(r"(query|mutation|subscription)\s+(\w+)", query.strip())
        if match:
            return match.group(2)
        return None


class GraphQLResponseFormatter:
    """Formats GraphQL responses with error handling."""

    @staticmethod
    def format_success(data: Dict[str, Any]) -> GraphQLResponse:
        return GraphQLResponse(data=data)

    @staticmethod
    def format_error(message: str, path: Optional[List[str]] = None,
                     locations: Optional[List[Dict[str, int]]] = None) -> GraphQLResponse:
        return GraphQLResponse(
            errors=[GraphQLError(message=message, path=path, locations=locations)]
        )

    @staticmethod
    def format_validation_error(errors: List[str]) -> GraphQLResponse:
        return GraphQLResponse(
            errors=[GraphQLError(message=e, extensions={"code": "VALIDATION_ERROR"}) for e in errors]
        )

    @staticmethod
    def format_not_found(resource: str) -> GraphQLResponse:
        return GraphQLResponse(
            errors=[GraphQLError(
                message=f"{resource} not found",
                extensions={"code": "NOT_FOUND"}
            )]
        )

    @staticmethod
    def format_internal_error(error: Exception) -> GraphQLResponse:
        return GraphQLResponse(
            errors=[GraphQLError(
                message="Internal server error",
                extensions={"code": "INTERNAL_ERROR", "detail": str(error)}
            )]
        )


class GraphQLHandler:
    """
    GraphQL handler providing schema definitions, query resolvers,
    mutation resolvers, and subscription resolvers for rules,
    validations, metrics, and system operations.
    """

    def __init__(self) -> None:
        self._schema_builder = GraphQLSchemaBuilder()
        self._schema = self._schema_builder.build()
        self._resolver = GraphQLResolver()
        self._formatter = GraphQLResponseFormatter()
        self._parser = GraphQLQueryParser()
        self._subscriptions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    @property
    def schema(self) -> GraphQLSchema:
        return self._schema

    def get_schema_sdl(self) -> str:
        lines = [f'""" {self._schema.description} """']
        for type_name, type_def in self._schema.types.items():
            if type_def.kind == GraphQLTypeKind.SCALAR:
                continue
            if type_def.kind == GraphQLTypeKind.ENUM:
                lines.append(f"enum {type_name} {{")
                for val in type_def.enum_values:
                    lines.append(f"  {val}")
                lines.append("}")
            elif type_def.kind == GraphQLTypeKind.INPUT_OBJECT:
                lines.append(f"input {type_name} {{")
                for field in type_def.fields:
                    req = "!" if field.is_required else ""
                    list_wrap = "[]" if field.is_list else ""
                    lines.append(f"  {field.name}: {field.type_name}{list_wrap}{req}")
                lines.append("}")
            elif type_def.kind == GraphQLTypeKind.OBJECT:
                lines.append(f"type {type_name} {{")
                for field in type_def.fields:
                    req = "!" if field.is_required else ""
                    list_wrap = "[]" if field.is_list else ""
                    lines.append(f"  {field.name}: {field.type_name}{list_wrap}{req}")
                lines.append("}")
        return "\n".join(lines)

    def execute_query(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            query = request_data.get("query", "")
            variables = request_data.get("variables", {})
            operation_name = request_data.get("operationName")

            if not query or not query.strip():
                response = self._formatter.format_error("No query provided")
                return response.to_dict()

            operation_type = self._parser.extract_operation_type(query)
            parsed = self._parser.parse(query)

            if operation_type == "mutation":
                result = self._execute_mutation(query, variables)
            elif operation_type == "subscription":
                result = self._execute_subscription(query, variables)
            else:
                result = self._execute_query(query, variables)

            if isinstance(result, GraphQLResponse):
                return result.to_dict()
            return result

        except Exception as e:
            logger.error(f"GraphQL execution error: {e}\n{traceback.format_exc()}")
            response = self._formatter.format_internal_error(e)
            return response.to_dict()

    def _execute_query(self, query: str, variables: Dict[str, Any]) -> GraphQLResponse:
        import re
        data: Dict[str, Any] = {}

        if "rules" in query and "ruleStats" not in query:
            filter_args = variables.get("filter", {})
            page = variables.get("page", 1)
            per_page = variables.get("perPage", 20)
            result = self._resolver.resolve_rules({
                "filter": filter_args,
                "page": page,
                "perPage": per_page,
            })
            data["rules"] = result

        if re.search(r'\brule\b', query) and "rules" not in query.lower():
            rule_id = variables.get("id")
            if rule_id:
                result = self._resolver.resolve_rule({"id": rule_id})
                if result is None:
                    return self._formatter.format_not_found(f"Rule {rule_id}")
                data["rule"] = result

        if "validationResult" in query:
            request_id = variables.get("requestId")
            if request_id:
                result = self._resolver.resolve_validation_result({"requestId": request_id})
                if result is None:
                    return self._formatter.format_not_found(f"ValidationResult {request_id}")
                data["validationResult"] = result

        if "violations" in query:
            request_id = variables.get("requestId")
            if request_id:
                data["violations"] = self._resolver.resolve_violations({"requestId": request_id})

        if "ruleStats" in query:
            data["ruleStats"] = self._resolver.resolve_rule_stats({})

        if "validationStats" in query:
            data["validationStats"] = self._resolver.resolve_validation_stats({})

        if "alerts" in query:
            data["alerts"] = self._resolver.resolve_alerts({
                "severity": variables.get("severity"),
                "resolved": variables.get("resolved"),
                "page": variables.get("page", 1),
                "perPage": variables.get("perPage", 20),
            })

        if "systemHealth" in query:
            data["systemHealth"] = self._resolver.resolve_system_health({})

        if "schema" in query.lower():
            data["schema"] = self.get_schema_sdl()

        if not data:
            return self._formatter.format_error("Could not resolve query fields")

        return self._formatter.format_success(data)

    def _execute_mutation(self, query: str, variables: Dict[str, Any]) -> GraphQLResponse:
        data: Dict[str, Any] = {}

        if "createRule" in query:
            input_data = variables.get("input", {})
            if not input_data:
                return self._formatter.format_validation_error(["Missing input for createRule"])
            required = ["name", "description", "tier", "ruleType", "severity"]
            missing = [r for r in required if r not in input_data]
            if missing:
                return self._formatter.format_validation_error([f"Missing required field: {m}" for m in missing])
            data["createRule"] = self._resolver.resolve_create_rule({"input": input_data})

        if "updateRule" in query:
            rule_id = variables.get("id")
            input_data = variables.get("input", {})
            if not rule_id:
                return self._formatter.format_validation_error(["Missing id for updateRule"])
            result = self._resolver.resolve_update_rule({"id": rule_id, "input": input_data})
            if result is None:
                return self._formatter.format_not_found(f"Rule {rule_id}")
            data["updateRule"] = result

        if "deleteRule" in query:
            rule_id = variables.get("id")
            if not rule_id:
                return self._formatter.format_validation_error(["Missing id for deleteRule"])
            success = self._resolver.resolve_delete_rule({"id": rule_id})
            if not success:
                return self._formatter.format_not_found(f"Rule {rule_id}")
            data["deleteRule"] = True

        if "validate" in query:
            input_data = variables.get("input", {})
            if not input_data or "content" not in input_data:
                return self._formatter.format_validation_error(["Missing content for validate"])
            data["validate"] = self._resolver.resolve_validate({"input": input_data})

        if "toggleRuleStatus" in query:
            rule_id = variables.get("id")
            status = variables.get("status")
            if not rule_id or not status:
                return self._formatter.format_validation_error(["Missing id or status for toggleRuleStatus"])
            result = self._resolver.resolve_toggle_rule_status({"id": rule_id, "status": status})
            if result is None:
                return self._formatter.format_not_found(f"Rule {rule_id}")
            data["toggleRuleStatus"] = result

        if "createAlert" in query:
            title = variables.get("title")
            severity = variables.get("severity")
            if not title or not severity:
                return self._formatter.format_validation_error(["Missing title or severity for createAlert"])
            data["createAlert"] = self._resolver.resolve_create_alert({
                "title": title,
                "severity": severity,
                "description": variables.get("description", ""),
            })

        if "resolveAlert" in query:
            alert_id = variables.get("id")
            if not alert_id:
                return self._formatter.format_validation_error(["Missing id for resolveAlert"])
            result = self._resolver.resolve_resolve_alert({"id": alert_id})
            if result is None:
                return self._formatter.format_not_found(f"Alert {alert_id}")
            data["resolveAlert"] = result

        if "recordMetric" in query:
            name = variables.get("name")
            value = variables.get("value")
            if not name or value is None:
                return self._formatter.format_validation_error(["Missing name or value for recordMetric"])
            data["recordMetric"] = self._resolver.resolve_record_metric({"name": name, "value": value})

        if not data:
            return self._formatter.format_error("Could not resolve mutation fields")

        return self._formatter.format_success(data)

    def _execute_subscription(self, query: str, variables: Dict[str, Any]) -> GraphQLResponse:
        sub_id = hashlib.md5(query.encode()).hexdigest()[:16]
        subscription = {
            "subscription_id": sub_id,
            "query": query,
            "variables": variables,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._subscriptions[sub_id].append(subscription)

        data: Dict[str, Any] = {}
        if "validationEvents" in query:
            data["validationEvents"] = self._resolver.subscribe_validation_events(variables)
        if "alertEvents" in query:
            data["alertEvents"] = self._resolver.subscribe_alert_events(variables)
        if "ruleEvents" in query:
            data["ruleEvents"] = self._resolver.subscribe_rule_events(variables)
        if "metricsEvents" in query:
            data["metricsEvents"] = self._resolver.subscribe_metrics_events(variables)

        return self._formatter.format_success({
            "subscription_id": sub_id,
            "data": data,
        })

    def get_type_definitions(self) -> Dict[str, GraphQLType]:
        return dict(self._schema.types)

    def get_query_fields(self) -> List[str]:
        query_type = self._schema.get_type("Query")
        if query_type:
            return [f.name for f in query_type.fields]
        return []

    def get_mutation_fields(self) -> List[str]:
        mutation_type = self._schema.get_type("Mutation")
        if mutation_type:
            return [f.name for f in mutation_type.fields]
        return []

    def get_subscription_fields(self) -> List[str]:
        sub_type = self._schema.get_type("Subscription")
        if sub_type:
            return [f.name for f in sub_type.fields]
        return []

    def clear_data(self) -> None:
        self._resolver = GraphQLResolver()
        self._subscriptions.clear()
