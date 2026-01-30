# Organization Rules

This directory contains organization-specific rules that apply to your organization or team.

## Structure

- Rules should be stored as YAML files
- Each rule must follow the schema defined in templates
- Rules are loaded automatically by the rule engine

## Creating Custom Rules

1. Copy the appropriate template from `rule_templates/`
2. Customize the conditions and actions
3. Save with a descriptive name (e.g., `my_organization_rule.yaml`)
4. The rule will be loaded on next engine initialization

## Rule Priority

Organization rules take precedence over system defaults but can be overridden by user rules if configured.
