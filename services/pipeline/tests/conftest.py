"""
Shared pytest fixtures and configuration for the pipeline service unit tests.
"""
import pytest


# ── asyncio mode ─────────────────────────────────────────────────────────────
# pytest-asyncio >= 0.21 requires an explicit mode declaration so that every
# async test function is recognised without per-test @pytest.mark.asyncio.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (handled by pytest-asyncio)"
    )
