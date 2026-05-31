"""
Unit tests for cosa.repo.directory_analyzer.statistics_collector.

Tests DirectoryStatisticsCollector: accumulates per-file-type line totals +
unique-file sets and per-language code/comment/docstring breakdowns, then
computes a summary with division-by-zero-safe percentages. Coverage drives
real aggregation maths: totals, file de-duplication, the None-category→code
default, non-supported file types, percentage computation incl. the zero
guards and the docstring>0 vs ==0 arcs, record_file, and reset().

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.directory_analyzer.statistics_collector import DirectoryStatisticsCollector


@pytest.fixture
def collector():
    """A fresh DirectoryStatisticsCollector."""
    return DirectoryStatisticsCollector()


class TestDebugLogging:
    """debug=True exercises the constructor/reset log branches."""

    def test_debug_init_logs( self, capsys ):
        """Ensures: debug=True emits an init banner."""
        DirectoryStatisticsCollector( debug=True )
        assert "Initialized" in capsys.readouterr().out

    def test_debug_reset_logs( self, capsys ):
        """Ensures: debug=True emits a reset banner."""
        DirectoryStatisticsCollector( debug=True ).reset()
        assert "reset" in capsys.readouterr().out.lower()


class TestRecordLine:
    """record_line feeds per-file-type totals + per-language breakdowns."""

    def test_supported_language_categories_counted( self, collector ):
        """
        Ensures:
            - explicit code/comment/docstring categories increment per-language
            - the per-file-type total increments for each recorded line
        """
        collector.record_line( "python", line_category="code" )
        collector.record_line( "python", line_category="comment" )
        collector.record_line( "python", line_category="docstring" )
        py = collector.get_summary()[ "language_details" ][ "python" ]
        assert py[ "code" ] == 1
        assert py[ "comment" ] == 1
        assert py[ "docstring" ] == 1
        assert py[ "total" ] == 3

    def test_none_category_counts_as_code( self, collector ):
        """
        Ensures:
            - a supported-language line with line_category=None defaults to code
              (the `elif line_category is None` arc)
        """
        collector.record_line( "python", line_category=None )
        py = collector.get_summary()[ "language_details" ][ "python" ]
        assert py[ "code" ] == 1
        assert py[ "total" ] == 1

    def test_invalid_category_counts_total_but_no_subcategory( self, collector ):
        """
        Ensures:
            - a supported-language line with a non-None category that is NOT
              one of code/comment/docstring falls through both branches (the
              `elif line_category is None` false arc): the language total still
              increments, but no code/comment/docstring sub-counter does
        """
        collector.record_line( "python", line_category="bogus" )
        py = collector.get_summary()[ "language_details" ][ "python" ]
        assert py[ "total" ] == 1
        assert py[ "code" ] == 0
        assert py[ "comment" ] == 0
        assert py[ "docstring" ] == 0

    def test_non_supported_file_type_only_counts_total( self, collector ):
        """
        Ensures:
            - a non-code file type (markdown) increments the overall/file-type
              total but never appears in language_details
        """
        collector.record_line( "markdown", line_category="code" )
        summary = collector.get_summary()
        assert summary[ "overall" ][ "total_lines" ] == 1
        assert "markdown" not in summary[ "language_details" ]

    def test_file_path_tracked_and_deduplicated( self, collector ):
        """
        Ensures:
            - distinct file_path values are tracked once each (set semantics)
            - total_files counts unique files, not lines
        """
        collector.record_line( "python", line_category="code", file_path="a.py" )
        collector.record_line( "python", line_category="code", file_path="a.py" )
        collector.record_line( "python", line_category="code", file_path="b.py" )
        summary = collector.get_summary()
        assert summary[ "overall" ][ "total_files" ] == 2
        assert summary[ "overall" ][ "total_lines" ] == 3


class TestRecordFile:
    """record_file tracks a file without counting a line."""

    def test_record_file_tracks_without_line( self, collector ):
        """
        Ensures:
            - record_file adds the file to the type's set
            - total_files reflects it while total_lines stays 0
        """
        collector.record_file( "python", "empty.py" )
        summary = collector.get_summary()
        assert summary[ "overall" ][ "total_files" ] == 1
        assert summary[ "overall" ][ "total_lines" ] == 0


class TestGetSummaryBreakdown:
    """Breakdown carries per-type totals/files/percentage, sorted desc."""

    def test_percentage_and_file_counts( self, collector ):
        """
        Ensures:
            - per-type percentage is total/total_lines*100
            - per-type file count comes from the tracking set
        """
        collector.record_line( "python", line_category="code", file_path="a.py" )
        collector.record_line( "python", line_category="code", file_path="a.py" )
        collector.record_line( "markdown", file_path="r.md" )
        rows = { r[ "file_type" ]: r for r in collector.get_summary()[ "by_file_type" ] }
        assert rows[ "python" ][ "total" ] == 2
        assert rows[ "python" ][ "files" ] == 1
        assert abs( rows[ "python" ][ "percentage" ] - (100.0 * 2 / 3) ) < 1e-9

    def test_sorted_by_total_desc( self, collector ):
        """Ensures: file types are ordered by line total, descending."""
        collector.record_line( "markdown" )
        collector.record_line( "python", line_category="code" )
        collector.record_line( "python", line_category="code" )
        order = [ r[ "file_type" ] for r in collector.get_summary()[ "by_file_type" ] ]
        assert order[ 0 ] == "python"

    def test_empty_collector_zero_percentage_guard( self, collector ):
        """
        Ensures:
            - with no records, overall totals are zero and there are no rows
              (exercises the total_lines==0 → pct 0.0 guard path safely)
        """
        summary = collector.get_summary()
        assert summary[ "overall" ] == { "total_lines": 0, "total_files": 0 }
        assert summary[ "by_file_type" ] == []
        assert summary[ "language_details" ] == {}


class TestGetSummaryLanguageDetails:
    """Language details compute percentages with zero + docstring guards."""

    def test_percentages_with_docstring( self, collector ):
        """
        Ensures:
            - code/comment/docstring percentages computed over total
            - the docstring>0 arc emits a real docstring percentage
        """
        for _ in range( 2 ):
            collector.record_line( "python", line_category="code" )
        collector.record_line( "python", line_category="comment" )
        collector.record_line( "python", line_category="docstring" )
        py = collector.get_summary()[ "language_details" ][ "python" ]
        assert py[ "percentages" ][ "code" ] == 50.0
        assert py[ "percentages" ][ "comment" ] == 25.0
        assert py[ "percentages" ][ "docstring" ] == 25.0

    def test_percentages_without_docstring_sets_zero( self, collector ):
        """
        Ensures:
            - when docstring==0 (but total>0), the docstring percentage is
              explicitly 0.0 (the `else` arc of the docstring>0 check)
        """
        collector.record_line( "javascript", line_category="code" )
        js = collector.get_summary()[ "language_details" ][ "javascript" ]
        assert js[ "docstring" ] == 0
        assert js[ "percentages" ][ "docstring" ] == 0.0
        assert js[ "percentages" ][ "code" ] == 100.0


class TestReset:
    """reset() clears all accumulated state."""

    def test_reset_clears_everything( self, collector ):
        """Ensures: after reset, totals/breakdown/files/languages are empty."""
        collector.record_line( "python", line_category="code", file_path="a.py" )
        collector.reset()
        summary = collector.get_summary()
        assert summary[ "overall" ] == { "total_lines": 0, "total_files": 0 }
        assert summary[ "by_file_type" ] == []
        assert summary[ "language_details" ] == {}
