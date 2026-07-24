"""Command Line Interface for Rules-Emerging-Pattern."""
import asyncio
import csv
import io
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.rule_engines.base.rule_manager import RuleManager
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleStatus, RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

from .output_formatter import OutputFormatter
from .config_commands import ConfigCommands
from .batch_processor import BatchProcessor

app = typer.Typer(help="Rules-Emerging-Pattern CLI")
console = Console()
formatter = OutputFormatter(console=console)


def get_engine():
    """Get or initialize rule engine."""
    rule_manager = RuleManager()
    return RuleEngine(rule_manager=rule_manager)


def load_config_file(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration from a config file."""
    if config_path is None:
        config_path = Path("config.json")
    if not config_path.exists():
        config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path.home() / ".rules-emerging-pattern" / "config.json"
    if not config_path.exists():
        config_path = Path.home() / ".rules-emerging-pattern" / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        content = config_path.read_text(encoding="utf-8")
        if config_path.suffix in (".yaml", ".yml"):
            import yaml
            return yaml.safe_load(content) or {}
        return json.loads(content)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not load config from {config_path}: {e}[/yellow]")
        return {}


def save_config_file(config: Dict[str, Any], config_path: Path) -> bool:
    """Save configuration to a file."""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.suffix in (".yaml", ".yml"):
            import yaml
            config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")
        else:
            config_path.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")
        return True
    except Exception as e:
        console.print(f"[red]Error saving config: {e}[/red]")
        return False


def get_default_config() -> Dict[str, Any]:
    """Get default configuration values."""
    return {
        "engine": {
            "max_workers": 10,
            "cache_size": 1000,
            "cache_ttl": 300,
            "batch_concurrency": 10,
            "evaluation_timeout_ms": 5000,
            "profiling_enabled": True,
            "hot_reload_enabled": False,
            "webhook_enabled": False,
        },
        "output": {
            "format": "table",
            "color_enabled": True,
            "verbose": False,
            "quiet": False,
        },
        "logging": {
            "level": "INFO",
            "format": "text",
        },
        "monitoring": {
            "enabled": True,
            "export_interval": 300,
            "prometheus_enabled": False,
        },
    }


@app.command()
def validate(
    content: str = typer.Option(..., "--content", "-c", help="Content to validate"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Rule tier (safety, operational, preference)"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Save output to file"),
):
    """Validate content against rules with detailed output."""
    engine = get_engine()

    try:
        rule_tier = RuleTier(tier) if tier else None
    except ValueError:
        console.print(f"[red]Error: Invalid tier '{tier}'. Choose from: safety, operational, preference[/red]")
        sys.exit(1)

    request = RuleEvaluationRequest(
        content=content,
        tier=rule_tier
    )

    try:
        result = asyncio.run(engine.evaluate(request))
    except Exception as e:
        console.print(f"[red]Error during evaluation: {e}[/red]")
        sys.exit(1)

    if output_json:
        output = json.dumps(result.dict(), indent=2, default=str)
        console.print(output)
        if output_file:
            output_file.write_text(output, encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
    elif verbose:
        formatter.print_verbose_result(result, title="Validation Result")
        if output_file:
            output_file.write_text(formatter.format_verbose_result(result), encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
    else:
        formatter.print_result(result, title="Validation Result")
        if output_file:
            output_file.write_text(formatter.format_result(result), encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")


@app.command()
def evaluate(
    content: str = typer.Option(..., "--content", "-c", help="Content to evaluate"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Rule tier filter"),
    rule_type: Optional[str] = typer.Option(None, "--rule-type", "-r", help="Rule type filter"),
    context_json: Optional[str] = typer.Option(None, "--context", help="Context as JSON string"),
    min_severity: Optional[str] = typer.Option(None, "--min-severity", help="Minimum severity threshold"),
    parallel: bool = typer.Option(True, "--parallel/--sequential", help="Parallel evaluation"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Save output to file"),
):
    """Detailed evaluation with full output and score breakdown."""
    engine = get_engine()

    try:
        rule_tier = RuleTier(tier) if tier else None
    except ValueError:
        console.print(f"[red]Error: Invalid tier '{tier}'. Choose from: safety, operational, preference[/red]")
        sys.exit(1)

    rule_type_enum = None
    if rule_type:
        try:
            rule_type_enum = RuleType(rule_type)
        except ValueError:
            console.print(f"[red]Error: Invalid rule type '{rule_type}'[/red]")
            sys.exit(1)

    severity_filter = None
    if min_severity:
        try:
            severity_filter = RuleSeverity(min_severity)
        except ValueError:
            console.print(f"[red]Error: Invalid severity '{min_severity}'. Choose from: low, medium, high, critical[/red]")
            sys.exit(1)

    context = None
    if context_json:
        try:
            context_data = json.loads(context_json)
            context = RuleContext(**context_data)
        except (json.JSONDecodeError, TypeError) as e:
            console.print(f"[red]Error parsing context: {e}[/red]")
            sys.exit(1)

    request = RuleEvaluationRequest(
        content=content,
        tier=rule_tier,
        context=context,
        parallel_evaluation=parallel,
    )

    if severity_filter:
        request.options["min_severity"] = min_severity

    try:
        result = asyncio.run(engine.evaluate(request))
    except Exception as e:
        console.print(f"[red]Error during evaluation: {e}[/red]")
        sys.exit(1)

    if output_json:
        output = json.dumps(result.dict(), indent=2, default=str)
        console.print(output)
        if output_file:
            output_file.write_text(output, encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
        return

    score_breakdown = result.get_score_breakdown()

    console.print(Panel(
        f"[bold]Content:[/bold] {content[:80]}{'...' if len(content) > 80 else ''}\n"
        f"[bold]Result:[/bold] {'[green]PASS[/green]' if result.valid else '[red]FAIL[/red]'}\n"
        f"[bold]Score:[/bold] {result.total_score:.3f}\n"
        f"[bold]Confidence:[/bold] {result.confidence:.2%}\n"
        f"[bold]Processing Time:[/bold] {result.processing_time_ms}ms",
        title="Evaluation Result",
        border_style="blue"
    ))

    console.print()
    score_table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
    score_table.add_column("Component", style="white")
    score_table.add_column("Value", style="yellow")
    score_table.add_row("Base Score", f"{score_breakdown['base_score']:.3f}")
    score_table.add_row("Tier Penalty", f"{score_breakdown['tier_penalty']:.3f}")
    score_table.add_row("Severity Penalty", f"{score_breakdown['severity_penalty']:.3f}")
    score_table.add_row("Total Penalty", f"{score_breakdown['total_penalty']:.3f}")
    score_table.add_row("Final Score", f"{score_breakdown['final_score']:.3f}")
    console.print(Panel(score_table, title="Score Breakdown", border_style="green"))

    if result.violations:
        console.print()
        violations_by_severity = result.get_violations_by_severity()
        for severity in ["critical", "high", "medium", "low"]:
            if severity in violations_by_severity:
                color = {"critical": "red", "high": "magenta", "medium": "yellow", "low": "cyan"}[severity]
                table = Table(show_header=True, header_style=f"bold {color}", box=box.ROUNDED)
                table.add_column("Rule Name", style="white")
                table.add_column("Tier", style="green")
                table.add_column("Type", style="blue")
                table.add_column("Action", style=color)
                table.add_column("Explanation", style="grey50")
                for v in violations_by_severity[severity]:
                    table.add_row(
                        v.rule_name,
                        v.rule_tier.value if hasattr(v.rule_tier, "value") else str(v.rule_tier),
                        v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type),
                        v.action_taken.value if hasattr(v.action_taken, "value") else str(v.action_taken),
                        (v.explanation or "")[:60]
                    )
                console.print(Panel(table, title=f"[bold {color}]{severity.upper()} Violations[/bold {color}]", border_style=color))

    if result.suggestions:
        console.print()
        suggest_table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        suggest_table.add_column("Type", style="blue")
        suggest_table.add_column("Title", style="white")
        suggest_table.add_column("Confidence", style="yellow")
        suggest_table.add_column("Auto-apply", style="green")
        for s in result.suggestions:
            suggest_table.add_row(
                s.type,
                s.title[:50],
                f"{s.confidence:.0%}",
                "[green]Yes[/green]" if s.auto_applicable else "[red]No[/red]"
            )
        console.print(Panel(suggest_table, title="Suggestions", border_style="cyan"))

    if verbose and result.processing_details:
        console.print()
        details_table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        details_table.add_column("Key", style="cyan")
        details_table.add_column("Value", style="yellow")
        for key, value in result.processing_details.items():
            details_table.add_row(str(key), str(value)[:80])
        console.print(Panel(details_table, title="Processing Details", border_style="magenta"))

    if output_file:
        content_str = formatter.format_verbose_result(result) if verbose else formatter.format_result(result)
        output_file.write_text(content_str, encoding="utf-8")
        console.print(f"[green]Output saved to {output_file}[/green]")


@app.command()
def add_rule(
    name: str = typer.Option(..., "--name", "-n", help="Rule name"),
    tier: str = typer.Option(..., "--tier", "-t", help="Rule tier"),
    pattern: str = typer.Option(..., "--pattern", "-p", help="Pattern to match"),
    enforcement: str = typer.Option("advisory", "--enforcement", "-e", help="Enforcement level"),
    rule_type: str = typer.Option("pattern_matching", "--rule-type", "-r", help="Rule type"),
    severity: str = typer.Option("medium", "--severity", "-s", help="Rule severity"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Rule description"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Add a new rule to the system."""
    try:
        tier_enum = RuleTier(tier)
    except ValueError:
        console.print(f"[red]Error: Invalid tier '{tier}'. Choose from: safety, operational, preference[/red]")
        sys.exit(1)

    try:
        enforcement_enum = EnforcementLevel(enforcement)
    except ValueError:
        console.print(f"[red]Error: Invalid enforcement '{enforcement}'. Choose from: strict, advisory, adaptive, fallback[/red]")
        sys.exit(1)

    try:
        type_enum = RuleType(rule_type)
    except ValueError:
        console.print(f"[red]Error: Invalid rule type '{rule_type}'[/red]")
        sys.exit(1)

    try:
        severity_enum = RuleSeverity(severity)
    except ValueError:
        console.print(f"[red]Error: Invalid severity '{severity}'. Choose from: low, medium, high, critical[/red]")
        sys.exit(1)

    rule = Rule(
        id=f"rule_{int(time.time())}",
        name=name,
        description=description or f"Rule: {name}",
        tier=tier_enum,
        rule_type=type_enum,
        severity=severity_enum,
        enforcement_level=enforcement_enum,
        patterns=[
            RulePattern(
                type=type_enum,
                keywords=[pattern],
                action=enforcement
            )
        ],
        created_by="cli_user",
    )

    if output_json:
        console.print(json.dumps(rule.dict(), indent=2, default=str))
        return

    console.print(Panel(
        f"[bold green]Rule added successfully[/bold green]\n\n"
        f"[bold]Name:[/bold] {rule.name}\n"
        f"[bold]ID:[/bold] {rule.id}\n"
        f"[bold]Tier:[/bold] {rule.tier.value}\n"
        f"[bold]Type:[/bold] {rule.rule_type.value}\n"
        f"[bold]Severity:[/bold] {rule.severity.value}\n"
        f"[bold]Enforcement:[/bold] {rule.enforcement_level.value}\n"
        f"[bold]Pattern:[/bold] {pattern}\n"
        f"[bold]Status:[/bold] {rule.status.value}",
        title="New Rule",
        border_style="green"
    ))

    console.print(f"\n[yellow]Note: Rule persistence not implemented in this demo. Rule exists only in memory.[/yellow]")


@app.command()
def list_rules(
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Filter by tier"),
    active_only: bool = typer.Option(True, "--active/--all", help="Show only active rules"),
    rule_type: Optional[str] = typer.Option(None, "--rule-type", "-r", help="Filter by rule type"),
    severity: Optional[str] = typer.Option(None, "--severity", "-s", help="Filter by severity"),
    search: Optional[str] = typer.Option(None, "--search", help="Search in rule names and descriptions"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Save output to file"),
):
    """List all rules with advanced filtering."""
    engine = get_engine()

    if not engine.rule_manager:
        console.print("[red]Error: Rule manager not initialized[/red]")
        sys.exit(1)

    all_rules: List[Rule] = []

    if tier:
        try:
            tier_enum = RuleTier(tier)
            all_rules = engine.rule_manager.get_rules_by_tier(tier_enum)
        except ValueError:
            console.print(f"[red]Error: Invalid tier '{tier}'[/red]")
            sys.exit(1)
    else:
        all_rules = list(engine.rule_manager.rules.values())

    if active_only:
        all_rules = [r for r in all_rules if r.status == RuleStatus.ACTIVE]

    if rule_type:
        try:
            type_enum = RuleType(rule_type)
            all_rules = [r for r in all_rules if r.rule_type == type_enum]
        except ValueError:
            console.print(f"[red]Error: Invalid rule type '{rule_type}'[/red]")
            sys.exit(1)

    if severity:
        try:
            severity_enum = RuleSeverity(severity)
            all_rules = [r for r in all_rules if r.severity == severity_enum]
        except ValueError:
            console.print(f"[red]Error: Invalid severity '{severity}'[/red]")
            sys.exit(1)

    if search:
        search_lower = search.lower()
        all_rules = [
            r for r in all_rules
            if search_lower in r.name.lower() or search_lower in (r.description or "").lower()
        ]

    if output_json:
        output = json.dumps([r.dict() for r in all_rules], indent=2, default=str)
        console.print(output)
        if output_file:
            output_file.write_text(output, encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
        return

    if not all_rules:
        console.print("[yellow]No rules found matching the criteria.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Tier", style="yellow")
    table.add_column("Type", style="blue")
    table.add_column("Severity", style="red")
    table.add_column("Status", style="white")
    table.add_column("Enforcement", style="magenta")

    for rule in all_rules:
        table.add_row(
            rule.id[:12],
            rule.name[:30],
            rule.tier.value if hasattr(rule.tier, "value") else str(rule.tier),
            rule.rule_type.value if hasattr(rule.rule_type, "value") else str(rule.rule_type),
            rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity),
            rule.status.value if hasattr(rule.status, "value") else str(rule.status),
            rule.enforcement_level.value if hasattr(rule.enforcement_level, "value") else str(rule.enforcement_level),
        )

    console.print(Panel(f"Total Rules: {len(all_rules)}", title="Rules List", border_style="blue"))
    console.print(table)

    if output_file:
        output_file.write_text(formatter.format_table_to_text(table), encoding="utf-8")
        console.print(f"[green]Output saved to {output_file}[/green]")


@app.command()
def metrics(
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Save output to file"),
    prometheus: bool = typer.Option(False, "--prometheus", "-p", help="Output in Prometheus format"),
):
    """Show system metrics and statistics."""
    engine = get_engine()
    stats = engine.get_statistics()

    if output_json:
        output = json.dumps(stats, indent=2, default=str)
        console.print(output)
        if output_file:
            output_file.write_text(output, encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
        return

    if prometheus:
        output = engine.export_statistics_prometheus()
        console.print(output)
        if output_file:
            output_file.write_text(output, encoding="utf-8")
            console.print(f"[green]Output saved to {output_file}[/green]")
        return

    console.print(Panel("[bold]Rule Engine Performance Metrics[/bold]", title="System Metrics", border_style="green"))

    main_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    main_table.add_column("Metric", style="cyan", no_wrap=True)
    main_table.add_column("Value", style="yellow")

    main_table.add_row("Total Evaluations", str(stats["total_evaluations"]))
    main_table.add_row("Successful", str(stats["successful_evaluations"]))
    main_table.add_row("Failed", str(stats["failed_evaluations"]))
    main_table.add_row("Violations Detected", str(stats["violations_detected"]))
    main_table.add_row("Blocks Applied", str(stats["blocks_applied"]))
    main_table.add_row("Warnings Issued", str(stats.get("warnings_issued", 0)))
    main_table.add_row("Suggestions Generated", str(stats.get("suggestions_generated", 0)))
    main_table.add_row("Average Time (ms)", f"{stats['average_time_ms']:.2f}")
    main_table.add_row("Peak Time (ms)", f"{stats.get('peak_time_ms', 0):.2f}")
    main_table.add_row("Min Time (ms)", f"{stats.get('min_time_ms', 0):.2f}")
    main_table.add_row("Cache Size", f"{stats['cache_size']} / {stats['cache_max_size']}")
    main_table.add_row("Cache Hits", str(stats.get("cache_hits", 0)))
    main_table.add_row("Cache Misses", str(stats.get("cache_misses", 0)))
    main_table.add_row("Profiling Records", str(stats.get("profiling_records_count", 0)))
    main_table.add_row("Tier Engines Loaded", str(stats.get("tier_engines_loaded", 0)))
    main_table.add_row("Uptime", f"{stats.get('uptime_seconds', 0):.0f}s")
    console.print(main_table)

    if "hot_reloader_stats" in stats:
        hr = stats["hot_reloader_stats"]
        console.print()
        console.print(Panel(
            f"Running: {hr['running']}\n"
            f"Tracked Files: {hr['tracked_files']}\n"
            f"Changes Detected: {hr['total_changes_detected']}\n"
            f"Callbacks: {hr['callbacks_registered']}",
            title="Hot Reloader",
            border_style="yellow"
        ))

    if "webhook_stats" in stats:
        wh = stats["webhook_stats"]
        console.print()
        console.print(Panel(
            f"Notifications Sent: {wh['notification_count']}\n"
            f"Errors: {wh['error_count']}\n"
            f"URLs: {len(wh['webhook_urls'])}",
            title="Webhook Notifier",
            border_style="magenta"
        ))

    if "batch_processor_stats" in stats:
        bp = stats["batch_processor_stats"]
        console.print()
        console.print(Panel(
            f"Total Batches: {bp['total_batches']}\n"
            f"Total Items: {bp['total_items']}\n"
            f"Total Errors: {bp['total_errors']}\n"
            f"Avg Time: {bp['average_batch_time_ms']}ms\n"
            f"Error Rate: {bp['error_rate']}%",
            title="Batch Processor",
            border_style="cyan"
        ))

    if output_file:
        output_file.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
        console.print(f"[green]Output saved to {output_file}[/green]")


@app.command()
def monitor(
    interval: int = typer.Option(60, "--interval", "-i", help="Monitoring interval in seconds"),
    duration: int = typer.Option(300, "--duration", "-d", help="Monitoring duration in seconds"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON on each tick"),
    live_view: bool = typer.Option(False, "--live", "-l", help="Use live updating display"),
):
    """Monitor system in real-time with rich live display."""
    engine = get_engine()

    if live_view:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        monitor_task = progress.add_task("[cyan]Monitoring...", total=duration)

        try:
            with Live(progress, refresh_per_second=4) as live:
                start_time = time.time()
                while time.time() - start_time < duration:
                    stats = engine.get_statistics()
                    progress.update(
                        monitor_task,
                        completed=int(time.time() - start_time),
                        description=f"[cyan]Monitoring - "
                                   f"Evals: {stats['total_evaluations']} | "
                                   f"Violations: {stats['violations_detected']} | "
                                   f"Avg: {stats['average_time_ms']:.1f}ms"
                    )
                    time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitoring stopped by user[/yellow]")
    else:
        console.print(f"[blue]Monitoring for {duration} seconds (interval: {interval}s)...[/blue]")
        console.print("[yellow]Press Ctrl+C to stop[/yellow]")

        try:
            start_time = time.time()
            tick_count = 0
            while time.time() - start_time < duration:
                stats = engine.get_statistics()
                elapsed = int(time.time() - start_time)
                tick_count += 1

                if output_json:
                    report = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "tick": tick_count,
                        "elapsed_seconds": elapsed,
                        "total_evaluations": stats["total_evaluations"],
                        "violations_detected": stats["violations_detected"],
                        "blocks_applied": stats["blocks_applied"],
                        "average_time_ms": round(stats["average_time_ms"], 2),
                        "cache_hits": stats.get("cache_hits", 0),
                        "cache_misses": stats.get("cache_misses", 0),
                    }
                    console.print(json.dumps(report, indent=2))
                else:
                    console.print(
                        f"[green][{elapsed}s][/green] "
                        f"Evals: [cyan]{stats['total_evaluations']}[/cyan] | "
                        f"Violations: [red]{stats['violations_detected']}[/red] | "
                        f"Blocks: [magenta]{stats['blocks_applied']}[/magenta] | "
                        f"Avg Time: [yellow]{stats['average_time_ms']:.2f}ms[/yellow] | "
                        f"Cache: {stats.get('cache_hits', 0)}H/{stats.get('cache_misses', 0)}M"
                    )

                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitoring stopped[/yellow]")

    console.print("[green]Monitoring session completed[/green]")


@app.command()
def batch(
    input_file: Path = typer.Option(..., "--input", "-i", help="Input file path (JSON, CSV, TXT)"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Rule tier filter"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    output_format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, csv"),
    max_parallel: int = typer.Option(10, "--parallel", "-p", help="Max parallel evaluations"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Batch process multiple content items from a file."""
    engine = get_engine()

    rule_tier = None
    if tier:
        try:
            rule_tier = RuleTier(tier)
        except ValueError:
            console.print(f"[red]Error: Invalid tier '{tier}'[/red]")
            sys.exit(1)

    if not input_file.exists():
        console.print(f"[red]Error: Input file not found: {input_file}[/red]")
        sys.exit(1)

    processor = BatchProcessor(
        engine=engine,
        max_concurrency=max_parallel,
        console=console,
    )

    result = asyncio.run(processor.process_file(
        filepath=input_file,
        tier=rule_tier,
        output_format=output_format,
        output_path=output_file,
        verbose=verbose,
    ))

    if not verbose and not output_file:
        summary = result.get_summary()
        console.print(Panel(
            f"[bold]Total Items:[/bold] {summary['total_items']}\n"
            f"[bold]Valid:[/bold] [green]{summary['valid_items']}[/green]\n"
            f"[bold]With Violations:[/bold] [red]{summary['items_with_violations']}[/red]\n"
            f"[bold]Blocked:[/bold] [magenta]{summary['blocked_items']}[/magenta]\n"
            f"[bold]Success Rate:[/bold] {summary['success_rate']}%\n"
            f"[bold]Violation Rate:[/bold] {summary['violation_rate']}%\n"
            f"[bold]Total Time:[/bold] {summary['total_processing_time_ms']}ms\n"
            f"[bold]Avg Time:[/bold] {summary['avg_processing_time_ms']}ms",
            title="Batch Processing Complete",
            border_style="blue"
        ))


@app.command()
def config(
    action: str = typer.Argument("view", help="Action: view, set, reset, load, list"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Config key to view/set"),
    value: Optional[str] = typer.Option(None, "--value", "-v", help="Config value to set"),
    config_file: Optional[Path] = typer.Option(None, "--file", "-f", help="Config file to load"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """View, set, or manage configuration."""
    cfg = ConfigCommands(console=console)

    if action == "view":
        if key:
            cfg.view_key(key, output_json=output_json)
        else:
            cfg.view_all(output_json=output_json)

    elif action == "set":
        if not key or value is None:
            console.print("[red]Error: --key and --value are required for 'set' action[/red]")
            sys.exit(1)
        cfg.set_key(key, value)

    elif action == "reset":
        cfg.reset_to_defaults()

    elif action == "load":
        if not config_file or not config_file.exists():
            console.print(f"[red]Error: Config file not found: {config_file}[/red]")
            sys.exit(1)
        cfg.load_from_file(config_file)

    elif action == "list":
        cfg.list_sections(output_json=output_json)

    else:
        console.print(f"[red]Error: Unknown action '{action}'. Use: view, set, reset, load, list[/red]")
        sys.exit(1)


@app.command()
def export(
    output_file: Path = typer.Option(..., "--output", "-o", help="Output file path"),
    fmt: str = typer.Option("json", "--format", "-f", help="Export format: json, csv, html, txt"),
    data_type: str = typer.Option("metrics", "--data", "-d", help="Data to export: metrics, rules, config"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Filter rules by tier"),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty print output"),
):
    """Export rules, metrics, or results to a file."""
    engine = get_engine()

    if data_type == "metrics":
        stats = engine.get_statistics()
        if fmt == "json":
            output = json.dumps(stats, indent=2 if pretty else None, default=str)
        elif fmt == "csv":
            output = formatter.format_dict_as_csv(stats)
        elif fmt == "txt":
            output = formatter.format_dict_as_text(stats)
        elif fmt == "html":
            output = formatter.format_dict_as_html(stats, title="System Metrics")
        else:
            console.print(f"[red]Unsupported format: {fmt}[/red]")
            sys.exit(1)

    elif data_type == "rules":
        if not engine.rule_manager:
            console.print("[red]Error: Rule manager not initialized[/red]")
            sys.exit(1)
        all_rules = list(engine.rule_manager.rules.values())
        if tier:
            try:
                tier_enum = RuleTier(tier)
                all_rules = engine.rule_manager.get_rules_by_tier(tier_enum)
            except ValueError:
                console.print(f"[red]Error: Invalid tier '{tier}'[/red]")
                sys.exit(1)
        rules_data = [r.dict() for r in all_rules]
        if fmt == "json":
            output = json.dumps(rules_data, indent=2 if pretty else None, default=str)
        elif fmt == "csv":
            output = formatter.format_rules_as_csv(all_rules)
        elif fmt == "txt":
            output = formatter.format_rules_as_text(all_rules)
        elif fmt == "html":
            output = formatter.format_rules_as_html(all_rules)
        else:
            console.print(f"[red]Unsupported format: {fmt}[/red]")
            sys.exit(1)

    elif data_type == "config":
        config_data = get_default_config()
        if fmt == "json":
            output = json.dumps(config_data, indent=2 if pretty else None)
        elif fmt == "yaml":
            import yaml
            output = yaml.dump(config_data, default_flow_style=False)
        elif fmt == "txt":
            output = formatter.format_dict_as_text(config_data)
        elif fmt == "html":
            output = formatter.format_dict_as_html(config_data, title="Configuration")
        else:
            console.print(f"[red]Unsupported format: {fmt}[/red]")
            sys.exit(1)
    else:
        console.print(f"[red]Unknown data type: {data_type}. Use: metrics, rules, config[/red]")
        sys.exit(1)

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(output, encoding="utf-8")
        console.print(f"[green]Exported {data_type} to {output_file} ({len(output)} bytes)[/green]")
    except Exception as e:
        console.print(f"[red]Error writing file: {e}[/red]")
        sys.exit(1)


@app.command()
def import_rules(
    input_file: Path = typer.Option(..., "--input", "-i", help="Input file (JSON)"),
    merge: bool = typer.Option(False, "--merge", "-m", help="Merge with existing rules"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without importing"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Import rules from a file."""
    if not input_file.exists():
        console.print(f"[red]Error: Input file not found: {input_file}[/red]")
        sys.exit(1)

    try:
        content = input_file.read_text(encoding="utf-8")
        if input_file.suffix in (".yaml", ".yml"):
            import yaml
            rules_data = yaml.safe_load(content)
        else:
            rules_data = json.loads(content)
    except Exception as e:
        console.print(f"[red]Error reading input file: {e}[/red]")
        sys.exit(1)

    if isinstance(rules_data, dict):
        rules_data = [rules_data]
    elif not isinstance(rules_data, list):
        console.print("[red]Error: Input must be a JSON array of rules or a single rule object[/red]")
        sys.exit(1)

    imported = 0
    errors = 0
    error_details = []

    for i, rule_dict in enumerate(rules_data):
        try:
            rule = Rule(**rule_dict)
            imported += 1
        except Exception as e:
            errors += 1
            error_details.append(f"  Item {i}: {e}")

    if dry_run:
        console.print(Panel(
            f"[bold]Dry Run Results[/bold]\n\n"
            f"File: {input_file}\n"
            f"Total items: {len(rules_data)}\n"
            f"Valid rules: [green]{imported}[/green]\n"
            f"Errors: [red]{errors}[/red]",
            title="Import Preview",
            border_style="yellow"
        ))
        if errors and error_details:
            console.print("[red]Errors:[/red]")
            for detail in error_details:
                console.print(detail)
        return

    if output_json:
        console.print(json.dumps({
            "total": len(rules_data),
            "imported": imported,
            "errors": errors,
            "error_details": error_details,
        }, indent=2))
        return

    console.print(Panel(
        f"[bold green]Import Complete[/bold green]\n\n"
        f"File: {input_file}\n"
        f"Total items: {len(rules_data)}\n"
        f"Imported: [green]{imported}[/green]\n"
        f"Errors: [red]{errors}[/red]",
        title="Import Results",
        border_style="green"
    ))

    if errors and error_details:
        console.print("[red]Error Details:[/red]")
        for detail in error_details:
            console.print(detail)


@app.command()
def health(
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Perform a comprehensive system health check."""
    engine = get_engine()
    stats = engine.get_statistics()

    checks = {
        "engine_initialized": engine is not None,
        "rule_manager_initialized": engine.rule_manager is not None,
        "has_rules": len(engine.rule_manager.rules) > 0 if engine.rule_manager else False,
        "tier_engines_loaded": len(engine.tier_engines) > 0 if hasattr(engine, "tier_engines") else False,
        "cache_functional": hasattr(engine, "evaluation_cache"),
        "profiling_status": "enabled" if engine.profiling_enabled else "disabled",
        "hot_reload_status": "enabled" if engine.hot_reloader is not None else "disabled",
        "webhook_status": "enabled" if engine.webhook_notifier is not None else "disabled",
    }

    all_pass = all(v for k, v in checks.items() if isinstance(v, bool))
    health_status = "healthy" if all_pass else "degraded"

    if output_json:
        report = {
            "status": health_status,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": checks,
            "summary": stats,
        }
        console.print(json.dumps(report, indent=2, default=str))
        return

    status_color = "green" if health_status == "healthy" else "yellow"
    console.print(Panel(
        f"[bold]System Health: [{'green' if health_status == 'healthy' else 'yellow'}]{health_status.upper()}[/]",
        title="Health Check",
        border_style=status_color
    ))

    health_table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
    health_table.add_column("Check", style="white")
    health_table.add_column("Status", style="bold")
    health_table.add_column("Detail", style="grey50")

    for check_name, check_value in checks.items():
        if isinstance(check_value, bool):
            status_str = "[green]PASS[/green]" if check_value else "[red]FAIL[/red]"
            detail = str(check_value)
        else:
            status_str = "[yellow]INFO[/yellow]"
            detail = str(check_value)
        health_table.add_row(check_name.replace("_", " ").title(), status_str, detail)

    health_table.add_row("Overall Status", f"[{status_color}]{health_status.upper()}[/{status_color}]", "")
    console.print(health_table)

    if verbose:
        console.print()
        console.print(Panel(
            f"Total Evaluations: {stats['total_evaluations']}\n"
            f"Successful: {stats['successful_evaluations']}\n"
            f"Failed: {stats['failed_evaluations']}\n"
            f"Violations: {stats['violations_detected']}\n"
            f"Cache: {stats.get('cache_hits', 0)}H / {stats.get('cache_misses', 0)}M\n"
            f"Uptime: {stats.get('uptime_seconds', 0):.0f}s\n"
            f"Avg Processing: {stats['average_time_ms']:.2f}ms",
            title="Detailed Health Info",
            border_style="cyan"
        ))


@app.command()
def shell(
    history_file: Optional[Path] = typer.Option(None, "--history", help="History file path"),
    persistent: bool = typer.Option(True, "--persistent/--no-persistent", help="Enable session persistence"),
):
    """Start an interactive REPL shell for the rule engine."""
    from .interactive_shell import InteractiveShell
    shell = InteractiveShell(
        engine=get_engine(),
        console=console,
        history_file=history_file,
        persistent=persistent,
    )
    shell.run()


@app.command()
def version():
    """Show version information."""
    console.print(Panel(
        "[bold]Rules-Emerging-Pattern CLI[/bold]\n"
        "Version: 1.0.0\n"
        "Python: " + sys.version.split()[0] + "\n"
        "Engine: Tiered Rule Engine\n"
        "Tiers: Safety, Operational, Preference",
        title="Version Info",
        border_style="blue"
    ))


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress non-essential output"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Rules-Emerging-Pattern CLI - Tiered rule evaluation engine."""
    if verbose and quiet:
        console.print("[red]Error: Cannot use both --verbose and --quiet[/red]")
        sys.exit(1)

    if config_file:
        loaded_config = load_config_file(config_file)
        if loaded_config:
            logger = logging.getLogger(__name__)
            logger.info(f"Loaded config from {config_file}")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
