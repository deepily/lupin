"""
The need record: construction, the stable id and the validator's named refusals.
"""
import copy

import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import schema

DRAFTER = { "model": "claude-fable-5-1", "prompt_version": "needset-draft-0123456789", "server": "max-plan" }


def matched( **over ):
    """Build a valid matched need and apply overrides to the new_need arguments."""
    args = dict( kind="near_copy", write_lang="ts", selection_route=None, seed="a.b.seed", key_symbols=[ "a.b.twin" ], key_lang="ts", key_source="twin",
                 need="A function that formats a count of milliseconds as minutes and seconds.", source_commit="abc123", drafter=DRAFTER )
    args.update( over )
    return schema.new_need( **args )


def none_need():
    """Build a valid nothing-exists need."""
    return schema.new_need( "nothing", "py", None, None, [], None, None, "A function that rotates a list left by a given count.", "abc123", DRAFTER )


def test_new_need_builds_a_valid_drafted_record_with_a_stable_id():
    rec = matched()
    assert rec[ "status" ] == "drafted" and rec[ "check" ] is None and rec[ "key" ][ "version" ] == 1
    assert rec[ "id" ] == schema.need_id( rec ) and rec[ "id" ].startswith( "n-" ) and len( rec[ "id" ] ) == 12
    assert "smoke" not in rec
    shuffled = { k: rec[ k ] for k in reversed( list( rec ) ) }
    assert schema.need_id( shuffled ) == rec[ "id" ]


def test_the_id_follows_the_need_text_and_ignores_key_check_and_status():
    base = matched()
    assert matched( need="A function that pads a string on the left to a width." )[ "id" ] != base[ "id" ]
    changed = copy.deepcopy( base ); changed[ "key" ][ "version" ] = 2; changed[ "status" ] = "final"
    assert schema.need_id( changed ) == base[ "id" ]


def test_a_smoke_need_carries_the_flag_and_no_other_value_is_accepted():
    rec = matched( smoke=True )
    assert rec[ "smoke" ] is True
    rec[ "smoke" ] = False
    with pytest.raises( er.NeedsetError, match="smoke is only ever true" ): schema.validate_need( rec )


def test_a_routed_kind_needs_a_route_and_an_unrouted_kind_refuses_one():
    assert matched( kind="work_alike", selection_route="sampled", key_source="bm25" )[ "selection_route" ] == "sampled"
    assert matched( kind="cross_language", selection_route="vector", key_lang="py", key_source="vector" )[ "selection_route" ] == "vector"
    with pytest.raises( er.NeedsetError, match="selection_route must be one of" ): matched( kind="work_alike", selection_route=None, key_source="bm25" )
    with pytest.raises( er.NeedsetError, match="only for work_alike" ): matched( selection_route="vector" )


def test_a_nothing_need_has_no_seed_no_key_and_no_key_language():
    assert none_need()[ "key" ] == { "symbols": [], "key_lang": None, "source": None, "version": 1 }
    for bad in ( dict( seed="x" ), dict( key_symbols=[ "x" ] ), dict( key_lang="py" ), dict( key_source="bm25" ) ):
        args = dict( kind="nothing", write_lang="py", selection_route=None, seed=None, key_symbols=[], key_lang=None, key_source=None, need="A function that rotates a list left.", source_commit="c", drafter=DRAFTER )
        args.update( bad )
        with pytest.raises( er.NeedsetError, match="nothing need has no seed" ): schema.new_need( **args )


def test_a_matched_need_needs_a_seed_a_key_and_a_key_language():
    with pytest.raises( er.NeedsetError, match="needs a seed" ): matched( seed=None )
    with pytest.raises( er.NeedsetError, match="non-empty key" ): matched( key_symbols=[] )
    with pytest.raises( er.NeedsetError, match="key_lang" ): matched( key_lang="dart" )


@pytest.mark.parametrize( "key", schema.TOP_KEYS )
def test_every_top_level_key_is_required(key):
    rec = matched()
    del rec[ key ]
    with pytest.raises( er.NeedsetError, match="missing key" ): schema.validate_need( rec )


@pytest.mark.parametrize( "field, value, message", [
    ( "kind",          "twin",   "unknown kind" ),
    ( "write_lang",    "dart",   "unknown write_lang" ),
    ( "status",        "done",   "unknown status" ),
    ( "need",          "  ",     "need must be a non-empty string" ),
    ( "source_commit", 7,        "source_commit must be a non-empty string" ),
] )
def test_a_mistyped_field_is_refused_by_name(field, value, message):
    rec = matched()
    rec[ field ] = value
    with pytest.raises( er.NeedsetError, match=message ): schema.validate_need( rec )


@pytest.mark.parametrize( "key", [ { "symbols": "x", "key_lang": "ts", "version": 1 }, { "symbols": [ "" ], "key_lang": "ts", "version": 1 }, "x" ] )
def test_a_malformed_key_block_is_refused(key):
    rec = matched()
    rec[ "key" ] = key
    with pytest.raises( er.NeedsetError, match="key.symbols" ): schema.validate_need( rec )


@pytest.mark.parametrize( "version", [ 0, -1, True, "1" ] )
def test_the_key_version_is_a_positive_int(version):
    rec = matched()
    rec[ "key" ][ "version" ] = version
    with pytest.raises( er.NeedsetError, match="key.version" ): schema.validate_need( rec )


@pytest.mark.parametrize( "drafter", [ None, { "model": "m" }, { "model": "m", "prompt_version": "", "server": "s" } ] )
def test_the_drafter_block_needs_all_three_fields(drafter):
    rec = matched()
    rec[ "drafter" ] = drafter
    with pytest.raises( er.NeedsetError, match="drafter needs" ): schema.validate_need( rec )


def test_the_check_block_follows_the_status():
    rec = matched()
    rec[ "check" ] = { "model": "m", "result": "agree", "note": "", "mechanical": [] }
    with pytest.raises( er.NeedsetError, match="no check yet" ): schema.validate_need( rec )
    rec[ "status" ] = "checked"
    schema.validate_need( rec )
    del rec[ "check" ][ "note" ]
    with pytest.raises( er.NeedsetError, match="check block" ): schema.validate_need( rec )
    rec[ "check" ] = None
    with pytest.raises( er.NeedsetError, match="check block" ): schema.validate_need( rec )


def checked():
    """Build a valid checked need."""
    rec = matched()
    rec[ "status" ] = "checked"
    rec[ "check" ]  = { "model": "claude-opus-5-5", "result": "agree", "note": "does the job", "mechanical": [] }
    schema.validate_need( rec )
    return rec


def test_a_stale_id_is_refused_whatever_else_changed():
    rec = matched()
    rec[ "need" ] = "A function that pads a string on the left to a fixed width."
    with pytest.raises( er.NeedsetError, match="id does not match need_id" ): schema.validate_need( rec )
    rec[ "id" ] = schema.need_id( rec )
    schema.validate_need( rec )


@pytest.mark.parametrize( "key", schema.CHECK_KEYS )
def test_every_key_of_the_check_block_is_required(key):
    rec = checked()
    del rec[ "check" ][ key ]
    with pytest.raises( er.NeedsetError, match="check block" ): schema.validate_need( rec )


@pytest.mark.parametrize( "key, value, message", [
    ( "model",      "",        "check.model must be a non-empty string" ),
    ( "model",      3,         "check.model must be a non-empty string" ),
    ( "result",     "yes",     "check.result must be one of" ),
    ( "result",     None,      "check.result must be one of" ),
    ( "note",       None,      "check.note must be a string" ),
    ( "mechanical", "none",    "check.mechanical must be a list" ),
] )
def test_every_value_of_the_check_block_is_typed(key, value, message):
    rec = checked()
    rec[ "check" ][ key ] = value
    with pytest.raises( er.NeedsetError, match=message ): schema.validate_need( rec )


@pytest.mark.parametrize( "result", schema.RESULTS )
def test_each_check_result_is_accepted(result):
    rec = checked()
    rec[ "check" ][ "result" ] = result
    schema.validate_need( rec )


@pytest.mark.parametrize( "key", schema.DRAFTER_KEYS )
def test_every_key_of_the_drafter_block_is_required_and_non_empty(key):
    for broken in ( "delete", "" ):
        rec = matched()
        if broken == "delete": del rec[ "drafter" ][ key ]
        else: rec[ "drafter" ][ key ] = broken
        with pytest.raises( er.NeedsetError, match="drafter needs" ): schema.validate_need( rec )


@pytest.mark.parametrize( "key", [ "symbols", "key_lang", "version" ] )
def test_every_key_of_the_key_block_is_required(key):
    rec = matched()
    del rec[ "key" ][ key ]
    with pytest.raises( er.NeedsetError ): schema.validate_need( rec )


def test_a_record_that_is_not_a_dict_is_refused():
    with pytest.raises( er.NeedsetError, match="not a dict" ): schema.validate_need( [] )


def test_the_error_code_leads_the_message_and_is_kept():
    e = er.NeedsetError( er.BAD_NEED, "n-1: why" )
    assert str( e ) == "BAD_NEED: n-1: why" and e.code == "BAD_NEED" and e.detail == "n-1: why"
    assert str( er.NeedsetError( er.PACKET_LEAK ) ) == "PACKET_LEAK"


def test_the_key_source_follows_the_kind_and_the_route():
    assert matched()[ "key" ][ "source" ] == "twin"
    for source in ( "bm25", "directory", "random" ): assert matched( kind="work_alike", selection_route="sampled", key_source=source )[ "key" ][ "source" ] == source
    assert matched( kind="cross_language", selection_route="vector", key_source="vector" )[ "key" ][ "source" ] == "vector"
    bad = ( dict( kind="near_copy", key_source="bm25" ), dict( kind="work_alike", selection_route="sampled", key_source="twin" ),
            dict( kind="work_alike", selection_route="sampled", key_source="vector" ), dict( kind="work_alike", selection_route="vector", key_source="bm25" ),
            dict( kind="work_alike", selection_route="vector", key_source=None ) )
    for over in bad:
        with pytest.raises( er.NeedsetError, match="key.source must be one of" ): matched( **over )
