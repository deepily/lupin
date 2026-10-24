"""
Member text for the need set: stripped names, raw bodies and named failures.
"""
import pathlib
import re

import pytest

from cosa.repo.symindex import js_index
from cosa.repo.symindex import spec as sp
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import strip

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )
JS_FILE   = "src/lupin_app/static/js/notifications.js"
JS_NAME   = "ccConsoleCanWatch"


@pytest.fixture( autouse=True )
def _typescript_lookup( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def js_line( name ):
    """Return the 1-based line where a top-level function of the monolith starts."""
    lines = ( REPO_ROOT / JS_FILE ).read_text( encoding="utf-8" ).splitlines()
    return next( i for i, l in enumerate( lines, 1 ) if l.startswith( f"function {name}(" ) )


PY_FUNCTION = { "id": "cosa.repo.symindex.dups.jaccard", "file": "src/cosa/repo/symindex/dups.py", "name": "jaccard", "lang": "py", "line": 0 }
PY_METHOD   = { "id": "cosa.repo.symindex.spec.IndexSpec.__init__", "file": "src/cosa/repo/symindex/spec.py", "name": "IndexSpec.__init__", "lang": "py", "line": 0 }


def monolith():
    """Return the index record of the monolith function."""
    return { "id": "src.lupin_app.static.js.notifications." + JS_NAME, "file": JS_FILE, "name": JS_NAME, "lang": "ts", "line": js_line( JS_NAME ) }


def whole_word( name, text ):
    """Say whether a name appears in text as a whole identifier."""
    return re.search( r"(?<![A-Za-z0-9_$])" + re.escape( name ) + r"(?![A-Za-z0-9_$])", text ) is not None


@pytest.mark.parametrize( "rec, kind", [ ( PY_FUNCTION, "function" ), ( PY_METHOD, "method" ), ( None, "function" ) ], ids=[ "python function", "python method", "monolith function" ] )
def test_a_real_member_strips_to_text_without_its_own_names( rec, kind ):
    rec  = monolith() if rec is None else rec
    got  = strip.strip_member( rec, REPO_ROOT )
    raw  = strip.bodies_for( [ rec ], REPO_ROOT )[ rec[ "id" ] ]
    assert got[ "kind" ] == kind
    assert got[ "forbidden" ], "a member with a name, parameters or a class has names to remove"
    assert not any( whole_word( n, got[ "text" ] ) for n in got[ "forbidden" ] )
    assert any( whole_word( n, raw ) for n in got[ "forbidden" ] ), "positive control: the unstripped text holds them"
    assert rec[ "name" ].split( "." )[ -1 ] in got[ "forbidden" ] or rec[ "name" ].endswith( "__init__" )


def test_the_monolith_member_keeps_its_doc_comment_and_names_become_placeholders():
    got = strip.strip_member( monolith(), REPO_ROOT )
    assert "NAME" in got[ "text" ] or "ARG1" in got[ "text" ]
    assert JS_NAME in strip.bodies_for( [ monolith() ], REPO_ROOT )[ monolith()[ "id" ] ]


def test_mixed_records_come_back_together_and_script_members_share_one_node_start( monkeypatch ):
    starts = []
    real   = js_index._run
    monkeypatch.setattr( js_index, "_run", lambda *a, **k: starts.append( k[ "script" ] ) or real( *a, **k ) )
    other  = dict( monolith(), name="ccConsoleBuildPageHref", id="src.lupin_app.static.js.notifications.ccConsoleBuildPageHref", line=js_line( "ccConsoleBuildPageHref" ) )
    recs   = [ monolith(), PY_FUNCTION, other ]
    assert sorted( strip.bodies_for( recs, REPO_ROOT ) ) == sorted( r[ "id" ] for r in recs )
    assert sorted( strip.strip_members( recs, REPO_ROOT ) ) == sorted( r[ "id" ] for r in recs )
    assert starts == [ strip.STRIP_SCRIPT, strip.STRIP_SCRIPT ]


def test_python_only_records_never_start_node( monkeypatch ):
    monkeypatch.setattr( js_index, "_run", lambda *a, **k: pytest.fail( "node was started for Python records" ) )
    assert strip.script_results( REPO_ROOT, [], strip.MODE_TEXT ) == []
    assert list( strip.strip_members( [ PY_FUNCTION ], REPO_ROOT ) ) == [ PY_FUNCTION[ "id" ] ]


def test_module_and_source_root_come_from_the_id_and_the_file():
    assert strip.module_of( PY_METHOD ) == "cosa.repo.symindex.spec"
    assert strip.module_of( { "id": "a.b.f#2", "name": "f" } ) == "a.b"
    assert strip.dotted_id( { "id": "a.b.f#2" } ) == "a.b.f"
    assert strip.src_root_of( "/r", PY_FUNCTION ) == pathlib.Path( "/r/src" )
    assert strip.src_root_of( "/r", { "id": "mod.f", "name": "f", "file": "mod.py" } ) == pathlib.Path( "/r" )
    assert strip.src_root_of( "/r", { "id": "pkg.f", "name": "f", "file": "pkg/__init__.py" } ) == pathlib.Path( "/r" )


def test_a_python_member_that_cannot_be_found_is_strip_failed_by_name( tmp_path ):
    ( tmp_path / "bad.py" ).write_text( "def (:\n", encoding="utf-8" )
    ( tmp_path / "ok.py" ).write_text( "def here():\n    return 1\n", encoding="utf-8" )
    for rec in ( { "id": "ghost.f", "name": "f", "file": "ghost.py", "lang": "py" }, { "id": "bad.f", "name": "f", "file": "bad.py", "lang": "py" },
                 { "id": "ok.absent", "name": "absent", "file": "ok.py", "lang": "py" } ):
        for call in ( strip.strip_members, strip.bodies_for ):
            with pytest.raises( er.NeedsetError ) as e: call( [ rec ], tmp_path )
            assert e.value.code == er.STRIP_FAILED and rec[ "id" ] in e.value.detail


def test_a_script_member_that_cannot_be_found_is_strip_failed_by_name():
    wrong_line = dict( monolith(), line=1 )
    no_file    = { "id": "nofile.f", "name": "f", "file": "src/lupin_app/static/js/no-such-file.js", "lang": "ts", "line": 1 }
    for rec, words in ( ( wrong_line, "starts on line 1" ), ( no_file, "no such file" ) ):
        with pytest.raises( er.NeedsetError ) as e: strip.script_results( REPO_ROOT, [ rec ], strip.MODE_TEXT )
        assert e.value.code == er.STRIP_FAILED and words in e.value.detail and rec[ "id" ] in e.value.detail


def test_decorators_are_part_of_a_python_members_raw_body( tmp_path ):
    ( tmp_path / "deco.py" ).write_text( "import functools\n\n\n@functools.cache\ndef cached( aaa ):\n    return aaa\n", encoding="utf-8" )
    rec = { "id": "deco.cached", "file": "deco.py", "name": "cached", "lang": "py", "line": 5 }
    assert strip.bodies_for( [ rec ], tmp_path )[ rec[ "id" ] ].startswith( "@functools.cache\ndef cached" )


def test_a_script_members_module_parts_are_stripped_from_its_text( tmp_path ):
    ( tmp_path / "util" ).mkdir()
    ( tmp_path / "util" / "helpers.ts" ).write_text( "export function helperThing( aaa: number ) { return helpers + aaa; }\n", encoding="utf-8" )
    rec = { "id": "util.helpers.helperThing", "file": "util/helpers.ts", "name": "helperThing", "lang": "ts", "line": 1 }
    got = strip.strip_member( rec, tmp_path )
    assert "helpers" in got[ "forbidden" ] and got[ "text" ] == "export function NAME( ARG1: number ) { return MODULE + ARG1; }"
