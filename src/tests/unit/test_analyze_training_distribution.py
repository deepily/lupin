"""
Unit tests for src/scripts/analyze-training-distribution.py — the LORA training-data report.

WHY THIS FILE EXISTS (row 6ed420a9, epic e2099400): `src/scripts` is entering the coverage
frame and this module sat at ZERO — 120 statements, 28 branches, nothing measured.

🔴 THE LOAD MECHANISM, DECIDED BY MEASUREMENT BEFORE ANY TEST WAS WRITTEN, because the
   filename contains DASHES and the row warned the previous approach would not transfer.

   · A BARE IMPORT IS NOT MERELY UNCONVENTIONAL, IT IS A SYNTAX ERROR. `import
     analyze-training-distribution` parses the dashes as subtraction:
     `SyntaxError: invalid syntax`. The `sys.path` + bare-import route used for the other
     src/scripts files is unavailable here, exactly as the row said.

   · THE DASH IS NOT A COVERAGE PROBLEM. That was the open question — Rachel found a file
     in this directory that coverage cannot see at all because of a DOT in its stem, and a
     dash could plausibly hit the same filter. It does not. Measured with a throwaway probe
     that only loaded the module and asserted nothing: coverage reported
     `src/scripts/analyze-training-distribution.py  120 stmts  28 branch  9%`. A file it
     could not address would have been absent from the report, not present at 9%.

   ⇒ CHOSEN: `importlib.util.spec_from_file_location` by absolute path. NOT `runpy`, and the
     decisive reason is mechanical rather than aesthetic: `spec_from_file_location` sets
     `__name__` to the name you pass, so the module's `if __name__ == "__main__"` guard stays
     shut, whereas runpy would execute `main()` on every load — printing a full report and
     reading real data files. NOT `subprocess` either: it puts the code in another process
     where this tier's coverage does not follow it, and turns every assertion into
     string-matching on stdout. Maya reached the same choice independently for her own dashed
     file (row 3b78bc8a); the reasoning is recorded on both rows.

⚠️ THE DATA DIRECTORY IS RESOLVED AT IMPORT TIME. `DATA_DIR` is computed once, at module
level, from `lupin_root`. Setting `LUPIN_ROOT` inside a test therefore does NOT move it — the
module already read it. The lever that works is rebinding `mod.DATA_DIR`, and it is autouse
so no test can read the developer's real training data by forgetting a fixture. The module is
read-only — it prints a report and writes nothing — so the hazard here is a test that
silently passes against the real corpus, not one that destroys anything.

⚠️ WHERE PATCHES ARE AIMED, AND WHY IT IS NOT A STYLE CHOICE. Every patch here targets a name
ON THE MODULE UNDER TEST, never a method on a shared package. The one test needing a
different `read_json` rebinds `mod.pd` to a shim rather than doing
`setattr( mod.pd, "read_json", ... )` — the latter reaches THROUGH to the real pandas module
and changes it for every importer in the process. monkeypatch restores it, so serially it is
contained; under parallel execution it would not be. Bounded by measurement: this module's
only non-stdlib collaborator is pandas, at exactly one call site — `pd.read_json`, line 104.
"""

import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest


def _load_module():
    """
    Load the dashed-name script by PATH.

    A bare `import` is a SyntaxError on this filename; see the module docstring for the
    measurement behind this choice and the proof that coverage still attributes lines to
    the file when it is loaded this way.
    """
    root = os.environ[ "LUPIN_ROOT" ]
    path = os.path.join( root, "src", "scripts", "analyze-training-distribution.py" )
    spec = importlib.util.spec_from_file_location( "analyze_training_distribution", path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ spec.name ] = module
    spec.loader.exec_module( module )
    return module


mod = _load_module()

TRAIN = "voice-commands-xml-train.jsonl"


# ── fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture( autouse=True )
def data_dir( tmp_path, monkeypatch ):
    """
    Point DATA_DIR at a temp directory for EVERY test.

    Autouse because DATA_DIR is import-time: a test that forgot to redirect would read the
    developer's real training data and pass for the wrong reason.
    """
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setattr( mod, "DATA_DIR", str( directory ) )
    return directory


def _write_jsonl( directory, filename, commands ):
    """Write one row per command, in the shape the report reads."""
    path = Path( directory ) / filename
    with open( path, "w", encoding="utf-8" ) as f:
        for command in commands:
            f.write( json.dumps( { "command": command, "text": "x" } ) + "\n" )
    return path


def _train( directory, commands ):
    return _write_jsonl( directory, TRAIN, commands )


class _PandasShim:
    """
    Stands in for the module's `pd`, wrapping ONLY read_json.

    Bound to `mod.pd`, never onto the real pandas module: patching a method on the shared
    package would change read_json for every other importer while the test runs.
    """

    def __init__( self, real, transform ):
        self._real      = real
        self._transform = transform

    def read_json( self, path, **kwargs ):
        return self._transform( self._real.read_json( path, **kwargs ) )


# ── the guard itself ─────────────────────────────────────────────────────────────

def test_the_data_directory_is_redirected_away_from_the_real_tree( data_dir ):
    """A test reading the real corpus would pass for the wrong reason; assert the redirect."""
    assert mod.DATA_DIR == str( data_dir )
    assert "ephemera" not in mod.DATA_DIR


# ── categorize_command ───────────────────────────────────────────────────────────

@pytest.mark.parametrize( "command,expected", [
    ( "agent router go to math", "Agent Router" ),
    ( "search google for pizza", "Browser Search" ),
    ( "go to gmail",             "Browser Navigation" ),
    ( "what time is it",         "Other" ),
] )
def test_each_command_family_gets_its_own_category( command, expected ):
    assert mod.categorize_command( command ) == expected


def test_the_category_match_is_a_prefix_not_a_substring():
    """'go to' inside a sentence is not navigation; only a command that STARTS with it is."""
    assert mod.categorize_command( "please go to gmail" ) == "Other"
    assert mod.categorize_command( "i want to search the web" ) == "Other"


# ── print_separator ──────────────────────────────────────────────────────────────

def test_the_separator_defaults_to_a_hundred_dashes( capsys ):
    mod.print_separator()
    assert capsys.readouterr().out == "-" * 100 + "\n"


def test_the_separator_honours_a_character_and_a_width( capsys ):
    mod.print_separator( "=", 5 )
    assert capsys.readouterr().out == "=====\n"


# ── the file inventory ───────────────────────────────────────────────────────────

def test_present_files_are_counted_and_absent_ones_are_marked_missing( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 3 )

    mod.main()

    out = capsys.readouterr().out
    assert "voice-commands-xml-train.jsonl" in out
    assert out.count( "MISSING" ) == 2, "the two files never written must be reported, not skipped"


def test_the_inventory_total_is_the_sum_of_the_rows_present( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 3 )
    _write_jsonl( data_dir, "voice-commands-xml-test.jsonl", [ "search x" ] * 4 )

    mod.main()

    out = capsys.readouterr().out
    total_line = [ l for l in out.splitlines() if l.strip().startswith( "TOTAL" ) ][ 0 ]
    assert total_line.split()[ -1 ] == "7"


def test_a_missing_training_file_exits_one_and_names_the_path( data_dir, capsys ):
    with pytest.raises( SystemExit ) as info:
        mod.main()

    assert info.value.code == 1
    assert "ERROR: Training file not found" in capsys.readouterr().out


# ── the distribution report ──────────────────────────────────────────────────────

def test_the_report_counts_samples_and_distinct_commands( data_dir, capsys ):
    _train( data_dir, [ "go to gmail", "go to gmail", "search x" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "Total training samples: 3" in out
    assert "Unique commands: 2" in out


def test_every_category_present_in_the_data_is_reported( data_dir, capsys ):
    _train( data_dir, [ "agent router go to math", "search x", "go to gmail", "hello" ] )

    mod.main()
    out = capsys.readouterr().out

    for category in ( "Browser Search", "Browser Navigation", "Agent Router", "Other" ):
        assert category in out


def test_a_category_absent_from_the_data_is_omitted_rather_than_printed_as_zero( data_dir, capsys ):
    """The `if cat in cat_counts` arm: a category with no samples must not get a row."""
    _train( data_dir, [ "go to gmail" ] * 2 )

    mod.main()

    out = capsys.readouterr().out
    category_block = out.split( "CATEGORY BREAKDOWN" )[ 1 ].split( "SUMMARY STATISTICS" )[ 0 ]
    assert "Browser Navigation" in category_block
    assert "Browser Search" not in category_block
    assert "Agent Router" not in category_block


# ── the agent-router detail section ──────────────────────────────────────────────

def test_the_agent_router_section_appears_when_such_commands_exist( data_dir, capsys ):
    _train( data_dir, [ "agent router go to math", "agent router go to math", "go to gmail" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "AGENT ROUTER COMMANDS (detail)" in out
    assert "SUBTOTAL" in out


def test_the_agent_router_section_is_skipped_entirely_when_there_are_none( data_dir, capsys ):
    _train( data_dir, [ "go to gmail", "search x" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "AGENT ROUTER COMMANDS (detail)" not in out
    assert "SUBTOTAL" not in out


# ── imbalance analysis ───────────────────────────────────────────────────────────

def test_a_balanced_distribution_is_reported_as_reasonable( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 3 + [ "search x" ] * 3 )

    mod.main()

    out = capsys.readouterr().out
    assert "Distribution looks reasonably balanced" in out
    assert "WARNING" not in out
    assert "MODERATE" not in out


def test_a_six_to_one_spread_is_reported_as_moderate( data_dir, capsys ):
    """Between 5x and 10x — the middle arm, which a two-way test would never reach."""
    _train( data_dir, [ "go to gmail" ] * 6 + [ "search x" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "MODERATE" in out
    assert "6x imbalance" in out
    assert "WARNING" not in out


def test_a_twenty_to_one_spread_is_reported_as_a_warning( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 20 + [ "search x" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "20x imbalance detected" in out
    assert "MODERATE" not in out


def test_the_most_and_least_sampled_commands_are_named( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 5 + [ "search x" ] )

    mod.main()

    out = capsys.readouterr().out
    assert "Most samples      : go to gmail" in out
    assert "Fewest samples    : search x" in out


def test_a_command_with_zero_samples_makes_the_ratio_unbounded( data_dir, capsys, monkeypatch ):
    """
    The `if counts.min() > 0 ... else inf` guard.

    Ordinary data cannot reach the else arm — value_counts never yields 0 for a value that
    is present. A CATEGORICAL column can: pandas reports unobserved categories at 0. So this
    uses real pandas rather than a stubbed frame, and the guard turns out to be REACHABLE
    rather than dead code needing a pragma.
    """
    _train( data_dir, [ "go to gmail" ] * 4 )

    def _make_categorical( frame ):
        frame[ "command" ] = pd.Categorical(
            frame[ "command" ], categories=[ "go to gmail", "never happened" ]
        )
        return frame

    monkeypatch.setattr( mod, "pd", _PandasShim( pd, _make_categorical ) )

    # 🔴 THE ASSERTION THAT ACTUALLY PINS THE GUARD, and it took a surviving mutation to
    # find it. Deleting the guard entirely does NOT change the printed output: numpy's
    # integer division by zero already yields inf, so `counts.max() / counts.min()` prints
    # the same "infx" either way. The ONLY observable difference is the RuntimeWarning
    # numpy emits on that division — which is precisely what the guard exists to avoid. An
    # output-only assertion here was green against unguarded code.
    with warnings.catch_warnings():
        warnings.simplefilter( "error", RuntimeWarning )
        mod.main()

    out = capsys.readouterr().out
    assert "Max/Min ratio     : infx" in out
    assert "Fewest samples    : never happened (0)" in out


# ── summary statistics ───────────────────────────────────────────────────────────

def test_the_summary_reports_min_max_mean_median_and_spread( data_dir, capsys ):
    _train( data_dir, [ "go to gmail" ] * 4 + [ "search x" ] * 2 )

    mod.main()

    out = capsys.readouterr().out
    assert "Min    :       2" in out
    assert "Max    :       4" in out
    assert "Mean   :     3.0" in out
    assert "Median :     3.0" in out
    assert "Std Dev:" in out


# ── the import-time bootstrap ────────────────────────────────────────────────────
#
# The bootstrap runs once at import. Unlike the other src/scripts files, its LUPIN_ROOT-
# missing arm is a FALLBACK rather than a refusal — it derives the root from __file__ — so
# both arms are live behaviour worth pinning. Re-executed from source, compiled under the
# file's REAL filename so coverage attributes the lines to it.

def _exec_bootstrap( namespace_name="analyze_training_distribution_bootstrap_probe" ):
    source_path = Path( mod.__file__ )
    code        = compile( source_path.read_text( encoding="utf-8" ), str( source_path ), "exec" )
    namespace   = { "__name__": namespace_name, "__file__": str( source_path ) }
    exec( code, namespace )
    return namespace


def test_the_bootstrap_uses_lupin_root_when_it_is_set( monkeypatch, tmp_path ):
    fake = tmp_path / "elsewhere"
    ( fake / "src" ).mkdir( parents=True )
    expected = os.path.join( str( fake ), "src" )

    original_path = list( sys.path )
    try:
        monkeypatch.setenv( "LUPIN_ROOT", str( fake ) )
        namespace = _exec_bootstrap()
        assert sys.path[ 0 ] == expected
        assert namespace[ "DATA_DIR" ].startswith( str( fake ) )
    finally:
        sys.path[ : ] = original_path


def test_the_bootstrap_derives_the_root_from_its_own_location_when_lupin_root_is_absent( monkeypatch ):
    """
    The fallback arm. It walks up from __file__: src/scripts -> src -> the checkout, so a
    run with no environment still finds the data directory next to the script.
    """
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    source_path   = Path( mod.__file__ )
    expected_src  = str( source_path.parent.parent )
    expected_root = str( source_path.parent.parent.parent )

    original_path = list( sys.path )
    try:
        # 🔴 THE SETUP THAT MAKES THE ASSERTION MEAN ANYTHING, found by a surviving mutation.
        # This worktree's own src dir is normally ALREADY at sys.path[0], put there by the
        # test harness — so "assert sys.path[0] == expected_src" was true before the
        # bootstrap ran, and stayed true when insert(0) was mutated to append(). Clearing it
        # out and parking a sentinel at position 0 is what turns the assertion into a
        # measurement of what the bootstrap did.
        sys.path[ : ] = [ q for q in sys.path if q != expected_src ]
        sys.path.insert( 0, "/nonexistent-sentinel-for-position-zero" )
        namespace = _exec_bootstrap()
        assert sys.path[ 0 ] == expected_src, "the derived src dir must go on the path first"
        assert namespace[ "lupin_root" ] == expected_root
        assert namespace[ "DATA_DIR" ] == os.path.join(
            expected_root, "src", "ephemera", "prompts", "data"
        )
    finally:
        sys.path[ : ] = original_path


def test_the_two_bootstrap_arms_agree_when_lupin_root_points_at_the_real_checkout( monkeypatch ):
    """
    A fallback that disagreed with the environment would be worse than no fallback: the
    script would read a different data directory depending on how it was launched.
    """
    source_path   = Path( mod.__file__ )
    expected_root = str( source_path.parent.parent.parent )

    original_path = list( sys.path )
    try:
        monkeypatch.setenv( "LUPIN_ROOT", expected_root )
        with_env = _exec_bootstrap()
        monkeypatch.delenv( "LUPIN_ROOT" )
        without_env = _exec_bootstrap()
        assert with_env[ "DATA_DIR" ] == without_env[ "DATA_DIR" ]
    finally:
        sys.path[ : ] = original_path
