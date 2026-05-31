"""
Unit tests for cosa.repo.git_loc_delta.daily_aggregator.

Tests DailyAggregator, which buckets the per-file change stream from
GitLogParser into (date, file_type) cells and per-date rollups, classifying
each path via the real branch_analyzer FileTypeClassifier. Coverage drives the
real single-pass aggregation maths: bucket creation + summation, unique
files/commits per bucket, the daily() rollup (cross-type unique counts +
added-descending sort), summary() totals incl. net, is_empty(), and the debug
log arc.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.git_loc_delta.daily_aggregator import DailyAggregator


def _change( date, sha, path, added, deleted, author="rick@example.com" ):
    """Build a GitLogParser-shaped change row."""
    return {
        "date": date, "sha": sha, "author": author,
        "path": path, "added": added, "deleted": deleted,
    }


@pytest.fixture
def agg():
    """A fresh DailyAggregator (loads the real FileTypeClassifier config)."""
    return DailyAggregator()


class TestRecordAndByType:
    """record() buckets by (date, file_type); by_type() exposes the cells."""

    def test_single_row_creates_bucket( self, agg ):
        """
        Ensures:
            - a single python row creates one (date, 'python') bucket carrying
              added/deleted and unique files_touched=1 / commits=1
        """
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        bt = agg.by_type()
        assert bt[ ( "2026-05-16", "python" ) ] == {
            "added": 10, "deleted": 2, "files_touched": 1, "commits": 1,
        }

    def test_same_bucket_sums_and_dedupes( self, agg ):
        """
        Ensures:
            - two rows in the same (date,type) bucket sum added/deleted
            - the same path counted once (files_touched), distinct SHAs counted
              separately (commits)
        """
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        agg.record( _change( "2026-05-16", "sha2", "src/a.py", 5, 1 ) )   # same path, new sha
        cell = agg.by_type()[ ( "2026-05-16", "python" ) ]
        assert cell[ "added" ] == 15
        assert cell[ "deleted" ] == 3
        assert cell[ "files_touched" ] == 1     # one unique path
        assert cell[ "commits" ] == 2           # two unique shas

    def test_distinct_file_types_separate_buckets( self, agg ):
        """Ensures: a python row and a markdown row land in distinct buckets."""
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        agg.record( _change( "2026-05-16", "sha1", "docs/r.md", 3, 0 ) )
        bt = agg.by_type()
        assert ( "2026-05-16", "python" ) in bt
        assert ( "2026-05-16", "markdown" ) in bt

    def test_by_type_returns_fresh_dict( self, agg ):
        """Ensures: mutating the by_type() result does not corrupt internal state."""
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        snap = agg.by_type()
        snap.clear()
        assert agg.by_type()  # still populated

    def test_debug_logs_each_row( self, capsys ):
        """Ensures: debug=True logs a per-row line."""
        a = DailyAggregator( debug=True )
        a.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        assert "DailyAggregator" in capsys.readouterr().out

    def test_string_counts_coerced_to_int( self, agg ):
        """
        Ensures:
            - added/deleted given as strings are coerced to int (the int()
              calls in record), so sums stay numeric
        """
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", "10", "2" ) )
        assert agg.by_type()[ ( "2026-05-16", "python" ) ][ "added" ] == 10


class TestDaily:
    """daily() rolls buckets up per date with a sorted by_file_type breakdown."""

    def test_per_date_rollup_unique_across_types( self, agg ):
        """
        Ensures:
            - date-level added/deleted sum across file types
            - files_touched / commits count UNIQUE entries across all types
              (a sha touching both a .py and a .md counts once for the date)
        """
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        agg.record( _change( "2026-05-16", "sha1", "docs/r.md", 3, 1 ) )  # same sha, diff type
        day = agg.daily()[ "2026-05-16" ]
        assert day[ "added" ] == 13
        assert day[ "deleted" ] == 3
        assert day[ "commits" ] == 1            # one unique sha across both types
        assert day[ "files_touched" ] == 2      # two distinct paths

    def test_by_file_type_sorted_by_added_desc( self, agg ):
        """Ensures: each date's by_file_type rows are ordered by added descending."""
        agg.record( _change( "2026-05-16", "sha1", "small.md", 1, 0 ) )
        agg.record( _change( "2026-05-16", "sha1", "big.py", 100, 0 ) )
        rows = agg.daily()[ "2026-05-16" ][ "by_file_type" ]
        assert rows[ 0 ][ "file_type" ] == "python"
        assert rows[ 0 ][ "added" ] == 100
        assert rows[ 1 ][ "file_type" ] == "markdown"

    def test_dates_sorted_ascending( self, agg ):
        """Ensures: daily() keys come back in ascending date order."""
        agg.record( _change( "2026-05-18", "s3", "c.py", 1, 0 ) )
        agg.record( _change( "2026-05-16", "s1", "a.py", 1, 0 ) )
        agg.record( _change( "2026-05-17", "s2", "b.py", 1, 0 ) )
        assert list( agg.daily().keys() ) == [ "2026-05-16", "2026-05-17", "2026-05-18" ]

    def test_empty_daily_is_empty_dict( self, agg ):
        """Ensures: with nothing recorded, daily() is an empty dict."""
        assert agg.daily() == {}


class TestSummary:
    """summary() returns overall totals across the whole range."""

    def test_totals_and_net( self, agg ):
        """
        Ensures:
            - total_added/deleted sum all buckets; net = added - deleted
            - total_files/commits count unique across everything
            - total_days counts distinct dates
        """
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 10, 2 ) )
        agg.record( _change( "2026-05-17", "sha2", "src/a.py", 5, 8 ) )   # same path, new day+sha
        s = agg.summary()
        assert s[ "total_added" ] == 15
        assert s[ "total_deleted" ] == 10
        assert s[ "net" ] == 5
        assert s[ "total_files" ] == 1          # one unique path overall
        assert s[ "total_commits" ] == 2
        assert s[ "total_days" ] == 2

    def test_empty_summary_zeros( self, agg ):
        """Ensures: an empty aggregator reports all-zero totals."""
        assert agg.summary() == {
            "total_added": 0, "total_deleted": 0, "total_files": 0,
            "total_commits": 0, "total_days": 0, "net": 0,
        }


class TestIsEmpty:
    """is_empty() reflects whether any row was recorded."""

    def test_true_before_record( self, agg ):
        """Ensures: a fresh aggregator is empty."""
        assert agg.is_empty() is True

    def test_false_after_record( self, agg ):
        """Ensures: after one record, is_empty() is False."""
        agg.record( _change( "2026-05-16", "sha1", "src/a.py", 1, 0 ) )
        assert agg.is_empty() is False
