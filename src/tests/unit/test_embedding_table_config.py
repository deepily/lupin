"""
Unit tests for the shared embedding-table constructor setup.

Twin refactor slice memory-core: EmbeddingCacheTable and QueryLogTable carried the same __init__ body.
"""

import pytest

import cosa.memory.embedding_provider as ep
from cosa.memory.embedding_cache_table import EmbeddingCacheTable
from cosa.memory.query_log_table import QueryLogTable


class _FakeConfig:
    def __init__( self, env_var_name ):
        self.env_var_name = env_var_name

    def get( self, key, default=None ):
        assert key == "embedding dimensions"
        return "384"


@pytest.fixture
def fake_config( monkeypatch ):
    monkeypatch.setattr( ep, "ConfigurationManager", _FakeConfig )


class _Bare:
    pass


def test_the_helper_sets_the_four_attributes( fake_config ):
    table = _Bare()
    ep.init_embedding_table_config( table, True, False )

    assert ( table.debug, table.verbose ) == ( True, False )
    assert table._config_mgr.env_var_name == "LUPIN_CONFIG_MGR_CLI_ARGS"
    assert table._embedding_dim == 384


@pytest.mark.parametrize( "cls", [ EmbeddingCacheTable, QueryLogTable ] )
def test_each_table_constructs_through_the_helper( cls, fake_config, monkeypatch ):
    calls = []
    module = __import__( cls.__module__, fromlist = [ "x" ] )
    monkeypatch.setattr( module, "init_embedding_table_config", lambda table, debug, verbose: calls.append( ( table, debug, verbose ) ) )

    table = cls( debug = True, verbose = True )
    assert calls == [ ( table, True, True ) ]


@pytest.mark.parametrize( "cls", [ EmbeddingCacheTable, QueryLogTable ] )
def test_each_table_ends_up_with_the_configured_dimension( cls, fake_config ):
    table = cls( debug = False, verbose = True )
    assert ( table.debug, table.verbose, table._embedding_dim ) == ( False, True, 384 )
