"""
Unit tests for `src/scripts/bridge_pin_sweep.py` — the detector that finds tests
driving bridge-reading code without pinning the bridge.

LOAD MECHANISM: `importlib.import_module( "bridge_pin_sweep" )` with `src/scripts`
on `sys.path`, matching `test_watch_hook_events.py`. The stem is a valid identifier
here, but the string form is used anyway so the two script tests load the same way.

WHY THE `__main__` BLOCK IS EXERCISED WITH `runpy` RATHER THAN LEFT UNCOVERED: the
block is where the three exit codes are decided, and those codes are the whole
interface — a caller distinguishes "the detector is broken" from "the detector found
work" by nothing else. `runpy.run_path( ..., run_name="__main__" )` re-executes the
module so the block actually runs; `os.walk` is redirected so the sweep reads a
fixture tree instead of the hardcoded `TEST_ROOT`.

⚠️ `TEST_ROOT` IS AN ABSOLUTE PATH INTO THE MAIN CHECKOUT
(`/mnt/.../projects/lupin/src/tests`), so the default argument of `sweep()` reads
the main tree no matter which worktree the caller stands in. Every test here passes
`test_root=` explicitly or redirects `os.walk`; none relies on the default. Reported
to the fleet rather than fixed here — this file adds tests, it does not change the
script.
"""

import importlib
import os
import re
import runpy
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

bps = importlib.import_module( "bridge_pin_sweep" )

SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "bridge_pin_sweep.py" )


# ── source fragments the fixtures are built from ─────────────────────────────

DRIVING = (
    "class TestProbe:\n"
    "    def test_drives_unpinned( self, monkeypatch ):\n"
    "        cv._notify_impl( \"hello\" )\n"
)

PINNED = (
    "class TestProbe:\n"
    "    def test_drives_pinned( self, monkeypatch ):\n"
    "        monkeypatch.setattr( sb, \"get_speakerphone\", lambda sid: False )\n"
    "        cv._notify_impl( \"hello\" )\n"
)


# ── helper_bodies ────────────────────────────────────────────────────────────

def test_helper_bodies_splits_each_helper_and_runs_the_last_to_end_of_file():
    """
    Ensures:
        - every `_private` def becomes a key
        - a non-final helper's body stops at the next helper
        - the final helper's body runs to the end of the source
    """
    src = (
        "    def _first( self ):\n"
        "        FIRST_MARKER = 1\n"
        "    def _second( self ):\n"
        "        SECOND_MARKER = 2\n"
    )
    out = bps.helper_bodies( src )
    assert set( out ) == { "_first", "_second" }
    assert "FIRST_MARKER"  in out[ "_first" ]
    assert "SECOND_MARKER" not in out[ "_first" ]      # stopped at the next def
    assert "SECOND_MARKER" in out[ "_second" ]         # ran to end of source


def test_helper_bodies_is_empty_when_there_are_no_private_helpers():
    assert bps.helper_bodies( "def test_a():\n    pass\n" ) == { }


# ── functions ────────────────────────────────────────────────────────────────

def test_functions_body_stops_at_the_next_test_def():
    src = (
        "def test_one():\n"
        "    ONE_MARKER = 1\n"
        "def test_two():\n"
        "    TWO_MARKER = 2\n"
    )
    got = dict( bps.functions( src ) )
    assert set( got ) == { "test_one", "test_two" }
    assert "TWO_MARKER" not in got[ "test_one" ]
    assert "TWO_MARKER" in got[ "test_two" ]


@pytest.mark.parametrize( "divider", [ "# ── next section ──", "class Later:" ] )
def test_functions_body_is_cut_at_a_section_divider_or_a_class( divider ):
    """
    The cut is the reason a test that does NOT call the driver stays unreported:
    without it the body swallows a trailing header naming `_notify_impl`.
    """
    src = f"def test_one():\n    KEPT = 1\n{divider}\n    _notify_impl_MENTION = 1\n"
    ( _name, body ), = bps.functions( src )
    assert "KEPT" in body
    assert "_notify_impl_MENTION" not in body


def test_functions_yields_nothing_when_no_test_defs_exist():
    assert list( bps.functions( "x = 1\n" ) ) == [ ]


# ── classify ─────────────────────────────────────────────────────────────────

def test_classify_returns_nothing_when_no_driver_appears_anywhere():
    assert bps.classify( "def test_a():\n    pass\n" ) == [ ]


def test_classify_flags_a_test_that_drives_the_impl_without_pinning():
    ( label, fn, drivers, unpinned ), = bps.classify( DRIVING, "probe.py" )
    assert label    == "probe.py"
    assert fn       == "test_drives_unpinned"
    assert drivers  == [ "_notify_impl" ]
    assert unpinned == [ "get_speakerphone" ]


def test_classify_default_label_is_used_when_none_is_given():
    ( label, _fn, _d, _u ), = bps.classify( DRIVING )
    assert label == "<memory>"


@pytest.mark.parametrize( "isolator", sorted( bps.ISOLATORS ) )
def test_classify_treats_every_declared_isolator_as_a_pin( isolator ):
    """
    One case per entry of ISOLATORS. If any stops being recognised the sweep starts
    inventing work, which is the failure the script's own docstring records.
    """
    src = DRIVING + f"        USE = {isolator}\n"
    ( _l, _f, _d, unpinned ), = bps.classify( src )
    assert unpinned == [ ]


def test_classify_counts_a_pin_that_lives_in_a_shared_helper():
    """
    The pin is in `_arrange`, not in the test body — a sweep reading bodies alone
    would call this exposed and send someone to fix correct code.

    🔴 THE HELPER MUST BE DEFINED BEFORE THE TEST, AND THAT IS THE WHOLE FIXTURE.
    `functions()` runs a test's body to the NEXT test def, or to end-of-file when there
    is none. So a helper written BELOW the last test is already inside that test's span,
    and `classify` sees the pin whether or not it appends helper bodies at all.

    Measured 2026-08-30: with the helper below the test, deleting the append
    (`body += helpers.get( h, "" )` -> `body += ""`) leaves this test GREEN — the
    assertion is correct, correctly named, and structurally blind. With the helper above
    it, the same deletion reports `[ "get_speakerphone" ]` and the test reddens.

    ⇒ The defect was the fixture's ORDER, never the assertion. Do not "simplify" this by
    moving `_arrange` back below the test.
    """
    src = (
        "class TestProbe:\n"
        "    def _arrange( self ):\n"
        "        monkeypatch.setattr( sb, \"get_speakerphone\", lambda sid: False )\n"
        "    def test_uses_helper( self ):\n"
        "        self._arrange()\n"
        "        cv._notify_impl( \"hello\" )\n"
        "    def test_after( self ):\n"
        "        pass\n"
    )
    ( _l, _f, _d, unpinned ), = bps.classify( src )
    assert unpinned == [ ]


def test_classify_counts_a_file_level_autouse_pin_for_every_test_in_the_file():
    src = (
        "@pytest.fixture( autouse=True )\n"
        "def _pin( monkeypatch ):\n"
        "    monkeypatch.setattr( sb, \"get_speakerphone\", lambda sid: False )\n"
        "\n"
        "def test_drives( monkeypatch ):\n"
        "    cv._notify_impl( \"hello\" )\n"
    )
    ( _l, _f, _d, unpinned ), = bps.classify( src )
    assert unpinned == [ ]


def test_classify_skips_a_test_that_does_not_itself_call_the_driver():
    """
    The driver appears in the FILE — so the early return does not fire — but not in
    this test's body, so the test contributes no row.
    """
    src = DRIVING + "def test_unrelated():\n    pass\n"
    names = [ r[ 1 ] for r in bps.classify( src ) ]
    assert names == [ "test_drives_unpinned" ]


def test_classify_calls_a_missing_helper_harmless():
    """A `self._absent()` call inlines nothing and must not raise."""
    src = (
        "class TestProbe:\n"
        "    def test_calls_absent( self ):\n"
        "        self._absent()\n"
        "        cv._notify_impl( \"hello\" )\n"
    )
    ( _l, _f, _d, unpinned ), = bps.classify( src )
    assert unpinned == [ "get_speakerphone" ]


# ── sweep ────────────────────────────────────────────────────────────────────

def _tree( root, files ):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    return str( root )


def test_sweep_walks_a_tree_and_labels_rows_relative_to_the_root( tmp_path ):
    root = _tree( tmp_path, { "sub/test_probe.py": DRIVING } )
    ( label, fn, _d, unpinned ), = bps.sweep( test_root=root )
    assert label    == os.path.join( "sub", "test_probe.py" )
    assert fn       == "test_drives_unpinned"
    assert unpinned == [ "get_speakerphone" ]


def test_sweep_skips_a_logs_directory_and_every_non_python_file( tmp_path ):
    root = _tree( tmp_path, {
        "logs/test_in_logs.py" : DRIVING,   # skipped: "/logs" in dirpath
        "notes.txt"            : DRIVING,   # skipped: not a .py
        "test_real.py"         : DRIVING,
    } )
    labels = [ r[ 0 ] for r in bps.sweep( test_root=root ) ]
    assert labels == [ "test_real.py" ]


def test_sweep_reads_a_file_that_is_not_valid_utf8( tmp_path ):
    """`errors="replace"` — undecodable bytes must not abort the whole sweep."""
    ( tmp_path / "test_bad.py" ).write_bytes( DRIVING.encode() + b"\n# \xff\xfe\n" )
    rows = bps.sweep( test_root=str( tmp_path ) )
    assert [ r[ 1 ] for r in rows ] == [ "test_drives_unpinned" ]


def test_sweep_returns_nothing_for_an_empty_tree( tmp_path ):
    assert bps.sweep( test_root=str( tmp_path ) ) == [ ]


# ── self_test ────────────────────────────────────────────────────────────────

def test_self_test_passes_against_the_real_detector():
    assert bps.self_test() == [ ]


def test_self_test_reports_a_detector_that_has_stopped_flagging( monkeypatch ):
    """
    The negative control: with `classify` blinded, an unpinned driver is no longer
    flagged and the sweep's 0 would mean nothing. The failure must say so.
    """
    monkeypatch.setattr( bps, "classify", lambda src, label="<memory>": [ ] )
    failures = bps.self_test()
    assert len( failures ) == 1
    assert "NEGATIVE CONTROL FAILED" in failures[ 0 ]


def test_self_test_reports_each_isolator_that_is_no_longer_recognised( monkeypatch ):
    """
    Every row is flagged as unpinned, so the negative control passes while all five
    isolators read as false positives — one failure line per isolator, naming it.
    """
    monkeypatch.setattr(
        bps, "classify",
        lambda src, label="<memory>": [ ( label, "test_x", [ "_notify_impl" ], [ "get_speakerphone" ] ) ] )
    failures = bps.self_test()
    assert len( failures ) == len( bps._ISOLATED )
    assert all( f.startswith( "FALSE POSITIVE" ) for f in failures )
    for name in bps._ISOLATED:
        assert any( name in f for f in failures )


# ── _driver_counts ───────────────────────────────────────────────────────────

def test_driver_counts_reports_zero_for_a_driver_no_row_mentions():
    assert bps._driver_counts( [ ] ) == { "_notify_impl": 0 }


def test_driver_counts_counts_only_rows_naming_that_driver():
    rows = [ ( "a.py", "t1", [ "_notify_impl" ], [ ] ),
             ( "b.py", "t2", [ ],                [ ] ) ]
    assert bps._driver_counts( rows ) == { "_notify_impl": 1 }


# ── the __main__ block and its three exit codes ──────────────────────────────

def _run_main( monkeypatch, capsys, walk_root ):
    """
    Execute the script as `__main__` with `os.walk` redirected at `walk_root`, so the
    sweep never reads the hardcoded TEST_ROOT. Returns ( exit_code, stdout ).
    """
    real_walk = os.walk
    monkeypatch.setattr( os, "walk", lambda _root: real_walk( walk_root ) )
    with pytest.raises( SystemExit ) as exc:
        runpy.run_path( SCRIPT_PATH, run_name="__main__" )
    return exc.value.code, capsys.readouterr().out


def test_main_exits_clean_and_names_a_driver_seen_by_nothing( tmp_path, monkeypatch, capsys ):
    """
    Empty tree: the self-test passes, nothing is unpinned — and the per-driver line
    reads 0, which the script prints as a tell because a blinded sweep and a clean
    tree otherwise report the same number.
    """
    code, out = _run_main( monkeypatch, capsys, str( tmp_path ) )
    assert code == bps.EXIT_CLEAN == 0
    assert "self-test: PASSED" in out
    assert "0 test(s) drive bridge-reading code; 0 do NOT pin" in out
    assert "ZERO: this driver is not being seen at all" in out


def test_main_exits_work_and_groups_findings_by_file( tmp_path, monkeypatch, capsys ):
    """
    Two unpinned tests in one file and one in another: the file header prints once
    per file, which is the `rel != seen` branch in both directions.
    """
    two_in_one = DRIVING + (
        "    def test_drives_unpinned_again( self, monkeypatch ):\n"
        "        cv._notify_impl( \"bye\" )\n"
    )
    _tree( tmp_path, { "test_a.py": two_in_one, "test_b.py": DRIVING } )
    code, out = _run_main( monkeypatch, capsys, str( tmp_path ) )
    assert code == bps.EXIT_WORK == 1
    assert "self-test: PASSED" in out
    assert "3 test(s) drive bridge-reading code; 3 do NOT pin" in out
    assert out.count( "test_a.py\n" ) == 1        # header printed once for two rows
    assert out.count( "test_b.py\n" ) == 1
    assert "ZERO: this driver" not in out


def test_main_exits_clean_when_every_driving_test_is_pinned( tmp_path, monkeypatch, capsys ):
    _tree( tmp_path, { "test_pinned.py": PINNED } )
    code, out = _run_main( monkeypatch, capsys, str( tmp_path ) )
    assert code == bps.EXIT_CLEAN == 0
    assert "1 test(s) drive bridge-reading code; 0 do NOT pin" in out


def test_main_exits_broken_and_refuses_to_stand_behind_its_own_count(
        tmp_path, monkeypatch, capsys ):
    """
    A detector that has stopped detecting must not report a count at all. Blinded by
    breaking the test-function regex the module compiles at import, so the failure is
    reached through the module's own code rather than by patching its functions —
    `runpy` re-executes the file, so a patched attribute would not survive.
    """
    real_compile = re.compile
    never = real_compile( r"(?!x)x" )
    monkeypatch.setattr(
        re, "compile",
        lambda pat, *a, **k: never if "def (test_" in pat else real_compile( pat, *a, **k ) )
    code, out = _run_main( monkeypatch, capsys, str( tmp_path ) )
    assert code == bps.EXIT_BROKEN == 2
    assert "WARNING  NEGATIVE CONTROL FAILED" in out
    assert "self-test: FAILED" in out
    assert "the counts above are NOT evidence" in out
