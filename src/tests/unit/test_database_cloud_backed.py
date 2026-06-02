"""
Unit tests for the LUPIN_CLOUD_BACKED cloud-backing gate (GCP M1, Decision 1).

Proves is_cloud_backed() decouples cloud-backing from the env NAME (explicit flag
wins; unset falls back to the legacy production-is-cloud invariant), and that
get_database_url() / get_pool_config() select the Cloud SQL path accordingly.

Pure-Python, non-mutating (create_engine is lazy — no DB connection), sub-second.
:7999-eligible / AI-discretionary. Full branch coverage of the new helper.
"""
import pytest

from cosa.rest.db.database import is_cloud_backed, get_database_url, get_pool_config


def _clear_env( monkeypatch ):
    monkeypatch.delenv( "LUPIN_CLOUD_BACKED", raising=False )
    monkeypatch.delenv( "LUPIN_ENV", raising=False )
    for k in ( "CLOUD_SQL_CONNECTION_NAME", "DB_PASSWORD", "DB_USER", "DB_NAME", "DB_HOST", "DB_PORT" ):
        monkeypatch.delenv( k, raising=False )


# ---- is_cloud_backed -------------------------------------------------------

@pytest.mark.parametrize( "value", [ "1", "true", "TRUE", "Yes", "on" ] )
def test_flag_truthy_forces_cloud_even_in_testing( monkeypatch, value ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )      # NOT production
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", value )
    assert is_cloud_backed() is True


@pytest.mark.parametrize( "value", [ "0", "false", "no", "off", "garbage" ] )
def test_flag_falsy_forces_non_cloud_even_if_set( monkeypatch, value ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", value )
    assert is_cloud_backed() is False


def test_env_name_never_implies_cloud( monkeypatch ):
    """Cloud-backing is NEVER inferred from the env name — production w/o flag is NOT cloud."""
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "production" )   # flag unset → still not cloud
    assert is_cloud_backed() is False


def test_unset_flag_testing_is_not_cloud( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    assert is_cloud_backed() is False


def test_unset_flag_default_dev_is_not_cloud( monkeypatch ):
    _clear_env( monkeypatch )                          # no LUPIN_ENV at all → development default
    assert is_cloud_backed() is False


def test_blank_flag_is_not_cloud( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "production" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "   " )  # blank → not cloud (env name irrelevant)
    assert is_cloud_backed() is False


# ---- get_database_url ------------------------------------------------------

def test_url_cloud_path_via_flag_in_testing( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "true" )
    monkeypatch.setenv( "CLOUD_SQL_CONNECTION_NAME", "proj:us-central1:lupin-test" )
    monkeypatch.setenv( "DB_PASSWORD", "secret" )
    url = get_database_url()
    assert "host=/cloudsql/proj:us-central1:lupin-test" in url
    assert "lupin_db_test" in url   # env-aware default for a cloud-backed testing env


def test_url_cloud_path_missing_inputs_raises( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "1" )    # cloud-backed but no instance/password
    with pytest.raises( ValueError, match="Cloud-backed" ):
        get_database_url()


def test_url_local_testing_when_flag_unset( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    url = get_database_url()
    assert "localhost" in url and "lupin_db_test" in url
    assert "cloudsql" not in url


def test_url_cloud_path_via_flag_in_production( monkeypatch ):
    """Cloud path is reached via the flag, and the prod env picks the prod DB-name default."""
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "production" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "true" )
    monkeypatch.setenv( "CLOUD_SQL_CONNECTION_NAME", "proj:us-central1:lupin-prod" )
    monkeypatch.setenv( "DB_PASSWORD", "secret" )
    url = get_database_url()
    assert "host=/cloudsql/proj:us-central1:lupin-prod" in url
    assert "lupin_db_prod" in url


def test_url_production_without_flag_is_not_cloud( monkeypatch ):
    """Env name alone must NOT select Cloud SQL — production w/o flag falls to local."""
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "production" )
    url = get_database_url()
    assert "cloudsql" not in url
    assert "localhost" in url


def test_url_dev_default( monkeypatch ):
    _clear_env( monkeypatch )                          # development default
    url = get_database_url()
    assert "localhost" in url and "lupin_db_dev" in url


# ---- get_pool_config -------------------------------------------------------

def test_pool_cloud_backed_uses_cloud_sql_pooling( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    monkeypatch.setenv( "LUPIN_CLOUD_BACKED", "true" )
    cfg = get_pool_config()
    assert cfg[ "pool_size" ] == 5 and cfg[ "pool_recycle" ] == 3600


def test_pool_local_testing_uses_nullpool( monkeypatch ):
    _clear_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )       # flag unset → local test isolation
    cfg = get_pool_config()
    assert "poolclass" in cfg


def test_pool_dev_uses_higher_pooling( monkeypatch ):
    _clear_env( monkeypatch )
    cfg = get_pool_config()
    assert cfg[ "pool_size" ] == 10
