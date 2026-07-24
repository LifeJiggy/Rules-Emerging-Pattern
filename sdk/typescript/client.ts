/**
 * Main SDK Client for the Rules-Emerging-Pattern API.
 * Provides methods for rule management, evaluation, validation, and monitoring.
 */

import {
  Rule,
  RuleTier,
  RuleType,
  RuleStatus,
  RuleContext,
  RulePattern,
  RuleSet,
  ValidationResult,
  AlertEvent,
  AlertSeverity,
  MetricsSnapshot,
  SdkOptions,
  RetryConfig,
  DEFAULT_RETRY_CONFIG,
  SdkResponse,
  SdkError,
  SdkClientError,
  SdkAuthError,
  SdkNotFoundError,
  SdkRateLimitError,
  SdkTimeoutError,
  SdkValidationError,
  createRule,
  validateRule,
  createRuleSet,
  createRuleContext,
  createValidationResult,
  isRule,
  isValidationResult,
  RuleEvaluationRequest,
  BatchValidationRequest,
  BatchValidationResult,
  createBatchValidationRequest,
  createBatchValidationResult,
} from './models';

export class Client {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly retryConfig: RetryConfig;
  private readonly logger: Console;
  private requestCount = 0;

  constructor(options: SdkOptions) {
    this.validateOptions(options);
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.timeout = options.timeout ?? 30000;
    this.retryConfig = { ...DEFAULT_RETRY_CONFIG, ...options.retryConfig };
    this.logger = console;
  }

  private validateOptions(options: SdkOptions): void {
    if (!options.apiKey || options.apiKey.trim().length === 0) {
      throw new SdkValidationError('API key is required');
    }
    if (!options.baseUrl || options.baseUrl.trim().length === 0) {
      throw new SdkValidationError('Base URL is required');
    }
    try {
      new URL(options.baseUrl);
    } catch {
      throw new SdkValidationError(`Invalid base URL: ${options.baseUrl}`);
    }
  }

  private buildUrl(path: string, params?: Record<string, string | undefined>): string {
    const url = new URL(`${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, value);
        }
      }
    }
    return url.toString();
  }

  private buildHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-API-Key': this.apiKey,
      'X-SDK-Version': '1.0.0',
      'X-SDK-Language': 'typescript',
    };
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | undefined>,
    requestTimeout?: number,
  ): Promise<SdkResponse<T>> {
    const startTime = Date.now();
    const requestId = `req_${++this.requestCount}_${Date.now()}`;

    try {
      const url = this.buildUrl(path, params);
      const headers = this.buildHeaders();
      const effectiveTimeout = requestTimeout ?? this.timeout;

      this.logRequest(method, url, body, requestId);

      const result = await this.executeWithRetry<T>(method, url, headers, body, effectiveTimeout, requestId, 0);

      const durationMs = Date.now() - startTime;
      this.logResponse(requestId, result, durationMs);

      return {
        success: true,
        data: result,
        requestId,
        durationMs,
      };
    } catch (error) {
      const durationMs = Date.now() - startTime;
      const sdkError = this.normalizeError(error);

      this.logError(requestId, sdkError, durationMs);

      return {
        success: false,
        error: sdkError,
        requestId,
        durationMs,
      };
    }
  }

  private async executeWithRetry<T>(
    method: string,
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
    requestId: string,
    attempt: number,
  ): Promise<T> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const response = await fetch(url, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          const text = await response.text();
          if (!text || text.trim().length === 0) {
            return undefined as unknown as T;
          }
          return JSON.parse(text) as T;
        }

        if (this.isRetryableStatus(response.status) && attempt < this.retryConfig.maxRetries) {
          const delay = this.calculateBackoff(attempt);
          this.logger.warn(`[SDK] ${requestId} attempt ${attempt + 1} failed with ${response.status}, retrying in ${delay}ms`);
          await this.sleep(delay);
          return this.executeWithRetry<T>(method, url, headers, body, timeoutMs, requestId, attempt + 1);
        }

        throw await this.buildHttpError(response);
      } finally {
        clearTimeout(timeoutId);
      }
    } catch (error) {
      if (error instanceof SdkClientError) {
        throw error;
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new SdkTimeoutError(timeoutMs);
      }
      throw this.normalizeError(error);
    }
  }

  private isRetryableStatus(status: number): boolean {
    return this.retryConfig.retryableStatuses.includes(status);
  }

  private calculateBackoff(attempt: number): number {
    const delay = Math.min(
      this.retryConfig.baseDelayMs * Math.pow(2, attempt),
      this.retryConfig.maxDelayMs,
    );
    const jitter = Math.random() * delay * 0.1;
    return Math.floor(delay + jitter);
  }

  private async buildHttpError(response: Response): Promise<SdkClientError> {
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
        return new SdkNotFoundError('Resource', response.url);
      case 409:
        return new SdkClientError(detail ?? 'Conflict', 'CONFLICT', response.status);
      case 422:
        return new SdkValidationError(detail ?? 'Validation failed');
      case 429:
        const retryAfter = response.headers.get('Retry-After');
        return new SdkRateLimitError(retryAfter ? parseInt(retryAfter, 10) * 1000 : 1000);
      default:
        if (response.status >= 500) {
          return new SdkClientError(detail ?? 'Internal server error', 'SERVER_ERROR', response.status);
        }
        return new SdkClientError(detail ?? `HTTP ${response.status}`, 'HTTP_ERROR', response.status);
    }
  }

  private normalizeError(error: unknown): SdkError {
    if (error instanceof SdkClientError) {
      return {
        code: error.code,
        message: error.message,
        details: error.details,
        statusCode: error.statusCode,
      };
    }
    if (error instanceof Error) {
      return {
        code: 'UNEXPECTED_ERROR',
        message: error.message,
      };
    }
    return {
      code: 'UNKNOWN_ERROR',
      message: String(error),
    };
  }

  private logRequest(method: string, url: string, body: unknown, requestId: string): void {
    this.logger.debug(`[SDK] ${requestId} → ${method} ${url}`, {
      body: body !== undefined ? this.truncateBody(body) : undefined,
    });
  }

  private logResponse<T>(requestId: string, data: T, durationMs: number): void {
    this.logger.debug(`[SDK] ${requestId} ← ${durationMs}ms`, {
      dataPreview: this.truncateBody(data),
    });
  }

  private logError(requestId: string, error: SdkError, durationMs: number): void {
    this.logger.warn(`[SDK] ${requestId} ✗ ${durationMs}ms [${error.code}] ${error.message}`);
  }

  private truncateBody(body: unknown): unknown {
    if (typeof body === 'string' && body.length > 500) {
      return body.substring(0, 500) + '...';
    }
    return body;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async requestJson<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | undefined>,
    requestTimeout?: number,
  ): Promise<T> {
    const response = await this.request<T>(method, path, body, params, requestTimeout);
    if (!response.success || response.data === undefined) {
      throw new SdkClientError(
        response.error?.message ?? 'Request failed',
        response.error?.code ?? 'REQUEST_FAILED',
        response.error?.statusCode,
      );
    }
    return response.data;
  }

  async validate(
    content: string,
    tier?: RuleTier,
    ruleIds?: string[],
    context?: RuleContext,
    options?: Record<string, unknown>,
  ): Promise<ValidationResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const request: RuleEvaluationRequest = {
      content,
      tier,
      rule_ids: ruleIds,
      context: context ?? createRuleContext({}),
      options: options ?? {},
      timeout_ms: 5000,
      parallel_evaluation: true,
      early_termination: true,
    };

    return this.requestJson<ValidationResult>('POST', '/api/v1/validate', request);
  }

  async evaluateRules(
    content: string,
    context?: RuleContext,
    options?: Record<string, unknown>,
  ): Promise<ValidationResult> {
    return this.validate(content, undefined, undefined, context, options);
  }

  async getRules(
    tier?: RuleTier,
    type?: RuleType,
    status?: RuleStatus,
    page?: number,
    pageSize?: number,
  ): Promise<{ rules: Rule[]; total: number; page: number; page_size: number }> {
    const params: Record<string, string | undefined> = {
      tier: tier as string | undefined,
      type: type as string | undefined,
      status: status as string | undefined,
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };

    return this.requestJson<{ rules: Rule[]; total: number; page: number; page_size: number }>('GET', '/api/v1/rules', undefined, params);
  }

  async getRule(ruleId: string): Promise<Rule> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    return this.requestJson<Rule>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}`);
  }

  async createRule(ruleData: Partial<Rule>): Promise<Rule> {
    const rule = createRule(ruleData);
    const errors = validateRule(rule);
    if (errors.length > 0) {
      throw new SdkValidationError(`Invalid rule data: ${errors.join('; ')}`, errors);
    }
    return this.requestJson<Rule>('POST', '/api/v1/rules', rule);
  }

  async updateRule(ruleId: string, ruleData: Partial<Rule>): Promise<Rule> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    return this.requestJson<Rule>('PUT', `/api/v1/rules/${encodeURIComponent(ruleId)}`, ruleData);
  }

  async deleteRule(ruleId: string): Promise<void> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    await this.requestJson<void>('DELETE', `/api/v1/rules/${encodeURIComponent(ruleId)}`);
  }

  async getRuleSets(
    tier?: RuleTier,
    page?: number,
    pageSize?: number,
  ): Promise<{ rule_sets: RuleSet[]; total: number; page: number; page_size: number }> {
    const params: Record<string, string | undefined> = {
      tier: tier as string | undefined,
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ rule_sets: RuleSet[]; total: number; page: number; page_size: number }>('GET', '/api/v1/rule-sets', undefined, params);
  }

  async getRuleSet(ruleSetId: string): Promise<RuleSet> {
    if (!ruleSetId || ruleSetId.trim().length === 0) {
      throw new SdkValidationError('Rule set ID cannot be empty');
    }
    return this.requestJson<RuleSet>('GET', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}`);
  }

  async createRuleSet(data: Partial<RuleSet>): Promise<RuleSet> {
    const ruleSet = createRuleSet(data);
    return this.requestJson<RuleSet>('POST', '/api/v1/rule-sets', ruleSet);
  }

  async updateRuleSet(ruleSetId: string, data: Partial<RuleSet>): Promise<RuleSet> {
    if (!ruleSetId || ruleSetId.trim().length === 0) {
      throw new SdkValidationError('Rule set ID cannot be empty');
    }
    return this.requestJson<RuleSet>('PUT', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}`, data);
  }

  async deleteRuleSet(ruleSetId: string): Promise<void> {
    if (!ruleSetId || ruleSetId.trim().length === 0) {
      throw new SdkValidationError('Rule set ID cannot be empty');
    }
    await this.requestJson<void>('DELETE', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}`);
  }

  async addRuleToSet(ruleSetId: string, ruleId: string): Promise<RuleSet> {
    if (!ruleSetId || ruleSetId.trim().length === 0) {
      throw new SdkValidationError('Rule set ID cannot be empty');
    }
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    return this.requestJson<RuleSet>('POST', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}/rules/${encodeURIComponent(ruleId)}`);
  }

  async removeRuleFromSet(ruleSetId: string, ruleId: string): Promise<RuleSet> {
    if (!ruleSetId || ruleSetId.trim().length === 0) {
      throw new SdkValidationError('Rule set ID cannot be empty');
    }
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    return this.requestJson<RuleSet>('DELETE', `/api/v1/rule-sets/${encodeURIComponent(ruleSetId)}/rules/${encodeURIComponent(ruleId)}`);
  }

  async getMetrics(): Promise<MetricsSnapshot> {
    return this.requestJson<MetricsSnapshot>('GET', '/api/v1/metrics');
  }

  async getMetric(
    name: string,
    aggregation?: string,
    window?: string,
  ): Promise<{ metric: string; values: unknown[] }> {
    const params: Record<string, string | undefined> = {
      aggregation,
      window,
    };
    return this.requestJson<{ metric: string; values: unknown[] }>('GET', `/api/v1/metrics/${encodeURIComponent(name)}`, undefined, params);
  }

  async getAlerts(
    severity?: AlertSeverity,
    status?: string,
    source?: string,
    page?: number,
    pageSize?: number,
  ): Promise<{ alerts: AlertEvent[]; total: number; page: number; page_size: number }> {
    const params: Record<string, string | undefined> = {
      severity: severity as string | undefined,
      status,
      source,
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ alerts: AlertEvent[]; total: number; page: number; page_size: number }>('GET', '/api/v1/alerts', undefined, params);
  }

  async getAlert(alertId: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.requestJson<AlertEvent>('GET', `/api/v1/alerts/${encodeURIComponent(alertId)}`);
  }

  async triggerAlert(
    name: string,
    severity: AlertSeverity,
    message: string,
    details?: Record<string, unknown>,
  ): Promise<AlertEvent> {
    if (!name || name.trim().length === 0) {
      throw new SdkValidationError('Alert name cannot be empty');
    }
    if (!message || message.trim().length === 0) {
      throw new SdkValidationError('Alert message cannot be empty');
    }
    return this.requestJson<AlertEvent>('POST', '/api/v1/alerts', {
      alert_name: name,
      severity,
      message,
      details: details ?? {},
    });
  }

  async resolveAlert(alertId: string, resolutionNotes?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.requestJson<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/resolve`, {
      resolution_notes: resolutionNotes,
    });
  }

  async acknowledgeAlert(alertId: string, notes?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.requestJson<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
      notes,
    });
  }

  async getDashboard(dashboardId?: string): Promise<Record<string, unknown>> {
    if (dashboardId) {
      return this.requestJson<Record<string, unknown>>('GET', `/api/v1/dashboards/${encodeURIComponent(dashboardId)}`);
    }
    return this.requestJson<Record<string, unknown>>('GET', '/api/v1/dashboards/default');
  }

  async getHealth(): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('GET', '/api/v1/health');
  }

  async healthCheck(): Promise<{ status: string; version: string; uptime: number; checks: Record<string, string> }> {
    const result = await this.request<{ status: string; version: string; uptime: number; checks: Record<string, string> }>('GET', '/api/v1/health');
    if (!result.success) {
      return {
        status: 'unhealthy',
        version: 'unknown',
        uptime: 0,
        checks: { api: 'down', error: result.error?.message ?? 'Unknown' },
      };
    }
    return result.data ?? {
      status: 'unknown',
      version: 'unknown',
      uptime: 0,
      checks: {},
    };
  }

  async getApiInfo(): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('GET', '/api/v1/info');
  }

  async getAlertDefinitions(
    page?: number,
    pageSize?: number,
  ): Promise<{ definitions: unknown[]; total: number; page: number; page_size: number }> {
    const params: Record<string, string | undefined> = {
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ definitions: unknown[]; total: number; page: number; page_size: number }>('GET', '/api/v1/alert-definitions', undefined, params);
  }

  async getRuleStats(ruleId: string): Promise<Record<string, unknown>> {
    if (!ruleId || ruleId.trim().length === 0) {
      throw new SdkValidationError('Rule ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('GET', `/api/v1/rules/${encodeURIComponent(ruleId)}/stats`);
  }

  async bulkValidate(
    contents: string[],
    context?: RuleContext,
    options?: Record<string, unknown>,
  ): Promise<BatchValidationResult> {
    if (!contents || contents.length === 0) {
      throw new SdkValidationError('Contents array cannot be empty');
    }
    if (contents.some((c) => !c || c.trim().length === 0)) {
      throw new SdkValidationError('All contents must be non-empty strings');
    }
    if (contents.length > 100) {
      throw new SdkValidationError('Maximum of 100 items per batch request');
    }

    const request = createBatchValidationRequest({
      requests: contents,
      common_context: context ? { ...context } : undefined,
      batch_options: options ?? {},
      max_parallel: 10,
      fail_fast: false,
      return_individual_results: true,
      aggregate_results: true,
    });

    return this.requestJson<BatchValidationResult>('POST', '/api/v1/validate/batch', request);
  }

  async getTemplates(
    tier?: RuleTier,
    type?: RuleType,
    page?: number,
    pageSize?: number,
  ): Promise<{ templates: unknown[]; total: number }> {
    const params: Record<string, string | undefined> = {
      tier: tier as string | undefined,
      type: type as string | undefined,
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ templates: unknown[]; total: number }>('GET', '/api/v1/templates', undefined, params);
  }

  async instantiateTemplate(
    templateId: string,
    variables: Record<string, string>,
  ): Promise<Rule> {
    if (!templateId || templateId.trim().length === 0) {
      throw new SdkValidationError('Template ID cannot be empty');
    }
    return this.requestJson<Rule>('POST', `/api/v1/templates/${encodeURIComponent(templateId)}/instantiate`, { variables });
  }

  async getConflicts(
    severity?: string,
    resolved?: boolean,
    page?: number,
    pageSize?: number,
  ): Promise<{ conflicts: unknown[]; total: number }> {
    const params: Record<string, string | undefined> = {
      severity,
      resolved: resolved?.toString(),
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ conflicts: unknown[]; total: number }>('GET', '/api/v1/conflicts', undefined, params);
  }

  async resolveConflict(
    conflictId: string,
    strategy: string,
    params?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (!conflictId || conflictId.trim().length === 0) {
      throw new SdkValidationError('Conflict ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('POST', `/api/v1/conflicts/${encodeURIComponent(conflictId)}/resolve`, {
      strategy,
      parameters: params ?? {},
    });
  }

  async getAuditLogs(
    category?: string,
    action?: string,
    actor?: string,
    from?: string,
    to?: string,
    page?: number,
    pageSize?: number,
  ): Promise<{ events: unknown[]; total: number }> {
    const params: Record<string, string | undefined> = {
      category,
      action,
      actor,
      from,
      to,
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.requestJson<{ events: unknown[]; total: number }>('GET', '/api/v1/audit-logs', undefined, params);
  }

  async getComplianceReport(
    periodStart: string,
    periodEnd: string,
  ): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('GET', '/api/v1/compliance', {
      period_start: periodStart,
      period_end: periodEnd,
    } as unknown as Record<string, string | undefined>);
  }

  async getProfiles(): Promise<unknown[]> {
    return this.requestJson<unknown[]>('GET', '/api/v1/profiles');
  }

  async getProfile(profileId: string): Promise<Record<string, unknown>> {
    if (!profileId || profileId.trim().length === 0) {
      throw new SdkValidationError('Profile ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('GET', `/api/v1/profiles/${encodeURIComponent(profileId)}`);
  }

  async createProfile(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('POST', '/api/v1/profiles', data);
  }

  async updateProfile(profileId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!profileId || profileId.trim().length === 0) {
      throw new SdkValidationError('Profile ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('PUT', `/api/v1/profiles/${encodeURIComponent(profileId)}`, data);
  }

  async deleteProfile(profileId: string): Promise<void> {
    if (!profileId || profileId.trim().length === 0) {
      throw new SdkValidationError('Profile ID cannot be empty');
    }
    await this.requestJson<void>('DELETE', `/api/v1/profiles/${encodeURIComponent(profileId)}`);
  }

  async getMonitors(): Promise<unknown[]> {
    return this.requestJson<unknown[]>('GET', '/api/v1/monitors');
  }

  async getMonitor(monitorId: string): Promise<Record<string, unknown>> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('GET', `/api/v1/monitors/${encodeURIComponent(monitorId)}`);
  }

  async createMonitor(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('POST', '/api/v1/monitors', data);
  }

  async updateMonitor(monitorId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('PUT', `/api/v1/monitors/${encodeURIComponent(monitorId)}`, data);
  }

  async deleteMonitor(monitorId: string): Promise<void> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    await this.requestJson<void>('DELETE', `/api/v1/monitors/${encodeURIComponent(monitorId)}`);
  }

  async getThresholds(): Promise<unknown[]> {
    return this.requestJson<unknown[]>('GET', '/api/v1/thresholds');
  }

  async getThreshold(thresholdId: string): Promise<Record<string, unknown>> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('GET', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`);
  }

  async createThreshold(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.requestJson<Record<string, unknown>>('POST', '/api/v1/thresholds', data);
  }

  async updateThreshold(thresholdId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    return this.requestJson<Record<string, unknown>>('PUT', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`, data);
  }

  async deleteThreshold(thresholdId: string): Promise<void> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    await this.requestJson<void>('DELETE', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`);
  }

  setLogLevel(level: 'debug' | 'info' | 'warn' | 'error'): void {
    this.logger.debug(`[SDK] Log level set to ${level}`);
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  getRequestCount(): number {
    return this.requestCount;
  }
}
