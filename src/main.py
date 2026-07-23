"""Main FastAPI application for Rules-Emerging-Pattern."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.rule_engines.base.rule_manager import RuleManager
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleEvaluationRequest
from rules_emerging_pattern.models.validation import ValidationResult, BatchValidationRequest, BatchValidationResult

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

rule_manager: Optional[RuleManager] = None
rule_engine: Optional[RuleEngine] = None


class HealthCheck(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str
    components: dict = Field(default_factory=dict)


class ValidationRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)
    tier: Optional[str] = None
    rule_ids: Optional[list] = None
    context: Optional[dict] = None
    options: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rule_manager, rule_engine
    logger.info("Starting up Rules Engine API...")
    rule_manager = RuleManager()
    rule_engine = RuleEngine(rule_manager=rule_manager)
    await rule_manager.load_predefined_rules()
    logger.info("Rules Engine API started successfully")
    yield
    logger.info("Shutting down Rules Engine API...")
    if rule_engine:
        await rule_engine.shutdown()
    logger.info("Rules Engine API shut down successfully")


app = FastAPI(
    title="Rules-Emerging-Pattern API",
    description="AI Guardrails and Consistency Framework",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", response_model=HealthCheck)
async def health_check():
    components = {
        "rule_engine": "healthy" if rule_engine else "unhealthy",
        "rule_manager": "healthy" if rule_manager else "unhealthy",
    }
    return HealthCheck(status="healthy", version="1.0.0", timestamp=datetime.utcnow().isoformat(), components=components)


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
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rules")
async def get_rules(tier: Optional[str] = None, active_only: bool = True):
    if not rule_manager:
        raise HTTPException(status_code=503, detail="Rule manager not initialized")
    try:
        if tier:
            try:
                tier_enum = RuleTier(tier)
                rules = rule_manager.get_rules_by_tier(tier_enum)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
        else:
            rules = rule_manager.get_all_rules()
        if active_only:
            from rules_emerging_pattern.models.rule import RuleStatus
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
        return {"rules": [r.dict() for r in rules], "total": len(rules)}
    except Exception as e:
        logger.error(f"Failed to get rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


def run_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run_server()
