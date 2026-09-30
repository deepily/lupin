"""
The Dart extractor, tested with real parses and with fake-runner failure paths.

Real parses run fixture files through the real Dart analyzer; the failure paths use a fake
process runner.

The extractor contract and DependencyMissing come from the symbol-index package when it is
present; until that package lands in this tree the tests register minimal stand-ins that
follow the agreed contract, so the same tests run against either.
"""

import os
import sys
import types
from types import SimpleNamespace

import pytest

import cosa.utils.util as cu

try:
    from cosa.repo.symindex import errors, extractor_contract
except ImportError:
    errors = types.ModuleType( "cosa.repo.symindex.errors" )

    class DependencyMissing( Exception ):
        def __init__( self, what, detail="" ):
            super().__init__( f"{what} is missing" + ( f": {detail}" if detail else "" ) )
            self.what = what

    errors.DependencyMissing = DependencyMissing
    extractor_contract = types.ModuleType( "cosa.repo.symindex.extractor_contract" )
    KEYS = ( "lang", "file", "name", "kind", "sig", "doc", "line", "public" )

    def validate_record( rec ):
        for k in KEYS:
            if k not in rec: raise ValueError( f"missing {k}" )
        if "pin" not in rec and "pin_text" not in rec: raise ValueError( "no pin" )

    extractor_contract.validate_record = validate_record
    sys.modules[ "cosa.repo.symindex.errors" ]             = errors
    sys.modules[ "cosa.repo.symindex.extractor_contract" ] = extractor_contract

from cosa.repo.symindex import dart_extractor as de

FIXTURE = '''/// A generic box.
class Box<T extends num> extends Base {
  /// Builds one.
  Box( this.value );
  Box.named( int v ) : value = v as T;
  factory Box.of( T v ) => Box( v );
  final T value;
  /// Doubles it.
  T twice<R>( Map<String, List<R>> m, { required int n }) => value;
  int get size => 1;
  set size( int v ) {}
  bool _hidden() => true;
}

mixin Loud on Base { void shout() {} }

enum Color { red, green; String get label => name; }

extension Shout on String { String get loud => toUpperCase(); }
extension on int { int get twice => this * 2; }
extension type Id( int v ) { int get plus => v + 1; }
typedef Cb = void Function( int );

/// Top level.
List<T> mapRows<T>( List<T> rows ) => rows;
String get _secret => "x";
'''


def _find_dart():
    override = os.environ.get( "LUPIN_DART" )
    if override and os.path.exists( override ): return override
    here = os.path.abspath( cu.get_project_root() )
    while here != os.path.dirname( here ):
        candidate = os.path.join( here, "lupin-mobile", "flutter", "bin", "dart" )
        if os.path.exists( candidate ): return candidate
        here = os.path.dirname( here )
    return None


@pytest.fixture( scope="module" )
def dart():
    path = _find_dart()
    if path is None: pytest.fail( "no dart SDK found: set LUPIN_DART or keep ../lupin-mobile/flutter beside the lupin checkout" )
    return path


@pytest.fixture
def mobile( tmp_path, dart, monkeypatch ):
    monkeypatch.setenv( "LUPIN_DART", dart )
    root = tmp_path / "mobile"
    ( root / "lib" ).mkdir( parents=True )
    ( root / "lib" / "a.dart" ).write_text( FIXTURE, encoding="utf-8" )
    return SimpleNamespace( root=root, data=tmp_path / "data", file=root / "lib" / "a.dart" )


def _snapshot( root ):
    return sorted( ( os.path.join( d, f ), os.stat( os.path.join( d, f ) ).st_mtime_ns ) for d, _, fs in os.walk( root ) for f in fs )


def _by_name( records ):
    return { r[ "name" ]: r for r in records }


def test_fixture_declarations_come_back_with_kind_signature_doc_line_and_visibility( mobile ):
    records = _by_name( de.extract_dart( mobile.root, [ mobile.file ], mobile.data ) )
    assert [ r[ "name" ] for r in records.values() ] == [
        "Box", "Box.Box", "Box.Box.named", "Box.Box.of", "Box.twice", "Box.get size", "Box.set size", "Box._hidden",
        "Loud", "Loud.shout", "Color", "Color.get label", "Shout", "Shout.get loud",
        "extension_on_int", "extension_on_int.get twice", "Id", "Id.get plus", "mapRows", "get _secret" ]
    assert ( records[ "Box" ][ "kind" ], records[ "Box" ][ "sig" ], records[ "Box" ][ "doc" ], records[ "Box" ][ "line" ] ) == ( "class", "", "A generic box.", 2 )
    assert ( records[ "Box.twice" ][ "kind" ], records[ "Box.twice" ][ "sig" ], records[ "Box.twice" ][ "doc" ] ) == ( "method", "<R>(Map<String, List<R>> m, {required int n}): T", "Doubles it." )
    assert records[ "Box.Box.named" ][ "kind" ] == "constructor" and records[ "Box.Box.of" ][ "kind" ] == "constructor"
    assert records[ "mapRows" ][ "kind" ] == "function" and records[ "mapRows" ][ "doc" ] == "Top level."
    assert ( records[ "Loud" ][ "kind" ], records[ "Color" ][ "kind" ], records[ "Shout" ][ "kind" ], records[ "extension_on_int" ][ "kind" ] ) == ( "mixin", "enum", "extension", "extension" )
    assert ( records[ "Box._hidden" ][ "public" ], records[ "get _secret" ][ "public" ], records[ "Box.Box" ][ "public" ], records[ "Box" ][ "public" ] ) == ( False, False, True, True )
    assert all( r[ "lang" ] == "dart" and r[ "file" ] == "lib/a.dart" for r in records.values() )


def test_a_comment_or_whitespace_edit_keeps_the_pin_text_and_a_token_edit_changes_it( mobile ):
    before = _by_name( de.extract_dart( mobile.root, [ mobile.file ], mobile.data ) )
    mobile.file.write_text( FIXTURE.replace( "/// Doubles it.", "/// Doubles it, differently worded.\n  // and a plain comment" ).replace( "T twice<R>(", "T   twice<R>(" ), encoding="utf-8" )
    after = _by_name( de.extract_dart( mobile.root, [ mobile.file ], mobile.data ) )
    assert after[ "Box.twice" ][ "pin_text" ] == before[ "Box.twice" ][ "pin_text" ] and after[ "Box.twice" ][ "doc" ] == "Doubles it, differently worded."
    mobile.file.write_text( FIXTURE.replace( "=> value;", "=> value + 1;" ), encoding="utf-8" )
    changed = _by_name( de.extract_dart( mobile.root, [ mobile.file ], mobile.data ) )
    assert changed[ "Box.twice" ][ "pin_text" ] != before[ "Box.twice" ][ "pin_text" ]
    assert changed[ "Box.get size" ][ "pin_text" ] == before[ "Box.get size" ][ "pin_text" ]


def test_nothing_is_written_under_the_index_root_and_the_scratch_project_lives_in_the_data_root( mobile ):
    before = _snapshot( mobile.root )
    de.extract_dart( mobile.root, [ mobile.file ], mobile.data )
    assert _snapshot( mobile.root ) == before
    assert ( mobile.data / de.SCRATCH_NAME / "pubspec.yaml" ).exists() and ( mobile.data / de.SCRATCH_NAME / ".dart_tool" / "package_config.json" ).exists()


def test_a_file_that_is_not_valid_utf8_does_not_lose_the_other_files( mobile ):
    bad = mobile.root / "lib" / "bad.dart"
    bad.write_bytes( b"/// caf\xe9\nclass Latin {}\n" )
    names = [ r[ "name" ] for r in de.extract_dart( mobile.root, [ bad, mobile.file ], mobile.data ) ]
    assert "Latin" in names and "Box" in names


def test_no_files_means_no_records_and_no_dart_lookup( monkeypatch, tmp_path ):
    monkeypatch.setattr( de, "find_dart", lambda root: pytest.fail( "dart must not be looked up" ) )
    assert de.extract_dart( tmp_path, [], tmp_path ) == []


def test_a_missing_dart_raises_dependency_missing_and_never_returns_an_empty_index( monkeypatch, tmp_path ):
    monkeypatch.delenv( "LUPIN_DART", raising=False )
    monkeypatch.setattr( de.shutil, "which", lambda name: None )
    with pytest.raises( errors.DependencyMissing ) as caught:
        de.extract_dart( tmp_path, [ tmp_path / "a.dart" ], tmp_path / "data" )
    assert caught.value.what == "dart"


def test_find_dart_prefers_the_override_then_the_bundled_sdk_then_the_search_path( monkeypatch, tmp_path ):
    bundled = tmp_path / "flutter" / "bin" / "dart"
    bundled.parent.mkdir( parents=True )
    bundled.write_text( "x", encoding="utf-8" )
    override = tmp_path / "override"
    override.write_text( "x", encoding="utf-8" )
    monkeypatch.setattr( de.shutil, "which", lambda name: "/on/path/dart" )
    monkeypatch.delenv( "LUPIN_DART", raising=False )
    assert de.find_dart( tmp_path ) == str( bundled )
    monkeypatch.setenv( "LUPIN_DART", str( override ) )
    assert de.find_dart( tmp_path ) == str( override )
    monkeypatch.setenv( "LUPIN_DART", str( tmp_path / "gone" ) )
    assert de.find_dart( tmp_path ) == str( bundled )
    bundled.unlink()
    assert de.find_dart( tmp_path ) == "/on/path/dart"


def _runner( results ):
    calls = []
    def run( cmd, **kwargs ):
        calls.append( cmd )
        return results.pop( 0 )
    run.calls = calls
    return run


def test_pub_get_runs_offline_first_then_online_and_is_skipped_when_nothing_changed( tmp_path ):
    ok, bad = SimpleNamespace( returncode=0, stdout="", stderr="" ), SimpleNamespace( returncode=1, stdout="", stderr="offline failed" )
    runner = _runner( [ bad, ok ] )
    scratch = de.prepare_scratch( "dart", tmp_path, runner )
    assert [ c[ 3: ] for c in runner.calls ] == [ [ "--offline" ], [] ]
    ( scratch_path := __import__( "pathlib" ).Path( scratch ) / ".dart_tool" ).mkdir()
    ( scratch_path / "package_config.json" ).write_text( "{}", encoding="utf-8" )
    again = _runner( [] )
    assert de.prepare_scratch( "dart", tmp_path, again ) == scratch and again.calls == []


def test_pub_get_failing_both_ways_raises_dependency_missing_naming_the_analyzer( tmp_path ):
    bad = SimpleNamespace( returncode=1, stdout="", stderr="no network" )
    with pytest.raises( errors.DependencyMissing ) as caught:
        de.prepare_scratch( "dart", tmp_path, _runner( [ bad, bad ] ) )
    assert "analyzer 7.7.1" in caught.value.what and "no network" in str( caught.value )


def test_a_failing_extractor_script_raises_runtime_error_with_its_stderr( monkeypatch, tmp_path ):
    monkeypatch.setattr( de, "find_dart", lambda root: "dart" )
    monkeypatch.setattr( de, "prepare_scratch", lambda dart, data_root, runner: str( tmp_path ) )
    crash = SimpleNamespace( returncode=255, stdout="", stderr="Unhandled exception: boom" )
    with pytest.raises( RuntimeError, match="exit 255.*boom" ):
        de.extract_dart( tmp_path, [ tmp_path / "a.dart" ], tmp_path, _runner( [ crash ] ) )


def test_records_failing_the_contract_are_rejected( monkeypatch, tmp_path ):
    monkeypatch.setattr( de, "find_dart", lambda root: "dart" )
    monkeypatch.setattr( de, "prepare_scratch", lambda dart, data_root, runner: str( tmp_path ) )
    out = SimpleNamespace( returncode=0, stdout='[{"file": "a.dart", "name": "x"}]', stderr="" )
    with pytest.raises( ValueError ):
        de.extract_dart( tmp_path, [ tmp_path / "a.dart" ], tmp_path, _runner( [ out ] ) )


def test_write_if_changed_reports_whether_it_wrote( tmp_path ):
    target = str( tmp_path / "f.txt" )
    assert de._write_if_changed( target, "a" ) is True
    assert de._write_if_changed( target, "a" ) is False
    assert de._write_if_changed( target, "b" ) is True


def test_the_pin_algorithm_names_the_parser_and_its_version():
    assert de.PIN_ALGORITHM == "dart-analyzer-parseString/7.7.1"
