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


def _run( client, steer, seen, system="SYS" ):
    async def sdk_query( prompt, options ):
        seen.append( ( prompt, options ) )
        yield _Assistant( [ _Text( " hi " ) ] )
        yield _Result()
    sdk = ( _Options, sdk_query, _Assistant, _Text, _Result )
    return asyncio.run( client._call_bounded( "m", system, "user", "kind", 0.9, steer, sdk, [], "default", 7, _Response ) )


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


def test_an_empty_system_prompt_with_a_steer_gives_exactly_the_steer_text():
    seen = []
    _run( _Client( _Cfg(), False, False, True ), lambda t: "BE CREATIVE", seen, system="" )
    assert seen[ 0 ][ 1 ].kw[ "system_prompt" ] == "BE CREATIVE"


def _options_of( module, client ):
    """Drive client._call_api against a stub sdk_query and return the options it was built with."""
    from unittest.mock import patch
    seen = []

    async def sdk_query( prompt, options ):
        seen.append( options )
        yield _Result()

    with patch.multiple( module, ResultMessage=_Result, AssistantMessage=_Assistant, TextBlock=_Text ), patch.object( module, "sdk_query", sdk_query ):
        asyncio.run( client._call_api( model="m", system_prompt="SYS", user_message="hi", call_type="t" ) )
    return seen[ 0 ]


def test_the_podcast_wrapper_passes_its_own_tools_permission_mode_and_script_turns():
    import cosa.agents.podcast_generator.api_client as ac
    client = ac.PodcastAPIClient()
    client.config.script_max_turns = 7
    options = _options_of( ac, client )
    assert options.tools == ac.PODCAST_SCRIPT_TOOLS and options.permission_mode == ac.PODCAST_PERMISSION_MODE and options.max_turns == 7


def test_the_presentation_wrapper_passes_its_own_tools_permission_mode_and_content_turns():
    import cosa.agents.presentation_generator.api_client as ac
    client = ac.PresentationAPIClient()
    client.config.content_max_turns = 9
    options = _options_of( ac, client )
    assert options.tools == ac.PRESENTATION_CONTENT_TOOLS and options.permission_mode == ac.PRESENTATION_PERMISSION_MODE and options.max_turns == 9
