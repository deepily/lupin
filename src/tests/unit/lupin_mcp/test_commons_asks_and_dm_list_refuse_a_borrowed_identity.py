#!/usr/bin/env python3
"""
The two commons asks and dm_list, driven under a guessed identity.

The guard file's own loop already covers these three through their impl symbols.
This file adds the seam each one reads first. A commons ask signs the question as the resolved seat.
`dm_list` asks the server for the resolved seat's inbox, so a guessed identity would read a colleague's mail.
Each tool is called with valid arguments and must return the refusal before the store or server is asked.

Venue: :7999-eligible. No server, no network, no writes.
"""
import pytest

from lupin_mcp import cosa_voice_mcp as m
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class _Reached( Exception ):
    """Raised by a stubbed seam. Its arrival is the assertion that the guard let go."""


def _boom( *a, **k ):
    raise _Reached( "reached" )


def _call( tool, **kwargs ):
    import asyncio, inspect
    result = getattr( m, tool ).fn( **kwargs )
    return asyncio.run( result ) if inspect.iscoroutine( result ) else result


CASES = [
    ( "commons_ask_sync",  "_get_commons_store", { "topic": "help-wanted", "body": "q" } ),
    ( "commons_ask_async", "_get_commons_store", { "topic": "help-wanted", "body": "q" } ),
    ( "dm_list",           "_mcp_outbound_api_key", { } ),
]


@pytest.mark.parametrize( "tool,seam,kwargs", CASES, ids = [ c[ 0 ] for c in CASES ] )
def test_a_guessed_identity_is_refused_before_the_store_or_server_is_asked( tool, seam, kwargs, monkeypatch ):
    monkeypatch.setattr( m, "_commons_enabled", lambda: True )
    monkeypatch.setattr( m, seam, _boom )
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_CWD_FALLBACK )

    result = _call( tool, **kwargs )

    assert result[ "reason" ] == "borrowed_identity" and tool in result[ "detail" ]


@pytest.mark.parametrize( "tool,seam,kwargs", CASES, ids = [ c[ 0 ] for c in CASES ] )
def test_NEGATIVE_CONTROL_a_definitive_identity_reaches_the_seam( tool, seam, kwargs, monkeypatch ):
    monkeypatch.setattr( m, "_commons_enabled", lambda: True )
    monkeypatch.setattr( m, seam, _boom )
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_PPID )

    with pytest.raises( _Reached ):
        _call( tool, **kwargs )
