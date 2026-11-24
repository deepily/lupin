"""
Tests for src/scripts/zero_model_proof.py.

install_guards patches real classes and the socket module. Each test that calls it first has monkeypatch record
every attribute, so teardown restores them. main runs with the guards faked. The cohort, engine and replay are
small doubles, so no database, model or vector file is touched.
"""

import collections
import runpy
import socket
import sys
import types

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import zero_model_proof as zmp   # noqa: E402

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine   # noqa: E402
import cosa.agents.llm_client_factory as factory_module   # noqa: E402
import cosa.memory.embedding_provider as provider_module   # noqa: E402
import cosa.research.preference_replay.service_embeddings as service_module   # noqa: E402


@pytest.fixture
def restore_patched( monkeypatch ):
    """Have monkeypatch record every attribute install_guards replaces, so teardown restores it."""
    for target, name in ( ( factory_module.LlmClientFactory, "get_client" ), ( PredictionEngine, "_get_llm_client" ),
                          ( PredictionEngine, "_generate_embedding" ), ( service_module.CachedServiceEmbedder, "__call__" ),
                          ( provider_module, "get_embedding_provider" ), ( socket.socket, "connect" ) ):
        monkeypatch.setattr( target, name, getattr( target, name ) )
    return monkeypatch


class _Connect:
    """Stands in for the real socket connect and records what reached it."""
    def __init__( self ): self.seen = []
    def __call__( self, sock, address ): self.seen.append( address )


def _install( restore_patched, fake_clients ):
    """Install the guards over fake client modules; return ( calls, the connect recorder )."""
    recorder = _Connect()
    restore_patched.setattr( socket.socket, "connect", recorder )
    for name, attributes in fake_clients.items():
        module = types.ModuleType( name )
        for attribute in attributes: setattr( module, attribute, object() )
        restore_patched.setitem( sys.modules, name, module )
    calls = collections.Counter()
    zmp.install_guards( calls )
    return calls, recorder


def test_every_model_embedding_and_client_entry_point_raises_and_is_counted( restore_patched ):
    calls, _ = _install( restore_patched, { "anthropic": ( "Anthropic", "AsyncAnthropic" ), "openai": ( "OpenAI", ) } )
    attempts = [ ( "LlmClientFactory.get_client",             lambda: factory_module.LlmClientFactory().get_client( "x" ) ),
                 ( "PredictionEngine._get_llm_client",        lambda: PredictionEngine._get_llm_client( object() ) ),
                 ( "PredictionEngine._generate_embedding",    lambda: PredictionEngine._generate_embedding( object(), "text" ) ),
                 ( "CachedServiceEmbedder.__call__",          lambda: service_module.CachedServiceEmbedder.__call__( object(), "text" ) ),
                 ( "get_embedding_provider",                  lambda: provider_module.get_embedding_provider() ),
                 ( "anthropic.Anthropic",                     lambda: sys.modules[ "anthropic" ].Anthropic() ),
                 ( "anthropic.AsyncAnthropic",                lambda: sys.modules[ "anthropic" ].AsyncAnthropic() ),
                 ( "openai.OpenAI",                           lambda: sys.modules[ "openai" ].OpenAI() ) ]
    for name, attempt in attempts:
        with pytest.raises( AssertionError, match=f"MODEL CALL ATTEMPTED: {name}" ): attempt()
    assert dict( calls ) == { name: 1 for name, _ in attempts }


def test_an_outside_connect_raises_and_a_loopback_or_non_tuple_address_passes_through( restore_patched ):
    calls, recorder = _install( restore_patched, {} )
    with pytest.raises( AssertionError, match="EXTERNAL CONNECT" ): socket.socket.connect( object(), ( "8.8.8.8", 53 ) )
    assert calls[ "socket.connect_external" ] == 1 and recorder.seen == []
    socket.socket.connect( object(), ( "127.0.0.1", 7999 ) )
    socket.socket.connect( object(), "/tmp/a-unix-socket" )
    assert recorder.seen == [ ( "127.0.0.1", 7999 ), "/tmp/a-unix-socket" ] and calls[ "socket.connect_external" ] == 1


def test_a_client_library_that_is_not_installed_is_named_and_skipped( restore_patched, capsys ):
    restore_patched.setitem( sys.modules, "anthropic", None )
    restore_patched.setitem( sys.modules, "openai", None )
    zmp.install_guards( collections.Counter() )
    out = capsys.readouterr().out
    assert "(anthropic not installed)" in out and "(openai not installed)" in out
    assert out.count( "not installed" ) == 3   # Anthropic and AsyncAnthropic each report; OpenAI once


def test_pick_slice_takes_the_first_asks_of_each_type_that_carry_a_vector_and_skips_the_rest():
    vector = [ 0.1 ]
    asks   = [ { "id": "a", "response_type": "yes_no",           "question_embedding": None },     # no vector
               { "id": "b", "response_type": "yes_no",           "question_embedding": vector },
               { "id": "c", "response_type": "open_ended",       "question_embedding": vector },   # other type
               { "id": "d", "response_type": "multiple_choice",  "question_embedding": vector },
               { "id": "e", "response_type": "yes_no",           "question_embedding": vector },   # over the cap
               { "id": "f", "response_type": "multiple_choice",  "question_embedding": vector } ]   # over the cap
    ids, counts = zmp.pick_slice( asks, 1 )
    assert ids == [ "b", "d" ] and dict( counts ) == { "yes_no": 1, "multiple_choice": 1 }


class _Engine:
    """A PredictionEngine double; the class attribute decides whether its model getter raises."""
    raises             = True
    recency_half_life_days = 14

    @classmethod
    def reset( cls ): pass

    def __init__( self, debug=False ): pass

    def _get_llm_client( self ):
        if self.raises: raise AssertionError( "MODEL CALL ATTEMPTED: double" )
        return None


class _Session:
    def __enter__( self ): return self
    def __exit__( self, *error ): return False


def _wire_main( monkeypatch, tmp_path, replay_result, engine_raises=True, attempts=0 ):
    """Replace everything main reaches; return the list of ( ids ) the replay was asked for."""
    asks    = [ { "id": "b", "response_type": "yes_no",          "question_embedding": [ 0.1 ] },
                { "id": "d", "response_type": "multiple_choice", "question_embedding": [ 0.1 ] } ]
    asked   = []
    _Engine.raises = engine_raises

    def fake_install( calls ):
        if attempts: calls[ "fake.model" ] += attempts

    def fake_replay( all_asks, engine, snapshot, baselines, target_types, target_ids ):
        asked.append( sorted( target_ids ) )
        return replay_result

    monkeypatch.setattr( zmp, "install_guards", fake_install )
    monkeypatch.setattr( PredictionEngine, "reset", _Engine.reset )
    monkeypatch.setattr( "cosa.agents.prediction_engine.prediction_engine.PredictionEngine", _Engine )
    monkeypatch.setattr( "cosa.research.preference_replay.question_vectors.load_side_file", lambda path: ( { "model": "m" }, {} ) )
    monkeypatch.setattr( "cosa.research.preference_replay.retune_run.read_cohort", lambda session, vectors: ( asks, { "database": "scratch_db" } ) )
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: _Session() )
    monkeypatch.setattr( "cosa.research.preference_replay.replay_loop.replay", fake_replay )
    monkeypatch.setattr( "cosa.research.preference_replay.three_way_report.make_three_way_arm", lambda half_life: ( lambda ask, rows: None ) )
    return asked


RUN_COUNT = { "records": { "engine": [ 1, 2 ], "three_way": [ 1, 2 ] }, "not_replayable": 0 }
RUN_LIST  = { "records": { "engine": [ 1 ] }, "not_replayable": [ "x", "y" ] }


def test_main_passes_the_slice_to_the_replay_and_returns_zero_when_no_call_was_attempted_and_the_control_fired( monkeypatch, tmp_path, capsys ):
    asked = _wire_main( monkeypatch, tmp_path, RUN_COUNT )
    assert zmp.main( [ "--vectors", "ignored", "--per-type", "5" ] ) == 0
    out = capsys.readouterr().out
    assert asked == [ [ "b", "d" ] ] and "cohort read 2 scratch_db" in out
    assert "model-call attempts: 0" in out and "positive control fired" in out
    assert "not_replayable 0" in out and "'three_way': 2" in out


def test_main_counts_a_list_of_not_replayable_ids_and_the_default_slice_size( monkeypatch, tmp_path, capsys ):
    _wire_main( monkeypatch, tmp_path, RUN_LIST )
    assert zmp.main( [ "--vectors", "ignored" ] ) == 0
    assert "not_replayable 2" in capsys.readouterr().out


def test_main_returns_one_when_a_model_call_was_attempted( monkeypatch, tmp_path, capsys ):
    _wire_main( monkeypatch, tmp_path, RUN_COUNT, attempts=3 )
    assert zmp.main( [ "--vectors", "ignored" ] ) == 1
    assert "model-call attempts: {'fake.model': 3}" in capsys.readouterr().out


def test_main_returns_one_when_the_positive_control_did_not_fire( monkeypatch, tmp_path, capsys ):
    _wire_main( monkeypatch, tmp_path, RUN_COUNT, engine_raises=False )
    assert zmp.main( [ "--vectors", "ignored" ] ) == 1
    assert "positive control fired" not in capsys.readouterr().out


def test_run_as_a_script_exits_with_mains_code( monkeypatch, restore_patched, tmp_path ):
    _wire_main( monkeypatch, tmp_path, RUN_COUNT )
    monkeypatch.setattr( sys, "argv", [ "zero_model_proof.py", "--vectors", "ignored" ] )
    monkeypatch.setitem( sys.modules, "anthropic", None )
    monkeypatch.setitem( sys.modules, "openai", None )
    with pytest.raises( SystemExit ) as raised: runpy.run_path( zmp.__file__, run_name="__main__" )
    assert raised.value.code == 0
