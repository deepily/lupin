"""
Unit tests for the model-loading and commons steps in `lupin_app/lifespan_steps.py`.

Collaborators that need a GPU, a model server or the commons stack are replaced by modules
placed in `sys.modules` for one test. Each branch runs here and the real modules never start.
"""

import asyncio
import io
import os
import sys
import types

import pytest

from lupin_app import lifespan_steps as steps


class FakeConfig:
    """A config double: get() returns the stored value, or the default when the key is absent."""

    def __init__( self, **values ):
        self.values = { k.replace( "_", " " ): v for k, v in values.items() }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )


def _install( monkeypatch, name, **attrs ):
    """Place a module called name in sys.modules for this test, carrying attrs."""
    module = types.ModuleType( name )
    for key, value in attrs.items():
        setattr( module, key, value )
    monkeypatch.setitem( sys.modules, name, module )
    return module


# ── probe_model_server ───────────────────────────────────────────────────────

class _Clock:
    """A clock that only moves when the fake sleep is called, so timeouts are exact."""

    def __init__( self ):
        self.now = 1000.0

    def __call__( self ):
        return self.now

    async def sleep( self, seconds ):
        self.now += seconds


class _Boom( Exception ):
    """The request error class the probe is told to retry on."""


def _probe( responses, timeout, clock=None ):
    clock = clock or _Clock()
    calls = []
    def get( url, timeout ):
        calls.append( ( url, timeout ) )
        outcome = responses.pop( 0 ) if len( responses ) > 1 else responses[ 0 ]
        if isinstance( outcome, Exception ): raise outcome
        return types.SimpleNamespace( status_code=outcome )
    ok = asyncio.run( steps.probe_model_server( "http://ms/health", timeout, get, _Boom, sleep_fn=clock.sleep, clock_fn=clock ) )
    return ok, calls, clock


def test_probe_returns_at_once_when_the_server_is_up( capsys ):
    """A 200 on the first request prints OK with zero seconds and never sleeps."""
    ok, calls, clock = _probe( [ 200 ], 60 )
    assert ok is True and calls == [ ( "http://ms/health", 2 ) ] and clock.now == 1000.0
    assert capsys.readouterr().out == "OK (0s)\n"


def test_probe_retries_after_a_refused_connection( capsys ):
    """A request error counts as not ready, the probe sleeps a second, and a later 200 succeeds."""
    ok, calls, clock = _probe( [ _Boom( "refused" ), 200 ], 60 )
    assert ok is True and len( calls ) == 2 and clock.now == 1001.0
    assert capsys.readouterr().out == "OK (1s)\n"


def test_probe_gives_up_at_the_deadline( capsys ):
    """A server that keeps answering 503 is reported as a timeout after the full budget."""
    ok, calls, clock = _probe( [ 503 ], 3 )
    assert ok is False and len( calls ) == 3
    assert capsys.readouterr().out == "TIMEOUT after 3s — continuing; model endpoints will 503 until reachable\n"


def test_probe_with_no_budget_never_asks( capsys ):
    """A zero budget times out without making a request."""
    ok, calls, _clock = _probe( [ 200 ], 0 )
    assert ok is False and calls == []
    assert capsys.readouterr().out.startswith( "TIMEOUT after 0s" )


# ── load_local_models ────────────────────────────────────────────────────────

class _Engine:
    def __init__( self, log, name ):
        self.log, self.name = log, name

    def __getattr__( self, method ):
        return lambda texts: self.log.append( ( self.name, method, len( texts ) ) )


def _local_fixture( monkeypatch ):
    """Install fake engines and providers; return the shared event log."""
    log = []
    _install( monkeypatch, "cosa.memory.local_embedding_engine",
              get_code_engine  = lambda debug, verbose: log.append( ( "get_code", debug, verbose ) ) or _Engine( log, "code" ),
              get_prose_engine = lambda debug, verbose: log.append( ( "get_prose", debug, verbose ) ) or _Engine( log, "prose" ) )
    _install( monkeypatch, "cosa.memory.embedding_provider",
              EmbeddingProvider = types.SimpleNamespace( declare_in_process_engine_owner=lambda: log.append( "embed-owner" ) ) )
    _install( monkeypatch, "cosa.memory.speech_to_text_provider",
              SpeechToTextProvider = types.SimpleNamespace(
                  declare_in_process_owner = lambda: log.append( "stt-owner" ),
                  declare_remote_only      = lambda: log.append( "stt-remote" ),
              ) )
    return log


def _run_local( log, load_stt, exists ):
    return asyncio.run( steps.load_local_models(
        FakeConfig(), True, False, lambda label: log.append( ( "vram", label ) ), load_stt, "/proj", exists
    ) )


def test_local_models_load_in_order_and_warm_up( monkeypatch, capsys ):
    """The code engine, prose engine and Whisper load in order, and the warmup file runs."""
    log = _local_fixture( monkeypatch )
    transcribed = []
    async def load_stt():
        return lambda path, **kw: transcribed.append( ( path, kw ) )
    pipeline = _run_local( log, load_stt, lambda path: True )
    assert callable( pipeline )
    assert transcribed == [ ( "/proj/src/conf/warmup/whisper-warmup-85s.mp3",
                              { "chunk_length_s": 30, "stride_length_s": 5, "return_timestamps": False } ) ]
    assert [ e for e in log if isinstance( e, tuple ) and e[ 0 ] == "vram" ] == [
        ( "vram", "CodeRankEmbed" ), ( "vram", "Prose Embedding" ), ( "vram", "Whisper" ) ]
    assert log[ 0 ] == ( "get_code", True, False )
    assert [ e for e in log if isinstance( e, str ) ] == [ "embed-owner", "stt-owner" ]
    assert [ e[ 1 ] for e in log if isinstance( e, tuple ) and e[ 0 ] == "code" ] == [ "encode_code", "encode_query", "encode_code" ]
    assert [ e[ 1 ] for e in log if isinstance( e, tuple ) and e[ 0 ] == "prose" ] == [ "encode_query", "encode_document", "encode_query" ]
    assert "Done! (with warmup)" in capsys.readouterr().out


def test_local_models_skip_the_warmup_when_the_file_is_missing( monkeypatch, capsys ):
    """Without a warmup file Whisper is still declared owner and the line says so."""
    log = _local_fixture( monkeypatch )
    async def load_stt():
        return lambda *a, **kw: pytest.fail( "the pipeline must not run without a warmup file" )
    assert callable( _run_local( log, load_stt, lambda path: False ) )
    assert "stt-owner" in log
    assert "Done! (no warmup file)" in capsys.readouterr().out


def test_local_models_survive_a_whisper_failure( monkeypatch, capsys ):
    """A Whisper load error returns None, warns, and does not declare ownership."""
    log = _local_fixture( monkeypatch )
    async def load_stt(): raise RuntimeError( "out of memory" )
    assert _run_local( log, load_stt, lambda path: True ) is None
    out = capsys.readouterr().out
    assert "FAILED!" in out
    assert "[WARN] Whisper STT model failed to load: out of memory" in out
    assert "[WARN] STT endpoints will return 503. All other endpoints remain functional." in out
    assert "stt-owner" not in log and "embed-owner" in log
    assert ( "vram", "Whisper" ) in log


# ── load_models ──────────────────────────────────────────────────────────────

def _load_models( monkeypatch, config, environ=None ):
    """Run load_models with load_local_models and probe_model_server replaced by recorders."""
    seen = {}
    async def fake_local( *args ):
        seen[ "local" ] = args
        return "PIPELINE"
    async def fake_probe( url, timeout, get_fn, error_cls ):
        seen[ "probe" ] = ( url, timeout, get_fn, error_cls )
    monkeypatch.setattr( steps, "load_local_models", fake_local )
    monkeypatch.setattr( steps, "probe_model_server", fake_probe )
    log = []
    _install( monkeypatch, "cosa.memory.speech_to_text_provider",
              SpeechToTextProvider = types.SimpleNamespace( declare_remote_only=lambda: log.append( "stt-remote" ) ) )
    result = asyncio.run( steps.load_models( config, True, False, "vram", "stt", "/proj", environ if environ is not None else { } ) )
    return result, seen, log


def test_default_provider_loads_models_locally( monkeypatch ):
    """With no provider key the models load onto this process and the pipeline is returned."""
    config = FakeConfig()
    result, seen, log = _load_models( monkeypatch, config )
    assert result == "PIPELINE" and "probe" not in seen and log == []
    assert seen[ "local" ][ 0 ] is config
    assert seen[ "local" ][ 1: ] == ( True, False, "vram", "stt", "/proj", os.path.exists )


def test_model_server_provider_is_matched_ignoring_case_and_padding( monkeypatch, capsys ):
    """The remote value matches after lower() and strip(), then probes the INI url."""
    config = FakeConfig( speech_to_text_provider=" Model-Server ", model_server_url="http://ms:1", model_server_startup_probe_timeout_seconds=7 )
    import requests
    result, seen, log = _load_models( monkeypatch, config )
    assert result is None and "local" not in seen and log == [ "stt-remote" ]
    assert seen[ "probe" ] == ( "http://ms:1/health", 7, requests.get, requests.RequestException )
    out = capsys.readouterr().out
    assert "[REMOTE-MODE] Skipping eager GPU loads — routing via HTTP to lupin-model-server" in out
    assert "[REMOTE-MODE] Probing model-server readiness at http://ms:1/health (budget=7s)... " in out


def test_environment_url_beats_the_ini_url( monkeypatch ):
    """LUPIN_MODEL_SERVER_URL overrides the INI value; the probe budget defaults to 60."""
    config = FakeConfig( speech_to_text_provider="model-server", model_server_url="http://ini:1" )
    _result, seen, _log = _load_models( monkeypatch, config, environ={ "LUPIN_MODEL_SERVER_URL": "http://env:2" } )
    assert seen[ "probe" ][ :2 ] == ( "http://env:2/health", 60 )


def test_default_model_server_url_is_the_compose_service( monkeypatch ):
    """With neither environment nor INI value the url is the compose service name."""
    _result, seen, _log = _load_models( monkeypatch, FakeConfig( speech_to_text_provider="model-server" ) )
    assert seen[ "probe" ][ 0 ] == "http://lupin-model-server:7998/health"


# ── build_commons_owner_resolver ─────────────────────────────────────────────

def test_owner_resolver_maps_each_session_to_its_owner():
    """Each live session id maps to its bridge owner, or None when the bridge has none."""
    bridges  = { "/a": { "owner_user_id": "u1" }, "/b": { }, "/c": None }
    sessions = lambda: [ ( "/a", "sa", { } ), ( "/b", "sb", { } ), ( "/c", "sc", { } ) ]
    resolver = steps.build_commons_owner_resolver( sessions, bridges.get )
    assert resolver() == { "sa": "u1", "sb": None }


def test_owner_resolver_builds_a_fresh_map_each_call():
    """A session that goes away between ticks is absent from the next map."""
    live     = [ ( "/a", "sa", { } ) ]
    resolver = steps.build_commons_owner_resolver( lambda: list( live ), lambda path: { "owner_user_id": "u1" } )
    assert resolver() == { "sa": "u1" }
    live.clear()
    assert resolver() == { }


# ── install_llm_disambiguator ────────────────────────────────────────────────

def test_disambiguator_is_built_from_the_config_and_installed( capsys ):
    """The class gets the config, the instance is installed, and success is printed."""
    installed = []
    class Cls:
        def __init__( self, config ): self.config = config
    config = FakeConfig()
    assert steps.install_llm_disambiguator( installed.append, Cls, config ) is True
    assert len( installed ) == 1 and installed[ 0 ].config is config
    assert capsys.readouterr().out == "[COMMONS] Phase 3 LLM disambiguator installed\n"


def test_disambiguator_constructor_failure_falls_back( capsys ):
    """A constructor error is reported as a fallback to the stub matcher."""
    class Cls:
        def __init__( self, config ): raise RuntimeError( "no key" )
    assert steps.install_llm_disambiguator( lambda inst: None, Cls, FakeConfig() ) is False
    assert capsys.readouterr().out == "[COMMONS] WARN — LLM disambiguator init failed (matcher falls back to Phase 1 stub): no key\n"


def test_disambiguator_configure_failure_falls_back( capsys ):
    """A configure error gets the same fallback line."""
    def boom( inst ): raise RuntimeError( "matcher missing" )
    assert steps.install_llm_disambiguator( boom, lambda config: object(), FakeConfig() ) is False
    assert "matcher falls back to Phase 1 stub): matcher missing" in capsys.readouterr().out


# ── init_commons ─────────────────────────────────────────────────────────────

def _state():
    return types.SimpleNamespace( commons_store=None, commons_rate_limiter=None, commons_ack_watcher=None, commons_activity_watcher=None )


def test_init_commons_skips_when_disabled( capsys ):
    """The commons switch off prints the skip line and never calls the starter."""
    called = []
    steps.init_commons( _state(), FakeConfig( commons_enabled=False ), "queue", start_fn=lambda *a: called.append( a ) )
    assert called == []
    assert capsys.readouterr().out == "[COMMONS] Disabled via `commons enabled = false` — skipping Phase 2+3 init\n"


def test_init_commons_calls_the_starter_when_enabled():
    """The starter receives the state, config and notification queue."""
    called, state, config = [], _state(), FakeConfig()
    steps.init_commons( state, config, "queue", start_fn=lambda *a: called.append( a ) )
    assert called == [ ( state, config, "queue" ) ]


def test_init_commons_failure_is_a_warning_and_keeps_partial_state( capsys ):
    """A starter that fails after building the store leaves the store on state and warns."""
    state = _state()
    def start( s, config, queue ):
        s.commons_store = "store"
        raise RuntimeError( "limiter broke" )
    steps.init_commons( state, FakeConfig(), "queue", start_fn=start )
    assert state.commons_store == "store" and state.commons_ack_watcher is None
    assert capsys.readouterr().out == "[COMMONS] WARN — Phase 2+3 init failed: limiter broke\n"


# ── start_commons ────────────────────────────────────────────────────────────

class _Obj:
    """A constructor double that records its keyword arguments and how often it was started."""

    created = None

    def __init__( self, *args, **kwargs ):
        self.args, self.kwargs, self.started = args, kwargs, 0
        type( self ).created = self

    def start( self ): self.started += 1


def _commons_fixture( monkeypatch ):
    """Install the eight modules start_commons imports; return the recorders."""
    rec = types.SimpleNamespace( state_calls=[], configured=[] )
    classes = {
        name: type( name, ( _Obj, ), { "created": None } )
        for name in ( "CommonsStore", "CommonsBroadcastRateLimiter", "CommonsAckWatcher", "CommonsActivityWatcher", "CommonsLlmDisambiguator" )
    }
    rec.classes = classes
    _install( monkeypatch, "cosa.rest.commons_ack_watcher",    CommonsAckWatcher = classes[ "CommonsAckWatcher" ] )
    _install( monkeypatch, "cosa.rest.commons_activity_watcher", CommonsActivityWatcher = classes[ "CommonsActivityWatcher" ] )
    _install( monkeypatch, "cosa.rest.commons_rate_limiter",   CommonsBroadcastRateLimiter = classes[ "CommonsBroadcastRateLimiter" ] )
    _install( monkeypatch, "cosa.rest.routers.commons",
              init_commons_state = lambda **kw: rec.state_calls.append( kw ),
              _load_bridge_fields = lambda path: { "owner_user_id": "u1" } )
    _install( monkeypatch, "lupin_cli.claude_code.hooks.lib.session_bridge",
              find_active_voice_persona_sessions = lambda: [ ( "/p", "sid", { } ) ] )
    _install( monkeypatch, "lupin_mcp.commons_llm_disambiguator", CommonsLlmDisambiguator = classes[ "CommonsLlmDisambiguator" ] )
    _install( monkeypatch, "lupin_mcp.commons_persona_matcher", configure_llm_disambiguator = rec.configured.append )
    _install( monkeypatch, "lupin_mcp.commons_store", CommonsStore = classes[ "CommonsStore" ] )
    return rec


class _Queue:
    def push_notification( self, **kw ): return None


def test_start_commons_builds_and_starts_everything( monkeypatch, capsys ):
    """With defaults the store, limiter and both watchers exist, and both watchers start."""
    rec, state, queue = _commons_fixture( monkeypatch ), _state(), _Queue()
    monkeypatch.setenv( "LUPIN_ROOT", "/the/root" )
    steps.start_commons( state, FakeConfig(), queue )
    assert state.commons_store.args == ( "/the/root", )
    assert state.commons_rate_limiter.kwargs == { "window_seconds": 30 }
    assert state.commons_ack_watcher.kwargs[ "store" ] is state.commons_store
    assert state.commons_ack_watcher.kwargs[ "poll_interval_seconds" ] == 1
    assert state.commons_ack_watcher.kwargs[ "push_notification_fn" ] == queue.push_notification
    assert rec.state_calls == [ { "store": state.commons_store, "rate_limiter": state.commons_rate_limiter,
                                  "ack_watcher": state.commons_ack_watcher, "active_session_threshold_seconds": 28800 } ]
    assert state.commons_ack_watcher.started == 1 and state.commons_activity_watcher.started == 1
    kw = state.commons_activity_watcher.kwargs
    assert kw[ "excluded_topics" ] == [ "presence", "system-events" ]
    assert kw[ "bridge_owner_resolver_fn" ]() == { "sid": "u1" }
    assert len( rec.configured ) == 1
    out = capsys.readouterr().out
    assert "[COMMONS] Phase 2.5/3.5 CommonsActivityWatcher started (excluded=['presence', 'system-events'])" in out
    assert "[COMMONS] Phase 2+3 subsystem started (root=/the/root)" in out


def test_start_commons_splits_the_exclude_list_on_commas( monkeypatch ):
    """Whitespace is stripped and empty items are dropped from the INI topic list."""
    _commons_fixture( monkeypatch )
    state = _state()
    steps.start_commons( state, FakeConfig( commons_traffic_visibility_exclude_topics=" a , ,b,, " ), _Queue() )
    assert state.commons_activity_watcher.kwargs[ "excluded_topics" ] == [ "a", "b" ]


@pytest.mark.parametrize( "key", [ "commons_traffic_visibility_enabled", "commons_traffic_visibility_ws_push_enabled" ] )
def test_start_commons_skips_the_activity_watcher_when_either_switch_is_off( monkeypatch, key ):
    """Either traffic-visibility switch off skips the activity watcher; the ack watcher starts."""
    _commons_fixture( monkeypatch )
    state = _state()
    steps.start_commons( state, FakeConfig( **{ key: False } ), _Queue() )
    assert state.commons_activity_watcher is None and state.commons_ack_watcher.started == 1


def test_start_commons_falls_back_to_the_working_directory( monkeypatch ):
    """With LUPIN_ROOT unset the store is rooted at the current directory."""
    _commons_fixture( monkeypatch )
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    state = _state()
    steps.start_commons( state, FakeConfig(), _Queue() )
    assert state.commons_store.args == ( os.getcwd(), )


def test_start_commons_keeps_what_it_built_before_a_failure( monkeypatch ):
    """A failing ack watcher constructor propagates, leaving the store and limiter on state."""
    rec = _commons_fixture( monkeypatch )
    class Broken( _Obj ):
        def __init__( self, *a, **kw ): raise RuntimeError( "watcher broke" )
    sys.modules[ "cosa.rest.commons_ack_watcher" ].CommonsAckWatcher = Broken
    state = _state()
    with pytest.raises( RuntimeError, match="watcher broke" ):
        steps.start_commons( state, FakeConfig(), _Queue() )
    assert state.commons_store is not None and state.commons_rate_limiter is not None
    assert state.commons_ack_watcher is None and rec.state_calls == []
