"""Advanced reporting system for rule violations."""
import csv
import io
import json
import logging
import os
import smtplib
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

logger = logging.getLogger(__name__)


class ReportFormat(Enum):
    """Supported report output formats."""
    JSON = "json"
    CSV = "csv"
    HTML = "html"
    TEXT = "text"


class ReportSchedule(Enum):
    """Scheduling frequency for automated reports."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class ReportTemplate(Enum):
    """Pre-defined report templates."""
    SUMMARY = "summary"
    DETAILED = "detailed"
    EXECUTIVE = "executive"
    COMPLIANCE = "compliance"
    TREND = "trend"
    DASHBOARD = "dashboard"
    AUDIT = "audit"


@dataclass
class ViolationReport:
    """Data class for violation reports."""
    violation_id: str
    rule_id: str
    severity: str
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    action_taken: str = "none"
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    report_format: str = "json"


@dataclass
class ScheduledReport:
    """Configuration for a scheduled report."""
    schedule_id: str
    frequency: ReportSchedule
    template: ReportTemplate
    format: ReportFormat
    recipients: List[str]
    enabled: bool = True
    last_sent: Optional[datetime] = None
    next_send: Optional[datetime] = None
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrendData:
    """Trend analysis data point."""
    period: str
    total_violations: int
    severity_distribution: Dict[str, int]
    top_rules: List[Tuple[str, int]]
    average_severity: float
    resolved_count: int
    new_count: int


@dataclass
class ReportingConfig:
    """Configuration for the reporting system."""
    enable_scheduling: bool = True
    enable_trend_analysis: bool = True
    enable_export: bool = True
    enable_email: bool = True
    enable_dashboard_data: bool = True
    max_reports_in_memory: int = 10000
    default_format: ReportFormat = ReportFormat.JSON
    export_directory: Optional[str] = None
    smtp_server: str = "localhost"
    smtp_port: int = 25
    smtp_from: str = "reports@system.local"
    retention_days: int = 90
    trend_window_days: int = 30
    max_trend_periods: int = 12


class ViolationReporter:
    """Reporter for managing and aggregating rule violations."""

    def __init__(self, config: Optional[ReportingConfig] = None) -> None:
        self.config = config or ReportingConfig()
        self.reports: Dict[str, ViolationReport] = {}
        self.aggregated_stats: Dict[str, int] = {}
        self.scheduled_reports: Dict[str, ScheduledReport] = {}
        self.trend_history: List[TrendData] = []
        self.custom_templates: Dict[str, Callable] = {}
        self.report_counter: int = 0
        self._scheduler_running: bool = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._start_scheduler()
        logger.info("ViolationReporter initialized")

    def _start_scheduler(self) -> None:
        if self.config.enable_scheduling and not self._scheduler_running:
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self._scheduler_thread.start()
            logger.info("Report scheduler thread started")

    def _scheduler_loop(self) -> None:
        while self._scheduler_running:
            try:
                self._check_scheduled_reports()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(60)

    def _check_scheduled_reports(self) -> None:
        now = datetime.now()
        for scheduled in self.scheduled_reports.values():
            if not scheduled.enabled:
                continue
            if scheduled.next_send and now >= scheduled.next_send:
                try:
                    report = self.generate_scheduled_report(scheduled)
                    self._send_report_email(report, scheduled.recipients)
                    scheduled.last_sent = now
                    scheduled.next_send = self._compute_next_send_time(scheduled.frequency, now)
                    logger.info(f"Scheduled report {scheduled.schedule_id} sent")
                except Exception as e:
                    logger.error(f"Failed to send scheduled report {scheduled.schedule_id}: {e}")

    def _compute_next_send_time(self, frequency: ReportSchedule, from_time: datetime) -> datetime:
        if frequency == ReportSchedule.HOURLY:
            return from_time + timedelta(hours=1)
        elif frequency == ReportSchedule.DAILY:
            return from_time + timedelta(days=1)
        elif frequency == ReportSchedule.WEEKLY:
            return from_time + timedelta(weeks=1)
        elif frequency == ReportSchedule.MONTHLY:
            next_month = from_time.month + 1
            next_year = from_time.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            return from_time.replace(year=next_year, month=next_month, day=1)
        elif frequency == ReportSchedule.QUARTERLY:
            return from_time + timedelta(days=90)
        return from_time + timedelta(days=1)

    def report_violation(
        self,
        violation_id: str,
        rule_id: str,
        severity: str,
        details: Optional[Dict[str, Any]] = None,
        source: str = "unknown",
        tags: Optional[List[str]] = None,
    ) -> ViolationReport:
        with self._lock:
            if len(self.reports) >= self.config.max_reports_in_memory:
                oldest_key = min(self.reports, key=lambda k: self.reports[k].timestamp)
                del self.reports[oldest_key]
                logger.warning(f"Removed oldest report {oldest_key} due to memory limit")

            report = ViolationReport(
                violation_id=violation_id,
                rule_id=rule_id,
                severity=severity,
                timestamp=datetime.now(),
                details=details or {},
                source=source,
                tags=tags or [],
            )
            self.reports[violation_id] = report
            self.aggregated_stats[severity] = self.aggregated_stats.get(severity, 0) + 1
            self.report_counter += 1
            logger.warning(f"Violation reported: {violation_id} (Rule: {rule_id}, Severity: {severity})")
            return report

    def get_report(self, violation_id: str) -> Optional[ViolationReport]:
        report = self.reports.get(violation_id)
        if report:
            logger.info(f"Retrieved report: {violation_id}")
        else:
            logger.warning(f"Report not found: {violation_id}")
        return report

    def aggregate_reports(self) -> Dict[str, Any]:
        total_violations = len(self.reports)
        severity_distribution = self.aggregated_stats.copy()
        rules_violated: Dict[str, int] = {}

        for report in self.reports.values():
            rules_violated[report.rule_id] = rules_violated.get(report.rule_id, 0) + 1

        top_rules = sorted(rules_violated.items(), key=lambda x: x[1], reverse=True)[:10]
        sources: Dict[str, int] = defaultdict(int)
        for report in self.reports.values():
            sources[report.source] += 1

        aggregation = {
            "total_violations": total_violations,
            "severity_distribution": severity_distribution,
            "rules_violated": rules_violated,
            "top_rules": top_rules,
            "sources": dict(sources),
            "timestamp": datetime.now().isoformat(),
            "report_count": self.report_counter,
        }

        logger.info(f"Aggregated {total_violations} violations")
        return aggregation

    def get_reports_by_severity(self, severity: str) -> List[ViolationReport]:
        filtered = [r for r in self.reports.values() if r.severity == severity]
        logger.info(f"Found {len(filtered)} reports with severity '{severity}'")
        return sorted(filtered, key=lambda r: r.timestamp, reverse=True)

    def get_reports_by_rule(self, rule_id: str) -> List[ViolationReport]:
        filtered = [r for r in self.reports.values() if r.rule_id == rule_id]
        return sorted(filtered, key=lambda r: r.timestamp, reverse=True)

    def get_reports_by_source(self, source: str) -> List[ViolationReport]:
        filtered = [r for r in self.reports.values() if r.source == source]
        return sorted(filtered, key=lambda r: r.timestamp, reverse=True)

    def get_reports_in_time_range(self, start: datetime, end: datetime) -> List[ViolationReport]:
        return [r for r in self.reports.values() if start <= r.timestamp <= end]

    def get_reports_by_tag(self, tag: str) -> List[ViolationReport]:
        return [r for r in self.reports.values() if tag in r.tags]

    def generate_report_json(self, template: ReportTemplate = ReportTemplate.SUMMARY,
                              filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        reports_view = list(self.reports.values())
        if filters:
            if 'severity' in filters:
                reports_view = [r for r in reports_view if r.severity == filters['severity']]
            if 'rule_id' in filters:
                reports_view = [r for r in reports_view if r.rule_id == filters['rule_id']]
            if 'source' in filters:
                reports_view = [r for r in reports_view if r.source == filters['source']]
            if 'start' in filters and 'end' in filters:
                reports_view = [r for r in reports_view
                                if filters['start'] <= r.timestamp <= filters['end']]

        severity_dist = defaultdict(int)
        rules_count = defaultdict(int)
        sources_count = defaultdict(int)
        for r in reports_view:
            severity_dist[r.severity] += 1
            rules_count[r.rule_id] += 1
            sources_count[r.source] += 1

        if template == ReportTemplate.SUMMARY:
            return {
                "template": "summary",
                "generated_at": datetime.now().isoformat(),
                "total_violations": len(reports_view),
                "severity_distribution": dict(severity_dist),
                "top_rules": sorted(rules_count.items(), key=lambda x: x[1], reverse=True)[:5],
                "sources": dict(sources_count),
            }
        elif template == ReportTemplate.DETAILED:
            return {
                "template": "detailed",
                "generated_at": datetime.now().isoformat(),
                "total_violations": len(reports_view),
                "severity_distribution": dict(severity_dist),
                "rules_violated": dict(rules_count),
                "sources": dict(sources_count),
                "violations": [
                    {
                        "id": r.violation_id,
                        "rule": r.rule_id,
                        "severity": r.severity,
                        "timestamp": r.timestamp.isoformat(),
                        "source": r.source,
                        "tags": r.tags,
                    }
                    for r in sorted(reports_view, key=lambda x: x.timestamp, reverse=True)[:100]
                ],
            }
        elif template == ReportTemplate.EXECUTIVE:
            resolved_count = sum(1 for r in reports_view if r.resolved)
            return {
                "template": "executive",
                "generated_at": datetime.now().isoformat(),
                "executive_summary": {
                    "total_violations": len(reports_view),
                    "resolved": resolved_count,
                    "resolution_rate": round(resolved_count / len(reports_view) * 100, 1) if reports_view else 0,
                    "critical_count": severity_dist.get("critical", 0),
                    "high_count": severity_dist.get("high", 0),
                    "unique_rules": len(rules_count),
                },
                "top_concerns": sorted(rules_count.items(), key=lambda x: x[1], reverse=True)[:3],
            }
        elif template == ReportTemplate.COMPLIANCE:
            return {
                "template": "compliance",
                "generated_at": datetime.now().isoformat(),
                "total_violations": len(reports_view),
                "severity_breakdown": dict(severity_dist),
                "compliance_score": self._compute_compliance_score(reports_view),
                "violations_by_rule": dict(rules_count),
                "time_range": {
                    "earliest": min(r.timestamp for r in reports_view).isoformat() if reports_view else None,
                    "latest": max(r.timestamp for r in reports_view).isoformat() if reports_view else None,
                },
            }
        elif template == ReportTemplate.DASHBOARD:
            return {
                "template": "dashboard",
                "generated_at": datetime.now().isoformat(),
                "total_violations": len(reports_view),
                "severity_distribution": dict(severity_dist),
                "violations_by_rule": dict(rules_count),
                "violations_by_source": dict(sources_count),
                "recent_activity": [
                    {
                        "id": r.violation_id,
                        "rule": r.rule_id,
                        "severity": r.severity,
                        "timestamp": r.timestamp.isoformat(),
                    }
                    for r in sorted(reports_view, key=lambda x: x.timestamp, reverse=True)[:20]
                ],
            }
        elif template == ReportTemplate.AUDIT:
            return {
                "template": "audit",
                "generated_at": datetime.now().isoformat(),
                "total_violations": len(reports_view),
                "unique_rules_violated": len(rules_count),
                "unique_sources": len(sources_count),
                "violations": [
                    {
                        "id": r.violation_id,
                        "rule": r.rule_id,
                        "severity": r.severity,
                        "timestamp": r.timestamp.isoformat(),
                        "source": r.source,
                        "resolved": r.resolved,
                        "action_taken": r.action_taken,
                        "tags": r.tags,
                    }
                    for r in sorted(reports_view, key=lambda x: x.timestamp, reverse=True)
                ],
            }
        else:
            return self.aggregate_reports()

    def _compute_compliance_score(self, reports: List[ViolationReport]) -> float:
        if not reports:
            return 100.0
        severity_weights = {"low": 1, "medium": 3, "high": 8, "critical": 15}
        total_weight = sum(severity_weights.get(r.severity, 1) for r in reports)
        max_possible = len(reports) * 15
        if max_possible == 0:
            return 100.0
        score = max(0, 100 - (total_weight / max_possible * 100))
        return round(score, 1)

    def generate_csv_report(self, template: ReportTemplate = ReportTemplate.SUMMARY,
                             filters: Optional[Dict[str, Any]] = None) -> str:
        data = self.generate_report_json(template, filters)
        output = io.StringIO()
        writer = csv.writer(output)

        if isinstance(data, dict):
            writer.writerow(["Key", "Value"])
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    writer.writerow([key, json.dumps(value)])
                else:
                    writer.writerow([key, value])

        csv_content = output.getvalue()
        output.close()
        return csv_content

    def generate_html_report(self, template: ReportTemplate = ReportTemplate.SUMMARY,
                              filters: Optional[Dict[str, Any]] = None) -> str:
        data = self.generate_report_json(template, filters)
        generated_at = data.get("generated_at", datetime.now().isoformat())
        total = data.get("total_violations", 0)
        severity = data.get("severity_distribution", {})

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Violation Report - {template.value}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
h1 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background-color: #4CAF50; color: white; }}
.severity-critical {{ background-color: #ff4444; color: white; }}
.severity-high {{ background-color: #ff8800; color: white; }}
.severity-medium {{ background-color: #ffcc00; }}
.severity-low {{ background-color: #88ff88; }}
</style>
</head>
<body>
<h1>Violation Report - {template.value}</h1>
<p>Generated: {generated_at}</p>
<p>Total Violations: {total}</p>
<h2>Severity Distribution</h2>
<table>
<tr><th>Severity</th><th>Count</th></tr>
"""
        for sev, count in sorted(severity.items()):
            css_class = f"severity-{sev}" if sev in ["critical", "high", "medium", "low"] else ""
            html += f'<tr class="{css_class}"><td>{sev}</td><td>{count}</td></tr>\n'

        html += "</table>\n"

        if "violations" in data:
            html += "<h2>Recent Violations</h2>\n<table>\n<tr><th>ID</th><th>Rule</th><th>Severity</th><th>Timestamp</th></tr>\n"
            for v in data["violations"][:50]:
                sev_class = f"severity-{v['severity']}" if v['severity'] in ["critical", "high", "medium", "low"] else ""
                html += f'<tr class="{sev_class}"><td>{v["id"]}</td><td>{v["rule"]}</td><td>{v["severity"]}</td><td>{v["timestamp"]}</td></tr>\n'
            html += "</table>\n"

        html += "</body>\n</html>"
        return html

    def generate_text_report(self, template: ReportTemplate = ReportTemplate.SUMMARY,
                              filters: Optional[Dict[str, Any]] = None) -> str:
        data = self.generate_report_json(template, filters)
        lines = []
        lines.append(f"Violation Report - {template.value}")
        lines.append(f"Generated: {data.get('generated_at', 'N/A')}")
        lines.append(f"Total Violations: {data.get('total_violations', 0)}")
        lines.append("")
        severity = data.get("severity_distribution", {})
        if severity:
            lines.append("Severity Distribution:")
            for sev, count in sorted(severity.items()):
                lines.append(f"  {sev}: {count}")
        lines.append("")
        if "violations" in data:
            lines.append("Recent Violations:")
            for v in data["violations"][:20]:
                lines.append(f"  {v['id']}: {v['rule']} ({v['severity']}) - {v['timestamp']}")
        return "\n".join(lines)

    def generate_scheduled_report(self, scheduled: ScheduledReport) -> str:
        filters = scheduled.filters if scheduled.filters else None
        if scheduled.format == ReportFormat.JSON:
            report_data = self.generate_report_json(scheduled.template, filters)
            return json.dumps(report_data, indent=2)
        elif scheduled.format == ReportFormat.CSV:
            return self.generate_csv_report(scheduled.template, filters)
        elif scheduled.format == ReportFormat.HTML:
            return self.generate_html_report(scheduled.template, filters)
        else:
            return self.generate_text_report(scheduled.template, filters)

    def _send_report_email(self, report_content: str, recipients: List[str]) -> bool:
        if not self.config.enable_email:
            logger.warning("Email sending is disabled")
            return False

        msg = MIMEMultipart()
        msg["From"] = self.config.smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"Violation Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        msg.attach(MIMEText(report_content[:1000] + "\n\nFull report attached.", "plain"))
        attachment = MIMEText(report_content)
        attachment.add_header("Content-Disposition", "attachment",
                               filename=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        msg.attach(attachment)

        try:
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10) as server:
                server.send_message(msg)
            logger.info(f"Report email sent to {len(recipients)} recipients")
            return True
        except Exception as e:
            logger.error(f"Failed to send report email: {e}")
            return False

    def export_report_to_file(self, report_content: str, filename: str) -> str:
        export_dir = self.config.export_directory or "reports"
        os.makedirs(export_dir, exist_ok=True)
        filepath = os.path.join(export_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Report exported to {filepath}")
        return filepath

    def create_scheduled_report(
        self,
        frequency: ReportSchedule,
        template: ReportTemplate,
        format: ReportFormat = ReportFormat.JSON,
        recipients: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        schedule_id = f"SCHED-{uuid.uuid4().hex[:8]}"
        now = datetime.now()
        scheduled = ScheduledReport(
            schedule_id=schedule_id,
            frequency=frequency,
            template=template,
            format=format,
            recipients=recipients or [],
            next_send=self._compute_next_send_time(frequency, now),
            filters=filters or {},
        )
        self.scheduled_reports[schedule_id] = scheduled
        logger.info(f"Scheduled report created: {schedule_id} ({frequency.value})")
        return schedule_id

    def remove_scheduled_report(self, schedule_id: str) -> bool:
        if schedule_id in self.scheduled_reports:
            del self.scheduled_reports[schedule_id]
            logger.info(f"Scheduled report removed: {schedule_id}")
            return True
        return False

    def get_scheduled_reports(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": s.schedule_id,
                "frequency": s.frequency.value,
                "template": s.template.value,
                "format": s.format.value,
                "enabled": s.enabled,
                "last_sent": s.last_sent.isoformat() if s.last_sent else None,
                "next_send": s.next_send.isoformat() if s.next_send else None,
                "recipients": s.recipients,
            }
            for s in self.scheduled_reports.values()
        ]

    def compute_trend_analysis(self) -> Dict[str, Any]:
        if not self.config.enable_trend_analysis:
            return {"error": "Trend analysis disabled"}

        now = datetime.now()
        window_start = now - timedelta(days=self.config.trend_window_days)
        reports_in_window = [r for r in self.reports.values() if r.timestamp >= window_start]

        if not reports_in_window:
            return {"message": "No data in trend window", "periods": []}

        daily_data: Dict[str, Dict[str, int]] = {}
        for r in reports_in_window:
            day_key = r.timestamp.strftime("%Y-%m-%d")
            if day_key not in daily_data:
                daily_data[day_key] = defaultdict(int)
            daily_data[day_key][r.severity] += 1
            daily_data[day_key]["total"] += 1

        periods = []
        for day_key in sorted(daily_data.keys()):
            day_stats = daily_data[day_key]
            periods.append({
                "date": day_key,
                "total": day_stats.get("total", 0),
                "critical": day_stats.get("critical", 0),
                "high": day_stats.get("high", 0),
                "medium": day_stats.get("medium", 0),
                "low": day_stats.get("low", 0),
            })

        if len(periods) >= 2:
            first_total = periods[0]["total"]
            last_total = periods[-1]["total"]
            trend_direction = "increasing" if last_total > first_total else "decreasing" if last_total < first_total else "stable"
            pct_change = ((last_total - first_total) / first_total * 100) if first_total > 0 else 0
        else:
            trend_direction = "insufficient_data"
            pct_change = 0

        return {
            "period_start": window_start.isoformat(),
            "period_end": now.isoformat(),
            "total_in_window": len(reports_in_window),
            "daily_average": round(len(reports_in_window) / max(len(periods), 1), 1),
            "trend_direction": trend_direction,
            "percent_change": round(pct_change, 1),
            "periods": periods[-self.config.max_trend_periods:],
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_reports = [r for r in self.reports.values() if r.timestamp >= today_start]
        week_start = now - timedelta(days=7)
        week_reports = [r for r in self.reports.values() if r.timestamp >= week_start]

        severity_today = defaultdict(int)
        for r in today_reports:
            severity_today[r.severity] += 1

        severity_week = defaultdict(int)
        for r in week_reports:
            severity_week[r.severity] += 1

        return {
            "total_all_time": len(self.reports),
            "today_count": len(today_reports),
            "week_count": len(week_reports),
            "today_severity": dict(severity_today),
            "week_severity": dict(severity_week),
            "active_schedules": len(self.scheduled_reports),
            "latest_violations": [
                {
                    "id": r.violation_id,
                    "rule": r.rule_id,
                    "severity": r.severity,
                    "timestamp": r.timestamp.isoformat(),
                    "source": r.source,
                }
                for r in sorted(self.reports.values(), key=lambda x: x.timestamp, reverse=True)[:10]
            ],
            "generated_at": now.isoformat(),
        }

    def resolve_violation(self, violation_id: str, action_taken: str) -> bool:
        report = self.reports.get(violation_id)
        if not report:
            logger.warning(f"Cannot resolve: report {violation_id} not found")
            return False
        report.resolved = True
        report.resolved_at = datetime.now()
        report.action_taken = action_taken
        logger.info(f"Violation resolved: {violation_id} - {action_taken}")
        return True

    def prune_old_reports(self, days: Optional[int] = None) -> int:
        retention = days or self.config.retention_days
        cutoff = datetime.now() - timedelta(days=retention)
        before = len(self.reports)
        self.reports = {k: v for k, v in self.reports.items() if v.timestamp >= cutoff}
        removed = before - len(self.reports)
        logger.info(f"Pruned {removed} old reports (retention: {retention} days)")
        return removed

    def get_report_count_by_severity(self) -> Dict[str, int]:
        return dict(self.aggregated_stats)

    def get_all_tags(self) -> List[str]:
        all_tags = set()
        for r in self.reports.values():
            all_tags.update(r.tags)
        return sorted(all_tags)

    def shutdown(self) -> None:
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("ViolationReporter shut down")