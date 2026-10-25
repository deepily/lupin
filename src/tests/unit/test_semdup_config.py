"""
Unit tests for semdup errors and config: freeze, drift check and policy refusal.
"""
import json
import os

import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.semdup import config as cf
from cosa.repo.semdup import errors as err

PROMPT  = "You rule on whether two functions do the same job."
USER    = "Definition: {definition}\nCandidates: {candidates}"
PARSER  = "def parse_reply( text, labels ): return json.loads( text )"
SCRUB   = [ "check_exists", "fetch_similar", "SEARCHED" ]
JSCPD   = { "version": "4.0.5", "min_tokens": 50, "min_lines": 5, "chosen_in": "default" }
DECIDED = { "backend": "max-plan", "temperature": "unsettable:bounded-cc", "unscorable_policy": "worst-rank" }


def make( **over ):
    """Build a configuration with the decided values, overriding any argument by keyword."""
    args = { **DECIDED, "system_prompt": PROMPT, "user_template": USER, "parser_source": PARSER, "scrub": SCRUB, "body_chars": 4000, "jscpd": JSCPD }
    return cf.build_config( **{ **args, **over } )


def test_every_error_code_is_listed_once_and_there_are_fourteen():
    named = { v for k, v in vars( err ).items() if k.isupper() and k != "CODES" }
    assert named == err.CODES and len( err.CODES ) == 14
    assert all( getattr( err, code ) == code for code in err.CODES )


def test_an_error_carries_its_code_and_detail_and_prints_both():
    e = err.SemdupError( err.NO_FLAGS, "the proof raised none" )
    assert ( e.code, e.detail, str( e ) ) == ( "NO_FLAGS", "the proof raised none", "NO_FLAGS: the proof raised none" )


def test_an_unknown_code_is_refused_at_construction():
    with pytest.raises( ValueError, match="unknown semdup error code 'NOPE'" ):
        err.SemdupError( "NOPE", "x" )


def test_build_config_holds_exactly_the_documented_fields_with_the_fixed_constants():
    cfg = make()
    assert sorted( cfg ) == sorted( [ "model_id", "backend", "temperature", "unscorable_policy", "prompt_version", "system_prompt_sha", "parser_sha",
                                      "min_nodes", "max_candidates", "min_candidates", "list_depth", "fusion_head", "body_chars", "clone_cover",
                                      "jscpd", "scrub_sha", "config_sha" ] )
    assert ( cfg[ "model_id" ], cfg[ "max_candidates" ], cfg[ "min_candidates" ], cfg[ "list_depth" ], cfg[ "fusion_head" ], cfg[ "clone_cover" ] ) == ( "claude-fable-5-1", 10, 5, 10, 2, 0.5 )
    assert cfg[ "min_nodes" ] == 25 and cfg[ "body_chars" ] == 4000 and cfg[ "jscpd" ] == JSCPD
    assert cfg[ "config_sha" ] == cf.config_sha( cfg ) and len( cfg[ "config_sha" ] ) == 64


def test_prompt_version_is_the_transports_version_of_the_prompt_template_and_parser():
    assert make()[ "prompt_version" ] == model_transport.prompt_version( "semdup", PROMPT, USER, PARSER )
    assert make()[ "prompt_version" ].startswith( "semdup-" )


@pytest.mark.parametrize( "over", [
    { "system_prompt": PROMPT.replace( "same", "equal" ) },
    { "user_template": USER + " " },
    { "parser_source": PARSER.replace( "loads", "load" ) },
] )
def test_one_word_of_the_prompt_template_or_parser_changes_the_prompt_version_and_the_sha( over ):
    base, other = make(), make( **over )
    assert other[ "prompt_version" ] != base[ "prompt_version" ] and other[ "config_sha" ] != base[ "config_sha" ]


def test_the_scrub_sha_ignores_token_order_but_not_content():
    assert make( scrub=list( reversed( SCRUB ) ) )[ "scrub_sha" ] == make()[ "scrub_sha" ]
    assert make( scrub=SCRUB + [ "record_search" ] )[ "scrub_sha" ] != make()[ "scrub_sha" ]


@pytest.mark.parametrize( "bad", [ { "version": "4.0.5" }, { **JSCPD, "extra": 1 } ] )
def test_jscpd_must_hold_exactly_its_four_keys( bad ):
    with pytest.raises( ValueError, match="jscpd must hold exactly" ):
        make( jscpd=bad )


def test_config_sha_ignores_key_order_and_the_stored_sha_field():
    cfg = make()
    shuffled = dict( reversed( list( cfg.items() ) ) )
    assert cf.config_sha( shuffled ) == cfg[ "config_sha" ]
    assert cf.config_sha( { **cfg, "config_sha": "x" } ) == cfg[ "config_sha" ]


@pytest.mark.parametrize( "value, empty", [ ( None, True ), ( "", True ), ( "  \t", True ), ( 0, False ), ( 0.0, False ), ( "unsettable:bounded-cc", False ), ( "max-plan", False ) ] )
def test_is_empty_treats_zero_as_set( value, empty ):
    assert cf.is_empty( value ) is empty


def test_freeze_writes_the_file_once_and_returns_the_sha(tmp_path):
    path = str( tmp_path / "nested" / "semdup-frozen-1.json" )
    cfg  = make()
    assert cf.freeze( cfg, path ) == cfg[ "config_sha" ]
    assert json.load( open( path ) ) == cfg


def test_a_failed_write_leaves_no_frozen_file_and_no_temporary_file_so_a_later_freeze_still_works(tmp_path, monkeypatch):
    path = str( tmp_path / "f.json" )
    real = cf.os.link
    def broken( src, dst ): raise OSError( "disk went away" )
    monkeypatch.setattr( cf.os, "link", broken )
    with pytest.raises( OSError, match="disk went away" ):
        cf.freeze( make(), path )
    assert os.listdir( tmp_path ) == []
    monkeypatch.setattr( cf.os, "link", real )
    assert cf.freeze( make(), path ) and os.listdir( tmp_path ) == [ "f.json" ]


def test_freezing_leaves_exactly_the_frozen_file_in_its_folder(tmp_path):
    cf.freeze( make(), str( tmp_path / "f.json" ) )
    assert os.listdir( tmp_path ) == [ "f.json" ]


def test_the_sha_is_the_sha256_of_sorted_compact_json_without_the_sha_field():
    import hashlib
    cfg = { "b": [ 2, 3 ], "a": 1, "config_sha": "ignored" }
    assert cf.config_sha( cfg ) == hashlib.sha256( b'{"a":1,"b":[2,3]}' ).hexdigest()


def test_freeze_accepts_a_temperature_of_zero(tmp_path):
    assert cf.freeze( make( backend="work-server", temperature=0 ), str( tmp_path / "f.json" ) )


def test_refreezing_is_refused_and_leaves_the_first_file_untouched(tmp_path):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    before = open( path ).read()
    with pytest.raises( err.SemdupError ) as caught:
        cf.freeze( make( body_chars=1 ), path )
    assert caught.value.code == err.CONFIG_ALREADY_FROZEN and open( path ).read() == before


@pytest.mark.parametrize( "over, named", [
    ( { "backend": None },        "backend" ),
    ( { "backend": "" },          "backend" ),
    ( { "temperature": None },    "temperature" ),
    ( { "temperature": " " },     "temperature" ),
    ( { "backend": None, "temperature": None }, "backend and temperature" ),
] )
def test_freeze_refuses_an_undecided_backend_or_temperature_and_writes_nothing( tmp_path, over, named ):
    path = str( tmp_path / "new-folder" / "f.json" )
    with pytest.raises( err.SemdupError ) as caught:
        cf.freeze( make( **over ), path )
    assert caught.value.code == err.CONFIG_UNDECIDED and named in caught.value.detail
    assert not os.path.exists( path ) and not os.path.exists( os.path.dirname( path ) )


def test_freeze_does_not_need_the_unscorable_policy(tmp_path):
    assert cf.freeze( make( unscorable_policy="" ), str( tmp_path / "f.json" ) )


def test_freeze_refuses_a_configuration_edited_after_it_was_built(tmp_path):
    cfg = make()
    cfg[ "max_candidates" ] = 99
    with pytest.raises( err.SemdupError ) as caught:
        cf.freeze( cfg, str( tmp_path / "f.json" ) )
    assert caught.value.code == err.CONFIG_DRIFT and not os.path.exists( tmp_path / "f.json" )


def test_verify_frozen_returns_the_frozen_configuration_when_nothing_moved(tmp_path):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    assert cf.verify_frozen( path, make() ) == make()


@pytest.mark.parametrize( "field", sorted( set( make() ) - { "config_sha" } ) )
def test_each_live_field_is_compared_on_its_own_and_named_when_it_differs( tmp_path, field ):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    live = make()
    live[ field ] = "different" if field != "jscpd" else { **JSCPD, "min_tokens": 51 }
    with pytest.raises( err.SemdupError ) as caught:
        cf.verify_frozen( path, live )
    assert caught.value.code == err.CONFIG_DRIFT and field in caught.value.detail.split( ": " )[ 1 ].split( ", " )


def test_a_field_only_the_live_configuration_has_is_drift_and_so_is_one_only_the_frozen_file_has(tmp_path):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    live_extra = { **make(), "added_since_freeze": 1 }
    with pytest.raises( err.SemdupError, match="added_since_freeze" ) as caught:
        cf.verify_frozen( path, live_extra )
    assert caught.value.code == err.CONFIG_DRIFT
    live_short = { key: value for key, value in make().items() if key != "body_chars" }
    with pytest.raises( err.SemdupError, match="body_chars" ) as caught:
        cf.verify_frozen( path, live_short )
    assert caught.value.code == err.CONFIG_DRIFT


def test_the_stored_sha_field_is_checked_against_the_file_and_not_against_live(tmp_path):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    assert cf.verify_frozen( path, { **make(), "config_sha": "anything" } ) == make()


@pytest.mark.parametrize( "over", [
    { "system_prompt": PROMPT.replace( "same", "equal" ) },
    { "backend": "work-server" },
    { "scrub": SCRUB + [ "x" ] },
    { "body_chars": 4001 },
] )
def test_code_that_moved_since_the_freeze_is_refused( tmp_path, over ):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    with pytest.raises( err.SemdupError ) as caught:
        cf.verify_frozen( path, make( **over ) )
    assert caught.value.code == err.CONFIG_DRIFT


def test_a_frozen_file_edited_by_hand_fails_its_own_sha(tmp_path):
    path = str( tmp_path / "f.json" )
    cf.freeze( make(), path )
    text = open( path ).read().replace( '"model_id": "claude-fable-5-1"', '"model_id": "claude-opus-5-5"' )
    open( path, "w" ).write( text )
    with pytest.raises( err.SemdupError, match="recomputes to" ) as caught:
        cf.verify_frozen( path, make() )
    assert caught.value.code == err.CONFIG_DRIFT


def test_verify_frozen_with_no_file_raises_rather_than_passing(tmp_path):
    with pytest.raises( FileNotFoundError ):
        cf.verify_frozen( str( tmp_path / "missing.json" ), make() )
