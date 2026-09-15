"""
Every E2E test file runs in exactly one half of the suite (row 2818dad7).

The e2e UI suite runs in the merge gate as two halves, "e2e_a" and "e2e_b". Each half runs
exactly the files listed in its manifest, src/tests/e2e_ui/partition/half-<a|b>.txt. That
has one failure mode that no run can show: a new test file listed in no manifest never runs,
and both halves still go green. A file listed in both runs twice and inflates the numbers.

So this test does not trust the manifests. It ENUMERATES the directory with the same
file-name predicate pytest collects by (`python_files` in pytest.ini, read rather than
restated) and compares.

`partition_problems` does the checking. The real-tree test asserts it returns nothing, and
the controls below run it on temporary trees to show it DOES report an unassigned file, a
file in both halves, and a stale line. Without them, an empty result would read the same
whether the tree is correct or the check is blind.
"""

import configparser
import fnmatch
import re
import shutil
from pathlib import Path

import cosa.utils.util as cu

E2E_DIR        = "src/tests/e2e_ui"
PARTITION_DIR  = "src/tests/e2e_ui/partition"
HALVES         = ( "a", "b" )
RUNNER         = "src/scripts/run-e2e-ui-tests.sh"


def _collect_patterns( root ):
    """
    The file-name patterns pytest collects by, read from pytest.ini.

    Requires:
        - root / "pytest.ini" exists and carries a [pytest] python_files key

    Ensures:
        - returns the whitespace-separated patterns, e.g. [ "test_*.py" ]
    """
    parser = configparser.ConfigParser()
    parser.read( root / "pytest.ini", encoding="utf-8" )
    return parser[ "pytest" ][ "python_files" ].split()


def _read_manifest( path ):
    """
    The repo-relative paths a manifest lists, in file order.

    Ensures:
        - blank lines and lines whose first non-space character is `#` are skipped
        - each remaining line is stripped
    """
    lines = path.read_text( encoding="utf-8" ).splitlines()
    return [ line.strip() for line in lines if line.strip() and not line.strip().startswith( "#" ) ]


def _runner_parity_files( root ):
    """
    The files named in run-e2e-ui-tests.sh's PARITY_ORACLE_E2E=( ... ) array.

    Requires:
        - the runner declares exactly one PARITY_ORACLE_E2E=( ... ) array

    Ensures:
        - returns the quoted paths inside it, in order
    """
    source = ( root / RUNNER ).read_text( encoding="utf-8" )
    arrays = re.findall( r"^PARITY_ORACLE_E2E=\(([^)]*)\)", source, re.MULTILINE )
    assert len( arrays ) == 1, f"expected one PARITY_ORACLE_E2E array in {RUNNER}, found {len( arrays )}"
    return re.findall( r"\"([^\"]+)\"", arrays[ 0 ] )


def collectable_e2e_files( root ):
    """
    Every file under src/tests/e2e_ui/ that pytest would collect, at any depth.

    Ensures:
        - returns sorted repo-relative POSIX paths
        - matches on the file NAME with pytest.ini's python_files patterns
    """
    patterns = _collect_patterns( root )
    found    = []
    for path in ( root / E2E_DIR ).rglob( "*" ):
        if not path.is_file(): continue
        if any( fnmatch.fnmatch( path.name, pattern ) for pattern in patterns ):
            found.append( path.relative_to( root ).as_posix() )
    return sorted( found )


def partition_problems( root ):
    """
    Everything wrong with the e2e partition under root, one message per problem.

    Requires:
        - root holds pytest.ini, the runner, and both partition manifests

    Ensures:
        - returns [] exactly when:
            · every collectable file under src/tests/e2e_ui/ is in exactly one half
            · no manifest lists a path twice
            · every manifest line names a file that exists
            · every manifest line under src/tests/e2e_ui/ is a collectable test file
            · the manifests' lines OUTSIDE src/tests/e2e_ui/ are the same set as the
              runner's PARITY_ORACLE_E2E array, which the whole-suite run uses
        - each message names the offending path
    """
    problems  = []
    listed    = { half: _read_manifest( root / PARTITION_DIR / f"half-{half}.txt" ) for half in HALVES }
    homes     = {}

    for half, paths in listed.items():
        seen = set()
        for rel in paths:
            if rel in seen:
                problems.append( f"half-{half}.txt lists {rel} twice" )
            seen.add( rel )
            homes.setdefault( rel, set() ).add( half )
            if not ( root / rel ).is_file():
                problems.append( f"half-{half}.txt lists {rel}, which is not a file" )

    collectable = collectable_e2e_files( root )
    for rel in collectable:
        if rel not in homes:
            problems.append( f"{rel} is in NEITHER half, so no gate runs it" )
        elif len( homes[ rel ] ) > 1:
            problems.append( f"{rel} is in BOTH halves, so it runs twice" )

    collectable_set = set( collectable )
    for rel, halves in homes.items():
        if rel.startswith( E2E_DIR + "/" ) and rel not in collectable_set and ( root / rel ).is_file():
            problems.append( f"half-{sorted( halves )[ 0 ]}.txt lists {rel}, which pytest does not collect" )

    outside = { rel for rel in homes if not rel.startswith( E2E_DIR + "/" ) }
    parity  = set( _runner_parity_files( root ) )
    for rel in sorted( parity - outside ):
        problems.append( f"{rel} runs in the whole suite (PARITY_ORACLE_E2E) but is in NEITHER half" )
    for rel in sorted( outside - parity ):
        problems.append( f"{rel} is in a half but not in the runner's PARITY_ORACLE_E2E, so the whole suite skips it" )
    for rel in sorted( outside & parity ):
        if len( homes[ rel ] ) > 1:
            problems.append( f"{rel} is in BOTH halves, so it runs twice" )

    return problems


# ---------------------------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------------------------

def test_every_e2e_test_file_is_in_exactly_one_half():
    root = Path( cu.get_project_root() )

    # A check over an empty population passes every assertion in it. The suite held 101
    # collectable files on 2026-09-14; the floor only proves the walk found the directory.
    collectable = collectable_e2e_files( root )
    assert len( collectable ) >= 50, (
        f"found only {len( collectable )} collectable files under {E2E_DIR} — the enumeration "
        f"is broken or LUPIN_ROOT points at the wrong tree ({root})"
    )

    problems = partition_problems( root )
    assert problems == [ ], (
        "the e2e partition is out of date:\n  " + "\n  ".join( problems ) +
        f"\nEdit {PARTITION_DIR}/half-a.txt or half-b.txt. Put a new file in the lighter half."
    )


def test_each_half_wrapper_passes_its_own_half():
    """
    The suite "e2e_a" must run half a, and "e2e_b" half b.

    A wrapper that passed the wrong letter would run one half twice and the other not at
    all, and the partition test above would still pass, because it checks the manifests,
    not what the wrappers do with them.
    """
    from cosa.agents.test_suite.job import SUITE_SCRIPTS

    root = Path( cu.get_project_root() )
    for half in HALVES:
        wrapper = SUITE_SCRIPTS[ f"e2e_{half}" ]
        lines   = [ line for line in ( root / wrapper ).read_text( encoding="utf-8" ).splitlines()
                    if not line.lstrip().startswith( "#" ) ]
        execs   = [ line for line in lines if line.lstrip().startswith( "exec " ) ]
        assert len( execs ) == 1, f"{wrapper} should have exactly one exec line, found {len( execs )}"
        assert "run-e2e-ui-tests.sh" in execs[ 0 ], f"{wrapper} does not exec the e2e runner: {execs[ 0 ]!r}"
        halves_named = re.findall( r"--half\s+(\S+)", execs[ 0 ] )
        assert halves_named == [ half ], f"{wrapper} passes --half {halves_named}, expected [{half!r}]"


# ---------------------------------------------------------------------------------------------
# Controls: the check can fail
# ---------------------------------------------------------------------------------------------

def _copy_of_real_tree( tmp_path ):
    """
    A minimal copy of the real partition inputs under tmp_path.

    Ensures:
        - tmp_path holds pytest.ini, the runner, both manifests, and an empty placeholder for
          every file they list and every collectable e2e file, at the same relative paths
    """
    root = Path( cu.get_project_root() )
    for rel in ( "pytest.ini", RUNNER, f"{PARTITION_DIR}/half-a.txt", f"{PARTITION_DIR}/half-b.txt" ):
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copyfile( root / rel, tmp_path / rel )
    listed = set( collectable_e2e_files( root ) )
    for half in HALVES:
        listed |= set( _read_manifest( root / PARTITION_DIR / f"half-{half}.txt" ) )
    for rel in listed:
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        ( tmp_path / rel ).touch()
    return tmp_path


def test_control_the_copied_tree_starts_clean( tmp_path ):
    # Each control below changes ONE thing, so it needs a baseline with no problems.
    assert partition_problems( _copy_of_real_tree( tmp_path ) ) == [ ]


def test_control_a_new_unassigned_test_file_reddens_it( tmp_path ):
    root = _copy_of_real_tree( tmp_path )
    ( root / E2E_DIR / "test_brand_new_page.py" ).touch()

    assert partition_problems( root ) == [
        "src/tests/e2e_ui/test_brand_new_page.py is in NEITHER half, so no gate runs it"
    ]


def test_control_a_new_test_file_in_a_subdirectory_reddens_it( tmp_path ):
    # pytest collects recursively; a check that only looked at the top level would miss this.
    root = _copy_of_real_tree( tmp_path )
    ( root / E2E_DIR / "admin" ).mkdir()
    ( root / E2E_DIR / "admin" / "test_nested.py" ).touch()

    assert partition_problems( root ) == [
        "src/tests/e2e_ui/admin/test_nested.py is in NEITHER half, so no gate runs it"
    ]


def test_control_a_helper_module_is_not_mistaken_for_a_test( tmp_path ):
    # parity_oracle.py and task_panes.py live in the directory and pytest does not collect them.
    root = _copy_of_real_tree( tmp_path )
    ( root / E2E_DIR / "a_new_helper.py" ).touch()

    assert partition_problems( root ) == [ ]


def test_control_a_file_in_both_halves_reddens_it( tmp_path ):
    root   = _copy_of_real_tree( tmp_path )
    moved  = _read_manifest( root / PARTITION_DIR / "half-a.txt" )[ 0 ]
    with open( root / PARTITION_DIR / "half-b.txt", "a", encoding="utf-8" ) as f:
        f.write( moved + "\n" )

    assert partition_problems( root ) == [ f"{moved} is in BOTH halves, so it runs twice" ]


def test_control_a_file_dropped_from_its_half_reddens_it( tmp_path ):
    root     = _copy_of_real_tree( tmp_path )
    manifest = root / PARTITION_DIR / "half-b.txt"
    dropped  = next( rel for rel in _read_manifest( manifest ) if rel.startswith( E2E_DIR + "/" ) )
    kept     = [ line for line in manifest.read_text( encoding="utf-8" ).splitlines() if line.strip() != dropped ]
    manifest.write_text( "\n".join( kept ) + "\n", encoding="utf-8" )

    assert partition_problems( root ) == [ f"{dropped} is in NEITHER half, so no gate runs it" ]


def test_control_a_stale_line_for_a_deleted_file_reddens_it( tmp_path ):
    root    = _copy_of_real_tree( tmp_path )
    deleted = _read_manifest( root / PARTITION_DIR / "half-a.txt" )[ -1 ]
    ( root / deleted ).unlink()

    assert f"half-a.txt lists {deleted}, which is not a file" in partition_problems( root )


def test_control_a_parity_file_missing_from_the_halves_reddens_it( tmp_path ):
    root     = _copy_of_real_tree( tmp_path )
    parity   = _runner_parity_files( root )[ 0 ]
    for half in HALVES:
        manifest = root / PARTITION_DIR / f"half-{half}.txt"
        kept     = [ line for line in manifest.read_text( encoding="utf-8" ).splitlines() if line.strip() != parity ]
        manifest.write_text( "\n".join( kept ) + "\n", encoding="utf-8" )

    assert partition_problems( root ) == [
        f"{parity} runs in the whole suite (PARITY_ORACLE_E2E) but is in NEITHER half"
    ]
