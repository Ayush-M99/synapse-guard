"""
Component health check utilities
Each component exposes /health endpoint for monitoring
"""

import time
from typing import Dict, Any
from datetime import datetime


class ComponentHealthCheck:
    """Health check for a DARWIN component"""

    def __init__(self, component_name: str):
        self.component_name = component_name
        self.start_time = time.time()
        self.last_heartbeat = time.time()
        self.status = "healthy"
        self.error_count = 0
        self.error_message = None
        self.circuit_breaker_state = "closed"

    def heartbeat(self):
        """Update last heartbeat timestamp"""
        self.last_heartbeat = time.time()

    def record_error(self, error_message: str):
        """Record an error"""
        self.error_count += 1
        self.error_message = error_message
        if self.error_count > 5:
            self.status = "unhealthy"

    def record_success(self):
        """Record a success"""
        if self.error_count > 0:
            self.error_count -= 1
        if self.error_count == 0:
            self.status = "healthy"

    def set_circuit_breaker_state(self, state: str):
        """Update circuit breaker state"""
        self.circuit_breaker_state = state

    async def health(self) -> Dict[str, Any]:
        """Get health check response"""
        return {
            "component": self.component_name,
            "status": self.status,
            "uptime_seconds": time.time() - self.start_time,
            "last_heartbeat": datetime.fromtimestamp(self.last_heartbeat).isoformat(),
            "error_count": self.error_count,
            "error_message": self.error_message,
            "circuit_breaker_state": self.circuit_breaker_state,
            "timestamp": datetime.utcnow().isoformat(),
        }
