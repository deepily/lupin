"""
Unit tests for cosa.utils.util — the shared utility grab-bag.

Covers the file I/O, date/time, CLI name=value parsing, banner/printing,
project-root resolution, API-key lookup, and small string/json helpers.
Filesystem-touching helpers use tempfiles; subprocess and ConfigurationManager
boundaries are mocked; the module-level `debug` flag is saved/restored so
debug-only branches can be exercised without leaking global state.

Assertions harvested and strengthened from the module's quick_smoke_test()
(now superseded) plus the many branches the smoke test never reached
(option flags, error paths, prose/timezone formatting, fallbacks).
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime as dt
from unittest.mock import patch, MagicMock

import cosa.utils.util as cu


def _capture( fn, *args, **kwargs ):
    """Run fn and return everything it printed to stdout."""
    buf = io.StringIO()
    with redirect_stdout( buf ):
        fn( *args, **kwargs )
    return buf.getvalue()


class _TmpFileMixin:
    """Helper to materialize a tempfile and auto-clean it."""

    def _write_tmp( self, content, suffix="" ):
        tmp = tempfile.NamedTemporaryFile( mode="w", suffix=suffix, delete=False, encoding="utf-8" )
        tmp.write( content )
        tmp.close()
        self.addCleanup( lambda: os.path.exists( tmp.name ) and os.unlink( tmp.name ) )
        return tmp.name


class TestDebugFlagAndPath( unittest.TestCase ):
    """init() + add_to_path() — global debug flag and sys.path management."""

    def setUp( self ):
        self._orig_debug = cu.debug
        self._orig_path  = list( sys.path )

    def tearDown( self ):
        cu.debug = self._orig_debug
        sys.path[ : ] = self._orig_path

    def test_init_sets_debug_flag( self ):
        cu.init( True )
        self.assertTrue( cu.debug )
        cu.init( False )
        self.assertFalse( cu.debug )

    def test_add_to_path_appends_when_absent( self ):
        marker = "/tmp/__sam_path_marker_append__"
        self.assertNotIn( marker, sys.path )
        cu.add_to_path( marker )
        self.assertIn( marker, sys.path )

    def test_add_to_path_inserts_at_index( self ):
        marker = "/tmp/__sam_path_marker_insert__"
        cu.add_to_path( marker, idx=0 )
        self.assertEqual( sys.path[ 0 ], marker )

    def test_add_to_path_noop_when_present( self ):
        marker = "/tmp/__sam_path_marker_present__"
        sys.path.append( marker )
        before = len( sys.path )
        cu.add_to_path( marker )           # already present -> no append
        self.assertEqual( len( sys.path ), before )


class TestDateTimeHelpers( unittest.TestCase ):
    """Timezone-aware date/time formatting helpers."""

    def test_datetime_raw_is_tz_aware( self ):
        d = cu.get_current_datetime_raw( days_offset=0 )
        self.assertIsInstance( d, dt )
        self.assertIsNotNone( d.tzinfo )

    def test_datetime_raw_offset_changes_day( self ):
        today    = cu.get_current_datetime_raw( days_offset=0 )
        tomorrow = cu.get_current_datetime_raw( days_offset=1 )
        self.assertGreater( tomorrow, today )

    def test_get_current_datetime_formats( self ):
        s = cu.get_current_datetime()
        self.assertIn( "@", s )

    def test_get_current_datetime_iso_has_offset( self ):
        s = cu.get_current_datetime_iso()
        self.assertIn( "T", s )

    def test_get_current_date_prose_and_iso( self ):
        prose = cu.get_current_date( return_prose=True )
        iso   = cu.get_current_date( return_prose=False )
        self.assertIn( ",", prose )                       # "Monday, January 01, 2021"
        self.assertEqual( len( iso.split( "-" ) ), 3 )    # YYYY-MM-DD

    def test_get_current_time_with_and_without_tz( self ):
        with_tz    = cu.get_current_time( include_timezone=True, format="%H:%M" )
        without_tz = cu.get_current_time( include_timezone=False, format="%H:%M" )
        self.assertGreater( len( with_tz ), len( without_tz ) )

    def test_get_timestamp_ms_truncates_micros( self ):
        ts = cu.get_timestamp_ms()
        self.assertEqual( ts.microsecond % 1000, 0 )


class TestNameValuePairs( unittest.TestCase ):
    """get_name_value_pairs() + v2 CLI arg parsing."""

    def test_empty_arglist_returns_empty( self ):
        self.assertEqual( cu.get_name_value_pairs( [ "script" ] ), {} )

    def test_parses_pairs_and_skips_non_pairs( self ):
        out = cu.get_name_value_pairs( [ "script", "a=1", "noeq", "b=2" ], debug=True, verbose=True )
        self.assertEqual( out, { "a": "1", "b": "2" } )

    def test_no_pairs_uses_default_width( self ):
        # all args lack '=' -> name_value_pairs stays empty (the max_len else branch)
        out = cu.get_name_value_pairs( [ "script", "noeq", "alsonoeq" ], debug=True )
        self.assertEqual( out, {} )

    def test_v2_empty_returns_empty( self ):
        self.assertEqual( cu.get_name_value_pairs_v2( [ "script" ] ), {} )

    def test_v2_decodes_spaces( self ):
        out = cu.get_name_value_pairs_v2( [ "script", "msg=hello+world", "noeq" ] )
        self.assertEqual( out[ "msg" ], "hello world" )

    def test_v2_without_space_decoding( self ):
        out = cu.get_name_value_pairs_v2( [ "script", "msg=a+b" ], decode_spaces=False )
        self.assertEqual( out[ "msg" ], "a+b" )

    def test_v2_all_non_pairs_yields_empty_dict( self ):
        # >1 arg but none contain '=' -> name_value_pairs stays empty (1033 False branch).
        out = cu.get_name_value_pairs_v2( [ "script", "noeq", "alsonoeq" ] )
        self.assertEqual( out, {} )


class TestFileReaders( _TmpFileMixin, unittest.TestCase ):
    """File-loading helpers: list/string/json/dictionary/line-numbering."""

    def test_get_file_as_list_options( self ):
        path = self._write_tmp( "# comment\nHELLO\n\n  spaced  \n" )
        lines = cu.get_file_as_list(
            path, lower_case=True, clean=True, strip_newlines=True,
            skip_empty=True, skip_comments=True
        )
        self.assertNotIn( "# comment", lines )
        self.assertIn( "hello", lines )
        self.assertNotIn( "", lines )

    def test_get_file_as_list_randomize_deterministic( self ):
        path = self._write_tmp( "\n".join( str( i ) for i in range( 20 ) ) )
        a = cu.get_file_as_list( path, randomize=True, seed=42 )
        b = cu.get_file_as_list( path, randomize=True, seed=42 )
        self.assertEqual( a, b )

    def test_get_file_as_string( self ):
        path = self._write_tmp( "raw content" )
        self.assertEqual( cu.get_file_as_string( path ), "raw content" )

    def test_get_file_as_json( self ):
        path = self._write_tmp( json.dumps( { "k": "v" } ), suffix=".json" )
        self.assertEqual( cu.get_file_as_json( path ), { "k": "v" } )

    def test_get_file_as_dictionary_parses_and_skips_comments( self ):
        # 'loneword' has no ' = ' separator -> len(pair) <= 1 -> skipped (no dict entry).
        path = self._write_tmp(
            "# a comment\n// another\nkey = value\n|piped| = |val|\nloneword\n"
        )
        d = cu.get_file_as_dictionary( path, debug=True, verbose=True )
        self.assertEqual( d[ "key" ], "value" )
        self.assertEqual( d[ "piped" ], "val" )       # pipes stripped
        self.assertNotIn( "loneword", d )

    def test_line_numbering_helpers( self ):
        path = self._write_tmp( "alpha\nbeta\n" )
        numbered = cu.get_file_as_source_code_with_line_numbers( path )
        self.assertIn( "001 ", numbered )
        self.assertIn( "002 ", numbered )

    def test_get_source_code_with_line_numbers_join( self ):
        out = cu.get_source_code_with_line_numbers( [ "x", "y" ], join_str="\n" )
        self.assertEqual( out, "001 x\n002 y" )

    def test_get_files_as_strings( self ):
        p1 = self._write_tmp( "one" )
        p2 = self._write_tmp( "two" )
        self.assertEqual( cu.get_files_as_strings( [ p1, p2 ] ), [ "one", "two" ] )


class TestFileWriters( _TmpFileMixin, unittest.TestCase ):
    """File-writing helpers."""

    def test_write_lines_strips_blanks_and_chmods( self ):
        path = self._write_tmp( "" )
        cu.write_lines_to_file(
            path, [ "a", "", "b" ], strip_blank_lines=True, world_read_write=True
        )
        self.assertEqual( cu.get_file_as_string( path ), "a\nb" )
        self.assertEqual( os.stat( path ).st_mode & 0o666, 0o666 )

    def test_write_lines_keeps_blanks_by_default( self ):
        # strip_blank_lines defaults False -> blank line is preserved (False branch).
        path = self._write_tmp( "" )
        cu.write_lines_to_file( path, [ "a", "", "b" ] )
        self.assertEqual( cu.get_file_as_string( path ), "a\n\nb" )

    def test_write_string_to_file( self ):
        path = self._write_tmp( "" )
        cu.write_string_to_file( path, "payload" )
        self.assertEqual( cu.get_file_as_string( path ), "payload" )


class TestPrintSimpleFileList( unittest.TestCase ):
    """print_simple_file_list() — existence guard + subprocess wrapping."""

    def test_missing_path_raises_file_not_found( self ):
        with self.assertRaises( FileNotFoundError ):
            cu.print_simple_file_list( "/tmp/__definitely_absent_dir_5521__" )

    def test_lists_existing_directory( self ):
        with tempfile.TemporaryDirectory() as d:
            open( os.path.join( d, "marker.txt" ), "w" ).close()
            out = _capture( cu.print_simple_file_list, d )
            # `ls -alh` output includes the total line and the file we created.
            self.assertIn( "total", out )
            self.assertIn( "marker.txt", out )

    def test_called_process_error_is_reraised( self ):
        err = subprocess.CalledProcessError( 2, [ "ls" ], output="o", stderr="e" )
        with patch( "cosa.utils.util.os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.subprocess.run", side_effect=err ):
            with self.assertRaises( subprocess.CalledProcessError ):
                cu.print_simple_file_list( "/whatever" )


class TestBanner( unittest.TestCase ):
    """print_banner() — default / expletive / flex decoration modes."""

    def test_default_mode( self ):
        out = _capture( cu.print_banner, "hello", prepend_nl=True )
        self.assertIn( "- hello", out )       # default decoration prefixes msg with "- "
        self.assertIn( "-" * 50, out )        # dashed bar rule

    def test_expletive_mode( self ):
        out = _capture( cu.print_banner, "boom", expletive=True, chunk="XO" )
        self.assertIn( "boom", out )
        self.assertIn( "XO", out )            # expletive uses the chunk for decoration

    def test_flex_mode( self ):
        out = _capture( cu.print_banner, "a\nbb\nccc", flex=True )
        self.assertIn( "ccc", out )
        self.assertIn( "-", out )


class TestProjectRoot( unittest.TestCase ):
    """get_project_root() — env var vs. fallback, with debug branch."""

    def setUp( self ):
        self._orig_debug = cu.debug

    def tearDown( self ):
        cu.debug = self._orig_debug

    def test_returns_env_var_when_present( self ):
        with patch.dict( os.environ, { "LUPIN_ROOT": "/custom/root" } ):
            self.assertEqual( cu.get_project_root(), "/custom/root" )

    def test_debug_branch_runs( self ):
        cu.debug = True
        with patch.dict( os.environ, { "LUPIN_ROOT": "/dbg/root" } ):
            self.assertEqual( cu.get_project_root(), "/dbg/root" )

    def test_fallback_when_env_absent( self ):
        with patch.dict( os.environ, {}, clear=False ):
            os.environ.pop( "LUPIN_ROOT", None )
            self.assertEqual( cu.get_project_root(), "/var/lupin" )


class TestTtsInteractionMode( unittest.TestCase ):
    """get_tts_interaction_mode() — valid / invalid / error -> chorus default."""

    def _patch_cfg( self, get_return=None, raises=False ):
        if raises:
            return patch(
                "cosa.config.configuration_manager.ConfigurationManager",
                side_effect=RuntimeError( "boom" ),
            )
        instance = MagicMock()
        instance.get.return_value = get_return
        return patch(
            "cosa.config.configuration_manager.ConfigurationManager",
            return_value=instance,
        )

    def test_valid_solo( self ):
        with self._patch_cfg( get_return="solo" ):
            self.assertEqual( cu.get_tts_interaction_mode(), "solo" )

    def test_invalid_value_defaults_chorus( self ):
        with self._patch_cfg( get_return="bogus" ):
            self.assertEqual( cu.get_tts_interaction_mode(), "chorus" )

    def test_config_error_defaults_chorus( self ):
        with self._patch_cfg( raises=True ):
            self.assertEqual( cu.get_tts_interaction_mode(), "chorus" )


class TestGetApiKey( _TmpFileMixin, unittest.TestCase ):
    """get_api_key() — present / missing / default-root resolution."""

    def _make_key_root( self, key_name, content ):
        root = tempfile.mkdtemp()
        self.addCleanup( lambda: __import__( "shutil" ).rmtree( root, ignore_errors=True ) )
        keys_dir = os.path.join( root, "src", "conf", "keys" )
        os.makedirs( keys_dir )
        with open( os.path.join( keys_dir, key_name ), "w" ) as f:
            f.write( content )
        return root

    def test_returns_key_when_present( self ):
        root = self._make_key_root( "openai", "  sk-abc123  \n" )
        self.assertEqual( cu.get_api_key( "openai", project_root=root ), "sk-abc123" )

    def test_returns_none_when_missing( self ):
        root = tempfile.mkdtemp()
        self.addCleanup( lambda: __import__( "shutil" ).rmtree( root, ignore_errors=True ) )
        self.assertIsNone( cu.get_api_key( "nope", project_root=root ) )

    def test_default_project_root_used_when_none( self ):
        root = self._make_key_root( "groq", "key-xyz" )
        with patch( "cosa.utils.util.get_project_root", return_value=root ):
            self.assertEqual( cu.get_api_key( "groq" ), "key-xyz" )


class TestSmallHelpers( unittest.TestCase ):
    """is_jsonl, truncate_string, generate_domain_names, find_files, print_stack_trace, sanity_check."""

    def test_is_jsonl_true( self ):
        self.assertTrue( cu.is_jsonl( '{"a": 1}\n{"b": 2}' ) )

    def test_is_jsonl_false( self ):
        self.assertFalse( cu.is_jsonl( "{not json}" ) )

    def test_truncate_string_long_and_short( self ):
        self.assertEqual( cu.truncate_string( "abc", max_len=10 ), "abc" )
        truncated = cu.truncate_string( "x" * 100, max_len=10 )
        self.assertTrue( truncated.endswith( "..." ) )
        self.assertEqual( len( truncated ), 13 )

    def test_generate_domain_names_count_and_dots( self ):
        with_dots = cu.generate_domain_names( count=5, remove_dots=False )
        self.assertEqual( len( with_dots ), 5 )
        no_dots = cu.generate_domain_names( count=3, remove_dots=True, debug=True )
        self.assertEqual( len( no_dots ), 3 )
        self.assertTrue( all( "." not in d for d in no_dots ) )

    def test_find_files_with_prefix_and_suffix( self ):
        with tempfile.TemporaryDirectory() as d:
            for name in ( "rep_a.md", "rep_b.md", "other.txt" ):
                open( os.path.join( d, name ), "w" ).close()
            matches = cu.find_files_with_prefix_and_suffix( d, "rep_", ".md" )
            self.assertEqual( len( matches ), 2 )

    def test_print_list_runs( self ):
        out = _capture( cu.print_list, [ 1, 2, 3 ] )
        self.assertEqual( out, "1\n2\n3\n" )

    def test_print_stack_trace_with_debug( self ):
        try:
            raise ValueError( "kaboom" )
        except ValueError as e:
            out = _capture(
                cu.print_stack_trace, e, explanation="bad thing", caller="my_caller", debug=True
            )
        self.assertIn( "bad thing", out )            # explanation surfaced
        self.assertIn( "my_caller", out )            # caller surfaced
        self.assertIn( "kaboom", out )               # exception message surfaced
        self.assertIn( "Full stack trace", out )     # debug=True prints the trace

    def test_print_stack_trace_without_debug( self ):
        try:
            raise KeyError( "missing" )
        except KeyError as e:
            out = _capture( cu.print_stack_trace, e, debug=False )
        self.assertIn( "KeyError", out )             # type always printed
        self.assertNotIn( "Full stack trace", out )  # debug=False suppresses the trace

    def test_sanity_check_existing_file( self ):
        tmp = tempfile.NamedTemporaryFile( delete=False )
        tmp.close()
        self.addCleanup( lambda: os.path.exists( tmp.name ) and os.unlink( tmp.name ) )
        cu.sanity_check_file_path( tmp.name )                    # silent=False prints
        cu.sanity_check_file_path( tmp.name, silent=True )

    def test_sanity_check_missing_file_raises( self ):
        with self.assertRaises( AssertionError ):
            cu.sanity_check_file_path( "/tmp/__absent_8842__.txt" )


if __name__ == "__main__":
    unittest.main()


# ── The wrong-tree detector (row ef22c328) ───────────────────────────────────
# A standalone script run by hand from a WORKTREE, using the documented bootstrap
# that joins $LUPIN_ROOT/src onto sys.path, imports its code from the MAIN checkout.
# Rio's worktree_tree_guard covers pytest; it arms on TEST COLLECTION, so a plain
# `python3 script.py` never trips it.

def _clear_warn_cache():
    cu._wrong_tree_warned.clear()


def test_a_caller_inside_the_root_is_silent( tmp_path, monkeypatch, capsys ):
    """The ordinary case — every normal run, the container included."""
    _clear_warn_cache()
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    cu.get_project_root()

    assert capsys.readouterr().err == ""


def test_a_sibling_tree_whose_NAME_starts_with_the_root_is_NOT_inside_it( tmp_path, monkeypatch, capsys ):
    """
    🔴 The bug this test exists for, measured while building the detector. Root is
    `…/lupin`; the worktrees on this box are `…/lupin-wt-clayton-unit`. A bare
    `caller.startswith( root )` is TRUE for those, so the fast path swallowed exactly
    the population the detector was built to catch — and it failed silently, which is
    the one failure mode a detector must not have.
    """
    _clear_warn_cache()
    root    = tmp_path / "lupin"
    sibling = tmp_path / "lupin-wt-someseat"
    for d in ( root, sibling ):
        ( d / ".git" ).mkdir( parents=True )

    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    monkeypatch.setattr(
        cu.sys, "_getframe",
        lambda depth: _FakeFrame( str( sibling / "script.py" ) ) if depth == 1 else _FakeFrame( cu.__file__ ),
    )
    cu.get_project_root()

    err = capsys.readouterr().err
    assert "WRONG-TREE WARNING" in err
    assert str( sibling ) in err


def test_it_warns_once_per_file_not_once_per_call( tmp_path, monkeypatch, capsys ):
    """get_project_root() is on the hot path; a per-call warning would be noise."""
    _clear_warn_cache()
    root    = tmp_path / "lupin"
    sibling = tmp_path / "lupin-wt-someseat"
    for d in ( root, sibling ):
        ( d / ".git" ).mkdir( parents=True )

    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    monkeypatch.setattr(
        cu.sys, "_getframe",
        lambda depth: _FakeFrame( str( sibling / "script.py" ) ) if depth == 1 else _FakeFrame( cu.__file__ ),
    )
    cu.get_project_root()
    capsys.readouterr()                      # drain the first, legitimate warning
    cu.get_project_root()

    assert capsys.readouterr().err == ""


def test_a_non_git_layout_says_nothing( tmp_path, monkeypatch, capsys ):
    """Nothing to compare — decide nothing rather than guess."""
    _clear_warn_cache()
    root    = tmp_path / "lupin"             # deliberately NO .git anywhere
    sibling = tmp_path / "lupin-wt-someseat"
    for d in ( root, sibling ): d.mkdir( parents=True )

    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    monkeypatch.setattr(
        cu.sys, "_getframe",
        lambda depth: _FakeFrame( str( sibling / "script.py" ) ) if depth == 1 else _FakeFrame( cu.__file__ ),
    )
    cu.get_project_root()

    assert capsys.readouterr().err == ""


def test_the_detector_never_raises( tmp_path, monkeypatch ):
    """A detector that breaks the thing it watches is worse than no detector."""
    _clear_warn_cache()
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( cu.sys, "_getframe", lambda depth: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )

    assert cu.get_project_root() == str( tmp_path )      # returns normally despite the blow-up


def test_git_tree_of_finds_a_worktree_dot_git_FILE( tmp_path ):
    """A linked worktree's `.git` is a FILE, not a directory — both must count."""
    tree = tmp_path / "wt"
    tree.mkdir()
    ( tree / ".git" ).write_text( "gitdir: /elsewhere/.git/worktrees/wt\n" )
    nested = tree / "a" / "b"
    nested.mkdir( parents=True )

    assert cu._git_tree_of( str( nested ) ) == str( tree )


def test_git_tree_of_returns_none_above_every_repo( tmp_path ):
    assert cu._git_tree_of( str( tmp_path ) ) is None


class _FakeFrame:
    def __init__( self, filename ):
        self.f_code = type( "C", (), { "co_filename": filename } )()


def test_git_tree_of_swallows_an_unreadable_path( monkeypatch ):
    """The walk must never raise into a caller that only asked for the project root."""
    monkeypatch.setattr( cu.os.path, "abspath", lambda p: ( _ for _ in () ).throw( OSError( "nope" ) ) )

    assert cu._git_tree_of( "/anything" ) is None


def test_the_frame_walk_gives_up_when_it_runs_out_of_frames( tmp_path, monkeypatch, capsys ):
    """
    A direct caller at module level has no deeper frame. `sys._getframe` raises
    ValueError there, and the walk must stop rather than let the outer except
    swallow it — which is how the first version failed silently.
    """
    _clear_warn_cache()
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )

    def _only_this_module( depth ):
        if depth < 3: return _FakeFrame( cu.__file__ )      # every frame is util.py …
        raise ValueError( "call stack is not deep enough" ) # … then the stack ends
    monkeypatch.setattr( cu.sys, "_getframe", _only_this_module )

    cu.get_project_root()

    assert capsys.readouterr().err == ""                    # no caller found → say nothing


def test_a_caller_equal_to_the_root_itself_is_inside_it( tmp_path, monkeypatch, capsys ):
    """The `caller == root_abs` arm — an exact match is not 'outside'."""
    _clear_warn_cache()
    root = tmp_path / "lupin"
    ( root / ".git" ).mkdir( parents=True )
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    monkeypatch.setattr(
        cu.sys, "_getframe",
        lambda depth: _FakeFrame( str( root ) ) if depth == 1 else _FakeFrame( cu.__file__ ),
    )
    cu.get_project_root()

    assert capsys.readouterr().err == ""


def test_two_paths_to_the_SAME_tree_do_not_warn( tmp_path, monkeypatch, capsys ):
    """
    A symlinked or otherwise aliased path into the same tree is not a wrong tree.
    The comparison is on realpath for exactly this reason.
    """
    _clear_warn_cache()
    root = tmp_path / "lupin"
    ( root / ".git" ).mkdir( parents=True )
    alias = tmp_path / "alias"
    alias.symlink_to( root )

    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    monkeypatch.setattr(
        cu.sys, "_getframe",
        lambda depth: _FakeFrame( str( alias / "script.py" ) ) if depth == 1 else _FakeFrame( cu.__file__ ),
    )
    cu.get_project_root()

    assert capsys.readouterr().err == ""


def test_the_frame_walk_is_bounded( tmp_path, monkeypatch, capsys ):
    """
    Deep recursion inside this module must not turn the walk into an unbounded
    climb on a hot-path function. It stops at 12 and says nothing.
    """
    _clear_warn_cache()
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( cu.sys, "_getframe", lambda depth: _FakeFrame( cu.__file__ ) )   # always this module

    cu.get_project_root()

    assert capsys.readouterr().err == ""


# ── get_spoken_char_cap — the six statements the file was short of 100% ──────
# Pre-existing and unrelated to the wrong-tree detector, but the gate is the FILE,
# not the diff, so they are covered here rather than rounded up to "99%".

def test_spoken_char_cap_reads_the_configured_value( monkeypatch ):
    """The runtime-tunable path: whatever the ini says, at call time."""
    import cosa.config.configuration_manager as cm

    class _Mgr:
        def __init__( self, **kwargs ): pass
        def get( self, key, default=None, return_type=None ):
            assert key == cu.SPOKEN_CHAR_CAP_INI_KEY
            assert return_type == "int"
            return 640
    monkeypatch.setattr( cm, "ConfigurationManager", _Mgr )

    assert cu.get_spoken_char_cap() == 640


def test_spoken_char_cap_falls_back_when_the_key_is_absent( monkeypatch ):
    """An absent key yields the default the caller passed in, not None."""
    import cosa.config.configuration_manager as cm

    class _Mgr:
        def __init__( self, **kwargs ): pass
        def get( self, key, default=None, return_type=None ): return default
    monkeypatch.setattr( cm, "ConfigurationManager", _Mgr )

    assert cu.get_spoken_char_cap() == cu.SPOKEN_CHAR_CAP_DEFAULT


def test_spoken_char_cap_never_raises_out_of_a_config_failure( monkeypatch ):
    """
    This cap is read on the TTS path. A config blow-up must degrade to the default
    rather than take the spoken channel down — the docstring promises 'never raises'
    and nothing was holding it to that.
    """
    import cosa.config.configuration_manager as cm

    class _Boom:
        def __init__( self, **kwargs ): raise RuntimeError( "ini unreadable" )
    monkeypatch.setattr( cm, "ConfigurationManager", _Boom )

    assert cu.get_spoken_char_cap() == cu.SPOKEN_CHAR_CAP_DEFAULT
