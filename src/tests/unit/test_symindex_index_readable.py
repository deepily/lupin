"""
Unit tests for index_readable and for the Dart-constructor exemption in wiki_lint.

index_readable is the one test every NOT_LUPIN_TREE site shares.
"""
import pathlib

import pytest

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex import paths
from cosa.repo.symindex import wiki_lint
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo, make_repo

REGISTERED = [ "lupin", "lupin-mobile" ]


@pytest.fixture
def data( monkeypatch, tmp_path ):
    """One data directory for every non-lupin repo.

    A published index is then found by default_out_dir.
    """
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    monkeypatch.setattr( paths, "registered_repo_names", lambda config=None: REGISTERED )
    return tmp_path / "data"


def _mobile( tmp_path, name="lupin-mobile", built=True ):
    root = make_repo( tmp_path / "repos", name )
    if built: sx_build.build( root, paths.default_out_dir( root ) )
    return root


def test_lupin_tree_is_readable_without_a_registration_or_a_built_index( data, tmp_path, monkeypatch ):
    monkeypatch.setattr( paths, "registered_repo_names", lambda config=None: [] )
    assert paths.index_readable( make_lupin_repo( tmp_path / "repos" ) ) is True


def test_registered_repo_with_a_built_index_is_readable( data, tmp_path ):
    assert paths.index_readable( _mobile( tmp_path ) ) is True


def test_registered_repo_without_a_built_index_is_refused( data, tmp_path ):
    assert paths.index_readable( _mobile( tmp_path, built=False ) ) is False


def test_unregistered_repo_is_refused_even_with_a_built_index( data, tmp_path ):
    stranger = _mobile( tmp_path, name="stranger" )
    assert sx_build.current_generation( paths.default_out_dir( stranger ) ) is not None       # the index is there
    assert paths.index_readable( stranger ) is False


def test_names_argument_overrides_the_ini_registry( data, tmp_path ):
    root = _mobile( tmp_path )
    assert paths.index_readable( root, names=[] ) is False and paths.index_readable( root, names=[ "lupin-mobile" ] ) is True


def test_registered_repo_names_reads_the_external_repos_key( monkeypatch ):
    class Cfg:
        def get( self, key, default=None, return_type=None ):
            assert key == "external repos" and return_type == "list-string"
            return [ " lupin ", "", "lupin-mobile" ]
    assert paths.registered_repo_names( Cfg() ) == [ "lupin", "lupin-mobile" ]
    monkeypatch.setattr( paths.storage_paths, "build_config", lambda: Cfg() )
    assert paths.registered_repo_names() == [ "lupin", "lupin-mobile" ]


def test_prepare_answers_for_a_mobile_index_and_refuses_the_others( data, tmp_path ):
    mobile = _mobile( tmp_path )
    flags, entries, sha_, gen = rt.prepare( rt.ReuseContext( mobile, tmp_path / "d1", transport=object() ) )
    assert "NOT_LUPIN_TREE" not in flags and entries and gen is not None
    for root in ( _mobile( tmp_path, built=False, name="lupin-mobile-2" ), _mobile( tmp_path, name="stranger" ) ):
        assert rt.prepare( rt.ReuseContext( root, tmp_path / "d2", transport=object() ) ) == ( { "NOT_LUPIN_TREE" }, [], "none", None )


# ── wiki_lint: a Dart constructor is covered when its class is pinned ───────

def _lint( monkeypatch, tmp_path, pinned ):
    ids   = [ "m:lib.a.Box", "m:lib.a.Box.Box", "m:lib.a.Box.Box.named", "m:lib.a.Other.Other", "m:lib.a.Other.Other.named" ]
    rows  = [ { "id": i, "pin": "0123456789", "kind": "class" if i.count( "." ) == 2 else "constructor" } for i in ids ]
    monkeypatch.setattr( wiki_lint, "read_symbols", lambda gen: rows )
    monkeypatch.setattr( wiki_lint, "read_header", lambda gen: { "pin_algorithm": "x" } )
    wiki = tmp_path / "wiki"; ( wiki / "capabilities" ).mkdir( parents=True )
    ( wiki / "INDEX.md" ).write_text( "- [[p]]\n", encoding="utf-8" )
    ( wiki / "capabilities" / "p.md" ).write_text( f"---\npin_algorithm: x\npins: {pinned}@0123456789\n---\n", encoding="utf-8" )
    return { f[ "symbol" ] for f in wiki_lint.queue( wiki, None ) if f[ "kind" ] == "orphan" }


def test_constructors_of_a_pinned_class_are_not_orphans( monkeypatch, tmp_path ):
    found = _lint( monkeypatch, tmp_path, "m:lib.a.Box" )
    assert "m:lib.a.Box.Box" not in found and "m:lib.a.Box.Box.named" not in found           # default and named, class pinned
    assert found == { "m:lib.a.Other.Other", "m:lib.a.Other.Other.named" }                    # an unpinned class's constructors still are
