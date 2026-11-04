"""Edge-path tests for the dead R&D citation scanner.

Four paths no other dead_rnd_citation test reaches:

- cross_repo_names refuses an INI with no `external repos` key.
- _python_call_argument_lines returns an empty set for a file that does not parse.
- scan() counts a file that in_corpus rejects as skipped.
- scan_index_links reports a missing link target as dead.

Each runs against a synthetic repo or INI under tmp_path.
"""

import importlib.util
import os
import subprocess

import pytest

import cosa.utils.util as cu


def _load_scanner():
    """Ensures: returns dead_rnd_citations loaded from this tree via cu.get_project_root()."""
    path = os.path.join( cu.get_project_root(), "src", "scripts", "dead_rnd_citations.py" )
    spec = importlib.util.spec_from_file_location( "dead_rnd_citations_edges", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


drc = _load_scanner()


def _git_repo( root, files ):
    """Create a git repo at root with the given { relpath: text } committed (tracked)."""
    subprocess.run( [ "git", "-C", str( root ), "init", "-q" ], check=True )
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( text )
    subprocess.run( [ "git", "-C", str( root ), "add", "-A" ], check=True )


def test_cross_repo_names_refuses_an_ini_with_no_external_repos_key( tmp_path ):
    ini = tmp_path / "x.ini"
    ini.write_text( "# a comment\n[main]\nother key = 1\nno equals here\n" )
    with pytest.raises( ValueError, match="no `external repos` key" ):
        drc.cross_repo_names( str( ini ) )


def test_cross_repo_names_reads_the_key_when_present_and_drops_this_repo( tmp_path ):
    # positive control for the refusal above: the same parser DOES find a key when it exists
    ini = tmp_path / "x.ini"
    ini.write_text( "external repos = lupin, alpha-repo, beta\n" )
    names = drc.cross_repo_names( str( ini ) )
    assert "alpha-repo" in names and "beta" in names
    assert drc.THIS_REPO not in names
    assert "lupin-plugin-firefox" in names              # the unregistered sibling is always added


def test_a_file_that_does_not_parse_has_no_call_argument_lines():
    assert drc._python_call_argument_lines( "def broken(:\n    pass\n" ) == set()
    # positive control: a parsable file with a call-argument string DOES report its line
    assert drc._python_call_argument_lines( "f(\n    'src/rnd/a.md'\n)\n" ) == { 2 }


def test_scan_counts_a_file_in_corpus_rejects_as_skipped( tmp_path, monkeypatch ):
    _git_repo( tmp_path, { "keep.md": "see src/rnd/gone.md\n", "drop.md": "see src/rnd/gone2.md\n" } )
    monkeypatch.setattr( drc, "in_corpus", lambda rel: rel != "drop.md" )
    result = drc.scan( str( tmp_path ) )
    assert result[ "scanned" ] == [ "keep.md" ]
    assert result[ "skipped" ] == 1


def test_scan_index_links_names_the_dead_target_beside_the_live_one( tmp_path ):
    rnd = tmp_path / "src" / "rnd"
    rnd.mkdir( parents=True )
    ( rnd / "here.md" ).write_text( "x\n" )
    ( rnd / "README.md" ).write_text( "[ok](here.md) and [gone](missing.md)\n" )
    live, dead = drc.scan_index_links( str( tmp_path ) )
    assert live == 1
    assert dead == [ "missing.md" ]
