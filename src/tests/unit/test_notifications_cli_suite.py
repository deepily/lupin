"""
Pins the behaviour of the manual notification CLI in test_notifications.py.

That CLI sends canned notifications through notify_user to a live server.
Every notify_user call is replaced by a recording fake and time.sleep by a no-op,
so nothing here reaches a server.
"""

import sys
from unittest.mock import patch

import pytest

from lupin_cli.notifications import test_notifications as tn

MODULE = "lupin_cli.notifications.test_notifications"

BASIC_ROWS = [
    ( "Basic Custom Notification", "Test notification from Claude Code", "custom", "medium" ),
    ( "Task Completion Success", "Build completed successfully", "task", "high" ),
    ( "Task Completion Failure", "Tests failed - please check output", "task", "high" ),
    ( "Progress Update", "Installing dependencies (step 1/4)", "progress", "low" ),
    ( "Warning Alert", "Deprecated API usage detected", "alert", "medium" ),
    ( "Critical Alert", "Disk space critically low", "alert", "urgent" ),
]
PRIORITY_ROWS = [
    ( "Low Priority Info", "Background cache cleanup completed", "custom", "low" ),
    ( "Medium Priority Update", "Code analysis finished", "custom", "medium" ),
    ( "High Priority Warning", "Memory usage approaching limit", "custom", "high" ),
    ( "Urgent Priority Alert", "System error requires immediate attention", "custom", "urgent" ),
]
WORKFLOW_ROWS = [
    ( "Build Started", "Starting build process for lupin", "progress", "low" ),
    ( "Dependencies Installed", "npm install completed successfully", "progress", "low" ),
    ( "Running Tests", "Executing test suite (15 tests)", "progress", "medium" ),
    ( "Tests Passed", "All tests passed - 15/15 successful", "task", "medium" ),
    ( "Build Complete", "Build completed successfully in 2m 34s", "task", "high" ),
    ( "Deployment Ready", "Application ready for deployment", "task", "high" ),
]
QUICK_ROWS = [
    ( "Basic Notification", "Quick test from Claude Code", "custom", "medium" ),
    ( "Task Success", "Quick task completed", "task", "medium" ),
    ( "Alert Test", "Quick alert test", "alert", "high" ),
]
ERROR_ROWS = [
    ( "Empty Message", "", "custom", "medium" ),
    ( "Very Long Message", "This is a very long message " * 10, "custom", "medium" ),
    ( "Special Characters", "Message with émojis 🎉 and symbols #@$%", "custom", "medium" ),
    ( "Multiline Message", "Line 1\nLine 2\nLine 3", "custom", "medium" ),
]

# ( method name, expected rows, expected banner text as printed first, expected plain-"=" rule )
SUITES = [
    ( "run_basic_tests",             BASIC_ROWS,    "📋 Running Basic Notification Tests" ),
    ( "run_priority_tests",          PRIORITY_ROWS, "\n🔔 Running Priority Level Tests" ),
    ( "run_realistic_workflow_tests", WORKFLOW_ROWS, "\n⚙️  Running Realistic Workflow Tests" ),
    ( "run_quick_tests",             QUICK_ROWS,    "⚡ Running Quick Test Suite" ),
    ( "run_error_scenarios",         ERROR_ROWS,    "\n⚠️  Running Error Scenario Tests" ),
]


class RecordingNotify:
    """Fake notify_user: records each call, fails the call numbers listed in fail_on."""

    def __init__( self, fail_on=() ):
        self.calls   = []
        self.fail_on = set( fail_on )

    def __call__( self, message, notification_type, priority ):
        self.calls.append( ( message, notification_type, priority ) )
        return len( self.calls ) not in self.fail_on


def run_suite( method, fail_on=(), delay=0.0 ):
    """Runs one suite method against the fake; returns ( passed, calls, lines, suite )."""
    fake  = RecordingNotify( fail_on=fail_on )
    suite = tn.NotificationTestSuite( debug=False, delay=delay )
    with patch( f"{MODULE}.notify_user", fake ), patch( f"{MODULE}.time.sleep" ), \
         patch( "builtins.print" ) as mock_print:
        passed = getattr( suite, method )()
    lines = [ c.args[0] if c.args else "" for c in mock_print.call_args_list ]
    return passed, fake.calls, lines, suite


class TestRunSuites:

    @pytest.mark.parametrize( "method, rows, banner", SUITES )
    def test_each_suite_sends_its_rows_in_order( self, method, rows, banner ):
        passed, calls, _, suite = run_suite( method )
        assert calls == [ ( msg, kind, prio ) for _, msg, kind, prio in rows ]
        assert passed == len( rows )
        assert [ r["test_name"] for r in suite.results ] == [ name for name, *_ in rows ]

    @pytest.mark.parametrize( "method, rows, banner", SUITES )
    def test_each_suite_prints_its_banner_then_a_fifty_char_rule( self, method, rows, banner ):
        _, _, lines, _ = run_suite( method )
        assert lines[ 0 ] == banner
        assert lines[ 1 ] == "=" * 50

    @pytest.mark.parametrize( "method, rows, banner", [ s for s in SUITES if s[ 0 ] != "run_error_scenarios" ] )
    def test_a_failing_notification_is_not_counted( self, method, rows, banner ):
        passed, calls, _, _ = run_suite( method, fail_on={ 1, 3 } if len( rows ) > 3 else { 1 } )
        expected_failures = 2 if len( rows ) > 3 else 1
        assert len( calls ) == len( rows )
        assert passed == len( rows ) - expected_failures

    def test_error_scenarios_count_every_row_even_when_notify_fails( self ):
        passed, calls, _, _ = run_suite( "run_error_scenarios", fail_on={ 1, 2, 3, 4 } )
        assert len( calls ) == 4
        assert passed == 4


class TestRunTable:

    def test_it_prints_the_banner_and_rule_runs_rows_in_order_and_counts_passes( self ):
        rows = [ ( "a", "ma", "task", "low" ), ( "b", "mb", "alert", "high" ), ( "c", "mc", "custom", "medium" ) ]
        fake = RecordingNotify( fail_on={ 2 } )
        suite = tn.NotificationTestSuite( delay=0 )
        with patch( f"{MODULE}.notify_user", fake ), patch( "builtins.print" ) as mock_print:
            passed = suite._run_table( "BANNER", rows )
        assert passed == 2
        assert fake.calls == [ ( "ma", "task", "low" ), ( "mb", "alert", "high" ), ( "mc", "custom", "medium" ) ]
        assert [ c.args[ 0 ] for c in mock_print.call_args_list[ :2 ] ] == [ "BANNER", "=" * 50 ]

    def test_no_rows_returns_zero( self ):
        with patch( "builtins.print" ):
            assert tn.NotificationTestSuite()._run_table( "B", [] ) == 0


class TestRunTest:

    def test_a_passing_test_prints_its_name_type_message_and_result( self ):
        _, _, lines, _ = run_suite( "run_quick_tests" )
        assert "\n🧪 Basic Notification" in lines
        assert "   Type: custom | Priority: medium" in lines
        assert "   Message: \"Quick test from Claude Code\"" in lines
        assert any( l.startswith( "   ✓ PASSED (" ) for l in lines )

    def test_a_failing_test_prints_failed( self ):
        _, _, lines, _ = run_suite( "run_quick_tests", fail_on={ 1 } )
        assert any( l.startswith( "   ✗ FAILED (" ) for l in lines )

    def test_the_result_record_carries_the_full_metadata( self ):
        _, _, _, suite = run_suite( "run_quick_tests", fail_on={ 2 } )
        first, second, _third = suite.results
        assert ( first[ "test_name" ], first[ "message" ], first[ "type" ], first[ "priority" ], first[ "success" ] ) == \
               ( "Basic Notification", "Quick test from Claude Code", "custom", "medium", True )
        assert second[ "success" ] is False
        assert first[ "duration" ] >= 0

    def test_the_delay_is_slept_after_each_test_only_when_positive( self ):
        suite = tn.NotificationTestSuite( debug=False, delay=0.25 )
        with patch( f"{MODULE}.notify_user", RecordingNotify() ), patch( f"{MODULE}.time.sleep" ) as sleep, \
             patch( "builtins.print" ):
            suite.run_quick_tests()
        assert [ c.args[ 0 ] for c in sleep.call_args_list ] == [ 0.25 ] * 3

        suite = tn.NotificationTestSuite( debug=False, delay=0 )
        with patch( f"{MODULE}.notify_user", RecordingNotify() ), patch( f"{MODULE}.time.sleep" ) as sleep, \
             patch( "builtins.print" ):
            suite.run_quick_tests()
        sleep.assert_not_called()

    def test_log_prints_a_timestamped_line_only_in_debug_mode( self ):
        quiet = tn.NotificationTestSuite( debug=False )
        loud  = tn.NotificationTestSuite( debug=True )
        with patch( "builtins.print" ) as mock_print:
            quiet.log( "hush" )
            mock_print.assert_not_called()
            loud.log( "hello", "WARN" )
        line = mock_print.call_args.args[ 0 ]
        assert line.endswith( "] WARN: hello" ) and line.startswith( "[" )

    def test_debug_mode_logs_each_test( self ):
        suite = tn.NotificationTestSuite( debug=True, delay=0 )
        with patch( f"{MODULE}.notify_user", RecordingNotify() ), patch( "builtins.print" ) as mock_print:
            suite.run_quick_tests()
        text = "\n".join( str( c ) for c in mock_print.call_args_list )
        assert "INFO: Running test: Basic Notification" in text
        assert "INFO: Test result: PASSED in" in text


class TestPrintSummary:

    def summary( self, results, passed, total ):
        suite         = tn.NotificationTestSuite()
        suite.results = results
        with patch( "builtins.print" ) as mock_print:
            verdict = suite.print_summary( passed, total )
        return verdict, [ c.args[ 0 ] for c in mock_print.call_args_list ]

    def test_all_passed_is_success( self ):
        results = [ { "type": "task", "priority": "high", "success": True, "duration": 0.5 },
                    { "type": "task", "priority": "low", "success": True, "duration": 1.5 } ]
        verdict, lines = self.summary( results, 2, 2 )
        assert verdict is True
        assert "✅ Tests Passed: 2/2 (100.0%)" in lines
        assert "❌ Tests Failed: 0" in lines
        assert "  task    :  2/ 2 (100.0%)" in lines
        assert "  high  :  1/ 1 (100.0%)" in lines
        assert "  Average Response Time: 1.00s" in lines
        assert "  Fastest Response:      0.50s" in lines
        assert "  Slowest Response:      1.50s" in lines
        assert "🎉 ALL TESTS PASSED! Notification system is working perfectly." in lines

    def test_above_eighty_percent_is_mostly_successful( self ):
        results = [ { "type": "task", "priority": "high", "success": i != 0, "duration": 0.1 } for i in range( 10 ) ]
        verdict, lines = self.summary( results, 9, 10 )
        assert verdict is True
        assert "  task    :  9/10 ( 90.0%)" in lines
        assert "✅ MOSTLY SUCCESSFUL! Minor issues detected." in lines

    def test_exactly_eighty_percent_fails( self ):
        verdict, lines = self.summary( [], 8, 10 )
        assert verdict is False
        assert "❌ TESTS FAILED! Check Lupin API status and configuration." in lines

    def test_zero_tests_reports_zero_percent_and_no_performance_block( self ):
        verdict, lines = self.summary( [], 0, 0 )
        assert verdict is True
        assert "✅ Tests Passed: 0/0 (0.0%)" in lines
        assert not any( "Performance" in l for l in lines )


class TestMain:

    def run_main( self, argv, env_ok=True ):
        suite_calls = []

        def spy( name ):
            def inner( self_ ):
                suite_calls.append( name )
                return 1
            return inner

        with patch.object( sys, "argv", [ "test_notifications.py" ] + argv ), \
             patch( f"{MODULE}.validate_environment", return_value=env_ok ), \
             patch.object( tn.NotificationTestSuite, "run_basic_tests", spy( "basic" ) ), \
             patch.object( tn.NotificationTestSuite, "run_priority_tests", spy( "priority" ) ), \
             patch.object( tn.NotificationTestSuite, "run_realistic_workflow_tests", spy( "workflow" ) ), \
             patch.object( tn.NotificationTestSuite, "run_error_scenarios", spy( "error" ) ), \
             patch.object( tn.NotificationTestSuite, "run_quick_tests", spy( "quick" ) ), \
             patch.object( tn.NotificationTestSuite, "print_summary", return_value=True ) as summary, \
             patch( "builtins.print" ):
            with pytest.raises( SystemExit ) as exc:
                tn.main()
        return exc.value.code, suite_calls, summary

    def test_a_bad_environment_exits_one_before_any_test( self ):
        code, calls, _ = self.run_main( [], env_ok=False )
        assert code == 1 and calls == []

    def test_validate_only_exits_zero_without_running_tests( self ):
        code, calls, _ = self.run_main( [ "--validate-only" ] )
        assert code == 0 and calls == []

    def test_quick_runs_only_the_quick_suite_and_totals_three( self ):
        code, calls, summary = self.run_main( [ "--quick" ] )
        assert calls == [ "quick" ]
        assert summary.call_args.args == ( 1, 3 )
        assert code == 0

    def test_full_runs_four_suites_in_order_and_totals_twenty( self ):
        code, calls, summary = self.run_main( [] )
        assert calls == [ "basic", "priority", "workflow", "error" ]
        assert summary.call_args.args == ( 4, 20 )
        assert code == 0

    def test_a_failing_summary_exits_one( self ):
        with patch.object( tn.NotificationTestSuite, "print_summary", return_value=False ), \
             patch.object( sys, "argv", [ "x", "--quick", "--delay", "0" ] ), \
             patch( f"{MODULE}.validate_environment", return_value=True ), \
             patch( f"{MODULE}.notify_user", RecordingNotify() ), \
             patch( "builtins.print" ):
            with pytest.raises( SystemExit ) as exc:
                tn.main()
        assert exc.value.code == 1
