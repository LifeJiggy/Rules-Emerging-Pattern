"""
Core data models for the Rules-Emerging-Pattern system.
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator
import hashlib


class RuleTier(str, Enum):
    """Rule tier levels in the three-tier architecture."""
    SAFETY = "safety"  # Tier 1: Non-negotiable rules
    OPERATIONAL = "operational"  # Tier 2: High-priority rules
    PREFERENCE = "preference"  # Tier 3: User-customizable rules


class EnforcementLevel(str, Enum):
    """Levels of rule enforcement."""
    STRICT = "strict"  # Automatic blocking, no override
    ADVISORY = "advisory"  # Warning with override option
    ADAPTIVE = "adaptive"  # Context-aware, learning-based
    FALLBACK = "fallback"  # Default when other methods fail


class RuleType(str, Enum):
    """Types of rules in the system."""
    CONTENT_FILTERING = "content_filtering"
    PATTERN_MATCHING = "pattern_matching"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    STRUCTURAL_VALIDATION = "structural_validation"
    COMPLIANCE_CHECK = "compliance_check"
    QUALITY_ASSESSMENT = "quality_assessment"
    CUSTOM = "custom"


class RuleSeverity(str, Enum):
    """Severity levels for rule violations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleStatus(str, Enum):
    """Status of a rule in the system."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    TESTING = "testing"


class RulePattern(BaseModel):
    """Pattern definition for rule matching."""
    type: RuleType
    keywords: List[str] = Field(default_factory=list)
    regex_patterns: List[str] = Field(default_factory=list)
    ml_model: Optional[str] = None
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    action: str = Field(default="warn")
    
    class Config:
        use_enum_values = True


class Rule(BaseModel):
    """Core rule definition."""
    
    # Basic rule properties
    id: str
    name: str
    description: str
    tier: RuleTier
    rule_type: RuleType
    severity: RuleSeverity
    status: RuleStatus = RuleStatus.ACTIVE
    
    # Rule definition
    patterns: List[RulePattern] = Field(default_factory=list)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    exceptions: List[str] = Field(default_factory=list)
    
    # Enforcement configuration
    enforcement_level: EnforcementLevel
    auto_block: bool = False
    user_override: bool = True
    override_justification_required: bool = False
    
    # Metadata
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    
    # Performance and optimization
    priority: int = Field(default=100, ge=1, le=1000)
    timeout_ms: int = Field(default=1000, ge=1, le=10000)
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    
    @validator('id')
    def validate_id(cls, v):
        """Validate rule ID format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Rule ID cannot be empty")
        return v.strip()
    
    def get_content_hash(self) -> str:
        """Generate hash of rule content for integrity checking."""
        content = f"{self.name}:{self.description}:{self.tier}:{self.version}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def is_applicable_to_context(self, context: Dict[str, Any]) -> bool:
        """Check if rule is applicable given the context."""
        # Basic context applicability check
        if not context:
            return True
        
        # Check domain-specific applicability
        if 'domain' in context:
            rule_domains = [tag for tag in self.tags if tag.startswith('domain:')]
            if rule_domains and not any(tag.split(':', 1)[1] == context['domain'] for tag in rule_domains):
                return False
        
        # Check user role applicability
        if 'user_role' in context:
            rule_roles = [tag for tag in self.tags if tag.startswith('role:')]
            if rule_roles and not any(tag.split(':', 1)[1] in context['user_role'] for tag in rule_roles):
                return False
        
        return True
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleSet(BaseModel):
    """Collection of related rules."""
    
    id: str
    name: str
    description: str
    rules: List[Rule] = Field(default_factory=list)
    tier: RuleTier
    status: RuleStatus = RuleStatus.ACTIVE
    
    # Metadata
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    
    # Configuration
    auto_discovery: bool = True
    conflict_resolution: str = "priority_based"
    evaluation_order: str = "priority_desc"  # priority_desc, priority_asc, custom
    
    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the rule set."""
        if rule not in self.rules:
            self.rules.append(rule)
            self.updated_at = datetime.utcnow()
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule from the rule set by ID."""
        original_count = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.id != rule_id]
        if len(self.rules) < original_count:
            self.updated_at = datetime.utcnow()
            return True
        return False
    
    def get_rule_by_id(self, rule_id: str) -> Optional[Rule]:
        """Get a rule by its ID."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None
    
    def get_rules_by_type(self, rule_type: RuleType) -> List[Rule]:
        """Get all rules of a specific type."""
        return [rule for rule in self.rules if rule.rule_type == rule_type]
    
    def get_active_rules(self) -> List[Rule]:
        """Get all active rules in the set."""
        return [rule for rule in self.rules if rule.status == RuleStatus.ACTIVE]
    
    def get_rules_by_priority(self, ascending: bool = False) -> List[Rule]:
        """Get rules sorted by priority."""
        return sorted(self.rules, key=lambda r: r.priority, reverse=not ascending)
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleContext(BaseModel):
    """Context information for rule evaluation."""
    
    # Basic context
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    domain: Optional[str] = None
    user_role: Optional[str] = None
    
    # Content context
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    language: Optional[str] = None
    
    # Business context
    organization: Optional[str] = None
    project: Optional[str] = None
    business_process: Optional[str] = None
    
    # Temporal context
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    time_zone: Optional[str] = None
    
    # Additional context data
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def get_effective_context(self) -> Dict[str, Any]:
        """Get context as a flat dictionary for processing."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "domain": self.domain,
            "user_role": self.user_role,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "language": self.language,
            "organization": self.organization,
            "project": self.project,
            "business_process": self.business_process,
            "timestamp": self.timestamp,
            "time_zone": self.time_zone,
            **self.metadata
        }
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleEvaluationRequest(BaseModel):
    """Request for rule evaluation."""
    
    content: str
    context: Optional[RuleContext] = None
    rule_ids: Optional[List[str]] = None  # Specific rules to evaluate
    tier: Optional[RuleTier] = None  # Evaluate all rules in tier
    rule_types: Optional[List[RuleType]] = None  # Specific rule types
    options: Dict[str, Any] = Field(default_factory=dict)
    
    # Performance options
    timeout_ms: int = Field(default=1000, ge=1, le=10000)
    parallel_evaluation: bool = True
    early_termination: bool = True  # Stop on first critical violation
    
    def get_context(self) -> RuleContext:
        """Get the context for evaluation."""
        return self.context or RuleContext()
    
    class Config:
        use_enum_values = True