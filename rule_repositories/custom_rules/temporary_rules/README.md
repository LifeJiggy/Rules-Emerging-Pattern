# Temporary Rules

This directory contains temporary or experimental rules.

## Purpose

- Testing new rule configurations
- A/B testing different rule approaches
- Temporary overrides for specific scenarios
- Rules with expiration dates

## Structure

- Rules are stored as YAML files
- Rules can have an optional `expires_at` field
- Expired rules are automatically archived

## Usage

1. Create a rule file with a clear name (e.g., `test_new_feature.yaml`)
2. Add an expiration date if needed
3. Monitor the rule's performance
4. Move to permanent location or delete when done

## Cleanup

Temporary rules older than 30 days are automatically archived unless marked as permanent.
