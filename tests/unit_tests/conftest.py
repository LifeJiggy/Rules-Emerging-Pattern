"""Pytest configuration and fixtures."""
import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil

@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_directory():
    """Provide a temporary directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture
def sample_rule_data():
    """Provide sample rule data for testing."""
    return {
        "id": "test_rule_001",
        "name": "Test Safety Rule",
        "description": "A test rule for safety validation",
        "tier": "safety",
        "type": "content_filtering",
        "severity": "high",
        "patterns": [{"type": "keyword", "keywords": ["test", "danger"]}],
        "enforcement": "strict",
        "auto_block": True,
        "user_override": False
    }

@pytest.fixture
def mock_context():
    """Provide a mock context for testing."""
    return {
        "user_id": "test_user",
        "domain": "test_domain",
        "user_role": "admin"
    }
