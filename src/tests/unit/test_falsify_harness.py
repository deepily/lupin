"""
Tests for src/scripts/falsify.py -- the mutation harness that proves WHERE a falsifier bit.

THE DEFECT UNDER TEST, restated because it is the reason every assertion here exists: a
mutation aimed at one function that silently lands in another STILL PRODUCES A RED, and
that red is indistinguishable from a real one. It happened on 2026-08-25 (row d2e23ecb)
when a pattern carrying an 8-space indent matched a legacy copy instead of the dedented
builder it named.

⇒ So the harness's refusals are the load-bearing behaviour, not its happy path, and they
are tested here as HARD FAILURES. A future change that turns any refusal into a warning
must break these tests -- that is what test_refusals_are_hard_not_warnings is for.
"""
import importlib.util
import textwrap
from pathlib import Path

import pytest

ROOT = Path( __file__ ).resolve().parents[ 3 ]
SPEC = importlib.util.spec_from_file_location( "falsify", ROOT / "src" / "scripts" / "falsify.py" )
fz   = importlib.util.module_from_spec( SPEC )
SPEC.loader.exec_module( fz )


SAMPLE = textwrap.dedent( '''
    def builder_a( x ):
        """Dedented to FOUR spaces, like a phase-5 builder."""
        value = compute( x, "the-default" )
        return value


    def legacy_copy( x ):
        if True:
            # EIGHT spaces -- the same statement, the shape that caused the original bug
            value = compute( x, "the-default" )
            return value
''' ).lstrip()


@pytest.fixture
def sample( tmp_path ):
    p = tmp_path / "sample.py"
    p.write_text( SAMPLE )
    return p


# ─────────────────────────────────────────────── structural lookup

def test_span_finds_a_function_by_name_whatever_its_indentation( sample ):
    lo, hi = fz.span_of( str( sample ), "builder_a" )
    body   = SAMPLE.split( "\n" )[ lo : hi ]
    assert any( "builder_a" in l for l in body )
    assert not any( "legacy_copy" in l for l in body ), "span leaked into the next function"


def test_span_refuses_an_unknown_function( sample ):
    with pytest.raises( fz.MutationRefused, match="no module-level function" ):
        fz.span_of( str( sample ), "does_not_exist" )


# ─────────────────────────────────────────────── the original bug, pinned

def test_a_four_space_pattern_lands_in_the_builder_not_the_legacy_copy( sample ):
    """The exact failure from row d2e23ecb: same statement, two indents, one intended target."""
    line = fz.apply_mutation( str( sample ), "builder_a",
                              'value = compute( x, "the-default" )',
                              'value = compute( x, "MUTATED" )' )
    after = sample.read_text().split( "\n" )
    assert 'MUTATED' in after[ line - 1 ]
    lo, hi = fz.span_of( str( sample ), "legacy_copy" )
    assert 'MUTATED' not in "\n".join( after[ lo : hi ] ), "mutation leaked into the legacy copy"


def test_an_eight_space_pattern_still_lands_in_the_four_space_builder( sample ):
    """Indentation is STRIPPED before matching, so a dedent cannot redirect a falsifier."""
    line = fz.apply_mutation( str( sample ), "builder_a",
                              '        value = compute( x, "the-default" )',
                              '        value = compute( x, "MUTATED" )' )
    lo, hi = fz.span_of( str( sample ), "builder_a" )
    assert 'MUTATED' in "\n".join( sample.read_text().split( "\n" )[ lo : hi ] )


def test_replacement_is_reindented_to_the_line_it_replaced( sample ):
    fz.apply_mutation( str( sample ), "builder_a",
                       'value = compute( x, "the-default" )',
                       'value = compute( x, "MUTATED" )' )
    hit = next( l for l in sample.read_text().split( "\n" ) if "MUTATED" in l )
    assert hit.startswith( "    value" ) and not hit.startswith( "     " )


# ─────────────────────────────────────────────── the refusals

def test_zero_matches_inside_the_named_function_is_refused( sample ):
    with pytest.raises( fz.MutationRefused, match="matched 0 times" ):
        fz.apply_mutation( str( sample ), "builder_a", "no_such_statement()", "x = 1" )


def test_two_matches_inside_the_named_function_is_refused( tmp_path ):
    """Ambiguity is a refusal too -- picking one silently is the same class of defect."""
    p = tmp_path / "dup.py"
    p.write_text( "def f( x ):\n    y = same( x )\n    y = same( x )\n    return y\n" )
    with pytest.raises( fz.MutationRefused, match="matched 2 times" ):
        fz.apply_mutation( str( p ), "f", "y = same( x )", "y = other( x )" )


def test_refusals_are_hard_not_warnings( sample ):
    """
    🔴 THE ANTI-DOWNGRADE PIN. Every refusal must RAISE and must leave the file untouched.
    A harness that warns about mutating blind is a harness that mutates blind, and the red
    it goes on to produce means nothing. If someone converts these to warnings, this test
    is what stops it reaching the tree.
    """
    before = sample.read_text()
    for args in [ ( "builder_a", "no_such_statement()", "x = 1" ),
                  ( "does_not_exist", 'value = compute( x, "the-default" )', "x = 1" ) ]:
        with pytest.raises( fz.MutationRefused ):
            fz.apply_mutation( str( sample ), *args )
    assert sample.read_text() == before, "a refused mutation still modified the file"


# ─────────────────────────────────────────────── restore + exit codes

def test_the_target_is_restored_even_when_the_suite_run_explodes( sample, monkeypatch ):
    before = sample.read_text()
    monkeypatch.setattr( fz, "run_suite", lambda suite: ( 1 / 0 ) )
    with pytest.raises( ZeroDivisionError ):
        fz.falsify( str( sample ), "irrelevant.py", "builder_a",
                    'value = compute( x, "the-default" )', 'value = compute( x, "MUTATED" )',
                    "boom", out=lambda *a: None )
    assert sample.read_text() == before


@pytest.mark.parametrize( "failed,expected", [ ( [ "test_a" ], 0 ), ( [], 1 ) ] )
def test_exit_code_distinguishes_fired_from_blind( sample, monkeypatch, failed, expected ):
    """0 = the falsifier fired; 1 = it applied and NOTHING reddened, which is the finding."""
    monkeypatch.setattr( fz, "run_suite", lambda suite: ( failed, "summary" ) )
    rc = fz.falsify( str( sample ), "irrelevant.py", "builder_a",
                     'value = compute( x, "the-default" )', 'value = compute( x, "MUTATED" )',
                     "label", out=lambda *a: None )
    assert rc == expected
    assert sample.read_text() == SAMPLE, "target not restored"


def test_refusal_exit_code_is_two( sample ):
    rc = fz.falsify( str( sample ), "irrelevant.py", "does_not_exist", "a", "b", "label", out=lambda *a: None )
    assert rc == 2


# ─────────────────────────────────────────────── the "it moved" refusal

def test_a_mutation_that_moved_after_reparse_is_refused( sample, monkeypatch ):
    """
    The last line of defence: the file is re-parsed AFTER writing and the mutation must
    still be inside the function it was aimed at. Editing a function can change what the
    parser considers that function's span -- a decorator, a stray dedent, a broken block --
    and a mutation that slid outside is the original defect in a new costume.
    """
    real = fz.span_of
    calls = { "n": 0 }
    def drifting( path, name ):
        calls[ "n" ] += 1
        lo, hi = real( path, name )
        return ( lo, lo + 1 ) if calls[ "n" ] > 1 else ( lo, hi )   # second call reports a shrunken span
    monkeypatch.setattr( fz, "span_of", drifting )
    with pytest.raises( fz.MutationRefused, match="it moved" ):
        fz.apply_mutation( str( sample ), "builder_a",
                           'value = compute( x, "the-default" )', 'value = compute( x, "MUTATED" )' )


# ─────────────────────────────────────────────── run_suite

def test_run_suite_reports_failed_cases_by_name_and_the_summary( monkeypatch ):
    class _R:
        stdout = ( "FAILED src/tests/unit/x.py::test_one\n"
                   "FAILED src/tests/unit/x.py::TestK::test_two\n"
                   "2 failed, 5 passed in 0.10s\n" )
    monkeypatch.setattr( fz.subprocess, "run", lambda *a, **k: _R() )
    failed, summary = fz.run_suite( "irrelevant.py" )
    assert failed  == [ "test_one", "test_two" ]
    assert summary == "2 failed, 5 passed in 0.10s"


def test_run_suite_survives_output_with_no_summary_line( monkeypatch ):
    class _R: stdout = "collected nothing at all\n"
    monkeypatch.setattr( fz.subprocess, "run", lambda *a, **k: _R() )
    failed, summary = fz.run_suite( "irrelevant.py" )
    assert failed == [] and summary == "(no summary)"


def test_run_suite_disables_random_ordering_so_names_are_reproducible( monkeypatch ):
    seen = {}
    class _R: stdout = "1 passed\n"
    def capture( cmd, **k ):
        seen[ "cmd" ] = cmd; seen[ "env" ] = k.get( "env", {} ); return _R()
    monkeypatch.setattr( fz.subprocess, "run", capture )
    fz.run_suite( "some_suite.py" )
    assert "no:randomly" in seen[ "cmd" ], "a falsifier that names different cases each run names nothing"
    assert seen[ "env" ][ "PYTHONPATH" ] == "src"


# ─────────────────────────────────────────────── the CLI

def test_main_wires_the_files_through_and_returns_the_exit_code( tmp_path, sample, monkeypatch ):
    old = tmp_path / "old.txt"; old.write_text( 'value = compute( x, "the-default" )' )
    new = tmp_path / "new.txt"; new.write_text( 'value = compute( x, "MUTATED" )' )
    monkeypatch.setattr( fz, "run_suite", lambda suite: ( [ "test_named" ], "1 failed" ) )
    rc = fz.main( [ "--target", str( sample ), "--suite", "s.py", "--func", "builder_a",
                    "--old", str( old ), "--new", str( new ), "--label", "cli" ] )
    assert rc == 0
    assert sample.read_text() == SAMPLE, "CLI path did not restore the target"


def test_main_returns_two_when_the_mutation_is_refused( tmp_path, sample ):
    old = tmp_path / "old.txt"; old.write_text( "nothing_matches_this()" )
    new = tmp_path / "new.txt"; new.write_text( "x = 1" )
    rc = fz.main( [ "--target", str( sample ), "--suite", "s.py", "--func", "builder_a",
                    "--old", str( old ), "--new", str( new ) ] )
    assert rc == 2
