"""
Base rule manager for the Rules-Emerging-Pattern system.
"""

import os
import yaml
import json
import asyncio
from typing import List, Dict, Any, Optional, Union, Set
from pathlib import Path
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import hashlib

from rules_emerging_pattern.models.rule import Rule, RuleSet, RuleTier, RuleType, RuleStatus, RuleContext, RuleEvaluationRequest, EnforcementLevel, RuleSeverity
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType, ConflictResolution, ResolutionStrategy

logger = logging.getLogger(__name__)


class RuleParser:
    """Parser for loading rules from various formats."""
    
    def __init__(self):
        self.supported_formats = {'.yaml', '.yml', '.json'}
    
    def parse_file(self, file_path: Union[str, Path]) -> List[Rule]:
        """Parse rules from a file."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Rule file not found: {file_path}")
        
        if file_path.suffix.lower() not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {file_path.suffix}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix.lower() in {'.yaml', '.yml'}:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        return self._parse_rule_data(data, source=str(file_path))
    
    def parse_directory(self, directory: Union[str, Path]) -> List[Rule]:
        """Parse all rule files from a directory."""
        directory = Path(directory)
        rules = []
        
        if not directory.exists():
            logger.warning(f"Rule directory not found: {directory}")
            return rules
        
        for file_path in directory.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in self.supported_formats:
                try:
                    file_rules = self.parse_file(file_path)
                    rules.extend(file_rules)
                    logger.info(f"Loaded {len(file_rules)} rules from {file_path}")
                except Exception as e:
                    logger.error(f"Failed to parse {file_path}: {e}")
        
        return rules
    
    def _parse_rule_data(self, data: Dict[str, Any], source: str) -> List[Rule]:
        """Parse rule data from loaded content."""
        rules = []
        
        if 'rules' in data:
            # Multiple rules
            for rule_data in data['rules'].values():
                if isinstance(rule_data, dict):
                    rule = self._create_rule(rule_data, source)
                    if rule:
                        rules.append(rule)
        elif 'rule' in data:
            # Single rule
            rule = self._create_rule(data['rule'], source)
            if rule:
                rules.append(rule)
        else:
            # Assume the data itself is a rule
            rule = self._create_rule(data, source)
            if rule:
                rules.append(rule)
        
        return rules
    
    def _create_rule(self, data: Dict[str, Any], source: str) -> Optional[Rule]:
        """Create a Rule object from parsed data."""
        try:
            # Ensure required fields
            if 'id' not in data or 'name' not in data:
                logger.warning(f"Rule missing required fields in {source}")
                return None
            
            # Parse patterns
            patterns = []
            if 'patterns' in data:
                for pattern_data in data['patterns']:
                    patterns.append(self._parse_pattern(pattern_data))
            
            # Create rule object
            rule = Rule(
                id=data['id'],
                name=data['name'],
                description=data.get('description', ''),
                tier=RuleTier(data.get('tier', 'preference')),
                rule_type=RuleType(data.get('type', 'custom')),
                severity=RuleSeverity(data.get('severity', 'medium')),
                patterns=patterns,
                enforcement_level=EnforcementLevel(data.get('enforcement', 'advisory')),
                conditions=data.get('conditions', {}),
                exceptions=data.get('exceptions', []),
                auto_block=data.get('auto_block', False),
                user_override=data.get('user_override', True),
                override_justification_required=data.get('override_justification_required', False),
                priority=data.get('priority', 100),
                timeout_ms=data.get('timeout_ms', 1000),
                tags=data.get('tags', []),
                created_by=data.get('created_by'),
                version=data.get('version', '1.0.0')
            )
            
            return rule
            
        except Exception as e:
            logger.error(f"Failed to create rule from {source}: {e}")
            return None
    
    def _parse_pattern(self, pattern_data: Dict[str, Any]) -> Any:
        """Parse rule pattern data."""
        # This will be implemented with proper pattern classes later
        return pattern_data


class RuleValidator:
    """Validator for rule definitions and configurations."""
    
    def __init__(self):
        self.validation_rules = self._load_validation_rules()
    
    def validate_rule(self, rule: Rule) -> List[str]:
        """Validate a single rule."""
        errors = []
        
        # Basic validation
        if not rule.id or not rule.id.strip():
            errors.append("Rule ID is required")
        
        if not rule.name or not rule.name.strip():
            errors.append("Rule name is required")
        
        if not rule.description or not rule.description.strip():
            errors.append("Rule description is required")
        
        # Tier-specific validation
        if rule.tier == RuleTier.SAFETY and rule.enforcement_level != EnforcementLevel.STRICT:
            errors.append("Safety rules must use strict enforcement")
        
        if rule.tier == RuleTier.SAFETY and rule.user_override:
            errors.append("Safety rules cannot allow user override")
        
        # Pattern validation
        if not rule.patterns:
            errors.append("Rule must have at least one pattern")
        
        # Priority validation
        if not (1 <= rule.priority <= 1000):
            errors.append("Rule priority must be between 1 and 1000")
        
        # Timeout validation
        if not (1 <= rule.timeout_ms <= 10000):
            errors.append("Rule timeout must be between 1 and 10000 ms")
        
        return errors
    
    def validate_rule_set(self, rule_set: RuleSet) -> List[str]:
        """Validate a rule set."""
        errors = []
        
        # Validate individual rules
        for rule in rule_set.rules:
            rule_errors = self.validate_rule(rule)
            if rule_errors:
                errors.extend([f"Rule {rule.id}: {error}" for error in rule_errors])
        
        # Check for duplicate rule IDs
        rule_ids = [rule.id for rule in rule_set.rules]
        duplicate_ids = set([rid for rid in rule_ids if rule_ids.count(rid) > 1])
        if duplicate_ids:
            errors.append(f"Duplicate rule IDs: {', '.join(duplicate_ids)}")
        
        # Validate rule set configuration
        if not rule_set.id or not rule_set.id.strip():
            errors.append("Rule set ID is required")
        
        if not rule_set.name or not rule_set.name.strip():
            errors.append("Rule set name is required")
        
        return errors
    
    def _load_validation_rules(self) -> Dict[str, Any]:
        """Load validation rules configuration."""
        # This would load from config files in a real implementation
        return {}


class BaseRuleManager:
    """Base rule manager with core functionality."""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self.config_path = config_path
        self.parser = RuleParser()
        self.validator = RuleValidator()
        
        # Rule storage
        self.rules: Dict[str, Rule] = {}
        self.rule_sets: Dict[str, RuleSet] = {}
        self.rules_by_tier: Dict[RuleTier, List[Rule]] = defaultdict(list)
        self.rules_by_type: Dict[RuleType, List[Rule]] = defaultdict(list)
        
        # Performance tracking
        self.load_time: Optional[datetime] = None
        self.rule_count: int = 0
        self.validation_errors: List[str] = []
        
        # Caching
        self._rule_cache: Dict[str, Rule] = {}
        self._cache_ttl: int = 300  # 5 minutes
        self._cache_timestamp: Dict[str, datetime] = {}
        
        logger.info("BaseRuleManager initialized")
    
    async def load_rules_from_directory(self, directory: Union[str, Path]) -> int:
        """Load all rules from a directory."""
        directory = Path(directory)
        
        if not directory.exists():
            raise FileNotFoundError(f"Rules directory not found: {directory}")
        
        start_time = datetime.utcnow()
        
        # Parse all rule files
        rules = self.parser.parse_directory(directory)
        
        # Validate and add rules
        loaded_count = 0
        for rule in rules:
            validation_errors = self.validator.validate_rule(rule)
            if validation_errors:
                self.validation_errors.extend([
                    f"Rule {rule.id}: {error}" for error in validation_errors
                ])
                logger.warning(f"Skipping invalid rule {rule.id}: {validation_errors}")
                continue
            
            await self.add_rule(rule)
            loaded_count += 1
        
        self.load_time = datetime.utcnow()
        load_duration = (self.load_time - start_time).total_seconds()
        
        logger.info(f"Loaded {loaded_count} rules from {directory} in {load_duration:.2f}s")
        
        return loaded_count
    
    async def add_rule(self, rule: Rule) -> None:
        """Add a single rule to the manager."""
        # Validate rule
        errors = self.validator.validate_rule(rule)
        if errors:
            raise ValueError(f"Invalid rule: {', '.join(errors)}")
        
        # Check for existing rule
        if rule.id in self.rules:
            logger.warning(f"Rule {rule.id} already exists, updating")
        
        # Add to storage
        self.rules[rule.id] = rule
        
        # Update indexes
        self.rules_by_tier[rule.tier].append(rule)
        self.rules_by_type[rule.rule_type].append(rule)
        
        # Update cache
        self._update_cache(rule)
        
        self.rule_count = len(self.rules)
        
        logger.debug(f"Added rule {rule.id} ({rule.tier} tier)")
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        
        # Remove from storage
        del self.rules[rule_id]
        
        # Update indexes
        if rule in self.rules_by_tier[rule.tier]:
            self.rules_by_tier[rule.tier].remove(rule)
        
        if rule in self.rules_by_type[rule.rule_type]:
            self.rules_by_type[rule.rule_type].remove(rule)
        
        # Remove from cache
        self._rule_cache.pop(rule_id, None)
        self._cache_timestamp.pop(rule_id, None)
        
        self.rule_count = len(self.rules)
        
        logger.debug(f"Removed rule {rule_id}")
        return True
    
    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a rule by ID with caching."""
        # Check cache first
        if rule_id in self._rule_cache:
            if self._is_cache_valid(rule_id):
                return self._rule_cache[rule_id]
            else:
                # Cache expired
                self._rule_cache.pop(rule_id, None)
                self._cache_timestamp.pop(rule_id, None)
        
        # Get from storage
        rule = self.rules.get(rule_id)
        
        # Update cache
        if rule:
            self._update_cache(rule)
        
        return rule
    
    def get_rules_by_tier(self, tier: RuleTier) -> List[Rule]:
        """Get all rules in a specific tier."""
        return list(self.rules_by_tier.get(tier, []))
    
    def get_rules_by_type(self, rule_type: RuleType) -> List[Rule]:
        """Get all rules of a specific type."""
        return list(self.rules_by_type.get(rule_type, []))
    
    def get_active_rules(self) -> List[Rule]:
        """Get all active rules."""
        return [rule for rule in self.rules.values() if rule.status == RuleStatus.ACTIVE]
    
    def get_applicable_rules(self, context: Optional[RuleContext] = None) -> List[Rule]:
        """Get rules applicable to given context."""
        active_rules = self.get_active_rules()
        
        if not context:
            return active_rules
        
        # Filter by context
        applicable_rules = []
        for rule in active_rules:
            if rule.is_applicable_to_context(context.get_effective_context()):
                applicable_rules.append(rule)
        
        return applicable_rules
    
    def create_rule_set(self, rule_set_id: str, name: str, description: str, 
                       rule_ids: List[str], tier: RuleTier) -> RuleSet:
        """Create a rule set from existing rules."""
        # Get rules
        rules = []
        missing_rules = []
        
        for rule_id in rule_ids:
            rule = self.get_rule(rule_id)
            if rule:
                rules.append(rule)
            else:
                missing_rules.append(rule_id)
        
        if missing_rules:
            raise ValueError(f"Rules not found: {', '.join(missing_rules)}")
        
        # Create rule set
        rule_set = RuleSet(
            id=rule_set_id,
            name=name,
            description=description,
            rules=rules,
            tier=tier
        )
        
        # Validate rule set
        errors = self.validator.validate_rule_set(rule_set)
        if errors:
            raise ValueError(f"Invalid rule set: {', '.join(errors)}")
        
        # Store rule set
        self.rule_sets[rule_set_id] = rule_set
        
        logger.info(f"Created rule set {rule_set_id} with {len(rules)} rules")
        
        return rule_set
    
    def get_rule_set(self, rule_set_id: str) -> Optional[RuleSet]:
        """Get a rule set by ID."""
        return self.rule_sets.get(rule_set_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "total_rules": self.rule_count,
            "rules_by_tier": {
                tier.value: len(rules) for tier, rules in self.rules_by_tier.items()
            },
            "rules_by_type": {
                rule_type.value: len(rules) for rule_type, rules in self.rules_by_type.items()
            },
            "active_rules": len(self.get_active_rules()),
            "rule_sets": len(self.rule_sets),
            "validation_errors": len(self.validation_errors),
            "load_time": self.load_time.isoformat() if self.load_time else None,
            "cache_hit_rate": self._get_cache_hit_rate()
        }
    
    def export_rules(self, format: str = "json", include_inactive: bool = False) -> str:
        """Export rules in specified format."""
        rules_to_export = []
        
        for rule in self.rules.values():
            if include_inactive or rule.status == RuleStatus.ACTIVE:
                rules_to_export.append(rule.dict())
        
        if format.lower() == "json":
            return json.dumps({"rules": rules_to_export}, indent=2)
        elif format.lower() in ["yaml", "yml"]:
            return yaml.dump({"rules": rules_to_export}, default_flow_style=False)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _update_cache(self, rule: Rule) -> None:
        """Update rule cache."""
        self._rule_cache[rule.id] = rule
        self._cache_timestamp[rule.id] = datetime.utcnow()
    
    def _is_cache_valid(self, rule_id: str) -> bool:
        """Check if cache entry is still valid."""
        if rule_id not in self._cache_timestamp:
            return False
        
        age = datetime.utcnow() - self._cache_timestamp[rule_id]
        return age.total_seconds() < self._cache_ttl
    
    def _get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate (simplified)."""
        # This would require proper cache tracking in a real implementation
        return 0.0
    
    async def reload_rules(self) -> int:
        """Reload rules from configured directories."""
        if not self.config_path:
            raise ValueError("No config path configured for reload")
        
        # Clear existing rules
        self.rules.clear()
        self.rule_sets.clear()
        self.rules_by_tier.clear()
        self.rules_by_type.clear()
        self._rule_cache.clear()
        self._cache_timestamp.clear()
        self.validation_errors.clear()
        
        # Reload from directory
        return await self.load_rules_from_directory(self.config_path)