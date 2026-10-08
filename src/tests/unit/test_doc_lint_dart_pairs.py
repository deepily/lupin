"""
dart_pairs: a git range to per-symbol before and after Dart doc text.

The fixtures are a scratch git repo with two commits of a small Dart tree, so every count in
the report is worked out by hand. The symbol tests feed source text straight to extract_blocks.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import dart_pairs as dp
from cosa.repo.doc_lint.labelled_pairs import load_pairs

LONG = " ".join( f"word{i}" for i in range( 35 ) )
SHORT = "Only a few words here."


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _symbols( source ):
    return [ s for s, _, _ in dp.extract_blocks( source ) ]


def test_block_text_strips_line_ends_and_edge_blank_lines_and_keeps_inner_layout():
    assert dp.block_text( "\n\nfirst  \n\n  - item\n\n" ) == "first\n\n  - item"


def test_squash_reduces_whitespace_runs_to_one_space():
    assert dp.squash( "  a \n\n b\t c " ) == "a b c"


def test_a_class_block_is_named_by_the_class_and_a_member_by_owner_dot_member():
    src = "/// Doc A.\nclass Alpha {\n  /// Doc m.\n  void run() {}\n}\n\n/// Doc B.\nclass Beta {\n  /// Doc n.\n  int count = 0;\n}\n"
    assert _symbols( src ) == [ "Alpha", "Alpha.run", "Beta", "Beta.count" ]


def test_annotations_one_line_and_many_lines_blank_lines_and_plain_comments_are_skipped():
    src = ( "class A {\n  /// One.\n  @override\n\n  // plain note\n  void a() {}\n"
            "  /// Two.\n  @Deprecated(\n    'old',\n  )\n  @override\n  void b() {}\n}\n" )
    assert _symbols( src ) == [ "A.a", "A.b" ]


def test_getter_setter_and_operator_are_told_apart():
    src = ( "class A {\n  /// G.\n  int get size => 1;\n  /// S.\n  set size( int v ) {}\n"
            "  /// O.\n  bool operator ==( Object other ) => true;\n}\n" )
    assert _symbols( src ) == [ "A.size", "A.size=", "A.operator==" ]


def test_constructors_factories_generics_and_fields_are_named():
    src = ( "class Foo {\n  /// C1.\n  Foo.named();\n  /// C2.\n  factory Foo.fromJson( Map m ) => Foo.named();\n"
            "  /// G.\n  static bool isRegistered<T extends Object>() => true;\n"
            "  /// F.\n  final List<Map<String, int>> items;\n}\n" )
    assert _symbols( src ) == [ "Foo.named", "Foo.fromJson", "Foo.isRegistered", "Foo.items" ]
    assert _symbols( "class Foo {\n  /// Plain.\n  Foo();\n}\n" ) == [ "Foo.new" ]


def test_a_function_typed_member_is_named_by_the_word_after_its_parameter_list_not_by_Function():
    src = ( "class A {\n  /// F1.\n  final void Function( TaskVerb verb )? onVerb;\n"
            "  /// F2.\n  final void Function( { String? priority, String? owner } )? onField;\n"
            "  /// F3.\n  final Future<List<Map<String, dynamic>>> Function(\n    String a,\n    int Function( int ) b,\n  )\n      fetchAll;\n"
            "  /// F4.\n  final Future<double> Function() ttsFraction;\n}\n" )
    assert _symbols( src ) == [ "A.onVerb", "A.onField", "A.fetchAll", "A.ttsFraction" ]


def test_a_top_level_function_that_returns_a_function_type_is_named_by_the_function():
    assert _symbols( "/// R.\nFuture<List<Sender>> Function()? muteRosterLoader( BuildContext context ) {\n  return null;\n}\n" ) == [ "muteRosterLoader" ]


def test_a_function_type_with_no_name_after_it_or_an_unclosed_list_is_unattached():
    assert _symbols( "/// A.\nvoid Function( int x )\n" ) == [ "<unattached>" ]
    assert _symbols( "/// B.\nvoid Function( int x,\n" ) == [ "<unattached>" ]


def test_enum_values_are_named_without_the_trailing_comma():
    src = "enum Kind {\n  /// A.\n  image,\n\n  /// B.\n  directory,\n\n  /// C.\n  last\n}\n"
    assert _symbols( src ) == [ "Kind.image", "Kind.directory", "Kind.last" ]


def test_a_declaration_head_that_runs_over_lines_is_read_up_to_its_parenthesis():
    src = "class A {\n  /// M.\n  static const\n      Duration\n      timeout\n      = Duration( seconds: 1 );\n}\n"
    assert _symbols( src ) == [ "A.timeout" ]


def test_a_head_with_no_delimiter_is_read_to_the_end_of_the_window():
    assert _symbols( "/// M.\nint x\n" ) == [ "x" ]


def test_a_library_block_a_top_level_function_and_a_mixin_enum_typedef_are_named():
    src = ( "/// Lib.\nlibrary foo;\n\n/// F.\nvoid top() {}\n\n/// M.\nmixin Mix {}\n\n/// E.\nenum Color { red }\n"
            "\n/// T.\ntypedef Cb = void Function();\n\n/// X.\nabstract class Abs {}\n" )
    assert _symbols( src ) == [ "<library>", "top", "Mix", "Color", "Cb", "Abs" ]


def test_a_function_after_a_closed_class_has_no_owner_and_a_one_line_class_owns_nothing():
    src = "class A {\n  /// One.\n  void a() {}\n}\n\n/// Free.\nvoid free() {}\n\nclass Empty {}\n\n/// Also free.\nvoid free2() {}\n\nclass B {\n  /// Two.\n  void b() {}\n}\n"
    assert _symbols( src ) == [ "A.a", "free", "free2", "B.b" ]


def test_a_class_never_closed_owns_to_the_end_of_the_file():
    assert _symbols( "class A {\n  /// One.\n  void a() {}\n" ) == [ "A.a" ]


def test_a_repeated_symbol_gets_a_number_suffix_in_file_order():
    src = "class A {\n  /// One.\n  void a() {}\n  /// Two.\n  void a( int x ) {}\n  /// Three.\n  void a( int x, int y ) {}\n}\n"
    assert _symbols( src ) == [ "A.a", "A.a#2", "A.a#3" ]


def test_a_block_comment_block_is_named_from_the_line_after_its_closing_marker():
    src = "class A {\n  /**\n   * Block doc.\n   */\n  void a() {}\n}\n"
    assert _symbols( src ) == [ "A.a" ]


def test_a_block_with_nothing_readable_under_it_is_unattached():
    assert _symbols( "class A {\n  /// Dangling.\n}\n" ) == [ "<unattached>" ]
    assert _symbols( "/// At the end." ) == [ "<unattached>" ]
    assert _symbols( "/// Modifier only.\nstatic ( x )\n" ) == [ "<unattached>" ]
    assert _symbols( "/// Unnamed.\nextension on String {}\n" ) == [ "<unattached>" ]


def test_the_first_line_is_one_based_and_text_is_normalized():
    out = dp.extract_blocks( "\n\n/// First.  \n///\n///   - x\nvoid f() {}\n" )
    assert out == [ ( "f", 3, "First.\n\n  - x" ) ]


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    lib = tmp_path / "lib"
    lib.mkdir()
    ( lib / "kept.dart" ).write_text(
        f"/// {LONG}\nclass Kept {{\n  /// {LONG}\n  void changed() {{}}\n  /// {LONG}\n  void same() {{}}\n"
        f"  /// {LONG}\n  void gone() {{}}\n  /// {SHORT}\n  void tiny() {{}}\n}}\n", encoding="utf-8" )
    ( lib / "deleted.dart" ).write_text( f"/// {LONG}\nclass Deleted {{}}\n", encoding="utf-8" )
    ( lib / "notes.md" ).write_text( "not dart\n", encoding="utf-8" )
    ( tmp_path / "other.dart" ).write_text( f"/// {LONG}\nclass Other {{}}\n", encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "old" )
    old = _git( tmp_path, "rev-parse", "HEAD" )
    ( lib / "kept.dart" ).write_text(
        f"/// {LONG}\nclass Kept {{\n  /// Rewritten and much shorter.\n  void changed() {{}}\n  ///   {LONG.replace( ' ', '  ' )}\n  void same() {{}}\n"
        f"  /// {SHORT}\n  void tiny() {{}}\n}}\n", encoding="utf-8" )
    ( lib / "deleted.dart" ).unlink()
    ( lib / "added.dart" ).write_text( f"/// {LONG}\nclass Added {{}}\n", encoding="utf-8" )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "commit", "-qm", "new" )
    return tmp_path, old, _git( tmp_path, "rev-parse", "HEAD" )


def test_dart_files_comes_from_git_under_the_prefix_and_keeps_only_dart( repo ):
    root, old, new = repo
    assert dp.dart_files( root, old ) == [ "lib/deleted.dart", "lib/kept.dart" ]
    assert dp.dart_files( root, new ) == [ "lib/added.dart", "lib/kept.dart" ]
    assert dp.dart_files( root, old, prefix="." ) == [ "lib/deleted.dart", "lib/kept.dart", "other.dart" ]


def test_dart_files_names_the_git_error_on_a_bad_revision( repo ):
    with pytest.raises( RuntimeError, match="git ls-tree nope failed" ):
        dp.dart_files( repo[ 0 ], "nope" )


def test_build_pairs_pairs_the_changed_block_and_reports_every_drop( repo ):
    root, old, new = repo
    pairs, report = dp.build_pairs( root, old, new )
    assert [ p[ "id" ] for p in pairs ] == [ "lib/kept.dart::Kept.changed" ]
    assert pairs[ 0 ][ "old" ] == f"{LONG}" and pairs[ 0 ][ "new" ] == "Rewritten and much shorter."
    assert pairs[ 0 ][ "file" ] == "lib/kept.dart" and pairs[ 0 ][ "symbol" ] == "Kept.changed" and pairs[ 0 ][ "linked_doc" ] is None
    assert pairs[ 0 ][ "changed" ] is True
    assert report == { "files_old" : 2, "files_new" : 2, "files_only_old" : [ "lib/deleted.dart" ], "files_only_new" : [ "lib/added.dart" ],
                       "blocks_old" : 6, "blocks_new" : 5, "eligible_old" : 5, "below_min_words" : 1,
                       "dropped_file_deleted" : 1, "dropped_symbol_gone" : 1, "dropped_unchanged" : 2,
                       "paired_plain_comment" : 0, "paired_no_comment" : 0, "pairs" : 1,
                       "dropped_comment_lines" : { "directive" : 0, "marker" : 0, "after_marker" : 0 }, "pairs_with_dropped_comment_lines" : 0 }


def test_the_class_block_of_a_changed_file_is_unchanged_and_the_whitespace_only_rewrite_is_dropped( repo ):
    root, old, new = repo
    pairs, _ = dp.build_pairs( root, old, new, include_unchanged=True )
    ids = [ p[ "id" ] for p in pairs ]
    assert ids == [ "lib/kept.dart::Kept", "lib/kept.dart::Kept.changed", "lib/kept.dart::Kept.same" ]
    assert dp.squash( next( p for p in pairs if p[ "symbol" ] == "Kept.same" )[ "new" ] ) == LONG
    assert { p[ "symbol" ] : p[ "changed" ] for p in pairs } == { "Kept" : False, "Kept.changed" : True, "Kept.same" : False }


def test_min_words_decides_which_old_blocks_are_eligible( repo ):
    root, old, new = repo
    _, low = dp.build_pairs( root, old, new, min_words=1 )
    assert low[ "eligible_old" ] == 6
    _, high = dp.build_pairs( root, old, new, min_words=36 )
    assert high[ "eligible_old" ] == 0 and high[ "pairs" ] == 0


def test_a_block_of_exactly_min_words_is_eligible_and_one_word_less_is_not( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "lib" ).mkdir()
    thirty, twenty_nine = " ".join( f"w{i}" for i in range( 30 ) ), " ".join( f"w{i}" for i in range( 29 ) )
    ( tmp_path / "lib" / "a.dart" ).write_text( f"/// {thirty}\nclass Edge {{}}\n\n/// {twenty_nine}\nclass Under {{}}\n", encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "old" )
    old = _git( tmp_path, "rev-parse", "HEAD" )
    ( tmp_path / "lib" / "a.dart" ).write_text( "/// Short.\nclass Edge {}\n\n/// Short.\nclass Under {}\n", encoding="utf-8" )
    _git( tmp_path, "commit", "-qam", "new" )
    pairs, report = dp.build_pairs( tmp_path, old, "HEAD", min_words=30 )
    assert [ p[ "symbol" ] for p in pairs ] == [ "Edge" ]
    assert report[ "eligible_old" ] == 1


def test_the_prefix_limits_the_population( repo ):
    root, old, new = repo
    _, report = dp.build_pairs( root, old, new, prefix="nowhere" )
    assert report[ "files_old" ] == 0 and report[ "pairs" ] == 0


def test_main_writes_the_jsonl_prints_the_report_and_the_rows_load_with_a_key( repo, tmp_path ):
    root, old, new = repo
    dest = tmp_path / "out.jsonl"
    buf = io.StringIO()
    assert dp.main( [ "--repo-root", str( root ), "--old", old, "--new", new, "--out", str( dest ) ], buf ) == 0
    assert json.loads( buf.getvalue() )[ "pairs" ] == 1
    rows = [ json.loads( line ) for line in dest.read_text( encoding="utf-8" ).split( "\n" ) if line ]
    assert [ r[ "id" ] for r in rows ] == [ "lib/kept.dart::Kept.changed" ]
    keys = tmp_path / "dev-keys.jsonl"
    keys.write_text( json.dumps( { "id" : rows[ 0 ][ "id" ], "seeded_positive" : True, "x_span_in_old" : "word3 word4" } ) + "\n", encoding="utf-8" )
    loaded = load_pairs( dest, keys )
    assert len( loaded ) == 1 and loaded[ 0 ][ "design" ] is None
    start, end = loaded[ 0 ][ "seed_span" ]
    assert loaded[ 0 ][ "old" ][ start : end ] == "word3 word4"


def test_main_without_out_only_prints_and_include_unchanged_keeps_the_unchanged_pairs( repo ):
    root, old, new = repo
    buf = io.StringIO()
    dp.main( [ "--repo-root", str( root ), "--old", old, "--new", new, "--include-unchanged", "--min-words", "30", "--prefix", "lib" ], buf )
    assert json.loads( buf.getvalue() )[ "pairs" ] == 3


def test_write_jsonl_keeps_non_ascii_text_as_written( tmp_path ):
    dest = tmp_path / "x.jsonl"
    dp.write_jsonl( [ { "id" : "a", "old" : "naïve — ok" } ], dest )
    assert dest.read_text( encoding="utf-8" ) == '{"id": "a", "old": "naïve — ok"}\n'
