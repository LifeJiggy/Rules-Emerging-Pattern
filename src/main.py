"""Main FastAPI application for Rules-Emerging-Pattern."""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from src.core.rule_engine import RuleEngine
from src.core.tiered_rules.tier_orchestrator import TierOrchestrator
from src.monitoring.alerting import AlertManager
from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.health_checker import HealthChecker
from src.monitoring.event_bus import EventBus
from src.monitoring.dashboard import MonitoringDashboard
from src.learning.pattern_engine import PatternRecognitionEngine
from src.learning.trend_analyzer import TrendAnalyzer
from src.learning.feedback_learner import FeedbackLearner
from src.memory.rule_cache import RuleCache
from src.memory.context_memory import ContextMemory
from src.privacy.data_redaction import DataRedactor
from src.privacy.consent_manager import ConsentManager
from src.privacy.anonymizer import Anonymizer
from src.compliance.compliance_orchestrator import ComplianceOrchestrator
from src.advanced.emergency_response import EmergencyResponse
from src.advanced.sandbox import CodeSandbox
from src.skills.skill_registry import SkillRegistry
from src.skills.skill_executor import SkillExecutor
from src.storage.rule_storage import RuleStorage
from src.storage.backup_manager import BackupManager
from src.tools.rule_analyzer import RuleAnalyzer
from src.tools.visualizer import Visualizer
from src.tools.profiler import Profiler
from src.models.rule import Rule, RuleTier, RuleEvaluationRequest
from src.models.validation import ValidationResult, BatchValidationRequest
from src.models.monitoring import AlertDefinition, AlertEvent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
rule_engine: Optional[RuleEngine] = None
tier_orchestrator: Optional[TierOrchestrator] = None
alert_manager: Optional[AlertManager] = None
metrics_collector: Optional[MetricsCollector] = None
health_checker: Optional[HealthChecker] = None
event_bus: Optional[EventBus] = None
monitoring_dashboard: Optional[MonitoringDashboard] = None
pattern_engine: Optional[PatternRecognitionEngine] = None
trend_analyzer: Optional[TrendAnalyzer] = None
feedback_learner: Optional[FeedbackLearner] = None
rule_cache: Optional[RuleCache] = None
context_memory: Optional[ContextMemory] = None
data_redactor: Optional[DataRedactor] = None
consent_manager: Optional[ConsentManager] = None
anonymizer: Optional[Anonymizer] = None
compliance_orchestrator: Optional[ComplianceOrchestrator] = None
emergency_response: Optional[EmergencyResponse] = None
code_sandbox: Optional[CodeSandbox] = None
skill_registry: Optional[SkillRegistry] = None
skill_executor: Optional[SkillExecutor] = None
rule_storage: Optional[RuleStorage] = None
backup_manager: Optional[BackupManager] = None
rule_analyzer: Optional[RuleAnalyzer] = None
visualizer: Optional[Visualizer] = None
profiler: Optional[Profiler] = None

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class HealthCheck(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str
    components: Dict[str, str] = Field(default_factory=dict)

class ValidationRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)
    tier: Optional[str] = None
    rule_ids: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None
    options: Optional[Dict[str, Any]] = None

class TieredEvaluateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)
    tiers: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None

class AlertCreateRequest(BaseModel):
    name: str
    metric_name: str
    threshold_value: float
    comparison_operator: str = "greater_than"
    severity: str = "warning"
    description: Optional[str] = None

class AlertResolveRequest(BaseModel):
    resolution_notes: Optional[str] = None

class EventPublishRequest(BaseModel):
    event_type: str
    source: str = "api"
    payload: Dict[str, Any] = Field(default_factory=dict)

class PatternAnalyzeRequest(BaseModel):
    content: str
    pattern_types: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None

class TrendAnalyzeRequest(BaseModel):
    metric_names: List[str]
    time_range_days: int = 30
    aggregation: str = "daily"

class FeedbackSubmitRequest(BaseModel):
    content: str
    rating: int = Field(default=3, ge=1, le=5)
    was_accurate: bool = True
    was_helpful: bool = True
    comments: Optional[str] = None

class RedactRequest(BaseModel):
    content: str
    rules: Optional[List[str]] = None
    preserve_format: bool = True

class AnonymizeRequest(BaseModel):
    content: str
    level: str = "standard"
    fields: Optional[List[str]] = None

class ClassifyRequest(BaseModel):
    content: str
    categories: Optional[List[str]] = None

class ConsentCheckRequest(BaseModel):
    user_id: str
    purpose: str
    data_categories: List[str]

class ComplianceCheckRequest(BaseModel):
    content: str
    frameworks: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None

class AgeVerifyRequest(BaseModel):
    user_id: str
    date_of_birth: str
    verification_method: str = "direct"

class EmergencyRequest(BaseModel):
    incident_type: str
    severity: str = "high"
    details: Dict[str, Any] = Field(default_factory=dict)

class IntentRequest(BaseModel):
    content: str
    context: Optional[Dict[str, Any]] = None

class SandboxExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout_ms: int = 5000
    inputs: Dict[str, Any] = Field(default_factory=dict)

class SkillExecuteRequest(BaseModel):
    skill_id: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None

class SkillValidateRequest(BaseModel):
    skill_id: str
    content: str

class StoreRulesRequest(BaseModel):
    rules: List[Dict[str, Any]]
    namespace: str = "default"

class AnalyzeRequest(BaseModel):
    rule_ids: List[str]
    analysis_type: str = "comprehensive"

class VisualizeRequest(BaseModel):
    rule_ids: List[str]
    format: str = "json"
    include_metrics: bool = True

class ProfileRequest(BaseModel):
    target: str = "engine"
    duration_seconds: int = 10
    detail_level: str = "standard"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global rule_engine, tier_orchestrator, alert_manager, metrics_collector
    global health_checker, event_bus, monitoring_dashboard, pattern_engine
    global trend_analyzer, feedback_learner, rule_cache, context_memory
    global data_redactor, consent_manager, anonymizer, compliance_orchestrator
    global emergency_response, code_sandbox, skill_registry, skill_executor
    global rule_storage, backup_manager, rule_analyzer, visualizer, profiler

    logger.info("Starting up Rules Engine API...")

    rule_engine = RuleEngine()
    tier_orchestrator = TierOrchestrator(rule_engine)
    alert_manager = AlertManager()
    metrics_collector = MetricsCollector()
    health_checker = HealthChecker()
    event_bus = EventBus()
    monitoring_dashboard = MonitoringDashboard()
    pattern_engine = PatternRecognitionEngine()
    trend_analyzer = TrendAnalyzer()
    feedback_learner = FeedbackLearner()
    rule_cache = RuleCache()
    context_memory = ContextMemory()
    data_redactor = DataRedactor()
    consent_manager = ConsentManager()
    anonymizer = Anonymizer()
    compliance_orchestrator = ComplianceOrchestrator()
    emergency_response = EmergencyResponse()
    code_sandbox = CodeSandbox()
    skill_registry = SkillRegistry()
    skill_executor = SkillExecutor(skill_registry)
    rule_storage = RuleStorage()
    backup_manager = BackupManager(rule_storage)
    rule_analyzer = RuleAnalyzer()
    visualizer = Visualizer()
    profiler = Profiler()

    logger.info("Rules Engine API started successfully")
    yield
    logger.info("Shutting down Rules Engine API...")
    if rule_engine:
        await rule_engine.shutdown()
    logger.info("Rules Engine API shut down successfully")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Rules-Emerging-Pattern API",
    description="AI Guardrails and Consistency Framework - Production API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthCheck)
async def health_check():
    components = {
        "rule_engine": "healthy" if rule_engine else "unhealthy",
        "tier_orchestrator": "healthy" if tier_orchestrator else "unhealthy",
        "alert_manager": "healthy" if alert_manager else "unhealthy",
        "metrics_collector": "healthy" if metrics_collector else "unhealthy",
        "health_checker": "healthy" if health_checker else "unhealthy",
        "event_bus": "healthy" if event_bus else "unhealthy",
        "monitoring_dashboard": "healthy" if monitoring_dashboard else "unhealthy",
        "pattern_engine": "healthy" if pattern_engine else "unhealthy",
        "trend_analyzer": "healthy" if trend_analyzer else "unhealthy",
        "feedback_learner": "healthy" if feedback_learner else "unhealthy",
        "rule_cache": "healthy" if rule_cache else "unhealthy",
        "context_memory": "healthy" if context_memory else "unhealthy",
        "data_redactor": "healthy" if data_redactor else "unhealthy",
        "consent_manager": "healthy" if consent_manager else "unhealthy",
        "anonymizer": "healthy" if anonymizer else "unhealthy",
        "compliance_orchestrator": "healthy" if compliance_orchestrator else "unhealthy",
        "emergency_response": "healthy" if emergency_response else "unhealthy",
        "code_sandbox": "healthy" if code_sandbox else "unhealthy",
        "skill_registry": "healthy" if skill_registry else "unhealthy",
        "skill_executor": "healthy" if skill_executor else "unhealthy",
        "rule_storage": "healthy" if rule_storage else "unhealthy",
        "backup_manager": "healthy" if backup_manager else "unhealthy",
        "rule_analyzer": "healthy" if rule_analyzer else "unhealthy",
        "visualizer": "healthy" if visualizer else "unhealthy",
        "profiler": "healthy" if profiler else "unhealthy",
    }
    return HealthCheck(status="healthy", version="1.0.0", timestamp=datetime.utcnow().isoformat(), components=components)

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
@app.post("/api/v1/validate", response_model=ValidationResult)
async def validate_content(request: ValidationRequest):
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    try:
        tier = None
        if request.tier:
            try:
                tier = RuleTier(request.tier)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid tier: {request.tier}")
        eval_request = RuleEvaluationRequest(
            content=request.content,
            context=request.context,
            rule_ids=request.rule_ids,
            tier=tier,
            options=request.options or {}
        )
        result = await rule_engine.evaluate(eval_request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@app.get("/api/v1/rules")
async def get_rules(tier: Optional[str] = None, active_only: bool = True):
    if not rule_engine or not rule_engine.rule_manager:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    try:
        if tier:
            try:
                tier_enum = RuleTier(tier)
                rules = rule_engine.rule_manager.get_rules_by_tier(tier_enum)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
        else:
            rules = rule_engine.rule_manager.get_all_rules()
        if active_only:
            from src.models.rule import RuleStatus
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
        return {"rules": [r.dict() for r in rules], "total": len(rules)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@app.get("/api/v1/metrics")
async def get_metrics():
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    try:
        stats = rule_engine.get_statistics()
        return {"metrics": stats}
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Tiered Rules /api/v1/tiered
# ---------------------------------------------------------------------------
@app.post("/api/v1/tiered/evaluate")
async def tiered_evaluate(request: TieredEvaluateRequest):
    if not tier_orchestrator:
        raise HTTPException(status_code=503, detail="Tier orchestrator not initialized")
    try:
        tiers = None
        if request.tiers:
            tiers = [RuleTier(t) for t in request.tiers]
        result = await tier_orchestrator.evaluate(request.content, tiers=tiers, context=request.context)
        return {"result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tiered evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tiered/{tier}/rules")
async def get_tier_rules(tier: str):
    if not rule_engine or not rule_engine.rule_manager:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    try:
        tier_enum = RuleTier(tier)
        rules = rule_engine.rule_manager.get_rules_by_tier(tier_enum)
        return {"tier": tier, "rules": [r.dict() for r in rules], "total": len(rules)}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
    except Exception as e:
        logger.error(f"Failed to get tier rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tiered/metrics")
async def get_tier_metrics():
    if not tier_orchestrator:
        raise HTTPException(status_code=503, detail="Tier orchestrator not initialized")
    try:
        metrics = tier_orchestrator.get_metrics()
        return {"tier_metrics": metrics}
    except Exception as e:
        logger.error(f"Failed to get tier metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Monitoring /api/v1/alerts
# ---------------------------------------------------------------------------
@app.post("/api/v1/alerts", status_code=201)
async def create_alert(request: AlertCreateRequest):
    if not alert_manager:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")
    try:
        alert_def = AlertDefinition(
            alert_id=str(uuid.uuid4()),
            name=request.name,
            metric_name=request.metric_name,
            threshold_value=request.threshold_value,
            comparison_operator=request.comparison_operator,
            severity=request.severity,
            description=request.description
        )
        await alert_manager.register_alert(alert_def)
        return {"alert_id": alert_def.alert_id, "status": "created"}
    except Exception as e:
        logger.error(f"Failed to create alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/alerts")
async def list_alerts(status: Optional[str] = None, limit: int = Query(default=50, le=500)):
    if not alert_manager:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")
    try:
        alerts = await alert_manager.list_alerts(status=status)
        return {"alerts": alerts[:limit], "total": len(alerts)}
    except Exception as e:
        logger.error(f"Failed to list alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, request: AlertResolveRequest):
    if not alert_manager:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")
    try:
        await alert_manager.resolve_alert(alert_id, notes=request.resolution_notes)
        return {"alert_id": alert_id, "status": "resolved"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to resolve alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Dashboard /api/v1/dashboard
# ---------------------------------------------------------------------------
@app.get("/api/v1/dashboard")
async def get_dashboard():
    if not monitoring_dashboard:
        raise HTTPException(status_code=503, detail="Dashboard not initialized")
    try:
        data = await monitoring_dashboard.get_snapshot()
        return {"dashboard": data}
    except Exception as e:
        logger.error(f"Failed to get dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Events /api/v1/events
# ---------------------------------------------------------------------------
@app.post("/api/v1/events", status_code=201)
async def publish_event(request: EventPublishRequest):
    if not event_bus:
        raise HTTPException(status_code=503, detail="Event bus not initialized")
    try:
        await event_bus.publish(request.event_type, request.payload, source=request.source)
        return {"status": "published", "event_type": request.event_type}
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/v1/events")
async def events_websocket(websocket: WebSocket):
    if not event_bus:
        await websocket.close(code=1011, reason="Event bus not initialized")
        return
    await websocket.accept()
    try:
        async for event in event_bus.subscribe():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from event bus")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

# ---------------------------------------------------------------------------
# Learning /api/v1/patterns
# ---------------------------------------------------------------------------
@app.post("/api/v1/patterns/analyze")
async def analyze_patterns(request: PatternAnalyzeRequest):
    if not pattern_engine:
        raise HTTPException(status_code=503, detail="Pattern engine not initialized")
    try:
        result = await pattern_engine.analyze(request.content, pattern_types=request.pattern_types, context=request.context)
        return {"patterns": result}
    except Exception as e:
        logger.error(f"Pattern analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/trends/analyze")
async def analyze_trends(request: TrendAnalyzeRequest):
    if not trend_analyzer:
        raise HTTPException(status_code=503, detail="Trend analyzer not initialized")
    try:
        result = await trend_analyzer.analyze(
            metric_names=request.metric_names,
            time_range_days=request.time_range_days,
            aggregation=request.aggregation
        )
        return {"trends": result}
    except Exception as e:
        logger.error(f"Trend analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/feedback")
async def submit_feedback(request: FeedbackSubmitRequest):
    if not feedback_learner:
        raise HTTPException(status_code=503, detail="Feedback learner not initialized")
    try:
        result = await feedback_learner.process_feedback(
            content=request.content,
            rating=request.rating,
            was_accurate=request.was_accurate,
            was_helpful=request.was_helpful,
            comments=request.comments
        )
        return {"feedback_id": result, "status": "recorded"}
    except Exception as e:
        logger.error(f"Feedback submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/models")
async def get_models():
    # Placeholder for model listing
    return {"models": [], "message": "Model management endpoint"}

# ---------------------------------------------------------------------------
# Privacy /api/v1/privacy
# ---------------------------------------------------------------------------
@app.post("/api/v1/privacy/redact")
async def redact_data(request: RedactRequest):
    if not data_redactor:
        raise HTTPException(status_code=503, detail="Data redactor not initialized")
    try:
        result = await data_redactor.redact(
            content=request.content,
            rules=request.rules,
            preserve_format=request.preserve_format
        )
        return {"redacted_content": result}
    except Exception as e:
        logger.error(f"Redaction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/privacy/anonymize")
async def anonymize_data(request: AnonymizeRequest):
    if not anonymizer:
        raise HTTPException(status_code=503, detail="Anonymizer not initialized")
    try:
        result = await anonymizer.anonymize(
            content=request.content,
            level=request.level,
            fields=request.fields
        )
        return {"anonymized_content": result}
    except Exception as e:
        logger.error(f"Anonymization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/privacy/classify")
async def classify_data(request: ClassifyRequest):
    if not data_redactor:
        raise HTTPException(status_code=503, detail="Data classifier not initialized")
    try:
        from src.privacy.data_classifier import DataClassifier
        classifier = DataClassifier()
        result = await classifier.classify(
            content=request.content,
            categories=request.categories
        )
        return {"classification": result}
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/privacy/consent/check")
async def check_consent(request: ConsentCheckRequest):
    if not consent_manager:
        raise HTTPException(status_code=503, detail="Consent manager not initialized")
    try:
        result = await consent_manager.check_consent(
            user_id=request.user_id,
            purpose=request.purpose,
            data_categories=request.data_categories
        )
        return {"consent_granted": result}
    except Exception as e:
        logger.error(f"Consent check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/privacy/audit")
async def get_privacy_audit(user_id: Optional[str] = None, limit: int = Query(default=50, le=500)):
    if not consent_manager:
        raise HTTPException(status_code=503, detail="Privacy auditor not initialized")
    try:
        from src.privacy.privacy_auditor import PrivacyAuditor
        auditor = PrivacyAuditor()
        logs = await auditor.get_audit_log(user_id=user_id)
        return {"audit_log": logs[:limit], "total": len(logs)}
    except Exception as e:
        logger.error(f"Privacy audit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Compliance /api/v1/compliance
# ---------------------------------------------------------------------------
@app.post("/api/v1/compliance/check")
async def check_compliance(request: ComplianceCheckRequest):
    if not compliance_orchestrator:
        raise HTTPException(status_code=503, detail="Compliance orchestrator not initialized")
    try:
        result = await compliance_orchestrator.check(
            content=request.content,
            frameworks=request.frameworks,
            context=request.context
        )
        return {"compliance_result": result}
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/compliance/gdpr")
async def check_gdpr(request: ComplianceCheckRequest):
    if not compliance_orchestrator:
        raise HTTPException(status_code=503, detail="Compliance orchestrator not initialized")
    try:
        from src.compliance.gdpr_compliance import GDPRComplianceChecker
        checker = GDPRComplianceChecker()
        result = await checker.check(request.content, context=request.context)
        return {"gdpr_result": result}
    except Exception as e:
        logger.error(f"GDPR check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/compliance/hipaa")
async def check_hipaa(request: ComplianceCheckRequest):
    if not compliance_orchestrator:
        raise HTTPException(status_code=503, detail="Compliance orchestrator not initialized")
    try:
        from src.compliance.hipaa_compliance import HIPAAComplianceChecker
        checker = HIPAAComplianceChecker()
        result = await checker.check(request.content, context=request.context)
        return {"hipaa_result": result}
    except Exception as e:
        logger.error(f"HIPAA check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/compliance/pci")
async def check_pci(request: ComplianceCheckRequest):
    if not compliance_orchestrator:
        raise HTTPException(status_code=503, detail="Compliance orchestrator not initialized")
    try:
        from src.compliance.pci_compliance import PCIComplianceChecker
        checker = PCIComplianceChecker()
        result = await checker.check(request.content, context=request.context)
        return {"pci_result": result}
    except Exception as e:
        logger.error(f"PCI check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/compliance/sox")
async def check_sox(request: ComplianceCheckRequest):
    if not compliance_orchestrator:
        raise HTTPException(status_code=503, detail="Compliance orchestrator not initialized")
    try:
        from src.compliance.sox_compliance import SOXComplianceChecker
        checker = SOXComplianceChecker()
        result = await checker.check(request.content, context=request.context)
        return {"sox_result": result}
    except Exception as e:
        logger.error(f"SOX check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Advanced /api/v1/advanced
# ---------------------------------------------------------------------------
@app.post("/api/v1/advanced/age-verify")
async def age_verify(request: AgeVerifyRequest):
    try:
        from src.advanced.age_verification import AgeVerifier
        verifier = AgeVerifier()
        result = await verifier.verify(
            user_id=request.user_id,
            date_of_birth=request.date_of_birth,
            method=request.verification_method
        )
        return {"age_verification": result}
    except Exception as e:
        logger.error(f"Age verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/advanced/emergency")
async def trigger_emergency(request: EmergencyRequest):
    if not emergency_response:
        raise HTTPException(status_code=503, detail="Emergency response not initialized")
    try:
        result = await emergency_response.trigger(
            incident_type=request.incident_type,
            severity=request.severity,
            details=request.details
        )
        return {"emergency_response": result}
    except Exception as e:
        logger.error(f"Emergency response failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/advanced/intent")
async def analyze_intent(request: IntentRequest):
    try:
        from src.advanced.intent_recognition import IntentAnalyzer
        analyzer = IntentAnalyzer()
        result = await analyzer.analyze(request.content, context=request.context)
        return {"intent": result}
    except Exception as e:
        logger.error(f"Intent analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/advanced/sandbox/execute")
async def sandbox_execute(request: SandboxExecuteRequest):
    if not code_sandbox:
        raise HTTPException(status_code=503, detail="Code sandbox not initialized")
    try:
        result = await code_sandbox.execute(
            code=request.code,
            language=request.language,
            timeout_ms=request.timeout_ms,
            inputs=request.inputs
        )
        return {"sandbox_result": result}
    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Skills /api/v1/skills
# ---------------------------------------------------------------------------
@app.post("/api/v1/skills/execute")
async def execute_skill(request: SkillExecuteRequest):
    if not skill_executor:
        raise HTTPException(status_code=503, detail="Skill executor not initialized")
    try:
        result = await skill_executor.execute(
            skill_id=request.skill_id,
            input_data=request.input_data,
            context=request.context
        )
        return {"skill_result": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Skill execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/skills")
async def list_skills():
    if not skill_registry:
        raise HTTPException(status_code=503, detail="Skill registry not initialized")
    try:
        skills = await skill_registry.list_skills()
        return {"skills": skills, "total": len(skills)}
    except Exception as e:
        logger.error(f"Failed to list skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/skills/validate")
async def validate_skill(request: SkillValidateRequest):
    if not skill_registry:
        raise HTTPException(status_code=503, detail="Skill registry not initialized")
    try:
        from src.skills.skill_validator import SkillValidator
        validator = SkillValidator(skill_registry)
        result = await validator.validate(skill_id=request.skill_id, content=request.content)
        return {"valid": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Skill validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Storage /api/v1/storage
# ---------------------------------------------------------------------------
@app.post("/api/v1/storage/rules", status_code=201)
async def store_rules(request: StoreRulesRequest):
    if not rule_storage:
        raise HTTPException(status_code=503, detail="Rule storage not initialized")
    try:
        stored = []
        for rule_data in request.rules:
            rule = Rule(**rule_data)
            await rule_storage.store(rule, namespace=request.namespace)
            stored.append(rule.id)
        return {"stored_ids": stored, "count": len(stored)}
    except Exception as e:
        logger.error(f"Failed to store rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/storage/rules/{rule_id}")
async def get_stored_rule(rule_id: str):
    if not rule_storage:
        raise HTTPException(status_code=503, detail="Rule storage not initialized")
    try:
        rule = await rule_storage.get(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        return {"rule": rule.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/storage/backup")
async def trigger_backup():
    if not backup_manager:
        raise HTTPException(status_code=503, detail="Backup manager not initialized")
    try:
        backup_id = await backup_manager.create_backup()
        return {"backup_id": backup_id, "status": "started"}
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/storage/migrate")
async def trigger_migration():
    if not rule_storage:
        raise HTTPException(status_code=503, detail="Rule storage not initialized")
    try:
        from src.storage.migration_manager import MigrationManager
        migrator = MigrationManager(rule_storage)
        result = await migrator.migrate()
        return {"migration": result}
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Tools /api/v1/tools
# ---------------------------------------------------------------------------
@app.post("/api/v1/tools/analyze")
async def analyze_rules(request: AnalyzeRequest):
    if not rule_analyzer:
        raise HTTPException(status_code=503, detail="Rule analyzer not initialized")
    try:
        result = await rule_analyzer.analyze(
            rule_ids=request.rule_ids,
            analysis_type=request.analysis_type
        )
        return {"analysis": result}
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tools/visualize")
async def visualize_rules(request: VisualizeRequest):
    if not visualizer:
        raise HTTPException(status_code=503, detail="Visualizer not initialized")
    try:
        result = await visualizer.visualize(
            rule_ids=request.rule_ids,
            format=request.format,
            include_metrics=request.include_metrics
        )
        return {"visualization": result}
    except Exception as e:
        logger.error(f"Visualization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tools/profile")
async def profile_system(request: ProfileRequest):
    if not profiler:
        raise HTTPException(status_code=503, detail="Profiler not initialized")
    try:
        result = await profiler.profile(
            target=request.target,
            duration_seconds=request.duration_seconds,
            detail_level=request.detail_level
        )
        return {"profile": result}
    except Exception as e:
        logger.error(f"Profiling failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    run_server()