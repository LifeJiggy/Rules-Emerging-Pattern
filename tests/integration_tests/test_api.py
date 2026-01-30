"""Integration tests for API."""
import pytest
import asyncio
from rules_emerging_pattern.main import app

class TestAPI:
    """Test API endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health check endpoint."""
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

if __name__ == "__main__":
    pytest.main([__file__])
