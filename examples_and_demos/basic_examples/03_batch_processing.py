#!/usr/bin/env python3
'''
03_batch_processing.py - Batch Processing Demonstration

Demonstrates how to process multiple content items in batch
with parallel evaluation and aggregated results.
'''

import asyncio
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.models.rule import (
    Rule, RuleTier, RuleType, RuleSeverity, RuleStatus,
    RulePattern, EnforcementLevel, RuleEvaluationRequest, RuleContext
)
from rules_emerging_pattern.models.validation import ValidationResult, BatchValidationResult


class BatchProcessor:
    '''Processor for batch content evaluation.'''
    
    def __init__(self, max_workers: int = 5):
        self.engine = RuleEngine()
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
    async def process_batch(
        self,
        contents: List[str],
        context: RuleContext = None,
        parallel: bool = True
    ) -> BatchValidationResult:
        '''Process multiple content items.'''
        start_time = time.time()
        
        if context is None:
            context = RuleContext()
            
        # Create evaluation requests
        requests = [
            RuleEvaluationRequest(
                content=content,
                context=context,
                parallel_evaluation=parallel
            )
            for content in contents
        ]
        
        # Evaluate all requests
        results = await self.engine.evaluate_batch(requests)
        
        # Calculate batch metrics
        total_time = int((time.time() - start_time) * 1000)
        valid_count = sum(1 for r in results if r.valid)
        blocked_count = sum(1 for r in results if r.is_blocked())
        violations_count = sum(len(r.violations) for r in results)
        
        return BatchValidationResult(
            total_items=len(contents),
            valid_items=valid_count,
            blocked_items=blocked_count,
            items_with_violations=sum(1 for r in results if r.has_violations()),
            individual_results=results,
            total_processing_time_ms=total_time,
            average_processing_time_ms=total_time / len(contents) if contents else 0,
            total_violations=violations_count,
            total_suggestions=sum(len(r.suggestions) for r in results)
        )
    
    async def process_with_progress(
        self,
        contents: List[str],
        progress_callback = None,
        context: RuleContext = None
    ) -> BatchValidationResult:
        '''Process with progress callbacks.'''
        results = []
        
        for i, content in enumerate(contents):
            request = RuleEvaluationRequest(
                content=content,
                context=context or RuleContext()
            )
            result = await self.engine.evaluate(request)
            results.append(result)
            
            if progress_callback:
                progress_callback(i + 1, len(contents), result)
                
        return BatchValidationResult(
            total_items=len(contents),
            valid_items=sum(1 for r in results if r.valid),
            blocked_items=sum(1 for r in results if r.is_blocked()),
            items_with_violations=sum(1 for r in results if r.has_violations()),
            individual_results=results,
            total_violations=sum(len(r.violations) for r in results)
        )
    
    async def shutdown(self):
        '''Clean up resources.'''
        self.executor.shutdown(wait=True)
        await self.engine.shutdown()


def print_batch_summary(batch_result: BatchValidationResult) -> None:
    '''Print summary of batch processing.'''
    print('\n' + '=' * 60)
    print('BATCH PROCESSING SUMMARY')
    print('=' * 60)
    print(f'Total Items: {batch_result.total_items}')
    print(f'Valid Items: {batch_result.valid_items}')
    print(f'Blocked Items: {batch_result.blocked_items}')
    print(f'Items with Violations: {batch_result.items_with_violations}')
    print(f'Success Rate: {batch_result.get_success_rate():.1f}%')
    print(f'Violation Rate: {batch_result.get_violation_rate():.1f}%')
    print(f'Total Processing Time: {batch_result.total_processing_time_ms}ms')
    print(f'Average Time per Item: {batch_result.average_processing_time_ms:.1f}ms')
    print(f'Total Violations: {batch_result.total_violations}')
    print(f'Total Suggestions: {batch_result.total_suggestions}')
    print('=' * 60)


async def main():
    '''Main example function.'''
    print('Batch Processing Example - Rules-Emerging-Pattern')
    print('=' * 60)
    
    # Create batch processor
    processor = BatchProcessor(max_workers=5)
    
    # Sample batch of content
    test_contents = [
        'This is completely safe content for processing.',
        'Instructions for creating dangerous weapons and explosives.',
        'A normal business email about quarterly reports.',
        'Content with harmful keywords that should be flagged.',
        'Safe educational material about chemistry.',
        'Another safe piece of content without issues.',
        'Medical advice that could be dangerous if misused.',
        'Regular customer support response template.',
        'Technical documentation for software features.',
        'Content discussing controversial political topics.'
    ]
    
    print(f'\nProcessing {len(test_contents)} items in batch...\n')
    
    # Process batch
    batch_result = await processor.process_batch(test_contents)
    
    # Print summary
    print_batch_summary(batch_result)
    
    # Show individual results
    print('\nINDIVIDUAL RESULTS:')
    print('-' * 60)
    for i, (content, result) in enumerate(zip(test_contents, batch_result.individual_results)):
        status = 'BLOCKED' if result.is_blocked() else 'VALID' if result.valid else 'VIOLATIONS'
        print(f'{i+1}. [{status}] {content[:50]}...')
        if result.violations:
            for v in result.violations:
                print(f'   - {v.rule_name}: {v.explanation}')
    
    # Process with progress callback
    print('\n\nProcessing with progress tracking...')
    
    def progress_callback(current, total, result):
        pct = (current / total) * 100
        print(f'Progress: {current}/{total} ({pct:.1f}%) - {"Blocked" if result.is_blocked() else "OK"}')
    
    small_batch = test_contents[:5]
    result = await processor.process_with_progress(
        small_batch,
        progress_callback=progress_callback
    )
    
    print('\nProgress tracking complete!')
    print(f'Success Rate: {result.get_success_rate():.1f}%')
    
    await processor.shutdown()
    
    print('\n' + '=' * 60)
    print('Batch processing example completed!')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
