"""
Unit tests for cosa/orchestration/claude_code/dispatcher.py.

Covers Task / TaskResult / TaskType / SessionInfo and the full
ClaudeCodeDispatcher surface: dispatch routing, _run_bounded (async subprocess,
fully faked), _run_interactive (SDK client, fully faked), inject / interrupt /
end_session / get_active_sessions, _default_message_handler, and the async
main() CLI entry point.

Isolation contract:
    - NO real subprocess: `asyncio.create_subprocess_exec` is replaced by an
      in-process `_FakeAsyncProcess` (async-iterable stdout, async stderr/wait).
    - NO real Claude Agent SDK calls: `ClaudeSDKClient` / `ClaudeAgentOptions`
      and the message-type classes are monkeypatched with in-process doubles.
    - NO env leakage: LUPIN_ROOT is set/cleared via monkeypatch only.
    - ZERO API spend, ZERO network, ZERO server contact.

TRIPWIRE (confirmed PROD BUG, NOT fixed here): `_run_interactive` reads
`self.debug` (dispatcher.py:468) on a RateLimitEvent, but `ClaudeCodeDispatcher.
__init__` never initializes `self.debug` → AttributeError. Per campaign doctrine
the bug is NOT fixed: `test_run_interactive_rate_limit_event_is_prod_bug` PINS the
current (raising→absorbed-as-failure) behavior; the manager owns the source fix
(add a `debug` attr) + this pin's removal.

The quick_smoke_test() + `if __name__ == "__main__":` block is MARKED FOR DELETION
(campaign-end consolidated cleanup); it is already coverage-excluded via the repo
exclude_also regex. `async def main()` is NOT excluded and is tested below.
"""
import asyncio

import pytest

import cosa.orchestration.claude_code.dispatcher as disp
from cosa.orchestration.claude_code.dispatcher import (
    Task, TaskType, TaskResult, ClaudeCodeDispatcher,
)


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _AsyncLineReader:
    """Async-iterable stand-in for process.stdout yielding scripted byte lines."""
    def __init__( self, lines ):
        self._lines = list( lines )

    def __aiter__( self ):
        return self

    async def __anext__( self ):
        if self._lines:
            return self._lines.pop( 0 )
        raise StopAsyncIteration


class _AsyncStderr:
    """Async stand-in for process.stderr.read()."""
    def __init__( self, data=b"" ):
        self._data = data

    async def read( self ):
        return self._data


class _FakeAsyncProcess:
    """Stand-in for asyncio.create_subprocess_exec's return value."""
    def __init__( self, stdout_lines, returncode=0, stderr=b"", pid=4242 ):
        self.stdout     = _AsyncLineReader( stdout_lines )
        self.stderr     = _AsyncStderr( stderr )
        self.returncode = returncode
        self.pid        = pid
        self.killed     = False

    async def wait( self ):
        return self.returncode

    def kill( self ):
        self.killed = True


def _patch_create_subprocess( monkeypatch, process ):
    """Replace asyncio.create_subprocess_exec with one returning `process`."""
    async def _fake( *a, **k ):
        return process
    monkeypatch.setattr( disp.asyncio, "create_subprocess_exec", _fake )


# --- SDK doubles ----------------------------------------------------------- #
class _FakeTextBlock:
    def __init__( self, text ): self.text = text


class _FakeBlock:
    """Generic content block; has `.text` only when given one."""
    def __init__( self, text=None ):
        if text is not None:
            self.text = text


class _FakeAssistantMessage:
    def __init__( self, content ): self.content = content


class _FakeResultMessage:
    def __init__( self, session_id="s1", result="done", total_cost_usd=0.01, duration_ms=42 ):
        self.session_id     = session_id
        self.result         = result
        self.total_cost_usd = total_cost_usd
        self.duration_ms    = duration_ms


class _FakeRateLimitEvent:
    def __init__( self, retry_after=5 ): self.retry_after = retry_after


class _FakeSDKClient:
    """Async-context SDK client double.

    Class-level config (one client per test):
        RESPONSE_BATCHES: list[list[message]] — yielded per receive_response() call
        INJECT: dict[int, str]                — call-idx → message to enqueue into
                                                 the live session's pending queue
        DISPATCHER: the dispatcher under test (to reach active_sessions)
        AENTER_RAISES / QUERY_RAISES: exception to raise (or None)
    """
    RESPONSE_BATCHES      = []
    INJECT                = {}
    DISPATCHER            = None
    AENTER_RAISES         = None
    QUERY_RAISES          = None
    STOP_RUNNING_ON_CALL  = set()   # call-idxs after which to flip every session's running→False

    def __init__( self, options=None ):
        self.options     = options
        self.queries     = []
        self.interrupted = 0
        self._call       = 0

    async def __aenter__( self ):
        if type( self ).AENTER_RAISES is not None:
            raise type( self ).AENTER_RAISES
        return self

    async def __aexit__( self, *exc ):
        return False

    async def query( self, prompt ):
        if type( self ).QUERY_RAISES is not None:
            raise type( self ).QUERY_RAISES
        self.queries.append( prompt )

    async def interrupt( self ):
        self.interrupted += 1

    async def _gen( self ):
        cls = type( self )
        if self._call in cls.INJECT and cls.DISPATCHER is not None:
            for sess in cls.DISPATCHER.active_sessions.values():
                sess[ "pending_messages" ].put_nowait( cls.INJECT[ self._call ] )
        if self._call in cls.STOP_RUNNING_ON_CALL and cls.DISPATCHER is not None:
            for sess in cls.DISPATCHER.active_sessions.values():
                sess[ "running" ] = False
        batch = cls.RESPONSE_BATCHES[ self._call ] if self._call < len( cls.RESPONSE_BATCHES ) else []
        self._call += 1
        for m in batch:
            yield m

    def receive_response( self ):
        return self._gen()


@pytest.fixture
def patched_sdk( monkeypatch ):
    """Monkeypatch the SDK names in the dispatcher module with in-process doubles."""
    monkeypatch.setattr( disp, "SDK_AVAILABLE", True )
    monkeypatch.setattr( disp, "ClaudeAgentOptions", lambda **k: ( "opts", k ) )
    monkeypatch.setattr( disp, "ClaudeSDKClient", _FakeSDKClient )
    monkeypatch.setattr( disp, "TextBlock", _FakeTextBlock )
    monkeypatch.setattr( disp, "AssistantMessage", _FakeAssistantMessage )
    monkeypatch.setattr( disp, "ResultMessage", _FakeResultMessage )
    monkeypatch.setattr( disp, "RateLimitEvent", _FakeRateLimitEvent )
    # reset class-level config between tests
    _FakeSDKClient.RESPONSE_BATCHES     = []
    _FakeSDKClient.INJECT               = {}
    _FakeSDKClient.DISPATCHER           = None
    _FakeSDKClient.AENTER_RAISES        = None
    _FakeSDKClient.QUERY_RAISES         = None
    _FakeSDKClient.STOP_RUNNING_ON_CALL = set()
    return _FakeSDKClient


@pytest.fixture
def lupin_root( monkeypatch, tmp_path ):
    """Set LUPIN_ROOT to a host-style temp path for dispatcher construction."""
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    return str( tmp_path )


def _make_dispatcher( on_message=None ):
    return ClaudeCodeDispatcher( on_message=on_message )


def _bounded_task( **kw ):
    kw.setdefault( "id", "t1" )
    kw.setdefault( "project", "lupin" )
    kw.setdefault( "prompt", "do it" )
    kw.setdefault( "type", TaskType.BOUNDED )
    return Task( **kw )


# =========================================================================== #
# TaskType / Task / TaskResult
# =========================================================================== #
def test_tasktype_values():
    """Enum values are the wire strings (harvest)."""
    assert TaskType.BOUNDED.value == "bounded"
    assert TaskType.INTERACTIVE.value == "interactive"


def test_task_sender_id_lowercases_project():
    """sender_id lowercases the project name (harvest)."""
    assert Task( id="t", project="COSA", prompt="p", type=TaskType.BOUNDED ).sender_id \
        == "claude.code@cosa.deepily.ai"


def test_task_working_dir_from_lupin_root( monkeypatch ):
    """working_dir defaults to LUPIN_ROOT when unset."""
    monkeypatch.setenv( "LUPIN_ROOT", "/opt/lupin" )
    assert _bounded_task().working_dir == "/opt/lupin"


def test_task_working_dir_fallback_when_no_lupin_root( monkeypatch ):
    """working_dir falls back to /home/projects when LUPIN_ROOT is unset."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert _bounded_task().working_dir == "/home/projects"


def test_task_working_dir_explicit_preserved( monkeypatch ):
    """An explicit working_dir is preserved (no env lookup)."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert _bounded_task( working_dir="/custom" ).working_dir == "/custom"


def test_task_defaults():
    """Task numeric defaults (harvest)."""
    t = _bounded_task()
    assert t.max_turns == 50 and t.timeout_seconds == 3600


def test_task_result_success_and_failure_shapes():
    """TaskResult carries success/failure fields (harvest)."""
    ok  = TaskResult( task_id="a", success=True, session_id="s", cost_usd=0.1, exit_code=0 )
    bad = TaskResult( task_id="b", success=False, error="boom", exit_code=-1 )
    assert ok.success is True and ok.session_id == "s"
    assert bad.success is False and bad.error == "boom"


# =========================================================================== #
# ClaudeCodeDispatcher.__init__
# =========================================================================== #
def test_init_requires_lupin_root( monkeypatch ):
    """Missing LUPIN_ROOT raises a RuntimeError naming the var (harvest)."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT" ):
        ClaudeCodeDispatcher()


def test_init_host_paths_default( lupin_root ):
    """Host LUPIN_ROOT → cosa_mcp.json + cosa_voice_mcp.py defaults."""
    d = ClaudeCodeDispatcher()
    assert d.mcp_config_path.endswith( "cosa_mcp.json" )
    assert d.mcp_server_path.endswith( "cosa_voice_mcp.py" )
    assert d.on_message == d._default_message_handler
    assert d.active_sessions == {}


def test_init_docker_paths( monkeypatch ):
    """LUPIN_ROOT=/var/lupin → the Docker MCP config path."""
    monkeypatch.setenv( "LUPIN_ROOT", "/var/lupin" )
    d = ClaudeCodeDispatcher()
    assert d.mcp_config_path.endswith( "cosa_mcp_docker.json" )


def test_init_explicit_paths_and_callback( lupin_root ):
    """Explicit paths are honored (expanduser applied) and on_message stored."""
    cb = lambda tid, m: None
    d = ClaudeCodeDispatcher( mcp_config_path="~/cfg.json", mcp_server_path="/srv/s.py", on_message=cb )
    assert d.mcp_config_path.startswith( "/" ) and d.mcp_config_path.endswith( "cfg.json" )
    assert d.mcp_server_path == "/srv/s.py"
    assert d.on_message is cb


# =========================================================================== #
# _default_message_handler
# =========================================================================== #
def test_default_message_handler_text_block( lupin_root, capsys ):
    """A message whose content blocks have `.text` prints the text branch."""
    d = _make_dispatcher()
    msg = _FakeAssistantMessage( content=[ _FakeBlock( text="hello world" ) ] )
    d._default_message_handler( "t1", msg )
    assert "hello world"[ :100 ] in capsys.readouterr().out


def test_default_message_handler_tool_block( lupin_root, capsys ):
    """A content block with `.name` (no text) prints the Tool branch."""
    class _Tool:
        name = "Bash"
    msg = _FakeAssistantMessage( content=[ _Tool() ] )
    _make_dispatcher()._default_message_handler( "t1", msg )
    assert "Tool: Bash" in capsys.readouterr().out


def test_default_message_handler_no_content( lupin_root, capsys ):
    """A message with no `content` attr prints its type name (else branch)."""
    class _Bare: pass
    _make_dispatcher()._default_message_handler( "t1", _Bare() )
    assert "_Bare" in capsys.readouterr().out


def test_default_message_handler_block_without_text_or_name( lupin_root, capsys ):
    """A content block with neither `.text` nor `.name` is silently skipped (loop continues)."""
    class _Empty: pass
    msg = _FakeAssistantMessage( content=[ _Empty(), _FakeBlock( text="after" ) ] )
    _make_dispatcher()._default_message_handler( "t1", msg )
    out = capsys.readouterr().out
    assert "after" in out                                    # second block still printed


# =========================================================================== #
# dispatch  (routing)
# =========================================================================== #
def test_dispatch_bounded_routes_to_run_bounded( lupin_root, monkeypatch ):
    """BOUNDED tasks route to _run_bounded."""
    d = _make_dispatcher()
    sentinel = TaskResult( task_id="t1", success=True )
    async def _fake_bounded( task ): return sentinel
    monkeypatch.setattr( d, "_run_bounded", _fake_bounded )
    assert asyncio.run( d.dispatch( _bounded_task() ) ) is sentinel


def test_dispatch_interactive_routes_when_sdk_available( lupin_root, monkeypatch ):
    """INTERACTIVE tasks route to _run_interactive when the SDK is present."""
    monkeypatch.setattr( disp, "SDK_AVAILABLE", True )
    d = _make_dispatcher()
    sentinel = TaskResult( task_id="t1", success=True )
    async def _fake_interactive( task ): return sentinel
    monkeypatch.setattr( d, "_run_interactive", _fake_interactive )
    task = _bounded_task( type=TaskType.INTERACTIVE )
    assert asyncio.run( d.dispatch( task ) ) is sentinel


def test_dispatch_interactive_without_sdk_returns_error( lupin_root, monkeypatch ):
    """INTERACTIVE with no SDK → a clear install-hint error result."""
    monkeypatch.setattr( disp, "SDK_AVAILABLE", False )
    d = _make_dispatcher()
    res = asyncio.run( d.dispatch( _bounded_task( type=TaskType.INTERACTIVE ) ) )
    assert res.success is False
    assert "claude-agent-sdk not installed" in res.error


def test_dispatch_unknown_type_returns_error( lupin_root ):
    """A task whose type is neither BOUNDED nor INTERACTIVE → error result."""
    d = _make_dispatcher()
    task = _bounded_task()
    task.type = "weird"                                       # neither enum member
    res = asyncio.run( d.dispatch( task ) )
    assert res.success is False
    assert "Unknown task type" in res.error


# =========================================================================== #
# _run_bounded
# =========================================================================== #
def test_run_bounded_success_with_result( lupin_root, monkeypatch ):
    """Streamed result JSON → success TaskResult with session/cost/result."""
    captured = []
    d = _make_dispatcher( on_message=lambda tid, data: captured.append( ( tid, data ) ) )
    lines = [
        b"\n",                                                # empty line → continue
        b'{"type":"assistant","text":"hi"}\n',                # non-result JSON
        b"plain text not json\n",                             # JSONDecodeError branch
        b'{"type":"result","session_id":"sess-9","result":"ok","cost_usd":0.05}\n',
    ]
    _patch_create_subprocess( monkeypatch, _FakeAsyncProcess( lines, returncode=0, stderr=b"" ) )
    res = asyncio.run( d._run_bounded( _bounded_task() ) )
    assert res.success is True
    assert res.session_id == "sess-9"
    assert res.result == "ok"
    assert res.cost_usd == 0.05
    assert res.exit_code == 0
    assert any( data.get( "type" ) == "result" for _, data in captured )


def test_run_bounded_success_no_result_message( lupin_root, monkeypatch ):
    """Exit 0 with no result message → success-without-fields; stderr printed."""
    d = _make_dispatcher( on_message=lambda tid, data: None )
    lines = [ b'{"type":"assistant","text":"working"}\n' ]
    _patch_create_subprocess( monkeypatch, _FakeAsyncProcess( lines, returncode=0, stderr=b"warn!" ) )
    res = asyncio.run( d._run_bounded( _bounded_task() ) )
    assert res.success is True
    assert res.session_id is None and res.exit_code == 0


def test_run_bounded_nonzero_exit_uses_stderr( lupin_root, monkeypatch ):
    """Non-zero exit → failure carrying decoded stderr."""
    d = _make_dispatcher( on_message=lambda tid, data: None )
    _patch_create_subprocess( monkeypatch, _FakeAsyncProcess( [], returncode=2, stderr=b"kaboom" ) )
    res = asyncio.run( d._run_bounded( _bounded_task() ) )
    assert res.success is False
    assert res.error == "kaboom" and res.exit_code == 2


def test_run_bounded_nonzero_exit_empty_stderr( lupin_root, monkeypatch ):
    """Non-zero exit with empty stderr → 'Unknown error'."""
    d = _make_dispatcher( on_message=lambda tid, data: None )
    _patch_create_subprocess( monkeypatch, _FakeAsyncProcess( [], returncode=3, stderr=b"" ) )
    res = asyncio.run( d._run_bounded( _bounded_task() ) )
    assert res.success is False
    assert res.error == "Unknown error" and res.exit_code == 3


def test_run_bounded_timeout_kills_process( lupin_root, monkeypatch ):
    """A read-stream timeout kills the process and returns a timeout failure."""
    d = _make_dispatcher( on_message=lambda tid, data: None )
    proc = _FakeAsyncProcess( [ b"slow\n" ], returncode=0 )
    _patch_create_subprocess( monkeypatch, proc )
    async def _wait_for_timeout( coro, timeout=None ):
        coro.close()                                          # avoid 'never awaited' warning
        raise asyncio.TimeoutError()
    monkeypatch.setattr( disp.asyncio, "wait_for", _wait_for_timeout )
    res = asyncio.run( d._run_bounded( _bounded_task( timeout_seconds=1 ) ) )
    assert res.success is False
    assert "timed out" in res.error and res.exit_code == -1
    assert proc.killed is True


def test_run_bounded_outer_exception( lupin_root, monkeypatch ):
    """An exception spawning the subprocess → failure with exit_code -1."""
    d = _make_dispatcher( on_message=lambda tid, data: None )
    async def _boom( *a, **k ):
        raise OSError( "cannot spawn claude" )
    monkeypatch.setattr( disp.asyncio, "create_subprocess_exec", _boom )
    res = asyncio.run( d._run_bounded( _bounded_task() ) )
    assert res.success is False
    assert "cannot spawn claude" in res.error and res.exit_code == -1


# =========================================================================== #
# _run_interactive  (SDK client fully faked)
# =========================================================================== #
def test_run_interactive_success_single_pass( lupin_root, patched_sdk ):
    """One response batch (text + assistant blocks + result) → success."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.RESPONSE_BATCHES = [ [
        _FakeTextBlock( "thinking" ),
        _FakeAssistantMessage( content=[ _FakeBlock( text="answer" ), _FakeBlock() ] ),
        _FakeResultMessage( session_id="sess-X", result="all done" ),
    ] ]
    res = asyncio.run( d._run_interactive( _bounded_task( type=TaskType.INTERACTIVE ) ) )
    assert res.success is True
    assert res.session_id == "sess-X"
    assert res.result == "all done"
    assert d.active_sessions == {}                            # cleaned up


def test_run_interactive_injected_message_loops( lupin_root, patched_sdk ):
    """A queued pending message drives a second query before completion."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.DISPATCHER       = d
    patched_sdk.INJECT           = { 0: "follow-up question" }
    patched_sdk.RESPONSE_BATCHES = [
        [ _FakeTextBlock( "first" ) ],                        # pass 1: pending gets enqueued
        [ _FakeResultMessage( session_id="sess-2" ) ],        # pass 2: result, then break
    ]
    res = asyncio.run( d._run_interactive( _bounded_task( id="loop", type=TaskType.INTERACTIVE ) ) )
    assert res.success is True
    assert res.session_id == "sess-2"


def test_run_interactive_running_flag_cleared_exits_loop( lupin_root, patched_sdk ):
    """If `running` flips False before the loop re-checks, the while exits via its condition."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.DISPATCHER           = d
    patched_sdk.INJECT               = { 0: "queued" }        # pending non-empty → would loop...
    patched_sdk.STOP_RUNNING_ON_CALL = { 0 }                  # ...but running flips False first
    patched_sdk.RESPONSE_BATCHES     = [ [ _FakeTextBlock( "only text" ) ] ]
    res = asyncio.run( d._run_interactive( _bounded_task( id="stop", type=TaskType.INTERACTIVE ) ) )
    assert res.success is False                               # no ResultMessage seen
    assert res.error == "No result received"
    assert d.active_sessions == {}


def test_run_interactive_no_result_returns_failure( lupin_root, patched_sdk ):
    """No ResultMessage in the stream → 'No result received' failure."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.RESPONSE_BATCHES = [ [ _FakeTextBlock( "no result here" ) ] ]
    res = asyncio.run( d._run_interactive( _bounded_task( type=TaskType.INTERACTIVE ) ) )
    assert res.success is False
    assert res.error == "No result received"
    assert d.active_sessions == {}


def test_run_interactive_query_exception_cleans_up_session( lupin_root, patched_sdk ):
    """An exception after the session is registered → failure + session deleted."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.QUERY_RAISES = RuntimeError( "query blew up" )
    res = asyncio.run( d._run_interactive( _bounded_task( id="qx", type=TaskType.INTERACTIVE ) ) )
    assert res.success is False
    assert "query blew up" in res.error
    assert "qx" not in d.active_sessions


def test_run_interactive_aenter_exception_before_session( lupin_root, patched_sdk ):
    """An exception entering the client (before session registered) → failure."""
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.AENTER_RAISES = RuntimeError( "connect failed" )
    res = asyncio.run( d._run_interactive( _bounded_task( id="ax", type=TaskType.INTERACTIVE ) ) )
    assert res.success is False
    assert "connect failed" in res.error
    assert "ax" not in d.active_sessions


def test_run_interactive_rate_limit_event_is_prod_bug( lupin_root, patched_sdk ):
    """TRIPWIRE PIN: a RateLimitEvent hits `self.debug` (uninitialized) →
    AttributeError absorbed by the broad except → failure naming 'debug'.

    This documents dispatcher.py:468's confirmed prod bug (ClaudeCodeDispatcher
    never sets self.debug). The manager owns the source fix + removing this pin.
    """
    d = _make_dispatcher( on_message=lambda tid, m: None )
    patched_sdk.RESPONSE_BATCHES = [ [ _FakeRateLimitEvent( retry_after=7 ) ] ]
    res = asyncio.run( d._run_interactive( _bounded_task( id="rl", type=TaskType.INTERACTIVE ) ) )
    assert res.success is False
    assert "debug" in res.error                               # AttributeError text
    assert "rl" not in d.active_sessions


# =========================================================================== #
# inject / interrupt / end_session / get_active_sessions
# =========================================================================== #
def _seed_session( dispatcher, task_id="t1", history=None ):
    """Register a fake interactive session for inject/interrupt/end tests."""
    client = _FakeSDKClient()
    dispatcher.active_sessions[ task_id ] = {
        "client"           : client,
        "pending_messages" : asyncio.Queue(),
        "running"          : True,
        "history"          : history,
    }
    return client


def test_get_active_sessions( lupin_root ):
    """get_active_sessions lists the registered task IDs."""
    d = _make_dispatcher()
    assert d.get_active_sessions() == []
    _seed_session( d, "a" ); _seed_session( d, "b" )
    assert set( d.get_active_sessions() ) == { "a", "b" }


def test_inject_session_not_found_returns_false( lupin_root ):
    """Injecting into an unknown session returns False."""
    d = _make_dispatcher()
    assert asyncio.run( d.inject( "nope", "msg" ) ) is False


def test_inject_with_context_and_interrupt( lupin_root ):
    """preserve_context + non-empty history → context prepended, interrupt fired."""
    from cosa.orchestration.claude_code.message_history import MessageHistory
    d = _make_dispatcher()
    hist = MessageHistory(); hist.set_original_prompt( "orig" ); hist.add_assistant_text( "prior" )
    client = _seed_session( d, "t1", history=hist )
    ok = asyncio.run( d.inject( "t1", "new question", preserve_context=True, force_interrupt=True ) )
    assert ok is True
    queued = d.active_sessions[ "t1" ][ "pending_messages" ].get_nowait()
    assert "[CONVERSATION CONTEXT]" in queued and "new question" in queued
    assert client.interrupted == 1
    assert any( m[ "content" ] == "new question" for m in hist.messages )   # user msg tracked


def test_inject_without_context_no_interrupt( lupin_root ):
    """preserve_context=False → raw message queued; force_interrupt=False → no interrupt."""
    d = _make_dispatcher()
    client = _seed_session( d, "t1", history=None )
    ok = asyncio.run( d.inject( "t1", "raw msg", preserve_context=False, force_interrupt=False ) )
    assert ok is True
    assert d.active_sessions[ "t1" ][ "pending_messages" ].get_nowait() == "raw msg"
    assert client.interrupted == 0


def test_inject_preserve_context_but_empty_history_uses_raw( lupin_root ):
    """preserve_context=True with a falsy (empty) history → raw message queued."""
    from cosa.orchestration.claude_code.message_history import MessageHistory
    d = _make_dispatcher()
    _seed_session( d, "t1", history=MessageHistory() )        # empty → falsy
    asyncio.run( d.inject( "t1", "raw", preserve_context=True, force_interrupt=False ) )
    assert d.active_sessions[ "t1" ][ "pending_messages" ].get_nowait() == "raw"


def test_interrupt_found_and_not_found( lupin_root ):
    """interrupt() returns True + calls client.interrupt; False when unknown."""
    d = _make_dispatcher()
    client = _seed_session( d, "t1" )
    assert asyncio.run( d.interrupt( "t1" ) ) is True
    assert client.interrupted == 1
    assert asyncio.run( d.interrupt( "ghost" ) ) is False


def test_end_session_found_and_not_found( lupin_root ):
    """end_session() flips running→False; False when unknown."""
    d = _make_dispatcher()
    _seed_session( d, "t1" )
    assert d.end_session( "t1" ) is True
    assert d.active_sessions[ "t1" ][ "running" ] is False
    assert d.end_session( "ghost" ) is False


# =========================================================================== #
# main()  (async CLI entry — NOT excluded from coverage)
# =========================================================================== #
def test_main_smoke_test_flag( monkeypatch ):
    """--smoke-test runs quick_smoke_test and returns its 0/1 exit code."""
    monkeypatch.setattr( "sys.argv", [ "dispatcher", "--smoke-test" ] )
    monkeypatch.setattr( disp, "quick_smoke_test", lambda: True )
    assert asyncio.run( disp.main() ) == 0
    monkeypatch.setattr( disp, "quick_smoke_test", lambda: False )
    assert asyncio.run( disp.main() ) == 1


def test_main_missing_prompt_errors( monkeypatch ):
    """No prompt (and not --smoke-test) → argparse error (SystemExit)."""
    monkeypatch.setattr( "sys.argv", [ "dispatcher" ] )
    with pytest.raises( SystemExit ):
        asyncio.run( disp.main() )


def test_main_missing_project_errors( monkeypatch ):
    """Prompt but no --project → argparse error (SystemExit)."""
    monkeypatch.setattr( "sys.argv", [ "dispatcher", "do the thing" ] )
    with pytest.raises( SystemExit ):
        asyncio.run( disp.main() )


def test_main_dispatch_success( monkeypatch, lupin_root, capsys ):
    """Full dispatch path prints the success summary with all optional fields."""
    monkeypatch.setattr( "sys.argv",
                         [ "dispatcher", "do it", "--project", "lupin", "--type", "bounded" ] )
    result = TaskResult( task_id="x", success=True, session_id="sess-7",
                         cost_usd=0.1234, duration_ms=987, result="R" * 300 )
    async def _fake_dispatch( self, task ): return result
    monkeypatch.setattr( disp.ClaudeCodeDispatcher, "dispatch", _fake_dispatch )
    assert asyncio.run( disp.main() ) is None
    out = capsys.readouterr().out
    assert "✓ Success" in out and "sess-7" in out and "0.1234" in out and "987ms" in out


def test_main_dispatch_success_minimal_fields( monkeypatch, lupin_root, capsys ):
    """Success with no cost/duration/result → the optional print branches are skipped."""
    monkeypatch.setattr( "sys.argv",
                         [ "dispatcher", "do it", "--project", "lupin" ] )
    result = TaskResult( task_id="x", success=True, session_id="sess-9",
                         cost_usd=None, duration_ms=None, result=None )
    async def _fake_dispatch( self, task ): return result
    monkeypatch.setattr( disp.ClaudeCodeDispatcher, "dispatch", _fake_dispatch )
    asyncio.run( disp.main() )
    out = capsys.readouterr().out
    assert "✓ Success" in out
    assert "Cost:" not in out and "Duration:" not in out and "Result:" not in out


def test_main_dispatch_failure_no_exit_code( monkeypatch, lupin_root, capsys ):
    """A failure with exit_code None omits the exit-code line."""
    monkeypatch.setattr( "sys.argv",
                         [ "dispatcher", "do it", "--project", "lupin" ] )
    result = TaskResult( task_id="x", success=False, error="nope", exit_code=None )
    async def _fake_dispatch( self, task ): return result
    monkeypatch.setattr( disp.ClaudeCodeDispatcher, "dispatch", _fake_dispatch )
    asyncio.run( disp.main() )
    out = capsys.readouterr().out
    assert "✗ Failed: nope" in out and "Exit code:" not in out


def test_main_dispatch_failure( monkeypatch, lupin_root, capsys ):
    """A failing dispatch prints the failure summary + exit code."""
    monkeypatch.setattr( "sys.argv",
                         [ "dispatcher", "do it", "--project", "lupin" ] )
    result = TaskResult( task_id="x", success=False, error="nope", exit_code=7 )
    async def _fake_dispatch( self, task ): return result
    monkeypatch.setattr( disp.ClaudeCodeDispatcher, "dispatch", _fake_dispatch )
    asyncio.run( disp.main() )
    out = capsys.readouterr().out
    assert "✗ Failed: nope" in out and "Exit code: 7" in out
