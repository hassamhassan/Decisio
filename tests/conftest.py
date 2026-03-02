"""Pytest configuration and fixtures."""

import pytest

# Enable pytest-asyncio for async tests
pytest_plugins = ["pytest_asyncio"]

def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async (pytest-asyncio)")
