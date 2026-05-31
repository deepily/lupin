"""
Unit tests for cosa.repo.git_loc_delta.report_formatter.

Real public surface (verified via live introspection, not a rendered Read):
    format_console(daily, summary, since=None, until=None, branch=None, rev_range=None) -> str
    format_json(daily, summary, since=None, until=None, branch=None, rev_range=None, repo_path=None) -> str
    print_console_banner(title) -> None

Pure string/JSON rendering — no I/O. Tests assert on the rendered content:
title-line branches (since+until / since / until / neither), optional
branch/rev_range lines, the empty "No commits" path, both tables with the
net-sign branches (positive vs negative), JSON validity + date-ascending
ordering, and the banner delegate.

Authored by Sam 🎙️ for the CoSA 100% coverage campaign (git_loc_delta group).
Reviewed by Mr. Radio (no self-audit).
"""
import json
from unittest.mock import patch

from cosa.repo.git_loc_delta import report_formatter as rf


def _day( added, deleted, files=1, commits=1, by_file_type=None ):
    return {
        "added": added, "deleted": deleted, "files_touched": files, "commits": commits,
        "by_file_type": by_file_type if by_file_type is not None else [
            { "file_type": "python", "added": added, "deleted": deleted,
              "files_touched": files, "commits": commits },
        ],
    }


def _summary( ta, td, tf=1, tc=1, days=1 ):
    return {
        "total_added": ta, "total_deleted": td, "total_files": tf,
        "total_commits": tc, "total_days": days, "net": ta - td,
    }


class TestFormatConsoleTitle:
    """The header title-line assembles from since/until presence."""

    def test_since_and_until( self ):
        out = rf.format_console( {}, _summary( 0, 0 ), since="2026-05-01", until="2026-05-31" )
        assert "2026-05-01 .. 2026-05-31" in out

    def test_since_only( self ):
        out = rf.format_console( {}, _summary( 0, 0 ), since="2026-05-01" )
        assert "since 2026-05-01" in out

    def test_until_only( self ):
        out = rf.format_console( {}, _summary( 0, 0 ), until="2026-05-31" )
        assert "until 2026-05-31" in out

    def test_neither_is_bare_title( self ):
        out = rf.format_console( {}, _summary( 0, 0 ) )
        assert "Daily LoC Delta" in out
        assert "—" not in out          # no range suffix appended


class TestFormatConsoleBody:
    """Branch/range lines, empty path, the two tables, net-sign branches."""

    def test_branch_and_rev_range_lines( self ):
        out = rf.format_console( {}, _summary( 0, 0 ), branch="wip-x", rev_range="main..wip-x" )
        assert "Branch: wip-x" in out
        assert "Range: main..wip-x" in out

    def test_empty_daily_is_no_commits( self ):
        out = rf.format_console( {}, _summary( 0, 0 ) )
        assert "No commits in range." in out
        assert "Daily Totals" not in out

    def test_tables_rendered_with_positive_net( self ):
        daily = { "2026-05-16": _day( 100, 10 ) }
        out = rf.format_console( daily, _summary( 100, 10 ) )
        assert "Daily Totals" in out
        assert "By Date × File Type" in out
        assert "TOTAL" in out
        assert "python" in out
        day_line = [ l for l in out.splitlines() if "2026-05-16" in l ][ 0 ]
        assert "+" in day_line and "90" in day_line   # net +90 (right-justified)

    def test_negative_net_has_no_plus_sign( self ):
        # a day + summary where deletions exceed additions exercises the
        # `sign = "+" if net >= 0 else ""` else-branch (both per-day and TOTAL).
        daily = { "2026-05-16": _day( 5, 20 ) }
        out = rf.format_console( daily, _summary( 5, 20 ) )
        lines = [ l for l in out.splitlines() if "2026-05-16" in l ]
        assert lines and "+" not in lines[ 0 ]   # net -15, no plus
        total_line = [ l for l in out.splitlines() if "TOTAL" in l ][ 0 ]
        assert "+" not in total_line

    def test_multiple_dates_sorted_ascending( self ):
        daily = { "2026-05-18": _day( 1, 0 ), "2026-05-16": _day( 2, 0 ) }
        out = rf.format_console( daily, _summary( 3, 0, days=2 ) )
        i16 = out.index( "2026-05-16" )
        i18 = out.index( "2026-05-18" )
        assert i16 < i18


class TestFormatJson:
    """format_json — validity, ordering, optional fields, passthrough."""

    def test_valid_json_with_summary_and_days( self ):
        daily = { "2026-05-16": _day( 10, 2 ) }
        parsed = json.loads(
            rf.format_json( daily, _summary( 10, 2 ), since="2026-05-01", repo_path="/ext/repo" )
        )
        assert parsed[ "since" ] == "2026-05-01"
        assert parsed[ "repo_path" ] == "/ext/repo"
        assert parsed[ "summary" ][ "net" ] == 8
        assert len( parsed[ "days" ] ) == 1
        assert parsed[ "days" ][ 0 ][ "by_file_type" ][ 0 ][ "file_type" ] == "python"

    def test_days_sorted_ascending( self ):
        daily = { "2026-05-18": _day( 1, 0 ), "2026-05-16": _day( 2, 0 ) }
        parsed = json.loads( rf.format_json( daily, _summary( 3, 0, days=2 ) ) )
        assert [ d[ "date" ] for d in parsed[ "days" ] ] == [ "2026-05-16", "2026-05-18" ]

    def test_optional_fields_default_null( self ):
        parsed = json.loads( rf.format_json( {}, _summary( 0, 0 ) ) )
        for k in ( "since", "until", "branch", "rev_range", "repo_path" ):
            assert parsed[ k ] is None


class TestPrintConsoleBanner:
    """print_console_banner delegates to du.print_banner."""

    def test_delegates_with_prepend_nl( self ):
        with patch( "cosa.repo.git_loc_delta.report_formatter.du.print_banner" ) as banner:
            rf.print_console_banner( "My Title" )
        banner.assert_called_once_with( "My Title", prepend_nl=True )
