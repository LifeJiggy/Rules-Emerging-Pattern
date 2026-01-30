"""Command Line Interface for Rules-Emerging-Pattern."""
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from rules_emerging_pattern.core.rule_engine import RuleEngine
from rules_emerging_pattern.rule_engines.base.rule_manager import RuleManager
from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleEvaluationRequest

app = typer.Typer(help="Rules-Emerging-Pattern CLI")
console = Console()


def get_engine():
    """Get or initialize rule engine."""
    rule_manager = RuleManager()
    return RuleEngine(rule_manager=rule_manager)


@app.command()
def validate(
    content: str = typer.Option(..., "--content", "-c", help="Content to validate"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Rule tier (safety, operational, preference)"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON")
):
    """Validate content against rules."""
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
    
    result = asyncio.run(engine.evaluate(request))
    
    if output_json:
        console.print(json.dumps(result.dict(), indent=2, default=str))
    else:
        console.print(Panel(f"Validation Result", title="Rules Engine", border_style="blue"))
        console.print(f"Valid: {'[green]Yes[/green]' if result.valid else '[red]No[/red]'}")
        console.print(f"Score: {result.total_score:.2f}")
        console.print(f"Violations: {len(result.violations)}")
        
        if result.violations:
            table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
            table.add_column("Rule", style="cyan")
            table.add_column("Tier", style="green")
            table.add_column("Severity", style="yellow")
            table.add_column("Action", style="red")
            
            for violation in result.violations:
                table.add_row(
                    violation.rule_name,
                    violation.rule_tier.value,
                    violation.rule_severity.value,
                    violation.action_taken.value
                )
            console.print(table)


@app.command()
def add_rule(
    name: str = typer.Option(..., "--name", "-n", help="Rule name"),
    tier: str = typer.Option(..., "--tier", "-t", help="Rule tier"),
    pattern: str = typer.Option(..., "--pattern", "-p", help="Pattern to match"),
    enforcement: str = typer.Option("advisory", "--enforcement", "-e", help="Enforcement level")
):
    """Add a new rule."""
    console.print(f"[green]Adding rule: {name}[/green]")
    console.print(f"  Tier: {tier}")
    console.print(f"  Pattern: {pattern}")
    console.print(f"  Enforcement: {enforcement}")
    console.print("[yellow]Note: Rule persistence not implemented in this demo[/yellow]")


@app.command()
def list_rules(
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Filter by tier"),
    active_only: bool = typer.Option(True, "--active/--all", help="Show only active rules")
):
    """List all rules."""
    engine = get_engine()
    
    if not engine.rule_manager:
        console.print("[red]Error: Rule manager not initialized[/red]")
        sys.exit(1)
    
    if tier:
        try:
            tier_enum = RuleTier(tier)
            rules = engine.rule_manager.get_rules_by_tier(tier_enum)
        except ValueError:
            console.print(f"[red]Error: Invalid tier '{tier}'[/red]")
            sys.exit(1)
    else:
        rules = list(engine.rule_manager.rules.values())
    
    if active_only:
        from rules_emerging_pattern.models.rule import RuleStatus
        rules = [r for r in rules if r.status == RuleStatus.ACTIVE]
    
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Tier", style="yellow")
    table.add_column("Type", style="blue")
    table.add_column("Status", style="red")
    
    for rule in rules:
        table.add_row(
            rule.id,
            rule.name,
            rule.tier.value,
            rule.rule_type.value,
            rule.status.value
        )
    
    console.print(Panel(f"Total Rules: {len(rules)}", title="Rules List", border_style="blue"))
    console.print(table)


@app.command()
def metrics():
    """Show system metrics."""
    engine = get_engine()
    stats = engine.get_statistics()
    
    console.print(Panel("System Metrics", title="Rules Engine", border_style="green"))
    
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="yellow")
    
    for key, value in stats.items():
        table.add_row(key.replace("_", " ").title(), str(value))
    
    console.print(table)


@app.command()
def monitor(
    interval: int = typer.Option(60, "--interval", "-i", help="Monitoring interval in seconds"),
    duration: int = typer.Option(300, "--duration", "-d", help="Monitoring duration in seconds")
):
    """Monitor system in real-time."""
    console.print(f"[blue]Monitoring for {duration} seconds (interval: {interval}s)...[/blue]")
    console.print("[yellow]Press Ctrl+C to stop[/yellow]")
    
    engine = get_engine()
    
    try:
        import time
        start_time = time.time()
        
        while time.time() - start_time < duration:
            stats = engine.get_statistics()
            console.print(f"[green]Evaluations: {stats['total_evaluations']} | "
                         f"Violations: {stats['violations_detected']} | "
                         f"Avg Time: {stats['average_time_ms']:.2f}ms[/green]")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped[/yellow]")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
