/**
 * RuleEngineClient - Specialized client for rule evaluation and management.
 * Provides tier-specific evaluation, batching, caching, and error recovery.
 */

import {
  Rule,
  RuleTier,
  RuleType,
  RuleStatus,
  RuleContext,
  RuleSet,
  RulePattern,
  ValidationResult,
  Violation,
  Suggestion,
  RuleEvaluationRequest,
  SdkOptions,
  SdkClientError,
  SdkValidationError,
  SdkNotFoundError,
  SdkTimeoutError,
  SdkAuthError,
  createRule,
  createRuleContext,
  createValidationResult,
  createEvaluationRequest,
  shouldEvaluateRule,
  contextToEffective,
  resultGetSummary,
  resultHasViolations,
  resultIsBlocked,
  resultGetTopViolations,
  resultMerge,
  RetryConfig,
  DEFAULT_RETRY_CONFIG,
} from './models';

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

interface RuleEngineOptions {
  apiKey: string;
  baseUrl: string;
  timeout?: number;
  retryConfig?: RetryConfig;
  cacheTtlMs?: number;
  maxCacheSize?: number;
  batchSize?: number;
  maxConcurrent?: number;
}

const DEFAULT_ENGINE_OPTIONS: Partial<RuleEngineOptions> = {
  timeout: 15000,
  cacheTtlMs: 300000,
  maxCacheSize: 1000,
  batchSize: 50,
  maxConcurrent: 10,
};

export class RuleEngineClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly retryConfig: RetryConfig;
  private readonly cacheTtlMs: number;
  private readonly maxCacheSize: number;
  private readonly batchSize: number;
  private readonly maxConcurrent: number;

  private ruleCache: Map<string, CacheEntry<Rule>> = new Map();
  private rulesetCache: Map<string, CacheEntry<RuleSet>> = new Map();
  private listCache: Map<string, CacheEntry<Rule[]>> = new Map();
  private pendingRequests: Map<string, Promise<Rule>> = new Map();

  private requestCount = 0;
  private cacheHits = 0;
  private cacheMisses = 0;

  constructor(options: RuleEngineOptions) {
    if (!options.apiKey || options.apiKey.trim().length === 0) {
      throw new SdkValidationError('API key is required');
    }
    if (!options.baseUrl || options.baseUrl.trim().length === 0) {
      throw new SdkValidationError('Base URL is required');
    }

    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.timeout = options.timeout ?? DEFAULT_ENGINE_OPTIONS.timeout!;
    this.retryConfig = { ...DEFAULT_RETRY_CONFIG, ...options.retryConfig };
    this.cacheTtlMs = options.cacheTtlMs ?? DEFAULT_ENGINE_OPTIONS.cacheTtlMs!;
    this.maxCacheSize = options.maxCacheSize ?? DEFAULT_ENGINE_OPTIONS.maxCacheSize!;
    this.batchSize = options.batchSize ?? DEFAULT_ENGINE_OPTIONS.batchSize!;
    this.maxConcurrent = options.maxConcurrent ?? DEFAULT_ENGINE_OPTIONS.maxConcurrent!;
  }

  private buildUrl(path: string): string {
    return `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  }

  private buildHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-API-Key': this.apiKey,
      'X-SDK-Version': '1.0.0',
      'X-SDK-Client': 'rule-engine',
    };
  }

  private getCacheKey(...parts: string[]): string {
    return parts.join(':');
  }

  private getFromCache<T>(cache: Map<string, CacheEntry<T>>, key: string): T | undefined {
    const entry = cache.get(key);
    if (!entry) {
      this.cacheMisses++;
      return undefined;
    }
    if (Date.now() > entry.expiresAt) {
      cache.delete(key);
      this.cacheMisses++;
      return undefined;
    }
    this.cacheHits++;
    return entry.data;
  }

  private setCache<T>(cache: Map<string, CacheEntry<T>>, key: string, data: T, ttlMs?: number): void {
    if (cache.size >= this.maxCacheSize) {
      const oldestKey = cache.keys().next().value;
      if (oldestKey) cache.delete(oldestKey);
    }
    cache.set(key, {
      data,
      expiresAt: Date.now() + (ttlMs ?? this.cacheTtlMs),
    });
  }

  private invalidateCache(ruleId?: string): void {
    if (ruleId) {
      this.ruleCache.delete(ruleId);
      this.pendingRequests.delete(ruleId);
    }
    this.listCache.clear();
  }

  getCacheStats(): { hits: number; misses: number; hitRate: number; size: number } {
    const total = this.cacheHits + this.cacheMisses;
    return {
      hits: this.cacheHits,
      misses: this.cacheMisses,
      hitRate: total > 0 ? this.cacheHits / total : 0,
      size: this.ruleCache.size + this.rulesetCache.size + this.listCache.size,
    };
  }

  clearCache(): void {
    this.ruleCache.clear();
    this.rulesetCache.clear();
    this.listCache.clear();
    this.pendingRequests.clear();
    this.cacheHits = 0;
    this.cacheMisses = 0;
  }

  private async httpRequest<T>(
    method: string,
    path: string,
    body?: unknown,
    timeoutMs?: number,
  ): Promise<T> {
    const url = this.buildUrl(path);
    const effectiveTimeout = timeoutMs ?? this.timeout;
    const requestId = `req_${++this.requestCount}`;

    for (let attempt = 0; attempt <= this.retryConfig.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), effectiveTimeout);

        try {
          const response = await fetch(url, {
            method,
            headers: this.buildHeaders(),
            body: body !== undefined ? JSON.stringify(body) : undefined,
            signal: controller.signal,
          });

          clearTimeout(timeoutId);

          if (!response.ok) {
            throw await this.buildError(response);
          }

          const text = await response.text();
          if (!text || text.trim().length === 0) {
            return undefined as unknown as T;
          }
          return JSON.parse(text) as T;
        } finally {
          clearTimeout(timeoutId);
        }
      } catch (error) {
        if (error instanceof SdkClientError) {
          if (this.isRetryable(error) && attempt < this.retryConfig.maxRetries) {
            const delay = this.calculateBackoff(attempt);
            await this.sleep(delay);
            continue;
          }
          throw error;
        }
        if (error instanceof DOMException && error.name === 'AbortError') {
          throw new SdkTimeoutError(effectiveTimeout);
        }
        throw new SdkClientError(`Unexpected error: ${error}`, 'UNEXPECTED');
      }
    }
    throw new SdkClientError(`Request failed after ${this.retryConfig.maxRetries} retries`, 'MAX_RETRIES');
  }

  private isRetryable(error: SdkClientError): boolean {
    return this.retryConfig.retryableStatuses.includes(error.statusCode ?? 0);
  }

  private calculateBackoff(attempt: number): number {
    const delay = Math.min(
      this.retryConfig.baseDelayMs * Math.pow(2, attempt),
      this.retryConfig.maxDelayMs,
    );
    return Math.floor(delay + Math.random() * delay * 0.1);
  }

  private async buildError(response: Response): Promise<SdkClientError> {
    let detail: string | undefined;
    try {
      const text = await response.text();
      if (text) {
        const parsed = JSON.parse(text);
        detail = parsed.message || parsed.error || text;
      }
    } catch {
      detail = response.statusText;
    }

    switch (response.status) {
      case 401:
      case 403:
        return new SdkAuthError(detail ?? 'Authentication failed');
      case 404:
        return new SdkNotFoundError('Rule', response.url);
      case 429:
        return new SdkClientError(detail ?? 'Rate limited', 'RATE_LIMIT', 429);
      default:
        return new SdkClientError(detail ?? `HTTP ${response.status}`, 'HTTP_ERROR', response.status);
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async fetchRule(ruleId: string, bypassCache = false): Promise<Rule> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }

    if (!bypassCache) {
      const cached = this.getFromCache(this.ruleCache, ruleId);
      if (cached) return cached;
    }

    if (this.pendingRequests.has(ruleId)) {
      return this.pendingRequests.get(ruleId)!;
    }

    const promise = this.httpRequest<Rule>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}`)
      .then((rule) => {
        this.setCache(this.ruleCache, ruleId, rule);
        return rule;
      })
      .finally(() => {
        this.pendingRequests.delete(ruleId);
      });

    this.pendingRequests.set(ruleId, promise);
    return promise;
  }

  async fetchRules(
    tier?: RuleTier,
    type?: RuleType,
    status?: RuleStatus,
    bypassCache = false,
  ): Promise<Rule[]> {
    const cacheKey = this.getCacheKey('rules', tier ?? '*', type ?? '*', status ?? '*');

    if (!bypassCache) {
      const cached = this.getFromCache(this.listCache, cacheKey);
      if (cached) return cached;
    }

    const params = new URLSearchParams();
    if (tier) params.set('tier', tier);
    if (type) params.set('type', type);
    if (status) params.set('status', status);

    const query = params.toString();
    const path = query ? `/api/v1/rules?${query}` : '/api/v1/rules';

    const result = await this.httpRequest<{ rules: Rule[] }>('GET', path);
    const rules = result.rules ?? [];

    this.setCache(this.listCache, cacheKey, rules);
    for (const rule of rules) {
      this.setCache(this.ruleCache, rule.id, rule);
    }

    return rules;
  }

  async getApplicableRules(context: Partial<RuleContext>): Promise<Rule[]> {
    if (!context || Object.keys(context).length === 0) {
      return this.fetchRules();
    }

    const effective = contextToEffective(createRuleContext(context));
    const allRules = await this.fetchRules();

    return allRules.filter((rule) => {
      if (rule.status !== RuleStatus.ACTIVE && rule.status !== RuleStatus.TESTING) {
        return false;
      }
      return this.isRuleApplicable(rule, effective);
    });
  }

  private isRuleApplicable(rule: Rule, context: Record<string, unknown>): boolean {
    if (context.domain) {
      const domainTags = rule.tags.filter((t) => t.startsWith('domain:'));
      if (domainTags.length > 0 && !domainTags.some((t) => t.split(':', 2)[1] === context.domain)) {
        return false;
      }
    }
    if (context.user_role) {
      const roleTags = rule.tags.filter((t) => t.startsWith('role:'));
      if (roleTags.length > 0) {
        const roles = Array.isArray(context.user_role) ? context.user_role : [String(context.user_role)];
        if (!roleTags.some((t) => roles.includes(t.split(':', 2)[1]))) {
          return false;
        }
      }
    }
    return true;
  }

  async evaluate(
    content: string,
    context?: Partial<RuleContext>,
    options?: RuleEvaluationOptions,
  ): Promise<ValidationResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;
    const request = createEvaluationRequest({
      content,
      context: effectiveContext,
      rule_ids: options?.ruleIds,
      tier: options?.tier,
      rule_types: options?.ruleTypes,
      options: options?.extraOptions,
      timeout_ms: options?.timeoutMs ?? 5000,
      parallel_evaluation: options?.parallel ?? true,
      early_termination: options?.earlyTermination ?? true,
    });

    const timeoutMs = (options?.timeoutMs ?? 5000) + 1000;

    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), timeoutMs);

    try {
      const result = await this.evaluateWithFallback(request, options);
      return result;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  private async evaluateWithFallback(
    request: RuleEvaluationRequest,
    options?: RuleEvaluationOptions,
  ): Promise<ValidationResult> {
    try {
      return await this.httpRequest<ValidationResult>('POST', '/api/v1/validate', request);
    } catch (error) {
      if (options?.fallback === 'strict') {
        return createValidationResult({ valid: false, total_score: 0, violations: [], critical_violations: [] });
      }
      if (options?.fallback === 'permissive') {
        return createValidationResult({ valid: true, total_score: 1.0 });
      }
      if (options?.fallback === 'local' && options.localEvaluator) {
        return options.localEvaluator(content, request, options);
      }

      const content = request.content;
      const rules = request.rule_ids
        ? await Promise.all(request.rule_ids.map((id) => this.fetchRule(id).catch(() => null)))
        : await this.fetchRules();

      const validRules = rules.filter((r): r is Rule => r !== null);
      return this.evaluateLocally(content, request, validRules);
    }
  }

  private async evaluateLocally(
    content: string,
    request: RuleEvaluationRequest,
    rules: Rule[],
  ): Promise<ValidationResult> {
    const startTime = Date.now();
    const violations: Violation[] = [];
    const suggestions: Suggestion[] = [];
    let rulesEvaluated = 0;
    let rulesTriggered = 0;
    const rulesByTier: Record<string, number> = {};

    for (const rule of rules) {
      if (!shouldEvaluateRule(request, rule)) continue;
      rulesEvaluated++;

      const tierKey = rule.tier;
      rulesByTier[tierKey] = (rulesByTier[tierKey] ?? 0) + 1;

      const localResult = this.matchRuleLocally(content, rule);
      if (localResult) {
        rulesTriggered++;
        violations.push(localResult);
      }
    }

    const processingTime = Date.now() - startTime;

    return createValidationResult({
      valid: violations.length === 0,
      total_score: violations.length === 0 ? 1.0 : Math.max(0, 1.0 - violations.length * 0.1),
      confidence: 0.7,
      total_rules_evaluated: rulesEvaluated,
      rules_triggered: rulesTriggered,
      rules_violated: violations.length,
      violations,
      critical_violations: violations.filter((v) => v.rule_severity === 'critical'),
      warnings: violations.filter((v) => v.rule_severity === 'low' || v.rule_severity === 'medium'),
      suggestions,
      processing_time_ms: processingTime,
      rules_by_tier: rulesByTier,
      processing_details: { mode: 'local_fallback' },
    });
  }

  private matchRuleLocally(content: string, rule: Rule): Violation | null {
    const lowerContent = content.toLowerCase();
    const matchedPatterns: string[] = [];

    for (const pattern of rule.patterns) {
      for (const keyword of pattern.keywords) {
        if (lowerContent.includes(keyword.toLowerCase())) {
          matchedPatterns.push(keyword);
        }
      }
      for (const regex of pattern.regex_patterns) {
        try {
          const re = new RegExp(regex, 'gi');
          if (re.test(content)) {
            matchedPatterns.push(regex);
          }
        } catch {
          continue;
        }
      }
    }

    if (matchedPatterns.length === 0) return null;

    const confidence = Math.min(matchedPatterns.length / Math.max(rule.patterns.length, 1), 1.0);

    return {
      rule_id: rule.id,
      rule_name: rule.name,
      rule_tier: rule.tier,
      rule_severity: rule.severity,
      violation_type: 'pattern_matching',
      matched_content: content.substring(0, 200),
      matched_patterns,
      confidence_score: confidence,
      position_info: {},
      action_taken: rule.auto_block ? 'block' : 'warning',
      blocked: rule.auto_block,
      user_override_allowed: rule.user_override,
      suggestions: [],
      detected_at: new Date().toISOString(),
      detection_method: 'local_fallback',
      context: {},
    };
  }

  async evaluateBatch(
    contents: string[],
    options?: RuleEvaluationOptions,
  ): Promise<ValidationResult[]> {
    if (!contents || contents.length === 0) {
      return [];
    }
    if (contents.length > 100) {
      throw new SdkValidationError('Maximum 100 items per batch');
    }

    const results: ValidationResult[] = [];
    const batches = this.chunkArray(contents, this.batchSize);

    for (const batch of batches) {
      const batchResults = await Promise.all(
        batch.map((content) =>
          this.evaluate(content, options?.context, options).catch((err) =>
            createValidationResult({
              valid: false,
              total_score: 0,
              processing_details: { error: err instanceof Error ? err.message : String(err) },
            }),
          ),
        ),
      );
      results.push(...batchResults);
    }

    return results;
  }

  async evaluateByTier(
    content: string,
    tier: RuleTier,
    options?: RuleEvaluationOptions,
  ): Promise<ValidationResult> {
    return this.evaluate(content, options?.context, {
      ...options,
      tier,
    });
  }

  async evaluateAllTiers(
    content: string,
    context?: Partial<RuleContext>,
  ): Promise<Record<RuleTier, ValidationResult>> {
    const results: Record<RuleTier, ValidationResult> = {} as Record<RuleTier, ValidationResult>;

    const tiers = [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE];
    const promises = tiers.map((tier) =>
      this.evaluateByTier(content, tier, { context }).then((r) => {
        results[tier] = r;
      }),
    );

    await Promise.all(promises);
    return results;
  }

  async createRule(ruleData: Partial<Rule>): Promise<Rule> {
    const rule = createRule(ruleData);
    const result = await this.httpRequest<Rule>('POST', '/api/v1/rules', rule);
    this.invalidateCache();
    return result;
  }

  async updateRule(ruleId: string, ruleData: Partial<Rule>): Promise<Rule> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    const result = await this.httpRequest<Rule>('PUT', `/api/v1/rules/${encodeURIComponent(ruleId)}`, ruleData);
    this.invalidateCache(ruleId);
    return result;
  }

  async deleteRule(ruleId: string): Promise<void> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    await this.httpRequest<void>('DELETE', `/api/v1/rules/${encodeURIComponent(ruleId)}`);
    this.invalidateCache(ruleId);
  }

  async activateRule(ruleId: string): Promise<Rule> {
    return this.updateRule(ruleId, { status: RuleStatus.ACTIVE });
  }

  async deactivateRule(ruleId: string): Promise<Rule> {
    return this.updateRule(ruleId, { status: RuleStatus.INACTIVE });
  }

  async getRuleStats(ruleId: string): Promise<Record<string, unknown>> {
    return this.httpRequest<Record<string, unknown>>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}/stats`);
  }

  async getRuleHistory(ruleId: string): Promise<unknown[]> {
    return this.httpRequest<unknown[]>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}/history`);
  }

  async getRelatedRules(ruleId: string): Promise<Rule[]> {
    return this.httpRequest<Rule[]>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}/related`);
  }

  async getRuleConflicts(ruleId: string): Promise<unknown[]> {
    return this.httpRequest<unknown[]>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}/conflicts`);
  }

  private chunkArray<T>(array: T[], size: number): T[][] {
    const chunks: T[][] = [];
    for (let i = 0; i < array.length; i += size) {
      chunks.push(array.slice(i, i + size));
    }
    return chunks;
  }

  async evaluateWithRules(
    content: string,
    rules: Rule[],
    context?: Partial<RuleContext>,
  ): Promise<ValidationResult> {
    const effectiveContext = context ? createRuleContext(context) : undefined;
    const request = createEvaluationRequest({
      content,
      context: effectiveContext,
      rule_ids: rules.map((r) => r.id),
    });

    return this.evaluateLocally(content, request, rules);
  }

  async getRuleSet(ruleSetId: string): Promise<RuleSet> {
    const cached = this.getFromCache(this.rulesetCache, ruleSetId);
    if (cached) return cached;

    const result = await this.httpRequest<RuleSet>('GET', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}`);
    this.setCache(this.rulesetCache, ruleSetId, result);
    return result;
  }

  async getRuleSets(tier?: RuleTier): Promise<RuleSet[]> {
    const params = tier ? `?tier=${encodeURIComponent(tier)}` : '';
    const result = await this.httpRequest<{ rule_sets: RuleSet[] }>('GET', `/api/v1/rule-sets${params}`);
    const ruleSets = result.rule_sets ?? [];
    for (const rs of ruleSets) {
      this.setCache(this.rulesetCache, rs.id, rs);
    }
    return ruleSets;
  }

  async batchEvaluateByTier(
    contents: string[],
    tier: RuleTier,
    options?: RuleEvaluationOptions,
  ): Promise<Map<string, ValidationResult>> {
    const results = new Map<string, ValidationResult>();
    const entries = contents.map((content) => ({ content }));

    const batches = this.chunkArray(entries, this.batchSize);
    for (const batch of batches) {
      const batchPromises = batch.map(({ content }) =>
        this.evaluateByTier(content, tier, options)
          .then((r) => results.set(content, r))
          .catch(() => results.set(content, createValidationResult({ valid: false }))),
      );
      await Promise.all(batchPromises);
    }

    return results;
  }

  async evaluateWithRetry(
    content: string,
    context?: Partial<RuleContext>,
    options?: RuleEvaluationOptions & { maxRetries?: number },
  ): Promise<ValidationResult> {
    const maxRetries = options?.maxRetries ?? 2;
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        return await this.evaluate(content, context, options);
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        if (attempt < maxRetries) {
          const delay = Math.pow(2, attempt) * 500;
          await this.sleep(delay);
        }
      }
    }

    throw lastError ?? new SdkClientError('Evaluation failed after retries');
  }

  async evaluateStream(
    contents: string[],
    context?: Partial<RuleContext>,
    options?: RuleEvaluationOptions,
  ): Promise<AsyncGenerator<{ content: string; result: ValidationResult; index: number }, void, unknown>> {
    const self = this;
    async function* generator(): AsyncGenerator<{ content: string; result: ValidationResult; index: number }, void, unknown> {
      for (let i = 0; i < contents.length; i++) {
        const content = contents[i];
        try {
          const result = await self.evaluate(content, context, options);
          yield { content, result, index: i };
        } catch (error) {
          yield {
            content,
            result: createValidationResult({
              valid: false,
              processing_details: { error: error instanceof Error ? error.message : String(error) },
            }),
            index: i,
          };
        }
      }
    }
    return generator();
  }

  async evaluateWithDedup(
    content: string,
    context?: Partial<RuleContext>,
    options?: RuleEvaluationOptions,
  ): Promise<ValidationResult> {
    const contentHash = this.simpleHash(content);
    const cacheKey = `eval:${contentHash}:${JSON.stringify(context ?? {})}:${JSON.stringify(options ?? {})}`;

    const cached = this.getFromCache<ValidationResult>(this.listCache as Map<string, CacheEntry<ValidationResult>>, cacheKey);
    if (cached) return cached;

    const result = await this.evaluate(content, context, options);
    this.setCache(this.listCache as Map<string, CacheEntry<ValidationResult>>, cacheKey, result, 60000);
    return result;
  }

  private simpleHash(str: string): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(36);
  }

  async healthCheck(): Promise<Record<string, unknown>> {
    return this.httpRequest<Record<string, unknown>>('GET', '/api/v1/health');
  }
}

export interface RuleEvaluationOptions {
  ruleIds?: string[];
  tier?: RuleTier;
  ruleTypes?: RuleType[];
  context?: Partial<RuleContext>;
  extraOptions?: Record<string, unknown>;
  timeoutMs?: number;
  parallel?: boolean;
  earlyTermination?: boolean;
  fallback?: 'strict' | 'permissive' | 'local' | 'error';
  localEvaluator?: (content: string, request: RuleEvaluationRequest, options?: RuleEvaluationOptions) => Promise<ValidationResult>;
}
