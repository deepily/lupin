"""
Gate 0 of the R&D triage: no doc that a live file cites may be called history.

The precedent census deleted two docs. Its search listed file extensions, so it never opened the
`.css` and `.md` files that named them. Each test here plants a citer in a file type that an
extension list would miss. An instrument has to be watched finding something before its silence
means anything.
"""

import json
import subprocess

import pytest

from cosa.repo.doc_lint import rnd_gate0


DOC = "src/rnd/v0.1.9/2026.06.19-layout/01-layout-parity-methodology.md"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _write( root, rel, text="x\n" ):
    path = root / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )


def _repo( tmp_path, files, untracked=None ):
    """Build a git repo of tracked `files` ({rel: text}) and untracked files outside the index."""
    _git( tmp_path, "init", "-q" )
    for rel, text in files.items(): _write( tmp_path, rel, text )
    _git( tmp_path, "add", "--", *files.keys() )
    _git( tmp_path, "commit", "-q", "-m", "seed" )
    for rel, text in ( untracked or {} ).items(): _write( tmp_path, rel, text )
    return tmp_path


def test_a_css_comment_that_names_the_doc_by_path_is_a_live_path_citer( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/static/css/surface.css": "/* provenance: %s */\n" % DOC } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "live_path_citers" ] == [ "src/static/css/surface.css" ]
    assert found[ "blocks_history" ] is True


def test_a_file_with_an_unknown_extension_is_still_searched( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "ops/notes.weirdext": "see %s\n" % DOC } )
    assert rnd_gate0.gate0( root, [ DOC ] )[ DOC ][ "live_path_citers" ] == [ "ops/notes.weirdext" ]


def test_a_file_name_without_its_directory_is_a_name_citer_not_a_path_citer( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/docs/guide.md": "read 01-layout-parity-methodology.md first\n" } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "live_path_citers" ] == []
    assert found[ "live_name_citers" ] == [ "src/docs/guide.md" ]
    assert found[ "blocks_history" ] is True


def test_a_file_that_names_the_doc_by_path_is_not_also_listed_by_name( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/docs/guide.md": "see %s\n" % DOC } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "live_path_citers" ] == [ "src/docs/guide.md" ]
    assert found[ "live_name_citers" ] == []


def test_the_doc_never_cites_itself( tmp_path ):
    root = _repo( tmp_path, { DOC: "# %s\nthis file is 01-layout-parity-methodology.md\n" % DOC } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "live_path_citers" ] == [] and found[ "rnd_path_citers" ] == []
    assert found[ "blocks_history" ] is False


def test_a_citer_inside_rnd_is_recorded_apart_and_blocks_nothing( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/rnd/v0.2.0/other.md": "builds on %s\n" % DOC } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "rnd_path_citers" ] == [ "src/rnd/v0.2.0/other.md" ]
    assert found[ "live_path_citers" ] == []
    assert found[ "blocks_history" ] is False


def test_a_citer_under_the_cosa_rnd_root_counts_as_rnd( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/cosa/rnd/note.md": "see %s\n" % DOC } )
    assert rnd_gate0.gate0( root, [ DOC ] )[ DOC ][ "rnd_path_citers" ] == [ "src/cosa/rnd/note.md" ]


@pytest.mark.parametrize( "index_path", sorted( rnd_gate0.NON_CITING ) )
def test_the_index_the_ledger_and_the_census_manifest_prove_nothing( tmp_path, index_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", index_path: "- %s\n" % DOC } )
    found = rnd_gate0.gate0( root, [ DOC ] )[ DOC ]
    assert found[ "live_path_citers" ] == [] and found[ "rnd_path_citers" ] == []
    assert found[ "blocks_history" ] is False


def test_the_non_citing_list_is_exactly_the_three_named_files():
    assert rnd_gate0.NON_CITING == frozenset( {
        "src/rnd/README.md",
        "src/docs/rnd-ledger.tsv",
        "src/docs/2026.09.22-pre-september-rnd-deletion-candidates.md",
    } )


def test_an_untracked_citer_is_not_seen_and_an_untracked_doc_is_not_in_the_population( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n" },
                  untracked={ "src/docs/guide.md": "see %s\n" % DOC, "src/rnd/v0.2.2/scratch.md": "x\n" } )
    assert rnd_gate0.gate0( root, [ DOC ] )[ DOC ][ "live_path_citers" ] == []
    assert rnd_gate0.rnd_population( root ) == [ DOC ]


def test_a_tracked_file_missing_from_the_work_tree_is_skipped_not_fatal( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/docs/gone.md": "see %s\n" % DOC } )
    ( root / "src/docs/gone.md" ).unlink()
    assert rnd_gate0.gate0( root, [ DOC ] )[ DOC ][ "live_path_citers" ] == []


def test_a_tracked_directory_symlink_is_skipped_not_fatal( tmp_path ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/docs/real.md": "x\n" } )
    ( root / "linked" ).symlink_to( root / "src" )
    _git( root, "add", "--", "linked" )
    assert rnd_gate0.gate0( root, [ DOC ] )[ DOC ][ "live_path_citers" ] == []


def test_the_population_is_every_tracked_file_under_both_roots_not_only_markdown( tmp_path ):
    files = { "src/rnd/a.md": "x\n", "src/rnd/assets/b.png": "x\n", "src/cosa/rnd/c.md": "x\n",
              "src/docs/d.md": "x\n", "src/rnd_extra/e.md": "x\n" }
    root = _repo( tmp_path, files )
    assert rnd_gate0.rnd_population( root ) == [ "src/cosa/rnd/c.md", "src/rnd/a.md", "src/rnd/assets/b.png" ]
    assert rnd_gate0.rnd_markdown( root ) == [ "src/cosa/rnd/c.md", "src/rnd/a.md" ]


def test_the_default_run_covers_the_whole_population( tmp_path ):
    root = _repo( tmp_path, { "src/rnd/a.md": "x\n", "src/rnd/b.md": "see src/rnd/a.md\n", "src/docs/live.md": "src/rnd/b.md\n" } )
    result = rnd_gate0.gate0( root )
    assert sorted( result ) == [ "src/rnd/a.md", "src/rnd/b.md" ]
    assert result[ "src/rnd/b.md" ][ "blocks_history" ] is True
    assert result[ "src/rnd/a.md" ][ "blocks_history" ] is False


def test_a_listing_failure_names_the_git_error( tmp_path ):
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        rnd_gate0.rnd_population( tmp_path )


def test_the_cli_prints_one_tab_separated_row_per_doc_with_a_header( tmp_path, capsys ):
    root = _repo( tmp_path, { DOC: "# doc\n", "src/static/a.css": "%s\n" % DOC } )
    assert rnd_gate0.main( [ "--repo-root", str( root ), DOC ] ) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[ 0 ].split( "\t" ) == [ "path", "blocks_history", "live_path_citers", "live_name_citers", "rnd_citers" ]
    assert lines[ 1 ].split( "\t" ) == [ DOC, "yes", "1", "0", "0" ]


def test_the_cli_json_flag_prints_the_result_and_the_default_covers_the_population( tmp_path, capsys ):
    root = _repo( tmp_path, { "src/rnd/a.md": "x\n" } )
    assert rnd_gate0.main( [ "--repo-root", str( root ), "--json" ] ) == 0
    printed = json.loads( capsys.readouterr().out )
    assert list( printed ) == [ "src/rnd/a.md" ]
    assert printed[ "src/rnd/a.md" ][ "blocks_history" ] is False
