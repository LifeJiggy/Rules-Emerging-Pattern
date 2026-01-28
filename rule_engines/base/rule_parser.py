"""
Rule parser for loading and parsing rule definitions.
"""

import re
import json
import yaml
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import logging

from rules_emerging_pattern.models.rule import Rule, RulePattern, RuleTier, RuleType, RuleSeverity, RuleStatus, EnforcementLevel

logger = logging.getLogger(__name__)


class RulePatternParser:
    """Parser for rule patterns."""
    
    def __init__(self):
        self.compiled_patterns: Dict[str, re.Pattern] = {}
    
    def parse_pattern(self, pattern_data: Dict[str, Any]) -> RulePattern:
        """Parse a single rule pattern."""
        try:
            pattern = RulePattern(
                type=RuleType(pattern_data.get('type', 'custom')),
                keywords=pattern_data.get('keywords', []),
                regex_patterns=pattern_data.get('regex_patterns', []),
                ml_model=pattern_data.get('ml_model'),
                confidence_threshold=float(pattern_data.get('confidence_threshold', 0.7)),
                action=pattern_data.get('action', 'warn')
            )
            
            # Pre-compile regex patterns
            for regex_pattern in pattern.regex_patterns:
                try:
                    compiled = re.compile(regex_pattern, re.IGNORECASE | re.MULTILINE)
                    self.compiled_patterns[regex_pattern] = compiled
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{regex_pattern}': {e}")
            
            return pattern
            
        except Exception as e:
            logger.error(f"Failed to parse pattern: {e}")
            raise ValueError(f"Invalid pattern definition: {e}")
    
    def match_pattern(self, pattern: RulePattern, content: str) -> Dict[str, Any]:
        """Match a pattern against content."""
        matches = []
        confidence = 0.0
        
        # Keyword matching
        if pattern.keywords:
            keyword_matches = []
            for keyword in pattern.keywords:
                if keyword.lower() in content.lower():
                    keyword_matches.append({
                        'keyword': keyword,
                        'positions': self._find_positions(content, keyword.lower())
                    })
            
            if keyword_matches:
                matches.append({
                    'type': 'keyword',
                    'matches': keyword_matches
                })
                confidence += len(keyword_matches) / len(pattern.keywords) * 0.5
        
        # Regex matching
        if pattern.regex_patterns:
            regex_matches = []
            for regex_pattern in pattern.regex_patterns:
                if regex_pattern in self.compiled_patterns:
                    compiled = self.compiled_patterns[regex_pattern]
                    for match in compiled.finditer(content):
                        regex_matches.append({
                            'pattern': regex_pattern,
                            'match': match.group(),
                            'start': match.start(),
                            'end': match.end()
                        })
            
            if regex_matches:
                matches.append({
                    'type': 'regex',
                    'matches': regex_matches
                })
                confidence += len(regex_matches) / len(pattern.regex_patterns) * 0.5
        
        return {
            'matched': len(matches) > 0,
            'matches': matches,
            'confidence': min(confidence, 1.0)
        }
    
    def _find_positions(self, content: str, keyword: str) -> List[Dict[str, int]]:
        """Find all positions of a keyword in content."""
        positions = []
        start = 0
        
        while True:
            pos = content.lower().find(keyword, start)
            if pos == -1:
                break
            
            positions.append({
                'start': pos,
                'end': pos + len(keyword)
            })
            start = pos + 1
        
        return positions


class RuleFileParser:
    """Parser for rule files in various formats."""
    
    def __init__(self):
        self.pattern_parser = RulePatternParser()
        self.supported_extensions = {'.yaml', '.yml', '.json', '.md'}
    
    def parse_file(self, file_path: Union[str, Path]) -> List[Rule]:
        """Parse a rule file and return list of rules."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Rule file not found: {file_path}")
        
        if file_path.suffix.lower() not in self.supported_extensions:
            raise ValueError(f"Unsupported file format: {file_path.suffix}")
        
        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse based on file type
        if file_path.suffix.lower() in {'.yaml', '.yml'}:
            return self._parse_yaml(content, str(file_path))
        elif file_path.suffix.lower() == '.json':
            return self._parse_json(content, str(file_path))
        elif file_path.suffix.lower() == '.md':
            return self._parse_markdown(content, str(file_path))
        else:
            raise ValueError(f"Unsupported format: {file_path.suffix}")
    
    def parse_directory(self, directory: Union[str, Path], recursive: bool = True) -> List[Rule]:
        """Parse all rule files in a directory."""
        directory = Path(directory)
        all_rules = []
        
        if not directory.exists():
            logger.warning(f"Directory not found: {directory}")
            return all_rules
        
        # Find rule files
        pattern = "**/*" if recursive else "*"
        for file_path in directory.glob(pattern):
            if file_path.is_file() and file_path.suffix.lower() in self.supported_extensions:
                try:
                    rules = self.parse_file(file_path)
                    all_rules.extend(rules)
                    logger.info(f"Loaded {len(rules)} rules from {file_path}")
                except Exception as e:
                    logger.error(f"Failed to parse {file_path}: {e}")
        
        return all_rules
    
    def _parse_yaml(self, content: str, source: str) -> List[Rule]:
        """Parse YAML content."""
        try:
            data = yaml.safe_load(content)
            return self._extract_rules_from_data(data, source)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {source}: {e}")
    
    def _parse_json(self, content: str, source: str) -> List[Rule]:
        """Parse JSON content."""
        try:
            data = json.loads(content)
            return self._extract_rules_from_data(data, source)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {source}: {e}")
    
    def _parse_markdown(self, content: str, source: str) -> List[Rule]:
        """Parse Markdown content with frontmatter."""
        # Extract YAML frontmatter if present
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                yaml_content = parts[1]
                markdown_content = parts[2]
                
                try:
                    frontmatter = yaml.safe_load(yaml_content)
                    # Combine frontmatter with markdown content
                    frontmatter['description'] = markdown_content.strip()
                    return self._extract_rules_from_data({'rule': frontmatter}, source)
                except yaml.YAMLError as e:
                    logger.warning(f"Invalid frontmatter in {source}: {e}")
        
        # Treat as simple text description
        rule_data = {
            'id': self._generate_rule_id_from_path(source),
            'name': Path(source).stem,
            'description': content.strip(),
            'tier': 'preference',
            'type': 'custom',
            'severity': 'low'
        }
        
        return [self._create_rule_from_data(rule_data, source)]
    
    def _extract_rules_from_data(self, data: Dict[str, Any], source: str) -> List[Rule]:
        """Extract rules from parsed data."""
        rules = []
        
        # Handle different data structures
        if 'rules' in data and isinstance(data['rules'], dict):
            # Multiple rules in a dictionary
            for rule_key, rule_data in data['rules'].items():
                if isinstance(rule_data, dict):
                    rule_data['id'] = rule_data.get('id', rule_key)
                    rule = self._create_rule_from_data(rule_data, source)
                    if rule:
                        rules.append(rule)
        
        elif 'rules' in data and isinstance(data['rules'], list):
            # Multiple rules in a list
            for rule_data in data['rules']:
                if isinstance(rule_data, dict):
                    rule = self._create_rule_from_data(rule_data, source)
                    if rule:
                        rules.append(rule)
        
        elif 'rule' in data:
            # Single rule
            rule = self._create_rule_from_data(data['rule'], source)
            if rule:
                rules.append(rule)
        
        else:
            # Assume the data itself is a rule
            rule = self._create_rule_from_data(data, source)
            if rule:
                rules.append(rule)
        
        return rules
    
    def _create_rule_from_data(self, rule_data: Dict[str, Any], source: str) -> Optional[Rule]:
        """Create a Rule object from data."""
        try:
            # Set defaults
            rule_id = rule_data.get('id') or self._generate_rule_id_from_path(source)
            
            # Parse patterns
            patterns = []
            if 'patterns' in rule_data:
                for pattern_data in rule_data['patterns']:
                    pattern = self.pattern_parser.parse_pattern(pattern_data)
                    patterns.append(pattern)
            
            # Create rule
            rule = Rule(
                id=rule_id,
                name=rule_data.get('name', rule_id),
                description=rule_data.get('description', ''),
                tier=RuleTier(rule_data.get('tier', 'preference')),
                rule_type=RuleType(rule_data.get('type', 'custom')),
                severity=RuleSeverity(rule_data.get('severity', 'medium')),
                status=RuleStatus(rule_data.get('status', 'active')),
                patterns=patterns,
                conditions=rule_data.get('conditions', {}),
                exceptions=rule_data.get('exceptions', []),
                enforcement_level=EnforcementLevel(rule_data.get('enforcement', 'advisory')),
                auto_block=rule_data.get('auto_block', False),
                user_override=rule_data.get('user_override', True),
                override_justification_required=rule_data.get('override_justification_required', False),
                priority=rule_data.get('priority', 100),
                timeout_ms=rule_data.get('timeout_ms', 1000),
                cache_ttl_seconds=rule_data.get('cache_ttl_seconds', 300),
                version=rule_data.get('version', '1.0.0'),
                created_by=rule_data.get('created_by'),
                tags=rule_data.get('tags', [])
            )
            
            return rule
            
        except Exception as e:
            logger.error(f"Failed to create rule from {source}: {e}")
            return None
    
    def _generate_rule_id_from_path(self, path: str) -> str:
        """Generate rule ID from file path."""
        path_obj = Path(path)
        name = path_obj.stem
        
        # Convert to valid rule ID format
        rule_id = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        rule_id = re.sub(r'_+', '_', rule_id)
        rule_id = rule_id.strip('_')
        
        # Add prefix if needed
        if not rule_id:
            rule_id = f"rule_{hash(path) % 10000}"
        
        return rule_id


class RuleTemplateParser:
    """Parser for rule templates."""
    
    def __init__(self):
        self.templates = {}
        self._load_default_templates()
    
    def _load_default_templates(self) -> None:
        """Load default rule templates."""
        self.templates = {
            'safety_template': {
                'tier': 'safety',
                'enforcement': 'strict',
                'auto_block': True,
                'user_override': False,
                'severity': 'critical',
                'priority': 1
            },
            'operational_template': {
                'tier': 'operational',
                'enforcement': 'advisory',
                'auto_block': False,
                'user_override': True,
                'severity': 'high',
                'priority': 50
            },
            'preference_template': {
                'tier': 'preference',
                'enforcement': 'adaptive',
                'auto_block': False,
                'user_override': True,
                'severity': 'medium',
                'priority': 100
            }
        }
    
    def create_rule_from_template(self, template_name: str, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create rule data from template."""
        if template_name not in self.templates:
            raise ValueError(f"Template not found: {template_name}")
        
        template = self.templates[template_name].copy()
        template.update(rule_data)
        
        return template
    
    def get_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Get a rule template."""
        return self.templates.get(template_name)
    
    def add_template(self, name: str, template: Dict[str, Any]) -> None:
        """Add a custom template."""
        self.templates[name] = template.copy()
    
    def list_templates(self) -> List[str]:
        """List available templates."""
        return list(self.templates.keys())