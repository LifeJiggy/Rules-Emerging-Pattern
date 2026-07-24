/**
 * Rules-Emerging-Pattern TypeScript SDK
 *
 * Main entry point exporting all public classes, types, enums,
 * and utility functions.
 */

export { Client } from './client';
export { RuleEngineClient } from './rule-client';
export { ValidationClient } from './validation-client';
export { MonitoringClient } from './monitoring-client';

export {
  RuleTier,
  EnforcementLevel,
  RuleType,
  RuleSeverity,
  RuleStatus,
  ViolationType,
  ActionTaken,
  ConflictType,
  ResolutionStrategy,
  ConflictSeverity,
  AlertSeverity,
  AlertStatus,
  AuditAction,
  AuditCategory,
  AuditSeverity,
} from './models';

export {
  isRuleTier,
  isEnforcementLevel,
  isRuleType,
  isRuleSeverity,
  isRuleStatus,
  isViolationType,
  isActionTaken,
  isConflictType,
  isResolutionStrategy,
  isConflictSeverity,
  isAlertSeverity,
} from './models';

export {
  isRule,
  isRuleSet,
  isRuleContext,
  isRulePattern,
  isViolation,
  isSuggestion,
  isValidationResult,
  isRuleConflict,
  isConflictResolution,
  isAuditEvent,
} from './models';

export type {
  RulePattern,
  Rule,
  RuleSet,
  RuleContext,
  RuleEvaluationRequest,
  Violation,
  Suggestion,
  ValidationResult,
  RuleConflict,
  ConflictResolution,
  BatchValidationRequest,
  BatchValidationResult,
  AlertDefinition,
  AlertEvent,
  MetricsSnapshot,
  DashboardConfig,
  DashboardWidget,
  MonitorConfig,
  MetricsThreshold,
  ComplianceReport,
  ValidationProfile,
  ValidationThreshold,
  AuditEvent,
  AuditTrail,
  RuleStats,
  RuleTemplate,
  RuleGroup,
  SdkOptions,
  RetryConfig,
  SdkResponse,
  SdkError,
  ContentCheckResult,
  ComplianceCheckResult,
  SafetyCheckResult,
  FormatCheckResult,
  QualityCheckResult,
  HallucinationResult,
} from './models';

export {
  createRule,
  createRuleSet,
  createRuleContext,
  createEvaluationRequest,
  createViolation,
  createValidationResult,
  createRuleConflict,
  createConflictResolution,
  createBatchValidationRequest,
  createBatchValidationResult,
  createAlertDefinition,
  createMetricsSnapshot,
  createAuditEvent,
  createAuditTrail,
  createRuleStats,
  createRulePattern,
} from './models';

export {
  validateRule,
  validateRulePattern,
} from './models';

export {
  shouldEvaluateRule,
  evaluateAlertCondition,
  contextToEffective,
  contextIsEmpty,
} from './models';

export {
  resultHasViolations,
  resultIsBlocked,
  resultGetViolationsByTier,
  resultGetViolationsBySeverity,
  resultGetSummary,
  resultGetTopViolations,
  resultGetScoreBreakdown,
  resultMerge,
} from './models';

export {
  batchResultGetSuccessRate,
  batchResultGetSummary,
} from './models';

export {
  snapshotGetAllMetrics,
  snapshotGetSummary,
  isAlertActive,
} from './models';

export {
  SdkClientError,
  SdkValidationError,
  SdkAuthError,
  SdkNotFoundError,
  SdkRateLimitError,
  SdkTimeoutError,
  DEFAULT_RETRY_CONFIG,
} from './models';

export { RULE_SEVERITY_ORDER } from './models';
