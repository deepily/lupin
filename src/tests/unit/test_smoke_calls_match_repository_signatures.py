"""
Unit tests: smoke and integration calls name only real NotificationRepository parameters.

Commit 32bf761ae gave the date-grouping methods a required timezone_name.
It also added the keyword to a get_sender_conversation call, which has no such parameter.
The smoke file only runs on :8000, so the host never noticed.
"""
import ast
import inspect
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.rest.db.repositories.notification_repository import NotificationRepository

_ROOT = cu.get_project_root()
_DIRS = [ "src/tests/smoke", "src/tests/integration" ]


def _test_files():
    """Tracked smoke and integration files that name NotificationRepository."""
    out   = subprocess.run( [ "git", "ls-files" ] + _DIRS, cwd=_ROOT, capture_output=True, text=True, check=True ).stdout
    paths = [ p for p in out.splitlines() if p.endswith( ".py" ) ]
    return [ p for p in paths if "NotificationRepository" in open( f"{_ROOT}/{p}", encoding="utf-8" ).read() ]


def _bad_keywords( source, filename="<src>" ):
    """List each keyword that a repository call passes and the method lacks."""
    bad = []
    for node in ast.walk( ast.parse( source, filename ) ):
        if not isinstance( node, ast.Call ) or not isinstance( node.func, ast.Attribute ): continue
        method = vars( NotificationRepository ).get( node.func.attr )
        if not callable( method ): continue
        params = inspect.signature( method ).parameters
        if any( p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values() ): continue
        for kw in node.keywords:
            if kw.arg is not None and kw.arg not in params: bad.append( ( filename, node.lineno, node.func.attr, kw.arg ) )
    return bad


def test_the_scan_sees_the_files_it_is_meant_to_scan():
    assert "src/tests/smoke/test_acks_are_not_conversations.py" in _test_files()


def test_the_scanner_finds_a_keyword_the_method_does_not_take():
    """Positive control: the exact call shape that was red."""
    src = "repo.get_sender_conversation( a, b, anchor=x, timezone_name=z )"
    assert _bad_keywords( src ) == [ ( "<src>", 1, "get_sender_conversation", "timezone_name" ) ]


def test_the_scanner_passes_a_keyword_the_method_takes_and_skips_unrelated_calls():
    src = "repo.get_sender_conversations_by_date( a, b, timezone_name=z )\nfoo.bar( q=1 )\nbaz( timezone_name=1 )\nr.get_sender_conversation( a, b, **kw )"
    assert _bad_keywords( src ) == []


@pytest.mark.parametrize( "path", _test_files() )
def test_every_repository_call_in_smoke_and_integration_uses_real_parameters( path ):
    with open( f"{_ROOT}/{path}", encoding="utf-8" ) as f: source = f.read()
    assert _bad_keywords( source, path ) == []
