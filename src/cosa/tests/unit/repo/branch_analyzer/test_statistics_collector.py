"""
Unit tests for cosa.repo.branch_analyzer.statistics_collector.

Tests StatisticsCollector: accumulates per-file-type add/remove counts and
per-language code/comment/docstring breakdowns, then computes a summary with
division-by-zero-safe percentages. Coverage drives real aggregation maths:
totals, net change, sorting, language percentages, the empty-input zero path,
file tracking, and reset().

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.branch_analyzer.statistics_collector import StatisticsCollector


@pytest.fixture
def collector():
    """A fresh StatisticsCollector."""
    return StatisticsCollector()


class TestDebugLogging:
    """debug=True exercises the constructor/reset log branches."""

    def test_debug_init_logs( self, capsys ):
        """Ensures: debug=True emits an init banner."""
        StatisticsCollector( debug=True )
        assert "Initialized" in capsys.readouterr().out

    def test_debug_reset_logs( self, capsys ):
        """Ensures: debug=True emits a reset banner."""
        StatisticsCollector( debug=True ).reset()
        assert "reset" in capsys.readouterr().out.lower()


class TestRecordEdgeBranches:
    """record_line tolerates invalid input and non-language removals."""

    def test_unknown_operation_is_ignored( self, collector ):
        """
        Ensures:
            - an operation that is neither 'add' nor 'remove' updates nothing
              (the elif-false fall-through to file tracking)
        """
        collector.record_line( "python", "noop" )
        summary = collector.get_summary()
        assert summary[ "overall" ][ "total_added" ] == 0
        assert summary[ "overall" ][ "total_removed" ] == 0

    def test_remove_for_non_language_type_skips_language_breakdown( self, collector ):
        """
        Ensures:
            - a 'remove' on a non-code file type (markdown) counts in the
              overall removed total but is NOT added to language_details
              (the file_type-not-in-languages false branch)
        """
        collector.record_line( "markdown", "remove" )
        summary = collector.get_summary()
        assert summary[ "overall" ][ "total_removed" ] == 1
        assert "markdown" not in summary[ "language_details" ]


class TestRecordAndOverall:
    """record_line() feeds the overall add/remove/net/file totals."""

    def test_added_and_removed_totals( self, collector ):
        """
        Ensures:
            - 'add' increments total_added; 'remove' increments total_removed
            - net_change is added minus removed
        """
        collector.record_line( "python", "add", line_category="code" )
        collector.record_line( "python", "add", line_category="comment" )
        collector.record_line( "python", "remove" )
        summary = collector.get_summary()

        assert summary[ "overall" ][ "total_added" ] == 2
        assert summary[ "overall" ][ "total_removed" ] == 1
        assert summary[ "overall" ][ "net_change" ] == 1

    def test_file_tracking_counts_unique_paths( self, collector ):
        """
        Ensures:
            - files_changed counts distinct file_path values only
        """
        collector.record_line( "python", "add", file_path="a.py" )
        collector.record_line( "python", "add", file_path="a.py" )
        collector.record_line( "python", "add", file_path="b.py" )
        summary = collector.get_summary()

        assert summary[ "overall" ][ "files_changed" ] == 2
        assert set( summary[ "files_changed_set" ] ) == { "a.py", "b.py" }

    def test_empty_collector_yields_zeros( self, collector ):
        """Ensures: with no records, all overall totals are zero."""
        summary = collector.get_summary()
        assert summary[ "overall" ] == {
            "total_added"   : 0,
            "total_removed" : 0,
            "net_change"    : 0,
            "files_changed" : 0,
        }
        assert summary[ "by_file_type" ] == []


class TestByFileTypeBreakdown:
    """Breakdown is per-file-type and sorted by total activity desc."""

    def test_breakdown_fields_and_net( self, collector ):
        """Ensures: each breakdown row carries added/removed/net/total."""
        collector.record_line( "python", "add" )
        collector.record_line( "python", "remove" )
        row = collector.get_summary()[ "by_file_type" ][ 0 ]

        assert row[ "file_type" ] == "python"
        assert row[ "added" ] == 1
        assert row[ "removed" ] == 1
        assert row[ "net" ] == 0
        assert row[ "total" ] == 2

    def test_breakdown_sorted_by_total_desc( self, collector ):
        """
        Ensures:
            - file types are ordered by (added+removed) descending
        """
        # markdown: 1 change; python: 3 changes → python first
        collector.record_line( "markdown", "add" )
        collector.record_line( "python", "add" )
        collector.record_line( "python", "add" )
        collector.record_line( "python", "remove" )
        order = [ row[ "file_type" ] for row in collector.get_summary()[ "by_file_type" ] ]
        assert order[ 0 ] == "python"
        assert order[ 1 ] == "markdown"


class TestLanguageDetails:
    """Language breakdowns compute code/comment/docstring percentages."""

    def test_percentages_sum_over_added_categories( self, collector ):
        """
        Ensures:
            - per-language code/comment/docstring counts are recorded
            - percentages are computed over total_added (here 4 → 50/25/25)
        """
        collector.record_line( "python", "add", line_category="code" )
        collector.record_line( "python", "add", line_category="code" )
        collector.record_line( "python", "add", line_category="comment" )
        collector.record_line( "python", "add", line_category="docstring" )
        py = collector.get_summary()[ "language_details" ][ "python" ]

        assert py[ "code" ] == 2
        assert py[ "comment" ] == 1
        assert py[ "docstring" ] == 1
        assert py[ "total_added" ] == 4
        assert py[ "percentages" ][ "code" ] == 50.0
        assert py[ "percentages" ][ "comment" ] == 25.0
        assert py[ "percentages" ][ "docstring" ] == 25.0

    def test_removed_only_language_has_zero_percentages( self, collector ):
        """
        Ensures:
            - a language with only removals (total_added==0) gets the
              zero-percentage fallback (division-by-zero guard)
            - net is negative
        """
        collector.record_line( "python", "remove" )
        py = collector.get_summary()[ "language_details" ][ "python" ]

        assert py[ "total_added" ] == 0
        assert py[ "removed" ] == 1
        assert py[ "net" ] == -1
        assert py[ "percentages" ] == { "code": 0.0, "comment": 0.0, "docstring": 0.0 }

    def test_non_language_file_type_absent_from_language_details( self, collector ):
        """
        Ensures:
            - a non-code file type (markdown) does not appear in
              language_details (only python/javascript/typescript do)
        """
        collector.record_line( "markdown", "add" )
        assert "markdown" not in collector.get_summary()[ "language_details" ]


class TestReset:
    """reset() clears all accumulated state."""

    def test_reset_clears_everything( self, collector ):
        """
        Ensures:
            - after reset, totals/breakdown/files are all empty again
        """
        collector.record_line( "python", "add", file_path="a.py" )
        collector.reset()
        summary = collector.get_summary()

        assert summary[ "overall" ][ "total_added" ] == 0
        assert summary[ "overall" ][ "files_changed" ] == 0
        assert summary[ "by_file_type" ] == []
        assert summary[ "language_details" ] == {}
