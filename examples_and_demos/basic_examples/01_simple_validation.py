#!/usr/bin/env python3
"""
01_simple_validation.py - Basic Content Validation Example

Demonstrates the most basic usage of the Rules-Emerging-Pattern framework
for validating content against simple safety rules.
"""

import asyncio
import logging
from typing import Dict, Any, List

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import (
    Rule,
    RuleTier,
    RuleType,
    RuleSeverity,
    RuleStatus,
    RulePattern,
    EnforcementLevel,
    RuleEvaluationRequest,
    RuleContext
)
from rules_emerging_pattern.models.validation import ValidationResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_basic_safety_rule() -> Rule:
    """Create a simple safety rule for prohibited content."""
    return Rule(
        id='basic_safety_001',
        name='Prohibited Keywords Rule',
        description='Blocks content containing prohibited keywords',
        tier=RuleTier.SAFETY,
        rule_type=RuleType.CONTENT_FILTERING,
        severity=RuleSeverity.HIGH,
        status=RuleStatus.ACTIVE,
        patterns=[
            RulePattern(
                type=RuleType.CONTENT_FILTERING,
                keywords=['dangerous', 'harmful', 'illegal'],
                action='block'
            )
        ],
        enforcement_level=EnforcementLevel.STRICT,
        auto_block=True,
        user_override=False,
        priority=100
    )


def create_advisory_rule() -> Rule:
    """Create an advisory rule for sensitive topics."""
    return Rule(
        id='advisory_001',
        name='Sensitive Topic Advisory',
        description='Warns about potentially sensitive content',
        tier=RuleTier.OPERATIONAL,
        rule_type=RuleType.SEMANTIC_ANALYSIS,
        severity=RuleSeverity.MEDIUM,
        status=RuleStatus.ACTIVE,
        patterns=[
            RulePattern(
                type=RuleType.SEMANTIC_ANALYSIS,
                keywords=['controversial', 'debated', 'polarizing'],
                action='warn',
                confidence_threshold=0.7
            )
        ],
        enforcement_level=EnforcementLevel.ADVISORY,
        auto_block=False,
        user_override=True,
        priority=50
    )


class SimpleRuleManager:
    """Simple rule manager for demonstration purposes."""
    
    def __init__(self):
        self.rules: Dict[str, Rule] = {}
        logger.info('SimpleRuleManager initialized')
    
    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the manager."""
        self.rules[rule.id] = rule
        logger.info(f'Rule added: {rule.id}')
    
    def get_rule(self, rule_id: str) -> Rule:
        """Get a rule by ID."""
        return self.rules.get(rule_id)
    
    def get_rules_by_tier(self, tier: RuleTier) -> List[Rule]:
        """Get all rules for a specific tier."""
        return [r for r in self.rules.values() if r.tier == tier]
    
    def get_applicable_rules(self, context: Dict[str, Any]) -> List[Rule]:
        """Get all rules applicable to the given context."""
        return list(self.rules.values())


async def validate_content(content: str, rule_manager: SimpleRuleManager) -> ValidationResult:
    """Validate content against all rules."""
    engine = RuleEngine(rule_manager=rule_manager)
    
    request = RuleEvaluationRequest(
        content=content,
        context=RuleContext(user_id='demo_user')
    )
    
    try:
        result = await engine.evaluate(request)
        return result
    finally:
        await engine.shutdown()


def print_result(result: ValidationResult, content: str) -> None:
    """Print validation result in a readable format."""
    print(f'\n{"="*60}')
    print(f'Content: {content[:50]}...' if len(content) > 50 else f'Content: {content}')
    print(f'Valid: {result.valid}')
    print(f'Score: {result.total_score:.2f}')
    print(f'Processing Time: {result.processing_time_ms}ms')
    print(f'Violations: {len(result.violations)}')
    
    for violation in result.violations:
        print(f'  - {violation.rule_name}: {violation.explanation}')
        print(f'    Severity: {violation.rule_severity}, Blocked: {violation.blocked}')


async def main():
    """Main example function."""
    print('Simple Validation Example - Rules-Emerging-Pattern')
    print('=' * 60)
    
    # Setup rule manager
    rule_manager = SimpleRuleManager()
    rule_manager.add_rule(create_basic_safety_rule())
    rule_manager.add_rule(create_advisory_rule())
    
    # Test cases
    test_contents = [
        'This is completely safe content.',
        'This contains dangerous instructions that are harmful.',
        'A controversial topic that might be debated.',
        'Mixed content with safe words but also dangerous keywords.'
    ]
    
    for content in test_contents:
        result = await validate_content(content, rule_manager)
        print_result(result, content)
    
    print(f'\n{"="*60}')
    print('Example completed successfully!')


if __name__ == '__main__':
    asyncio.run(main())
