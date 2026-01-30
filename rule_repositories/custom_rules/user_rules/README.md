# User Rules

This directory contains user-specific rules that can be customized per user.

## Structure

- Rules should be stored as YAML files per user
- Each rule must follow the schema defined in templates
- Rules are loaded when the user context is active

## Creating User Rules

1. Copy the appropriate template from `rule_templates/`
2. Customize the conditions and actions for your needs
3. Save with a descriptive name (e.g., `my_personal_rule.yaml`)
4. The rule will be applied when you interact with the system

## Rule Priority

User rules can override organization and system rules depending on configuration settings.
