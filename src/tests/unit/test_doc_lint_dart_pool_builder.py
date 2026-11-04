"""
The Dart pool builder: its rows, its commit-only reading, its manifest and its refusals, and the seeder's
plan and rule-1 check run over a Dart pool.

Every Dart file here is a hand-made fixture written into a throwaway git repo. No real tree and no
labelled-set or pilot data is read, and nothing here can reach a model.
"""

import hashlib
import json
import os
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import dart_pool_builder as dpb
from cosa.repo.doc_lint import labelled_set_seeder as seeder

WIDGET = '''/// The widget library: everything the screen draws.
library widgets;

import 'dart:async';

/// Hold one parked row.
///
/// The flag is computed when the row is parked.
class Parked {
  /// Build a parked row from its id.
  Parked( this.id );

  /// Return the count of parked rows.
  int count() => 1;

  /// The row id, as given at construction.
  final String id;

  // not a doc comment
  void plain() {}
}

/// Documents nothing at the end of the file.
'''

OTHER = '/// Hold one other row.\nclass Other {\n  /// Run once.\n  void run() {}\n}\n'

SAME_AS_OTHER = '/// Hold  one other   row.\nclass Copy {}\n'


def git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.decode( "utf-8" ).strip()


def commit( root, files ):
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
    sha = commit( repo, { "lib/widgets.dart": WIDGET, "lib/other.dart": OTHER, "lib/copy.dart": SAME_AS_OTHER, "lib/readme.md": "text\n" } )
    return repo, sha


FILES = [ "lib/widgets.dart", "lib/other.dart" ]


# ---- what a row is --------------------------------------------------------------------------

def test_each_doc_block_that_names_a_declaration_or_a_library_becomes_a_row_in_the_shape_of_the_python_pool( populated ):
    repo, sha = populated
    rows, facts = dpb.build_dart_pool( str( repo ), sha, FILES )
    mine = [ r for r in rows if r[ "file" ] == "lib/widgets.dart" ]
    assert [ r[ "symbol" ] for r in mine ] == [ "<library>", "Parked", "Parked.new", "Parked.count", "Parked.id" ]
    assert all( set( r ) == { "id", "file", "symbol", "old" } for r in rows )
    assert [ r[ "id" ] for r in mine ][ :2 ] == [ "lib/widgets.dart::<library>", "lib/widgets.dart::Parked" ]
    assert next( r for r in mine if r[ "symbol" ] == "Parked" )[ "old" ] == "Hold one parked row.\n\nThe flag is computed when the row is parked."
    assert next( r for r in mine if r[ "symbol" ] == "Parked.count" )[ "old" ] == "Return the count of parked rows."
    assert facts[ "unattached_dropped" ] == 1                                                    # the block at the end of the file documents nothing


def test_a_blank_doc_block_is_left_out_and_not_counted_as_unattached( repo ):
    sha = commit( repo, { "lib/a.dart": "///\nclass A {}\n\n/// Real text.\nclass B {}\n" } )
    rows, facts = dpb.build_dart_pool( str( repo ), sha, [ "lib/a.dart" ] )
    assert [ r[ "symbol" ] for r in rows ] == [ "B" ] and facts[ "unattached_dropped" ] == 0


def test_two_blocks_with_the_same_name_in_one_file_get_the_numbered_ids_dart_pairs_gives( repo ):
    sha = commit( repo, { "lib/a.dart": "/// First text.\nvoid run() {}\n\n/// Second text.\nvoid run() {}\n" } )
    rows, _ = dpb.build_dart_pool( str( repo ), sha, [ "lib/a.dart" ] )
    assert [ r[ "id" ] for r in rows ] == [ "lib/a.dart::run", "lib/a.dart::run#2" ]


def test_a_copy_of_a_text_in_another_file_is_kept_once_and_named_in_the_manifest( populated ):
    repo, sha = populated
    rows, facts = dpb.build_dart_pool( str( repo ), sha, [ "lib/other.dart", "lib/copy.dart" ] )
    assert [ r[ "id" ] for r in rows if r[ "symbol" ] in ( "Other", "Copy" ) ] == [ "lib/copy.dart::Copy" ]       # the smaller id is kept, whitespace ignored
    assert facts[ "duplicates" ] == [ { "kept": "lib/copy.dart::Copy", "dropped": [ "lib/other.dart::Other" ] } ]
    assert facts[ "duplicate_rows_dropped" ] == 1 and facts[ "rows_before_dedupe" ] == facts[ "rows" ] + 1


def test_a_file_that_is_not_utf8_is_skipped_with_its_reason( repo ):
    sha = commit( repo, { "lib/good.dart": OTHER, "lib/bad.dart": b"/// caf\xe9\nclass Bad {}\n" } )
    rows, facts = dpb.build_dart_pool( str( repo ), sha, [ "lib/good.dart", "lib/bad.dart" ] )
    assert facts[ "files_skipped" ] == [ [ "lib/bad.dart", "encoding" ] ] and facts[ "files_read" ] == 2
    assert { r[ "file" ] for r in rows } == { "lib/good.dart" }


# ---- where the text comes from --------------------------------------------------------------

def test_the_pool_is_read_from_the_commit_and_not_from_the_working_tree( populated ):
    repo, sha = populated
    before, _ = dpb.build_dart_pool( str( repo ), sha, FILES )
    ( repo / "lib" / "widgets.dart" ).write_text( "/// Changed after the commit.\nclass Z {}\n" )
    ( repo / "lib" / "other.dart" ).unlink()
    after, _ = dpb.build_dart_pool( str( repo ), sha, FILES )
    assert after == before
    assert dpb.build_dart_pool( str( repo ), sha[ :10 ], FILES )[ 1 ][ "source_sha" ] == sha        # a short sha is recorded in full


# ---- refusals -------------------------------------------------------------------------------

def test_an_empty_list_a_non_dart_path_and_a_path_that_is_not_a_file_at_the_commit_are_refused( populated ):
    repo, sha = populated
    with pytest.raises( ValueError, match="declared, not defaulted" ): dpb.build_dart_pool( str( repo ), sha, [] )
    with pytest.raises( ValueError, match="not Dart files: lib/readme.md" ): dpb.build_dart_pool( str( repo ), sha, [ "lib/readme.md" ] )
    with pytest.raises( ValueError, match="not a file at .*: lib/nope.dart" ): dpb.build_dart_pool( str( repo ), sha, [ "lib/widgets.dart", "lib/nope.dart" ] )
    ( repo / "dir.dart" ).mkdir()                                                                  # a directory named *.dart is a tree entry, not a blob
    sha2 = commit( repo, { "dir.dart/x.dart": OTHER } )
    with pytest.raises( ValueError, match="not a file at .*: dir.dart" ): dpb.build_dart_pool( str( repo ), sha2, [ "dir.dart" ] )


@pytest.mark.parametrize( "path, why", [
    ( "test/widget_test.dart",                  "test file" ),
    ( "integration_test/app_test.dart",         "test file" ),
    ( "packages/core/test/a_test.dart",         "test file" ),
    ( "lib/src/test/helper.dart",               "test file" ),
    ( "lib/models/user.g.dart",                 "generated file" ),
    ( "lib/models/user.freezed.dart",           "generated file" ),
    ( "lib/services/api.mocks.dart",            "generated file" ),
    ( "test/user.g.dart",                       "test file" ),                       # a test directory is named before the generated suffix
    ( "lib/latest/page.dart",                   None ),                              # a directory that merely contains "test" is not a test directory
    ( "lib/testing/page.dart",                  None ),
    ( "lib/test_utils.dart",                    None ),                              # nor is a file name that starts with it
    ( "lib/contest/integration_tester.dart",    None ),
    ( "lib/models/user.dart",                   None ),
    ( "lib/models/g.dart",                      None ),
    ( "lib/models/user.generated_helper.dart",  None ),
] )
def test_a_test_or_generated_file_is_named_with_its_reason_and_nothing_else_is( path, why ):
    assert dpb.refusal_reason( path ) == why


def test_every_test_and_generated_file_is_refused_and_named_before_anything_is_read( populated ):
    repo, sha = populated
    listed = [ "lib/widgets.dart", "test/widgets_test.dart", "lib/user.g.dart", "integration_test/a.dart", "lib/nope.dart" ]
    with pytest.raises( ValueError ) as caught: dpb.build_dart_pool( str( repo ), sha, listed )
    message = str( caught.value )
    assert message == "refused, not prose for the pool: test/widgets_test.dart (test file); lib/user.g.dart (generated file); integration_test/a.dart (test file)"
    assert "lib/widgets.dart" not in message and "nope" not in message                        # the refusal comes first, so the missing file is not reported yet


def test_the_command_line_refuses_a_listed_test_file_with_exit_2_and_writes_nothing( populated, tmp_path, capsys ):
    repo, sha = populated
    listing = tmp_path / "files.txt"
    listing.write_text( "lib/widgets.dart\ntest/widgets_test.dart\n", encoding="utf-8" )
    out = tmp_path / "pool.jsonl"
    assert dpb.main( [ "--repo", str( repo ), "--sha", sha, "--files-from", str( listing ), "--out", str( out ) ] ) == 2
    assert "REFUSED: refused, not prose for the pool: test/widgets_test.dart (test file)" in capsys.readouterr().err and not out.exists()


def test_a_pool_with_no_rows_and_an_unknown_commit_are_refused( repo ):
    sha = commit( repo, { "lib/a.dart": "class A {}\n" } )
    with pytest.raises( ValueError, match="empty pool" ): dpb.build_dart_pool( str( repo ), sha, [ "lib/a.dart" ] )
    with pytest.raises( RuntimeError, match="failed" ): dpb.build_dart_pool( str( repo ), "0" * 40, [ "lib/a.dart" ] )


def test_the_file_list_is_read_one_path_a_line_and_a_repeated_path_counts_once( tmp_path ):
    listing = tmp_path / "files.txt"
    listing.write_text( "lib/a.dart\n\n  lib/b.dart  \nlib/a.dart\n", encoding="utf-8" )
    assert dpb.read_file_list( str( listing ) ) == [ "lib/a.dart", "lib/b.dart" ]


# ---- the files written and the command line -------------------------------------------------

def test_the_pool_and_manifest_are_written_with_hashes_and_the_same_commit_gives_the_same_bytes( populated, tmp_path, capsys ):
    repo, sha = populated
    listing = tmp_path / "files.txt"
    listing.write_text( "\n".join( FILES ) + "\n", encoding="utf-8" )
    outs = [ str( tmp_path / n / "pool.jsonl" ) for n in ( "a", "b" ) ]
    for out in outs: assert dpb.main( [ "--repo", str( repo ), "--sha", sha, "--files-from", str( listing ), "--out", out ] ) == 0
    assert "pool: 7 doc blocks from 2 files at " + sha in capsys.readouterr().out.splitlines()[ 0 ]
    assert open( outs[ 0 ], "rb" ).read() == open( outs[ 1 ], "rb" ).read()
    manifest = json.loads( open( outs[ 0 ] + ".manifest.json" ).read() )
    assert manifest[ "pool_sha256" ] == hashlib.sha256( open( outs[ 0 ], "rb" ).read() ).hexdigest()
    assert manifest[ "builder_sha256" ] == hashlib.sha256( open( dpb.__file__, "rb" ).read() ).hexdigest() == dpb.builder_sha256()
    assert manifest[ "source_sha" ] == sha and manifest[ "files" ] == FILES and manifest[ "language" ] == "dart" and manifest[ "rows" ] == 7
    assert seeder.read_jsonl( outs[ 0 ] )[ 0 ].keys() == { "id", "file", "symbol", "old" }


def test_the_command_line_refuses_with_exit_2_and_writes_nothing( populated, tmp_path, capsys ):
    repo, sha = populated
    listing = tmp_path / "files.txt"
    listing.write_text( "lib/nope.dart\n", encoding="utf-8" )
    out = tmp_path / "pool.jsonl"
    assert dpb.main( [ "--repo", str( repo ), "--sha", sha, "--files-from", str( listing ), "--out", str( out ) ] ) == 2
    assert "REFUSED: not a file at" in capsys.readouterr().err and not out.exists()
    assert dpb.main( [ "--repo", str( repo ), "--sha", sha, "--files-from", str( tmp_path / "missing.txt" ), "--out", str( out ) ] ) == 2
    assert "REFUSED" in capsys.readouterr().err and not out.exists()


# ---- the seeder over a Dart pool ------------------------------------------------------------

SMALL = { "pairs": 15, "delete": 4, "weaken": 5, "short": 2, "class_floor": 1, "relocate": 2, "paraphrase": 4 }
SIZES = json.dumps( { "gate": SMALL, "dev": SMALL } )


def dart_doc( n, filler ):
    """A hand-made doc block that offers every weaken class and deletable phrases; filler lines set the stratum."""
    lines = [ f"Return the number of idle workers in pool p{n}, or zero when parked.", "",
              "The count is exact when the pool is open, and it never raises",
              "if the pool is closed (it returns zero instead). Callers must hold the lock (in practice)",
              f"for at least three seconds, which keeps the figure of pool p{n} stable. The figure is only a hint and is always safe." ]
    lines += [ f"Note {chr( 97 + i )} says something distinct about shape {chr( 97 + i )}." for i in range( filler ) ]
    return "\n".join( ( "  /// " + l ).rstrip() for l in lines )


@pytest.fixture
def dart_repo( repo ):
    files = {}
    for u in range( 12 ):
        for k in range( 6 ):
            n = u * 100 + k + 7
            files[ f"lib/pkg{u:02d}/mod{k}.dart" ] = f"class Pool{n} {{\n{dart_doc( n, [ 0, 5, 12 ][ k % 3 ] )}\n  int idle() => 0;\n}}\n"
    return repo, commit( repo, files ), sorted( files )


@pytest.fixture
def planned( dart_repo, tmp_path, monkeypatch ):
    repo, sha, files = dart_repo
    fake_root = tmp_path / "fake-repo"; fake_root.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( fake_root ) )                          # gate output under tmp_path is then outside the repo
    pool = str( tmp_path / "pool.jsonl" )
    rows, facts = dpb.build_dart_pool( str( repo ), sha, files )
    dpb.write_pool( rows, facts, pool )
    args = [ "plan", "--pool", pool, "--out", str( tmp_path / "out" ), "--gate-out", str( tmp_path / "gate-store" ), "--option", "A",
             "--seed", "1", "--gate-seed", "2", "--split-seed", "100", "--sizes-json", SIZES ]
    assert seeder.main( args ) == 0
    return tmp_path / "out", rows


def test_plan_accepts_a_dart_pool_and_draws_from_the_doc_text_of_every_unit( planned ):
    base, rows = planned
    plan = json.loads( ( base / "dev" / "plan.json" ).read_text() )
    assert len( rows ) == 72 and plan[ "pairs" ] and { p[ "kind" ] for p in plan[ "pairs" ] } >= { "weaken", "delete" }
    assert all( p[ "file" ].startswith( "lib/pkg" ) and p[ "file" ].endswith( ".dart" ) for p in plan[ "pairs" ] )
    tasks = seeder.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )
    assert tasks and not any( "///" in t[ "text" ] for t in tasks )                                 # the writer sees prose, never the comment marker


def write_outputs( base, restore=None ):
    """Writer outputs from hand: each task's own text, which keeps a cut cut and a weak word weak; `restore` maps a task id to other text."""
    plan  = json.loads( ( base / "dev" / "plan.json" ).read_text() )
    tasks = seeder.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )
    rows  = [ { "task_id": t[ "task_id" ], "task_sha": plan[ "tasks" ][ t[ "task_id" ] ][ "sha256" ], "text": ( restore or {} ).get( t[ "task_id" ], t[ "text" ] ) } for t in tasks ]
    seeder.write_jsonl( str( base / "dev" / "writer_outputs.jsonl" ), rows )
    return plan, tasks


def test_rule_1_passes_a_dart_set_whose_writer_kept_every_cut_and_weak_word( planned, capsys ):
    base, _ = planned
    plan, _ = write_outputs( base )
    seeded = [ p for p in plan[ "pairs" ] if p[ "kind" ] in seeder.SEEDED_KINDS ]
    assert seeded and seeder.main( [ "check", "--base", str( base ), "--split", "dev" ] ) == 0
    assert f"check dev: {len( seeded )} seeded pairs, 0 fail" in capsys.readouterr().out


def test_rule_1_fails_a_dart_pair_whose_writer_put_the_cut_span_back( planned, capsys ):
    base, _ = planned
    plan = json.loads( ( base / "dev" / "plan.json" ).read_text() )
    pair = next( p for p in plan[ "pairs" ] if p[ "kind" ] == "delete" )
    task_id = next( t for t, meta in plan[ "tasks" ].items() if meta[ "pair_id" ] == pair[ "id" ] and meta[ "role" ] == "new" )
    write_outputs( base, restore={ task_id: "Restored: " + pair[ "x_span_in_old" ] } )
    assert seeder.main( [ "check", "--base", str( base ), "--split", "dev" ] ) == 1
    assert f"{pair[ 'id' ]} SPAN_VERBATIM" in capsys.readouterr().out


def test_a_dart_doc_with_code_fence_reference_brackets_and_backticks_still_plans_and_checks( repo, tmp_path, monkeypatch ):
    """The Dart house style: [Foo] references, `code` spans and fenced samples. The seeder reads the text, so none of it may break a draw."""
    doc = ( "  /// Returns the [Parked] row for [id], or `null` when none was parked.\n  ///\n"
            "  /// The lookup is exact and never throws if the cache is empty (it returns `null` instead).\n"
            "  /// Callers must call [open] first, which keeps the cache stable for at least three seconds.\n"
            "  ///\n  /// ```dart\n  /// final row = cache.find( 'a' );\n  /// ```\n"
            "  /// The value is only a hint and is always safe to ignore." )
    files = { f"lib/p{u}/m{k}.dart": f"class C{u}{k} {{\n{doc.replace( 'Parked', f'Parked{u}{k}' )}\n  int find() => 0;\n}}\n" for u in range( 12 ) for k in range( 6 ) }
    sha = commit( repo, files )
    rows, facts = dpb.build_dart_pool( str( repo ), sha, sorted( files ) )
    assert len( rows ) == 72 and "```dart" in rows[ 0 ][ "old" ] and "[id]" in rows[ 0 ][ "old" ]
    docs_by_kind, units = seeder.build_docs( rows, seeder.load_stoplist( seeder.DEFAULT_STOPLIST ) )
    assert len( units ) == 12 and docs_by_kind[ "delete" ] and docs_by_kind[ "weaken" ]
