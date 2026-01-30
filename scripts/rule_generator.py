#!/usr/bin/env python3
"""Generate rules from templates."""
import json
import yaml
from pathlib import Path

def generate_rule_from_template(template_name, rule_data):
    """Generate a rule from a template."""
    templates = {
        'safety': {
            'tier': 'safety',
            'enforcement': 'strict',
            'auto_block': True,
            'user_override': False,
            'severity': 'critical'
        },
        'operational': {
            'tier': 'operational',
            'enforcement': 'advisory',
            'auto_block': False,
            'user_override': True,
            'severity': 'high'
        },
        'preference': {
            'tier': 'preference',
            'enforcement': 'adaptive',
            'auto_block': False,
            'user_override': True,
            'severity': 'low'
        }
    }
    
    if template_name not in templates:
        raise ValueError(f"Template {template_name} not found")
    
    rule = templates[template_name].copy()
    rule.update(rule_data)
    return rule

def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate rules from templates")
    parser.add_argument("template", choices=['safety', 'operational', 'preference'])
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    rule = generate_rule_from_template(args.template, {'name': args.name, 'id': args.name.lower().replace(' ', '_')})
    
    with open(args.output, 'w') as f:
        yaml.dump({'rule': rule}, f)
    
    print(f"Rule generated: {args.output}")

if __name__ == "__main__":
    main()
