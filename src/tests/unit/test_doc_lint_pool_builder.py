"""
The docstring pool builder: its rows, its commit-only reading, its manifest and its refusals.

Every source file here is a small synthetic one written into a throwaway git repo, so no real tree and
no real pool is read. The builder reads files from git at one commit, so the tests also change the
working tree after the commit and check that the pool does not move.
"""

import hashlib
import json
import subprocess

import pytest

from cosa.repo.doc_lint import labelled_set_seeder as seeder
from cosa.repo.doc_lint import pool_builder as pb

MODULE_SRC = '''"""Module text that says what the module is for."""


class Parked:
    """Hold one parked row.

    The flag is computed when the row is parked.
    """

    def count( self ):
        """Return the count of parked rows."""
        def inner():
            """Inner text for a nested function."""
        return 1

    def nodoc( self ):
        return 2

    async def later( self ):
        """Return the count of rows parked later."""


def helper():
    """Help with the thing."""


def blank():
    """   """
'''

OTHER_SRC = '"""Other module."""\n\n\ndef run():\n    """Run once."""\n'


def git( root, *args, data=None ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], input=data, capture_output=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.decode( "utf-8" ).strip()


def commit( root, files ):
    """Write files into the repo, commit them all, and return the commit sha."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir( parents=True, exist_ok=True )
        if isinstance( content, bytes ): path.write_bytes( content )
        else:                           path.write_text( content, encoding="utf-8" )
    git( root, "add", "-A" )
    git( root, "commit", "-q", "-m", "c" )
    return git( root, "rev-parse", "HEAD" )


@pytest.fixture
def repo( tmp_path ):
    git( tmp_path, "init", "-q" )
    return tmp_path


@pytest.fixture
def populated( repo ):
    sha = commit( repo, { "src/pkg/a.py": MODULE_SRC, "src/pkg/b.py": OTHER_SRC, "src/other/c.py": OTHER_SRC, "src/pkg/notes.md": "text\n",
                          "src/pkg/.venv/d.py": OTHER_SRC, "src/pkg/skip/e.py": OTHER_SRC, "src/pkgx/f.py": OTHER_SRC } )
    return repo, sha


def ids( rows ): return [ r[ "id" ] for r in rows ]


# ---- what a row is --------------------------------------------------------------------------

def test_the_module_class_methods_and_nested_functions_each_become_a_row_in_source_order( populated ):
    repo, sha = populated
    rows, _   = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [ "src/pkg/skip" ] )
    mine      = [ r for r in rows if r[ "file" ] == "src/pkg/a.py" ]
    assert [ r[ "symbol" ] for r in mine ] == [ "<module>", "Parked", "Parked.count", "Parked.count.inner", "Parked.later", "helper" ]
    assert [ r[ "id" ] for r in mine ][ :2 ] == [ "src/pkg/a.py::<module>", "src/pkg/a.py::Parked" ]


def test_a_row_has_exactly_the_four_fields_the_seeder_reads_and_its_text_is_cleandoc( populated ):
    repo, sha = populated
    rows, _   = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
    assert rows and all( set( r ) == { "id", "file", "symbol", "old" } for r in rows )
    parked = next( r for r in rows if r[ "symbol" ] == "Parked" )
    assert parked[ "old" ] == "Hold one parked row.\n\nThe flag is computed when the row is parked."
    assert seeder.stratum_of( parked[ "old" ] ) == "S"


def test_a_blank_docstring_and_a_missing_one_make_no_row( populated ):
    repo, sha = populated
    rows, _   = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
    assert "blank" not in [ r[ "symbol" ] for r in rows ] and "Parked.nodoc" not in [ r[ "symbol" ] for r in rows ]


def test_a_second_definition_of_one_name_gets_a_numbered_id():
    rows, reason = pb.pool_rows( "m.py", b'def f():\n    """One."""\n\n\ndef f():\n    """Two."""\n' )
    assert reason is None and ids( rows ) == [ "m.py::f", "m.py::f#2" ]


def test_a_file_that_is_not_utf8_or_does_not_parse_is_skipped_with_its_reason():
    assert pb.pool_rows( "m.py", b"\xff\xfe" ) == ( [], "encoding" )
    assert pb.pool_rows( "m.py", b"def (:\n" ) == ( [], "syntax" )
    assert pb.pool_rows( "m.py", b"x = 1\x00\n" ) == ( [], "syntax" )


NESTED_SRC = '''import os

if os.name:
    def under_if():
        """Defined under an if."""
else:
    def under_else():
        """Defined under an else."""

try:
    class UnderTry:
        """Defined under a try."""
except ImportError:
    pass

with open( __file__ ) as f:
    def under_with():
        """Defined under a with."""

for _ in range( 1 ):
    def under_for():
        """Defined under a loop."""
'''


def test_a_definition_under_an_if_a_try_a_with_or_a_loop_is_found_and_named_like_its_neighbours():
    rows, reason = pb.pool_rows( "m.py", NESTED_SRC.encode( "utf-8" ) )
    assert reason is None
    assert [ r[ "symbol" ] for r in rows ] == [ "under_if", "under_else", "UnderTry", "under_with", "under_for" ]


# ---- one row for each distinct docstring --------------------------------------------------------

SAME_DOC = '"""Return the idle workers, or zero when parked."""\n'


def test_the_same_docstring_in_two_directories_gives_one_row_and_the_other_id_is_in_the_manifest( repo ):
    sha = commit( repo, { "src/one/a.py": SAME_DOC, "src/two/b.py": SAME_DOC, "src/two/c.py": '"""A different docstring."""\n' } )
    rows, facts = pb.build_pool( str( repo ), sha, [ "src" ], [] )
    assert ids( rows ) == [ "src/one/a.py::<module>", "src/two/c.py::<module>" ]
    assert facts[ "duplicates" ] == [ { "kept": "src/one/a.py::<module>", "dropped": [ "src/two/b.py::<module>" ] } ]
    assert facts[ "rows_before_dedupe" ] == 3 and facts[ "rows" ] == 2 and facts[ "duplicate_rows_dropped" ] == 1


def test_docstrings_that_differ_only_in_whitespace_are_the_same_text( repo ):
    sha = commit( repo, { "src/a.py": '"""One two\n    three."""\n', "src/b.py": '"""One   two three."""\n' } )
    rows, facts = pb.build_pool( str( repo ), sha, [ "src" ], [] )
    assert ids( rows ) == [ "src/a.py::<module>" ] and facts[ "duplicates" ][ 0 ][ "dropped" ] == [ "src/b.py::<module>" ]


def test_the_kept_row_is_the_smallest_id_and_a_group_of_three_lists_both_others():
    rows = [ { "id": "z::f", "old": "Same text." }, { "id": "a::f", "old": "Same  text." }, { "id": "m::f", "old": "Same text." }, { "id": "q::f", "old": "Other." } ]
    kept, dups = pb.drop_duplicates( rows )
    assert [ r[ "id" ] for r in kept ] == [ "a::f", "q::f" ]
    assert dups == [ { "kept": "a::f", "dropped": [ "m::f", "z::f" ] } ]


def test_a_pool_of_distinct_texts_has_no_duplicates_listed_and_records_the_text_choice( populated ):
    repo, sha = populated
    _, facts  = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [ "src/pkg/skip" ] )
    assert facts[ "duplicates" ] == [] and facts[ "duplicate_rows_dropped" ] == 0 and facts[ "rows_before_dedupe" ] == facts[ "rows" ] > 0
    assert facts[ "docstring_text" ] == "inspect.cleandoc"


# ---- which files are read ------------------------------------------------------------------

def test_the_include_prefix_exclude_prefix_skip_names_and_extension_pick_the_files( populated ):
    repo, sha = populated
    got = [ path for path, _ in pb.list_sources( str( repo ), sha, [ "src/pkg" ], [ "src/pkg/skip" ] ) ]
    assert got == [ "src/pkg/a.py", "src/pkg/b.py" ]


def test_a_prefix_matches_a_directory_not_the_start_of_a_name( populated ):
    repo, sha = populated
    both = [ path for path, _ in pb.list_sources( str( repo ), sha, [ "src/pkg/", "src/pkgx" ], [] ) ]
    assert "src/pkgx/f.py" in both and "src/other/c.py" not in both
    assert "src/pkgx/f.py" not in [ path for path, _ in pb.list_sources( str( repo ), sha, [ "src/pkg" ], [] ) ]


def test_a_submodule_entry_is_not_a_file_to_read( populated ):
    repo, sha = populated
    git( repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},src/pkg/sub.py" )
    git( repo, "commit", "-q", "-m", "gitlink" )
    new = git( repo, "rev-parse", "HEAD" )
    assert "src/pkg/sub.py" not in [ path for path, _ in pb.list_sources( str( repo ), new, [ "src/pkg" ], [] ) ]


def test_an_empty_include_list_is_refused_because_the_population_must_be_declared( populated ):
    repo, sha = populated
    with pytest.raises( ValueError, match="include at least one" ):
        pb.list_sources( str( repo ), sha, [], [] )


# ---- reading at one commit ------------------------------------------------------------------

def test_the_pool_is_read_from_the_commit_not_from_the_working_tree( populated ):
    repo, sha = populated
    before, _ = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
    ( repo / "src" / "pkg" / "a.py" ).write_text( '"""Changed after the commit."""\n', encoding="utf-8" )
    ( repo / "src" / "pkg" / "new.py" ).write_text( '"""Untracked."""\n', encoding="utf-8" )
    after, _  = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
    assert before == after and any( "Parked" in r[ "symbol" ] for r in after )


def test_a_later_commit_gives_a_different_pool_and_the_same_commit_gives_the_same_bytes( populated, tmp_path_factory ):
    repo, sha = populated
    later     = commit( repo, { "src/pkg/a.py": '"""Rewritten module."""\n' } )
    one       = tmp_path_factory.mktemp( "one" ) / "pool.jsonl"
    two       = tmp_path_factory.mktemp( "two" ) / "pool.jsonl"
    for out in ( one, two ):
        rows, facts = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
        pb.write_pool( rows, facts, str( out ) )
    assert one.read_bytes() == two.read_bytes() and one.read_bytes()
    assert ( one.parent / "pool.jsonl.manifest.json" ).read_bytes() == ( two.parent / "pool.jsonl.manifest.json" ).read_bytes()
    newer, _ = pb.build_pool( str( repo ), later, [ "src/pkg" ], [] )
    assert [ r for r in newer if r[ "file" ] == "src/pkg/a.py" ] != [ r for r in pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )[ 0 ] if r[ "file" ] == "src/pkg/a.py" ]


def test_a_short_sha_is_recorded_in_full( populated ):
    repo, sha = populated
    _, facts  = pb.build_pool( str( repo ), sha[ :9 ], [ "src/pkg" ], [] )
    assert facts[ "source_sha" ] == sha and len( sha ) == 40


def test_a_name_that_is_not_a_commit_is_refused( populated ):
    repo, _ = populated
    with pytest.raises( RuntimeError, match="git rev-parse" ):
        pb.build_pool( str( repo ), "no-such-commit", [ "src/pkg" ], [] )


def test_two_files_with_the_same_content_are_read_once_and_give_one_set_of_rows( repo ):
    sha  = commit( repo, { "src/a.py": OTHER_SRC, "src/b.py": OTHER_SRC } )
    rows, facts = pb.build_pool( str( repo ), sha, [ "src" ], [] )
    assert ids( rows ) == [ "src/a.py::<module>", "src/a.py::run" ] and facts[ "files_read" ] == 2 and facts[ "duplicate_rows_dropped" ] == 2


def test_the_listing_is_sorted_whatever_order_git_returns_it_in( monkeypatch ):
    monkeypatch.setattr( pb, "run_git", lambda repo, args, data=None: b"100644 blob bbb\tsrc/z.py\x00100644 blob aaa\tsrc/a.py\x00" )
    assert pb.list_sources( "repo", "sha", [ "src" ], [] ) == [ ( "src/a.py", "aaa" ), ( "src/z.py", "bbb" ) ]


def test_an_empty_oid_list_reads_nothing_and_a_wrong_answer_from_git_is_refused( repo, monkeypatch ):
    assert pb.read_blobs( str( repo ), [] ) == {}
    monkeypatch.setattr( pb, "run_git", lambda repo, args, data=None: b"abc missing\n" )
    with pytest.raises( RuntimeError, match="did not return blob abc" ):
        pb.read_blobs( str( repo ), [ "abc" ] )


# ---- the manifest, the refusals and the command ----------------------------------------------

def test_the_manifest_records_both_shas_the_counts_and_every_skipped_file( repo, tmp_path_factory ):
    sha = commit( repo, { "src/ok.py": OTHER_SRC, "src/bad.py": "def (:\n", "src/enc.py": b"\xff\xfe" } )
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    rows, facts = pb.build_pool( str( repo ), sha, [ "src" ], [] )
    pb.write_pool( rows, facts, str( out ) )
    manifest = json.loads( ( out.parent / "pool.jsonl.manifest.json" ).read_text( encoding="utf-8" ) )
    assert manifest[ "source_sha" ] == sha and manifest[ "rows" ] == 2 and manifest[ "files_read" ] == 3
    assert manifest[ "files_skipped" ] == [ [ "src/bad.py", "syntax" ], [ "src/enc.py", "encoding" ] ]
    assert manifest[ "pool_sha256" ] == hashlib.sha256( out.read_bytes() ).hexdigest()
    assert manifest[ "builder_sha256" ] == hashlib.sha256( open( pb.__file__, "rb" ).read() ).hexdigest()


def test_the_written_pool_is_read_back_by_the_seeder_unchanged( populated, tmp_path_factory ):
    repo, sha = populated
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    rows, facts = pb.build_pool( str( repo ), sha, [ "src/pkg" ], [] )
    pb.write_pool( rows, facts, str( out ) )
    assert seeder.read_jsonl( str( out ) ) == rows and len( rows ) > 0


def test_a_pool_with_no_docstrings_is_refused_and_writes_nothing( repo, tmp_path_factory, capsys ):
    sha = commit( repo, { "src/a.py": "x = 1\n" } )
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    assert pb.main( [ "--repo", str( repo ), "--sha", sha, "--include", "src", "--out", str( out ) ] ) == 2
    assert "REFUSED: no docstrings found" in capsys.readouterr().err and not out.exists()


def test_the_command_writes_the_pool_and_reports_the_counts( populated, tmp_path_factory, capsys ):
    repo, sha = populated
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    assert pb.main( [ "--repo", str( repo ), "--sha", sha, "--include", "src/pkg", "--exclude", "src/pkg/skip", "--out", str( out ) ] ) == 0
    assert f"at {sha}" in capsys.readouterr().out
    assert out.exists() and ( out.parent / "pool.jsonl.manifest.json" ).exists()


def test_the_command_defaults_to_the_project_root( populated, tmp_path_factory, monkeypatch ):
    repo, sha = populated
    monkeypatch.setattr( pb.cu, "get_project_root", lambda: str( repo ) )
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    assert pb.main( [ "--sha", sha, "--include", "src/pkg", "--out", str( out ) ] ) == 0 and out.exists()


def test_the_command_refuses_a_bad_commit_without_a_traceback( populated, tmp_path_factory, capsys ):
    repo, _ = populated
    out = tmp_path_factory.mktemp( "o" ) / "pool.jsonl"
    assert pb.main( [ "--repo", str( repo ), "--sha", "nope", "--include", "src", "--out", str( out ) ] ) == 2
    assert "REFUSED:" in capsys.readouterr().err
