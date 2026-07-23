"""
Preference rule catalog - user-customizable preference rules for UI/UX,
content personalization, and notification preferences.

Provides predefined preference rule definitions with config-driven parameters
that users can customize to tailor their experience.
"""

import hashlib
import json
import logging
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict

import yaml

from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)

logger = logging.getLogger(__name__)


class PreferenceCategory(str, Enum):
    """Categories of preference rules."""
    UI_UX = "ui_ux"
    CONTENT_PERSONALIZATION = "content_personalization"
    NOTIFICATION = "notification"
    LANGUAGE = "language"
    ACCESSIBILITY = "accessibility"
    LAYOUT = "layout"
    INTERACTION = "interaction"
    DISPLAY = "display"
    SORTING = "sorting"
    FILTERING = "filtering"
    COLLABORATION = "collaboration"
    PRODUCTIVITY = "productivity"


class PersonalizationDimension(str, Enum):
    """Dimensions of content personalization."""
    TOPIC = "topic"
    DIFFICULTY = "difficulty"
    FORMAT = "format"
    LENGTH = "length"
    LANGUAGE = "language"
    SOURCE = "source"
    RECENCY = "recency"
    RELEVANCE = "relevance"


class NotificationChannel(str, Enum):
    """Notification delivery channels."""
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SLACK = "slack"
    TEAMS = "teams"


class NotificationPriority(str, Enum):
    """Priority levels for notifications."""
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    DIGEST = "digest"


@dataclass
class PreferenceRuleDefinition:
    """Definition of a predefined preference rule."""

    rule_id: str
    name: str
    description: str
    category: PreferenceCategory
    severity: RuleSeverity
    enforcement: EnforcementLevel
    patterns: List[RulePattern]
    version: str = "1.0.0"
    auto_block: bool = False
    user_override: bool = True
    override_justification_required: bool = False
    tags: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    priority: int = 500
    conditions: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    default_enabled: bool = True
    customizable: bool = True
    user_visible: bool = True

    def to_rule(self) -> Rule:
        """Convert definition to a Rule model instance."""
        rule_type = self._determine_rule_type()
        return Rule(
            id=self.rule_id,
            name=self.name,
            description=self.description,
            tier=RuleTier.PREFERENCE,
            rule_type=rule_type,
            severity=self.severity,
            status=RuleStatus.ACTIVE if self.default_enabled else RuleStatus.INACTIVE,
            patterns=self.patterns,
            conditions={**self.conditions, **self.parameters},
            exceptions=self.exceptions,
            enforcement_level=self.enforcement,
            auto_block=self.auto_block,
            user_override=self.user_override,
            override_justification_required=self.override_justification_required,
            version=self.version,
            tags=self.tags + ["customizable"] if self.customizable else self.tags,
            priority=self.priority,
        )

    def _determine_rule_type(self) -> RuleType:
        """Determine the RuleType based on category."""
        type_map = {
            PreferenceCategory.UI_UX: RuleType.CUSTOM,
            PreferenceCategory.CONTENT_PERSONALIZATION: RuleType.CUSTOM,
            PreferenceCategory.NOTIFICATION: RuleType.CUSTOM,
            PreferenceCategory.LANGUAGE: RuleType.CUSTOM,
            PreferenceCategory.ACCESSIBILITY: RuleType.CUSTOM,
            PreferenceCategory.LAYOUT: RuleType.CUSTOM,
            PreferenceCategory.INTERACTION: RuleType.CUSTOM,
            PreferenceCategory.DISPLAY: RuleType.CUSTOM,
            PreferenceCategory.SORTING: RuleType.CUSTOM,
            PreferenceCategory.FILTERING: RuleType.CUSTOM,
            PreferenceCategory.COLLABORATION: RuleType.CUSTOM,
            PreferenceCategory.PRODUCTIVITY: RuleType.CUSTOM,
        }
        return type_map.get(self.category, RuleType.CUSTOM)


@dataclass
class PreferenceOption:
    """A configurable option for a preference rule."""

    name: str
    display_name: str
    description: str
    option_type: str
    default_value: Any
    allowed_values: Optional[List[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    requires_restart: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "option_type": self.option_type,
            "default_value": self.default_value,
            "allowed_values": self.allowed_values,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "requires_restart": self.requires_restart,
        }


class PreferenceRuleCatalog:
    """Catalog of user-customizable preference rules.

    Provides predefined preference rule definitions for UI/UX customization,
    content personalization, and notification preferences with config-driven
    parameters that users can customize.
    """

    PREFERENCE_OPTIONS: Dict[str, PreferenceOption] = {
        "theme": PreferenceOption(
            name="theme",
            display_name="UI Theme",
            description="Color theme for the user interface",
            option_type="enum",
            default_value="system",
            allowed_values=["light", "dark", "system", "high_contrast"],
        ),
        "font_size": PreferenceOption(
            name="font_size",
            display_name="Font Size",
            description="Base font size for the user interface",
            option_type="enum",
            default_value="medium",
            allowed_values=["small", "medium", "large", "xlarge"],
        ),
        "language": PreferenceOption(
            name="language",
            display_name="Language",
            description="Display language for the application",
            option_type="enum",
            default_value="en",
            allowed_values=["en", "es", "fr", "de", "zh", "ja", "ko", "pt", "ru", "ar"],
        ),
        "results_per_page": PreferenceOption(
            name="results_per_page",
            display_name="Results Per Page",
            description="Number of results to display per page",
            option_type="int",
            default_value=25,
            min_value=10,
            max_value=100,
        ),
        "notification_digest_frequency": PreferenceOption(
            name="notification_digest_frequency",
            display_name="Digest Frequency",
            description="How often to send notification digests",
            option_type="enum",
            default_value="daily",
            allowed_values=["real_time", "hourly", "daily", "weekly", "never"],
        ),
        "content_difficulty": PreferenceOption(
            name="content_difficulty",
            display_name="Content Difficulty",
            description="Preferred content difficulty level",
            option_type="enum",
            default_value="intermediate",
            allowed_values=["beginner", "intermediate", "advanced", "expert"],
        ),
        "compact_mode": PreferenceOption(
            name="compact_mode",
            display_name="Compact Mode",
            description="Display content in compact format",
            option_type="bool",
            default_value=False,
        ),
        "auto_save_interval": PreferenceOption(
            name="auto_save_interval",
            display_name="Auto-Save Interval",
            description="Interval in seconds for auto-saving work",
            option_type="int",
            default_value=30,
            min_value=5,
            max_value=300,
        ),
        "sidebar_visible": PreferenceOption(
            name="sidebar_visible",
            display_name="Sidebar Visible",
            description="Whether the navigation sidebar is visible by default",
            option_type="bool",
            default_value=True,
        ),
        "content_width": PreferenceOption(
            name="content_width",
            display_name="Content Width",
            description="Preferred content area width",
            option_type="enum",
            default_value="standard",
            allowed_values=["narrow", "standard", "wide", "full"],
        ),
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = self._default_config()
        if config:
            self._config.update(config)
        self._rules: Dict[str, Rule] = {}
        self._definitions: Dict[str, PreferenceRuleDefinition] = {}
        self._options: Dict[str, PreferenceOption] = dict(self.PREFERENCE_OPTIONS)
        self._option_values: Dict[str, Any] = {
            name: opt.default_value
            for name, opt in self._options.items()
        }
        self._category_enabled: Dict[PreferenceCategory, bool] = {
            cat: True for cat in PreferenceCategory
        }
        self._version: str = "1.0.0"
        self._changelog: List[Dict[str, Any]] = []
        self._lock = RLock()
        self._user_overrides: Dict[str, Dict[str, Any]] = {}

        self._initialize_catalog()
        logger.info(
            "PreferenceRuleCatalog initialized (version=%s, %d rules)",
            self._version,
            len(self._definitions),
        )

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for the preference catalog."""
        return {
            "enable_ui_ux": True,
            "enable_content_personalization": True,
            "enable_notification": True,
            "enable_language": True,
            "enable_accessibility": True,
            "enable_layout": True,
            "enable_interaction": True,
            "enable_display": True,
            "enable_sorting": True,
            "enable_filtering": True,
            "enable_collaboration": True,
            "enable_productivity": True,
            "auto_register_rules": True,
            "allow_user_customization": True,
            "max_customizations_per_user": 100,
            "track_customization_history": True,
            "apply_defaults_on_reset": True,
            "validate_customizations": True,
            "version_check_enabled": True,
            "rule_tags_prefix": "preference",
        }

    def _initialize_catalog(self) -> None:
        """Initialize the catalog with predefined preference rule definitions."""
        self._add_ui_ux_rules()
        self._add_content_personalization_rules()
        self._add_notification_rules()
        self._add_language_rules()
        self._add_accessibility_rules()
        self._add_layout_rules()
        self._add_interaction_rules()
        self._add_display_rules()
        self._add_sorting_rules()
        self._add_filtering_rules()
        self._add_collaboration_rules()
        self._add_productivity_rules()

    def _add_ui_ux_rules(self) -> None:
        """Add UI/UX preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_ui_001",
                name="Theme Preference",
                description="User's preferred color theme for the interface",
                category=PreferenceCategory.UI_UX,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["theme", "color", "appearance", "dark mode", "light mode"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"theme": "system"},
                priority=500,
                tags=["ui", "theme", "appearance"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_ui_002",
                name="Font Size Preference",
                description="User's preferred font size for readability",
                category=PreferenceCategory.UI_UX,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["font", "text size", "readability", "zoom"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"font_size": "medium"},
                priority=510,
                tags=["ui", "font", "readability"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_ui_003",
                name="Compact Mode Preference",
                description="Whether to use compact display mode",
                category=PreferenceCategory.UI_UX,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["compact", "dense", "spacious", "view mode"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"compact_mode": False},
                priority=520,
                tags=["ui", "layout", "compact"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_ui_004",
                name="Sidebar Visibility Preference",
                description="Whether the sidebar is visible by default",
                category=PreferenceCategory.UI_UX,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["sidebar", "navigation", "panel", "drawer"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"sidebar_visible": True},
                priority=530,
                tags=["ui", "sidebar", "navigation"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_content_personalization_rules(self) -> None:
        """Add content personalization rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_content_001",
                name="Content Difficulty Preference",
                description="Preferred difficulty level of displayed content",
                category=PreferenceCategory.CONTENT_PERSONALIZATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["difficulty", "level", "beginner", "advanced", "expert"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"difficulty": "intermediate"},
                priority=600,
                tags=["content", "personalization", "difficulty"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_content_002",
                name="Content Length Preference",
                description="Preferred length of content items",
                category=PreferenceCategory.CONTENT_PERSONALIZATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["length", "short", "long", "brief", "detailed", "summary"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"preferred_length": "medium", "max_length_chars": 5000},
                priority=610,
                tags=["content", "personalization", "length"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_content_003",
                name="Content Format Preference",
                description="Preferred format for content delivery",
                category=PreferenceCategory.CONTENT_PERSONALIZATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["format", "video", "article", "tutorial", "reference"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"preferred_formats": ["article", "tutorial"]},
                priority=620,
                tags=["content", "personalization", "format"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_content_004",
                name="Content Recency Preference",
                description="Preferred recency of content items",
                category=PreferenceCategory.CONTENT_PERSONALIZATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["recent", "new", "latest", "updated", "archive"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"max_age_days": 365, "prioritize_recent": True},
                priority=630,
                tags=["content", "personalization", "recency"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_notification_rules(self) -> None:
        """Add notification preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_notif_001",
                name="Notification Channel Preference",
                description="Preferred channels for receiving notifications",
                category=PreferenceCategory.NOTIFICATION,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["notification", "alert", "channel", "push", "email"],
                        confidence_threshold=0.2,
                        action="suggest",
                    ),
                ],
                parameters={
                    "channels": ["in_app"],
                    "quiet_hours_enabled": False,
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                },
                priority=400,
                tags=["notification", "channel", "preferences"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_notif_002",
                name="Notification Frequency Preference",
                description="How frequently to receive notification digests",
                category=PreferenceCategory.NOTIFICATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["digest", "frequency", "daily", "weekly", "real-time"],
                        confidence_threshold=0.15,
                        action="suggest",
                    ),
                ],
                parameters={"digest_frequency": "daily", "batch_notifications": True},
                priority=410,
                tags=["notification", "frequency", "digest"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_notif_003",
                name="Notification Types Preference",
                description="Which types of events to receive notifications for",
                category=PreferenceCategory.NOTIFICATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=[
                            "notification type", "alert type", "subscribe",
                            "unsubscribe", "event",
                        ],
                        confidence_threshold=0.15,
                        action="suggest",
                    ),
                ],
                parameters={
                    "notify_on_mentions": True,
                    "notify_on_comments": True,
                    "notify_on_updates": True,
                    "notify_on_errors": True,
                    "min_priority": "normal",
                },
                priority=420,
                tags=["notification", "types", "subscription"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_notif_004",
                name="Notification Priority Threshold",
                description="Minimum priority level for sending notifications",
                category=PreferenceCategory.NOTIFICATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["priority", "threshold", "important", "urgent"],
                        confidence_threshold=0.15,
                        action="suggest",
                    ),
                ],
                parameters={"minimum_priority": "low"},
                priority=430,
                tags=["notification", "priority", "threshold"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_language_rules(self) -> None:
        """Add language preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_lang_001",
                name="Display Language Preference",
                description="Preferred language for application display",
                category=PreferenceCategory.LANGUAGE,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["language", "locale", "translation", "i18n", "l10n"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"language": "en", "fallback_language": "en"},
                priority=700,
                tags=["language", "locale", "i18n"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_lang_002",
                name="Content Language Preference",
                description="Preferred languages for content discovery",
                category=PreferenceCategory.LANGUAGE,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["content language", "translation", "original language"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "preferred_languages": ["en"],
                    "show_translations": True,
                    "auto_translate": False,
                },
                priority=710,
                tags=["language", "content", "translation"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_accessibility_rules(self) -> None:
        """Add accessibility preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_a11y_001",
                name="High Contrast Mode Preference",
                description="Whether to use high contrast display mode",
                category=PreferenceCategory.ACCESSIBILITY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["contrast", "accessibility", "a11y", "visibility"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"high_contrast": False},
                priority=300,
                tags=["accessibility", "contrast", "a11y"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_a11y_002",
                name="Screen Reader Optimization",
                description="Enable screen reader optimized output",
                category=PreferenceCategory.ACCESSIBILITY,
                severity=RuleSeverity.MEDIUM,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["screen reader", "aria", "alt text", "narrator"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "screen_reader_optimized": False,
                    "aria_labels_enabled": True,
                    "keyboard_navigation": True,
                },
                priority=310,
                tags=["accessibility", "screen_reader", "a11y"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_a11y_003",
                name="Reduced Motion Preference",
                description="Preference for reduced animations and motion",
                category=PreferenceCategory.ACCESSIBILITY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["motion", "animation", "reduce", "transition"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"reduced_motion": False},
                priority=320,
                tags=["accessibility", "motion", "animation"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_layout_rules(self) -> None:
        """Add layout preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_layout_001",
                name="Content Width Preference",
                description="Preferred width of the content area",
                category=PreferenceCategory.LAYOUT,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["width", "layout", "narrow", "wide", "full width"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"content_width": "standard"},
                priority=540,
                tags=["layout", "width", "content_area"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_layout_002",
                name="Results Per Page Preference",
                description="Number of items to show per page",
                category=PreferenceCategory.LAYOUT,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["per page", "page size", "pagination", "limit"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"results_per_page": 25},
                priority=550,
                tags=["layout", "pagination", "page_size"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_interaction_rules(self) -> None:
        """Add interaction preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_interact_001",
                name="Auto-Save Preference",
                description="Whether and how often to auto-save work",
                category=PreferenceCategory.INTERACTION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["auto-save", "autosave", "save interval"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"auto_save_enabled": True, "auto_save_interval_seconds": 30},
                priority=800,
                tags=["interaction", "auto_save", "productivity"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_interact_002",
                name="Keyboard Shortcut Preference",
                description="User's preferred keyboard shortcuts",
                category=PreferenceCategory.INTERACTION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["shortcut", "keyboard", "hotkey", "key binding"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"enable_keyboard_shortcuts": True, "shortcut_preset": "default"},
                priority=810,
                tags=["interaction", "shortcuts", "keyboard"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_interact_003",
                name="Confirmation Dialog Preference",
                description="Whether to show confirmation dialogs for destructive actions",
                category=PreferenceCategory.INTERACTION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["confirmation", "confirm", "are you sure", "dialog"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "confirm_before_delete": True,
                    "confirm_before_discard": True,
                    "confirm_before_leave": True,
                },
                priority=820,
                tags=["interaction", "confirmation", "dialogs"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_display_rules(self) -> None:
        """Add display preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_display_001",
                name="Date Format Preference",
                description="Preferred format for displaying dates",
                category=PreferenceCategory.DISPLAY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["date format", "date display", "date style"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"date_format": "YYYY-MM-DD", "time_format": "24h"},
                priority=900,
                tags=["display", "date", "format"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_display_002",
                name="Number Format Preference",
                description="Preferred format for displaying numbers",
                category=PreferenceCategory.DISPLAY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["number format", "decimal", "thousands", "separator"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "decimal_separator": ".",
                    "thousands_separator": ",",
                    "decimal_places": 2,
                },
                priority=910,
                tags=["display", "number", "format"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_sorting_rules(self) -> None:
        """Add sorting preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_sort_001",
                name="Default Sort Order",
                description="Preferred default sort order for content lists",
                category=PreferenceCategory.SORTING,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["sort", "order", "ascending", "descending"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "default_sort_field": "updated_at",
                    "default_sort_direction": "desc",
                },
                priority=650,
                tags=["sorting", "order", "defaults"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_sort_002",
                name="Custom Sort Fields",
                description="Custom sort order preferences for specific content types",
                category=PreferenceCategory.SORTING,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["custom sort", "sort by", "reorder"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={"allow_custom_sort": True, "remember_sort_preference": True},
                priority=660,
                tags=["sorting", "custom", "preferences"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_filtering_rules(self) -> None:
        """Add filtering preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_filter_001",
                name="Default Content Filter",
                description="Default filters to apply to content views",
                category=PreferenceCategory.FILTERING,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["filter", "default filter", "show", "hide"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "default_filters": {},
                    "remember_last_filter": True,
                },
                priority=670,
                tags=["filtering", "defaults", "views"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_filter_002",
                name="Advanced Filtering Preference",
                description="Enable advanced filtering options",
                category=PreferenceCategory.FILTERING,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["advanced filter", "faceted", "search filter"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "advanced_filtering": False,
                    "save_filter_presets": True,
                },
                priority=680,
                tags=["filtering", "advanced", "presets"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_collaboration_rules(self) -> None:
        """Add collaboration preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_collab_001",
                name="Collaboration Mode Preference",
                description="Preferred collaboration and sharing settings",
                category=PreferenceCategory.COLLABORATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["collaboration", "share", "team", "permission"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "default_sharing": "private",
                    "allow_public_sharing": False,
                    "auto_notify_collaborators": True,
                },
                priority=750,
                tags=["collaboration", "sharing", "permissions"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_collab_002",
                name="Comment and Review Preference",
                description="Preferences for commenting and code review workflows",
                category=PreferenceCategory.COLLABORATION,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["comment", "review", "feedback", "annotation"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "default_comment_visibility": "all",
                    "require_review_approval": False,
                    "auto_subscribe_to_comments": True,
                },
                priority=760,
                tags=["collaboration", "comments", "review"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _add_productivity_rules(self) -> None:
        """Add productivity preference rules to the catalog."""
        definitions = [
            PreferenceRuleDefinition(
                rule_id="pref_prod_001",
                name="Focus Mode Preference",
                description="Focus mode and distraction-free preferences",
                category=PreferenceCategory.PRODUCTIVITY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["focus", "distraction-free", "zen mode", "concentrate"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "focus_mode_enabled": False,
                    "hide_notifications_in_focus": True,
                    "focus_session_minutes": 25,
                },
                priority=850,
                tags=["productivity", "focus", "distraction_free"],
            ),
            PreferenceRuleDefinition(
                rule_id="pref_prod_002",
                name="Template and Snippet Preference",
                description="Preferred templates and code snippets",
                category=PreferenceCategory.PRODUCTIVITY,
                severity=RuleSeverity.LOW,
                enforcement=EnforcementLevel.ADAPTIVE,
                patterns=[
                    RulePattern(
                        type=RuleType.CUSTOM,
                        keywords=["template", "snippet", "boilerplate", "starter"],
                        confidence_threshold=0.1,
                        action="suggest",
                    ),
                ],
                parameters={
                    "default_template": "default",
                    "enable_snippets": True,
                    "auto_complete_templates": True,
                },
                priority=860,
                tags=["productivity", "templates", "snippets"],
            ),
        ]
        for definition in definitions:
            self._register_definition(definition)

    def _register_definition(self, definition: PreferenceRuleDefinition) -> None:
        """Register a preference rule definition in the catalog."""
        if definition.rule_id in self._definitions:
            logger.warning("Overwriting existing rule definition: %s", definition.rule_id)
        self._definitions[definition.rule_id] = definition
        if self._config.get("auto_register_rules", True):
            rule = definition.to_rule()
            self._rules[definition.rule_id] = rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a preference rule by ID."""
        return self._rules.get(rule_id)

    def get_definition(self, rule_id: str) -> Optional[PreferenceRuleDefinition]:
        """Get a preference rule definition by ID."""
        return self._definitions.get(rule_id)

    def get_rules(
        self,
        category: Optional[PreferenceCategory] = None,
        enabled_only: bool = False,
        user_visible_only: bool = False,
    ) -> List[Rule]:
        """Get preference rules with optional filtering."""
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if self._rule_matches_category(r, category)]
        if enabled_only:
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
        if user_visible_only:
            visible_ids = {
                d.rule_id for d in self._definitions.values() if d.user_visible
            }
            rules = [r for r in rules if r.id in visible_ids]
        return rules

    def _rule_matches_category(self, rule: Rule, category: PreferenceCategory) -> bool:
        """Check if a rule matches a preference category."""
        for definition in self._definitions.values():
            if definition.rule_id == rule.id and definition.category == category:
                return True
        return False

    def get_definitions(
        self,
        category: Optional[PreferenceCategory] = None,
        customizable_only: bool = False,
    ) -> List[PreferenceRuleDefinition]:
        """Get rule definitions with optional filtering."""
        definitions = list(self._definitions.values())
        if category:
            definitions = [d for d in definitions if d.category == category]
        if customizable_only:
            definitions = [d for d in definitions if d.customizable]
        return definitions

    def get_option(self, name: str) -> Optional[Any]:
        """Get the current value of a named preference option."""
        return self._option_values.get(name)

    def get_option_definition(self, name: str) -> Optional[PreferenceOption]:
        """Get the definition of a named preference option."""
        return self._options.get(name)

    def set_option(self, name: str, value: Any, user_id: Optional[str] = None) -> List[str]:
        """Set a preference option value, returning validation errors."""
        errors: List[str] = []
        option = self._options.get(name)
        if not option:
            errors.append(f"Unknown option: {name}")
            return errors

        if option.allowed_values and value not in option.allowed_values:
            errors.append(
                f"Invalid value '{value}' for option '{name}'. "
                f"Allowed: {option.allowed_values}"
            )
            return errors
        if option.min_value is not None and isinstance(value, (int, float)) and value < option.min_value:
            errors.append(f"Value for '{name}' must be >= {option.min_value}")
            return errors
        if option.max_value is not None and isinstance(value, (int, float)) and value > option.max_value:
            errors.append(f"Value for '{name}' must be <= {option.max_value}")
            return errors

        self._option_values[name] = value

        if user_id and self._config.get("track_customization_history", True):
            if user_id not in self._user_overrides:
                self._user_overrides[user_id] = {}
            self._user_overrides[user_id][name] = {
                "value": value,
                "set_at": datetime.utcnow().isoformat(),
            }

        logger.debug("Option '%s' set to %s (user: %s)", name, value, user_id or "system")
        return errors

    def set_options(self, values: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, List[str]]:
        """Set multiple preference option values."""
        all_errors: Dict[str, List[str]] = {}
        for name, value in values.items():
            errors = self.set_option(name, value, user_id)
            if errors:
                all_errors[name] = errors
        return all_errors

    def get_all_options(self) -> Dict[str, Any]:
        """Get all current preference option values."""
        return dict(self._option_values)

    def get_option_descriptors(self) -> List[Dict[str, Any]]:
        """Get descriptors for all preference options (for UI rendering)."""
        return [
            {
                **opt.to_dict(),
                "current_value": self._option_values.get(opt.name),
            }
            for opt in self._options.values()
        ]

    def get_user_customizations(self, user_id: str) -> Dict[str, Any]:
        """Get all customizations made by a specific user."""
        return dict(self._user_overrides.get(user_id, {}))

    def reset_user_customizations(self, user_id: str) -> None:
        """Reset all customizations for a user to defaults."""
        if user_id in self._user_overrides:
            for name in self._user_overrides[user_id]:
                option = self._options.get(name)
                if option:
                    self._option_values[name] = option.default_value
            del self._user_overrides[user_id]
            logger.info("Reset all customizations for user: %s", user_id)

    def reset_option(self, name: str) -> bool:
        """Reset a single option to its default value."""
        option = self._options.get(name)
        if not option:
            return False
        self._option_values[name] = option.default_value
        return True

    def reset_all_options(self) -> None:
        """Reset all options to their default values."""
        for name, option in self._options.items():
            self._option_values[name] = option.default_value
        self._user_overrides.clear()
        logger.info("All preference options reset to defaults")

    def enable_category(self, category: PreferenceCategory) -> None:
        """Enable all rules in a preference category."""
        self._category_enabled[category] = True
        for definition in self._definitions.values():
            if definition.category == category and definition.rule_id in self._rules:
                self._rules[definition.rule_id].status = RuleStatus.ACTIVE
        logger.info("Enabled preference category: %s", category.value)

    def disable_category(self, category: PreferenceCategory) -> None:
        """Disable all rules in a preference category."""
        self._category_enabled[category] = False
        for definition in self._definitions.values():
            if definition.category == category and definition.rule_id in self._rules:
                self._rules[definition.rule_id].status = RuleStatus.INACTIVE
        logger.info("Disabled preference category: %s", category.value)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the preference catalog."""
        total = len(self._rules)
        active = sum(1 for r in self._rules.values() if r.status == RuleStatus.ACTIVE)
        by_category: Dict[str, int] = defaultdict(int)
        customizable_count = 0
        visible_count = 0
        for definition in self._definitions.values():
            by_category[definition.category.value] += 1
            if definition.customizable:
                customizable_count += 1
            if definition.user_visible:
                visible_count += 1
        return {
            "total_rules": total,
            "active_rules": active,
            "inactive_rules": total - active,
            "version": self._version,
            "rules_by_category": dict(by_category),
            "customizable_rules": customizable_count,
            "user_visible_rules": visible_count,
            "total_options": len(self._options),
            "total_user_overrides": sum(len(v) for v in self._user_overrides.values()),
            "enabled_categories": {k.value: v for k, v in self._category_enabled.items()},
        }

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a specific preference rule."""
        if rule_id in self._rules:
            self._rules[rule_id].status = RuleStatus.ACTIVE
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a specific preference rule."""
        if rule_id in self._rules:
            self._rules[rule_id].status = RuleStatus.INACTIVE
            return True
        return False

    def update_catalog(self, version: str, changes: List[Dict[str, Any]]) -> None:
        """Update the catalog version with a list of changes."""
        self._version = version
        self._changelog.append({
            "version": version,
            "timestamp": datetime.utcnow().isoformat(),
            "changes": changes,
        })
        logger.info("Preference catalog updated to version %s (%d changes)", version, len(changes))

    def get_version(self) -> str:
        """Get the current catalog version."""
        return self._version

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the catalog to a dictionary."""
        return {
            "version": self._version,
            "rules": [d.to_rule().dict() for d in self._definitions.values()],
            "category_enabled": {k.value: v for k, v in self._category_enabled.items()},
            "options": {k: v for k, v in self._option_values.items()},
            "changelog": self._changelog,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreferenceRuleCatalog":
        """Create a catalog from a dictionary."""
        catalog = cls()
        catalog._version = data.get("version", "1.0.0")
        category_enabled = data.get("category_enabled", {})
        for cat_value, enabled in category_enabled.items():
            try:
                cat = PreferenceCategory(cat_value)
                catalog._category_enabled[cat] = enabled
            except ValueError:
                pass
        options = data.get("options", {})
        for name, value in options.items():
            if name in catalog._option_values:
                catalog._option_values[name] = value
        catalog._changelog = data.get("changelog", [])
        return catalog

    def to_json(self) -> str:
        """Serialize the catalog to JSON."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "PreferenceRuleCatalog":
        """Create a catalog from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_yaml(self) -> str:
        """Serialize the catalog to YAML."""
        return yaml.dump(self.to_dict(), default_flow_style=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "PreferenceRuleCatalog":
        """Create a catalog from a YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)
