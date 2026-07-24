/**
 * MonitoringClient - Specialized client for system monitoring, metrics,
 * alerting, dashboards, and health checks.
 */

import {
  AlertSeverity,
  AlertStatus,
  AlertDefinition,
  AlertEvent,
  MetricsSnapshot,
  DashboardConfig,
  DashboardWidget,
  MonitorConfig,
  MetricsThreshold,
  SdkOptions,
  SdkClientError,
  SdkValidationError,
  SdkAuthError,
  SdkTimeoutError,
  SdkNotFoundError,
  createAlertDefinition,
  createMetricsSnapshot,
  evaluateAlertCondition,
  isAlertActive,
  snapshotGetAllMetrics,
  snapshotGetSummary,
  RetryConfig,
  DEFAULT_RETRY_CONFIG,
} from './models';

interface MonitoringClientOptions {
  apiKey: string;
  baseUrl: string;
  timeout?: number;
  retryConfig?: RetryConfig;
  defaultPollIntervalMs?: number;
}

const DEFAULT_MONITORING_OPTIONS: Partial<MonitoringClientOptions> = {
  timeout: 15000,
  defaultPollIntervalMs: 30000,
};

export class MonitoringClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly retryConfig: RetryConfig;
  private readonly defaultPollIntervalMs: number;
  private requestCount = 0;
  private pollingTimers: Map<string, ReturnType<typeof setInterval>> = new Map();

  constructor(options: MonitoringClientOptions) {
    if (!options.apiKey || options.apiKey.trim().length === 0) {
      throw new SdkValidationError('API key is required');
    }
    if (!options.baseUrl || options.baseUrl.trim().length === 0) {
      throw new SdkValidationError('Base URL is required');
    }
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.timeout = options.timeout ?? DEFAULT_MONITORING_OPTIONS.timeout!;
    this.retryConfig = { ...DEFAULT_RETRY_CONFIG, ...options.retryConfig };
    this.defaultPollIntervalMs = options.defaultPollIntervalMs ?? DEFAULT_MONITORING_OPTIONS.defaultPollIntervalMs!;
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
      'X-SDK-Client': 'monitoring',
    };
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | undefined>,
    timeoutMs?: number,
  ): Promise<T> {
    const url = this.buildUrl(path, params);
    const effectiveTimeout = timeoutMs ?? this.timeout;

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

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
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
      case 400:
        return new SdkValidationError(detail ?? 'Bad request');
      case 401:
      case 403:
        return new SdkAuthError(detail ?? 'Authentication failed');
      case 404:
        return new SdkNotFoundError('Resource', response.url);
      case 429:
        return new SdkClientError(detail ?? 'Rate limited', 'RATE_LIMIT', 429);
      default:
        return new SdkClientError(detail ?? `HTTP ${response.status}`, 'HTTP_ERROR', response.status);
    }
  }

  async getMetrics(): Promise<MetricsSnapshot> {
    return this.request<MetricsSnapshot>('GET', '/api/v1/metrics');
  }

  async getMetric(
    name: string,
    aggregation?: string,
    window?: string,
  ): Promise<{ metric: string; values: number[]; timestamps: string[]; aggregation: string; window: string }> {
    if (!name || name.trim().length === 0) {
      throw new SdkValidationError('Metric name cannot be empty');
    }

    const params: Record<string, string | undefined> = {
      aggregation,
      window,
    };

    return this.request<{ metric: string; values: number[]; timestamps: string[]; aggregation: string; window: string }>(
      'GET',
      `/api/v1/metrics/${encodeURIComponent(name)}`,
      undefined,
      params,
    );
  }

  async getMetricsSummary(): Promise<Record<string, number>> {
    const snapshot = await this.getMetrics();
    return snapshotGetAllMetrics(snapshot);
  }

  async getMetricsHistory(
    names: string[],
    window?: string,
  ): Promise<Record<string, { values: number[]; timestamps: string[] }>> {
    if (!names || names.length === 0) {
      throw new SdkValidationError('Metric names array cannot be empty');
    }

    const params: Record<string, string | undefined> = {
      names: names.join(','),
      window: window ?? 'last_1h',
    };

    return this.request<Record<string, { values: number[]; timestamps: string[] }>>('GET', '/api/v1/metrics/history', undefined, params);
  }

  async getMetricAggregates(
    names: string[],
    aggregation: string,
    window?: string,
  ): Promise<Record<string, number>> {
    if (!names || names.length === 0) {
      throw new SdkValidationError('Metric names array cannot be empty');
    }

    const params: Record<string, string | undefined> = {
      names: names.join(','),
      aggregation,
      window,
    };

    return this.request<Record<string, number>>('GET', '/api/v1/metrics/aggregate', undefined, params);
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

    return this.request<{ alerts: AlertEvent[]; total: number; page: number; page_size: number }>('GET', '/api/v1/alerts', undefined, params);
  }

  async getActiveAlerts(
    severity?: AlertSeverity,
    source?: string,
  ): Promise<AlertEvent[]> {
    const result = await this.getAlerts(severity, undefined, source);
    return result.alerts.filter((a) => isAlertActive(a));
  }

  async getAlert(alertId: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.request<AlertEvent>('GET', `/api/v1/alerts/${encodeURIComponent(alertId)}`);
  }

  async triggerAlert(
    name: string,
    severity: AlertSeverity,
    message: string,
    details?: Record<string, unknown>,
    source?: string,
  ): Promise<AlertEvent> {
    if (!name || name.trim().length === 0) {
      throw new SdkValidationError('Alert name cannot be empty');
    }
    if (!message || message.trim().length === 0) {
      throw new SdkValidationError('Alert message cannot be empty');
    }

    const body: Record<string, unknown> = {
      alert_name: name,
      severity,
      message,
      details: details ?? {},
    };
    if (source) body.source = source;

    return this.request<AlertEvent>('POST', '/api/v1/alerts', body);
  }

  async resolveAlert(alertId: string, resolutionNotes?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.request<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/resolve`, {
      resolution_notes: resolutionNotes,
    });
  }

  async acknowledgeAlert(alertId: string, notes?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.request<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
      notes,
    });
  }

  async dismissAlert(alertId: string, reason?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.request<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/dismiss`, {
      reason: reason ?? 'Dismissed by user',
    });
  }

  async escalateAlert(alertId: string, reason?: string): Promise<AlertEvent> {
    if (!alertId || alertId.trim().length === 0) {
      throw new SdkValidationError('Alert ID cannot be empty');
    }
    return this.request<AlertEvent>('POST', `/api/v1/alerts/${encodeURIComponent(alertId)}/escalate`, {
      reason,
    });
  }

  async getAlertDefinitions(
    page?: number,
    pageSize?: number,
  ): Promise<{ definitions: AlertDefinition[]; total: number; page: number; page_size: number }> {
    const params: Record<string, string | undefined> = {
      page: page?.toString(),
      page_size: pageSize?.toString(),
    };
    return this.request<{ definitions: AlertDefinition[]; total: number; page: number; page_size: number }>('GET', '/api/v1/alert-definitions', undefined, params);
  }

  async getAlertDefinition(definitionId: string): Promise<AlertDefinition> {
    if (!definitionId || definitionId.trim().length === 0) {
      throw new SdkValidationError('Alert definition ID cannot be empty');
    }
    return this.request<AlertDefinition>('GET', `/api/v1/alert-definitions/${encodeURIComponent(definitionId)}`);
  }

  async createAlertDefinition(data: Partial<AlertDefinition>): Promise<AlertDefinition> {
    const definition = createAlertDefinition(data);
    return this.request<AlertDefinition>('POST', '/api/v1/alert-definitions', definition);
  }

  async updateAlertDefinition(definitionId: string, data: Partial<AlertDefinition>): Promise<AlertDefinition> {
    if (!definitionId || definitionId.trim().length === 0) {
      throw new SdkValidationError('Alert definition ID cannot be empty');
    }
    return this.request<AlertDefinition>('PUT', `/api/v1/alert-definitions/${encodeURIComponent(definitionId)}`, data);
  }

  async deleteAlertDefinition(definitionId: string): Promise<void> {
    if (!definitionId || definitionId.trim().length === 0) {
      throw new SdkValidationError('Alert definition ID cannot be empty');
    }
    await this.request<void>('DELETE', `/api/v1/alert-definitions/${encodeURIComponent(definitionId)}`);
  }

  async toggleAlertDefinition(definitionId: string, active: boolean): Promise<AlertDefinition> {
    return this.updateAlertDefinition(definitionId, { is_active: active } as Partial<AlertDefinition>);
  }

  async evaluateAlertCondition(definitionId: string): Promise<{ triggered: boolean; currentValue: number }> {
    const definition = await this.getAlertDefinition(definitionId);
    const metricData = await this.getMetric(definition.metric_name);
    const currentValue = metricData.values[metricData.values.length - 1] ?? 0;
    const triggered = evaluateAlertCondition(definition, currentValue);

    return { triggered, currentValue };
  }

  async getAlertStats(): Promise<{
    total: number;
    active: number;
    resolved: number;
    bySeverity: Record<string, number>;
    byStatus: Record<string, number>;
  }> {
    const result = await this.getAlerts();
    const alerts = result.alerts;

    const bySeverity: Record<string, number> = {};
    const byStatus: Record<string, number> = {};

    for (const alert of alerts) {
      bySeverity[alert.severity] = (bySeverity[alert.severity] ?? 0) + 1;
      byStatus[alert.status] = (byStatus[alert.status] ?? 0) + 1;
    }

    return {
      total: result.total,
      active: alerts.filter((a) => isAlertActive(a)).length,
      resolved: alerts.filter((a) => a.status === AlertStatus.RESOLVED).length,
      bySeverity,
      byStatus,
    };
  }

  async getDashboard(dashboardId?: string): Promise<DashboardConfig> {
    const path = dashboardId
      ? `/api/v1/dashboards/${encodeURIComponent(dashboardId)}`
      : '/api/v1/dashboards/default';

    return this.request<DashboardConfig>('GET', path);
  }

  async getDashboards(): Promise<DashboardConfig[]> {
    return this.request<DashboardConfig[]>('GET', '/api/v1/dashboards');
  }

  async createDashboard(data: Partial<DashboardConfig>): Promise<DashboardConfig> {
    return this.request<DashboardConfig>('POST', '/api/v1/dashboards', data);
  }

  async updateDashboard(dashboardId: string, data: Partial<DashboardConfig>): Promise<DashboardConfig> {
    if (!dashboardId || dashboardId.trim().length === 0) {
      throw new SdkValidationError('Dashboard ID cannot be empty');
    }
    return this.request<DashboardConfig>('PUT', `/api/v1/dashboards/${encodeURIComponent(dashboardId)}`, data);
  }

  async deleteDashboard(dashboardId: string): Promise<void> {
    if (!dashboardId || dashboardId.trim().length === 0) {
      throw new SdkValidationError('Dashboard ID cannot be empty');
    }
    await this.request<void>('DELETE', `/api/v1/dashboards/${encodeURIComponent(dashboardId)}`);
  }

  async addDashboardWidget(dashboardId: string, widget: Partial<DashboardWidget>): Promise<DashboardConfig> {
    return this.request<DashboardConfig>('POST', `/api/v1/dashboards/${encodeURIComponent(dashboardId)}/widgets`, widget);
  }

  async removeDashboardWidget(dashboardId: string, widgetId: string): Promise<DashboardConfig> {
    return this.request<DashboardConfig>('DELETE', `/api/v1/dashboards/${encodeURIComponent(dashboardId)}/widgets/${encodeURIComponent(widgetId)}`);
  }

  async getWidgetMetrics(
    widgetId: string,
    dashboardId?: string,
  ): Promise<Record<string, number[]>> {
    const path = dashboardId
      ? `/api/v1/dashboards/${encodeURIComponent(dashboardId)}/widgets/${encodeURIComponent(widgetId)}/metrics`
      : `/api/v1/widgets/${encodeURIComponent(widgetId)}/metrics`;

    return this.request<Record<string, number[]>>('GET', path);
  }

  async getHealth(): Promise<{
    status: string;
    version: string;
    uptime: number;
    checks: Record<string, string>;
    components: Record<string, { status: string; latency_ms: number; last_check: string }>;
  }> {
    return this.request<{
      status: string;
      version: string;
      uptime: number;
      checks: Record<string, string>;
      components: Record<string, { status: string; latency_ms: number; last_check: string }>;
    }>('GET', '/api/v1/health');
  }

  async healthCheck(): Promise<{ healthy: boolean; status: string; latencyMs: number }> {
    const startTime = Date.now();
    try {
      const health = await this.getHealth();
      return {
        healthy: health.status === 'healthy' || health.status === 'ok',
        status: health.status,
        latencyMs: Date.now() - startTime,
      };
    } catch {
      return {
        healthy: false,
        status: 'unreachable',
        latencyMs: Date.now() - startTime,
      };
    }
  }

  async getHealthDetailed(): Promise<Record<string, unknown>> {
    const health = await this.getHealth();
    return {
      ...health,
      healthy: health.status === 'healthy',
      allComponentsHealthy: Object.values(health.components ?? {}).every((c) => c.status === 'healthy'),
    };
  }

  async getMonitors(): Promise<MonitorConfig[]> {
    return this.request<MonitorConfig[]>('GET', '/api/v1/monitors');
  }

  async getMonitor(monitorId: string): Promise<MonitorConfig> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    return this.request<MonitorConfig>('GET', `/api/v1/monitors/${encodeURIComponent(monitorId)}`);
  }

  async createMonitor(data: Partial<MonitorConfig>): Promise<MonitorConfig> {
    return this.request<MonitorConfig>('POST', '/api/v1/monitors', data);
  }

  async updateMonitor(monitorId: string, data: Partial<MonitorConfig>): Promise<MonitorConfig> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    return this.request<MonitorConfig>('PUT', `/api/v1/monitors/${encodeURIComponent(monitorId)}`, data);
  }

  async deleteMonitor(monitorId: string): Promise<void> {
    if (!monitorId || monitorId.trim().length === 0) {
      throw new SdkValidationError('Monitor ID cannot be empty');
    }
    await this.request<void>('DELETE', `/api/v1/monitors/${encodeURIComponent(monitorId)}`);
  }

  async toggleMonitor(monitorId: string, enabled: boolean): Promise<MonitorConfig> {
    return this.request<MonitorConfig>('PATCH', `/api/v1/monitors/${encodeURIComponent(monitorId)}`, { enabled });
  }

  async getThresholds(): Promise<MetricsThreshold[]> {
    return this.request<MetricsThreshold[]>('GET', '/api/v1/thresholds');
  }

  async getThreshold(thresholdId: string): Promise<MetricsThreshold> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    return this.request<MetricsThreshold>('GET', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`);
  }

  async createThreshold(data: Partial<MetricsThreshold>): Promise<MetricsThreshold> {
    return this.request<MetricsThreshold>('POST', '/api/v1/thresholds', data);
  }

  async updateThreshold(thresholdId: string, data: Partial<MetricsThreshold>): Promise<MetricsThreshold> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    return this.request<MetricsThreshold>('PUT', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`, data);
  }

  async deleteThreshold(thresholdId: string): Promise<void> {
    if (!thresholdId || thresholdId.trim().length === 0) {
      throw new SdkValidationError('Threshold ID cannot be empty');
    }
    await this.request<void>('DELETE', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`);
  }

  async evaluateThreshold(thresholdId: string, currentValue: number): Promise<{
    triggered: boolean;
    severity: 'ok' | 'warning' | 'critical';
    message?: string;
  }> {
    const threshold = await this.getThreshold(thresholdId);

    const evaluate = (val: number): { severity: 'ok' | 'warning' | 'critical'; triggered: boolean } => {
      switch (threshold.comparison_operator) {
        case 'greater_than':
          if (val > threshold.critical_value) return { severity: 'critical', triggered: true };
          if (val > threshold.warning_value) return { severity: 'warning', triggered: true };
          return { severity: 'ok', triggered: false };
        case 'less_than':
          if (val < threshold.critical_value) return { severity: 'critical', triggered: true };
          if (val < threshold.warning_value) return { severity: 'warning', triggered: true };
          return { severity: 'ok', triggered: false };
        default:
          return { severity: 'ok', triggered: false };
      }
    };

    const result = evaluate(currentValue);
    return {
      ...result,
      message: result.triggered
        ? `Metric ${threshold.metric_name} is at ${currentValue} (${result.severity} threshold)`
        : undefined,
    };
  }

  startPolling(
    name: string,
    callback: (data: MetricsSnapshot) => void,
    intervalMs?: number,
  ): void {
    if (this.pollingTimers.has(name)) {
      throw new SdkValidationError(`Polling already active: ${name}`);
    }

    const poll = async (): Promise<void> => {
      try {
        const data = await this.getMetrics();
        callback(data);
      } catch (error) {
        console.warn(`[SDK] Polling error for ${name}:`, error);
      }
    };

    poll();
    const timer = setInterval(poll, intervalMs ?? this.defaultPollIntervalMs);
    this.pollingTimers.set(name, timer);
  }

  stopPolling(name: string): boolean {
    const timer = this.pollingTimers.get(name);
    if (timer) {
      clearInterval(timer);
      this.pollingTimers.delete(name);
      return true;
    }
    return false;
  }

  stopAllPolling(): void {
    for (const [name, timer] of this.pollingTimers.entries()) {
      clearInterval(timer);
      this.pollingTimers.delete(name);
    }
  }

  async getSystemInfo(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('GET', '/api/v1/info');
  }

  async getPerformanceMetrics(): Promise<Record<string, unknown>> {
    const metrics = await this.getMetricsSummary();
    return {
      cpu: metrics.cpu_usage_percent,
      memory: metrics.memory_usage_percent,
      disk: metrics.disk_usage_percent,
      requests: metrics.request_count,
      errors: metrics.error_count,
      latency: metrics.average_latency_ms,
      p99Latency: metrics.p99_latency_ms,
      evaluations: metrics.rule_evaluation_count,
      violations: metrics.violation_count,
      blocked: metrics.blocked_count,
      activeRules: metrics.active_rule_count,
      cacheHitRate: metrics.cache_hit_rate,
      queueDepth: metrics.processing_queue_depth,
    };
  }

  async getAlertHistory(
    hours: number = 24,
    severity?: AlertSeverity,
  ): Promise<{ events: AlertEvent[]; timeline: Record<string, number> }> {
    const since = new Date(Date.now() - hours * 3600000).toISOString();
    const params: Record<string, string | undefined> = {
      since,
      severity: severity as string | undefined,
      page_size: '1000',
    };

    const result = await this.request<{ alerts: AlertEvent[]; total: number }>('GET', '/api/v1/alerts', undefined, params);

    const timeline: Record<string, number> = {};
    for (const alert of result.alerts) {
      const hour = new Date(alert.triggered_at).toISOString().substring(0, 13);
      timeline[hour] = (timeline[hour] ?? 0) + 1;
    }

    return { events: result.alerts, timeline };
  }

  async getDashboardSnapshots(
    dashboardId: string,
    hours: number = 24,
  ): Promise<MetricsSnapshot[]> {
    const params: Record<string, string | undefined> = {
      dashboard_id: dashboardId,
      since: new Date(Date.now() - hours * 3600000).toISOString(),
    };
    return this.request<MetricsSnapshot[]>('GET', '/api/v1/metrics/snapshots', undefined, params);
  }

  async exportMetrics(
    names: string[],
    format: 'json' | 'csv' = 'json',
    window?: string,
  ): Promise<string> {
    const params: Record<string, string | undefined> = {
      names: names.join(','),
      format,
      window,
    };
    return this.request<string>('GET', '/api/v1/metrics/export', undefined, params);
  }

  async checkMetricThreshold(
    metricName: string,
    thresholdId: string,
  ): Promise<{ ok: boolean; detail: string }> {
    try {
      const metricData = await this.getMetric(metricName);
      const currentValue = metricData.values[metricData.values.length - 1] ?? 0;
      const result = await this.evaluateThreshold(thresholdId, currentValue);
      return {
        ok: !result.triggered,
        detail: result.message ?? `Metric ${metricName} = ${currentValue}`,
      };
    } catch (error) {
      return {
        ok: false,
        detail: error instanceof Error ? error.message : 'Check failed',
      };
    }
  }

  async getComponentStatus(): Promise<Record<string, { status: string; metrics: Record<string, number> }>> {
    const health = await this.getHealth();
    const components: Record<string, { status: string; metrics: Record<string, number> }> = {};

    for (const [name, info] of Object.entries(health.components ?? {})) {
      components[name] = {
        status: typeof info === 'object' && info !== null ? (info as Record<string, unknown>).status as string : 'unknown',
        metrics: {},
      };
    }

    return components;
  }

  async getUptime(): Promise<{ uptimeSeconds: number; uptimeHuman: string; startedAt: string }> {
    const health = await this.getHealth();
    const uptime = health.uptime ?? 0;
    return {
      uptimeSeconds: uptime,
      uptimeHuman: this.formatUptime(uptime),
      startedAt: new Date(Date.now() - uptime * 1000).toISOString(),
    };
  }

  private formatUptime(seconds: number): string {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const parts: string[] = [];
    if (days > 0) parts.push(`${days}d`);
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);
    parts.push(`${secs}s`);
    return parts.join(' ');
  }

  async getAlertRate(
    windowMinutes: number = 60,
  ): Promise<{ alertsPerMinute: number; totalAlerts: number; windowMinutes: number }> {
    const since = new Date(Date.now() - windowMinutes * 60000).toISOString();
    const params: Record<string, string | undefined> = {
      since,
      page_size: '1',
    };
    const result = await this.request<{ total: number }>('GET', '/api/v1/alerts', undefined, params);

    return {
      alertsPerMinute: windowMinutes > 0 ? result.total / windowMinutes : 0,
      totalAlerts: result.total,
      windowMinutes,
    };
  }

  dispose(): void {
    this.stopAllPolling();
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  getRequestCount(): number {
    return this.requestCount;
  }
}
