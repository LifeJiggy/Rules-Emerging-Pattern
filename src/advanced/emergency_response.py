"""Emergency response system for critical rule violations."""
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class EmergencyLevel(Enum):
    """Emergency severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EmergencyIncident:
    """Represents an emergency incident."""
    incident_id: str
    level: EmergencyLevel
    description: str
    timestamp: datetime
    affected_systems: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    resolved: bool = False


class EmergencyResponse:
    """Emergency response coordinator for critical situations."""
    
    def __init__(self):
        """Initialize the emergency response system."""
        self.active_incidents: Dict[str, EmergencyIncident] = {}
        self.response_handlers: Dict[EmergencyLevel, List[Callable]] = {
            level: [] for level in EmergencyLevel
        }
        self.incident_history: List[EmergencyIncident] = []
        self.emergency_contacts: List[str] = []
        logger.info("EmergencyResponse system initialized")
    
    def register_handler(self, level: EmergencyLevel, handler: Callable) -> None:
        """Register a response handler for an emergency level.
        
        Args:
            level: The emergency level to handle
            handler: Callable to invoke when emergency occurs
        """
        self.response_handlers[level].append(handler)
        logger.info(f"Registered handler for {level.value} emergencies")
    
    def trigger_emergency(
        self,
        incident_id: str,
        level: EmergencyLevel,
        description: str,
        affected_systems: Optional[List[str]] = None
    ) -> EmergencyIncident:
        """Trigger an emergency response.
        
        Args:
            incident_id: Unique identifier for the incident
            level: Severity level of the emergency
            description: Description of the emergency
            affected_systems: List of affected system names
            
        Returns:
            The created emergency incident
        """
        incident = EmergencyIncident(
            incident_id=incident_id,
            level=level,
            description=description,
            timestamp=datetime.now(),
            affected_systems=affected_systems or [],
            actions_taken=["Emergency triggered"],
            resolved=False
        )
        
        self.active_incidents[incident_id] = incident
        
        # Invoke all handlers for this level
        for handler in self.response_handlers.get(level, []):
            try:
                handler(incident)
                incident.actions_taken.append(f"Handler executed: {handler.__name__}")
            except Exception as e:
                logger.error(f"Handler failed: {e}")
        
        logger.critical(f"EMERGENCY TRIGGERED: {incident_id} - {description}")
        
        # Send notifications
        self._notify_emergency_contacts(incident)
        
        return incident
    
    def resolve_emergency(self, incident_id: str, resolution_notes: str) -> bool:
        """Resolve an active emergency incident.
        
        Args:
            incident_id: The ID of the incident to resolve
            resolution_notes: Notes about the resolution
            
        Returns:
            True if successfully resolved, False otherwise
        """
        if incident_id not in self.active_incidents:
            logger.warning(f"Incident not found: {incident_id}")
            return False
        
        incident = self.active_incidents[incident_id]
        incident.resolved = True
        incident.actions_taken.append(f"Resolved: {resolution_notes}")
        
        # Move to history
        self.incident_history.append(incident)
        del self.active_incidents[incident_id]
        
        logger.info(f"Emergency resolved: {incident_id}")
        return True
    
    def add_emergency_contact(self, contact: str) -> None:
        """Add an emergency contact for notifications.
        
        Args:
            contact: Contact information (email, phone, etc.)
        """
        self.emergency_contacts.append(contact)
        logger.info(f"Added emergency contact: {contact}")
    
    def _notify_emergency_contacts(self, incident: EmergencyIncident) -> None:
        """Notify all emergency contacts about an incident."""
        for contact in self.emergency_contacts:
            logger.info(f"Emergency notification sent to {contact} for incident {incident.incident_id}")
    
    def get_active_incidents(self, level: Optional[EmergencyLevel] = None) -> List[EmergencyIncident]:
        """Get all active incidents, optionally filtered by level.
        
        Args:
            level: Optional level to filter by
            
        Returns:
            List of active incidents
        """
        incidents = list(self.active_incidents.values())
        if level:
            incidents = [i for i in incidents if i.level == level]
        return incidents
    
    def get_incident_stats(self) -> Dict:
        """Get statistics about incidents.
        
        Returns:
            Dictionary with incident statistics
        """
        stats = {
            "active_incidents": len(self.active_incidents),
            "total_incidents": len(self.incident_history) + len(self.active_incidents),
            "by_level": {level.value: 0 for level in EmergencyLevel},
            "resolved_count": len([i for i in self.incident_history if i.resolved]),
            "emergency_contacts": len(self.emergency_contacts)
        }
        
        for incident in list(self.active_incidents.values()) + self.incident_history:
            stats["by_level"][incident.level.value] += 1
        
        return stats
