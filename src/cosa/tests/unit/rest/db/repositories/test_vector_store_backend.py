"""
Unit tests for the vector-store backend selector (the §6 flag seam) — including
the A1 rollback-path test (flag flip-back, which the design asserts but never
tested). No database needed: a stub config_mgr drives the flag value.

100% lines/branches/functions of vector_store_backend.py.
"""

import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories import vector_store_backend as vsb
from cosa.rest.db.repositories.vector_store_backend import (
    get_vector_store_backend, is_postgres_backend, LANCEDB, POSTGRES,
)


class _StubConfig:
    """Minimal config_mgr stand-in whose get() returns a fixed flag value."""

    def __init__( self, value ):
        self._value = value
        self.calls  = []

    def get( self, key, default=None, **kwargs ):
        self.calls.append( ( key, default ) )
        return self._value if self._value is not None else default


def test_default_is_lancedb_when_key_absent():
    cfg = _StubConfig( None )                       # get() falls back to default
    assert get_vector_store_backend( cfg ) == LANCEDB
    assert cfg.calls[ 0 ] == ( "vector store backend", LANCEDB )


def test_explicit_postgres():
    assert get_vector_store_backend( _StubConfig( "postgres" ) ) == POSTGRES


def test_value_is_lowercased_and_stripped():
    assert get_vector_store_backend( _StubConfig( "  POSTGRES  " ) ) == POSTGRES


def test_invalid_value_fails_loud():
    with pytest.raises( ValueError, match="Invalid 'vector store backend'" ):
        get_vector_store_backend( _StubConfig( "sqlite" ) )


def test_is_postgres_backend_true_and_false():
    assert is_postgres_backend( _StubConfig( "postgres" ) ) is True
    assert is_postgres_backend( _StubConfig( "lancedb" ) ) is False


def test_is_postgres_backend_propagates_valueerror():
    with pytest.raises( ValueError ):
        is_postgres_backend( _StubConfig( "nonsense" ) )


def test_none_config_mgr_builds_real_manager_and_reads_default():
    """Exercises the `config_mgr is None` branch against the real INI.

    Regression guard (bug 236c70ba): the committed default is now POSTGRES, per
    the RATIFIED v0.2.0 Lane C LanceDB->pgvector migration (commit 6d4ca864 —
    `vector store backend = postgres` in [Lupin: Baseline]). This assertion is a
    tripwire against a silent default-flip back to the pre-cutover LANCEDB path:
    if it ever reads 'lancedb' again, the migration has been regressed. (Was
    asserting LANCEDB pre-cutover; flipped 2026-07-11 after the merged tree read
    'postgres' — the stale assertion surfaced during the 3a14292b post-merge sweep.)
    """
    assert get_vector_store_backend() == POSTGRES


# ---------------------------------------------------------------------------
# A1 — rollback-path test: the §6 flip-back is asserted in the design but never
# tested. Prove postgres -> lancedb -> postgres all resolve correctly.
# ---------------------------------------------------------------------------
def test_a1_flag_flip_forward_then_rollback_then_forward():
    forward  = _StubConfig( POSTGRES )
    rollback = _StubConfig( LANCEDB )

    # Cutover: flip to postgres.
    assert get_vector_store_backend( forward ) == POSTGRES
    assert is_postgres_backend( forward ) is True

    # Rollback: flip BACK to lancedb (the untested path).
    assert get_vector_store_backend( rollback ) == LANCEDB
    assert is_postgres_backend( rollback ) is False

    # Re-cutover after rollback resolves to postgres again.
    assert is_postgres_backend( _StubConfig( POSTGRES ) ) is True


def test_module_exposes_valid_backend_tuple():
    assert vsb.VALID_BACKENDS == ( LANCEDB, POSTGRES )
