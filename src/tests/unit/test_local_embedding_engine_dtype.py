"""
Local embedding engines load the INI dtype and describe() reports the loaded one.

Fakes only: tiny torch modules stand in for the models, so no GPU and no download.
The fake loaders ignore the requested dtype and hand back float32, which is what
the real engines were measured doing.
"""

import sys
import types

import pytest
import torch
from unittest.mock import patch

from cosa.memory import local_embedding_engine as lee
from cosa.memory.local_embedding_engine import CodeEmbeddingEngine, ProseEmbeddingEngine


class _Cfg:
    """Config stub: INI values keyed by name."""
    def __init__( self, dtype ):
        self.values = {
            "local embedding code model name"        : "fake/code",
            "local embedding code model dimensions"  : "8",
            "local embedding prose model name"       : "fake/prose",
            "local embedding prose model dimensions" : "8",
            "local embedding prose matryoshka dim"   : "8",
            "local embedding device"                 : "cpu",
            "local embedding dtype"                  : dtype,
            "local embedding code query prefix"      : "q:",
            "local embedding prose query prefix"     : "q:",
            "local embedding prose document prefix"  : "d:",
            "debug local embedding"                  : "False",
        }

    def get( self, key, default=None ):
        return self.values.get( key, default if default is not None else "" )


class _FakeCodeModel( torch.nn.Module ):
    """SentenceTransformer stand-in: float32 weights, indexable, with a commit hash."""
    def __init__( self ):
        super().__init__()
        self.lin = torch.nn.Linear( 2, 2 )
        inner    = types.SimpleNamespace( auto_model=types.SimpleNamespace( config=types.SimpleNamespace( _commit_hash="abc" ) ) )
        self._inner = inner

    def __getitem__( self, i ):
        return self._inner


class _FakeProseModel( torch.nn.Module ):
    """AutoModel stand-in: float32 weights, has config._commit_hash."""
    def __init__( self ):
        super().__init__()
        self.lin    = torch.nn.Linear( 2, 2 )
        self.config = types.SimpleNamespace( _commit_hash="def" )


def _fresh_code_engine( dtype ):
    CodeEmbeddingEngine._instance = None
    with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_Cfg( dtype ) ):
        return CodeEmbeddingEngine( debug=False )


def _fresh_prose_engine( dtype ):
    ProseEmbeddingEngine._instance = None
    with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_Cfg( dtype ) ):
        return ProseEmbeddingEngine( debug=False )


@pytest.fixture( autouse=True )
def _clean_singletons():
    yield
    CodeEmbeddingEngine._instance  = None
    ProseEmbeddingEngine._instance = None


class TestHelpers:

    def test_loaded_dtype_name_none_when_no_model( self ):
        assert lee._loaded_dtype_name( None ) is None

    @pytest.mark.parametrize( "dtype, name", [ ( torch.float16, "float16" ), ( torch.float32, "float32" ), ( torch.bfloat16, "bfloat16" ) ] )
    def test_loaded_dtype_name_reads_parameters( self, dtype, name ):
        assert lee._loaded_dtype_name( torch.nn.Linear( 2, 2 ).to( dtype ) ) == name

    def test_enforce_dtype_casts_a_mismatched_model( self ):
        model = lee._enforce_dtype( torch.nn.Linear( 2, 2 ), torch.float16 )
        assert next( model.parameters() ).dtype == torch.float16

    def test_enforce_dtype_leaves_a_matching_model_untouched( self ):
        model = torch.nn.Linear( 2, 2 ).to( torch.float16 )
        with patch.object( torch.nn.Linear, "to", side_effect=AssertionError( "must not cast" ) ):
            assert lee._enforce_dtype( model, torch.float16 ) is model


class TestCodeEngineDtype:

    def _load( self, engine ):
        fake_st = types.SimpleNamespace( SentenceTransformer=lambda *a, **k: _FakeCodeModel() )
        with patch.dict( sys.modules, { "sentence_transformers": fake_st } ):
            engine._load_model()

    def test_describe_reports_the_ini_value_before_load( self ):
        engine = _fresh_code_engine( "float16" )
        assert engine.describe()[ "dtype" ] == "float16"

    def test_float16_ini_is_honoured_when_loader_returns_float32( self ):
        engine = _fresh_code_engine( "float16" )
        self._load( engine )
        assert next( engine._model.parameters() ).dtype == torch.float16
        assert engine.describe()[ "dtype" ] == "float16"

    def test_describe_reports_the_loaded_dtype_not_the_ini_string( self ):
        engine = _fresh_code_engine( "float32" )
        self._load( engine )
        engine._model.to( torch.bfloat16 )
        assert engine._dtype_str == "float32"
        assert engine.describe()[ "dtype" ] == "bfloat16"


class TestProseEngineDtype:

    def _load( self, engine ):
        fake_tf = types.SimpleNamespace(
            AutoTokenizer=types.SimpleNamespace( from_pretrained=lambda *a, **k: object() ),
            AutoModel=types.SimpleNamespace( from_pretrained=lambda *a, **k: _FakeProseModel() )
        )
        with patch.dict( sys.modules, { "transformers": fake_tf } ):
            engine._load_model()

    def test_describe_reports_the_ini_value_before_load( self ):
        engine = _fresh_prose_engine( "float16" )
        assert engine.describe()[ "dtype" ] == "float16"

    def test_float16_ini_is_honoured_when_loader_returns_float32( self ):
        engine = _fresh_prose_engine( "float16" )
        self._load( engine )
        assert next( engine._model.parameters() ).dtype == torch.float16
        assert engine.describe()[ "dtype" ] == "float16"

    def test_describe_reports_the_loaded_dtype_not_the_ini_string( self ):
        engine = _fresh_prose_engine( "float32" )
        self._load( engine )
        engine._model.to( torch.bfloat16 )
        assert engine.describe()[ "dtype" ] == "bfloat16"
