"""
Test harness for agentic jobs.

Provides mock implementations for testing queue UI and job lifecycle
without incurring inference costs.

Exports:
    MockAgenticJob: Simulates long-running jobs with configurable behavior
"""

from cosa.agents.test_harness.mock_job import MockAgenticJob

__all__ = [ "MockAgenticJob" ]
__version__ = "0.1.0"
