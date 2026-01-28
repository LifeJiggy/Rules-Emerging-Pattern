"""
Main rule engine for the Rules-Emerging-Pattern system.
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Union, Set
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleContext, RuleEvaluationRequest
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken, Suggestion
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType, ConflictResolution, ResolutionStrategy

logger = logging.getLogger(__name__)


class RuleEngine:
    """Main rule engine with tiered architecture and comprehensive evaluation."""
    
    def __init__(self, rule_manager=None):
        self.rule_manager = rule_manager
        self.evaluation_stats = {
            'total_evaluations': 0,
            'successful_evaluations': 0,
            'failed_evaluations': 0,
            'average_time_ms': 0.0,
            'violations_detected': 0,
            'blocks_applied': 0
        }
        
        # Performance optimization
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.evaluation_cache = {}
        self.cache_ttl = 300  # 5 minutes
        
        # Tier-specific engines
        self.tier_engines = {}
        self._initialize_tier_engines()
        
        logger.info("RuleEngine initialized")
    
    def _initialize_tier_engines(self) -> None:
        """Initialize tier-specific rule engines."""
        from .tiered_rules.safety_engine import SafetyRuleEngine
        from .tiered_rules.operational_engine import OperationalRuleEngine
        from .tiered_rules.preference_engine import PreferenceRuleEngine
        
        self.tier_engines[RuleTier.SAFETY] = SafetyRuleEngine()
        self.tier_engines[RuleTier.OPERATIONAL] = OperationalRuleEngine()
        self.tier_engines[RuleTier.PREFERENCE] = PreferenceRuleEngine()
    
    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        """Evaluate content against rules."""
        start_time = time.time()
        
        try:
            # Get content hash for caching
            content_hash = self._get_content_hash(request.content)
            
            # Check cache
            cached_result = self._get_cached_result(content_hash, request.context)
            if cached_result:
                logger.debug(f"Cache hit for content hash: {content_hash}")
                return cached_result
            
            # Get applicable rules
            applicable_rules = self._get_applicable_rules(request)
            
            if not applicable_rules:
                return self._create_empty_result(request, start_time)
            
            # Evaluate rules by tier (safety first)
            result = await self._evaluate_by_tiers(request, applicable_rules)
            
            # Update statistics
            self._update_statistics(result, start_time)
            
            # Cache result
            self._cache_result(content_hash, request.context, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Rule evaluation failed: {e}")
            self.evaluation_stats['failed_evaluations'] += 1
            return self._create_error_result(request, str(e), start_time)
    
    async def evaluate_batch(self, requests: List[RuleEvaluationRequest]) -> List[ValidationResult]:
        """Evaluate multiple requests in batch."""
        if not requests:
            return []
        
        # Process in parallel with controlled concurrency
        semaphore = asyncio.Semaphore(10)  # Limit concurrent evaluations
        
        async def evaluate_single(request):
            async with semaphore:
                return await self.evaluate(request)
        
        # Run all evaluations
        results = await asyncio.gather(
            *[evaluate_single(req) for req in requests],
            return_exceptions=True
        )
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Batch evaluation failed for request {i}: {result}")
                processed_results.append(self._create_error_result(
                    requests[i], str(result), time.time()
                ))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def evaluate_tiered(self, request: RuleEvaluationRequest) -> ValidationResult:
        """Evaluate content with explicit tier handling."""
        start_time = time.time()
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content)
        )
        
        # Evaluate tiers in order (safety -> operational -> preference)
        for tier in [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]:
            if request.tier and request.tier != tier:
                continue
            
            tier_engine = self.tier_engines.get(tier)
            if not tier_engine:
                continue
            
            try:
                tier_result = await tier_engine.evaluate(request)
                self._merge_tier_result(result, tier_result)
                
                # Early termination for critical safety violations
                if tier == RuleTier.SAFETY and result.is_blocked():
                    logger.info("Early termination due to safety violation")
                    break
                    
            except Exception as e:
                logger.error(f"Tier {tier} evaluation failed: {e}")
                # Continue with other tiers
        
        # Finalize result
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        result.evaluated_at = datetime.utcnow()
        
        return result
    
    def _get_applicable_rules(self, request: RuleEvaluationRequest) -> List[Rule]:
        """Get rules applicable to the request."""
        if not self.rule_manager:
            return []
        
        # Filter by specific rule IDs if provided
        if request.rule_ids:
            rules = []
            for rule_id in request.rule_ids:
                rule = self.rule_manager.get_rule(rule_id)
                if rule and rule.status.value == "active":
                    rules.append(rule)
            return rules
        
        # Filter by tier if specified
        if request.tier:
            return self.rule_manager.get_rules_by_tier(request.tier)
        
        # Filter by rule types if specified
        if request.rule_types:
            rules = []
            for rule_type in request.rule_types:
                rules.extend(self.rule_manager.get_rules_by_type(rule_type))
            return rules
        
        # Get all applicable rules
        context = request.get_context()
        return self.rule_manager.get_applicable_rules(context)
    
    async def _evaluate_by_tiers(self, request: RuleEvaluationRequest, rules: List[Rule]) -> ValidationResult:
        """Evaluate rules by tier with proper priority handling."""
        start_time = time.time()
        
        # Group rules by tier
        rules_by_tier = {}
        for rule in rules:
            if rule.tier not in rules_by_tier:
                rules_by_tier[rule.tier] = []
            rules_by_tier[rule.tier].append(rule)
        
        # Create result
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content)
        )
        
        # Evaluate tiers in priority order
        tier_order = [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]
        
        for tier in tier_order:
            if tier not in rules_by_tier:
                continue
            
            tier_rules = rules_by_tier[tier]
            tier_engine = self.tier_engines.get(tier)
            
            if tier_engine:
                # Use tier-specific engine
                tier_request = RuleEvaluationRequest(
                    content=request.content,
                    context=request.context,
                    rule_ids=[rule.id for rule in tier_rules],
                    options=request.options
                )
                
                try:
                    tier_result = await tier_engine.evaluate(tier_request)
                    self._merge_tier_result(result, tier_result)
                    
                    # Early termination for critical violations
                    if tier == RuleTier.SAFETY and result.is_blocked():
                        logger.info("Early termination due to safety violation")
                        break
                        
                except Exception as e:
                    logger.error(f"Tier {tier} engine failed: {e}")
                    # Fall back to direct evaluation
                    await self._evaluate_rules_directly(result, tier_rules, request)
            else:
                # Direct evaluation
                await self._evaluate_rules_directly(result, tier_rules, request)
        
        # Finalize result
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        result.evaluated_at = datetime.utcnow()
        result.total_rules_evaluated = len(rules)
        result.rules_triggered = len(result.violations)
        result.rules_violated = len([v for v in result.violations if v.action_taken != ActionTaken.NONE])
        
        return result
    
    async def _evaluate_rules_directly(self, result: ValidationResult, rules: List[Rule], request: RuleEvaluationRequest) -> None:
        """Evaluate rules directly without tier engine."""
        for rule in rules:
            try:
                violation = await self._evaluate_single_rule(rule, request.content, request.context)
                if violation:
                    result.violations.append(violation)
                    
                    if violation.is_critical():
                        result.critical_violations.append(violation)
                    
                    if violation.action_taken == ActionTaken.WARNING:
                        result.warnings.append(violation)
                    
                    # Update validity
                    if violation.blocked:
                        result.valid = False
                    
            except Exception as e:
                logger.error(f"Rule {rule.id} evaluation failed: {e}")
    
    async def _evaluate_single_rule(self, rule: Rule, content: str, context: Optional[RuleContext]) -> Optional[Violation]:
        """Evaluate a single rule against content."""
        # Check rule applicability
        if context and not rule.is_applicable_to_context(context.get_effective_context()):
            return None
        
        # Evaluate patterns
        for pattern in rule.patterns:
            # This would use the pattern parser in a real implementation
            # For now, simplified keyword matching
            if pattern.keywords:
                content_lower = content.lower()
                for keyword in pattern.keywords:
                    if keyword.lower() in content_lower:
                        return Violation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            rule_tier=rule.tier,
                            rule_severity=rule.severity,
                            violation_type=ViolationType.KEYWORD_MATCH,
                            matched_content=keyword,
                            matched_patterns=[keyword],
                            confidence_score=0.8,
                            action_taken=self._get_action_for_rule(rule),
                            blocked=rule.auto_block,
                            user_override_allowed=rule.user_override,
                            explanation=f"Content contains prohibited keyword: {keyword}",
                            context=context.get_effective_context() if context else {}
                        )
        
        return None
    
    def _get_action_for_rule(self, rule: Rule) -> ActionTaken:
        """Get the action to take for a rule violation."""
        if rule.enforcement_level.value == "strict":
            return ActionTaken.BLOCK
        elif rule.enforcement_level.value == "advisory":
            return ActionTaken.WARNING
        elif rule.enforcement_level.value == "adaptive":
            return ActionTaken.SUGGESTION
        else:
            return ActionTaken.NONE
    
    def _merge_tier_result(self, main_result: ValidationResult, tier_result: ValidationResult) -> None:
        """Merge tier evaluation result into main result."""
        # Merge violations
        main_result.violations.extend(tier_result.violations)
        main_result.critical_violations.extend(tier_result.critical_violations)
        main_result.warnings.extend(tier_result.warnings)
        
        # Merge suggestions
        main_result.suggestions.extend(tier_result.suggestions)
        
        # Update validity (if any tier says invalid, it's invalid)
        if not tier_result.valid:
            main_result.valid = False
        
        # Update score (use minimum score)
        main_result.total_score = min(main_result.total_score, tier_result.total_score)
        
        # Update confidence (use weighted average)
        main_result.confidence = (main_result.confidence + tier_result.confidence) / 2
    
    def _get_content_hash(self, content: str) -> str:
        """Generate hash for content caching."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _get_cached_result(self, content_hash: str, context: Optional[RuleContext]) -> Optional[ValidationResult]:
        """Get cached result if available and valid."""
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        
        if cache_key in self.evaluation_cache:
            cached_item = self.evaluation_cache[cache_key]
            timestamp = cached_item['timestamp']
            
            # Check if cache is still valid
            if (datetime.utcnow() - timestamp).total_seconds() < self.cache_ttl:
                return cached_item['result']
            else:
                # Remove expired cache entry
                del self.evaluation_cache[cache_key]
        
        return None
    
    def _cache_result(self, content_hash: str, context: Optional[RuleContext], result: ValidationResult) -> None:
        """Cache evaluation result."""
        cache_key = f"{content_hash}:{hash(str(context)) if context else 'no_context'}"
        
        self.evaluation_cache[cache_key] = {
            'result': result,
            'timestamp': datetime.utcnow()
        }
        
        # Limit cache size
        if len(self.evaluation_cache) > 1000:
            # Remove oldest entries
            oldest_keys = sorted(
                self.evaluation_cache.keys(),
                key=lambda k: self.evaluation_cache[k]['timestamp']
            )[:100]
            
            for key in oldest_keys:
                del self.evaluation_cache[key]
    
    def _create_empty_result(self, request: RuleEvaluationRequest, start_time: float) -> ValidationResult:
        """Create empty result for no applicable rules."""
        return ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            processing_time_ms=int((time.time() - start_time) * 1000),
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
            evaluated_at=datetime.utcnow()
        )
    
    def _create_error_result(self, request: RuleEvaluationRequest, error: str, start_time: float) -> ValidationResult:
        """Create error result."""
        return ValidationResult(
            valid=False,
            total_score=0.0,
            confidence=0.0,
            processing_time_ms=int((time.time() - start_time) * 1000),
            request_id=self._generate_request_id(),
            content_hash=self._get_content_hash(request.content),
            evaluated_at=datetime.utcnow(),
            violations=[Violation(
                rule_id="system_error",
                rule_name="System Error",
                rule_tier=RuleTier.SAFETY,
                rule_severity=RuleSeverity.CRITICAL,
                violation_type=ViolationType.CUSTOM_VIOLATION,
                confidence_score=1.0,
                action_taken=ActionTaken.BLOCK,
                blocked=True,
                user_override_allowed=False,
                explanation=f"Evaluation failed: {error}",
                context={}
            )]
        )
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID."""
        return f"req_{int(time.time() * 1000)}_{hash(str(time.time())) % 10000}"
    
    def _update_statistics(self, result: ValidationResult, start_time: float) -> None:
        """Update evaluation statistics."""
        self.evaluation_stats['total_evaluations'] += 1
        
        if result.valid:
            self.evaluation_stats['successful_evaluations'] += 1
        else:
            self.evaluation_stats['failed_evaluations'] += 1
        
        # Update average time
        processing_time = (time.time() - start_time) * 1000
        total_evaluations = self.evaluation_stats['total_evaluations']
        current_avg = self.evaluation_stats['average_time_ms']
        self.evaluation_stats['average_time_ms'] = (
            (current_avg * (total_evaluations - 1) + processing_time) / total_evaluations
        )
        
        # Update violation stats
        if result.has_violations():
            self.evaluation_stats['violations_detected'] += len(result.violations)
        
        if result.is_blocked():
            self.evaluation_stats['blocks_applied'] += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get evaluation statistics."""
        return self.evaluation_stats.copy()
    
    def clear_cache(self) -> None:
        """Clear evaluation cache."""
        self.evaluation_cache.clear()
        logger.info("Evaluation cache cleared")
    
    async def shutdown(self) -> None:
        """Shutdown the rule engine."""
        self.executor.shutdown(wait=True)
        logger.info("RuleEngine shutdown complete")