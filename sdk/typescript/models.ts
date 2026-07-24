/**
 * Type definitions for the Rules-Emerging-Pattern SDK.
 * Mirrors the Python models from src/models/
 */

import { v4 as uuidv4 } from 'uuid';

export enum RuleTier {
  SAFETY = 'safety',
  OPERATIONAL = 'operational',
  PREFERENCE = 'preference',
}

export function isRuleTier(value: unknown): value is RuleTier {
  return Object.values(RuleTier).includes(value as RuleTier);
}

export enum EnforcementLevel {
  STRICT = 'strict',
  ADVISORY = 'advisory',
  ADAPTIVE = 'adaptive',
  FALLBACK = 'fallback',
}

export function isEnforcementLevel(value: unknown): value is EnforcementLevel {
  return Object.values(EnforcementLevel).includes(value as EnforcementLevel);
}

export enum RuleType {
  CONTENT_FILTERING = 'content_filtering',
  PATTERN_MATCHING = 'pattern_matching',
  SEMANTIC_ANALYSIS = 'semantic_analysis',
  STRUCTURAL_VALIDATION = 'structural_validation',
  COMPLIANCE_CHECK = 'compliance_check',
  QUALITY_ASSESSMENT = 'quality_assessment',
  CUSTOM = 'custom',
}

export function isRuleType(value: unknown): value is RuleType {
  return Object.values(RuleType).includes(value as RuleType);
}

export enum RuleSeverity {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical',
}

export function isRuleSeverity(value: unknown): value is RuleSeverity {
  return Object.values(RuleSeverity).includes(value as RuleSeverity);
}

export enum RuleStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  DEPRECATED = 'deprecated',
  TESTING = 'testing',
}

export function isRuleStatus(value: unknown): value is RuleStatus {
  return Object.values(RuleStatus).includes(value as RuleStatus);
}

export enum ViolationType {
  KEYWORD_MATCH = 'keyword_match',
  REGEX_MATCH = 'regex_match',
  SEMANTIC_VIOLATION = 'semantic_violation',
  STRUCTURAL_VIOLATION = 'structural_violation',
  COMPLIANCE_VIOLATION = 'compliance_violation',
  QUALITY_VIOLATION = 'quality_violation',
  CUSTOM_VIOLATION = 'custom_violation',
}

export function isViolationType(value: unknown): value is ViolationType {
  return Object.values(ViolationType).includes(value as ViolationType);
}

export enum ActionTaken {
  NONE = 'none',
  WARNING = 'warning',
  SUGGESTION = 'suggestion',
  BLOCK = 'block',
  REDACT = 'redact',
  QUARANTINE = 'quarantine',
  ESCALATE = 'escalate',
}

export function isActionTaken(value: unknown): value is ActionTaken {
  return Object.values(ActionTaken).includes(value as ActionTaken);
}

export enum ConflictType {
  RULE_CONFLICT = 'rule_conflict',
  PRIORITY_CONFLICT = 'priority_conflict',
  SEMANTIC_CONFLICT = 'semantic_conflict',
  CONTEXT_CONFLICT = 'context_conflict',
  LOGICAL_CONTRADICTION = 'logical_contradiction',
  MUTUAL_EXCLUSIVITY = 'mutual_exclusivity',
}

export function isConflictType(value: unknown): value is ConflictType {
  return Object.values(ConflictType).includes(value as ConflictType);
}

export enum ResolutionStrategy {
  PRIORITY_BASED = 'priority_based',
  CONTEXT_AWARE = 'context_aware',
  USER_PREFERENCE = 'user_preference',
  FALLBACK = 'fallback',
  HYBRID = 'hybrid',
  HUMAN_REVIEW = 'human_review',
}

export function isResolutionStrategy(value: unknown): value is ResolutionStrategy {
  return Object.values(ResolutionStrategy).includes(value as ResolutionStrategy);
}

export enum ConflictSeverity {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical',
}

export function isConflictSeverity(value: unknown): value is ConflictSeverity {
  return Object.values(ConflictSeverity).includes(value as ConflictSeverity);
}

export enum AlertSeverity {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  CRITICAL = 'critical',
}

export function isAlertSeverity(value: unknown): value is AlertSeverity {
  return Object.values(AlertSeverity).includes(value as AlertSeverity);
}

export enum AlertStatus {
  TRIGGERED = 'triggered',
  ACKNOWLEDGED = 'acknowledged',
  RESOLVED = 'resolved',
  DISMISSED = 'dismissed',
  ESCALATED = 'escalated',
}

export enum AuditAction {
  CREATE = 'create',
  READ = 'read',
  UPDATE = 'update',
  DELETE = 'delete',
  ACTIVATE = 'activate',
  DEACTIVATE = 'deactivate',
  EVALUATE = 'evaluate',
  RESOLVE = 'resolve',
  ESCALATE = 'escalate',
  OVERRIDE = 'override',
  EXPORT = 'export',
  IMPORT = 'import',
  CONFIGURE = 'configure',
  VALIDATE = 'validate',
  APPROVE = 'approve',
  REJECT = 'reject',
  SYSTEM = 'system',
}

export enum AuditCategory {
  RULE = 'rule',
  CONFLICT = 'conflict',
  VIOLATION = 'violation',
  VALIDATION = 'validation',
  CONFIGURATION = 'configuration',
  SYSTEM = 'system',
  SECURITY = 'security',
  COMPLIANCE = 'compliance',
  USER = 'user',
}

export enum AuditSeverity {
  DEBUG = 'debug',
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  CRITICAL = 'critical',
}

export interface RulePattern {
  type: RuleType;
  keywords: string[];
  regex_patterns: string[];
  ml_model?: string;
  confidence_threshold: number;
  action: string;
}

export function createRulePattern(data: Partial<RulePattern>): RulePattern {
  return {
    type: data.type ?? RuleType.CONTENT_FILTERING,
    keywords: data.keywords ?? [],
    regex_patterns: data.regex_patterns ?? [],
    confidence_threshold: data.confidence_threshold ?? 0.7,
    action: data.action ?? 'warn',
    ...data,
  };
}

export function validateRulePattern(pattern: RulePattern): string[] {
  const errors: string[] = [];
  if (!isRuleType(pattern.type)) {
    errors.push('Invalid rule type');
  }
  if (pattern.confidence_threshold < 0 || pattern.confidence_threshold > 1) {
    errors.push('Confidence threshold must be between 0 and 1');
  }
  return errors;
}

export function isRulePattern(value: unknown): value is RulePattern {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return isRuleType(obj.type) && Array.isArray(obj.keywords) && Array.isArray(obj.regex_patterns);
}

export interface Rule {
  id: string;
  name: string;
  description: string;
  tier: RuleTier;
  rule_type: RuleType;
  severity: RuleSeverity;
  status: RuleStatus;
  patterns: RulePattern[];
  conditions: Record<string, unknown>;
  exceptions: string[];
  enforcement_level: EnforcementLevel;
  auto_block: boolean;
  user_override: boolean;
  override_justification_required: boolean;
  version: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  tags: string[];
  priority: number;
  timeout_ms: number;
  cache_ttl_seconds: number;
}

export function createRule(data: Partial<Rule>): Rule {
  return {
    id: data.id ?? uuidv4(),
    name: data.name ?? '',
    description: data.description ?? '',
    tier: data.tier ?? RuleTier.SAFETY,
    rule_type: data.rule_type ?? RuleType.CONTENT_FILTERING,
    severity: data.severity ?? RuleSeverity.MEDIUM,
    status: data.status ?? RuleStatus.ACTIVE,
    patterns: data.patterns ?? [],
    conditions: data.conditions ?? {},
    exceptions: data.exceptions ?? [],
    enforcement_level: data.enforcement_level ?? EnforcementLevel.STRICT,
    auto_block: data.auto_block ?? false,
    user_override: data.user_override ?? true,
    override_justification_required: data.override_justification_required ?? false,
    version: data.version ?? '1.0.0',
    created_at: data.created_at ?? new Date().toISOString(),
    updated_at: data.updated_at ?? new Date().toISOString(),
    tags: data.tags ?? [],
    priority: data.priority ?? 100,
    timeout_ms: data.timeout_ms ?? 1000,
    cache_ttl_seconds: data.cache_ttl_seconds ?? 300,
  };
}

export function validateRule(rule: Rule): string[] {
  const errors: string[] = [];
  if (!rule.id || rule.id.trim().length === 0) {
    errors.push('Rule ID cannot be empty');
  }
  if (!rule.name || rule.name.trim().length === 0) {
    errors.push('Rule name cannot be empty');
  }
  if (!isRuleTier(rule.tier)) {
    errors.push('Invalid rule tier');
  }
  if (!isRuleType(rule.rule_type)) {
    errors.push('Invalid rule type');
  }
  if (!isRuleSeverity(rule.severity)) {
    errors.push('Invalid rule severity');
  }
  if (!isRuleStatus(rule.status)) {
    errors.push('Invalid rule status');
  }
  if (!isEnforcementLevel(rule.enforcement_level)) {
    errors.push('Invalid enforcement level');
  }
  if (rule.priority < 1 || rule.priority > 1000) {
    errors.push('Priority must be between 1 and 1000');
  }
  if (rule.timeout_ms < 1 || rule.timeout_ms > 10000) {
    errors.push('Timeout must be between 1 and 10000 ms');
  }
  if (rule.cache_ttl_seconds < 0 || rule.cache_ttl_seconds > 86400) {
    errors.push('Cache TTL must be between 0 and 86400 seconds');
  }
  return errors;
}

export function isRule(value: unknown): value is Rule {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.id === 'string' &&
    typeof obj.name === 'string' &&
    isRuleTier(obj.tier) &&
    isRuleType(obj.rule_type) &&
    isRuleSeverity(obj.severity) &&
    isRuleStatus(obj.status)
  );
}

export function ruleToDict(rule: Rule): Record<string, unknown> {
  return { ...rule };
}

export const RULE_SEVERITY_ORDER: Record<string, number> = {
  [RuleSeverity.LOW]: 1,
  [RuleSeverity.MEDIUM]: 2,
  [RuleSeverity.HIGH]: 3,
  [RuleSeverity.CRITICAL]: 4,
};

export interface RuleSet {
  id: string;
  name: string;
  description: string;
  rules: Rule[];
  tier: RuleTier;
  status: RuleStatus;
  version: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  auto_discovery: boolean;
  conflict_resolution: string;
  evaluation_order: string;
}

export function createRuleSet(data: Partial<RuleSet>): RuleSet {
  return {
    id: data.id ?? uuidv4(),
    name: data.name ?? '',
    description: data.description ?? '',
    rules: data.rules ?? [],
    tier: data.tier ?? RuleTier.SAFETY,
    status: data.status ?? RuleStatus.ACTIVE,
    version: data.version ?? '1.0.0',
    created_at: data.created_at ?? new Date().toISOString(),
    updated_at: data.updated_at ?? new Date().toISOString(),
    auto_discovery: data.auto_discovery ?? true,
    conflict_resolution: data.conflict_resolution ?? 'priority_based',
    evaluation_order: data.evaluation_order ?? 'priority_desc',
  };
}

export function isRuleSet(value: unknown): value is RuleSet {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.id === 'string' && typeof obj.name === 'string' && Array.isArray(obj.rules) && isRuleTier(obj.tier);
}

export interface RuleContext {
  user_id?: string;
  session_id?: string;
  domain?: string;
  user_role?: string;
  content_type?: string;
  content_length?: number;
  language?: string;
  organization?: string;
  project?: string;
  business_process?: string;
  timestamp: string;
  time_zone?: string;
  metadata: Record<string, unknown>;
}

export function createRuleContext(data: Partial<RuleContext>): RuleContext {
  return {
    timestamp: data.timestamp ?? new Date().toISOString(),
    metadata: data.metadata ?? {},
    ...data,
  };
}

export function isRuleContext(value: unknown): value is RuleContext {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.timestamp === 'string';
}

export function contextToEffective(context: RuleContext): Record<string, unknown> {
  return {
    user_id: context.user_id,
    session_id: context.session_id,
    domain: context.domain,
    user_role: context.user_role,
    content_type: context.content_type,
    content_length: context.content_length,
    language: context.language,
    organization: context.organization,
    project: context.project,
    business_process: context.business_process,
    timestamp: context.timestamp,
    time_zone: context.time_zone,
    ...context.metadata,
  };
}

export function contextIsEmpty(context: RuleContext): boolean {
  return (
    !context.user_id &&
    !context.session_id &&
    !context.domain &&
    !context.user_role &&
    !context.content_type &&
    context.content_length === undefined &&
    !context.language &&
    !context.organization &&
    !context.project &&
    !context.business_process &&
    !context.time_zone &&
    Object.keys(context.metadata).length === 0
  );
}

export interface RuleEvaluationRequest {
  content: string;
  context?: RuleContext;
  rule_ids?: string[];
  tier?: RuleTier;
  rule_types?: RuleType[];
  options: Record<string, unknown>;
  timeout_ms: number;
  parallel_evaluation: boolean;
  early_termination: boolean;
}

export function createEvaluationRequest(data: Partial<RuleEvaluationRequest>): RuleEvaluationRequest {
  return {
    content: data.content ?? '',
    timeout_ms: data.timeout_ms ?? 1000,
    parallel_evaluation: data.parallel_evaluation ?? true,
    early_termination: data.early_termination ?? true,
    options: data.options ?? {},
    ...data,
  };
}

export function shouldEvaluateRule(request: RuleEvaluationRequest, rule: Rule): boolean {
  if (request.rule_ids && !request.rule_ids.includes(rule.id)) return false;
  if (request.tier && rule.tier !== request.tier) return false;
  if (request.rule_types && !request.rule_types.includes(rule.rule_type)) return false;
  return true;
}

export interface Violation {
  rule_id: string;
  rule_name: string;
  rule_tier: RuleTier;
  rule_severity: RuleSeverity;
  violation_type: ViolationType;
  matched_content?: string;
  matched_patterns: string[];
  confidence_score: number;
  position_info: Record<string, unknown>;
  action_taken: ActionTaken;
  blocked: boolean;
  user_override_allowed: boolean;
  override_justification?: string;
  explanation?: string;
  suggestions: string[];
  educational_content?: string;
  detected_at: string;
  detection_method: string;
  context: Record<string, unknown>;
}

export function createViolation(data: Partial<Violation>): Violation {
  return {
    rule_id: data.rule_id ?? '',
    rule_name: data.rule_name ?? '',
    rule_tier: data.rule_tier ?? RuleTier.SAFETY,
    rule_severity: data.rule_severity ?? RuleSeverity.MEDIUM,
    violation_type: data.violation_type ?? ViolationType.CUSTOM_VIOLATION,
    matched_patterns: data.matched_patterns ?? [],
    confidence_score: data.confidence_score ?? 0.0,
    position_info: data.position_info ?? {},
    action_taken: data.action_taken ?? ActionTaken.NONE,
    blocked: data.blocked ?? false,
    user_override_allowed: data.user_override_allowed ?? false,
    suggestions: data.suggestions ?? [],
    detected_at: data.detected_at ?? new Date().toISOString(),
    detection_method: data.detection_method ?? 'automatic',
    context: data.context ?? {},
    ...data,
  };
}

export function isViolation(value: unknown): value is Violation {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.rule_id === 'string' &&
    typeof obj.rule_name === 'string' &&
    isRuleTier(obj.rule_tier) &&
    isRuleSeverity(obj.rule_severity) &&
    isViolationType(obj.violation_type)
  );
}

export function violationToSummary(v: Violation): Record<string, unknown> {
  return {
    rule_id: v.rule_id,
    rule_name: v.rule_name,
    rule_tier: v.rule_tier,
    rule_severity: v.rule_severity,
    violation_type: v.violation_type,
    action_taken: v.action_taken,
    blocked: v.blocked,
    confidence: Math.round(v.confidence_score * 100) / 100,
    critical: v.rule_severity === RuleSeverity.CRITICAL,
  };
}

export interface Suggestion {
  type: string;
  title: string;
  description: string;
  confidence: number;
  original_text?: string;
  suggested_text?: string;
  reasoning?: string;
  auto_applicable: boolean;
  user_approval_required: boolean;
  implementation_steps: string[];
  source_rule?: string;
  created_at: string;
}

export function isSuggestion(value: unknown): value is Suggestion {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.type === 'string' && typeof obj.title === 'string' && typeof obj.description === 'string';
}

export interface ValidationResult {
  valid: boolean;
  total_score: number;
  confidence: number;
  total_rules_evaluated: number;
  rules_triggered: number;
  rules_violated: number;
  violations: Violation[];
  critical_violations: Violation[];
  warnings: Violation[];
  suggestions: Suggestion[];
  processing_time_ms: number;
  rules_by_tier: Record<string, number>;
  processing_details: Record<string, unknown>;
  request_id?: string;
  content_hash?: string;
  evaluated_at: string;
  evaluator_version: string;
}

export function createValidationResult(data: Partial<ValidationResult>): ValidationResult {
  return {
    valid: data.valid ?? true,
    total_score: data.total_score ?? 1.0,
    confidence: data.confidence ?? 1.0,
    total_rules_evaluated: data.total_rules_evaluated ?? 0,
    rules_triggered: data.rules_triggered ?? 0,
    rules_violated: data.rules_violated ?? 0,
    violations: data.violations ?? [],
    critical_violations: data.critical_violations ?? [],
    warnings: data.warnings ?? [],
    suggestions: data.suggestions ?? [],
    processing_time_ms: data.processing_time_ms ?? 0,
    rules_by_tier: data.rules_by_tier ?? {},
    processing_details: data.processing_details ?? {},
    evaluated_at: data.evaluated_at ?? new Date().toISOString(),
    evaluator_version: data.evaluator_version ?? '1.0.0',
    ...data,
  };
}

export function isValidationResult(value: unknown): value is ValidationResult {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.valid === 'boolean' && Array.isArray(obj.violations);
}

export function resultHasViolations(result: ValidationResult): boolean {
  return result.violations.length > 0;
}

export function resultIsBlocked(result: ValidationResult): boolean {
  return result.violations.some((v) => v.blocked);
}

export function resultGetViolationsByTier(result: ValidationResult): Record<string, Violation[]> {
  const grouped: Record<string, Violation[]> = {};
  for (const v of result.violations) {
    const tier = v.rule_tier;
    if (!grouped[tier]) grouped[tier] = [];
    grouped[tier].push(v);
  }
  return grouped;
}

export function resultGetViolationsBySeverity(result: ValidationResult): Record<string, Violation[]> {
  const grouped: Record<string, Violation[]> = {};
  for (const v of result.violations) {
    const sev = v.rule_severity;
    if (!grouped[sev]) grouped[sev] = [];
    grouped[sev].push(v);
  }
  return grouped;
}

export function resultGetSummary(result: ValidationResult): Record<string, unknown> {
  return {
    valid: result.valid,
    blocked: resultIsBlocked(result),
    score: result.total_score,
    violations_count: result.violations.length,
    critical_violations: result.critical_violations.length,
    warnings_count: result.warnings.length,
    suggestions_count: result.suggestions.length,
    rules_evaluated: result.total_rules_evaluated,
    processing_time_ms: result.processing_time_ms,
    violations_by_tier: resultGetViolationsByTier(result),
    violations_by_severity: resultGetViolationsBySeverity(result),
  };
}

export function resultGetTopViolations(result: ValidationResult, n = 5): Violation[] {
  const sorted = [...result.violations].sort((a, b) => {
    const aScore = (a.rule_severity === RuleSeverity.CRITICAL ? 1 : 0) + a.confidence_score;
    const bScore = (b.rule_severity === RuleSeverity.CRITICAL ? 1 : 0) + b.confidence_score;
    return bScore - aScore;
  });
  return sorted.slice(0, n);
}

export function resultGetScoreBreakdown(result: ValidationResult): Record<string, number> {
  const tierPenalties = (resultGetViolationsByTier(result)[RuleTier.SAFETY]?.length ?? 0) * 0.3;
  const severityPenalties = result.critical_violations.length * 0.2 + result.warnings.length * 0.05;
  const totalPenalty = Math.min(tierPenalties + severityPenalties, 1.0);
  return {
    base_score: 1.0,
    tier_penalty: Math.round(tierPenalties * 1000) / 1000,
    severity_penalty: Math.round(severityPenalties * 1000) / 1000,
    total_penalty: Math.round(totalPenalty * 1000) / 1000,
    final_score: Math.round(Math.max(1.0 - totalPenalty, 0.0) * 1000) / 1000,
  };
}

export function resultMerge(a: ValidationResult, b: ValidationResult): ValidationResult {
  return {
    ...a,
    valid: a.critical_violations.length === 0,
    total_score: Math.min(a.total_score, b.total_score),
    confidence: (a.confidence + b.confidence) / 2,
    total_rules_evaluated: a.total_rules_evaluated + b.total_rules_evaluated,
    rules_triggered: a.rules_triggered + b.rules_triggered,
    rules_violated: a.rules_violated + b.rules_violated,
    violations: [...a.violations, ...b.violations],
    critical_violations: [...a.critical_violations, ...b.critical_violations],
    warnings: [...a.warnings, ...b.warnings],
    suggestions: [...a.suggestions, ...b.suggestions],
    processing_time_ms: a.processing_time_ms + b.processing_time_ms,
    rules_by_tier: mergeCountMaps(a.rules_by_tier, b.rules_by_tier),
    processing_details: { ...a.processing_details, ...b.processing_details },
  };
}

function mergeCountMaps(a: Record<string, number>, b: Record<string, number>): Record<string, number> {
  const result: Record<string, number> = { ...a };
  for (const [key, val] of Object.entries(b)) {
    result[key] = (result[key] ?? 0) + val;
  }
  return result;
}

export interface RuleConflict {
  conflict_id: string;
  conflict_type: ConflictType;
  severity: ConflictSeverity;
  rule_1: Rule;
  rule_2: Rule;
  additional_rules: Rule[];
  description: string;
  conflict_reason: string;
  contradictory_elements: string[];
  context_triggers: string[];
  detected_at: string;
  detection_method: string;
  confidence: number;
  resolution_strategy?: ResolutionStrategy;
  resolved: boolean;
  resolution_applied?: string;
  resolution_outcome?: string;
}

export function createRuleConflict(data: Partial<RuleConflict>): RuleConflict {
  return {
    conflict_id: data.conflict_id ?? uuidv4(),
    conflict_type: data.conflict_type ?? ConflictType.RULE_CONFLICT,
    severity: data.severity ?? ConflictSeverity.MEDIUM,
    rule_1: data.rule_1 ?? createRule({}),
    rule_2: data.rule_2 ?? createRule({}),
    additional_rules: data.additional_rules ?? [],
    description: data.description ?? '',
    conflict_reason: data.conflict_reason ?? '',
    contradictory_elements: data.contradictory_elements ?? [],
    context_triggers: data.context_triggers ?? [],
    detected_at: data.detected_at ?? new Date().toISOString(),
    detection_method: data.detection_method ?? 'automatic',
    confidence: data.confidence ?? 0.0,
    resolved: data.resolved ?? false,
    ...data,
  };
}

export function isRuleConflict(value: unknown): value is RuleConflict {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.conflict_id === 'string' && isConflictType(obj.conflict_type);
}

export interface ConflictResolution {
  resolution_id: string;
  conflict_id: string;
  strategy: ResolutionStrategy;
  description: string;
  reasoning: string;
  chosen_rule_id?: string;
  applied_action: string;
  parameters: Record<string, unknown>;
  custom_logic?: string;
  outcome: string;
  effectiveness_score: number;
  user_satisfaction?: number;
  applied_at: string;
  applied_by?: string;
  verified: boolean;
  verification_details?: string;
  feedback?: string;
  success_indicators: Record<string, boolean>;
  improvement_suggestions: string[];
}

export function createConflictResolution(data: Partial<ConflictResolution>): ConflictResolution {
  return {
    resolution_id: data.resolution_id ?? uuidv4(),
    conflict_id: data.conflict_id ?? '',
    strategy: data.strategy ?? ResolutionStrategy.PRIORITY_BASED,
    description: data.description ?? '',
    reasoning: data.reasoning ?? '',
    applied_action: data.applied_action ?? '',
    parameters: data.parameters ?? {},
    outcome: data.outcome ?? 'success',
    effectiveness_score: data.effectiveness_score ?? 0.0,
    applied_at: data.applied_at ?? new Date().toISOString(),
    verified: data.verified ?? false,
    success_indicators: data.success_indicators ?? {},
    improvement_suggestions: data.improvement_suggestions ?? [],
    ...data,
  };
}

export function isConflictResolution(value: unknown): value is ConflictResolution {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.resolution_id === 'string' && typeof obj.conflict_id === 'string' && isResolutionStrategy(obj.strategy);
}

export interface BatchValidationRequest {
  requests: string[];
  common_context?: Record<string, unknown>;
  batch_options: Record<string, unknown>;
  max_parallel: number;
  fail_fast: boolean;
  return_individual_results: boolean;
  aggregate_results: boolean;
}

export function createBatchValidationRequest(data: Partial<BatchValidationRequest>): BatchValidationRequest {
  return {
    requests: data.requests ?? [],
    batch_options: data.batch_options ?? {},
    max_parallel: data.max_parallel ?? 10,
    fail_fast: data.fail_fast ?? false,
    return_individual_results: data.return_individual_results ?? true,
    aggregate_results: data.aggregate_results ?? true,
    ...data,
  };
}

export interface BatchValidationResult {
  total_items: number;
  valid_items: number;
  blocked_items: number;
  items_with_violations: number;
  individual_results: ValidationResult[];
  total_processing_time_ms: number;
  average_processing_time_ms: number;
  total_violations: number;
  total_suggestions: number;
  batch_id?: string;
  started_at: string;
  completed_at?: string;
}

export function createBatchValidationResult(data: Partial<BatchValidationResult>): BatchValidationResult {
  return {
    total_items: data.total_items ?? 0,
    valid_items: data.valid_items ?? 0,
    blocked_items: data.blocked_items ?? 0,
    items_with_violations: data.items_with_violations ?? 0,
    individual_results: data.individual_results ?? [],
    total_processing_time_ms: data.total_processing_time_ms ?? 0,
    average_processing_time_ms: data.average_processing_time_ms ?? 0.0,
    total_violations: data.total_violations ?? 0,
    total_suggestions: data.total_suggestions ?? 0,
    started_at: data.started_at ?? new Date().toISOString(),
    ...data,
  };
}

export function batchResultGetSuccessRate(result: BatchValidationResult): number {
  if (result.total_items === 0) return 0;
  return (result.valid_items / result.total_items) * 100;
}

export function batchResultGetSummary(result: BatchValidationResult): Record<string, unknown> {
  return {
    batch_id: result.batch_id,
    total_items: result.total_items,
    valid_items: result.valid_items,
    blocked_items: result.blocked_items,
    items_with_violations: result.items_with_violations,
    success_rate: Math.round(batchResultGetSuccessRate(result) * 100) / 100,
    total_violations: result.total_violations,
    total_suggestions: result.total_suggestions,
    avg_processing_time_ms: Math.round(result.average_processing_time_ms * 100) / 100,
    total_processing_time_ms: result.total_processing_time_ms,
  };
}

export interface AlertDefinition {
  alert_id: string;
  name: string;
  description?: string;
  alert_type: string;
  severity: AlertSeverity;
  metric_name: string;
  metric_source: string;
  comparison_operator: string;
  threshold_value: number;
  duration_seconds: number;
  evaluation_window_minutes: number;
  cooldown_minutes: number;
  max_alerts_per_hour: number;
  notification_channels: string[];
  escalation_levels: Record<string, unknown>[];
  auto_resolve_minutes?: number;
  is_active: boolean;
  is_system_alert: boolean;
  enabled_environments: string[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export function createAlertDefinition(data: Partial<AlertDefinition>): AlertDefinition {
  return {
    alert_id: data.alert_id ?? uuidv4(),
    name: data.name ?? '',
    alert_type: data.alert_type ?? 'threshold',
    severity: data.severity ?? AlertSeverity.WARNING,
    metric_name: data.metric_name ?? '',
    metric_source: data.metric_source ?? 'system',
    comparison_operator: data.comparison_operator ?? 'greater_than',
    threshold_value: data.threshold_value ?? 0.0,
    duration_seconds: data.duration_seconds ?? 60,
    evaluation_window_minutes: data.evaluation_window_minutes ?? 5,
    cooldown_minutes: data.cooldown_minutes ?? 10,
    max_alerts_per_hour: data.max_alerts_per_hour ?? 10,
    notification_channels: data.notification_channels ?? ['log'],
    escalation_levels: data.escalation_levels ?? [],
    is_active: data.is_active ?? true,
    is_system_alert: data.is_system_alert ?? false,
    enabled_environments: data.enabled_environments ?? [],
    created_at: data.created_at ?? new Date().toISOString(),
    updated_at: data.updated_at ?? new Date().toISOString(),
    metadata: data.metadata ?? {},
    tags: data.tags ?? [],
    ...data,
  };
}

export function evaluateAlertCondition(definition: AlertDefinition, currentValue: number): boolean {
  switch (definition.comparison_operator) {
    case 'greater_than': return currentValue > definition.threshold_value;
    case 'less_than': return currentValue < definition.threshold_value;
    case 'equal_to': return currentValue === definition.threshold_value;
    case 'not_equal_to': return currentValue !== definition.threshold_value;
    case 'greater_than_or_equal': return currentValue >= definition.threshold_value;
    case 'less_than_or_equal': return currentValue <= definition.threshold_value;
    case 'percentage_change':
      return Math.abs(currentValue - definition.threshold_value) / Math.max(definition.threshold_value, 0.001) > 0.1;
    default: return false;
  }
}

export interface AlertEvent {
  event_id: string;
  alert_id: string;
  alert_name: string;
  severity: AlertSeverity;
  status: AlertStatus;
  metric_name: string;
  metric_value: number;
  threshold_value: number;
  comparison_operator: string;
  message: string;
  details: Record<string, unknown>;
  context: Record<string, unknown>;
  triggered_at: string;
  acknowledged_at?: string;
  resolved_at?: string;
  dismissed_at?: string;
  escalated_at?: string;
  acknowledged_by?: string;
  resolved_by?: string;
  resolution_notes?: string;
  consecutive_occurrence: number;
  source: string;
  environment?: string;
  host?: string;
  service?: string;
  related_event_ids: string[];
  tags: string[];
  metadata: Record<string, unknown>;
}

export function isAlertActive(event: AlertEvent): boolean {
  return event.status === AlertStatus.TRIGGERED || event.status === AlertStatus.ACKNOWLEDGED || event.status === AlertStatus.ESCALATED;
}

export interface MetricsSnapshot {
  snapshot_id: string;
  source: string;
  timestamp: string;
  metrics: Record<string, number>;
  labels: Record<string, string>;
  tags: string[];
  host?: string;
  service?: string;
  environment?: string;
  region?: string;
  cpu_usage_percent?: number;
  memory_usage_percent?: number;
  disk_usage_percent?: number;
  network_in_bytes?: number;
  network_out_bytes?: number;
  request_count?: number;
  error_count?: number;
  average_latency_ms?: number;
  p99_latency_ms?: number;
  rule_evaluation_count?: number;
  violation_count?: number;
  blocked_count?: number;
  active_rule_count?: number;
  conflict_count?: number;
  unresolved_conflict_count?: number;
  processing_queue_depth?: number;
  cache_hit_rate?: number;
  cache_miss_count?: number;
  custom_metrics: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export function createMetricsSnapshot(data: Partial<MetricsSnapshot>): MetricsSnapshot {
  return {
    snapshot_id: data.snapshot_id ?? uuidv4(),
    source: data.source ?? 'system',
    timestamp: data.timestamp ?? new Date().toISOString(),
    metrics: data.metrics ?? {},
    labels: data.labels ?? {},
    tags: data.tags ?? [],
    custom_metrics: data.custom_metrics ?? {},
    metadata: data.metadata ?? {},
    ...data,
  };
}

export function snapshotGetAllMetrics(snapshot: MetricsSnapshot): Record<string, number> {
  const result: Record<string, number> = { ...snapshot.metrics };
  const fields: (keyof MetricsSnapshot)[] = [
    'cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent',
    'network_in_bytes', 'network_out_bytes', 'request_count', 'error_count',
    'average_latency_ms', 'p99_latency_ms', 'rule_evaluation_count',
    'violation_count', 'blocked_count', 'active_rule_count', 'conflict_count',
    'unresolved_conflict_count', 'processing_queue_depth', 'cache_hit_rate', 'cache_miss_count',
  ];
  for (const field of fields) {
    const val = snapshot[field];
    if (val !== undefined && val !== null) {
      result[field] = Number(val);
    }
  }
  return result;
}

export function snapshotGetSummary(snapshot: MetricsSnapshot): Record<string, unknown> {
  const allMetrics = snapshotGetAllMetrics(snapshot);
  return {
    snapshot_id: snapshot.snapshot_id,
    source: snapshot.source,
    timestamp: snapshot.timestamp,
    metric_count: Object.keys(allMetrics).length,
    key_metrics: {
      request_count: allMetrics.request_count,
      error_count: allMetrics.error_count,
      average_latency_ms: allMetrics.average_latency_ms,
      violation_count: allMetrics.violation_count,
      blocked_count: allMetrics.blocked_count,
      cache_hit_rate: allMetrics.cache_hit_rate,
    },
    host: snapshot.host,
    service: snapshot.service,
    environment: snapshot.environment,
  };
}

export interface DashboardConfig {
  dashboard_id: string;
  name: string;
  description?: string;
  dashboard_type: string;
  layout: string;
  refresh_interval_seconds: number;
  time_range_default: string;
  widgets: Record<string, unknown>[];
  metric_sources: string[];
  data_filters: Record<string, unknown>;
  variables: Record<string, unknown>;
  is_default: boolean;
  is_public: boolean;
  is_active: boolean;
  owner?: string;
  allowed_roles: string[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  theme?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface AuditEvent {
  event_id: string;
  event_type: string;
  category: AuditCategory;
  action: AuditAction;
  severity: AuditSeverity;
  actor: string;
  actor_type: string;
  actor_id?: string;
  resource_type?: string;
  resource_id?: string;
  resource_name?: string;
  summary: string;
  description?: string;
  details: Record<string, unknown>;
  previous_value?: unknown;
  new_value?: unknown;
  changes: Record<string, unknown>[];
  outcome: string;
  reason?: string;
  error_message?: string;
  timestamp: string;
  ip_address?: string;
  user_agent?: string;
  session_id?: string;
  correlation_id?: string;
  source: string;
  environment?: string;
  host?: string;
  service?: string;
  related_event_ids: string[];
  tags: string[];
  metadata: Record<string, unknown>;
}

export function createAuditEvent(data: Partial<AuditEvent>): AuditEvent {
  return {
    event_id: data.event_id ?? uuidv4(),
    event_type: data.event_type ?? '',
    category: data.category ?? AuditCategory.SYSTEM,
    action: data.action ?? AuditAction.SYSTEM,
    severity: data.severity ?? AuditSeverity.INFO,
    actor: data.actor ?? 'system',
    actor_type: data.actor_type ?? 'system',
    summary: data.summary ?? '',
    changes: data.changes ?? [],
    outcome: data.outcome ?? 'success',
    timestamp: data.timestamp ?? new Date().toISOString(),
    source: data.source ?? 'system',
    related_event_ids: data.related_event_ids ?? [],
    tags: data.tags ?? [],
    metadata: data.metadata ?? {},
    details: data.details ?? {},
    ...data,
  };
}

export function isAuditEvent(value: unknown): value is AuditEvent {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.event_id === 'string' && typeof obj.summary === 'string' && typeof obj.timestamp === 'string';
}

export interface AuditTrail {
  trail_id: string;
  name: string;
  description?: string;
  trail_type: string;
  events: AuditEvent[];
  event_count: number;
  unique_actors: string[];
  unique_resources: string[];
  categories: Record<string, number>;
  actions: Record<string, number>;
  period_start?: string;
  period_end?: string;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  is_immutable: boolean;
  retention_days: number;
  size_bytes: number;
  source: string;
  environment?: string;
  metadata: Record<string, unknown>;
}

export function createAuditTrail(data: Partial<AuditTrail>): AuditTrail {
  return {
    trail_id: data.trail_id ?? uuidv4(),
    name: data.name ?? '',
    trail_type: data.trail_type ?? 'continuous',
    events: data.events ?? [],
    event_count: data.event_count ?? 0,
    unique_actors: data.unique_actors ?? [],
    unique_resources: data.unique_resources ?? [],
    categories: data.categories ?? {},
    actions: data.actions ?? {},
    created_at: data.created_at ?? new Date().toISOString(),
    updated_at: data.updated_at ?? new Date().toISOString(),
    is_active: data.is_active ?? true,
    is_immutable: data.is_immutable ?? false,
    retention_days: data.retention_days ?? 90,
    size_bytes: data.size_bytes ?? 0,
    source: data.source ?? 'system',
    metadata: data.metadata ?? {},
    ...data,
  };
}

export interface RuleStats {
  rule_id: string;
  evaluation_count: number;
  violation_count: number;
  override_count: number;
  block_count: number;
  suggestion_count: number;
  escalation_count: number;
  total_processing_time_ms: number;
  average_processing_time_ms: number;
  min_processing_time_ms: number;
  max_processing_time_ms: number;
  last_evaluated_at?: string;
  first_evaluated_at?: string;
  violation_rate: number;
  override_rate: number;
  block_rate: number;
  daily_counts: Record<string, number>;
  weekly_counts: Record<string, number>;
  monthly_counts: Record<string, number>;
  violation_types: Record<string, number>;
  top_contexts: Record<string, unknown>[];
  peak_hours: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export function createRuleStats(data: Partial<RuleStats>): RuleStats {
  return {
    rule_id: data.rule_id ?? '',
    evaluation_count: data.evaluation_count ?? 0,
    violation_count: data.violation_count ?? 0,
    override_count: data.override_count ?? 0,
    block_count: data.block_count ?? 0,
    suggestion_count: data.suggestion_count ?? 0,
    escalation_count: data.escalation_count ?? 0,
    total_processing_time_ms: data.total_processing_time_ms ?? 0,
    average_processing_time_ms: data.average_processing_time_ms ?? 0.0,
    min_processing_time_ms: data.min_processing_time_ms ?? 0,
    max_processing_time_ms: data.max_processing_time_ms ?? 0,
    violation_rate: data.violation_rate ?? 0.0,
    override_rate: data.override_rate ?? 0.0,
    block_rate: data.block_rate ?? 0.0,
    daily_counts: data.daily_counts ?? {},
    weekly_counts: data.weekly_counts ?? {},
    monthly_counts: data.monthly_counts ?? {},
    violation_types: data.violation_types ?? {},
    top_contexts: data.top_contexts ?? [],
    peak_hours: data.peak_hours ?? {},
    created_at: data.created_at ?? new Date().toISOString(),
    updated_at: data.updated_at ?? new Date().toISOString(),
    ...data,
  };
}

export interface RuleTemplate {
  template_id: string;
  name: string;
  description: string;
  template_content: string;
  variables: Record<string, string>;
  default_values: Record<string, string>;
  constraints: Record<string, unknown>;
  rule_type: RuleType;
  tier: RuleTier;
  severity: RuleSeverity;
  enforcement_level: EnforcementLevel;
  category: string;
  version: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  tags: string[];
  usage_count: number;
  is_deprecated: boolean;
}

export interface RuleGroup {
  group_id: string;
  name: string;
  description: string;
  rule_ids: string[];
  rules: Rule[];
  parent_group_id?: string;
  child_group_ids: string[];
  group_type: string;
  category: string;
  priority: number;
  is_system_group: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface ComplianceReport {
  report_id: string;
  generated_at: string;
  period_start: string;
  period_end: string;
  total_evaluations: number;
  compliant_evaluations: number;
  non_compliant_evaluations: number;
  compliance_rate: number;
  violations_by_tier: Record<string, number>;
  violations_by_severity: Record<string, number>;
  violations_by_type: Record<string, number>;
  average_processing_time_ms: number;
  peak_processing_time_ms: number;
  total_processing_time_ms: number;
  trends: Record<string, unknown>;
  recommendations: string[];
}

export interface ValidationProfile {
  profile_id: string;
  name: string;
  description?: string;
  profile_type: string;
  owner?: string;
  organization?: string;
  enabled_tiers: RuleTier[];
  enabled_rule_types: string[];
  excluded_rule_ids: string[];
  severity_overrides: Record<string, string>;
  enforcement_overrides: Record<string, string>;
  timeout_ms: number;
  parallel_evaluation: boolean;
  early_termination: boolean;
  max_violations: number;
  is_default: boolean;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface ValidationThreshold {
  threshold_id: string;
  name: string;
  description?: string;
  threshold_type: string;
  min_score: number;
  max_score: number;
  warning_score: number;
  critical_score: number;
  max_violations: number;
  max_critical_violations: number;
  max_warnings: number;
  max_processing_time_ms: number;
  min_confidence: number;
  max_suggestions: number;
  is_strict: boolean;
  is_default: boolean;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
}

export interface MonitorConfig {
  monitor_id: string;
  name: string;
  description?: string;
  monitor_type: string;
  target: string;
  interval_seconds: number;
  metrics: string[];
  alert_definitions: string[];
  data_sources: Record<string, unknown>;
  enabled: boolean;
  is_system_monitor: boolean;
  log_level: string;
  retry_on_failure: boolean;
  max_retries: number;
  timeout_seconds: number;
  health_check_path?: string;
  health_check_interval_seconds: number;
  notification_channels: string[];
  escalation_contacts: string[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface MetricsThreshold {
  threshold_id: string;
  name: string;
  description?: string;
  metric_name: string;
  metric_source: string;
  warning_value: number;
  critical_value: number;
  comparison_operator: string;
  evaluation_window_seconds: number;
  consecutive_hits_required: number;
  cooldown_seconds: number;
  is_active: boolean;
  is_default: boolean;
  auto_recovery: boolean;
  recovery_value?: number;
  severity: string;
  alert_definition_id?: string;
  notification_channels: string[];
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface DashboardWidget {
  widget_id: string;
  name: string;
  description?: string;
  widget_type: string;
  data_source: string;
  metric_names: string[];
  width: number;
  height: number;
  position_x: number;
  position_y: number;
  chart_type: string;
  aggregation: string;
  group_by?: string;
  color_scheme?: string;
  show_legend: boolean;
  show_thresholds: boolean;
  threshold_ids: string[];
  visual_settings: Record<string, unknown>;
  query_filter: Record<string, unknown>;
  time_range?: string;
  refresh_interval_seconds?: number;
  cache_ttl_seconds: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  tags: string[];
}

export interface SdkOptions {
  apiKey: string;
  baseUrl: string;
  timeout?: number;
  retryConfig?: RetryConfig;
}

export interface RetryConfig {
  maxRetries: number;
  baseDelayMs: number;
  maxDelayMs: number;
  retryableStatuses: number[];
}

export const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  baseDelayMs: 200,
  maxDelayMs: 5000,
  retryableStatuses: [408, 429, 500, 502, 503, 504],
};

export interface SdkResponse<T> {
  success: boolean;
  data?: T;
  error?: SdkError;
  requestId?: string;
  durationMs: number;
}

export interface SdkError {
  code: string;
  message: string;
  details?: unknown;
  statusCode?: number;
}

export class SdkClientError extends Error {
  public readonly code: string;
  public readonly statusCode?: number;
  public readonly details?: unknown;

  constructor(message: string, code = 'INTERNAL_ERROR', statusCode?: number, details?: unknown) {
    super(message);
    this.name = 'SdkClientError';
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

export class SdkValidationError extends SdkClientError {
  constructor(message: string, details?: unknown) {
    super(message, 'VALIDATION_ERROR', 400, details);
    this.name = 'SdkValidationError';
  }
}

export class SdkAuthError extends SdkClientError {
  constructor(message = 'Authentication failed') {
    super(message, 'AUTH_ERROR', 401);
    this.name = 'SdkAuthError';
  }
}

export class SdkNotFoundError extends SdkClientError {
  constructor(resource: string, id: string) {
    super(`${resource} not found: ${id}`, 'NOT_FOUND', 404);
    this.name = 'SdkNotFoundError';
  }
}

export class SdkRateLimitError extends SdkClientError {
  public readonly retryAfterMs: number;

  constructor(retryAfterMs = 1000) {
    super('Rate limit exceeded', 'RATE_LIMIT', 429);
    this.name = 'SdkRateLimitError';
    this.retryAfterMs = retryAfterMs;
  }
}

export class SdkTimeoutError extends SdkClientError {
  constructor(timeoutMs: number) {
    super(`Request timed out after ${timeoutMs}ms`, 'TIMEOUT', 408);
    this.name = 'SdkTimeoutError';
  }
}

export type ContentCheckResult = ValidationResult;
export type ComplianceCheckResult = ValidationResult;
export type SafetyCheckResult = ValidationResult;
export type FormatCheckResult = { valid: boolean; format: string; errors: string[] };
export type QualityCheckResult = { score: number; issues: string[]; suggestions: string[] };
export type HallucinationResult = { detected: boolean; confidence: number; segments: string[] };
