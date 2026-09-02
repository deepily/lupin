"""
The standing gate-reachability census (board row d97b024e).

WHY THIS FILE EXISTS: a test suite that no gate references cannot go red, and a
suite that cannot go red is indistinguishable from a suite that passes.
`src/tests/store_owed_cutover_e2e/` sat RED for roughly a month in exactly that
state; three people re-derived its absence by hand and no control anywhere
reported it.

A census that lives in a document decays the day it is written. This file is
the census as a GATE: it rides `src/tests/run-unit-tests.sh`, which the `unit`
test-type already runs, so it goes red on its own without anyone remembering
to look.

THE LEDGER: `gate-reachability-allowlist.json` beside this file. Every entry is
a file someone chose not to gate, with a dated reason. The point is not that
the list is short — after the src/cosa/tests/** wire-in (row c9d3ddcb) it is 88
entries long, down from 486 once those ~398 files became gate-reachable. The
point is that the gap is ENUMERATED instead of silent, and that adding the next
entry requires editing a checked-in file rather than nobody noticing.

THE RED ARM: `test_detector_reports_the_witness_when_not_allowlisted` runs the
detector against the original witness with the allowlist withdrawn and asserts
it fires. A detector that has never gone red is indistinguishable from one that
cannot, so that proof runs on every unit-suite pass — not once, at authoring time.
"""

import json
import os
import re
import subprocess

from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.repo.gate_reachability import (
    EXCLUDED_PATH_PARTS,
    SUITE_SCRIPTS_SOURCE,
    find_gate_targets,
    find_stale_allowlist_entries,
    find_test_file_population,
    find_unreferenced_test_files,
    find_zero_collect_test_files,
    read_suite_scripts,
    _defines_a_test,
    _is_reachable,
)


WITNESS = "src/tests/store_owed_cutover_e2e/test_store_owed_cutover_e2e.py"

ALLOWLIST_NAME = "gate-reachability-allowlist.json"


@pytest.fixture( scope="module" )
def project_root():
    """The Lupin repository root, as every gate-invocable runner resolves it."""
    return Path( cu.get_project_root() )


@pytest.fixture( scope="module" )
def allowlist( project_root ):
    """The checked-in ledger of deliberately-ungated test files."""
    path = project_root / "src/tests/unit" / ALLOWLIST_NAME
    return json.loads( path.read_text( encoding="utf-8" ) )


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_no_unreferenced_test_files_outside_the_allowlist( project_root, allowlist ):
    """A new test file must be reachable by a gate, or declared ungated with a reason."""
    unreferenced = find_unreferenced_test_files( project_root, allowlist )

    assert unreferenced == [], (
        f"{len( unreferenced )} test file(s) are reachable by NO gate-invocable runner and are "
        f"not declared in src/tests/unit/{ALLOWLIST_NAME}.\n"
        "Either wire them into a suite a test-type can invoke, or add each to the ledger with "
        "a dated reason:\n  " + "\n  ".join( unreferenced )
    )


def test_no_zero_collect_test_files_outside_the_allowlist( project_root, allowlist ):
    """A gated test_*.py that defines no test is inside the gate and still emitting nothing."""
    barren = find_zero_collect_test_files( project_root, allowlist )

    assert barren == [], (
        f"{len( barren )} file(s) named test_*.py sit inside a gated root but define no test — "
        "they look covered from every angle and contribute nothing.\n"
        "Give them real tests, rename them, or declare them in the ledger:\n  "
        + "\n  ".join( barren )
    )


def test_allowlist_has_no_stale_entries( project_root, allowlist ):
    """A standing exemption for a condition that no longer holds is the defect this row is about."""
    stale = find_stale_allowlist_entries( project_root, allowlist )

    assert stale == [], (
        f"{len( stale )} ledger entry(ies) no longer describe an unreachable test file — the file "
        "was deleted, or it was wired into a gate and the exemption was never withdrawn.\n"
        "Remove them from the ledger:\n  " + "\n  ".join( stale )
    )


def test_every_allowlist_entry_carries_a_reason( allowlist ):
    """An entry without a reason is a silence with extra steps."""
    reasonless = sorted( key for key, reason in allowlist.items() if not reason.strip() )

    assert reasonless == [], f"ledger entries with an empty reason: {reasonless}"


def test_every_allowlist_key_names_a_file_git_tracks( project_root, allowlist ):
    """
    The question the reason audit never asked: are the KEYS real?

    A reason can be audited by reading the file it points at. That check assumes
    the file is part of the project. An entry naming a path git has never tracked
    is an exemption for something that exists on ONE developer's disk and in no
    clone, worktree or CI checkout — so the ledger answers differently depending
    on which checkout you ask it from. Row c4dd7768: 14 `src/tmp/` entries were
    exactly that, and `test_allowlist_has_no_stale_entries` was green in the main
    checkout and red in every worktree because of them.

    Deliberately NOT skipped when git is unavailable — a guard that stands down
    when it cannot measure is the silence it was written to end. The ledger file
    itself is the proof that git answered: if it is absent from `git ls-files`,
    the command failed rather than the ledger being clean.
    """
    listing = subprocess.run(
        [ "git", "-C", str( project_root ), "ls-files" ],
        capture_output=True, text=True, check=True,
    )
    tracked = set( listing.stdout.split( "\n" ) )
    ledger  = f"src/tests/unit/{ALLOWLIST_NAME}"

    assert ledger in tracked, (
        f"git listed no tracked files at {project_root} — the listing failed, so this guard "
        "cannot conclude anything about the ledger's keys"
    )

    untracked = sorted( key for key in allowlist if key not in tracked )

    assert untracked == [], (
        f"{len( untracked )} ledger entry(ies) name a path git does not track, so they exempt "
        "files that exist in this checkout and in no other:\n  " + "\n  ".join( untracked )
    )


# ---------------------------------------------------------------------------
# The RED arm — proof the detector can fire
# ---------------------------------------------------------------------------

def test_detector_reports_the_witness_when_not_allowlisted( project_root, allowlist ):
    """
    Withdraw the witness's exemption and confirm the detector still names it.

    This is the arm that keeps the gate honest. If a future refactor made
    `find_unreferenced_test_files` return nothing under all conditions, every
    assertion above would pass silently; this one would not.
    """
    assert WITNESS in allowlist, "the witness must stay in the ledger for the gate to ship green"

    without_witness = { key: value for key, value in allowlist.items() if key != WITNESS }

    assert WITNESS in find_unreferenced_test_files( project_root, without_witness )


def test_detector_reports_a_freshly_added_unreachable_file( project_root, allowlist, tmp_path, monkeypatch ):
    """
    A file added today, in a directory no runner names, must surface immediately.

    Uses a synthetic tree rather than writing into the real repo — a detector
    that only works when you dirty the working copy is not one you can run on
    every unit pass.
    """
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/brand_new" ).mkdir( parents=True )
    ( tmp_path / "src/tests/brand_new/test_added_today.py" ).write_text( "def test_x(): pass\n" )

    assert find_unreferenced_test_files( tmp_path, {} ) == [ "src/tests/brand_new/test_added_today.py" ]


# ---------------------------------------------------------------------------
# Primitives — exercised on synthetic trees
# ---------------------------------------------------------------------------

def _build_synthetic_tree( root: Path ):
    """
    Build a miniature repo: one SUITE_SCRIPTS source, two runners, one gated suite.

    Ensures:
        - root contains src/cosa/agents/test_suite/job.py with a SUITE_SCRIPTS literal
        - `all` delegates to `unit`, so runner-following is exercised
        - src/tests/unit/ holds one collectible test file
    """
    job = root / "src/cosa/agents/test_suite"
    job.mkdir( parents=True )
    ( job / "job.py" ).write_text(
        "SUITE_SCRIPTS = {\n"
        '    "unit" : "src/tests/run-unit-tests.sh",\n'
        '    "all"  : "src/tests/run-all-tests.sh",\n'
        '    "gone" : "src/tests/run-missing.sh",\n'
        # 🔴 A DIGIT IN THE KEY. Every key here used to be lowercase-only, so the fixture
        # could not tell a `[a-z_]+` key class from a correct one — the assertions were
        # right and blind. The real literal carries `e2e` and `v2_eval`, and the narrow
        # class dropped both.
        '    "e2e"  : "src/tests/run-e2e-tests.sh",\n'
        "}\n"
    )

    tests = root / "src/tests"
    ( tests / "unit" ).mkdir( parents=True )
    ( tests / "unit/test_gated.py" ).write_text( "def test_ok(): pass\n" )
    ( tests / "run-unit-tests.sh" ).write_text(
        "#!/usr/bin/env bash\n"
        "# usage: run-unit-tests.sh src/tests/never_run/\n"
        "exec pytest src/tests/unit/ src/conf/lupin-app.ini --ignore=src/tests/deleted_last_week/\n"
    )
    ( tests / "run-all-tests.sh" ).write_text(
        "#!/usr/bin/env bash\n"
        "bash src/tests/run-unit-tests.sh\n"
        "bash src/tests/run-all-tests.sh\n"
    )

    conf = root / "src/conf"
    conf.mkdir( parents=True )
    ( conf / "lupin-app.ini" ).write_text( "[x]\n" )


def test_read_suite_scripts_extracts_only_shell_values( tmp_path ):
    _build_synthetic_tree( tmp_path )

    assert read_suite_scripts( tmp_path ) == {
        "src/tests/run-unit-tests.sh",
        "src/tests/run-all-tests.sh",
        "src/tests/run-missing.sh",
        "src/tests/run-e2e-tests.sh",
    }


def test_every_shell_entry_of_the_real_literal_is_extracted():
    """
    THE ARM THAT CANNOT GO BLIND ON A FIXTURE. The synthetic tree above is written by this
    file, so it only ever contains keys somebody here thought to write — which is how a
    `[a-z_]+` key class survived: every synthetic key was lowercase, and the assertions
    were correct and unfalsifiable.

    This counts the REAL literal instead. Measured 2026-09-01 before the fix: 13 `.sh`
    entries present, 11 returned, `e2e` and `v2_eval` dropped for carrying a digit, with
    nothing in the output saying any were missing.

    ⚠️ The e2e loss was MASKED and that is why it lasted: `find_gate_targets` follows `.sh`
    references and `run-all-tests.sh` names the e2e runner, so `src/tests/e2e_ui` reached
    the target set by a second route. The masking holds only while some other seeded runner
    happens to name the dropped one, which is not a property anybody chose.
    """
    root    = Path( os.environ[ "LUPIN_ROOT" ] )
    source  = ( root / SUITE_SCRIPTS_SOURCE ).read_text( encoding="utf-8" )
    present = re.findall( r'^\s*"[^"]+"\s*:\s*"(src/[^"]+\.sh)"', source, re.M )

    assert present, "positive control: the literal must hold some .sh entries at all"
    assert set( present ) == read_suite_scripts( root ), (
        "every .sh value in the literal must be extracted; missing "
        f"{sorted( set( present ) - read_suite_scripts( root ) )}" )


def test_read_suite_scripts_raises_when_source_absent( tmp_path ):
    with pytest.raises( FileNotFoundError ):
        read_suite_scripts( tmp_path )


def test_find_gate_targets_follows_runners_and_skips_comments( tmp_path ):
    """
    Covers, in one pass: a runner naming a directory, a runner naming a
    non-test file, a runner naming a path that does not exist (the comment's
    `src/tests/never_run/`), a missing runner, and a self-referential runner.
    """
    _build_synthetic_tree( tmp_path )

    targets = find_gate_targets( tmp_path )

    assert "src/tests/unit"       in targets
    assert "src/tests/never_run"  not in targets   # named only in a comment
    assert "src/conf/lupin-app.ini" not in targets  # exists, but neither dir nor .py


def test_find_gate_targets_ignores_a_glob_root( tmp_path ):
    """
    A glob's leading directory must NEVER become a gate target.

    Caught for real while wiring the TypeScript runner (row 36e479ed): the line
    `c8 tsx --test "src/tests/**/*.test.ts"` yields the token `src/tests`,
    which is a genuine directory. Accepting it would have marked every Python
    test under `src/tests/` reachable and turned this whole census green while
    detecting nothing — the gate disabling itself the moment a new suite was
    added.
    """
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/orphan" ).mkdir()
    ( tmp_path / "src/tests/orphan/test_dark.py" ).write_text( "def test_x(): pass\n" )
    runner = tmp_path / "src/tests/run-unit-tests.sh"
    runner.write_text( runner.read_text() + 'c8 tsx --test "src/tests/**/*.test.ts"\n' )

    assert "src/tests" not in find_gate_targets( tmp_path )
    assert find_unreferenced_test_files( tmp_path, {} ) == [ "src/tests/orphan/test_dark.py" ]


def test_find_gate_targets_keeps_a_directly_named_test_file( tmp_path ):
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/extra" ).mkdir()
    ( tmp_path / "src/tests/extra/test_named.py" ).write_text( "def test_a(): pass\n" )
    runner = tmp_path / "src/tests/run-unit-tests.sh"
    runner.write_text( runner.read_text() + "pytest src/tests/extra/test_named.py\n" )

    assert "src/tests/extra/test_named.py" in find_gate_targets( tmp_path )


def test_find_test_file_population_excludes_worktrees_and_vendored_trees( tmp_path ):
    _build_synthetic_tree( tmp_path )
    for excluded in EXCLUDED_PATH_PARTS:
        junk = tmp_path / "src" / excluded / "nested"
        junk.mkdir( parents=True )
        ( junk / "test_stale_copy.py" ).write_text( "def test_x(): pass\n" )

    assert find_test_file_population( tmp_path ) == { "src/tests/unit/test_gated.py" }


def test_find_unreferenced_test_files_honours_the_allowlist( tmp_path ):
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/orphan" ).mkdir()
    ( tmp_path / "src/tests/orphan/test_dark.py" ).write_text( "def test_x(): pass\n" )

    assert find_unreferenced_test_files( tmp_path, {} ) == [ "src/tests/orphan/test_dark.py" ]
    assert find_unreferenced_test_files( tmp_path, { "src/tests/orphan/test_dark.py": "declared" } ) == []


def test_find_zero_collect_test_files_covers_every_branch( tmp_path ):
    """Allowlisted, unreachable, collectible, and barren files each take a distinct path."""
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/unit/test_barren.py" ).write_text( "def helper(): pass\n" )
    ( tmp_path / "src/tests/unit/test_excused.py" ).write_text( "x = 1\n" )
    ( tmp_path / "src/tests/orphan" ).mkdir()
    ( tmp_path / "src/tests/orphan/test_dark.py" ).write_text( "x = 1\n" )

    barren = find_zero_collect_test_files( tmp_path, { "src/tests/unit/test_excused.py": "declared" } )

    assert barren == [ "src/tests/unit/test_barren.py" ]


def test_find_stale_allowlist_entries_flags_deleted_and_rewired_files( tmp_path ):
    """
    Both exemption classes keep their entry; only an entry excusing nothing goes stale.

    The zero-collect entry is the one that caught a real defect in this control:
    it is gate-REACHABLE by design, so a staleness rule keyed on reachability
    alone would have evicted every zero-collect exemption on the first run.
    """
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/orphan" ).mkdir()
    ( tmp_path / "src/tests/orphan/test_dark.py" ).write_text( "def test_x(): pass\n" )
    ( tmp_path / "src/tests/unit/test_barren.py" ).write_text( "x = 1\n" )

    stale = find_stale_allowlist_entries(
        tmp_path,
        {
            "src/tests/unit/test_gated.py"   : "gated AND has tests — excuses nothing",
            "src/tests/gone/test_deleted.py" : "file no longer exists",
            "src/tests/orphan/test_dark.py"  : "genuinely still ungated",
            "src/tests/unit/test_barren.py"  : "gated but defines no test — still zero-collect",
        },
    )

    assert stale == [ "src/tests/gone/test_deleted.py", "src/tests/unit/test_gated.py" ]


@pytest.mark.parametrize(
    "relative,targets,expected",
    [
        ( "src/tests/unit/test_a.py", { "src/tests/unit/test_a.py" }, True  ),
        ( "src/tests/unit/test_a.py", { "src/tests/unit" },           True  ),
        ( "src/tests/unit/test_a.py", { "src/tests/other" },          False ),
    ],
)
def test_is_reachable_direct_ancestor_and_miss( relative, targets, expected ):
    assert _is_reachable( relative, targets ) is expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ( "def test_a(): pass\n",             True  ),
        ( "async def test_a(): pass\n",       True  ),
        ( "class TestThing:\n    pass\n",     True  ),
        ( "class Helper:\n    pass\n",        False ),
        ( "def helper(): pass\n",             False ),
        ( "def (\n",                          True  ),   # unparseable fails collection loudly
    ],
)
def test_defines_a_test_recognises_pytest_discovery_shapes( tmp_path, source, expected ):
    path = tmp_path / "test_probe.py"
    path.write_text( source )

    assert _defines_a_test( path ) is expected


@pytest.mark.parametrize(
    "source,expected",
    [
        # The three real shapes that were misreported as barren on 2026-08-01.
        ( "class FooTests( unittest.TestCase ):\n    def test_a(self): pass\n",           True  ),
        ( "class FooTests( TestCase ):\n    def test_a(self): pass\n",                    True  ),
        ( "class FooTest( unittest.IsolatedAsyncioTestCase ):\n"
          "    async def test_a(self): pass\n",                                           True  ),
        # THE CONTROL — inheritance alone must NOT excuse a file. pytest collects
        # nothing from a TestCase with no test method, so the census must still
        # name it. If this ever flips to True the widening has gone too far.
        ( "class FooTests( unittest.TestCase ):\n    def helper(self): pass\n",           False ),
        # A helper method whose name merely CONTAINS "test" is not a test method.
        ( "class FooTests( unittest.TestCase ):\n    def assert_test_ran(self): pass\n",  False ),
        # Inheritance through a project-local base is invisible to the AST — the
        # documented limit. Such a file reads as barren and needs a ledger entry.
        ( "class FooTests( OurOwnBase ):\n    def test_a(self): pass\n",                  False ),
    ],
)
def test_defines_a_test_recognises_unittest_testcase_subclasses( tmp_path, source, expected ):
    """
    pytest collects `unittest.TestCase` subclasses by INHERITANCE, not by name.

    The detector knew only the `Test*` name prefix, so a file whose classes are
    named `FooTests(unittest.TestCase)` — the dominant spelling in this repo —
    was reported as defining no test while holding real, passing, collected
    tests. Row 663433a7. The rule is inheritance AND at least one `test_*`
    method; the fourth case above is the arm that keeps the second half honest.
    """
    path = tmp_path / "test_probe.py"
    path.write_text( source )

    assert _defines_a_test( path ) is expected


def test_zero_collect_detector_does_not_flag_a_real_testcase_file( tmp_path ):
    """
    End-to-end arm: a gated TestCase-style file must not surface as barren.

    The parametrized cases above pin the predicate; this pins the CENSUS that
    calls it, so a future refactor cannot reintroduce the false positive one
    layer up while every unit-level assertion still passes.
    """
    _build_synthetic_tree( tmp_path )
    ( tmp_path / "src/tests/unit/test_unittest_style.py" ).write_text(
        "import unittest\n"
        "class ReloadEnabledGateTests( unittest.TestCase ):\n"
        "    def test_gate(self): self.assertTrue( True )\n"
    )
    ( tmp_path / "src/tests/unit/test_hollow_case.py" ).write_text(
        "import unittest\n"
        "class HollowTests( unittest.TestCase ):\n"
        "    def helper(self): pass\n"
    )

    assert find_zero_collect_test_files( tmp_path, {} ) == [ "src/tests/unit/test_hollow_case.py" ]
