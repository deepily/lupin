"""
Tests for `src/scripts/find_interchangeable_assertions.py`.

LOAD MECHANISM: `importlib.import_module` with `src/scripts` on the path — the module
has an underscored name, so the by-path dance the dashed scripts need is unnecessary.

WHAT THESE PIN, and the ordering is deliberate. The probe's whole value is a BOUNDARY:
it finds blind assertions and NOT undefended behaviour. So the caveat is tested as
load-bearing output, not as decoration — a triage aid that stops printing its own limits
becomes a defect list in the next reader's hands.

⚠️ FIXTURES ARE CHOSEN SO THE LOOSE AND STRICT ANSWERS DIFFER. This file is about
fixture blindness, so its own fixtures must not be blind: every count case uses values
that are NOT interchangeable (2 of 3, never 1 of 2 where the two are the same thing),
and the negative controls are containers that are ALMOST hits — right shape, distinct
values — rather than unrelated code that would pass under any implementation.
"""

import importlib
import json
import os
import sys

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
if os.path.join( _ROOT, "src", "scripts" ) not in sys.path:
    sys.path.insert( 0, os.path.join( _ROOT, "src", "scripts" ) )

mod = importlib.import_module( "find_interchangeable_assertions" )


import ast


def _first_container( source ):
    """The first Dict/Tuple/List node in a snippet — the probe's unit of work."""
    for node in ast.walk( ast.parse( source ) ):
        if isinstance( node, ( ast.Dict, ast.Tuple, ast.List ) ): return node
    raise AssertionError( "snippet contains no container" )


class TestLiteralOf:

    @pytest.mark.parametrize( "snippet,expected", [
        ( "1",       "1" ),
        ( "'a'",     "'a'" ),
        ( "1.5",     "1.5" ),
        ( "True",    "True" ),
    ] )
    def test_plain_literals_are_comparable( self, snippet, expected ):
        node = ast.parse( snippet, mode="eval" ).body
        assert mod.literal_of( node ) == expected

    @pytest.mark.parametrize( "snippet", [ "None", "x", "f( 1 )", "[ 1 ]", "1 + 1" ] )
    def test_anything_it_cannot_compare_is_None_rather_than_a_guess( self, snippet ):
        node = ast.parse( snippet, mode="eval" ).body
        assert mod.literal_of( node ) is None

    def test_None_is_excluded_deliberately( self ):
        """
        🔴 `None` is a Constant but NOT comparable here. Two None values are equal, so
        including them would flag `{ "a": None, "b": None }` — a shape that is almost
        always a deliberate 'neither is set' assertion rather than a blind one.
        """
        assert mod.literal_of( ast.parse( "None", mode="eval" ).body ) is None


class TestRepeatedIn:

    def test_a_dict_with_two_equal_values_is_a_hit( self ):
        assert mod.repeated_in( _first_container( '{ "migrated": 1, "skipped": 1 }' ) ) == ( "1", 2, 2 )

    def test_a_tuple_with_equal_elements_is_a_hit( self ):
        assert mod.repeated_in( _first_container( "( 1, 1 )" ) ) == ( "1", 2, 2 )

    def test_a_list_with_equal_elements_is_a_hit( self ):
        assert mod.repeated_in( _first_container( "[ 'x', 'y', 'x' ]" ) ) == ( "'x'", 2, 3 )

    def test_the_report_names_how_many_of_how_many( self ):
        """
        2 of 3 rather than 2 of 2 — a partial repeat is still blind BETWEEN the two that
        repeat, and the total is what tells a reader how much of the container is safe.
        """
        assert mod.repeated_in( _first_container( "( 5, 5, 9 )" ) ) == ( "5", 2, 3 )

    def test_all_distinct_values_are_NOT_a_hit( self ):
        assert mod.repeated_in( _first_container( '{ "migrated": 2, "skipped": 1 }' ) ) is None

    def test_a_single_element_container_is_not_a_hit( self ):
        assert mod.repeated_in( _first_container( "( 1, )" ) ) is None

    def test_an_empty_container_is_not_a_hit( self ):
        assert mod.repeated_in( _first_container( "{ }" ) ) is None

    def test_a_container_holding_a_non_literal_is_skipped_rather_than_guessed( self ):
        """A value it cannot compare makes the whole container unjudgeable, not a hit."""
        assert mod.repeated_in( _first_container( '{ "a": 1, "b": x }' ) ) is None

    def test_a_node_that_is_not_a_container_is_not_a_hit( self ):
        assert mod.repeated_in( ast.parse( "1", mode="eval" ).body ) is None

    def test_dict_unpacking_makes_the_container_unjudgeable( self ):
        """`{ **other, "a": 1 }` has a None key and a value this probe cannot see past."""
        assert mod.repeated_in( _first_container( '{ **other, "a": 1 }' ) ) is None


class TestFindingsInSource:

    def test_it_reports_the_line_of_the_ASSERT_not_of_the_container( self ):
        source = "x = 1\n\nassert (\n    x == ( 7, 7 )\n)\n"
        found  = mod.findings_in_source( source, "f.py" )
        assert [ ( f[ "line" ], f[ "value" ], f[ "times" ], f[ "total" ] ) for f in found ] == [ ( 3, "7", 2, 2 ) ]

    def test_one_finding_per_assert_even_when_two_containers_repeat( self ):
        """
        An assert is the unit a reader adjudicates. Reporting it twice would inflate the
        queue without adding a site to look at.
        """
        found = mod.findings_in_source( "assert ( 1, 1 ) == ( 2, 2 )\n", "f.py" )
        assert len( found ) == 1

    def test_findings_come_back_in_source_order( self ):
        source = "assert a == ( 9, 9 )\nassert b == ( 4, 4 )\nassert c == ( 6, 6 )\n"
        found  = mod.findings_in_source( source, "f.py" )
        assert [ f[ "line" ] for f in found ] == [ 1, 2, 3 ]
        assert [ f[ "value" ] for f in found ] == [ "9", "4", "6" ]

    def test_a_file_with_no_asserts_yields_nothing( self ):
        assert mod.findings_in_source( "x = ( 1, 1 )\n", "f.py" ) == [ ]

    def test_a_non_assert_container_is_not_reported( self ):
        """The shape only matters inside an assertion; a fixture literal is not a claim."""
        assert mod.findings_in_source( "fixture = { 'a': 1, 'b': 1 }\n", "f.py" ) == [ ]

    def test_an_unparseable_file_is_NOT_a_finding( self ):
        assert mod.findings_in_source( "def broken( :\n", "f.py" ) == [ ]

    def test_the_path_travels_with_the_finding( self ):
        found = mod.findings_in_source( "assert a == ( 3, 3 )\n", "some/where.py" )
        assert found[ 0 ][ "path" ] == "some/where.py"


class TestScan:

    def test_it_reads_every_path_and_counts_them( self ):
        files = { "a.py": "assert x == ( 1, 1 )\n", "b.py": "assert y == ( 2, 3 )\n" }
        findings, files_read = mod.scan( sorted( files ), lambda p: files[ p ] )
        assert files_read == 2
        assert [ f[ "path" ] for f in findings ] == [ "a.py" ]

    def test_an_unreadable_file_is_skipped_and_NOT_counted_as_read( self ):
        """
        🔴 The load-bearing one. If an unreadable file counted as read, a run that could
        open nothing would report files_read > 0 and exit 0 — a clean bill for a scan
        that never happened.
        """
        def read( path ):
            if path == "bad.py": raise OSError( "nope" )
            return "assert x == ( 1, 1 )\n"
        findings, files_read = mod.scan( [ "bad.py", "good.py" ], read )
        assert files_read == 1
        assert [ f[ "path" ] for f in findings ] == [ "good.py" ]

    def test_findings_are_ordered_by_path_then_line( self ):
        files = {
            "z.py": "assert a == ( 1, 1 )\n",
            "a.py": "assert b == ( 2, 2 )\nassert c == ( 3, 3 )\n",
        }
        findings, _ = mod.scan( [ "z.py", "a.py" ], lambda p: files[ p ] )
        assert [ ( f[ "path" ], f[ "line" ] ) for f in findings ] == [ ( "a.py", 1 ), ( "a.py", 2 ), ( "z.py", 1 ) ]

    def test_no_paths_reads_nothing( self ):
        assert mod.scan( [ ], lambda p: "" ) == ( [ ], 0 )


class TestRender:

    def _findings( self, n ):
        return [ { "path": f"f{i}.py", "line": i, "value": "1", "times": 2, "total": 2 }
                 for i in range( n ) ]

    def test_the_caveat_prints_when_there_ARE_findings( self, capsys ):
        mod.render( self._findings( 1 ), 1, 40 )
        out = capsys.readouterr().out
        assert "DOES NOT   : find undefended behaviour" in out
        assert "never a mutation" not in out

    def test_the_caveat_prints_when_there_are_NONE( self, capsys ):
        """
        🔴 A triage aid that only states its limits when it has something to say has the
        boundary backwards: a clean run is exactly when a reader concludes 'nothing here'.
        """
        mod.render( [ ], 5, 40 )
        out = capsys.readouterr().out
        assert "DOES NOT   : find undefended behaviour" in out
        # 🔴 A ZERO RUN MUST SAY IT IS NOT AN ALL-CLEAR, in the OUTPUT (Chloé, 2026-08-30).
        # The docstring caveat only reaches someone who opens the source; a consumer reads
        # stdout, and "no findings" from a triage aid reads as a clean bill of health.
        assert "NOT FOUND — and NOT the same as none present." in out
        assert "has not been cleared" in out
        assert "Only a mutation clears it." in out

    def test_it_truncates_and_says_how_many_it_withheld( self, capsys ):
        mod.render( self._findings( 10 ), 3, 4 )
        out = capsys.readouterr().out
        assert "… and 6 more" in out
        assert "f4.py" not in out

    def test_it_does_not_claim_a_remainder_when_everything_fitted( self, capsys ):
        mod.render( self._findings( 2 ), 2, 40 )
        assert "more (raise --limit" not in capsys.readouterr().out

    def test_the_files_scanned_count_is_stated( self, capsys ):
        mod.render( [ ], 137, 40 )
        assert "137 test files scanned" in capsys.readouterr().out


class TestMain:

    @pytest.fixture
    def wired( self, monkeypatch ):
        """Replace both filesystem seams; the tests decide what the tree contains."""
        def install( files ):
            monkeypatch.setattr( mod, "_default_paths", lambda root: sorted( files ) )
            monkeypatch.setattr( mod, "_default_read",  lambda path: files[ path ] )
        return install

    def test_findings_exit_1( self, wired, capsys ):
        wired( { "a.py": "assert x == ( 1, 1 )\n" } )
        assert mod.main( [ ] ) == 1
        assert "a.py:1" in capsys.readouterr().out

    def test_a_clean_scan_exits_0( self, wired, capsys ):
        wired( { "a.py": "assert x == ( 1, 2 )\n" } )
        assert mod.main( [ ] ) == 0
        out = capsys.readouterr().out
        # 0 means nothing MATCHED, never that no fixture is blind — and the run has to say so.
        assert "NOT FOUND — and NOT the same as none present." in out

    def test_nothing_readable_exits_2_and_says_it_is_not_clean( self, wired, capsys ):
        """
        🔴 2, never 0. An empty scan and a clean scan print almost the same thing, and
        only the exit code separates 'nothing is wrong' from 'nothing was looked at'.
        """
        wired( { } )
        assert mod.main( [ "some/root" ] ) == 2
        assert "NOT a clean result" in capsys.readouterr().err

    def test_json_mode_carries_the_caveat_as_a_field( self, wired, capsys ):
        """The caveat must survive machine consumption, or it is lost exactly where it matters."""
        wired( { "a.py": "assert x == ( 1, 1 )\n" } )
        assert mod.main( [ "--json" ] ) == 1
        payload = json.loads( capsys.readouterr().out )
        assert payload[ "files_read" ] == 1
        assert len( payload[ "findings" ] ) == 1
        assert "sibling assertion" in payload[ "caveat" ]

    def test_json_mode_still_exits_0_on_a_clean_tree( self, wired, capsys ):
        wired( { "a.py": "assert x == ( 1, 2 )\n" } )
        assert mod.main( [ "--json" ] ) == 0
        assert json.loads( capsys.readouterr().out )[ "findings" ] == [ ]

    def test_limit_is_honoured( self, wired, capsys ):
        wired( { "a.py": "assert x == ( 1, 1 )\nassert y == ( 2, 2 )\n" } )
        assert mod.main( [ "--limit", "1" ] ) == 1
        assert "… and 1 more" in capsys.readouterr().out

    def test_the_root_argument_reaches_the_path_seam( self, monkeypatch, capsys ):
        """Asserting only the default would pass if the argument were ignored entirely."""
        seen = [ ]
        monkeypatch.setattr( mod, "_default_paths", lambda root: seen.append( root ) or [ ] )
        monkeypatch.setattr( mod, "_default_read",  lambda path: "" )
        mod.main( [ "src/tests/unit" ] )
        assert seen == [ "src/tests/unit" ]

    def test_the_default_root_is_the_test_tree( self, monkeypatch ):
        seen = [ ]
        monkeypatch.setattr( mod, "_default_paths", lambda root: seen.append( root ) or [ ] )
        monkeypatch.setattr( mod, "_default_read",  lambda path: "" )
        mod.main( [ ] )
        assert seen == [ mod.DEFAULT_ROOT ]


def test_running_the_script_without_lupin_root_refuses_to_guess( monkeypatch ):
    """
    The bootstrap contract: no LUPIN_ROOT is a loud RuntimeError, never a guess.

    Run through runpy rather than the already-imported module, because the guard fires
    at IMPORT and `mod` is long past that point — asserting against `mod` here would
    test nothing and pass.
    """
    import runpy
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        runpy.run_path( os.path.join( _ROOT, "src", "scripts", "find_interchangeable_assertions.py" ),
                        run_name="__main__" )
