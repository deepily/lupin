"""BoundedCCClientBase._call_bounded: the shared bounded call."""
import asyncio
from dataclasses import dataclass

from cosa.agents.shared.bounded_cc_client import BoundedCCClientBase, BoundedCCCostEstimate


class _Text:
    def __init__( self, text ): self.text = text


class _Assistant:
    def __init__( self, content ): self.content = content


class _Result:
    is_error = False
    usage = { "input_tokens": 3, "output_tokens": 4 }
    total_cost_usd = 0.5
    stop_reason = "end_turn"


class _Options:
    def __init__( self, **kw ): self.kw = kw


@dataclass
class _Response:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    sdk_cost_usd: float
    raw_response: object


class _Cfg:
    model = "m"


class _Client( BoundedCCClientBase ):
    COST_ESTIMATE_CLASS = BoundedCCCostEstimate
    LABEL               = "TestClient"
    BANNER_FIELD        = "model"


def _run( client, steer, seen ):
    async def sdk_query( prompt, options ):
        seen.append( ( prompt, options ) )
        yield _Assistant( [ _Text( " hi " ) ] )
        yield _Result()
    sdk = ( _Options, sdk_query, _Assistant, _Text, _Result )
    return asyncio.run( client._call_bounded( "m", "SYS", "user", "kind", 0.9, steer, sdk, [], "default", 7, _Response ) )


def test_steer_is_folded_into_the_system_prompt_and_the_reply_is_wrapped( capsys ):
    seen = []
    client = _Client( _Cfg(), True, False, True )
    out = _run( client, lambda t: "BE CREATIVE" if t > 0.8 else "", seen )
    prompt, options = seen[ 0 ]
    assert prompt == "user" and options.kw == { "model": "m", "system_prompt": "SYS\n\nBE CREATIVE", "tools": [], "permission_mode": "default", "max_turns": 7 }
    assert out == _Response( "hi", "m", 3, 4, "end_turn", 0.5, None ) and client.cost_estimate.total_api_calls == 1
    printed = capsys.readouterr().out
    assert "[TestClient] sdk_query m for kind (max_turns=7)" in printed and "Response: 3 in, 4 out, sdk_cost_usd=$0.5000" in printed


def test_no_steer_leaves_the_prompt_alone_and_an_empty_prompt_becomes_none( capsys ):
    seen, client = [], _Client( _Cfg(), False, False, True )
    async def sdk_query( prompt, options ):
        seen.append( options )
        yield _Result()
    sdk = ( _Options, sdk_query, _Assistant, _Text, _Result )
    asyncio.run( client._call_bounded( "m", "", "u", "k", 0.1, lambda t: "", sdk, [], "default", 1, _Response ) )
    assert seen[ 0 ].kw[ "system_prompt" ] is None and capsys.readouterr().out == ""
