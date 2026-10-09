#!/usr/bin/env python3
"""
Four wired tools with no `<tool>_impl` symbol, driven under a guessed identity.

The two speakerphone tools flip the resolved session's conversation mode and displace the session
that holds it. `request_persona` allocates a voice for the resolved session. `spawn_sessions` launches
real sessions parented to the resolved manager. Every identity-bearing tool refuses a guessed identity.

The guard file proves each refusal is the first statement. This file drives the assembled tools and
asserts what that check cannot: a refused call never reaches the body's first seam.
Each tool has a refuse arm and a negative control. The control carries the file,
because a tool that refused every call would pass the refuse arm.

Venue: :7999-eligible. Module globals are monkeypatched; no server, no network, no tmux, no writes.
"""
import pytest

from lupin_mcp import cosa_voice_mcp as m
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class _Reached( Exception ):
    """Raised by a stubbed seam. Its arrival is the assertion that the guard let go."""


# tool name, the module symbol its body reaches first, the arguments for an otherwise valid call
CASES = [
    ( "enable_speakerphone",  "_flip_speakerphone",  { } ),
    ( "disable_speakerphone", "_flip_speakerphone",  { } ),
    ( "request_persona",      "_request_persona",    { } ),
    ( "spawn_sessions",       "_wait_for_sender_id", { "count": 1, "task_prompt": "x" } ),
]
IDS = [ case[ 0 ] for case in CASES ]


def _arm( monkeypatch, seam, source ):
    def _sentinel( *a, **k ):
        raise _Reached( f"{seam} reached" )

    monkeypatch.setattr( m, seam, _sentinel )
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", source )


@pytest.mark.parametrize( "tool,seam,kwargs", CASES, ids = IDS )
def test_the_tool_REFUSES_and_never_reaches_its_first_seam( tool, seam, kwargs, monkeypatch ):
    _arm( monkeypatch, seam, sb.SOURCE_CWD_FALLBACK )

    result = getattr( m, tool ).fn( **kwargs )

    assert result[ "reason" ] == "borrowed_identity" and tool in result[ "detail" ]


@pytest.mark.parametrize( "tool,seam,kwargs", CASES, ids = IDS )
def test_NEGATIVE_CONTROL_a_definitive_identity_reaches_the_seam( tool, seam, kwargs, monkeypatch ):
    _arm( monkeypatch, seam, sb.SOURCE_PPID )

    with pytest.raises( _Reached ):
        getattr( m, tool ).fn( **kwargs )
