#!/usr/bin/env python3
"""
COSA Test Suite Agent.

Runs integration and E2E test suites as scheduled background jobs
within the CJ Flow queue system. Supports monopolize mode for
exclusive DB hot-swap access.

Usage:
    from cosa.agents.test_suite.job import TestSuiteJob

    job = TestSuiteJob(
        test_types = [ "integration", "e2e" ],
        user_id    = "user123",
        user_email = "user@example.com",
        session_id = "wise-penguin",
        dry_run    = True
    )
    result = job.do_all()
"""

from . import voice_io       # noqa: F401
from . import cosa_interface  # noqa: F401
