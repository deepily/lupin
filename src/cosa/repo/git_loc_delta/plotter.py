"""
Plotter — branch LoC delta visualization for the Daily LoC Delta tool.

Library-shape rendering layer. Consumes the `daily` + `summary` dicts produced
by `DailyAggregator` and emits a two-panel matplotlib PNG:

    Top panel — aggregate per-day insertions / deletions bars + net line
    Bottom panel — signed per-key net lines (one line per file_type, or per
                   repo for the future global-aggregator variant)

The `group_by` parameter selects which key drives the bottom panel:
    "file_type"  — bottom = lines per file_type (default; per-branch use)
    "repo"       — bottom = lines per repo (global aggregator use)

The caller passes pre-aggregated dicts — the plotter does no CSV I/O. This
keeps it reusable by both `run_git_loc_delta.py` (per-branch) and a future
`run_git_loc_delta_global.py` aggregator (cross-repo daily rollup) that
builds an equivalent `daily` dict from concat'd per-repo CSVs.

Authored 2026-05-21 by Rachel 🕊️ (session e13fed4f) extending María's
`git_loc_delta` package per cross-session DM-thread design with María.
Plan: cosa/rnd/2026.05.16-daily-loc-delta-tool.md (Plot extension section
to be added in the same pass).
"""

import os
from typing  import Dict, Optional
from pathlib import Path

import matplotlib.dates  as mdates
import matplotlib.pyplot as plt

import cosa.utils.util as du


# Module-level constants — kept here so callers can read them without
# instantiating any state. matplotlib's tab10 wraps at 10 colors; we
# fall back to tab20 (20 colors) for high-cardinality grouping.
_TAB10_SIZE = 10
_TAB20_SIZE = 20

_BAR_COLOR_INSERTIONS = "#4CAF50"
_BAR_COLOR_DELETIONS  = "#E53935"
_LINE_COLOR_NET       = "black"
_ZERO_LINE_COLOR      = "#999"


def plot_summary(
    daily:       Dict[str, dict],
    summary:     dict,
    output_path: str,
    group_by:    str               = "file_type",
    title_meta:  Optional[dict]    = None,
    debug:       bool              = False,
) -> str:
    """
    Render a two-panel branch LoC delta plot to PNG.

    Requires:
        - daily is dict[date_str -> {added, deleted, files_touched, commits,
          by_{group_by}: [{<group_by>, added, deleted, ...}, ...]}]
          where date_str is YYYY-MM-DD. The `by_{group_by}` list may be empty
          on days with no activity. Single-day daily dicts (len == 1) are
          rejected — caller must filter.
        - summary is the dict produced by DailyAggregator.summary()
        - output_path is a writable filesystem path ending in .png
        - group_by is "file_type" (default) or "repo"
        - title_meta is None or a dict with scope-dependent shape (see _format_title)

    Ensures:
        - PNG written at output_path (parent dir created if missing)
        - Returns the absolute path written
        - figure is closed (no matplotlib state leakage)

    Raises:
        - ValueError if daily has fewer than 2 dates (plots need a time axis)
        - ValueError if group_by is not "file_type" or "repo"
        - KeyError if a daily entry is missing the `by_{group_by}` field
          (callers should ensure their aggregator populates the field)
    """
    if group_by not in ( "file_type", "repo" ):
        raise ValueError( f"group_by must be 'file_type' or 'repo', got {group_by!r}" )

    if len( daily ) < 2:
        raise ValueError(
            f"plot_summary requires >= 2 dates, got {len(daily)}. "
            "Single-day data should use console / json output instead."
        )

    # ── Build axis data
    sorted_dates = sorted( daily.keys() )
    dates_dt     = [ _parse_date( d ) for d in sorted_dates ]
    added_v      = [  daily[d][ "added"   ] for d in sorted_dates ]
    deleted_v    = [ -daily[d][ "deleted" ] for d in sorted_dates ]   # negate → below-zero bars
    net_v        = [  daily[d][ "added"   ] - daily[d][ "deleted" ] for d in sorted_dates ]

    # ── Build per-group time series for the bottom panel
    by_key = f"by_{group_by}"
    per_group = _build_per_group_series( daily, sorted_dates, by_key, group_by )

    if debug:
        du.print_banner( f"plot_summary debug — {len(sorted_dates)} dates, {len(per_group)} groups by {group_by}", prepend_nl=True )

    # ── Create figure + axes
    fig, ( ax_top, ax_bot ) = plt.subplots(
        nrows       = 2,
        ncols       = 1,
        figsize     = ( 14, 9 ),
        sharex      = True,
        gridspec_kw = { "height_ratios": [ 1, 1 ], "hspace": 0.18 }
    )

    _render_aggregate_panel( ax_top, dates_dt, added_v, deleted_v, net_v )
    _render_grouped_panel(   ax_bot, dates_dt, per_group, group_by )

    # ── x-axis formatting (shared)
    n_days = len( sorted_dates )
    ax_bot.xaxis.set_major_locator(   mdates.DayLocator( interval=max( 1, n_days // 14 ) ) )
    ax_bot.xaxis.set_major_formatter( mdates.DateFormatter( "%m-%d" ) )
    fig.autofmt_xdate( rotation=45 )

    # ── Suptitle
    fallback_stem = Path( output_path ).stem
    suptitle      = _format_title( title_meta, summary, fallback_stem )
    fig.suptitle( suptitle, fontsize=13, fontweight="bold", y=0.995 )

    # ── Save
    parent = os.path.dirname( output_path )
    if parent and not os.path.isdir( parent ):
        os.makedirs( parent, exist_ok=True )
        if debug: print( f"[plotter] Created directory: {parent}" )

    plt.savefig( output_path, dpi=120, bbox_inches="tight" )
    plt.close( fig )

    abs_path = os.path.abspath( output_path )
    if debug: print( f"[plotter] Wrote {abs_path}" )
    return abs_path


def _parse_date( date_str: str ):
    """
    Parse a YYYY-MM-DD date string into a datetime.date.

    Ensures:
        - Returns a datetime.date object
        - Raises ValueError on malformed input (delegated to datetime)
    """
    from datetime import datetime
    return datetime.strptime( date_str, "%Y-%m-%d" ).date()


def _build_per_group_series(
    daily:        Dict[str, dict],
    sorted_dates: list,
    by_key:       str,
    group_key:    str,
) -> Dict[str, list]:
    """
    Build per-group time series with zero-fill across missing days.

    Requires:
        - daily, sorted_dates as in plot_summary
        - by_key is "by_file_type" or "by_repo"
        - group_key is "file_type" or "repo" (the row-level key inside the by_key list)

    Ensures:
        - Returns dict[group_value -> list of (date, signed_net)] ordered
          by sorted_dates. Missing days zero-filled.
        - Groups ordered by total absolute churn descending (legend prominence)
    """
    raw: Dict[str, Dict[str, int]] = {}

    for date_str in sorted_dates:
        day = daily[ date_str ]
        if by_key not in day:
            raise KeyError(
                f"daily[{date_str!r}] is missing {by_key!r} — "
                f"caller must populate this field for group_by={group_key!r}"
            )
        for row in day[ by_key ]:
            key = row[ group_key ]
            net = row[ "added" ] - row[ "deleted" ]
            raw.setdefault( key, {} )[ date_str ] = net

    # Zero-fill across all sorted_dates
    filled = {}
    for key, day_map in raw.items():
        filled[ key ] = [ ( _parse_date( d ), day_map.get( d, 0 ) ) for d in sorted_dates ]

    # Order keys by total absolute churn descending (legend prominence)
    ordered_keys = sorted(
        filled.keys(),
        key = lambda k: -sum( abs( v ) for _, v in filled[ k ] )
    )
    return { k: filled[ k ] for k in ordered_keys }


def _render_aggregate_panel( ax, dates_dt, added_v, deleted_v, net_v ) -> None:
    """
    Render the top (aggregate) panel: bars + net line.

    Ensures:
        - ax populated with insertions (positive green bars), deletions
          (negative red bars), and a thick black net line with markers
        - Legend rendered in upper-left
        - Zero line drawn for reference
    """
    bar_w = 0.7
    ax.bar(  dates_dt, added_v,   width=bar_w, color=_BAR_COLOR_INSERTIONS, alpha=0.55, label="Insertions" )
    ax.bar(  dates_dt, deleted_v, width=bar_w, color=_BAR_COLOR_DELETIONS,  alpha=0.55, label="Deletions"  )
    ax.plot( dates_dt, net_v,     color=_LINE_COLOR_NET, linewidth=2.5, marker="o", markersize=4, label="Net" )
    ax.axhline( 0, color=_ZERO_LINE_COLOR, linewidth=0.8 )

    ax.set_ylabel( "Lines of code" )
    ax.set_title( "Aggregate — insertions / deletions / net", loc="left", fontsize=11, fontweight="bold" )
    ax.legend( loc="upper left", framealpha=0.9, fontsize=9 )
    ax.grid( axis="y", alpha=0.3 )


def _render_grouped_panel( ax, dates_dt, per_group, group_by ) -> None:
    """
    Render the bottom (grouped) panel: signed net line per group.

    Ensures:
        - One colored line + markers per group (ordered by total churn)
        - tab10 palette below 10 groups, tab20 between 10 and 20, distinct
          colors via HSV for >20 groups
        - Legend rendered in upper-left, 2 columns when >5 groups
        - Zero line drawn for reference
    """
    n_groups = len( per_group )
    cmap     = _select_cmap( n_groups )

    for i, ( key, points ) in enumerate( per_group.items() ):
        d_axis = [ p[ 0 ] for p in points ]
        v_axis = [ p[ 1 ] for p in points ]
        ax.plot(
            d_axis, v_axis,
            color      = cmap( i ),
            marker     = "o",
            markersize = 3.5,
            linewidth  = 1.6,
            label      = key
        )

    ax.axhline( 0, color=_ZERO_LINE_COLOR, linewidth=0.8 )
    ax.set_ylabel( "Lines of code (signed)" )
    ax.set_title( f"Per-{group_by} net (added − deleted)", loc="left", fontsize=11, fontweight="bold" )

    legend_cols = 2 if n_groups > 5 else 1
    ax.legend( loc="upper left", framealpha=0.9, fontsize=9, ncol=legend_cols )
    ax.grid( axis="y", alpha=0.3 )


def _select_cmap( n_groups: int ):
    """
    Pick a colormap function that produces distinct colors for n_groups items.

    Ensures:
        - Returns a callable cmap(i) -> RGBA tuple
        - Sized by n_groups: tab10 for ≤10, tab20 for 11-20, HSV for >20
    """
    if n_groups <= _TAB10_SIZE:
        base = plt.get_cmap( "tab10" )
        return lambda i: base( i % _TAB10_SIZE )
    if n_groups <= _TAB20_SIZE:
        base = plt.get_cmap( "tab20" )
        return lambda i: base( i % _TAB20_SIZE )
    # >20 groups: evenly spaced HSV
    base = plt.get_cmap( "hsv" )
    return lambda i: base( ( i / max( 1, n_groups - 1 ) ) % 1.0 )


def _format_title( title_meta: Optional[dict], summary: dict, fallback_stem: str ) -> str:
    """
    Build the suptitle string from title_meta + summary.

    Ensures:
        - title_meta None → falls back to "git_loc_delta — {fallback_stem}"
        - title_meta["scope"] == "branch" → "{repo} / {branch} · {since}..{until} · {net:+d} net, {commits} commits"
        - title_meta["scope"] == "global" → "global · {n} repos · {rev_window} · {net:+d} net, {commits} commits"
        - Missing fields in title_meta tolerated (skipped, not raised)
    """
    if title_meta is None:
        return f"git_loc_delta — {fallback_stem}"

    scope = title_meta.get( "scope" )
    net   = summary.get( "net", 0 )
    cmts  = summary.get( "total_commits", 0 )

    if scope == "branch":
        repo   = title_meta.get( "repo",   "?" )
        branch = title_meta.get( "branch", "?" )
        since  = title_meta.get( "since",  "?" )
        until  = title_meta.get( "until",  "?" )
        return f"git_loc_delta — {repo} / {branch} · {since}..{until} · {net:+d} net, {cmts} commits"

    if scope == "global":
        repos      = title_meta.get( "repos",      [] )
        rev_window = title_meta.get( "rev_window", "?" )
        return f"git_loc_delta — global · {len(repos)} repos · {rev_window} · {net:+d} net, {cmts} commits"

    # Unknown scope — defensive fallback
    return f"git_loc_delta — {fallback_stem}"


def quick_smoke_test():
    """
    Quick smoke test for the plotter.

    Synthesizes a tiny daily dict + summary, runs plot_summary() with both
    group_by modes, and verifies the output PNG was written.

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Uses cu.print_banner formatting
        - Does NOT raise (catches all exceptions)
        - Cleans up the temp output files on success
    """
    import tempfile

    du.print_banner( "Plotter Smoke Test", prepend_nl=True )

    # Synthesize 5-day test data
    test_daily = {
        "2026-05-17": {
            "added":         300,  "deleted":         50,
            "files_touched": 4,    "commits":         2,
            "by_file_type": [
                { "file_type": "python",   "added": 250, "deleted": 40, "files_touched": 3, "commits": 2 },
                { "file_type": "markdown", "added": 50,  "deleted": 10, "files_touched": 1, "commits": 1 },
            ],
            "by_repo": [
                { "repo": "cosa",  "added": 200, "deleted": 30, "files_touched": 2, "commits": 1 },
                { "repo": "lupin", "added": 100, "deleted": 20, "files_touched": 2, "commits": 1 },
            ],
        },
        "2026-05-18": {
            "added":         150,  "deleted":         200,
            "files_touched": 3,    "commits":         1,
            "by_file_type": [
                { "file_type": "python",   "added": 100, "deleted": 180, "files_touched": 2, "commits": 1 },
                { "file_type": "markdown", "added": 50,  "deleted": 20,  "files_touched": 1, "commits": 1 },
            ],
            "by_repo": [
                { "repo": "cosa",  "added": 50,  "deleted": 100, "files_touched": 1, "commits": 1 },
                { "repo": "lupin", "added": 100, "deleted": 100, "files_touched": 2, "commits": 1 },
            ],
        },
        "2026-05-19": {
            "added":         500,  "deleted":         100,
            "files_touched": 6,    "commits":         3,
            "by_file_type": [
                { "file_type": "python",     "added": 350, "deleted": 80, "files_touched": 4, "commits": 2 },
                { "file_type": "markdown",   "added": 100, "deleted": 15, "files_touched": 1, "commits": 1 },
                { "file_type": "typescript", "added": 50,  "deleted": 5,  "files_touched": 1, "commits": 1 },
            ],
            "by_repo": [
                { "repo": "cosa",  "added": 300, "deleted": 50, "files_touched": 3, "commits": 2 },
                { "repo": "lupin", "added": 200, "deleted": 50, "files_touched": 3, "commits": 1 },
            ],
        },
        "2026-05-20": {
            "added":         800,  "deleted":         60,
            "files_touched": 5,    "commits":         2,
            "by_file_type": [
                { "file_type": "python",     "added": 600, "deleted": 50, "files_touched": 3, "commits": 1 },
                { "file_type": "markdown",   "added": 200, "deleted": 10, "files_touched": 2, "commits": 1 },
            ],
            "by_repo": [
                { "repo": "cosa",  "added": 800, "deleted": 60, "files_touched": 5, "commits": 2 },
            ],
        },
        "2026-05-21": {
            "added":         400,  "deleted":         30,
            "files_touched": 3,    "commits":         1,
            "by_file_type": [
                { "file_type": "python", "added": 400, "deleted": 30, "files_touched": 3, "commits": 1 },
            ],
            "by_repo": [
                { "repo": "cosa", "added": 400, "deleted": 30, "files_touched": 3, "commits": 1 },
            ],
        },
    }
    test_summary = {
        "total_added":   2150,
        "total_deleted": 440,
        "total_files":   21,
        "total_commits": 9,
        "total_days":    5,
        "net":           1710,
    }
    test_title_meta_branch = {
        "scope":  "branch",
        "repo":   "cosa",
        "branch": "wip-v0.1.7-test",
        "since":  "2026-05-17",
        "until":  "2026-05-21",
    }
    test_title_meta_global = {
        "scope":      "global",
        "repos":      [ "cosa", "lupin" ],
        "rev_window": "2026-05-17..2026-05-21",
    }

    try:
        # Test 1: group_by="file_type" with branch-scope title
        print( "Test 1: group_by='file_type' branch-scope title..." )
        with tempfile.NamedTemporaryFile( suffix="-test-ft.png", delete=False ) as tmp:
            tmp_path = tmp.name
        out_path = plot_summary(
            daily       = test_daily,
            summary     = test_summary,
            output_path = tmp_path,
            group_by    = "file_type",
            title_meta  = test_title_meta_branch,
        )
        assert os.path.isfile( out_path )
        assert os.path.getsize( out_path ) > 1000  # non-trivial PNG size
        print( f"✓ file_type plot rendered ({os.path.getsize(out_path)} bytes)" )
        os.unlink( out_path )

        # Test 2: group_by="repo" with global-scope title
        print( "Test 2: group_by='repo' global-scope title..." )
        with tempfile.NamedTemporaryFile( suffix="-test-repo.png", delete=False ) as tmp:
            tmp_path = tmp.name
        out_path = plot_summary(
            daily       = test_daily,
            summary     = test_summary,
            output_path = tmp_path,
            group_by    = "repo",
            title_meta  = test_title_meta_global,
        )
        assert os.path.isfile( out_path )
        assert os.path.getsize( out_path ) > 1000
        print( f"✓ repo plot rendered ({os.path.getsize(out_path)} bytes)" )
        os.unlink( out_path )

        # Test 3: title_meta=None falls back to stem
        print( "Test 3: title_meta=None stem fallback..." )
        with tempfile.NamedTemporaryFile( suffix="-fallback.png", delete=False ) as tmp:
            tmp_path = tmp.name
        out_path = plot_summary(
            daily       = test_daily,
            summary     = test_summary,
            output_path = tmp_path,
            group_by    = "file_type",
            title_meta  = None,
        )
        assert os.path.isfile( out_path )
        print( "✓ stem fallback rendered" )
        os.unlink( out_path )

        # Test 4: Single-day data rejected
        print( "Test 4: single-day rejection..." )
        try:
            plot_summary(
                daily       = { "2026-05-21": test_daily[ "2026-05-21" ] },
                summary     = test_summary,
                output_path = "/tmp/should-not-exist.png",
                group_by    = "file_type",
            )
            print( "✗ single-day did not raise ValueError" )
        except ValueError as e:
            assert ">= 2 dates" in str( e )
            print( "✓ single-day raised ValueError correctly" )

        # Test 5: Invalid group_by rejected
        print( "Test 5: invalid group_by rejection..." )
        try:
            plot_summary(
                daily       = test_daily,
                summary     = test_summary,
                output_path = "/tmp/should-not-exist.png",
                group_by    = "nonsense",
            )
            print( "✗ invalid group_by did not raise ValueError" )
        except ValueError as e:
            assert "group_by must be" in str( e )
            print( "✓ invalid group_by raised ValueError correctly" )

        # Test 6: Title formatting matrix
        print( "Test 6: title formatting matrix..." )
        t_branch = _format_title( test_title_meta_branch, test_summary, "stem" )
        assert "cosa" in t_branch and "wip-v0.1.7-test" in t_branch and "+1710" in t_branch
        t_global = _format_title( test_title_meta_global, test_summary, "stem" )
        assert "global" in t_global and "2 repos" in t_global and "+1710" in t_global
        t_none = _format_title( None, test_summary, "stem" )
        assert t_none == "git_loc_delta — stem"
        print( "✓ title formatting correct across 3 modes" )

        print( "\n✓ All plotter smoke tests passed successfully!" )

    except AssertionError as e:
        print( f"\n✗ Smoke test assertion failed: {e}" )
        import traceback
        traceback.print_exc()
    except Exception as e:
        print( f"\n✗ Smoke test failed with exception: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
