"""Batch processing of content items through the rule engine."""
import asyncio
import csv
import io
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleStatus, RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.core.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


class BatchFormat(str, Enum):
    """Supported batch input formats."""
    JSON = "json"
    CSV = "csv"
    TXT = "txt"
    JSONL = "jsonl"


class BatchOutputFormat(str, Enum):
    """Supported batch output formats."""
    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    TEXT = "text"
    HTML = "html"


class BatchItemStatus(str, Enum):
    """Status of a batch item after processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    VIOLATED = "violated"
    BLOCKED = "blocked"


@dataclass
class BatchItem:
    """Single item in a batch."""
    index: int
    content: str
    source: str = ""
    tier: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    status: BatchItemStatus = BatchItemStatus.PENDING
    result: Optional[ValidationResult] = None
    error: Optional[str] = None
    processing_time_ms: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def elapsed_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0

    @property
    def is_valid(self) -> bool:
        return self.result is not None and self.result.valid

    @property
    def has_violations(self) -> bool:
        return self.result is not None and len(self.result.violations) > 0

    @property
    def is_blocked(self) -> bool:
        return self.result is not None and self.result.is_blocked()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "content": self.content[:100],
            "source": self.source,
            "status": self.status.value,
            "error": self.error,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "valid": self.is_valid if self.result else None,
            "violations": len(self.result.violations) if self.result else 0,
            "score": round(self.result.total_score, 3) if self.result else None,
        }


@dataclass
class BatchResult:
    """Aggregated result from batch processing."""
    total_items: int
    valid_items: int
    items_with_violations: int
    blocked_items: int
    failed_items: int
    items: List[BatchItem] = field(default_factory=list)
    total_processing_time_ms: float = 0.0
    average_processing_time_ms: float = 0.0
    total_violations: int = 0
    total_suggestions: int = 0
    batch_id: str = ""
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    source_file: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.valid_items / self.total_items) * 100

    @property
    def violation_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.items_with_violations / self.total_items) * 100

    @property
    def failure_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.failed_items / self.total_items) * 100

    def get_summary(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "source_file": self.source_file,
            "total_items": self.total_items,
            "valid_items": self.valid_items,
            "items_with_violations": self.items_with_violations,
            "blocked_items": self.blocked_items,
            "failed_items": self.failed_items,
            "success_rate": round(self.success_rate, 2),
            "violation_rate": round(self.violation_rate, 2),
            "failure_rate": round(self.failure_rate, 2),
            "total_violations": self.total_violations,
            "total_suggestions": self.total_suggestions,
            "total_processing_time_ms": round(self.total_processing_time_ms, 2),
            "avg_processing_time_ms": round(self.average_processing_time_ms, 2),
        }

    def get_aggregate_validation_result(self) -> ValidationResult:
        if not self.items:
            return ValidationResult(valid=True, total_rules_evaluated=0)
        all_violations = []
        all_suggestions = []
        total_time = 0
        total_rules = 0
        for item in self.items:
            if item.result:
                all_violations.extend(item.result.violations)
                all_suggestions.extend(item.result.suggestions)
                total_time += item.result.processing_time_ms
                total_rules += item.result.total_rules_evaluated
        return ValidationResult(
            valid=self.failed_items == 0 and self.blocked_items == 0,
            total_score=1.0 - (self.items_with_violations / max(self.total_items, 1)),
            violations=all_violations,
            suggestions=all_suggestions,
            total_rules_evaluated=total_rules,
            processing_time_ms=int(total_time),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.get_summary(),
            "items": [item.to_dict() for item in self.items],
        }


class BatchProcessor:
    """Process multiple content items through the rule engine."""

    def __init__(
        self,
        engine: Optional[RuleEngine] = None,
        console: Optional[Console] = None,
        max_concurrency: int = 10,
        show_progress: bool = True,
    ):
        self.engine = engine
        self.console = console or Console()
        self.max_concurrency = max_concurrency
        self.show_progress = show_progress
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def set_engine(self, engine: RuleEngine) -> None:
        self.engine = engine

    async def process_file(
        self,
        filepath: Path,
        tier: Optional[RuleTier] = None,
        output_format: str = "table",
        output_path: Optional[Path] = None,
        verbose: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> BatchResult:
        if not self.engine:
            raise RuntimeError("Engine not set. Call set_engine() first.")

        start_time = time.time()
        batch_id = f"batch_{int(start_time * 1000)}"

        items = self._parse_file(filepath)
        total = len(items)

        if total == 0:
            self.console.print("[yellow]No items found in input file[/yellow]")
            return BatchResult(total_items=0, valid_items=0, items_with_violations=0,
                              blocked_items=0, failed_items=0)

        self.console.print(f"[blue]Processing {total} items from {filepath}...[/blue]")
        self.console.print(f"[blue]Max concurrency: {self.max_concurrency}[/blue]")

        for item in items:
            item.status = BatchItemStatus.PROCESSING
            item.started_at = time.time()

        completed = 0
        failed = 0
        sem = asyncio.Semaphore(self.max_concurrency)

        progress: Optional[Progress] = None
        task_id = None

        if self.show_progress and not verbose:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
            )
            task_id = progress.add_task("[cyan]Processing...", total=total)
            progress.start()

        async def process_item(item: BatchItem) -> None:
            nonlocal completed, failed
            async with sem:
                try:
                    rule_tier = RuleTier(item.tier) if item.tier else tier
                except ValueError:
                    rule_tier = tier

                req_context = None
                if item.context or context:
                    merged = {}
                    if context:
                        merged.update(context)
                    if item.context:
                        merged.update(item.context)
                    req_context = RuleContext(**merged)

                request = RuleEvaluationRequest(
                    content=item.content,
                    tier=rule_tier,
                    context=req_context,
                )

                try:
                    result = await self.engine.evaluate(request)
                    item.result = result
                    item.status = BatchItemStatus.COMPLETED if result.valid else BatchItemStatus.VIOLATED
                    if result.is_blocked():
                        item.status = BatchItemStatus.BLOCKED
                except Exception as e:
                    item.status = BatchItemStatus.FAILED
                    item.error = str(e)
                    failed += 1

                item.completed_at = time.time()
                item.processing_time_ms = item.elapsed_ms

                completed += 1
                if progress and task_id is not None:
                    progress.update(task_id, advance=1)
                    status_text = f"[cyan]Processing... {completed}/{total} ({failed} failed)"
                    progress.update(task_id, description=status_text)

        tasks = [process_item(item) for item in items]
        await asyncio.gather(*tasks)

        if progress and task_id is not None:
            progress.update(task_id, description=f"[green]Complete: {completed}/{total}")
            progress.stop()

        end_time = time.time()
        total_time_ms = (end_time - start_time) * 1000

        valid_count = sum(1 for item in items if item.is_valid)
        violated_count = sum(1 for item in items if item.has_violations)
        blocked_count = sum(1 for item in items if item.is_blocked)
        failed_count = sum(1 for item in items if item.status == BatchItemStatus.FAILED)
        total_violations = sum(len(item.result.violations) for item in items if item.result)
        total_suggestions = sum(len(item.result.suggestions) for item in items if item.result)

        result = BatchResult(
            total_items=total,
            valid_items=valid_count,
            items_with_violations=violated_count,
            blocked_items=blocked_count,
            failed_items=failed_count,
            items=items,
            total_processing_time_ms=total_time_ms,
            average_processing_time_ms=total_time_ms / max(total, 1),
            total_violations=total_violations,
            total_suggestions=total_suggestions,
            batch_id=batch_id,
            started_at=start_time,
            completed_at=end_time,
            source_file=str(filepath),
        )

        if verbose:
            self._print_verbose_results(result)
        elif self.show_progress:
            self._print_summary(result)

        if output_path:
            self._write_output(result, output_path, output_format)

        return result

    def _parse_file(self, filepath: Path) -> List[BatchItem]:
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        suffix = filepath.suffix.lower()
        content = filepath.read_text(encoding="utf-8")

        if suffix == ".json":
            return self._parse_json(content)
        elif suffix == ".jsonl":
            return self._parse_jsonl(content)
        elif suffix == ".csv":
            return self._parse_csv(filepath)
        elif suffix in (".txt", ".text"):
            return self._parse_txt(content)
        elif suffix in (".yaml", ".yml"):
            return self._parse_yaml(content)
        else:
            return self._parse_txt(content)

    def _parse_json(self, content: str) -> List[BatchItem]:
        data = json.loads(content)
        items = []

        if isinstance(data, dict):
            items = [self._dict_to_batch_item(data, 0)]
        elif isinstance(data, list):
            for i, entry in enumerate(data):
                if isinstance(entry, str):
                    items.append(BatchItem(index=i, content=entry))
                elif isinstance(entry, dict):
                    items.append(self._dict_to_batch_item(entry, i))
        return items

    def _parse_jsonl(self, content: str) -> List[BatchItem]:
        items = []
        for i, line in enumerate(content.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, str):
                    items.append(BatchItem(index=i, content=entry))
                elif isinstance(entry, dict):
                    items.append(self._dict_to_batch_item(entry, i))
            except json.JSONDecodeError:
                items.append(BatchItem(index=i, content=line, error="Invalid JSON"))
        return items

    def _parse_csv(self, filepath: Path) -> List[BatchItem]:
        items = []
        with open(str(filepath), newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                content = row.get("content", row.get("text", row.get("input", "")))
                tier = row.get("tier")
                context_str = row.get("context")
                context = None
                if context_str:
                    try:
                        context = json.loads(context_str)
                    except json.JSONDecodeError:
                        context = {"raw": context_str}
                items.append(BatchItem(
                    index=i,
                    content=content,
                    source=row.get("source", ""),
                    tier=tier,
                    context=context,
                ))
        if not items:
            with open(str(filepath), newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if row:
                        items.append(BatchItem(index=i, content=row[0]))
        return items

    def _parse_txt(self, content: str) -> List[BatchItem]:
        lines = content.strip().split("\n")
        items = []
        for i, line in enumerate(lines):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                items.append(BatchItem(index=i, content=line))
        return items

    def _parse_yaml(self, content: str) -> List[BatchItem]:
        import yaml
        data = yaml.safe_load(content)
        items = []
        if isinstance(data, list):
            for i, entry in enumerate(data):
                if isinstance(entry, str):
                    items.append(BatchItem(index=i, content=entry))
                elif isinstance(entry, dict):
                    items.append(self._dict_to_batch_item(entry, i))
        elif isinstance(data, dict):
            items.append(self._dict_to_batch_item(data, 0))
        return items

    def _dict_to_batch_item(self, d: Dict[str, Any], index: int) -> BatchItem:
        content = d.get("content", d.get("text", d.get("input", "")))
        if not content:
            content = json.dumps(d)
        context = d.get("context")
        if isinstance(context, str):
            try:
                context = json.loads(context)
            except json.JSONDecodeError:
                context = {"raw": context}
        return BatchItem(
            index=index,
            content=str(content),
            source=d.get("source", d.get("name", "")),
            tier=d.get("tier"),
            context=context,
        )

    def _print_summary(self, result: BatchResult) -> None:
        summary = result.get_summary()
        color = "green" if summary["success_rate"] >= 80 else ("yellow" if summary["success_rate"] >= 50 else "red")
        self.console.print()
        self.console.print(Panel(
            f"[bold]Batch ID:[/bold] {result.batch_id}\n"
            f"[bold]File:[/bold] {result.source_file}\n\n"
            f"[bold]Total Items:[/bold] {summary['total_items']}\n"
            f"[bold]Valid:[/bold] [green]{summary['valid_items']}[/green] "
            f"(Success Rate: [{'green' if summary['success_rate'] >= 80 else 'yellow'}]{summary['success_rate']}%[/])\n"
            f"[bold]With Violations:[/bold] [red]{summary['items_with_violations']}[/red] "
            f"(Violation Rate: {summary['violation_rate']}%)\n"
            f"[bold]Blocked:[/bold] [magenta]{summary['blocked_items']}[/magenta]\n"
            f"[bold]Failed:[/bold] [red]{summary['failed_items']}[/red] "
            f"(Failure Rate: {summary['failure_rate']}%)\n"
            f"[bold]Total Violations:[/bold] {summary['total_violations']}\n"
            f"[bold]Total Suggestions:[/bold] {summary['total_suggestions']}\n\n"
            f"[bold]Processing Time:[/bold] {summary['total_processing_time_ms']}ms total, "
            f"{summary['avg_processing_time_ms']}ms avg",
            title=f"Batch Processing Complete",
            border_style=color
        ))

    def _print_verbose_results(self, result: BatchResult) -> None:
        self._print_summary(result)
        self.console.print()

        if result.failed_items > 0:
            self.console.print(Panel("Failed Items", title="Errors", border_style="red"))
            fail_table = Table(show_header=True, header_style="bold red", box=box.ROUNDED)
            fail_table.add_column("Index", style="cyan")
            fail_table.add_column("Content", style="yellow")
            fail_table.add_column("Error", style="red")
            for item in result.items:
                if item.status == BatchItemStatus.FAILED:
                    fail_table.add_row(str(item.index), item.content[:60], item.error or "Unknown")
            self.console.print(fail_table)
            self.console.print()

        if result.items_with_violations > 0:
            self.console.print(Panel("Items with Violations", title="Violations Detail", border_style="red"))
            viol_table = Table(show_header=True, header_style="bold red", box=box.ROUNDED)
            viol_table.add_column("Index", style="cyan")
            viol_table.add_column("Content", style="yellow")
            viol_table.add_column("Violations", style="red")
            viol_table.add_column("Score", style="magenta")
            for item in result.items:
                if item.has_violations and item.result:
                    viol_table.add_row(
                        str(item.index),
                        item.content[:50],
                        str(len(item.result.violations)),
                        f"{item.result.total_score:.2f}",
                    )
            self.console.print(viol_table)

    def _write_output(self, result: BatchResult, output_path: Path, fmt: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            output_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        elif fmt == "csv":
            self._write_csv_output(result, output_path)
        elif fmt == "text":
            lines = [f"Batch Results: {result.batch_id}", f"Source: {result.source_file}", ""]
            summary = result.get_summary()
            for key, value in summary.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
            for item in result.items:
                status = item.status.value
                score = f"{item.result.total_score:.2f}" if item.result else "N/A"
                lines.append(f"  [{status}] Item {item.index}: score={score}, violations={len(item.result.violations) if item.result else 0}")
            output_path.write_text("\n".join(lines), encoding="utf-8")
        elif fmt == "html":
            self._write_html_output(result, output_path)
        else:
            output_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")

        self.console.print(f"[green]Results written to {output_path}[/green]")

    def _write_csv_output(self, result: BatchResult, output_path: Path) -> None:
        with open(str(output_path), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Index", "Content", "Status", "Score", "Violations", "Suggestions", "Blocked", "Error", "ProcessingTimeMs"])
            for item in result.items:
                writer.writerow([
                    item.index,
                    item.content[:200],
                    item.status.value,
                    round(item.result.total_score, 3) if item.result else "",
                    len(item.result.violations) if item.result else "",
                    len(item.result.suggestions) if item.result else "",
                    item.result.is_blocked() if item.result else "",
                    item.error or "",
                    round(item.processing_time_ms, 2),
                ])

    def _write_html_output(self, result: BatchResult, output_path: Path) -> None:
        rows = []
        for item in result.items:
            score = f"{item.result.total_score:.3f}" if item.result else "N/A"
            violations = str(len(item.result.violations)) if item.result else "0"
            rows.append(f"<tr><td>{item.index}</td><td>{item.content[:80]}</td>"
                       f"<td>{item.status.value}</td><td>{score}</td>"
                       f"<td>{violations}</td><td>{item.error or ''}</td></tr>")
        html = f"""<html><head><title>Batch Results</title>
        <style>table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 6px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; }}
        .passed {{ color: green; }} .failed {{ color: red; }} .violated {{ color: orange; }}</style></head>
        <body><h2>Batch Results: {result.batch_id}</h2>
        <p>Source: {result.source_file} | Items: {result.total_items} | "
        f"Valid: {result.valid_items} | Violations: {result.items_with_violations} | "
        f"Failed: {result.failed_items}</p>
        <table><tr><th>Index</th><th>Content</th><th>Status</th><th>Score</th><th>Violations</th><th>Error</th></tr>
        {''.join(rows)}
        </table><p>Generated: {datetime.utcnow().isoformat()}</p></body></html>"""
        output_path.write_text(html, encoding="utf-8")

    def process_strings(
        self,
        strings: List[str],
        tier: Optional[RuleTier] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> BatchResult:
        items = [BatchItem(index=i, content=s) for i, s in enumerate(strings)]
        return asyncio.run(self._process_items(items, tier=tier, context=context))

    async def _process_items(
        self,
        items: List[BatchItem],
        tier: Optional[RuleTier] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> BatchResult:
        start_time = time.time()
        batch_id = f"batch_{int(start_time * 1000)}"
        total = len(items)

        completed = 0
        failed = 0
        sem = asyncio.Semaphore(self.max_concurrency)

        async def process_item(item: BatchItem) -> None:
            nonlocal completed, failed
            async with sem:
                item.started_at = time.time()
                item.status = BatchItemStatus.PROCESSING
                try:
                    req = RuleEvaluationRequest(content=item.content, tier=tier)
                    result = await self.engine.evaluate(req)
                    item.result = result
                    item.status = BatchItemStatus.COMPLETED if result.valid else BatchItemStatus.VIOLATED
                    if result.is_blocked():
                        item.status = BatchItemStatus.BLOCKED
                except Exception as e:
                    item.status = BatchItemStatus.FAILED
                    item.error = str(e)
                    failed += 1
                item.completed_at = time.time()
                item.processing_time_ms = item.elapsed_ms
                completed += 1

        await asyncio.gather(*[process_item(item) for item in items])

        end_time = time.time()
        total_time_ms = (end_time - start_time) * 1000

        valid_count = sum(1 for item in items if item.is_valid)
        violated_count = sum(1 for item in items if item.has_violations)
        blocked_count = sum(1 for item in items if item.is_blocked)
        failed_count = sum(1 for item in items if item.status == BatchItemStatus.FAILED)
        total_violations = sum(len(item.result.violations) for item in items if item.result)
        total_suggestions = sum(len(item.result.suggestions) for item in items if item.result)

        return BatchResult(
            total_items=total,
            valid_items=valid_count,
            items_with_violations=violated_count,
            blocked_items=blocked_count,
            failed_items=failed_count,
            items=items,
            total_processing_time_ms=total_time_ms,
            average_processing_time_ms=total_time_ms / max(total, 1),
            total_violations=total_violations,
            total_suggestions=total_suggestions,
            batch_id=batch_id,
            started_at=start_time,
            completed_at=end_time,
        )

    def get_item_by_index(self, result: BatchResult, index: int) -> Optional[BatchItem]:
        for item in result.items:
            if item.index == index:
                return item
        return None

    def get_failed_items(self, result: BatchResult) -> List[BatchItem]:
        return [item for item in result.items if item.status == BatchItemStatus.FAILED]

    def get_violated_items(self, result: BatchResult) -> List[BatchItem]:
        return [item for item in result.items if item.has_violations]

    def get_passed_items(self, result: BatchResult) -> List[BatchItem]:
        return [item for item in result.items if item.is_valid]

    def get_items_by_status(self, result: BatchResult, status: BatchItemStatus) -> List[BatchItem]:
        return [item for item in result.items if item.status == status]

    def get_violations_summary(self, result: BatchResult) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for item in result.items:
            if item.result and item.result.violations:
                for v in item.result.violations:
                    key = v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type)
                    summary[key] = summary.get(key, 0) + 1
        return summary

    def get_severity_summary(self, result: BatchResult) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for item in result.items:
            if item.result and item.result.violations:
                for v in item.result.violations:
                    key = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
                    summary[key] = summary.get(key, 0) + 1
        return summary

    def get_tier_summary(self, result: BatchResult) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for item in result.items:
            if item.result and item.result.violations:
                for v in item.result.violations:
                    key = v.rule_tier.value if hasattr(v.rule_tier, "value") else str(v.rule_tier)
                    summary[key] = summary.get(key, 0) + 1
        return summary

    def print_detailed_failure_report(self, result: BatchResult) -> None:
        failed = self.get_failed_items(result)
        if not failed:
            self.console.print("[green]No failures to report[/green]")
            return
        self.console.print(Panel(f"Total Failures: {len(failed)}", title="Failure Report", border_style="red"))
        for item in failed:
            self.console.print(f"  [{item.index}] {item.content[:80]}")
            self.console.print(f"       Error: {item.error}")
            self.console.print()

    def get_processing_time_distribution(self, result: BatchResult) -> Dict[str, int]:
        buckets = {"0-10ms": 0, "10-50ms": 0, "50-100ms": 0, "100-500ms": 0, "500ms+": 0}
        for item in result.items:
            t = item.processing_time_ms
            if t < 10:
                buckets["0-10ms"] += 1
            elif t < 50:
                buckets["10-50ms"] += 1
            elif t < 100:
                buckets["50-100ms"] += 1
            elif t < 500:
                buckets["100-500ms"] += 1
            else:
                buckets["500ms+"] += 1
        return buckets
