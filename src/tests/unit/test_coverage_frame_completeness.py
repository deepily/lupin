"""
Guard the coverage FRAME against silently measuring less than it claims.

Row e2099400, 2026-08-29. pyproject's own comment said listing directory paths in
`source` makes coverage "enter every .py at 0%". Measured: it does not. The walk
covers a source directory's top level and refuses to descend into any subdirectory
that is not an import package, so 12 files / 1,091 statements under src/scripts sat
outside a path that reads as inclusive — and a frame that drops files reports a
HIGHER percentage, because the code nobody measures is the code nobody tested.

The load-bearing test here is test_a_real_coverage_run_skips_a_non_package_subdir:
it runs coverage for real and asserts on the report it produces, so the rule this
module mirrors is demonstrated rather than assumed. The rest guard the mirror.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

import cosa.utils.coverage_frame as cf


def _live_omit():
    """
    Read the omit globs from the real pyproject rather than restating them. A hard-coded
    copy in the gate had already drifted from the config the first time it ran, which is
    the same defect this module exists to catch, one level down.
    """
    return cf.omit_patterns( open( os.path.join( _project_root(), "pyproject.toml" ), encoding="utf-8" ).read() )


def _project_root():
    """Resolve the repo root from this file, without importing the project's config."""
    return os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )


# ── coverage_can_see: the filename filter ────────────────────────────────────────

@pytest.mark.parametrize( "name,visible", [
    ( "plain_name.py",                 True  ),
    ( "has-dashes.py",                 True  ),   # dashes are FINE — measured, not assumed
    ( "module.pyw",                    True  ),
    ( "dotted.name.2026.05.12.py",     False ),   # a dot in the stem is the killer
    # kept as a fixture after the real file was renamed 2026-08-30 (row 9078a035):
    # this feeds a STRING to the filter and never touches disk, so it stays a valid
    # regression case for the rule regardless of what is on disk.
    ( "probe-cc-bounded-billing-2026.05.12.py", False ),
    ( "2026.05.21-prototype.py",       False ),
    ( "junk~.py",                      False ),
    ( "has#hash.py",                   False ),
    ( "not_python.txt",                False ),
] )
def test_coverage_can_see_matches_coverages_own_filename_rule( name, visible ):
    assert cf.coverage_can_see( os.path.join( "some", "dir", name ) ) is visible


# ── is_package_dir ───────────────────────────────────────────────────────────────

def test_is_package_dir_is_decided_by_init_file( tmp_path ):
    pkg = tmp_path / "pkg"; pkg.mkdir(); ( pkg / "__init__.py" ).write_text( "" )
    plain = tmp_path / "plain"; plain.mkdir()
    assert cf.is_package_dir( str( pkg ) ) is True
    assert cf.is_package_dir( str( plain ) ) is False


# ── source_dirs ──────────────────────────────────────────────────────────────────

def test_source_dirs_reads_the_live_pyproject():
    text = open( os.path.join( _project_root(), "pyproject.toml" ), encoding="utf-8" ).read()
    dirs = cf.source_dirs( text )
    assert "src/cosa" in dirs
    assert "src/scripts" in dirs

def test_source_dirs_ignores_quoted_text_inside_comments():
    """
    The regression test for this module's OWN first defect: a regex scanner returned
    two phrases out of the source block's comments as if they were directories.
    """
    text = textwrap.dedent( '''
        [tool.coverage.run]
        source = [
            "src/real_one",
            # a comment mentioning "src/not_a_directory" and "enter every .py at 0%"
            "src/real_two",
        ]
    ''' )
    assert cf.source_dirs( text ) == [ "src/real_one", "src/real_two" ]

@pytest.mark.parametrize( "text", [ "[tool.other]\nx = 1\n", "[tool.coverage.run]\nbranch = true\n" ] )
def test_source_dirs_raises_when_the_frame_is_absent( text ):
    with pytest.raises( ValueError ):
        cf.source_dirs( text )


# ── unreachable_subdirs: the static guard ────────────────────────────────────────

def test_the_live_frame_has_no_unreachable_subdirectories():
    """
    THE STANDING GUARD. Fails the moment somebody adds a non-package subdirectory
    under a source entry without listing it, which is exactly how 12 files went
    missing. Asserts against the real pyproject and the real tree.
    """
    root = _project_root()
    text = open( os.path.join( root, "pyproject.toml" ), encoding="utf-8" ).read()
    dirs = cf.source_dirs( text )
    assert cf.unreachable_subdirs( root, dirs, cf.omit_patterns( text ) ) == []

def test_an_unlisted_non_package_subdir_is_flagged( tmp_path ):
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "a.py" ).write_text( "x = 1\n" )
    ( top / "sub" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top" ] ) == [ os.path.join( "top", "sub" ) ]

def test_listing_the_subdir_makes_it_reachable( tmp_path ):
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "sub" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top", os.path.join( "top", "sub" ) ] ) == []

def test_a_package_subdir_is_reachable_without_listing( tmp_path ):
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "sub" / "__init__.py" ).write_text( "" )
    ( top / "sub" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top" ] ) == []

def test_a_subdir_holding_only_unseeable_files_is_not_flagged( tmp_path ):
    """coverage cannot see these names, so listing the directory would not help."""
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "sub" / "2026.05.21-prototype.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top" ] ) == []

def test_omitted_subdirs_are_not_flagged( tmp_path ):
    top = tmp_path / "top"; ( top / "tests" ).mkdir( parents=True )
    ( top / "tests" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top" ], ( "*/tests/*", ) ) == []

def test_pycache_is_never_flagged( tmp_path ):
    top = tmp_path / "top"; ( top / "__pycache__" ).mkdir( parents=True )
    ( top / "__pycache__" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unreachable_subdirs( str( tmp_path ), [ "top" ] ) == []

def test_a_source_entry_that_is_not_a_directory_is_skipped( tmp_path ):
    assert cf.unreachable_subdirs( str( tmp_path ), [ "does_not_exist" ] ) == []


# ── unseen_python_files: the dynamic census ──────────────────────────────────────

def test_unseen_split_separates_the_fixable_from_the_unrenamable( tmp_path ):
    top = tmp_path / "top"; top.mkdir()
    ( top / "reported.py"     ).write_text( "x = 1\n" )
    ( top / "missing.py"      ).write_text( "x = 1\n" )
    ( top / "2026.01.01-x.py" ).write_text( "x = 1\n" )
    unexpected, unseeable = cf.unseen_python_files(
        str( tmp_path ), [ "top" ], [ os.path.join( "top", "reported.py" ) ] )
    assert unexpected == [ os.path.join( "top", "missing.py" ) ]
    assert unseeable  == [ os.path.join( "top", "2026.01.01-x.py" ) ]

def test_unseen_honours_omits_and_skips_missing_entries( tmp_path ):
    top = tmp_path / "top"; ( top / "tests" ).mkdir( parents=True )
    ( top / "tests" / "t.py" ).write_text( "x = 1\n" )
    ( top / "__pycache__" ).mkdir()
    ( top / "__pycache__" / "c.py" ).write_text( "x = 1\n" )
    assert cf.unseen_python_files( str( tmp_path ), [ "top", "nope" ], [], ( "*/tests/*", ) ) == ( [], [] )

def test_unseen_does_not_descend_into_a_non_package_subdir( tmp_path ):
    """Mirrors coverage: a file the walk never reaches is not reported as missing."""
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "sub" / "b.py" ).write_text( "x = 1\n" )
    assert cf.unseen_python_files( str( tmp_path ), [ "top" ], [] ) == ( [], [] )

def test_unseen_descends_into_a_package_subdir( tmp_path ):
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "sub" / "__init__.py" ).write_text( "" )
    ( top / "sub" / "b.py" ).write_text( "x = 1\n" )
    unexpected, _ = cf.unseen_python_files( str( tmp_path ), [ "top" ], [] )
    assert os.path.join( "top", "sub", "b.py" ) in unexpected

def test_non_python_files_are_ignored( tmp_path ):
    top = tmp_path / "top"; top.mkdir()
    ( top / "notes.md" ).write_text( "hi\n" )
    assert cf.unseen_python_files( str( tmp_path ), [ "top" ], [] ) == ( [], [] )


# ── report_paths ─────────────────────────────────────────────────────────────────

def test_report_paths_reads_a_coverage_json( tmp_path ):
    p = tmp_path / "cov.json"
    p.write_text( json.dumps( { "files": { "b.py": {}, "a.py": {} } } ) )
    assert cf.report_paths( str( p ) ) == [ "a.py", "b.py" ]


# ── the load-bearing test: assert on what a REAL coverage run produces ───────────

def test_a_real_coverage_run_skips_a_non_package_subdir( tmp_path ):
    """
    Demonstrates the rule this module mirrors, by running coverage for real and
    reading its report. Without this, every other test here only proves the mirror
    is self-consistent — and a mirror of a rule nobody checked is the defect this
    row is about.

    Asserts BOTH directions, because only the pair is evidence: the top-level file
    enters the report at 0% (so the walk did happen and the run was valid) while the
    subdirectory file does not (so the descent really is refused).
    """
    top = tmp_path / "top"; ( top / "sub" ).mkdir( parents=True )
    ( top / "top_level.py"  ).write_text( "x = 1\n" )
    ( top / "sub" / "buried.py" ).write_text( "x = 1\n" )
    ( top / "driver.py"     ).write_text( "y = 2\n" )
    ( tmp_path / "cfg.toml" ).write_text( '[tool.coverage.run]\nsource = [ "top" ]\n' )

    env = dict( os.environ )
    # Never inherit the parent's data file: a child writing into the tier's own
    # COVERAGE_FILE is how ~610 statements of CPython's json landed in this repo's
    # denominator (row e2099400 §3a).
    env[ "COVERAGE_FILE" ] = str( tmp_path / ".coverage" )

    subprocess.run( [ sys.executable, "-m", "coverage", "run", "--rcfile=cfg.toml",
                      os.path.join( "top", "driver.py" ) ],
                    cwd=str( tmp_path ), env=env, check=True,
                    capture_output=True, timeout=120 )
    out = subprocess.run( [ sys.executable, "-m", "coverage", "json", "--rcfile=cfg.toml",
                            "-o", "cov.json" ],
                          cwd=str( tmp_path ), env=env, check=True,
                          capture_output=True, timeout=120 )
    assert out.returncode == 0

    reported = set( cf.report_paths( str( tmp_path / "cov.json" ) ) )
    assert any( r.endswith( "top_level.py" ) for r in reported ), (
        f"the walk did not run at all, so this proves nothing; report held {reported}" )
    assert not any( r.endswith( "buried.py" ) for r in reported ), (
        f"coverage DID descend into a non-package subdir — the premise of "
        f"coverage_frame.py is wrong and the frame comment should be rewritten; "
        f"report held {reported}" )


def test_the_declared_unseeable_files_are_really_unseeable_and_really_present():
    """
    KNOWN_UNSEEABLE is a declaration, and a declaration nobody checks becomes a lie.
    Both halves are asserted: each named file must still EXIST (else delete the entry)
    and must still be invisible to coverage (else stop declaring it and measure it).
    """
    root = _project_root()
    for rel in sorted( cf.KNOWN_UNSEEABLE ):
        assert os.path.isfile( os.path.join( root, rel ) ), (
            f"{rel} is declared unseeable but no longer exists — remove it from KNOWN_UNSEEABLE" )
        assert not cf.coverage_can_see( rel ), (
            f"{rel} is declared unseeable but coverage CAN see it — it belongs in the frame" )


# ── omit_patterns / is_omitted: read the frame's omissions, never restate them ────

def test_omit_patterns_reads_the_live_pyproject():
    pats = _live_omit()
    assert any( "cosa/tests" in p for p in pats )
    assert any( "__main__" in p for p in pats ), (
        "pyproject omits */cosa/agents/*/__main__.py; a checker that misses it reports "
        "deliberately-omitted files as unaccounted, which is what happened on first run" )

def test_omit_patterns_is_empty_when_none_configured():
    assert cf.omit_patterns( "[tool.coverage.run]\nsource = [ \"src\" ]\n" ) == []

@pytest.mark.parametrize( "path,expected", [
    ( "src/cosa/tests/test_x.py",                     True  ),
    ( "src/cosa/agents/podcast_generator/__main__.py", True  ),
    ( "src/lupin_cli/notifications/test_notifications.py", True ),
    ( "src/cosa/utils/coverage_frame.py",             False ),
    ( "src/scripts/secret_scan.py",                   False ),
] )
def test_is_omitted_matches_the_live_globs( path, expected ):
    assert cf.is_omitted( path, _live_omit() ) is expected

def test_an_omitted_file_at_the_top_level_is_skipped_by_the_census( tmp_path ):
    """
    Closes the arc where a walked file IS omitted. The sibling omit test puts its file in
    a SUBDIRECTORY, which the walk never descends into — so it exercised the descent rule
    rather than the omit rule, and the omit branch stayed uncovered at 99%.
    """
    top = tmp_path / "top"; top.mkdir()
    ( top / "keep.py"      ).write_text( "x = 1\n" )
    ( top / "test_skip.py" ).write_text( "x = 1\n" )
    unexpected, unseeable = cf.unseen_python_files(
        str( tmp_path ), [ "top" ], [], ( "*/test_skip.py", ) )
    assert unexpected == [ os.path.join( "top", "keep.py" ) ]
    assert unseeable  == []
