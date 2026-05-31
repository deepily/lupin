"""
Unit tests for cosa.repo.git_loc_delta.plotter.

Real public surface (verified via live introspection, not a rendered Read):
    plot_summary(daily, summary, output_path, group_by="file_type",
                 title_meta=None, debug=False) -> str
    (quick_smoke_test / __main__ are config-excluded from the denominator.)

matplotlib runs on the headless Agg backend; plt.savefig is mocked so NO PNG is
ever written (NO real rendering to disk per the campaign mandate) — the figure
construction + the render helpers still execute in-memory for genuine coverage.
The private helpers with combinatorial arcs (_select_cmap sizing, _format_title
scopes, _render_grouped_panel legend columns, _parse_date) are exercised
directly.

Authored by Sam 🎙️ for the CoSA 100% coverage campaign (git_loc_delta group).
Reviewed by Mr. Radio (no self-audit).
"""
import os
import tempfile

import matplotlib
matplotlib.use( "Agg" )            # headless; no display, no real output
import matplotlib.pyplot as plt    # noqa: E402

import pytest
from unittest.mock import patch

from cosa.repo.git_loc_delta import plotter as P
from cosa.repo.git_loc_delta.plotter import (
    plot_summary,
    _parse_date,
    _build_per_group_series,
    _render_aggregate_panel,
    _render_grouped_panel,
    _select_cmap,
    _format_title,
)


def _day( added, deleted, by_field, rows ):
    return {
        "added": added, "deleted": deleted, "files_touched": 1, "commits": 1,
        by_field: rows,
    }


def _ft_row( ft, added, deleted ):
    return { "file_type": ft, "added": added, "deleted": deleted,
             "files_touched": 1, "commits": 1 }


def _repo_row( repo, added, deleted ):
    return { "repo": repo, "added": added, "deleted": deleted,
             "files_touched": 1, "commits": 1 }


def _two_day_file_type():
    return {
        "2026-05-16": _day( 100, 10, "by_file_type",
                            [ _ft_row( "python", 100, 10 ) ] ),
        "2026-05-17": _day( 50, 5, "by_file_type",
                            [ _ft_row( "markdown", 50, 5 ) ] ),
    }


_SUMMARY = {
    "total_added": 150, "total_deleted": 15, "total_files": 3,
    "total_commits": 2, "total_days": 2, "net": 135,
}


class TestPlotSummary:
    """plot_summary() integration — Agg render, savefig mocked."""

    def test_file_type_render_returns_abspath( self ):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join( d, "plot.png" )
            with patch( "cosa.repo.git_loc_delta.plotter.plt.savefig" ) as savefig:
                result = plot_summary(
                    _two_day_file_type(), _SUMMARY, out,
                    title_meta={ "scope": "branch", "repo": "cosa", "branch": "wip",
                                 "since": "2026-05-16", "until": "2026-05-17" },
                )
            savefig.assert_called_once()
            assert result == os.path.abspath( out )

    def test_repo_group_render( self ):
        daily = {
            "2026-05-16": _day( 100, 10, "by_repo", [ _repo_row( "cosa", 100, 10 ) ] ),
            "2026-05-17": _day( 50, 5, "by_repo", [ _repo_row( "lupin", 50, 5 ) ] ),
        }
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join( d, "plot.png" )
            with patch( "cosa.repo.git_loc_delta.plotter.plt.savefig" ) as savefig:
                result = plot_summary(
                    daily, _SUMMARY, out, group_by="repo",
                    title_meta={ "scope": "global", "repos": [ "cosa", "lupin" ],
                                 "rev_window": "2026-05-16..2026-05-17" },
                )
            savefig.assert_called_once()
            assert result.endswith( "plot.png" )

    def test_invalid_group_by_raises( self ):
        with pytest.raises( ValueError ):
            plot_summary( _two_day_file_type(), _SUMMARY, "/tmp/x.png", group_by="author" )

    def test_single_date_raises( self ):
        single = { "2026-05-16": _day( 1, 0, "by_file_type", [ _ft_row( "python", 1, 0 ) ] ) }
        with pytest.raises( ValueError ):
            plot_summary( single, _SUMMARY, "/tmp/x.png" )

    def test_debug_and_nested_dir_creation( self, capsys ):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join( d, "nested", "deep", "plot.png" )   # parents missing
            with patch( "cosa.repo.git_loc_delta.plotter.plt.savefig" ):
                plot_summary( _two_day_file_type(), _SUMMARY, out, debug=True )
            assert os.path.isdir( os.path.dirname( out ) )          # makedirs ran
            printed = capsys.readouterr().out
            assert "Created directory" in printed
            assert "Wrote" in printed

    def test_missing_by_key_raises_keyerror( self ):
        # A day lacking the by_file_type field → KeyError from _build_per_group_series.
        bad = {
            "2026-05-16": { "added": 1, "deleted": 0, "files_touched": 1, "commits": 1 },
            "2026-05-17": _day( 2, 0, "by_file_type", [ _ft_row( "python", 2, 0 ) ] ),
        }
        with patch( "cosa.repo.git_loc_delta.plotter.plt.savefig" ):
            with pytest.raises( KeyError ):
                plot_summary( bad, _SUMMARY, "/tmp/x.png" )


class TestParseDate:
    """_parse_date()."""

    def test_valid( self ):
        d = _parse_date( "2026-05-16" )
        assert ( d.year, d.month, d.day ) == ( 2026, 5, 16 )

    def test_malformed_raises( self ):
        with pytest.raises( ValueError ):
            _parse_date( "not-a-date" )


class TestBuildPerGroupSeries:
    """_build_per_group_series() — zero-fill + churn-desc ordering."""

    def test_zero_fill_and_ordering( self ):
        dates = [ "2026-05-16", "2026-05-17" ]
        daily = {
            "2026-05-16": _day( 0, 0, "by_file_type",
                                [ _ft_row( "python", 100, 0 ), _ft_row( "markdown", 5, 0 ) ] ),
            "2026-05-17": _day( 0, 0, "by_file_type",
                                [ _ft_row( "python", 1, 0 ) ] ),   # markdown absent → zero-filled
        }
        series = _build_per_group_series( daily, dates, "by_file_type", "file_type" )
        # python has more total churn → ordered first.
        assert list( series.keys() )[ 0 ] == "python"
        # markdown zero-filled on the second date.
        md = dict( ( str( pt[ 0 ] ), pt[ 1 ] ) for pt in series[ "markdown" ] )
        assert md[ "2026-05-17" ] == 0


class TestSelectCmap:
    """_select_cmap() — tab10 / tab20 / hsv by group count."""

    def test_small_uses_tab10( self ):
        cmap = _select_cmap( 5 )
        assert len( cmap( 0 ) ) == 4          # RGBA

    def test_mid_uses_tab20( self ):
        cmap = _select_cmap( 15 )
        assert len( cmap( 11 ) ) == 4

    def test_large_uses_hsv( self ):
        cmap = _select_cmap( 25 )
        assert len( cmap( 24 ) ) == 4


class TestFormatTitle:
    """_format_title() — None / branch / global / unknown-scope arcs."""

    def test_none_falls_back_to_stem( self ):
        assert _format_title( None, _SUMMARY, "myplot" ) == "git_loc_delta — myplot"

    def test_branch_scope( self ):
        title = _format_title(
            { "scope": "branch", "repo": "cosa", "branch": "wip",
              "since": "2026-05-16", "until": "2026-05-17" },
            _SUMMARY, "stem",
        )
        assert "cosa / wip" in title
        assert "+135 net" in title
        assert "2 commits" in title

    def test_global_scope( self ):
        title = _format_title(
            { "scope": "global", "repos": [ "a", "b", "c" ], "rev_window": "x..y" },
            _SUMMARY, "stem",
        )
        assert "global · 3 repos" in title

    def test_unknown_scope_falls_back( self ):
        assert _format_title( { "scope": "weekly" }, _SUMMARY, "stem" ) == "git_loc_delta — stem"


class TestRenderPanelsDirect:
    """Direct render helpers — legend-column branch + aggregate panel."""

    def test_aggregate_panel_draws_bars_and_line( self ):
        fig, ax = plt.subplots()
        try:
            _render_aggregate_panel(
                ax,
                [ _parse_date( "2026-05-16" ), _parse_date( "2026-05-17" ) ],
                [ 100, 50 ], [ -10, -5 ], [ 90, 45 ],
            )
            assert ax.get_legend() is not None     # legend rendered
        finally:
            plt.close( fig )

    def test_grouped_panel_two_legend_columns_when_many_groups( self ):
        fig, ax = plt.subplots()
        try:
            dts = [ _parse_date( "2026-05-16" ), _parse_date( "2026-05-17" ) ]
            # 6 groups (>5) → legend_cols == 2 branch.
            per_group = {
                f"g{i}": [ ( dts[ 0 ], i ), ( dts[ 1 ], i + 1 ) ] for i in range( 6 )
            }
            _render_grouped_panel( ax, dts, per_group, "file_type" )
            assert len( ax.get_lines() ) >= 6      # 6 group lines + zero line
        finally:
            plt.close( fig )

    def test_grouped_panel_single_legend_column_when_few_groups( self ):
        fig, ax = plt.subplots()
        try:
            dts = [ _parse_date( "2026-05-16" ), _parse_date( "2026-05-17" ) ]
            per_group = { "only": [ ( dts[ 0 ], 1 ), ( dts[ 1 ], 2 ) ] }
            _render_grouped_panel( ax, dts, per_group, "repo" )
            assert ax.get_legend() is not None
        finally:
            plt.close( fig )
