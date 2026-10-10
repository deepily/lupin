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


def test_the_non_citing_list_is_exactly_the_five_named_files():
    assert rnd_gate0.NON_CITING == frozenset( {
        "src/rnd/README.md",
        "src/docs/rnd-ledger.tsv",
        "src/docs/2026.09.22-pre-september-rnd-deletion-candidates.md",
        "src/cosa/repo/doc_lint/rnd_gate0.py",
        "src/tests/unit/test_doc_lint_rnd_gate0.py",
    } )


def test_the_gate_names_no_real_doc_in_its_own_source():
    with open( rnd_gate0.__file__, encoding="utf-8" ) as handle: source = handle.read()
    assert "01-design-overview.md" not in source


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
    assert lines[ 0 ].split( "\t" ) == [ "path", "blocks_history", "live_path_citers", "live_name_citers", "live_stem_citers", "rnd_citers" ]
    assert lines[ 1 ].split( "\t" ) == [ DOC, "yes", "1", "0", "0", "0" ]


def test_the_cli_json_flag_prints_the_result_and_the_default_covers_the_population( tmp_path, capsys ):
    root = _repo( tmp_path, { "src/rnd/a.md": "x\n" } )
    assert rnd_gate0.main( [ "--repo-root", str( root ), "--json" ] ) == 0
    printed = json.loads( capsys.readouterr().out )
    assert list( printed ) == [ "src/rnd/a.md" ]
    assert printed[ "src/rnd/a.md" ][ "blocks_history" ] is False


# --- the stem class: a citation that drops the file extension ---------------------------------------

STEM_DOC = "src/rnd/v0.1.7/2026.04.26-cards/03-has-interactions-accuracy.md"


def test_a_stem_inside_a_brace_list_is_a_live_stem_citer_and_blocks( tmp_path ):
    root = _repo( tmp_path, { STEM_DOC: "# doc\n",
                              "history/2026-08-10-history.md": "moved {02-api-shape, 03-has-interactions-accuracy}.md\n" } )
    found = rnd_gate0.gate0( root, [ STEM_DOC ] )[ STEM_DOC ]
    assert found[ "live_stem_citers" ] == [ "history/2026-08-10-history.md" ]
    assert found[ "live_path_citers" ] == [] and found[ "live_name_citers" ] == []
    assert found[ "blocks_history" ] is True


def test_a_stem_in_prose_with_no_extension_is_a_live_stem_citer( tmp_path ):
    root = _repo( tmp_path, { STEM_DOC: "# doc\n", "TODO.md": "(01-design + 03-has-interactions-accuracy)\n" } )
    assert rnd_gate0.gate0( root, [ STEM_DOC ] )[ STEM_DOC ][ "live_stem_citers" ] == [ "TODO.md" ]


def test_a_file_that_names_the_full_file_name_is_not_also_a_stem_citer( tmp_path ):
    root = _repo( tmp_path, { STEM_DOC: "# doc\n", "src/docs/guide.md": "read 03-has-interactions-accuracy.md\n" } )
    found = rnd_gate0.gate0( root, [ STEM_DOC ] )[ STEM_DOC ]
    assert found[ "live_name_citers" ] == [ "src/docs/guide.md" ]
    assert found[ "live_stem_citers" ] == []


def test_a_stem_shorter_than_the_minimum_is_not_searched( tmp_path ):
    short = "src/rnd/v0.1.7/x/00-index.md"
    root  = _repo( tmp_path, { short: "# doc\n", "TODO.md": "see 00-index here\n" } )
    found = rnd_gate0.gate0( root, [ short ] )[ short ]
    assert len( "00-index" ) < rnd_gate0.MIN_STEM_LENGTH
    assert found[ "live_stem_citers" ] == [] and found[ "blocks_history" ] is False


def test_a_stem_of_exactly_the_minimum_length_is_searched( tmp_path ):
    stem = "a" * rnd_gate0.MIN_STEM_LENGTH
    doc  = "src/rnd/v0.1.7/x/%s.md" % stem
    root = _repo( tmp_path, { doc: "# doc\n", "TODO.md": "see %s\n" % stem } )
    assert rnd_gate0.gate0( root, [ doc ] )[ doc ][ "live_stem_citers" ] == [ "TODO.md" ]


def test_the_minimum_stem_length_is_twelve():
    assert rnd_gate0.MIN_STEM_LENGTH == 12


def test_a_stem_citer_inside_rnd_is_recorded_apart_and_blocks_nothing( tmp_path ):
    root  = _repo( tmp_path, { STEM_DOC: "# doc\n", "src/rnd/v0.2.0/other.md": "builds on 03-has-interactions-accuracy\n" } )
    found = rnd_gate0.gate0( root, [ STEM_DOC ] )[ STEM_DOC ]
    assert found[ "rnd_stem_citers" ] == [ "src/rnd/v0.2.0/other.md" ]
    assert found[ "blocks_history" ] is False


def test_a_stem_in_a_non_citing_file_is_ignored( tmp_path ):
    root = _repo( tmp_path, { STEM_DOC: "# doc\n", "src/docs/rnd-ledger.tsv": "03-has-interactions-accuracy\n" } )
    assert rnd_gate0.gate0( root, [ STEM_DOC ] )[ STEM_DOC ][ "live_stem_citers" ] == []


def test_every_citer_list_is_sorted_when_two_citers_are_planted( tmp_path ):
    doc   = "src/rnd/v0.1.7/x/01-layout-parity-methodology.md"
    files = { doc: "# doc\n" }
    for name in ( "zz", "aa" ):
        files[ "src/docs/%s-path.md" % name ] = "see %s\n" % doc
        files[ "src/docs/%s-name.md" % name ] = "read 01-layout-parity-methodology.md\n"
        files[ "src/docs/%s-stem.md" % name ] = "{a, 01-layout-parity-methodology}.md\n"
        files[ "src/rnd/v0.2.0/%s-rpath.md" % name ] = "see %s\n" % doc
        files[ "src/rnd/v0.2.0/%s-rname.md" % name ] = "read 01-layout-parity-methodology.md\n"
        files[ "src/rnd/v0.2.0/%s-rstem.md" % name ] = "{a, 01-layout-parity-methodology}.md\n"
    found = rnd_gate0.gate0( _repo( tmp_path, files ), [ doc ] )[ doc ]
    for key in ( "live_path_citers", "live_name_citers", "live_stem_citers", "rnd_path_citers", "rnd_name_citers", "rnd_stem_citers" ):
        assert len( found[ key ] ) == 2, key
        assert found[ key ] == sorted( found[ key ] ), key


# --- the live-citer ruling: which citers hold a doc out of history ----------------------------------

A = "src/rnd/v0.1.7/a/alpha-design-document.md"
B = "src/rnd/v0.1.7/b/beta-design-document.md"
C = "src/rnd/v0.1.7/c/gamma-design-document.md"


def _entry( **citers ):
    entry = { key: [] for key in ( "live_path_citers", "live_name_citers", "live_stem_citers",
                                   "rnd_path_citers", "rnd_name_citers", "rnd_stem_citers" ) }
    entry.update( citers )
    entry[ "blocks_history" ] = bool( entry[ "live_path_citers" ] or entry[ "live_name_citers" ] or entry[ "live_stem_citers" ] )
    return entry


@pytest.mark.parametrize( "path, kind", [
    ( "src/cosa/agents/foo.py",                  "live" ),
    ( "src/tests/unit/test_x.py",                "live" ),
    ( "CLAUDE.md",                               "live" ),
    ( "src/cosa/CLAUDE.md",                      "live" ),
    ( "src/docs/guide.md",                       "live" ),
    ( "TODO.md",                                 "live" ),
    ( ".claude/commands/plan-review.md",         "live" ),
    ( ".claude/skills/some-skill/SKILL.md",      "live" ),
    ( "bug-fix-queue.md",                        "live" ),
    ( "history/2026-08-10-to-12-history.md",     "archive" ),
    ( "todo-history/2026-08-todo.md",            "archive" ),
    ( "src/cosa/history/2026-04-25-history.md",  "archive" ),
    ( "history.md",                              "archive" ),
    ( "src/cosa/history.md",                     "archive" ),
    ( ".claude-session.md",                      "archive" ),
    ( "src/cosa/.claude-session.md",             "archive" ),
    ( "src/rnd/README.md",                       "index" ),
    ( "src/cosa/rnd/README.md",                  "index" ),
    ( "src/rnd/v0.1.7/x/README.md",              "rnd" ),
    ( "src/cosa/rnd/sub/README.md",              "rnd" ),
    ( "src/rnd/v0.1.7/x/other.md",               "rnd" ),
    ( "src/cosa/rnd/note.md",                    "rnd" ),
] )
def test_each_citer_falls_in_the_category_the_ruling_table_gives_it( path, kind ):
    assert rnd_gate0.citer_kind( path ) == kind


@pytest.mark.parametrize( "citer_field", [ "live_path_citers", "live_name_citers", "live_stem_citers" ] )
def test_a_live_citer_of_any_class_holds_a_would_be_history_doc( citer_field ):
    gate  = { A: _entry( **{ citer_field: [ "src/cosa/agents/foo.py" ] } ) }
    final = rnd_gate0.resolve( gate, { A: "history" } )
    assert final[ A ][ "class" ] == "new"
    assert final[ A ][ "holding_citers" ] == [ "src/cosa/agents/foo.py" ]


def test_a_history_archive_citer_alone_does_not_hold_a_doc():
    gate  = { A: _entry( live_path_citers=[ "history/2026-08-history.md", "src/cosa/history.md", ".claude-session.md" ] ) }
    final = rnd_gate0.resolve( gate, { A: "history" } )
    assert final[ A ][ "class" ] == "history"
    assert final[ A ][ "holding_citers" ] == []
    assert final[ A ][ "free_citers" ] == [ ".claude-session.md", "history/2026-08-history.md", "src/cosa/history.md" ]


def test_an_index_readme_alone_does_not_hold_a_doc():
    gate  = { A: _entry( rnd_name_citers=[ "src/rnd/README.md", "src/cosa/rnd/README.md" ] ) }
    final = rnd_gate0.resolve( gate, { A: "history" } )
    assert final[ A ][ "class" ] == "history"


def test_an_initiative_folder_readme_holds_a_doc_like_any_other_rnd_citer():
    gate  = { A: _entry( rnd_name_citers=[ "src/rnd/v0.1.7/x/README.md" ] ) }
    final = rnd_gate0.resolve( gate, { A: "history" } )
    assert final[ A ][ "class" ] == "new"
    assert final[ A ][ "holding_citers" ] == [ "src/rnd/v0.1.7/x/README.md" ]


@pytest.mark.parametrize( "citer_class", [ "in force", "new" ] )
def test_an_rnd_citer_classed_in_force_or_new_holds_a_doc( citer_class ):
    gate  = { A: _entry( rnd_path_citers=[ B ] ), B: _entry() }
    final = rnd_gate0.resolve( gate, { A: "history", B: citer_class } )
    assert final[ A ][ "class" ] == "new"
    assert final[ A ][ "holding_citers" ] == [ B ]


def test_an_rnd_citer_not_yet_classified_holds_a_doc():
    gate  = { A: _entry( rnd_path_citers=[ B ] ), B: _entry() }
    final = rnd_gate0.resolve( gate, { A: "history" } )
    assert final[ A ][ "class" ] == "new"
    assert final[ B ][ "class" ] == "new"


@pytest.mark.parametrize( "citer_class", [ "history", "superseded" ] )
def test_an_rnd_citer_classed_history_or_superseded_does_not_hold_a_doc( citer_class ):
    gate  = { A: _entry( rnd_path_citers=[ B ] ), B: _entry() }
    final = rnd_gate0.resolve( gate, { A: "history", B: citer_class } )
    assert final[ A ][ "class" ] == "history"
    assert final[ A ][ "free_citers" ] == [ B ]


def test_the_classes_settle_over_passes_until_nothing_changes():
    gate  = { A: _entry( rnd_path_citers=[ B ] ), B: _entry( rnd_path_citers=[ C ] ), C: _entry( live_path_citers=[ "src/docs/guide.md" ] ) }
    final = rnd_gate0.resolve( gate, { A: "history", B: "history", C: "history" } )
    assert [ final[ d ][ "class" ] for d in ( A, B, C ) ] == [ "new", "new", "new" ]


def test_a_chain_cited_only_by_history_docs_stays_history():
    gate  = { A: _entry( rnd_path_citers=[ B ] ), B: _entry( rnd_path_citers=[ C ] ), C: _entry( live_path_citers=[ "history/2026-08-history.md" ] ) }
    final = rnd_gate0.resolve( gate, { A: "history", B: "history", C: "history" } )
    assert [ final[ d ][ "class" ] for d in ( A, B, C ) ] == [ "history", "history", "history" ]


def test_a_superseded_or_in_force_doc_keeps_its_class_whatever_cites_it():
    gate  = { A: _entry( live_path_citers=[ "src/cosa/agents/foo.py" ] ), B: _entry( live_path_citers=[ "src/cosa/agents/foo.py" ] ) }
    final = rnd_gate0.resolve( gate, { A: "superseded", B: "in force" } )
    assert final[ A ][ "class" ] == "superseded" and final[ B ][ "class" ] == "in force"


def test_an_entry_keeps_the_proposed_class_beside_the_final_one():
    gate  = { A: _entry( live_path_citers=[ "TODO.md" ] ) }
    entry = rnd_gate0.resolve( gate, { A: "history" } )[ A ]
    assert entry[ "proposed" ] == "history" and entry[ "class" ] == "new"


def test_the_description_counts_the_citers_that_hold_and_the_ones_that_do_not():
    gate  = { A: _entry( live_path_citers=[ "src/cosa/agents/foo.py", "history/a.md", "history/b.md" ],
                         rnd_path_citers=[ "src/rnd/README.md" ] ) }
    entry = rnd_gate0.resolve( gate, { A: "history" } )[ A ]
    assert rnd_gate0.describe( entry ) == "holds 1 (live 1); passes 3 (archive 2, index 1)"


def test_the_description_of_an_uncited_doc_says_so():
    assert rnd_gate0.describe( rnd_gate0.resolve( { A: _entry() }, { A: "history" } )[ A ] ) == "holds 0; passes 0"


def test_the_precedent_check_names_every_doc_that_came_out_history():
    final = { A: { "class": "history" }, B: { "class": "new" }, C: { "class": "history" } }
    assert rnd_gate0.precedent_violations( final, [ C, B, A, "src/rnd/not-in-census.md" ] ) == [ A, C ]


def test_the_ruling_note_marks_the_rule_as_the_managers_and_open_to_change():
    assert "2026-10-09" in rnd_gate0.RULING_NOTE
    assert "Rick may change it" in rnd_gate0.RULING_NOTE


def test_the_cli_resolves_a_proposed_class_file_into_final_classes( tmp_path, capsys ):
    root     = _repo( tmp_path, { A: "# a\n", B: "# b\n", "src/docs/guide.md": "see %s\n" % A } )
    proposed = tmp_path / "proposed.tsv"
    proposed.write_text( "%s\thistory\n\n%s\thistory\textra column\n" % ( A, B ), encoding="utf-8" )
    assert rnd_gate0.main( [ "--repo-root", str( root ), "--proposed", str( proposed ) ] ) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[ 0 ].split( "\t" ) == [ "path", "proposed", "class", "holds", "passes" ]
    assert lines[ 1 ].split( "\t" ) == [ A, "history", "new", "1", "0" ]
    assert lines[ 2 ].split( "\t" ) == [ B, "history", "history", "0", "0" ]
