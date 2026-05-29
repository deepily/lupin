"""
Unit tests for WG-7 — TestSuiteJob non-pytest stdout fallback parser.

The websocket smoke runner is a bash-driven async orchestrator that emits
its own log format (no junit-xml). Without a fallback, _parse_junit_xml
returns zero-counts and the suite is mis-classified as FAIL even when
the runner reports ALL SMOKE TESTS PASSED.

These tests exercise `TestSuiteJob._parse_non_pytest_stdout` directly.

Created: 2026-04-28 (WG-7)
"""

from cosa.agents.test_suite.job import TestSuiteJob


# ──────────────────────────────────────────────────────────────────────────
# Sample stdout payloads (representative of the actual runner output)
# ──────────────────────────────────────────────────────────────────────────

WEBSOCKET_PASS_STDOUT = """\
[01:58:29.050] [INFO] 📊 SMOKE TEST RESULTS SUMMARY
[01:58:29.050] [INFO] ============================================================
[01:58:29.050] [INFO] Execution Time: 45.11s
[01:58:29.050] [INFO] Total Tests: 50
[01:58:29.050] [INFO] Passed: 50
[01:58:29.050] [INFO] Failed: 0
[01:58:29.050] [INFO] Success Rate: 100.0%
[01:58:29.050] [INFO] ============================================================
[01:58:29.050] [INFO] ✅ ALL SMOKE TESTS PASSED!
"""

WEBSOCKET_FAIL_STDOUT = """\
[01:58:29.050] [INFO] 📊 SMOKE TEST RESULTS SUMMARY
[01:58:29.050] [INFO] Total Tests: 50
[01:58:29.050] [INFO] Passed: 47
[01:58:29.050] [INFO] Failed: 3
[01:58:29.050] [INFO] Success Rate: 94.0%
[01:58:29.050] [INFO] ❌ SOME SMOKE TESTS FAILED
"""

WEBSOCKET_PARTIAL_STDOUT_TOTAL_ONLY = """\
[01:58:29.050] [INFO] Total Tests: 50
[01:58:29.050] [INFO] ✅ ALL SMOKE TESTS PASSED!
"""

WEBSOCKET_PARTIAL_STDOUT_AMBIGUOUS = """\
[01:58:29.050] [INFO] Total Tests: 50
"""

UNRECOGNIZED_STDOUT = """\
some random output that doesn't match any known runner format
"""


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

def test_websocket_pass_full_summary():
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", WEBSOCKET_PASS_STDOUT )
    assert parsed == {
        "passed"  : 50,
        "failed"  : 0,
        "skipped" : 0,
        "errors"  : 0,
    }


def test_websocket_fail_full_summary():
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", WEBSOCKET_FAIL_STDOUT )
    assert parsed == {
        "passed"  : 47,
        "failed"  : 3,
        "skipped" : 0,
        "errors"  : 0,
    }


def test_websocket_total_only_with_pass_marker():
    """When only 'Total Tests: N' is parseable but 'ALL SMOKE TESTS PASSED' is present."""
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", WEBSOCKET_PARTIAL_STDOUT_TOTAL_ONLY )
    assert parsed == {
        "passed"  : 50,
        "failed"  : 0,
        "skipped" : 0,
        "errors"  : 0,
    }


def test_websocket_total_only_no_marker_returns_none():
    """When only Total is found and no PASSED marker — too ambiguous; preserve zero default."""
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", WEBSOCKET_PARTIAL_STDOUT_AMBIGUOUS )
    assert parsed is None


def test_unrecognized_stdout_returns_none():
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", UNRECOGNIZED_STDOUT )
    assert parsed is None


def test_empty_stdout_returns_none():
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", "" )
    assert parsed is None


def test_non_websocket_suite_returns_none():
    """Parser only handles 'websocket' today; other suite types pass through."""
    parsed = TestSuiteJob._parse_non_pytest_stdout( "smoke", WEBSOCKET_PASS_STDOUT )
    assert parsed is None


def test_passed_failed_no_total_reconciled():
    """Stdout has Passed and Failed but no explicit Total — total computed from sum."""
    stdout = "Passed: 30\nFailed: 5\n"
    parsed = TestSuiteJob._parse_non_pytest_stdout( "websocket", stdout )
    assert parsed == {
        "passed"  : 30,
        "failed"  : 5,
        "skipped" : 0,
        "errors"  : 0,
    }
