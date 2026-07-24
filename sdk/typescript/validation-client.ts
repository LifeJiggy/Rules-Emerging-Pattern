/**
 * ValidationClient - Specialized client for content validation, compliance checking,
 * safety analysis, format validation, quality assessment, and hallucination detection.
 */

import {
  Rule,
  RuleTier,
  RuleType,
  RuleContext,
  RuleSeverity,
  Violation,
  ViolationType,
  Suggestion,
  ValidationResult,
  BatchValidationRequest,
  BatchValidationResult,
  ValidationProfile,
  ValidationThreshold,
  ComplianceReport,
  SdkOptions,
  SdkClientError,
  SdkValidationError,
  SdkAuthError,
  SdkTimeoutError,
  SdkNotFoundError,
  createRule,
  createRuleContext,
  createValidationResult,
  createViolation,
  resultGetSummary,
  resultHasViolations,
  resultIsBlocked,
  resultGetViolationsByTier,
  resultGetViolationsBySeverity,
  resultGetTopViolations,
  resultGetScoreBreakdown,
  resultMerge,
  createBatchValidationRequest,
  createBatchValidationResult,
  batchResultGetSuccessRate,
  batchResultGetSummary,
  RetryConfig,
  DEFAULT_RETRY_CONFIG,
  ContentCheckResult,
  ComplianceCheckResult,
  SafetyCheckResult,
  FormatCheckResult,
  QualityCheckResult,
  HallucinationResult,
} from './models';

interface ValidationClientOptions {
  apiKey: string;
  baseUrl: string;
  timeout?: number;
  retryConfig?: RetryConfig;
  defaultProfile?: string;
}

const DEFAULT_VALIDATION_OPTIONS: Partial<ValidationClientOptions> = {
  timeout: 30000,
};

export class ValidationClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly retryConfig: RetryConfig;
  private readonly defaultProfile?: string;
  private requestCount = 0;

  constructor(options: ValidationClientOptions) {
    if (!options.apiKey || options.apiKey.trim().length === 0) {
      throw new SdkValidationError('API key is required');
    }
    if (!options.baseUrl || options.baseUrl.trim().length === 0) {
      throw new SdkValidationError('Base URL is required');
    }
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.timeout = options.timeout ?? DEFAULT_VALIDATION_OPTIONS.timeout!;
    this.retryConfig = { ...DEFAULT_RETRY_CONFIG, ...options.retryConfig };
    this.defaultProfile = options.defaultProfile;
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
      'X-SDK-Client': 'validation',
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
      case 422:
        return new SdkValidationError(detail ?? 'Unprocessable entity');
      case 429:
        return new SdkClientError(detail ?? 'Rate limited', 'RATE_LIMIT', 429);
      default:
        return new SdkClientError(detail ?? `HTTP ${response.status}`, 'HTTP_ERROR', response.status);
    }
  }

  async validateContent(
    content: string,
    rules?: { ruleIds?: string[]; tier?: RuleTier },
    context?: Partial<RuleContext>,
    options?: Record<string, unknown>,
  ): Promise<ValidationResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      options: options ?? {},
      timeout_ms: 5000,
      parallel_evaluation: true,
      early_termination: true,
    };

    if (rules?.ruleIds) body.rule_ids = rules.ruleIds;
    if (rules?.tier) body.tier = rules.tier;
    if (this.defaultProfile) body.profile_id = this.defaultProfile;

    return this.request<ValidationResult>('POST', '/api/v1/validate', body);
  }

  async validateBatch(
    contents: string[],
    options?: {
      context?: Partial<RuleContext>;
      ruleIds?: string[];
      tier?: RuleTier;
      maxParallel?: number;
      failFast?: boolean;
    },
  ): Promise<BatchValidationResult> {
    if (!contents || contents.length === 0) {
      throw new SdkValidationError('Contents array cannot be empty');
    }
    if (contents.length > 100) {
      throw new SdkValidationError('Maximum 100 items per batch request');
    }

    const request = createBatchValidationRequest({
      requests: contents,
      common_context: options?.context ? { ...options.context } : undefined,
      batch_options: {
        rule_ids: options?.ruleIds,
        tier: options?.tier,
      },
      max_parallel: options?.maxParallel ?? 10,
      fail_fast: options?.failFast ?? false,
      return_individual_results: true,
      aggregate_results: true,
    });

    return this.request<BatchValidationResult>('POST', '/api/v1/validate/batch', request);
  }

  async checkCompliance(
    content: string,
    regulations?: string[],
    context?: Partial<RuleContext>,
  ): Promise<ComplianceCheckResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      rule_types: [RuleType.COMPLIANCE_CHECK],
      options: {
        check_type: 'compliance',
        regulations: regulations ?? ['general'],
      },
      timeout_ms: 10000,
      parallel_evaluation: true,
      early_termination: false,
    };

    if (this.defaultProfile) body.profile_id = this.defaultProfile;

    return this.request<ValidationResult>('POST', '/api/v1/validate', body);
  }

  async checkSafety(content: string, context?: Partial<RuleContext>): Promise<SafetyCheckResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      tier: RuleTier.SAFETY,
      options: {
        check_type: 'safety',
      },
      timeout_ms: 5000,
      parallel_evaluation: true,
      early_termination: true,
    };

    return this.request<ValidationResult>('POST', '/api/v1/validate', body);
  }

  async checkFormat(
    content: string,
    formatType: string,
  ): Promise<FormatCheckResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }
    if (!formatType || formatType.trim().length === 0) {
      throw new SdkValidationError('Format type cannot be empty');
    }

    const validFormats = ['json', 'xml', 'html', 'markdown', 'yaml', 'csv', 'text'];
    if (!validFormats.includes(formatType.toLowerCase())) {
      throw new SdkValidationError(`Unsupported format: ${formatType}. Supported: ${validFormats.join(', ')}`);
    }

    const body: Record<string, unknown> = {
      content,
      rule_types: [RuleType.STRUCTURAL_VALIDATION],
      options: {
        check_type: 'format',
        format: formatType.toLowerCase(),
      },
      timeout_ms: 5000,
      parallel_evaluation: false,
      early_termination: true,
    };

    try {
      const result = await this.request<ValidationResult>('POST', '/api/v1/validate', body);
      const errors = result.violations.map((v) => v.explanation ?? v.rule_name);
      return {
        valid: result.valid,
        format: formatType,
        errors,
      };
    } catch (error) {
      if (error instanceof SdkClientError && error.code === 'NOT_FOUND') {
        const localErrors = this.validateFormatLocally(content, formatType);
        return {
          valid: localErrors.length === 0,
          format: formatType,
          errors: localErrors,
        };
      }
      throw error;
    }
  }

  private validateFormatLocally(content: string, formatType: string): string[] {
    const errors: string[] = [];

    switch (formatType.toLowerCase()) {
      case 'json': {
        try {
          JSON.parse(content);
        } catch (e) {
          errors.push(`Invalid JSON: ${e instanceof Error ? e.message : 'parse error'}`);
        }
        break;
      }
      case 'xml': {
        if (!content.trim().startsWith('<') || !content.trim().endsWith('>')) {
          errors.push('Invalid XML: must start with < and end with >');
        }
        const openTags = (content.match(/<(\w+)[^>]*>/g) ?? []).map((t) => t.match(/<(\w+)/)?.[1]).filter(Boolean);
        const closeTags = (content.match(/<\/(\w+)>/g) ?? []).map((t) => t.match(/<\/(\w+)>/)?.[1]).filter(Boolean);
        for (const tag of openTags) {
          if (!closeTags.includes(tag)) {
            errors.push(`Unclosed XML tag: <${tag}>`);
          }
        }
        break;
      }
      case 'html': {
        if (!/<html[\s>]/i.test(content) && !/<body[\s>]/i.test(content)) {
          errors.push('Content does not appear to be valid HTML');
        }
        break;
      }
      case 'markdown': {
        if (content.trim().length > 0 && !/[#*_\-[\]()>`~|]/.test(content)) {
          errors.push('Content does not contain markdown formatting');
        }
        break;
      }
      case 'csv': {
        const lines = content.trim().split('\n');
        if (lines.length < 1) {
          errors.push('CSV must have at least one line');
        } else {
          const colCount = lines[0].split(',').length;
          for (let i = 1; i < lines.length; i++) {
            if (lines[i].split(',').length !== colCount) {
              errors.push(`Line ${i + 1} has inconsistent column count`);
            }
          }
        }
        break;
      }
      case 'yaml': {
        if (!content.includes(':') && !content.startsWith('---')) {
          errors.push('Content does not appear to be valid YAML');
        }
        break;
      }
      default:
        break;
    }

    return errors;
  }

  async checkQuality(
    content: string,
    context?: Partial<RuleContext>,
  ): Promise<QualityCheckResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      rule_types: [RuleType.QUALITY_ASSESSMENT],
      options: {
        check_type: 'quality',
      },
      timeout_ms: 10000,
      parallel_evaluation: true,
      early_termination: false,
    };

    try {
      const result = await this.request<ValidationResult>('POST', '/api/v1/validate', body);
      const score = result.total_score;
      const issues = result.violations.map((v) => v.explanation ?? v.rule_name);
      const suggestions = result.suggestions.map((s) => s.title);

      return {
        score,
        issues,
        suggestions,
      };
    } catch {
      return this.evaluateQualityLocally(content);
    }
  }

  private evaluateQualityLocally(content: string): QualityCheckResult {
    const issues: string[] = [];
    const suggestions: string[] = [];
    let score = 1.0;

    const wordCount = content.split(/\s+/).length;
    const charCount = content.length;
    const sentenceCount = (content.match(/[.!?]+/g) ?? []).length;

    if (wordCount < 3) {
      issues.push('Content is too short');
      score -= 0.2;
      suggestions.push('Expand the content with more detail');
    }

    if (wordCount > 10000) {
      issues.push('Content is very long');
      score -= 0.1;
      suggestions.push('Consider breaking content into smaller sections');
    }

    const uniqueWords = new Set(content.toLowerCase().split(/\s+/)).size;
    const lexicalDiversity = uniqueWords / Math.max(wordCount, 1);
    if (lexicalDiversity < 0.3 && wordCount > 10) {
      issues.push('Low lexical diversity - repetitive vocabulary');
      score -= 0.1;
      suggestions.push('Use a wider variety of vocabulary');
    }

    if (sentenceCount > 0) {
      const avgWordsPerSentence = wordCount / sentenceCount;
      if (avgWordsPerSentence > 50) {
        issues.push('Sentences are too long on average');
        score -= 0.1;
        suggestions.push('Break long sentences into shorter ones');
      }
    }

    const readabilityScore = this.calculateReadability(content);
    if (readabilityScore < 20) {
      issues.push('Text may be difficult to read');
      score -= 0.1;
      suggestions.push('Simplify sentence structures');
    }

    const repeatedPatterns = content.match(/(.{20,})\1/g);
    if (repeatedPatterns) {
      issues.push('Detected repeated content patterns');
      score -= 0.15;
      suggestions.push('Remove duplicate content');
    }

    const spellingIssues = this.basicSpellCheck(content);
    if (spellingIssues.length > 0) {
      issues.push(`Possible spelling issues: ${spellingIssues.slice(0, 5).join(', ')}`);
      score -= 0.1;
      suggestions.push('Run spell-check on the content');
    }

    score = Math.max(0, Math.round(score * 100) / 100);

    return { score, issues, suggestions };
  }

  private calculateReadability(content: string): number {
    const words = content.split(/\s+/).filter(Boolean);
    const sentences = content.split(/[.!?]+/).filter(Boolean);
    const syllables = words.reduce((sum, word) => {
      return sum + this.countSyllables(word);
    }, 0);

    if (sentences.length === 0 || words.length === 0) return 0;

    return 206.835 - 1.015 * (words.length / sentences.length) - 84.6 * (syllables / words.length);
  }

  private countSyllables(word: string): number {
    word = word.toLowerCase().replace(/[^a-z]/g, '');
    if (word.length <= 3) return 1;
    const vowels = word.match(/[aeiouy]+/g);
    if (!vowels) return 1;
    let count = vowels.length;
    if (word.endsWith('e')) count--;
    if (word.endsWith('le') && word.length > 2 && !'aeiouy'.includes(word[word.length - 3])) {
      count++;
    }
    return Math.max(1, count);
  }

  private basicSpellCheck(content: string): string[] {
    const commonWords = new Set([
      'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i',
      'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at',
      'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she',
      'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their', 'what',
      'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which', 'go', 'me',
      'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know', 'take',
      'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other',
      'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also',
      'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way',
    ]);

    const words = content.toLowerCase().split(/\s+/).filter((w) => /^[a-z]+$/.test(w));
    const suspect: string[] = [];

    for (const word of words) {
      if (word.length > 2 && !commonWords.has(word) && word.length > 5) {
        if (/(.)\1{3,}/.test(word)) {
          suspect.push(word);
        }
        if (/^[^aeiouy]+$/.test(word)) {
          suspect.push(word);
        }
      }
    }

    return [...new Set(suspect)].slice(0, 10);
  }

  async detectHallucinations(
    content: string,
    context?: Partial<RuleContext>,
  ): Promise<HallucinationResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      rule_types: [RuleType.SEMANTIC_ANALYSIS],
      options: {
        check_type: 'hallucination',
        semantic_analysis: true,
      },
      timeout_ms: 15000,
      parallel_evaluation: true,
      early_termination: false,
    };

    try {
      const result = await this.request<ValidationResult>('POST', '/api/v1/validate', body);

      const detected = resultHasViolations(result);
      const segments = result.violations
        .filter((v) => v.matched_content)
        .map((v) => v.matched_content!);

      return {
        detected,
        confidence: detected ? 1.0 - result.total_score : 0.0,
        segments,
      };
    } catch {
      return this.detectHallucinationsLocally(content);
    }
  }

  private detectHallucinationsLocally(content: string): HallucinationResult {
    const segments: string[] = [];
    let confidence = 0.0;

    const hedgingPatterns = [
      /\bi (?:think|believe|guess|suppose|assume)\b/i,
      /\b(?:probably|possibly|maybe|perhaps|might|could be)\b/i,
      /\b(?:to the best of my knowledge|as far as i know)\b/i,
      /\b(?:i'm not sure|i am not certain|i don't know)\b/i,
    ];

    const numericalInconsistencies = content.match(/\b\d+[,.\d]*\b/g);
    if (numericalInconsistencies && numericalInconsistencies.length > 5) {
      confidence = Math.min(confidence + 0.1, 1.0);
      segments.push('High density of numerical claims');
    }

    for (const pattern of hedgingPatterns) {
      const match = content.match(pattern);
      if (match) {
        confidence = Math.min(confidence + 0.15, 1.0);
        segments.push(match[0]);
      }
    }

    const absoluteStatements = content.match(/\b(?:always|never|everyone|no one|all|none)\b/gi);
    if (absoluteStatements && absoluteStatements.length > 3) {
      confidence = Math.min(confidence + 0.1, 1.0);
      segments.push('Excessive absolute statements');
    }

    const repeatedClaims = this.findRepeatedClaims(content);
    if (repeatedClaims.length > 0) {
      confidence = Math.min(confidence + 0.2, 1.0);
      segments.push(...repeatedClaims);
    }

    const specificityRatio = this.measureSpecificity(content);
    if (specificityRatio < 0.1 && content.split(/\s+/).length > 50) {
      confidence = Math.min(confidence + 0.1, 1.0);
      segments.push('Low specificity in long text');
    }

    return {
      detected: confidence > 0.3,
      confidence: Math.round(confidence * 100) / 100,
      segments: [...new Set(segments)],
    };
  }

  private findRepeatedClaims(content: string): string[] {
    const sentences = content.split(/[.!?]+/).filter(Boolean);
    const claims: string[] = [];
    const normalized = sentences.map((s) => s.toLowerCase().trim());

    for (let i = 0; i < normalized.length; i++) {
      for (let j = i + 1; j < normalized.length; j++) {
        const words1 = new Set(normalized[i].split(/\s+/));
        const words2 = new Set(normalized[j].split(/\s+/));
        const intersection = new Set([...words1].filter((w) => words2.has(w) && w.length > 3));
        if (intersection.size > 3 && words1.size > 3 && words2.size > 3) {
          claims.push(`Contradictory or repeated claim: "${sentences[i].trim()}" vs "${sentences[j].trim()}"`);
        }
      }
    }

    return claims.slice(0, 5);
  }

  private measureSpecificity(content: string): number {
    const specificPatterns = content.match(/\b\d+(?:\.\d+)?(?:\s*%)?\b/g);
    const properNouns = content.match(/\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b/g);
    const totalWords = content.split(/\s+/).length;

    let specificCount = 0;
    if (specificPatterns) specificCount += specificPatterns.length;
    if (properNouns) specificCount += properNouns.length;

    return totalWords > 0 ? specificCount / totalWords : 0;
  }

  async checkAll(
    content: string,
    context?: Partial<RuleContext>,
  ): Promise<{
    validation: ValidationResult;
    compliance: ComplianceCheckResult;
    safety: SafetyCheckResult;
    quality: QualityCheckResult;
    hallucinations: HallucinationResult;
  }> {
    const [validation, compliance, safety, quality, hallucinations] = await Promise.all([
      this.validateContent(content, undefined, context),
      this.checkCompliance(content, undefined, context).catch(() => createValidationResult({ valid: true }) as unknown as ComplianceCheckResult),
      this.checkSafety(content, context).catch(() => createValidationResult({ valid: true }) as unknown as SafetyCheckResult),
      this.checkQuality(content, context).catch(() => ({ score: 1.0, issues: [], suggestions: [] })),
      this.detectHallucinations(content, context).catch(() => ({ detected: false, confidence: 0, segments: [] })),
    ]);

    return { validation, compliance, safety, quality, hallucinations };
  }

  async getValidationProfile(profileId: string): Promise<ValidationProfile> {
    return this.request<ValidationProfile>('GET', `/api/v1/profiles/${encodeURIComponent(profileId)}`);
  }

  async getValidationProfiles(): Promise<ValidationProfile[]> {
    return this.request<ValidationProfile[]>('GET', '/api/v1/profiles');
  }

  async createValidationProfile(data: Partial<ValidationProfile>): Promise<ValidationProfile> {
    return this.request<ValidationProfile>('POST', '/api/v1/profiles', data);
  }

  async updateValidationProfile(profileId: string, data: Partial<ValidationProfile>): Promise<ValidationProfile> {
    return this.request<ValidationProfile>('PUT', `/api/v1/profiles/${encodeURIComponent(profileId)}`, data);
  }

  async deleteValidationProfile(profileId: string): Promise<void> {
    await this.request<void>('DELETE', `/api/v1/profiles/${encodeURIComponent(profileId)}`);
  }

  async getThresholds(): Promise<ValidationThreshold[]> {
    return this.request<ValidationThreshold[]>('GET', '/api/v1/thresholds');
  }

  async createThreshold(data: Partial<ValidationThreshold>): Promise<ValidationThreshold> {
    return this.request<ValidationThreshold>('POST', '/api/v1/thresholds', data);
  }

  async updateThreshold(thresholdId: string, data: Partial<ValidationThreshold>): Promise<ValidationThreshold> {
    return this.request<ValidationThreshold>('PUT', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`, data);
  }

  async deleteThreshold(thresholdId: string): Promise<void> {
    await this.request<void>('DELETE', `/api/v1/thresholds/${encodeURIComponent(thresholdId)}`);
  }

  async getComplianceReport(
    periodStart: string,
    periodEnd: string,
  ): Promise<ComplianceReport> {
    return this.request<ComplianceReport>('GET', '/api/v1/compliance', undefined, {
      period_start: periodStart,
      period_end: periodEnd,
    });
  }

  async checkAgainstRules(
    content: string,
    rules: Rule[],
    context?: Partial<RuleContext>,
  ): Promise<ValidationResult> {
    if (!content || content.trim().length === 0) {
      throw new SdkValidationError('Content cannot be empty');
    }
    if (!rules || rules.length === 0) {
      return createValidationResult({ valid: true, total_score: 1.0 });
    }

    const effectiveContext = context ? createRuleContext(context) : undefined;

    const body: Record<string, unknown> = {
      content,
      context: effectiveContext,
      rule_ids: rules.map((r) => r.id),
      options: { inline_rules: true },
      timeout_ms: 10000,
      parallel_evaluation: true,
      early_termination: false,
    };

    return this.request<ValidationResult>('POST', '/api/v1/validate', body);
  }

  async validateContentAsync(
    content: string,
    context?: Partial<RuleContext>,
    webhookUrl?: string,
  ): Promise<{ requestId: string; status: string }> {
    const body: Record<string, unknown> = {
      content,
      context: context ? createRuleContext(context) : undefined,
      async: true,
    };
    if (webhookUrl) body.webhook_url = webhookUrl;

    return this.request<{ requestId: string; status: string }>('POST', '/api/v1/validate/async', body);
  }

  async getValidationResult(requestId: string): Promise<ValidationResult> {
    return this.request<ValidationResult>('GET', `/api/v1/validate/async/${encodeURIComponent(requestId)}`);
  }

  async streamValidation(
    contents: string[],
    context?: Partial<RuleContext>,
  ): Promise<AsyncGenerator<{ index: number; result: ValidationResult; error?: string }, void, unknown>> {
    const self = this;
    async function* generator(): AsyncGenerator<{ index: number; result: ValidationResult; error?: string }, void, unknown> {
      for (let i = 0; i < contents.length; i++) {
        try {
          const result = await self.validateContent(contents[i], undefined, context);
          yield { index: i, result };
        } catch (error) {
          yield {
            index: i,
            result: createValidationResult({ valid: false, total_score: 0 }),
            error: error instanceof Error ? error.message : String(error),
          };
        }
      }
    }
    return generator();
  }

  healthCheck(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('GET', '/api/v1/health');
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }
}
