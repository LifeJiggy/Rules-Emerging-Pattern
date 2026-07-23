"""Advanced reporting system for rule violations."""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ViolationReport:
    """Data class for violation reports."""
    violation_id: str
    rule_id: str
    severity: str
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)


class ViolationReporter:
    """Reporter for managing and aggregating rule violations."""
    
    def __init__(self) -> None:
        """Initialize the violation reporter."""
        self.reports: Dict[str, ViolationReport] = {}
        self.aggregated_stats: Dict[str, int] = {}
        logger.info("ViolationReporter initialized")
    
    def report_violation(
        self,
        violation_id: str,
        rule_id: str,
        severity: str,
        details: Optional[Dict[str, Any]] = None
    ) -> ViolationReport:
        """Report a new rule violation.
        
        Args:
            violation_id: Unique identifier for the violation
            rule_id: Identifier of the violated rule
            severity: Severity level (low, medium, high, critical)
            details: Additional violation details
            
        Returns:
            The created violation report
        """
        report = ViolationReport(
            violation_id=violation_id,
            rule_id=rule_id,
            severity=severity,
            timestamp=datetime.now(),
            details=details or {}
        )
        self.reports[violation_id] = report
        self.aggregated_stats[severity] = self.aggregated_stats.get(severity, 0) + 1
        logger.warning(f"Violation reported: {violation_id} (Rule: {rule_id}, Severity: {severity})")
        return report
    
    def get_report(self, violation_id: str) -> Optional[ViolationReport]:
        """Retrieve a specific violation report.
        
        Args:
            violation_id: The ID of the violation to retrieve
            
        Returns:
            The violation report if found, None otherwise
        """
        report = self.reports.get(violation_id)
        if report:
            logger.info(f"Retrieved report: {violation_id}")
        else:
            logger.warning(f"Report not found: {violation_id}")
        return report
    
    def aggregate_reports(self) -> Dict[str, Any]:
        """Aggregate all reports into summary statistics.
        
        Returns:
            Dictionary containing aggregated statistics
        """
        total_violations = len(self.reports)
        severity_distribution = self.aggregated_stats.copy()
        rules_violated = {}
        
        for report in self.reports.values():
            rules_violated[report.rule_id] = rules_violated.get(report.rule_id, 0) + 1
        
        aggregation = {
            "total_violations": total_violations,
            "severity_distribution": severity_distribution,
            "rules_violated": rules_violated,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Aggregated {total_violations} violations")
        return aggregation
    
    def get_reports_by_severity(self, severity: str) -> List[ViolationReport]:
        """Get all reports filtered by severity level.
        
        Args:
            severity: The severity level to filter by
            
        Returns:
            List of violation reports with the specified severity
        """
        filtered = [r for r in self.reports.values() if r.severity == severity]
        logger.info(f"Found {len(filtered)} reports with severity '{severity}'")
        return filtered
