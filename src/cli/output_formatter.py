"""Output formatting utilities for CLI output."""
import csv
import io
import json
import logging
import textwrap
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from typing import List, Optional, Dict, Any

from rich import box
from rich.console import Console, ConsoleOptions, RenderResult, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleStatus, RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class OutputFormat(str, Enum):
    """Supported output formats."""
    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    HTML = "html"
    TEXT = "text"
    TREE = "tree"


class ColorTheme:
    """Color theme for output formatting."""

    THEMES = {
        "default": {
            "valid": "green",
            "invalid": "red",
            "warning": "yellow",
            "info": "blue",
            "critical": "red bold",
            "high": "magenta",
            "medium": "yellow",
            "low": "cyan",
            "header": "bold magenta",
            "subheader": "bold cyan",
            "key": "cyan",
            "value": "white",
            "border": "blue",
            "success": "green",
            "error": "red bold",
            "muted": "grey50",
            "accent": "green",
        },
        "dark": {
            "valid": "green",
            "invalid": "red",
            "warning": "yellow",
            "info": "bright_blue",
            "critical": "bright_red bold",
            "high": "bright_magenta",
            "medium": "bright_yellow",
            "low": "bright_cyan",
            "header": "bold bright_magenta",
            "subheader": "bold bright_cyan",
            "key": "bright_cyan",
            "value": "white",
            "border": "bright_blue",
            "success": "bright_green",
            "error": "bright_red bold",
            "muted": "grey50",
            "accent": "bright_green",
        },
        "minimal": {
            "valid": "green",
            "invalid": "red",
            "warning": "yellow",
            "info": "",
            "critical": "red bold",
            "high": "magenta",
            "medium": "yellow",
            "low": "cyan",
            "header": "bold",
            "subheader": "bold",
            "key": "",
            "value": "",
            "border": "",
            "success": "green",
            "error": "red bold",
            "muted": "grey50",
            "accent": "green",
        },
    }

    def __init__(self, theme_name: str = "default"):
        self.name = theme_name
        self.colors = self.THEMES.get(theme_name, self.THEMES["default"])

    def get(self, key: str) -> str:
        return self.colors.get(key, "")

    def style(self, key: str) -> str:
        return self.colors.get(key, "")


class OutputFormatter:
    """Formats validation results and other data for CLI output."""

    def __init__(
        self,
        console: Optional[Console] = None,
        theme: str = "default",
        verbose: bool = False,
        quiet: bool = False,
        color_enabled: bool = True,
    ):
        self.console = console or Console()
        self.theme = ColorTheme(theme)
        self.verbose = verbose
        self.quiet = quiet
        self.color_enabled = color_enabled

    def set_theme(self, theme_name: str) -> None:
        self.theme = ColorTheme(theme_name)

    def set_verbose(self, verbose: bool) -> None:
        self.verbose = verbose

    def set_quiet(self, quiet: bool) -> None:
        self.quiet = quiet

    def c(self, key: str) -> str:
        return self.theme.style(key)

    def print_result(self, result: ValidationResult, title: str = "Validation Result") -> None:
        self.console.print()
        self.console.print(Panel(
            f"Valid: {'[green]Yes[/green]' if result.valid else '[red]No[/red]'}\n"
            f"Score: [yellow]{result.total_score:.3f}[/yellow]\n"
            f"Confidence: [cyan]{result.confidence:.1%}[/cyan]\n"
            f"Processing Time: [magenta]{result.processing_time_ms}ms[/magenta]\n"
            f"Violations: [red]{len(result.violations)}[/red]\n"
            f"Suggestions: [blue]{len(result.suggestions)}[/blue]",
            title=title,
            border_style=self.c("border")
        ))

        if result.violations:
            self.console.print()
            self._print_violations_table(result.violations)

        if result.suggestions:
            self.console.print()
            self._print_suggestions_table(result.suggestions)

    def print_verbose_result(self, result: ValidationResult, title: str = "Validation Result") -> None:
        self.print_result(result, title)
        self.console.print()

        score_breakdown = result.get_score_breakdown()
        breakdown_table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        breakdown_table.add_column("Component", style=self.c("key"))
        breakdown_table.add_column("Value", style=self.c("value"))

        for key, value in score_breakdown.items():
            breakdown_table.add_row(key.replace("_", " ").title(), f"{value:.3f}")

        self.console.print(Panel(breakdown_table, title="Score Breakdown", border_style=self.c("border")))

        if result.processing_details:
            self.console.print()
            details_table = Table(show_header=True, header_style=self.c("subheader"), box=box.SIMPLE)
            details_table.add_column("Detail", style=self.c("key"))
            details_table.add_column("Value", style=self.c("value"))
            for key, value in result.processing_details.items():
                details_table.add_row(key, str(value))
            self.console.print(Panel(details_table, title="Processing Details", border_style=self.c("border")))

        violations_by_tier = result.get_violations_by_tier()
        if violations_by_tier:
            self.console.print()
            tier_table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
            tier_table.add_column("Tier", style=self.c("key"))
            tier_table.add_column("Violations", style=self.c("value"))
            tier_colors = {"safety": "red", "operational": "yellow", "preference": "blue"}
            for tier_name, violations in violations_by_tier.items():
                color = tier_colors.get(tier_name, "white")
                tier_table.add_row(f"[{color}]{tier_name}[/{color}]", str(len(violations)))
            self.console.print(Panel(tier_table, title="Violations by Tier", border_style=self.c("border")))

        if result.warnings:
            self.console.print()
            warn_table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
            warn_table.add_column("Rule", style=self.c("key"))
            warn_table.add_column("Type", style=self.c("value"))
            warn_table.add_column("Explanation", style=self.c("muted"))
            for w in result.warnings:
                warn_table.add_row(w.rule_name, w.violation_type.value, (w.explanation or "")[:80])
            self.console.print(Panel(warn_table, title="Warnings", border_style=self.c("warning")))

    def format_result(self, result: ValidationResult) -> str:
        lines = []
        lines.append(f"Valid: {result.valid}")
        lines.append(f"Score: {result.total_score:.3f}")
        lines.append(f"Confidence: {result.confidence:.1%}")
        lines.append(f"Processing Time: {result.processing_time_ms}ms")
        lines.append(f"Violations: {len(result.violations)}")
        lines.append(f"Suggestions: {len(result.suggestions)}")
        if result.violations:
            lines.append("")
            lines.append("Violations:")
            for v in result.violations:
                lines.append(f"  - [{v.rule_severity}] {v.rule_name}: {v.explanation or ''}")
        if result.suggestions:
            lines.append("")
            lines.append("Suggestions:")
            for s in result.suggestions:
                lines.append(f"  - [{s.type}] {s.title}: {s.description[:80]}")
        return "\n".join(lines)

    def format_verbose_result(self, result: ValidationResult) -> str:
        lines = [self.format_result(result)]
        score_breakdown = result.get_score_breakdown()
        lines.append("")
        lines.append("Score Breakdown:")
        for key, value in score_breakdown.items():
            lines.append(f"  {key}: {value:.3f}")
        if result.processing_details:
            lines.append("")
            lines.append("Processing Details:")
            for key, value in result.processing_details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def _print_violations_table(self, violations: List[Violation]) -> None:
        table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        table.add_column("Rule", style=self.c("key"))
        table.add_column("Tier", style="green")
        table.add_column("Severity", style=self.c("value"))
        table.add_column("Type", style="blue")
        table.add_column("Action", style="magenta")
        table.add_column("Explanation", style=self.c("muted"))

        sev_colors = {
            "critical": "red bold",
            "high": "magenta",
            "medium": "yellow",
            "low": "cyan",
        }

        for v in violations:
            severity_str = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
            color = sev_colors.get(severity_str, "white")
            table.add_row(
                v.rule_name[:30],
                v.rule_tier.value if hasattr(v.rule_tier, "value") else str(v.rule_tier),
                f"[{color}]{severity_str}[/{color}]",
                v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type),
                v.action_taken.value if hasattr(v.action_taken, "value") else str(v.action_taken),
                (v.explanation or "")[:60],
            )
        self.console.print(Panel(table, title="Violations", border_style=self.c("invalid")))

    def _print_suggestions_table(self, suggestions: List["Any"]) -> None:
        table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        table.add_column("Type", style="blue")
        table.add_column("Title", style=self.c("key"))
        table.add_column("Confidence", style=self.c("value"))
        table.add_column("Auto-apply", style="green")
        table.add_column("Description", style=self.c("muted"))

        for s in suggestions:
            table.add_row(
                s.type,
                s.title[:40],
                f"{s.confidence:.0%}",
                "[green]Yes[/green]" if s.auto_applicable else "[red]No[/red]",
                s.description[:80],
            )
        self.console.print(Panel(table, title="Suggestions", border_style=self.c("info")))

    def print_violation_tree(self, violations: List[Violation]) -> None:
        tree = Tree("[bold]Violations[/bold]", style=self.c("key"))

        by_severity: Dict[str, List[Violation]] = {}
        for v in violations:
            sev = v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity)
            if sev not in by_severity:
                by_severity[sev] = []
            by_severity[sev].append(v)

        sev_order = ["critical", "high", "medium", "low"]
        sev_colors = {"critical": "red", "high": "magenta", "medium": "yellow", "low": "cyan"}

        for sev in sev_order:
            if sev in by_severity:
                color = sev_colors.get(sev, "white")
                sev_node = tree.add(f"[{color}]{sev.upper()} ({len(by_severity[sev])})[/{color}]")
                for v in by_severity[sev]:
                    sev_node.add(f"[bold]{v.rule_name}[/bold] - {(v.explanation or '')[:50]}")

        self.console.print(tree)

    def format_violations_as_csv(self, violations: List[Violation]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Rule ID", "Rule Name", "Tier", "Severity", "Type", "Action", "Explanation", "Confidence"])
        for v in violations:
            writer.writerow([
                v.rule_id,
                v.rule_name,
                v.rule_tier.value if hasattr(v.rule_tier, "value") else str(v.rule_tier),
                v.rule_severity.value if hasattr(v.rule_severity, "value") else str(v.rule_severity),
                v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type),
                v.action_taken.value if hasattr(v.action_taken, "value") else str(v.action_taken),
                v.explanation or "",
                v.confidence_score,
            ])
        return output.getvalue()

    def format_violations_as_json(self, violations: List[Violation]) -> str:
        return json.dumps([v.dict() for v in violations], indent=2, default=str)

    def format_violations_as_html(self, violations: List[Violation]) -> str:
        rows = []
        for v in violations:
            rows.append(f"""<tr>
                <td>{v.rule_id}</td>
                <td>{v.rule_name}</td>
                <td>{v.rule_tier.value if hasattr(v.rule_tier, 'value') else str(v.rule_tier)}</td>
                <td>{v.rule_severity.value if hasattr(v.rule_severity, 'value') else str(v.rule_severity)}</td>
                <td>{v.violation_type.value if hasattr(v.violation_type, 'value') else str(v.violation_type)}</td>
                <td>{v.action_taken.value if hasattr(v.action_taken, 'value') else str(v.action_taken)}</td>
                <td>{v.explanation or ''}</td>
            </tr>""")
        return f"""<html><head><title>Violations Report</title>
        <style>table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; }}</style></head>
        <body><h2>Violations Report</h2><table>
        <tr><th>ID</th><th>Name</th><th>Tier</th><th>Severity</th><th>Type</th><th>Action</th><th>Explanation</th></tr>
        {''.join(rows)}
        </table><p>Generated: {datetime.utcnow().isoformat()}</p></body></html>"""

    def print_summary_panel(self, title: str, items: Dict[str, Any], border_style: str = "blue") -> None:
        content = "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in items.items())
        self.console.print(Panel(content, title=title, border_style=border_style))

    def print_key_value_table(self, title: str, data: Dict[str, Any], border_style: str = "blue") -> None:
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Key", style=self.c("key"))
        table.add_column("Value", style=self.c("value"))
        for key, value in data.items():
            table.add_row(str(key).replace("_", " ").title(), str(value))
        self.console.print(Panel(table, title=title, border_style=border_style))

    def format_rules_as_csv(self, rules: List[Rule]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Name", "Description", "Tier", "Type", "Severity", "Status", "Enforcement", "Version"])
        for r in rules:
            writer.writerow([
                r.id,
                r.name,
                r.description,
                r.tier.value if hasattr(r.tier, "value") else str(r.tier),
                r.rule_type.value if hasattr(r.rule_type, "value") else str(r.rule_type),
                r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                r.status.value if hasattr(r.status, "value") else str(r.status),
                r.enforcement_level.value if hasattr(r.enforcement_level, "value") else str(r.enforcement_level),
                r.version,
            ])
        return output.getvalue()

    def format_rules_as_text(self, rules: List[Rule]) -> str:
        lines = [f"Rules ({len(rules)}):", "=" * 60]
        for r in rules:
            lines.append(f"  ID: {r.id}")
            lines.append(f"  Name: {r.name}")
            lines.append(f"  Tier: {r.tier.value if hasattr(r.tier, 'value') else str(r.tier)}")
            lines.append(f"  Severity: {r.severity.value if hasattr(r.severity, 'value') else str(r.severity)}")
            lines.append(f"  Status: {r.status.value if hasattr(r.status, 'value') else str(r.status)}")
            lines.append(f"  Enforcement: {r.enforcement_level.value if hasattr(r.enforcement_level, 'value') else str(r.enforcement_level)}")
            lines.append("")
        return "\n".join(lines)

    def format_rules_as_html(self, rules: List[Rule]) -> str:
        rows = []
        for r in rules:
            rows.append(f"""<tr>
                <td>{r.id[:12]}</td>
                <td>{r.name}</td>
                <td>{r.tier.value if hasattr(r.tier, 'value') else str(r.tier)}</td>
                <td>{r.rule_type.value if hasattr(r.rule_type, 'value') else str(r.rule_type)}</td>
                <td>{r.severity.value if hasattr(r.severity, 'value') else str(r.severity)}</td>
                <td>{r.status.value if hasattr(r.status, 'value') else str(r.status)}</td>
                <td>{r.enforcement_level.value if hasattr(r.enforcement_level, 'value') else str(r.enforcement_level)}</td>
            </tr>""")
        return f"""<html><head><title>Rules Export</title>
        <style>table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #2196F3; color: white; }}</style></head>
        <body><h2>Rules Export ({len(rules)} rules)</h2><table>
        <tr><th>ID</th><th>Name</th><th>Tier</th><th>Type</th><th>Severity</th><th>Status</th><th>Enforcement</th></tr>
        {''.join(rows)}
        </table><p>Generated: {datetime.utcnow().isoformat()}</p></body></html>"""

    def format_dict_as_csv(self, data: Dict[str, Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Key", "Value"])
        for key, value in data.items():
            writer.writerow([str(key), str(value)[:200]])
        return output.getvalue()

    def format_dict_as_text(self, data: Dict[str, Any]) -> str:
        lines = []
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for sub_key, sub_value in value.items():
                    lines.append(f"  {sub_key}: {sub_value}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def format_dict_as_html(self, data: Dict[str, Any], title: str = "Data Export") -> str:
        rows = []
        for key, value in data.items():
            if isinstance(value, dict):
                rows.append(f"<tr><td colspan='2' style='font-weight:bold'>{key}</td></tr>")
                for sub_key, sub_value in value.items():
                    rows.append(f"<tr><td style='padding-left:20px'>{sub_key}</td><td>{sub_value}</td></tr>")
            else:
                rows.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        return f"""<html><head><title>{title}</title>
        <style>table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 6px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #555; color: white; }}</style></head>
        <body><h2>{title}</h2><table>
        <tr><th>Key</th><th>Value</th></tr>
        {''.join(rows)}
        </table><p>Generated: {datetime.utcnow().isoformat()}</p></body></html>"""

    def format_table_to_text(self, table: Table) -> str:
        with io.StringIO() as buf:
            console = Console(file=buf, width=120)
            console.print(table)
            return buf.getvalue()

    def print_error(self, message: str) -> None:
        if not self.quiet:
            self.console.print(f"[{self.c('error')}]Error: {message}[/{self.c('error')}]")

    def print_warning(self, message: str) -> None:
        if not self.quiet:
            self.console.print(f"[{self.c('warning')}]Warning: {message}[/{self.c('warning')}]")

    def print_info(self, message: str) -> None:
        if not self.quiet:
            self.console.print(f"[{self.c('info')}]{message}[/{self.c('info')}]")

    def print_success(self, message: str) -> None:
        if not self.quiet:
            self.console.print(f"[{self.c('success')}]{message}[/{self.c('success')}]")

    def print_data_table(self, title: str, columns: List[str], rows: List[List[str]], border_style: str = "blue") -> None:
        table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*row)
        self.console.print(Panel(table, title=title, border_style=border_style))

    def print_json(self, data: Any, title: Optional[str] = None) -> None:
        json_str = json.dumps(data, indent=2, default=str)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
        if title:
            self.console.print(Panel(syntax, title=title, border_style=self.c("border")))
        else:
            self.console.print(syntax)

    def print_section_header(self, title: str, style: str = "bold blue") -> None:
        width = min(self.console.width or 80, 80)
        self.console.print()
        self.console.print(Text(f" {'=' * (width - 2)} ", style=style))
        self.console.print(Text(f" {title.center(width - 2)} ", style=style))
        self.console.print(Text(f" {'=' * (width - 2)} ", style=style))
        self.console.print()

    def format_validation_summary(self, result: ValidationResult) -> str:
        lines = [
            f"Valid: {result.valid}",
            f"Score: {result.total_score:.3f}",
            f"Violations: {len(result.violations)}",
            f"Suggestions: {len(result.suggestions)}",
            f"Processing: {result.processing_time_ms}ms",
        ]
        if result.violations:
            lines.append("")
            lines.append("Violation Summary:")
            by_severity = result.get_violations_by_severity()
            for sev in ["critical", "high", "medium", "low"]:
                if sev in by_severity:
                    lines.append(f"  {sev}: {len(by_severity[sev])}")
        return "\n".join(lines)

    def format_metrics_prometheus(self, stats: Dict[str, Any]) -> str:
        lines = [
            "# HELP rule_engine_cli_metrics CLI exported metrics",
            "# TYPE rule_engine_cli_metrics gauge",
        ]
        for key, value in stats.items():
            if isinstance(value, (int, float)):
                safe_key = key.replace(" ", "_").replace(".", "_").lower()
                lines.append(f"rule_engine_{safe_key} {value}")
        return "\n".join(lines)

    def render_batch_progress(self, current: int, total: int, errors: int) -> str:
        pct = (current / total * 100) if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        return f"[{bar}] {current}/{total} ({pct:.0f}%) errors={errors}"

    def print_batch_summary(self, result: "Any") -> None:
        summary = result.get_summary()
        self.console.print()
        self.console.print(Panel(
            f"[bold]Batch Processing Summary[/bold]\n\n"
            f"Total Items: {summary['total_items']}\n"
            f"[green]Valid: {summary['valid_items']}[/green]\n"
            f"[red]With Violations: {summary['items_with_violations']}[/red]\n"
            f"[magenta]Blocked: {summary['blocked_items']}[/magenta]\n"
            f"Success Rate: [bold]{summary['success_rate']}%[/bold]\n"
            f"Violation Rate: {summary['violation_rate']}%\n"
            f"Total Violations: {summary['total_violations']}\n"
            f"Total Suggestions: {summary['total_suggestions']}\n"
            f"Total Time: {summary['total_processing_time_ms']}ms\n"
            f"Avg Time: {summary['avg_processing_time_ms']}ms",
            title="Batch Results",
            border_style=self.c("border")
        ))

    def export_to_file(self, data: Any, filepath: Path, fmt: str = "json") -> bool:
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            if fmt == "json":
                content = json.dumps(data, indent=2, default=str)
            elif fmt == "csv":
                if isinstance(data, list) and data and hasattr(data[0], "dict"):
                    content = self.format_rules_as_csv(data)
                else:
                    content = self.format_dict_as_csv(data)
            elif fmt == "html":
                if isinstance(data, dict):
                    content = self.format_dict_as_html(data)
                else:
                    content = f"<pre>{json.dumps(data, indent=2, default=str)}</pre>"
            elif fmt == "txt":
                if isinstance(data, dict):
                    content = self.format_dict_as_text(data)
                else:
                    content = str(data)
            elif fmt == "prometheus":
                content = self.format_metrics_prometheus(data if isinstance(data, dict) else {})
            else:
                content = str(data)
            filepath.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def print_config_table(self, config: Dict[str, Any], title: str = "Configuration") -> None:
        table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        table.add_column("Section", style=self.c("key"))
        table.add_column("Key", style="green")
        table.add_column("Value", style=self.c("value"))
        for section, values in config.items():
            if isinstance(values, dict):
                first = True
                for key, value in values.items():
                    section_display = section if first else ""
                    table.add_row(section_display, key, str(value)[:80])
                    first = False
            else:
                table.add_row("", section, str(values)[:80])
        self.console.print(Panel(table, title=title, border_style=self.c("border")))

    def print_rule_details(self, rule: "Rule") -> None:
        self.console.print(Panel(
            f"ID: {rule.id}\n"
            f"Name: {rule.name}\n"
            f"Description: {rule.description}\n"
            f"Tier: {rule.tier.value if hasattr(rule.tier, 'value') else str(rule.tier)}\n"
            f"Type: {rule.rule_type.value if hasattr(rule.rule_type, 'value') else str(rule.rule_type)}\n"
            f"Severity: {rule.severity.value if hasattr(rule.severity, 'value') else str(rule.severity)}\n"
            f"Status: {rule.status.value if hasattr(rule.status, 'value') else str(rule.status)}\n"
            f"Enforcement: {rule.enforcement_level.value if hasattr(rule.enforcement_level, 'value') else str(rule.enforcement_level)}\n"
            f"Version: {rule.version}\n"
            f"Patterns: {len(rule.patterns)}\n"
            f"Tags: {', '.join(rule.tags) if rule.tags else 'none'}\n"
            f"Created: {rule.created_at.isoformat() if hasattr(rule.created_at, 'isoformat') else rule.created_at}",
            title=f"Rule: {rule.name}",
            border_style=self.c("border")
        ))

    def print_health_report(self, checks: Dict[str, Any], healthy: bool) -> None:
        color = "green" if healthy else "yellow"
        table = Table(show_header=True, header_style=self.c("subheader"), box=box.ROUNDED)
        table.add_column("Check", style=self.c("key"))
        table.add_column("Status", style="bold")
        table.add_column("Detail", style=self.c("muted"))
        for name, result in checks.items():
            if isinstance(result, bool):
                status = f"[{'green' if result else 'red'}]{'PASS' if result else 'FAIL'}[/]"
            else:
                status = f"[yellow]INFO[/]"
            table.add_row(name.replace("_", " ").title(), status, str(result))
        self.console.print(Panel(table, title=f"Health Check - {'[green]HEALTHY[/]' if healthy else '[yellow]DEGRADED[/]'}",
                                border_style=color))

    def print_progress_bar(self, current: int, total: int, label: str = "Progress", width: int = 40) -> None:
        if total <= 0:
            return
        pct = current / total
        filled = int(width * pct)
        bar = "█" * filled + "░" * (width - filled)
        self.console.print(f"{label}: [{self.c('accent')}]{bar}[/] {current}/{total} ({pct:.0%})")

    def format_violation_count_by_type(self, violations: List[Violation]) -> str:
        counts: Dict[str, int] = {}
        for v in violations:
            vtype = v.violation_type.value if hasattr(v.violation_type, "value") else str(v.violation_type)
            counts[vtype] = counts.get(vtype, 0) + 1
        return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))

    def print_separator(self, char: str = "=", width: Optional[int] = None) -> None:
        w = width or (self.console.width or 80)
        self.console.print(char * w)

    def print_timestamped(self, message: str, style: str = "white") -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        self.console.print(f"[{self.c('muted')}]{ts}[/{self.c('muted')}] [{style}]{message}[/{style}]")
