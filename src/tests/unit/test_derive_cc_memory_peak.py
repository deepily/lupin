"""
Unit tests for src/scripts/derive_cc_memory_peak.py.

The denominator test is the point of this file: the first draft of the
derivation counted `sessions in whole log` using the strict post-fix regex, so
it reported 7 where the log held 52. A tool whose job is publishing what it
excluded must not itself compute the exclusion over a filtered population.
"""
import importlib.util
import os
import sys

import pytest

import cosa.utils.util as cu

_SCRIPT = os.path.join( cu.get_project_root(), "src", "scripts", "derive_cc_memory_peak.py" )
_spec   = importlib.util.spec_from_file_location( "derive_cc_memory_peak", _SCRIPT )
dcm     = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( dcm )


def _line( ts=None, pid=1, rss=0.50, anon=None, session="aaaa1111" ):
    """Build one watcher report line; omit ts/anon to simulate a pre-fix line."""
    parts = []
    if ts is not None: parts.append( f"ts={ts}" )
    parts.append( f"pid={pid}" )
    parts.append( f"rss_gb= {rss:.2f}" )
    if anon is not None: parts.append( f"scope_anon_gb= {anon:.2f}" )
    parts.append( f"session={session}" )
    return "  " + " ".join( parts )


class TestDenominator:

    def test_sessions_all_counts_pre_fix_lines_the_strict_regex_cannot_match( self ):
        # THE REGRESSION THIS FILE EXISTS FOR: three sessions appear only on
        # pre-fix lines. A denominator computed over groupable lines reports 1.
        lines = [
            _line( ts="2026-08-25T19:00:00-0400", anon=1.0, session="post0001" ),
            _line( session="pre00001" ),
            _line( session="pre00002" ),
            _line( session="pre00003" ),
        ]
        r = dcm.derive( lines )
        assert r[ "sessions_all" ]    == 4
        assert r[ "sessions_window" ] == 1
        assert r[ "excluded_no_ts" ]  == 3

    def test_line_with_ts_but_no_scope_anon_is_excluded_separately( self ):
        # A watcher running post-ts= but pre-ab2a321c: groupable, wrong noun.
        lines = [ _line( ts="2026-08-25T19:00:00-0400", session="mid00001" ) ]
        r = dcm.derive( lines )
        assert r[ "excluded_no_scope" ] == 1
        assert r[ "excluded_no_ts" ]    == 0
        assert r[ "usable_lines" ]      == 0

    def test_non_rss_lines_are_not_counted_at_all( self ):
        r = dcm.derive( [ "ALERT: something else entirely", "" ] )
        assert r[ "total_lines" ] == 0


class TestPeaks:

    def test_concurrency_and_box_peak_are_taken_per_pass( self ):
        lines = [
            _line( ts="T1", pid=1, anon=1.0, session="s1" ),
            _line( ts="T1", pid=2, anon=2.0, session="s2" ),
            _line( ts="T2", pid=1, anon=9.0, session="s1" ),
        ]
        r = dcm.derive( lines )
        assert r[ "passes" ]           == 2
        assert r[ "concurrency_peak" ] == 2      # T1 has two seats
        assert r[ "box_anon_peak_gb" ] == 9.0    # T2 totals higher with one seat
        assert r[ "worst_scope_gb" ]   == 9.0

    def test_repeated_session_within_one_pass_does_not_double_count( self ):
        lines = [
            _line( ts="T1", pid=1, anon=1.0, session="s1" ),
            _line( ts="T1", pid=2, anon=1.0, session="s1" ),
        ]
        r = dcm.derive( lines )
        assert r[ "concurrency_peak" ] == 1
        assert r[ "box_anon_peak_gb" ] == 1.0

    def test_empty_input_returns_zeroed_peaks_rather_than_raising( self ):
        r = dcm.derive( [] )
        assert r[ "concurrency_peak" ] == 0
        assert r[ "usable_lines" ]     == 0


class TestRender:

    def test_render_names_exclusions_beside_every_peak( self ):
        lines = [
            _line( ts="T1", anon=1.0, session="post0001" ),
            _line( session="pre00001" ),
        ]
        out = dcm.render( dcm.derive( lines ), "/tmp/x.log" )
        assert "EXCLUDED no ts=" in out
        assert "1 of 2 sessions" in out
        assert "concurrency peak" in out

    def test_render_refuses_to_print_peaks_when_nothing_is_usable( self ):
        out = dcm.render( dcm.derive( [ _line( session="pre00001" ) ] ), "/tmp/x.log" )
        assert "NO USABLE LINES" in out
        assert "concurrency peak" not in out

    def test_render_handles_a_log_with_no_rss_lines( self ):
        out = dcm.render( dcm.derive( [ "noise" ] ), "/tmp/x.log" )
        assert "NO rss_gb LINES" in out


class TestMain:

    def test_main_reads_the_path_it_is_given( self, tmp_path, capsys, monkeypatch ):
        log = tmp_path / "samples.log"
        log.write_text( _line( ts="T1", anon=1.0, session="s1" ) + "\n" )
        monkeypatch.setattr( sys, "argv", [ "derive_cc_memory_peak.py", str( log ) ] )
        dcm.main()
        assert "concurrency peak" in capsys.readouterr().out

    def test_main_falls_back_to_the_default_log_path( self, tmp_path, capsys, monkeypatch ):
        log = tmp_path / "default.log"
        log.write_text( _line( ts="T1", anon=2.0, session="s1" ) + "\n" )
        monkeypatch.setattr( dcm, "DEFAULT_LOG", str( log ) )
        monkeypatch.setattr( sys, "argv", [ "derive_cc_memory_peak.py" ] )
        dcm.main()
        assert "concurrency peak" in capsys.readouterr().out
