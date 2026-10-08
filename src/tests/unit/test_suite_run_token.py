"""
Unit tests for the per-run suite token store (cosa.rest.suite_run_token).

Each test names one rule a caller depends on.
A token checks only for the parent it was issued for.
It checks only until it expires, and only while that parent holds the slot.
A reason word is all a refusal ever reveals.
Venue: :7999 (unit, no server, no database).
"""

import pytest

import cosa.rest.suite_run_token as srt
from cosa.utils.secret_redaction import credential_env_values

PARENT = "ts-aaaa1111"


@pytest.fixture( autouse=True )
def _empty_store():
    srt.clear()
    yield
    srt.clear()


def _active( parent ):
    """A reader that reports `parent` as the monopolizer."""
    return lambda: parent


def test_a_fresh_token_checks_for_its_parent_while_that_parent_holds_the_slot():
    token = srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, token, _active( PARENT ), now=1 ) == ( True, None )


def test_the_token_is_long_url_safe_and_different_each_time():
    first, second = srt.issue( "a", 10 ), srt.issue( "b", 10 )
    assert first != second
    assert len( first ) >= 40
    assert all( c.isalnum() or c in "-_" for c in first )


def test_the_store_holds_a_digest_and_never_the_token():
    token = srt.issue( PARENT, 100, now=0 )
    assert token not in repr( srt._store )
    assert srt._store[ PARENT ][ 0 ] == srt._digest( token )
    assert len( srt._store[ PARENT ][ 0 ] ) == 64


def test_issue_without_a_clock_uses_the_monotonic_clock_and_still_checks():
    token = srt.issue( PARENT, 600 )
    assert srt.check( PARENT, token, _active( PARENT ) ) == ( True, None )


@pytest.mark.parametrize( "parent, ttl", [ ( "", 10 ), ( None, 10 ), ( PARENT, 0 ), ( PARENT, -5 ) ] )
def test_issue_refuses_an_empty_parent_and_a_non_positive_lifetime( parent, ttl ):
    with pytest.raises( ValueError ):
        srt.issue( parent, ttl )
    assert srt._store == { }


def test_a_parent_with_no_token_is_token_unknown():
    assert srt.check( PARENT, "anything", _active( PARENT ) ) == ( False, srt.REASON_UNKNOWN )


def test_a_token_for_another_parent_does_not_check_here():
    token = srt.issue( "ts-other", 100, now=0 )
    assert srt.check( PARENT, token, _active( PARENT ), now=1 ) == ( False, srt.REASON_UNKNOWN )


def test_a_wrong_token_is_token_mismatch():
    srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, "not-the-token", _active( PARENT ), now=1 ) == ( False, srt.REASON_MISMATCH )


def test_a_token_past_its_expiry_is_token_expired_and_the_expiry_instant_is_expired():
    token = srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, token, _active( PARENT ), now=99.9 ) == ( True, None )
    assert srt.check( PARENT, token, _active( PARENT ), now=100 ) == ( False, srt.REASON_EXPIRED )
    assert srt.check( PARENT, token, _active( PARENT ), now=5000 ) == ( False, srt.REASON_EXPIRED )


def test_a_token_whose_parent_no_longer_holds_the_slot_is_not_active_monopolizer():
    token = srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, token, _active( "ts-someone-else" ), now=1 ) == ( False, srt.REASON_NOT_ACTIVE )
    assert srt.check( PARENT, token, _active( None ), now=1 ) == ( False, srt.REASON_NOT_ACTIVE )


def test_the_slot_is_read_only_after_the_digest_and_expiry_pass():
    token  = srt.issue( PARENT, 100, now=0 )
    reads  = [ ]
    def reader():
        reads.append( 1 )
        return PARENT
    srt.check( PARENT, "wrong", reader, now=1 )
    srt.check( PARENT, token, reader, now=500 )
    srt.check( "ts-unknown", token, reader, now=1 )
    assert reads == [ ]
    srt.check( PARENT, token, reader, now=1 )
    assert reads == [ 1 ]


@pytest.mark.parametrize( "odd", [ None, "", 7, b"bytes", "tökén", "x" * ( srt.TOKEN_HEADER_MAX + 1 ), "y" * 10_000_000 ] )
def test_an_empty_odd_or_oversized_token_fails_closed_and_never_raises( odd ):
    srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, odd, _active( PARENT ), now=1 ) == ( False, srt.REASON_MISMATCH )


def test_a_token_of_exactly_the_cap_length_is_still_compared_not_refused_for_its_size():
    token = srt.issue( PARENT, 100, now=0 )
    assert len( token ) <= srt.TOKEN_HEADER_MAX
    assert srt.check( PARENT, "z" * srt.TOKEN_HEADER_MAX, _active( PARENT ), now=1 ) == ( False, srt.REASON_MISMATCH )
    assert srt.check( PARENT, token, _active( PARENT ), now=1 ) == ( True, None )


@pytest.mark.parametrize( "parent", [ None, "", 5, [ ] ] )
def test_an_odd_parent_id_is_token_unknown_and_never_raises( parent ):
    srt.issue( PARENT, 100, now=0 )
    assert srt.check( parent, "tok", _active( PARENT ), now=1 ) == ( False, srt.REASON_UNKNOWN )


def test_issuing_twice_for_one_parent_keeps_only_the_newer_token():
    old = srt.issue( PARENT, 100, now=0 )
    new = srt.issue( PARENT, 100, now=0 )
    assert srt.check( PARENT, old, _active( PARENT ), now=1 ) == ( False, srt.REASON_MISMATCH )
    assert srt.check( PARENT, new, _active( PARENT ), now=1 ) == ( True, None )


def test_revoke_makes_the_token_stop_checking_and_a_second_revoke_is_harmless():
    token = srt.issue( PARENT, 100, now=0 )
    srt.revoke( PARENT )
    assert srt.check( PARENT, token, _active( PARENT ), now=1 ) == ( False, srt.REASON_UNKNOWN )
    srt.revoke( PARENT )
    srt.revoke( "never-issued" )


def test_clear_forgets_every_token():
    first, second = srt.issue( "a", 100, now=0 ), srt.issue( "b", 100, now=0 )
    srt.clear()
    assert srt.check( "a", first, _active( "a" ), now=1 )[ 1 ] == srt.REASON_UNKNOWN
    assert srt.check( "b", second, _active( "b" ), now=1 )[ 1 ] == srt.REASON_UNKNOWN


def test_no_reason_word_contains_the_token():
    token = srt.issue( PARENT, 100, now=0 )
    reasons = { srt.REASON_UNKNOWN, srt.REASON_MISMATCH, srt.REASON_EXPIRED, srt.REASON_NOT_ACTIVE }
    assert not any( token in reason for reason in reasons )
    assert reasons == { "token_unknown", "token_mismatch", "token_expired", "not_active_monopolizer" }


def test_the_comparison_is_constant_time_and_the_digests_are_ascii( monkeypatch ):
    seen = [ ]
    real = srt.hmac.compare_digest
    def spy( a, b ):
        seen.append( ( a, b ) )
        return real( a, b )
    monkeypatch.setattr( srt.hmac, "compare_digest", spy )
    token = srt.issue( PARENT, 100, now=0 )
    srt.check( PARENT, token, _active( PARENT ), now=1 )
    assert len( seen ) == 1
    assert all( isinstance( side, str ) and side.isascii() and len( side ) == 64 for side in seen[ 0 ] )


def test_the_variable_name_keeps_a_credential_word_so_the_redaction_layer_hunts_its_value():
    """A rename that drops the credential word turns the by-value redaction off."""
    value = srt.issue( PARENT, 100, now=0 )
    hunted = credential_env_values( { srt.TOKEN_ENV_NAME: value, "LUPIN_TEST_MONOPOLIZE_PARENT_ID": PARENT + "-padding" } )
    assert value in hunted
    assert PARENT + "-padding" not in hunted
    assert srt.TOKEN_ENV_NAME == "LUPIN_TEST_MONOPOLIZE_PARENT_TOKEN"
    assert srt.TOKEN_HEADER == "X-Lupin-Lineage-Token"


@pytest.mark.parametrize( "odd", [ "tökén", "x" * ( srt.TOKEN_HEADER_MAX + 1 ), "y" * 10_000_000 ] )
def test_a_non_ascii_or_oversized_token_is_refused_before_it_is_hashed( odd, monkeypatch ):
    """The refusal comes from the shape check, so attacker-sized input never reaches the hash."""
    srt.issue( PARENT, 100, now=0 )
    hashed = [ ]
    real   = srt._digest
    monkeypatch.setattr( srt, "_digest", lambda t: hashed.append( len( t ) ) or real( t ) )
    assert srt.check( PARENT, odd, _active( PARENT ), now=1 ) == ( False, srt.REASON_MISMATCH )
    assert hashed == [ ]


class _Mgr:
    value = None
    def __init__( self, env_var_name ): self.env_var_name = env_var_name
    def get( self, key, default=None, return_type=None ):
        assert key == srt.TOKEN_ENABLED_KEY and return_type == "boolean"
        return default if self.value is None else self.value


@pytest.mark.parametrize( "configured, expected", [ ( None, False ), ( False, False ), ( True, True ) ] )
def test_the_switch_reads_the_ini_key_and_defaults_to_off( configured, expected, monkeypatch ):
    _Mgr.value = configured
    monkeypatch.setattr( srt, "ConfigurationManager", _Mgr )
    assert srt.token_enabled() is expected


BLOCK_CLI_ARGS = ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
                   "config_block_id=Lupin:+{block}" )


@pytest.mark.parametrize( "block, expected", [
    ( "Production",  False ),
    ( "Baseline",    False ),
    ( "Development", True ),
    ( "Testing",     True ),
    ( "Testing-GCS", True ),
] )
def test_the_shipped_ini_switches_the_token_on_only_for_test_and_dev_servers( block, expected, monkeypatch ):
    """The real ConfigurationManager over the shipped INI, one block at a time."""
    from cosa.config.configuration_manager import ConfigurationManager
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", BLOCK_CLI_ARGS.format( block=block ) )
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    try:
        assert srt.token_enabled() is expected
    finally:
        monkeypatch.undo()
        ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
