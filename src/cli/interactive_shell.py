"""Interactive REPL shell for the rules engine."""
import asyncio
import cmd
import json
import logging
import os
import readline
import shlex
import sys
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
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RuleStatus, RulePattern, RuleContext, RuleEvaluationRequest, EnforcementLevel
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.core.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


@dataclass
class ShellCommand:
    """Definition of a shell command."""
    name: str
    aliases: List[str]
    description: str
    usage: str
    handler: Callable
    min_args: int = 0
    category: str = "general"


class ShellCategory(str, Enum):
    """Categories for shell commands."""
    EVALUATION = "evaluation"
    CONFIGURATION = "configuration"
    RULES = "rules"
    SYSTEM = "system"
    HELP = "help"
    HISTORY = "history"
    OUTPUT = "output"


class InteractiveShell:
    """Interactive REPL shell for the rules engine with rich features."""

    def __init__(
        self,
        engine: Optional[RuleEngine] = None,
        console: Optional[Console] = None,
        history_file: Optional[Path] = None,
        persistent: bool = True,
        prompt: str = "rules> ",
        welcome_message: Optional[str] = None,
    ):
        self.engine = engine
        self.console = console or Console()
        self.history_file = history_file or Path.home() / ".rules-emerging-pattern" / "shell_history.txt"
        self.persistent = persistent
        self.prompt = prompt
        self.welcome_message = welcome_message or self._default_welcome()
        self.running = True
        self.context: Dict[str, Any] = {}
        self.commands: List[ShellCommand] = []
        self.aliases: Dict[str, str] = {}
        self.history: List[str] = []
        self.history_max_size: int = 1000
        self.multi_line_buffer: List[str] = []
        self.multi_line_mode: bool = False
        self.output_format: str = "table"
        self.last_result: Optional[Any] = None
        self.variables: Dict[str, Any] = {}
        self.session_start: datetime = datetime.utcnow()
        self.command_count: int = 0
        self.error_count: int = 0
        self._tab_completion_items: List[str] = []
        self._initialize_commands()

    def _default_welcome(self) -> str:
        return (
            "Rules-Emerging-Pattern Interactive Shell\n"
            "Type 'help' for available commands, 'exit' to quit.\n"
            "Tab-completion and command history are enabled."
        )

    def _initialize_commands(self) -> None:
        eval_cmds = [
            ShellCommand("evaluate", ["eval", "e"], "Evaluate content against rules",
                        "evaluate <content> [--tier <tier>] [--json]",
                        self._cmd_evaluate, 1, ShellCategory.EVALUATION),
            ShellCommand("validate", ["val", "v"], "Validate content (alias for evaluate)",
                        "validate <content> [options]",
                        self._cmd_evaluate, 1, ShellCategory.EVALUATION),
            ShellCommand("batch", ["b"], "Batch evaluate from file",
                        "batch <filepath> [--tier <tier>] [--format <fmt>]",
                        self._cmd_batch, 1, ShellCategory.EVALUATION),
            ShellCommand("check", ["chk"], "Quick check content validity",
                        "check <content>",
                        self._cmd_check, 1, ShellCategory.EVALUATION),
        ]
        config_cmds = [
            ShellCommand("config", ["cfg", "c"], "View or set configuration",
                        "config [--key <key>] [--value <value>]",
                        self._cmd_config, 0, ShellCategory.CONFIGURATION),
            ShellCommand("set", [], "Set a configuration value",
                        "set <key> <value>",
                        self._cmd_set, 2, ShellCategory.CONFIGURATION),
            ShellCommand("get", [], "Get a configuration value",
                        "get <key>",
                        self._cmd_get, 1, ShellCategory.CONFIGURATION),
            ShellCommand("reset", [], "Reset configuration to defaults",
                        "reset",
                        self._cmd_reset, 0, ShellCategory.CONFIGURATION),
        ]
        rules_cmds = [
            ShellCommand("rules", ["ls", "list"], "List all rules",
                        "rules [--tier <tier>] [--active]",
                        self._cmd_rules, 0, ShellCategory.RULES),
            ShellCommand("add-rule", ["add", "ar"], "Add a new rule",
                        "add-rule <name> <tier> <pattern> [--enforcement <level>]",
                        self._cmd_add_rule, 3, ShellCategory.RULES),
            ShellCommand("rule-info", ["ri", "info"], "Show rule details",
                        "rule-info <rule_id>",
                        self._cmd_rule_info, 1, ShellCategory.RULES),
            ShellCommand("search-rules", ["search", "sr"], "Search rules by name or description",
                        "search-rules <query>",
                        self._cmd_search_rules, 1, ShellCategory.RULES),
        ]
        system_cmds = [
            ShellCommand("metrics", ["stats", "m"], "Show system metrics",
                        "metrics [--json]",
                        self._cmd_metrics, 0, ShellCategory.SYSTEM),
            ShellCommand("health", ["h"], "System health check",
                        "health",
                        self._cmd_health, 0, ShellCategory.SYSTEM),
            ShellCommand("monitor", ["mon"], "Start real-time monitoring",
                        "monitor [--interval <sec>] [--duration <sec>]",
                        self._cmd_monitor, 0, ShellCategory.SYSTEM),
            ShellCommand("version", ["ver"], "Show version information",
                        "version",
                        self._cmd_version, 0, ShellCategory.SYSTEM),
            ShellCommand("engine", ["eng"], "Show engine status",
                        "engine",
                        self._cmd_engine, 0, ShellCategory.SYSTEM),
        ]
        history_cmds = [
            ShellCommand("history", ["hist", "h"], "Show command history",
                        "history [--clear] [--search <query>]",
                        self._cmd_history, 0, ShellCategory.HISTORY),
            ShellCommand("repeat", ["r"], "Repeat a previous command by number",
                        "repeat <number>",
                        self._cmd_repeat, 1, ShellCategory.HISTORY),
        ]
        output_cmds = [
            ShellCommand("format", ["fmt"], "Set output format (table, json, text)",
                        "format <table|json|text>",
                        self._cmd_format, 1, ShellCategory.OUTPUT),
            ShellCommand("export", ["exp"], "Export last result to file",
                        "export <filepath> [--format <fmt>]",
                        self._cmd_export, 1, ShellCategory.OUTPUT),
            ShellCommand("print", ["p"], "Print a variable or last result",
                        "print [<variable>]",
                        self._cmd_print, 0, ShellCategory.OUTPUT),
            ShellCommand("clear", ["cls"], "Clear the screen",
                        "clear",
                        self._cmd_clear, 0, ShellCategory.OUTPUT),
        ]
        help_cmds = [
            ShellCommand("help", ["?", "h"], "Show this help message",
                        "help [command]",
                        self._cmd_help, 0, ShellCategory.HELP),
            ShellCommand("exit", ["quit", "q"], "Exit the shell",
                        "exit",
                        self._cmd_exit, 0, ShellCategory.HELP),
            ShellCommand("echo", [], "Print arguments",
                        "echo <text>",
                        self._cmd_echo, 1, ShellCategory.HELP),
        ]
        all_cmds = eval_cmds + config_cmds + rules_cmds + system_cmds + history_cmds + output_cmds + help_cmds
        self.commands = all_cmds
        for cmd_def in all_cmds:
            for alias in cmd_def.aliases:
                self.aliases[alias] = cmd_def.name
        self._update_completions()

    def _update_completions(self) -> None:
        items = set()
        for cmd_def in self.commands:
            items.add(cmd_def.name)
            items.update(cmd_def.aliases)
        items.update(["--tier", "--json", "--format", "--key", "--value",
                      "--interval", "--duration", "--clear", "--search",
                      "--enforcement", "--active", "--all", "--output", "--help"])
        items.update(["safety", "operational", "preference", "table", "json", "text", "csv"])
        self._tab_completion_items = sorted(items)

    def run(self) -> None:
        """Run the interactive shell main loop."""
        self._setup_history()
        self._print_welcome()
        self._setup_readline()

        while self.running:
            try:
                line = self._read_line()
                if line is None:
                    continue
                if not line.strip():
                    continue
                self._add_to_history(line)
                self.command_count += 1
                self._execute_line(line)
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrupted[/yellow]")
                continue
            except EOFError:
                self.console.print("\n[yellow]Exiting...[/yellow]")
                self.running = False
                break
            except Exception as e:
                self.error_count += 1
                self.console.print(f"[red]Error: {e}[/red]")
                if self._is_verbose():
                    traceback.print_exc()

        self._on_exit()

    def _setup_history(self) -> None:
        if self.persistent and self.history_file:
            try:
                self.history_file.parent.mkdir(parents=True, exist_ok=True)
                if self.history_file.exists():
                    with open(str(self.history_file), "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.rstrip("\n")
                            if line:
                                self.history.append(line)
                    readline.set_history_length(self.history_max_size)
                    for line in self.history:
                        readline.add_history(line)
            except Exception as e:
                logger.debug(f"Could not load history: {e}")

    def _save_history(self) -> None:
        if self.persistent and self.history_file:
            try:
                self.history_file.parent.mkdir(parents=True, exist_ok=True)
                recent = self.history[-self.history_max_size:]
                self.history_file.write_text("\n".join(recent) + "\n", encoding="utf-8")
            except Exception as e:
                logger.debug(f"Could not save history: {e}")

    def _setup_readline(self) -> None:
        try:
            readline.set_completer(self._tab_complete)
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" \t\n;")
        except Exception:
            pass

    def _tab_complete(self, text: str, state: int) -> Optional[str]:
        try:
            matches = [item for item in self._tab_completion_items if item.startswith(text)]
            if state < len(matches):
                return matches[state]
            return None
        except Exception:
            return None

    def _read_line(self) -> Optional[str]:
        if self.multi_line_mode:
            try:
                line = input("... ")
                if line.strip() == "%%":
                    self.multi_line_mode = False
                    full = "\n".join(self.multi_line_buffer)
                    self.multi_line_buffer = []
                    return full
                self.multi_line_buffer.append(line)
                return None
            except EOFError:
                self.multi_line_mode = False
                return None
        try:
            return input(self.prompt)
        except KeyboardInterrupt:
            raise

    def _execute_line(self, line: str) -> None:
        if self.multi_line_mode:
            return
        if line.strip().startswith("#") or line.strip().startswith("//"):
            return
        if line.strip() == "!!":
            if self.history:
                self._execute_line(self.history[-1])
            return

        parts = shlex.split(line)
        if not parts:
            return
        raw_cmd = parts[0].lower()
        args = parts[1:]

        cmd_name = self.aliases.get(raw_cmd, raw_cmd)
        cmd_def = self._find_command(cmd_name)

        if cmd_def is None:
            self.console.print(f"[red]Unknown command: {raw_cmd}[/red]")
            self.console.print(f"Type 'help' for available commands.")
            return

        if len(args) < cmd_def.min_args:
            self.console.print(f"[red]Error: '{cmd_def.name}' requires at least {cmd_def.min_args} arguments[/red]")
            self.console.print(f"Usage: {cmd_def.usage}")
            return

        try:
            cmd_def.handler(args)
        except Exception as e:
            self.error_count += 1
            self.console.print(f"[red]Command '{cmd_def.name}' failed: {e}[/red]")

    def _find_command(self, name: str) -> Optional[ShellCommand]:
        for cmd in self.commands:
            if cmd.name == name:
                return cmd
        return None

    def _add_to_history(self, line: str) -> None:
        self.history.append(line)
        if len(self.history) > self.history_max_size:
            self.history = self.history[-self.history_max_size:]

    def _print_welcome(self) -> None:
        self.console.print()
        self.console.print(Panel(self.welcome_message, title="Welcome", border_style="green"))
        self.console.print()

    def _on_exit(self) -> None:
        self._save_history()
        session_duration = datetime.utcnow() - self.session_start
        self.console.print()
        self.console.print(Panel(
            f"Session duration: {session_duration}\n"
            f"Commands executed: {self.command_count}\n"
            f"Errors: {self.error_count}",
            title="Session Summary",
            border_style="blue"
        ))

    def _is_verbose(self) -> bool:
        return self.variables.get("verbose", False)

    def _parse_flags(self, args: List[str]) -> Tuple[List[str], Dict[str, str], Dict[str, bool]]:
        positional = []
        flags = {}
        bool_flags = {}
        i = 0
        while i < len(args):
            if args[i].startswith("--"):
                flag_name = args[i][2:]
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    flags[flag_name] = args[i + 1]
                    i += 2
                else:
                    bool_flags[flag_name] = True
                    i += 1
            else:
                positional.append(args[i])
                i += 1
        return positional, flags, bool_flags

    def _cmd_help(self, args: List[str]) -> None:
        if args:
            cmd_name = self.aliases.get(args[0].lower(), args[0].lower())
            cmd_def = self._find_command(cmd_name)
            if cmd_def:
                self.console.print()
                self.console.print(Panel(
                    f"Command: [bold]{cmd_def.name}[/bold]\n"
                    f"Aliases: {', '.join(cmd_def.aliases) if cmd_def.aliases else 'none'}\n"
                    f"Category: {cmd_def.category}\n"
                    f"Description: {cmd_def.description}\n"
                    f"Usage: [cyan]{cmd_def.usage}[/cyan]",
                    title="Help",
                    border_style="blue"
                ))
            else:
                self.console.print(f"[red]No help found for '{args[0]}'[/red]")
            return

        self.console.print()
        by_category: Dict[str, List[ShellCommand]] = {}
        for cmd in self.commands:
            by_category.setdefault(cmd.category, []).append(cmd)

        category_names = {
            "evaluation": "Evaluation Commands",
            "configuration": "Configuration Commands",
            "rules": "Rule Management Commands",
            "system": "System Commands",
            "history": "History Commands",
            "output": "Output Commands",
            "help": "Help Commands",
        }

        for cat_key in ["evaluation", "configuration", "rules", "system", "history", "output", "help"]:
            cmds = by_category.get(cat_key, [])
            if not cmds:
                continue
            cat_name = category_names.get(cat_key, cat_key.title())
            table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
            table.add_column("Command", style="green", no_wrap=True)
            table.add_column("Aliases", style="yellow")
            table.add_column("Description", style="white")
            for cmd in sorted(cmds, key=lambda x: x.name):
                aliases_str = ", ".join(cmd.aliases) if cmd.aliases else ""
                table.add_row(cmd.name, aliases_str, cmd.description)
            self.console.print(Panel(table, title=cat_name, border_style="blue"))
            self.console.print()

    def _cmd_exit(self, args: List[str]) -> None:
        self.running = False

    def _cmd_echo(self, args: List[str]) -> None:
        self.console.print(" ".join(args))

    def _cmd_evaluate(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        if not positional:
            self.console.print("[red]Usage: evaluate <content> [--tier <tier>] [--json][/red]")
            return

        content = " ".join(positional)
        tier_str = flags.get("tier")
        output_json = bool_flags.get("json", False) or self.output_format == "json"

        tier = None
        if tier_str:
            try:
                tier = RuleTier(tier_str)
            except ValueError:
                self.console.print(f"[red]Invalid tier: {tier_str}. Use: safety, operational, preference[/red]")
                return

        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return

        request = RuleEvaluationRequest(content=content, tier=tier)
        try:
            result = asyncio.run(self.engine.evaluate(request))
        except Exception as e:
            self.console.print(f"[red]Evaluation failed: {e}[/red]")
            return

        self.last_result = result
        self.variables["last"] = result

        if output_json:
            self.console.print(json.dumps(result.dict(), indent=2, default=str))
        else:
            from .output_formatter import OutputFormatter
            fmt = OutputFormatter(console=self.console, verbose=self._is_verbose())
            fmt.print_result(result)
            if result.suggestions:
                fmt._print_suggestions_table(result.suggestions)

    def _cmd_check(self, args: List[str]) -> None:
        content = " ".join(args)
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return
        request = RuleEvaluationRequest(content=content)
        try:
            result = asyncio.run(self.engine.evaluate(request))
        except Exception as e:
            self.console.print(f"[red]Check failed: {e}[/red]")
            return
        status = "[green]PASS[/green]" if result.valid else "[red]FAIL[/red]"
        self.console.print(f"Result: {status} | Score: {result.total_score:.2f} | Violations: {len(result.violations)}")

    def _cmd_batch(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        if not positional:
            self.console.print("[red]Usage: batch <filepath> [--tier <tier>] [--format <fmt>][/red]")
            return

        filepath = Path(positional[0])
        if not filepath.exists():
            self.console.print(f"[red]File not found: {filepath}[/red]")
            return

        tier_str = flags.get("tier")
        fmt = flags.get("format", self.output_format)

        tier = None
        if tier_str:
            try:
                tier = RuleTier(tier_str)
            except ValueError:
                self.console.print(f"[red]Invalid tier: {tier_str}[/red]")
                return

        from .batch_processor import BatchProcessor
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return

        processor = BatchProcessor(engine=self.engine, console=self.console)
        try:
            result = asyncio.run(processor.process_file(filepath=filepath, tier=tier, output_format=fmt, verbose=self._is_verbose()))
        except Exception as e:
            self.console.print(f"[red]Batch failed: {e}[/red]")
            return

        self.last_result = result
        summary = result.get_summary()
        self.console.print(Panel(
            f"Total: {summary['total_items']} | Valid: {summary['valid_items']} | "
            f"Violations: {summary['items_with_violations']} | Success: {summary['success_rate']}%",
            title="Batch Complete",
            border_style="blue"
        ))

    def _cmd_config(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        key = flags.get("key")
        value = flags.get("value")

        if key and value is not None:
            self.variables[f"config.{key}"] = value
            self.console.print(f"[green]Set config.{key} = {value}[/green]")
        elif key:
            val = self.variables.get(f"config.{key}", "not set")
            self.console.print(f"config.{key} = {val}")
        else:
            from .config_commands import ConfigCommands
            cfg = ConfigCommands(console=self.console)
            cfg.view_all()

    def _cmd_set(self, args: List[str]) -> None:
        if len(args) < 2:
            self.console.print("[red]Usage: set <key> <value>[/red]")
            return
        self.variables[f"config.{args[0]}"] = " ".join(args[1:])
        self.console.print(f"[green]{args[0]} = {' '.join(args[1:])}[/green]")

    def _cmd_get(self, args: List[str]) -> None:
        val = self.variables.get(f"config.{args[0]}", "not set")
        self.console.print(f"{args[0]} = {val}")

    def _cmd_reset(self, args: List[str]) -> None:
        config_keys = [k for k in self.variables if k.startswith("config.")]
        for k in config_keys:
            del self.variables[k]
        self.console.print("[green]Configuration reset to defaults[/green]")

    def _cmd_rules(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        tier_str = flags.get("tier")
        active_only = not bool_flags.get("all", False)

        if not self.engine or not self.engine.rule_manager:
            self.console.print("[red]Rule manager not initialized[/red]")
            return

        if tier_str:
            try:
                tier = RuleTier(tier_str)
                rules = self.engine.rule_manager.get_rules_by_tier(tier)
            except ValueError:
                self.console.print(f"[red]Invalid tier: {tier_str}[/red]")
                return
        else:
            rules = list(self.engine.rule_manager.rules.values())

        if active_only:
            rules = [r for r in rules if r.status == RuleStatus.ACTIVE]

        if not rules:
            self.console.print("[yellow]No rules found[/yellow]")
            return

        table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Tier", style="yellow")
        table.add_column("Severity", style="red")
        table.add_column("Status", style="white")

        for rule in rules:
            table.add_row(
                rule.id[:12],
                rule.name[:30],
                rule.tier.value if hasattr(rule.tier, "value") else str(rule.tier),
                rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity),
                rule.status.value if hasattr(rule.status, "value") else str(rule.status),
            )
        self.console.print(Panel(f"Rules: {len(rules)}", title="Rule List", border_style="blue"))
        self.console.print(table)

    def _cmd_add_rule(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        if len(positional) < 3:
            self.console.print("[red]Usage: add-rule <name> <tier> <pattern> [--enforcement <level>][/red]")
            return
        name = positional[0]
        tier_str = positional[1]
        pattern = positional[2]
        enforcement = flags.get("enforcement", "advisory")

        try:
            tier = RuleTier(tier_str)
            enforcement_level = EnforcementLevel(enforcement)
        except ValueError as e:
            self.console.print(f"[red]{e}[/red]")
            return

        rule = Rule(
            id=f"rule_{int(time.time())}",
            name=name,
            description=f"Rule: {name}",
            tier=tier,
            rule_type=RuleType.PATTERN_MATCHING,
            severity=RuleSeverity.MEDIUM,
            enforcement_level=enforcement_level,
            patterns=[RulePattern(type=RuleType.PATTERN_MATCHING, keywords=[pattern])],
        )
        self.last_result = rule
        self.console.print(f"[green]Rule '{name}' created (ID: {rule.id})[/green]")
        self.console.print(f"  Tier: {tier.value}, Enforcement: {enforcement_level.value}")

    def _cmd_rule_info(self, args: List[str]) -> None:
        rule_id = args[0]
        if not self.engine or not self.engine.rule_manager:
            self.console.print("[red]Rule manager not initialized[/red]")
            return
        rule = self.engine.rule_manager.get_rule(rule_id)
        if not rule:
            self.console.print(f"[red]Rule not found: {rule_id}[/red]")
            return
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
            f"Tags: {', '.join(rule.tags) if rule.tags else 'none'}",
            title="Rule Details",
            border_style="blue"
        ))

    def _cmd_search_rules(self, args: List[str]) -> None:
        query = " ".join(args).lower()
        if not self.engine or not self.engine.rule_manager:
            self.console.print("[red]Rule manager not initialized[/red]")
            return
        all_rules = list(self.engine.rule_manager.rules.values())
        matched = [r for r in all_rules if query in r.name.lower() or query in (r.description or "").lower()]
        if not matched:
            self.console.print(f"[yellow]No rules matching '{query}'[/yellow]")
            return
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Tier", style="yellow")
        for rule in matched:
            table.add_row(rule.id[:12], rule.name[:40], rule.tier.value if hasattr(rule.tier, "value") else str(rule.tier))
        self.console.print(Panel(table, title=f"Rules matching '{query}'", border_style="blue"))

    def _cmd_metrics(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        output_json = bool_flags.get("json", False) or self.output_format == "json"
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return
        stats = self.engine.get_statistics()
        self.last_result = stats
        if output_json:
            self.console.print(json.dumps(stats, indent=2, default=str))
        else:
            table = Table(show_header=False, box=box.SIMPLE)
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="yellow")
            for key, value in stats.items():
                if isinstance(value, (str, int, float)):
                    table.add_row(key.replace("_", " ").title(), str(value))
            self.console.print(Panel(table, title="System Metrics", border_style="green"))

    def _cmd_health(self, args: List[str]) -> None:
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return
        checks = [
            ("Engine", self.engine is not None),
            ("Rule Manager", self.engine.rule_manager is not None),
            ("Has Rules", len(self.engine.rule_manager.rules) > 0 if self.engine.rule_manager else False),
            ("Tier Engines", len(self.engine.tier_engines) > 0 if hasattr(self.engine, "tier_engines") else False),
            ("Cache", hasattr(self.engine, "evaluation_cache")),
            ("Profiling", self.engine.profiling_enabled),
        ]
        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("Check", style="white")
        table.add_column("Status", style="bold")
        for name, ok in checks:
            status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
            table.add_row(name, status)
        all_ok = all(ok for _, ok in checks)
        status_text = "[green]HEALTHY[/green]" if all_ok else "[yellow]DEGRADED[/yellow]"
        self.console.print(Panel(table, title=f"Health Check - {status_text}", border_style="green" if all_ok else "yellow"))

    def _cmd_monitor(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        interval = int(flags.get("interval", "5"))
        duration = int(flags.get("duration", "60"))
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return
        self.console.print(f"[blue]Monitoring for {duration}s (interval: {interval}s)...[/blue]")
        start = time.time()
        try:
            while time.time() - start < duration:
                stats = self.engine.get_statistics()
                elapsed = int(time.time() - start)
                self.console.print(f"[{elapsed}s] Evals: {stats['total_evaluations']} | "
                                  f"Violations: {stats['violations_detected']} | "
                                  f"Avg: {stats['average_time_ms']:.1f}ms")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Monitoring stopped[/yellow]")

    def _cmd_version(self, args: List[str]) -> None:
        self.console.print(Panel(
            "Rules-Emerging-Pattern Interactive Shell\n"
            "Version: 1.0.0\n"
            "Engine: Tiered Rule Engine\n"
            "Tiers: Safety, Operational, Preference",
            title="Version",
            border_style="blue"
        ))

    def _cmd_engine(self, args: List[str]) -> None:
        if not self.engine:
            self.console.print("[red]Engine not initialized[/red]")
            return
        info = {
            "Initialized": "Yes",
            "Rule Manager": "Yes" if self.engine.rule_manager else "No",
            "Tier Engines": str(len(self.engine.tier_engines)),
            "Profiling": "Enabled" if self.engine.profiling_enabled else "Disabled",
            "Cache Max Size": str(self.engine.cache_max_size),
            "Hot Reload": "Enabled" if self.engine.hot_reloader else "Disabled",
            "Webhooks": "Enabled" if self.engine.webhook_notifier else "Disabled",
        }
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        for key, value in info.items():
            table.add_row(key, value)
        self.console.print(Panel(table, title="Engine Status", border_style="blue"))

    def _cmd_history(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        if bool_flags.get("clear", False):
            self.history.clear()
            self.console.print("[yellow]History cleared[/yellow]")
            return
        search = flags.get("search")
        if search:
            matched = [(i, line) for i, line in enumerate(self.history, 1) if search.lower() in line.lower()]
            if matched:
                for num, line in matched[-50:]:
                    self.console.print(f"  {num:4d}  {line}")
            else:
                self.console.print(f"[yellow]No history entries matching '{search}'[/yellow]")
        else:
            start = max(0, len(self.history) - 50)
            for i in range(start, len(self.history)):
                self.console.print(f"  {i + 1:4d}  {self.history[i]}")

    def _cmd_repeat(self, args: List[str]) -> None:
        try:
            num = int(args[0])
            if 1 <= num <= len(self.history):
                line = self.history[num - 1]
                self.console.print(f"[yellow]Repeating: {line}[/yellow]")
                self._execute_line(line)
            else:
                self.console.print(f"[red]Invalid history number: {num}[/red]")
        except ValueError:
            self.console.print("[red]Usage: repeat <number>[/red]")

    def _cmd_format(self, args: List[str]) -> None:
        fmt = args[0].lower()
        if fmt not in ("table", "json", "text", "csv"):
            self.console.print(f"[red]Invalid format: {fmt}. Use: table, json, text, csv[/red]")
            return
        self.output_format = fmt
        self.console.print(f"[green]Output format set to {fmt}[/green]")

    def _cmd_export(self, args: List[str]) -> None:
        positional, flags, bool_flags = self._parse_flags(args)
        if not positional:
            self.console.print("[red]Usage: export <filepath> [--format <fmt>][/red]")
            return
        filepath = Path(positional[0])
        fmt = flags.get("format", "json")
        if self.last_result is None:
            self.console.print("[red]No result to export. Run a command first.[/red]")
            return
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(self.last_result, "dict"):
                data = self.last_result.dict()
            else:
                data = self.last_result
            if fmt == "json":
                filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            elif fmt == "text":
                filepath.write_text(str(data), encoding="utf-8")
            else:
                filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            self.console.print(f"[green]Exported to {filepath}[/green]")
        except Exception as e:
            self.console.print(f"[red]Export failed: {e}[/red]")

    def _cmd_print(self, args: List[str]) -> None:
        if not args:
            if self.last_result is not None:
                if hasattr(self.last_result, "dict"):
                    self.console.print(json.dumps(self.last_result.dict(), indent=2, default=str))
                else:
                    self.console.print(str(self.last_result))
            return
        var_name = args[0]
        value = self.variables.get(var_name, self.variables.get(f"config.{var_name}", None))
        if value is not None:
            self.console.print(str(value))
        else:
            self.console.print(f"[yellow]Variable '{var_name}' not set[/yellow]")

    def _cmd_clear(self, args: List[str]) -> None:
        os.system("cls" if sys.platform == "win32" else "clear")
