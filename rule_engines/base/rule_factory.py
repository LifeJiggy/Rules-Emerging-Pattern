"""Rule factory - creates rule instances from templates, schemas, and configuration."""
import logging
import uuid
from typing import List, Dict, Any, Optional, Type
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class RuleFactorySource(str, Enum):
    TEMPLATE = "template"
    SCHEMA = "schema"
    MANUAL = "manual"
    IMPORT = "import"
    DEFAULT = "default"


@dataclass
class RuleCreationResult:
    rule_id: str
    rule_data: Dict[str, Any]
    source: RuleFactorySource
    template_name: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


DEFAULT_SAFETY_RULES = [
    {
        "id": "safety_block_harmful",
        "name": "Block Harmful Content",
        "description": "Block content containing harmful instructions or dangerous information",
        "tier": "safety", "patterns": ["harmful", "dangerous", "weapon", "explosive"],
        "enforcement": "strict", "severity": "critical", "priority": 1,
        "auto_block": True, "user_override": False,
    },
    {
        "id": "safety_block_hate",
        "name": "Block Hate Speech",
        "description": "Block hate speech and discriminatory content",
        "tier": "safety", "patterns": ["hate", "discriminat", "racial slur"],
        "enforcement": "strict", "severity": "critical", "priority": 2,
        "auto_block": True, "user_override": False,
    },
    {
        "id": "safety_protect_privacy",
        "name": "Protect Personal Data",
        "description": "Block exposure of personal identifiable information",
        "tier": "safety", "patterns": ["ssn", "credit card", "password"],
        "enforcement": "strict", "severity": "high", "priority": 3,
        "auto_block": True, "user_override": False,
    },
]

DEFAULT_OPERATIONAL_RULES = [
    {
        "id": "op_copyright",
        "name": "Copyright Compliance",
        "description": "Flag excessive quotation or copyrighted material",
        "tier": "operational", "patterns": ["copyright", "all rights reserved"],
        "enforcement": "advisory", "severity": "high", "priority": 50,
        "user_override": True,
    },
    {
        "id": "op_quality",
        "name": "Content Quality",
        "description": "Flag low-quality or poorly formatted content",
        "tier": "operational", "patterns": ["spam", "clickbait"],
        "enforcement": "advisory", "severity": "medium", "priority": 60,
        "user_override": True,
    },
]

DEFAULT_PREFERENCE_RULES = [
    {
        "id": "pref_tone",
        "name": "Tone Preference",
        "description": "Adjust content tone based on user preference",
        "tier": "preference", "patterns": ["professional", "casual"],
        "enforcement": "adaptive", "severity": "low", "priority": 100,
        "user_override": True,
    },
]


class RuleFactory:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._creation_count = 0
        logger.info("RuleFactory initialized")

    def create_from_template(self, template_name: str,
                             overrides: Dict[str, Any]) -> RuleCreationResult:
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")
        rule_data = dict(template)
        rule_data.update(overrides)
        if "id" not in rule_data:
            rule_data["id"] = f"rule_{uuid.uuid4().hex[:8]}"
        self._creation_count += 1
        warnings = self._check_warnings(rule_data)
        return RuleCreationResult(
            rule_id=rule_data["id"],
            rule_data=rule_data,
            source=RuleFactorySource.TEMPLATE,
            template_name=template_name,
            warnings=warnings,
        )

    def create_manual(self, name: str, tier: str, patterns: List[str],
                      enforcement: str = "advisory",
                      **kwargs: Any) -> RuleCreationResult:
        rule_id = kwargs.pop("id", f"rule_{uuid.uuid4().hex[:8]}")
        rule_data = {
            "id": rule_id,
            "name": name,
            "description": kwargs.pop("description", f"Manual rule: {name}"),
            "tier": tier,
            "patterns": patterns,
            "enforcement": enforcement,
            "severity": kwargs.pop("severity", "medium"),
            "priority": kwargs.pop("priority", 100),
            "tags": kwargs.pop("tags", []),
            "user_override": kwargs.pop("user_override", True),
            "auto_block": kwargs.pop("auto_block", False),
            "conditions": kwargs.pop("conditions", {}),
            "timeout_ms": kwargs.pop("timeout_ms", 1000),
        }
        rule_data.update(kwargs)
        self._creation_count += 1
        return RuleCreationResult(
            rule_id=rule_id, rule_data=rule_data,
            source=RuleFactorySource.MANUAL,
        )

    def create_default_safety(self) -> List[RuleCreationResult]:
        return self._create_defaults(DEFAULT_SAFETY_RULES, "default_safety")

    def create_default_operational(self) -> List[RuleCreationResult]:
        return self._create_defaults(DEFAULT_OPERATIONAL_RULES, "default_operational")

    def create_default_preference(self) -> List[RuleCreationResult]:
        return self._create_defaults(DEFAULT_PREFERENCE_RULES, "default_preference")

    def create_all_defaults(self) -> Dict[str, List[RuleCreationResult]]:
        return {
            "safety": self.create_default_safety(),
            "operational": self.create_default_operational(),
            "preference": self.create_default_preference(),
        }

    def register_template(self, name: str, template: Dict[str, Any]) -> None:
        self._templates[name] = template.copy()
        logger.info("Registered template: %s", name)

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        return self._templates.get(name)

    def list_templates(self) -> List[str]:
        return list(self._templates.keys())

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_created": self._creation_count,
            "registered_templates": len(self._templates),
        }

    def _create_defaults(self, defaults: List[Dict[str, Any]],
                         source: str) -> List[RuleCreationResult]:
        results = []
        for rule_def in defaults:
            result = self.create_manual(
                name=rule_def["name"],
                tier=rule_def["tier"],
                patterns=rule_def["patterns"],
                enforcement=rule_def["enforcement"],
                id=rule_def["id"],
                description=rule_def["description"],
                severity=rule_def.get("severity", "medium"),
                priority=rule_def.get("priority", 100),
                auto_block=rule_def.get("auto_block", False),
                user_override=rule_def.get("user_override", True),
            )
            results.append(result)
        logger.info("Created %d default rules from %s", len(results), source)
        return results

    def _check_warnings(self, rule: Dict[str, Any]) -> List[str]:
        warnings = []
        tier = rule.get("tier", "preference")
        enforcement = rule.get("enforcement", "advisory")
        if tier == "safety" and enforcement != "strict":
            warnings.append("Safety rule should use 'strict' enforcement")
        if tier == "safety" and rule.get("user_override", True):
            warnings.append("Safety rule should not allow user override")
        if not rule.get("patterns"):
            warnings.append("Rule has no patterns defined")
        return warnings
