"""Operational Rule Engine - Tier 2 enforcement with advisory handling."""
import logging
import re
import json
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleSeverity, RuleContext
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class OperationalAction(str, Enum):
    WARNING = "warning"
    BLOCK = "block"
    LOG = "log"
    SUGGESTION = "suggestion"


class OperationalImpact(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperationalCategory:
    def __init__(
        self,
        name: str,
        severity: RuleSeverity,
        action: OperationalAction,
        patterns: List[str],
        regex_patterns: Optional[List[str]] = None,
        exemptions: Optional[List[str]] = None,
        description: str = "",
        performance_impact: OperationalImpact = OperationalImpact.LOW,
        override_requires_justification: bool = False,
        auto_resolve_after: Optional[int] = None,
    ):
        self.name = name
        self.severity = severity
        self.action = action
        self.patterns = [p.lower() for p in patterns]
        self.regex_patterns = regex_patterns or []
        self.exemptions = [e.lower() for e in (exemptions or [])]
        self.description = description
        self.performance_impact = performance_impact
        self.override_requires_justification = override_requires_justification
        self.auto_resolve_after = auto_resolve_after

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "action": self.action.value,
            "pattern_count": len(self.patterns),
            "regex_count": len(self.regex_patterns),
            "exemption_count": len(self.exemptions),
            "performance_impact": self.performance_impact.value,
            "override_requires_justification": self.override_requires_justification,
            "auto_resolve_after": self.auto_resolve_after,
            "description": self.description,
        }


class OverrideRecord:
    def __init__(
        self,
        category: str,
        user_id: str,
        justification: str,
        timestamp: Optional[datetime] = None,
    ):
        self.category = category
        self.user_id = user_id
        self.justification = justification
        self.timestamp = timestamp or datetime.utcnow()
        self.resolved: bool = False
        self.resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "user_id": self.user_id,
            "justification": self.justification,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def resolve(self) -> None:
        self.resolved = True
        self.resolved_at = datetime.utcnow()


class OperationalStats:
    def __init__(self):
        self.evaluation_count: int = 0
        self.warning_count: int = 0
        self.block_count: int = 0
        self.log_count: int = 0
        self.suggestion_count: int = 0
        self.category_counts: Dict[str, int] = {}
        self.override_count: int = 0
        self.override_by_category: Dict[str, int] = {}
        self.total_processing_time_ms: int = 0
        self.performance_impact_scores: Dict[str, float] = {}
        self.adherence_rate: float = 1.0
        self.total_resolved_overrides: int = 0

    def record_match(
        self, category: str, action: OperationalAction, processing_ms: int
    ) -> None:
        self.evaluation_count += 1
        self.total_processing_time_ms += processing_ms
        self.category_counts[category] = self.category_counts.get(category, 0) + 1
        if action == OperationalAction.WARNING:
            self.warning_count += 1
        elif action == OperationalAction.BLOCK:
            self.block_count += 1
        elif action == OperationalAction.LOG:
            self.log_count += 1
        elif action == OperationalAction.SUGGESTION:
            self.suggestion_count += 1

    def record_override(self, category: str) -> None:
        self.override_count += 1
        self.override_by_category[category] = (
            self.override_by_category.get(category, 0) + 1
        )

    def get_summary(self) -> Dict[str, Any]:
        return {
            "evaluation_count": self.evaluation_count,
            "warning_count": self.warning_count,
            "block_count": self.block_count,
            "log_count": self.log_count,
            "suggestion_count": self.suggestion_count,
            "category_counts": dict(self.category_counts),
            "override_count": self.override_count,
            "override_by_category": dict(self.override_by_category),
            "avg_processing_time_ms": round(
                self.total_processing_time_ms / max(self.evaluation_count, 1), 2
            ),
            "adherence_rate": round(self.adherence_rate, 4),
            "total_resolved_overrides": self.total_resolved_overrides,
            "total_processing_time_ms": self.total_processing_time_ms,
        }


class OperationalRuleEngine:
    """Tier 2 Operational Rule Engine with advisory enforcement."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.tier = RuleTier.OPERATIONAL
        self.config = config or {}
        self.stats = OperationalStats()
        self._compiled_regexes: Dict[str, re.Pattern] = {}
        self._categories: List[OperationalCategory] = []
        self._override_log: List[OverrideRecord] = []
        self._initialize_categories()
        self._compile_regexes()
        logger.info(
            "OperationalRuleEngine initialized with %d categories, %d total patterns",
            len(self._categories),
            sum(len(c.patterns) + len(c.regex_patterns) for c in self._categories),
        )

    def _initialize_categories(self) -> None:
        self._categories = [
            OperationalCategory(
                name="copyright",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "copyright violation", "copyright infringement",
                    "unauthorized reproduction", "intellectual property theft",
                    "plagiarized content", "copyrighted material",
                    "license violation", "dmca notice", "cease and desist copyright",
                    "stolen content", "pirated material", "copyright claim",
                ],
                regex_patterns=[
                    r"\b(copyright|dmca|cease.?and.?desist)\s+(violation|infring|notice|claim)",
                    r"\b(plagiar|stolen.?content|pirated)\s+(content|material|work)",
                ],
                description="Copyright or intellectual property violations",
                performance_impact=OperationalImpact.LOW,
                override_requires_justification=True,
                auto_resolve_after=86400,
            ),
            OperationalCategory(
                name="pii",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.BLOCK,
                patterns=[
                    "personal information", "personally identifiable",
                    "private data leak", "confidential personal data",
                    "sensitive personal information", "personal records exposure",
                    "employee personal data", "customer private data",
                ],
                regex_patterns=[
                    r"\b(pii|personally.?identifiable|personal.?data|private.?data)\s+(leak|expos|breach|disclosure)",
                    r"\b(employee|customer|patient|client)\s+(personal|private|confidential)\s+(data|info|record)",
                ],
                description="Personally identifiable information handling",
                performance_impact=OperationalImpact.HIGH,
                override_requires_justification=True,
            ),
            OperationalCategory(
                name="language",
                severity=RuleSeverity.LOW,
                action=OperationalAction.WARNING,
                patterns=[
                    "inappropriate language", "profanity", "offensive language",
                    "vulgar content", "obscene language", "explicit language",
                    "abusive language", "hateful language", "derogatory terms",
                    "discriminatory language", "slur usage",
                ],
                regex_patterns=[
                    r"\b(inappropriate|offensive|vulgar|obscene|abusive|hateful)\s+(language|content|speech|term|word)",
                    r"\b(discriminatory|derogatory|pejorative)\s+(language|term|remark|statement)",
                ],
                description="Inappropriate or offensive language usage",
                performance_impact=OperationalImpact.LOW,
                override_requires_justification=False,
            ),
            OperationalCategory(
                name="data_quality",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "incomplete data", "missing required field",
                    "data validation error", "corrupted data",
                    "inconsistent data format", "duplicate entry",
                    "stale data", "outdated information",
                    "data integrity issue", "data quality issue",
                ],
                regex_patterns=[
                    r"\b(data|record|entry|field)\s+(incomplete|missing|corrupted|invalid|duplicate|stale|outdated)",
                    r"\b(data.?quality|data.?integrity)\s+(issue|problem|error|violation|fail)",
                ],
                description="Data quality and integrity issues",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=3600,
            ),
            OperationalCategory(
                name="compliance",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.BLOCK,
                patterns=[
                    "regulatory violation", "compliance breach",
                    "gdpr violation", "hipaa violation",
                    "sox non compliance", "pci dss violation",
                    "data protection breach", "privacy regulation violation",
                    "industry standard non compliance", "legal requirement breach",
                ],
                regex_patterns=[
                    r"\b(gdpr|hipaa|sox|pci.?dss|ccpa|ferpa|coppa)\s+(violation|breach|non.?complian|infring)",
                    r"\b(regulatory|compliance|legal|statutory)\s+(violation|breach|non.?complian|fail)",
                ],
                description="Regulatory or compliance violations",
                performance_impact=OperationalImpact.CRITICAL,
                override_requires_justification=True,
            ),
            OperationalCategory(
                name="security_best_practice",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.WARNING,
                patterns=[
                    "insecure configuration", "security misconfiguration",
                    "weak encryption", "plaintext password storage",
                    "unsecured endpoint", "missing authentication",
                    "exposed debug endpoint", "hardcoded secret",
                    "insecure direct object reference", "missing rate limiting",
                    "improper access control", "insecure deserialization",
                ],
                regex_patterns=[
                    r"\b(insecure|weak|missing|exposed|hardcoded|unsecured)\s+(config|encryption|auth|endpoint|secret|access)",
                    r"\b(security|access.?control|auth)\s+(misconfig|weakness|hole|gap|bypass)",
                ],
                description="Security best practice violations",
                performance_impact=OperationalImpact.CRITICAL,
                override_requires_justification=True,
                auto_resolve_after=86400,
            ),
            OperationalCategory(
                name="naming_convention",
                severity=RuleSeverity.LOW,
                action=OperationalAction.WARNING,
                patterns=[
                    "inconsistent naming", "naming convention violation",
                    "non standard naming", "naming pattern mismatch",
                    "bad variable name", "non descriptive identifier",
                    "hungarian notation misuse", "snake case required",
                    "camel case required", "naming style violation",
                ],
                regex_patterns=[
                    r"\b(naming|name.?convention|identifier|variable)\s+(violation|inconsistent|non.?standard|bad|wrong)",
                    r"\b(snake.?case|camel.?case|pascal.?case|kebab.?case)\s+(required|expected|violation)",
                ],
                description="Naming convention violations",
                performance_impact=OperationalImpact.LOW,
            ),
            OperationalCategory(
                name="code_quality",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "code duplication", "dead code", "unreachable code",
                    "complex function", "deep nesting", "magic number",
                    "todo left in code", "fixme left in code",
                    "hardcoded value", "insufficient error handling",
                    "missing null check", "resource leak",
                    "memory leak potential", "unused import",
                    "unused variable", "empty catch block",
                ],
                regex_patterns=[
                    r"\b(code|function|method|class)\s+(duplication|duplicate|dead|unreachable|complex|deeply.?nest)",
                    r"\b(todo|fixme|hack|workaround|temp)\s+(left|found|in.?code|present)",
                ],
                description="Code quality issues and anti-patterns",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="dependency_risk",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "outdated dependency", "vulnerable package",
                    "deprecated library", "unmaintained dependency",
                    "license risk dependency", "malicious package detected",
                    "supply chain risk", "unverified package source",
                    "peer dependency conflict", "version mismatch",
                ],
                regex_patterns=[
                    r"\b(dependency|package|library|module)\s+(outdated|vulnerable|deprecated|unmaintained|risky|malicious)",
                    r"\b(supply.?chain|version.?conflict|peer.?depend)\s+(risk|vulnerability|issue|conflict)",
                ],
                description="Dependency and supply chain risks",
                performance_impact=OperationalImpact.HIGH,
                auto_resolve_after=86400,
            ),
            OperationalCategory(
                name="documentation",
                severity=RuleSeverity.LOW,
                action=OperationalAction.SUGGESTION,
                patterns=[
                    "missing documentation", "incomplete documentation",
                    "outdated documentation", "no docstring",
                    "missing readme", "missing api documentation",
                    "insufficient comments", "no changelog",
                    "missing architecture doc", "unclear documentation",
                ],
                regex_patterns=[
                    r"\b(documentation|docstring|readme|changelog|api.?doc)\s+(missing|incomplete|outdated|insufficient|absent)",
                    r"\b(no|without|missing)\s+(documentation|comments|docstring|readme)",
                ],
                description="Documentation gaps or quality issues",
                performance_impact=OperationalImpact.LOW,
            ),
            OperationalCategory(
                name="performance",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "performance regression", "slow query detected",
                    "n+1 query pattern", "unoptimized loop",
                    "memory leak symptom", "cpu spike detected",
                    "high latency endpoint", "inefficient algorithm",
                    "unbounded collection", "synchronous bottleneck",
                ],
                regex_patterns=[
                    r"\b(performance|perf|slow|latency)\s+(regression|degradation|bottleneck|spike|issue|problem)",
                    r"\b(n\+1|unoptimized|inefficient|unbounded|synchronous)\s+(query|loop|algorithm|collection|calls?)",
                ],
                description="Performance issues and anti-patterns",
                performance_impact=OperationalImpact.HIGH,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="logging",
                severity=RuleSeverity.LOW,
                action=OperationalAction.WARNING,
                patterns=[
                    "missing error log", "excessive logging",
                    "log contains sensitive data", "no structured logging",
                    "inconsistent log format", "log level misuse",
                    "missing audit trail", "insufficient logging",
                    "log injection risk", "log forging risk",
                ],
                regex_patterns=[
                    r"\b(log|logging|audit.?trail)\s+(missing|excessive|insufficient|inconsistent|misuse|injection|forge)",
                    r"\b(log|log.?entry)\s+(sensitive|password|secret|private|pii)",
                ],
                description="Logging issues or audit trail gaps",
                performance_impact=OperationalImpact.LOW,
                auto_resolve_after=86400,
            ),
            OperationalCategory(
                name="testing",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "insufficient test coverage", "missing unit test",
                    "missing integration test", "flaky test detected",
                    "test without assertion", "skipped test",
                    "incomplete test suite", "no edge case coverage",
                    "missing regression test", "test data dependency",
                ],
                regex_patterns=[
                    r"\b(test|unit.?test|integration.?test|coverage)\s+(missing|insufficient|flaky|skipped|incomplete|without)",
                    r"\b(edge.?case|regression|acceptance)\s+(test|coverage|missed|missing)",
                ],
                description="Testing gaps or quality issues",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="deployment",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.BLOCK,
                patterns=[
                    "missing rollback plan", "deployment without backup",
                    "broken migration script", "incompatible schema change",
                    "deployment config error", "missing health check",
                    "zero downtime violation", "canary deployment misconfig",
                    "blue green deployment error", "infrastructure drift",
                ],
                regex_patterns=[
                    r"\b(deploy|rollout|release|migration)\s+(without|missing|broken|error|fail|misconfig)",
                    r"\b(rollback|backup|health.?check|canary|blue.?green)\s+(missing|fail|error|broken|violation)",
                ],
                description="Deployment process violations",
                performance_impact=OperationalImpact.CRITICAL,
                override_requires_justification=True,
            ),
            OperationalCategory(
                name="monitoring",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "missing alert", "insufficient monitoring",
                    "no observability", "missing metric",
                    "alert fatigue risk", "missing dashboard",
                    "no slo defined", "missing tracing",
                    "insufficient telemetry", "black box operation",
                ],
                regex_patterns=[
                    r"\b(monitor|alert|metric|telemetry|observability|tracing|dashboard)\s+(missing|insufficient|no|without|fatigue)",
                    r"\b(slo|sla|sli)\s+(missing|undefined|not.?defined|without)",
                ],
                description="Monitoring and observability gaps",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=86400,
            ),
            OperationalCategory(
                name="backup_recovery",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.WARNING,
                patterns=[
                    "missing backup", "backup failure",
                    "no disaster recovery plan", "unrecoverable data",
                    "backup verification failure", "rpo violation",
                    "rto violation", "no offsite backup",
                    "backup corruption detected", "restore test never run",
                ],
                regex_patterns=[
                    r"\b(backup|recovery|disaster.?recovery|restore)\s+(missing|fail|never|violation|corrupt|unrecoverable)",
                    r"\b(rpo|rto|recovery.?point|recovery.?time)\s+(violation|exceeded|missing|breach)",
                ],
                description="Backup and disaster recovery issues",
                performance_impact=OperationalImpact.CRITICAL,
                override_requires_justification=True,
            ),
            OperationalCategory(
                name="cost_optimization",
                severity=RuleSeverity.LOW,
                action=OperationalAction.SUGGESTION,
                patterns=[
                    "cost overrun detected", "wasteful resource allocation",
                    "unused resource", "orphaned resource",
                    "oversized instance", "underutilized capacity",
                    "inefficient storage tier", "data transfer cost spike",
                    "unnecessary api call", "cost optimization opportunity",
                ],
                regex_patterns=[
                    r"\b(cost|spend|budget|resource)\s+(overrun|waste|orphaned|unused|oversized|underutilized|spike)",
                    r"\b(inefficient|unnecessary|optimization)\s+(resource|storage|api.?call|allocation|tier)",
                ],
                description="Cost optimization opportunities",
                performance_impact=OperationalImpact.LOW,
            ),
            OperationalCategory(
                name="scalability",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "scalability bottleneck", "vertical scaling limit",
                    "no auto scaling config", "single point of failure",
                    "connection pool exhaustion", "thread starvation",
                    "queue backpressure", "database connection limit",
                    "no caching strategy", "synchronous scaling limit",
                ],
                regex_patterns=[
                    r"\b(scalability|scaling|bottleneck|auto.?scale)\s+(limit|issue|problem|missing|no|exhaustion|starvation)",
                    r"\b(single.?point.?of.?failure|connection.?pool|thread.?starve|backpressure|cache.?miss)",
                ],
                description="Scalability concerns and bottlenecks",
                performance_impact=OperationalImpact.HIGH,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="error_handling",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "unhandled exception", "generic error message",
                    "user unfriendly error", "stack trace exposed",
                    "error disclosure vulnerability", "improper error handling",
                    "missing try catch", "uncaught promise rejection",
                    "silent failure", "error swallowing",
                ],
                regex_patterns=[
                    r"\b(error|exception|failure)\s+(unhandled|uncaught|silent|swallow|generic|exposed|disclosure)",
                    r"\b(try.?catch|error.?handling|exception.?handling)\s+(missing|improper|insufficient|wrong)",
                ],
                description="Error handling issues and anti-patterns",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="api_design",
                severity=RuleSeverity.MEDIUM,
                action=OperationalAction.WARNING,
                patterns=[
                    "rest api violation", "api versioning missing",
                    "breaking api change", "inconsistent api response",
                    "missing api validation", "api rate limit missing",
                    "api pagination missing", "api error format inconsistent",
                    "api security issue", "api deprecation missing",
                ],
                regex_patterns=[
                    r"\b(api|rest|endpoint)\s+(violation|versioning|breaking|inconsistent|missing|wrong|deprecat)",
                    r"\b(rate.?limit|pagination|validat|error.?format)\s+(missing|inconsistent|wrong|violation)",
                ],
                description="API design best practice violations",
                performance_impact=OperationalImpact.MEDIUM,
                auto_resolve_after=604800,
            ),
            OperationalCategory(
                name="access_control_operational",
                severity=RuleSeverity.HIGH,
                action=OperationalAction.WARNING,
                patterns=[
                    "excessive permissions", "privilege escalation risk",
                    "least privilege violation", "shared account usage",
                    "service account misuse", "role assignment error",
                    "permission creep detected", "unused access right",
                    "temporary access expired", "cross account access",
                ],
                regex_patterns=[
                    r"\b(permission|access|privilege|role)\s+(excessive|escalat|violation|creep|misuse|error|expired)",
                    r"\b(least.?privilege|shared.?account|service.?account|cross.?account)\s+(violation|misuse|error|risk)",
                ],
                description="Access control operational issues",
                performance_impact=OperationalImpact.CRITICAL,
                override_requires_justification=True,
            ),
        ]
        custom_categories = self.config.get("custom_categories", [])
        for cat_data in custom_categories:
            self._categories.append(OperationalCategory(
                name=cat_data.get("name", "custom"),
                severity=RuleSeverity(cat_data.get("severity", "medium")),
                action=OperationalAction(cat_data.get("action", "warning")),
                patterns=cat_data.get("patterns", []),
                regex_patterns=cat_data.get("regex_patterns", []),
                exemptions=cat_data.get("exemptions", []),
                description=cat_data.get("description", ""),
                performance_impact=OperationalImpact(cat_data.get("performance_impact", "low")),
                override_requires_justification=cat_data.get("override_requires_justification", False),
                auto_resolve_after=cat_data.get("auto_resolve_after"),
            ))
        disabled = set(self.config.get("disabled_categories", []))
        self._categories = [c for c in self._categories if c.name not in disabled]

    def _compile_regexes(self) -> None:
        for category in self._categories:
            for regex in category.regex_patterns:
                try:
                    self._compiled_regexes[f"{category.name}:{regex}"] = re.compile(
                        regex, re.IGNORECASE
                    )
                except re.error as e:
                    logger.warning("Failed to compile regex for %s: %s", category.name, e)

    def _check_exemptions(
        self, content_lower: str, category: OperationalCategory, context: Optional[RuleContext]
    ) -> bool:
        for exemption in category.exemptions:
            if exemption.lower() in content_lower:
                logger.debug(
                    "Exemption '%s' matched for operational category '%s'",
                    exemption, category.name,
                )
                return True
        if context:
            effective = context.get_effective_context()
            exempt_domains = self.config.get("exempt_domains", [])
            if effective.get("domain") in exempt_domains:
                return True
        return False

    def _scan_content(
        self, content: str, content_lower: str
    ) -> List[Tuple[str, str, RuleSeverity, OperationalAction, float, bool, Optional[int]]]:
        matches: List[Tuple[str, str, RuleSeverity, OperationalAction, float, bool, Optional[int]]] = []
        seen_categories: Set[str] = set()
        for category in self._categories:
            if category.name in seen_categories:
                continue
            for pattern in category.patterns:
                idx = content_lower.find(pattern)
                if idx != -1:
                    matches.append((
                        category.name,
                        content[idx:idx + len(pattern)],
                        category.severity,
                        category.action,
                        0.88,
                        False,
                        idx,
                    ))
                    seen_categories.add(category.name)
                    break
        for category in self._categories:
            if category.name in seen_categories:
                continue
            for regex_str in category.regex_patterns:
                key = f"{category.name}:{regex_str}"
                compiled = self._compiled_regexes.get(key)
                if compiled:
                    match = compiled.search(content)
                    if match:
                        matches.append((
                            category.name,
                            match.group(),
                            category.severity,
                            category.action,
                            0.82,
                            True,
                            match.start(),
                        ))
                        seen_categories.add(category.name)
                        break
        return matches

    def _calculate_performance_score(self, matches_data: List[Tuple]) -> float:
        if not matches_data:
            return 0.0
        impact_weights = {
            OperationalImpact.NONE: 0.0,
            OperationalImpact.LOW: 0.25,
            OperationalImpact.MEDIUM: 0.50,
            OperationalImpact.HIGH: 0.75,
            OperationalImpact.CRITICAL: 1.0,
        }
        total_weight = 0.0
        for match_data in matches_data:
            category_name = match_data[0]
            category_obj = next(
                (c for c in self._categories if c.name == category_name), None
            )
            if category_obj:
                total_weight += impact_weights.get(category_obj.performance_impact, 0.25)
        raw_score = total_weight / len(matches_data)
        return round(raw_score, 4)

    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = datetime.utcnow()
        content = request.content
        content_lower = content.lower()

        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=0.9,
            request_id=f"operational_{self.stats.evaluation_count}",
            content_hash=str(hash(content))[:16],
        )

        matches_data = self._scan_content(content, content_lower)
        category_context = request.context.get_effective_context() if request.context else {}
        filtered_matches: List[Tuple] = []
        matched_categories: Set[str] = set()

        for match_data in matches_data:
            category_name = match_data[0]
            if category_name in matched_categories:
                continue
            category_obj = next(
                (c for c in self._categories if c.name == category_name), None
            )
            if category_obj and self._check_exemptions(
                content_lower, category_obj, request.context
            ):
                continue
            filtered_matches.append(match_data)
            matched_categories.add(category_name)

        performance_score = self._calculate_performance_score(filtered_matches)
        self.stats.performance_impact_scores[
            request.content_hash or str(hash(content))[:16]
        ] = performance_score

        for match_data in filtered_matches:
            category_name, matched_text, severity, action, confidence, is_regex, position = match_data
            category_obj = next(
                (c for c in self._categories if c.name == category_name), None
            )
            override_allowed = category_obj.override_requires_justification if category_obj else True

            if action == OperationalAction.WARNING:
                vt = ViolationType.COMPLIANCE_VIOLATION
            elif action == OperationalAction.BLOCK:
                vt = ViolationType.STRUCTURAL_VIOLATION
            elif action == OperationalAction.SUGGESTION:
                vt = ViolationType.QUALITY_VIOLATION
            else:
                vt = ViolationType.CUSTOM_VIOLATION

            action_taken_map = {
                OperationalAction.WARNING: ActionTaken.WARNING,
                OperationalAction.BLOCK: ActionTaken.BLOCK,
                OperationalAction.LOG: ActionTaken.NONE,
                OperationalAction.SUGGESTION: ActionTaken.SUGGESTION,
            }

            violation = Violation(
                rule_id=f"operational_{category_name}",
                rule_name=f"Operational Rule: {category_name}",
                rule_tier=RuleTier.OPERATIONAL,
                rule_severity=severity,
                violation_type=vt,
                matched_content=matched_text,
                matched_patterns=[matched_text],
                confidence_score=confidence,
                action_taken=action_taken_map.get(action, ActionTaken.WARNING),
                blocked=action == OperationalAction.BLOCK,
                user_override_allowed=override_allowed,
                explanation=f"Operational guideline: {category_name} (matched: {matched_text})",
                position_info=(
                    {"position": position, "performance_impact": performance_score}
                    if position is not None
                    else {"performance_impact": performance_score}
                ),
                context=category_context,
            )
            result.violations.append(violation)
            if action == OperationalAction.WARNING:
                result.warnings.append(violation)
            if action == OperationalAction.BLOCK:
                result.valid = False
            self.stats.record_match(
                category=category_name, action=action, processing_ms=0
            )
            logger.info(
                "Operational %s: category='%s' action=%s severity=%s impact=%s",
                "blocked" if violation.blocked else "detected",
                category_name,
                action.value,
                severity.value,
                category_obj.performance_impact.value if category_obj else "unknown",
            )

        processing_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.processing_time_ms = processing_ms
        result.total_rules_evaluated = len(self._categories)
        result.rules_triggered = len(result.violations)
        total_evaluations = self.stats.evaluation_count
        if total_evaluations > 0:
            self.stats.adherence_rate = round(
                1.0 - (self.stats.violation_count_override or 0) / total_evaluations, 4
            )

        logger.debug(
            "Operational evaluation completed: %d violations in %dms (perf_score=%s)",
            len(result.violations), processing_ms, performance_score,
        )
        return result

    @property
    def violation_count_override(self) -> int:
        return self.stats.warning_count + self.stats.block_count

    def record_override(
        self,
        category: str,
        user_id: str,
        justification: str,
        auto_resolve: bool = False,
    ) -> OverrideRecord:
        record = OverrideRecord(
            category=category,
            user_id=user_id,
            justification=justification,
        )
        if auto_resolve:
            category_obj = next(
                (c for c in self._categories if c.name == category), None
            )
            if category_obj and category_obj.auto_resolve_after:
                record.resolved = False
        self._override_log.append(record)
        self.stats.record_override(category)
        logger.info(
            "Override recorded: category='%s' user='%s'",
            category, user_id,
        )
        return record

    def resolve_override(self, record: OverrideRecord) -> None:
        record.resolve()
        self.stats.total_resolved_overrides += 1
        logger.info("Override resolved: category='%s'", record.category)

    def get_override_history(
        self,
        category: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        records = self._override_log
        if category:
            records = [r for r in records if r.category == category]
        if user_id:
            records = [r for r in records if r.user_id == user_id]
        records = records[-limit:]
        return [r.to_dict() for r in records]

    def get_override_count(self) -> int:
        return self.stats.override_count

    def get_active_auto_resolve_categories(self) -> List[str]:
        return [
            c.name for c in self._categories
            if c.auto_resolve_after is not None
        ]

    def get_categories(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self._categories]

    def get_active_categories(self) -> List[str]:
        return [c.name for c in self._categories]

    def get_category_detail(self, name: str) -> Optional[Dict[str, Any]]:
        for c in self._categories:
            if c.name == name:
                return c.to_dict()
        return None

    def get_statistics(self) -> Dict[str, Any]:
        return self.stats.get_summary()

    def get_performance_impact_scores(self) -> Dict[str, float]:
        return dict(self.stats.performance_impact_scores)

    def get_average_performance_impact(self) -> float:
        scores = list(self.stats.performance_impact_scores.values())
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 4)

    def add_custom_category(self, category_data: Dict[str, Any]) -> None:
        cat = OperationalCategory(
            name=category_data["name"],
            severity=RuleSeverity(category_data.get("severity", "medium")),
            action=OperationalAction(category_data.get("action", "warning")),
            patterns=category_data.get("patterns", []),
            regex_patterns=category_data.get("regex_patterns", []),
            exemptions=category_data.get("exemptions", []),
            description=category_data.get("description", ""),
            performance_impact=OperationalImpact(
                category_data.get("performance_impact", "low")
            ),
            override_requires_justification=category_data.get(
                "override_requires_justification", False
            ),
            auto_resolve_after=category_data.get("auto_resolve_after"),
        )
        self._categories.append(cat)
        for regex in cat.regex_patterns:
            try:
                self._compiled_regexes[f"{cat.name}:{regex}"] = re.compile(
                    regex, re.IGNORECASE
                )
            except re.error as e:
                logger.warning(
                    "Failed to compile regex for %s: %s", cat.name, e
                )
        logger.info("Added custom operational category: %s", cat.name)

    def remove_category(self, name: str) -> bool:
        before = len(self._categories)
        self._categories = [c for c in self._categories if c.name != name]
        keys_to_remove = [k for k in self._compiled_regexes if k.startswith(f"{name}:")]
        for k in keys_to_remove:
            del self._compiled_regexes[k]
        removed = len(self._categories) < before
        if removed:
            logger.info("Removed operational category: %s", name)
        return removed

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config.update(config)
        self._categories.clear()
        self._compiled_regexes.clear()
        self._initialize_categories()
        self._compile_regexes()
        logger.info("OperationalRuleEngine configuration updated")

    def get_override_rate(self) -> float:
        if self.stats.evaluation_count == 0:
            return 0.0
        return round(
            self.stats.override_count / self.stats.evaluation_count, 4
        )

    def get_adherence_rate(self) -> float:
        return self.stats.adherence_rate

    def reset_statistics(self) -> None:
        self.stats = OperationalStats()
        logger.info("OperationalRuleEngine statistics reset")

    def clear_override_log(self) -> None:
        self._override_log.clear()
        logger.info("Override log cleared")

    def get_warning_rate(self) -> float:
        if self.stats.evaluation_count == 0:
            return 0.0
        return round(
            self.stats.warning_count / self.stats.evaluation_count, 4
        )

    def get_block_rate(self) -> float:
        if self.stats.evaluation_count == 0:
            return 0.0
        return round(
            self.stats.block_count / self.stats.evaluation_count, 4
        )

    def get_category_statistics(self) -> Dict[str, Dict[str, int]]:
        result = {}
        all_categories = set(self.stats.category_counts.keys())
        all_categories.update(c.name for c in self._categories)
        for cat_name in sorted(all_categories):
            result[cat_name] = {
                "total_matches": self.stats.category_counts.get(cat_name, 0),
                "override_count": self.stats.override_by_category.get(cat_name, 0),
                "is_active": any(c.name == cat_name for c in self._categories),
            }
        return result
