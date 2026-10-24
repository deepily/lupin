"""
The need record of the diagnostic set, and its validator.

A need is one plain sentence an agent is about to build, paired with an answer key.
The key is the set of index symbols that already do the job, or none.
"""
import hashlib
import json

from lupin_mcp.reuse_needset import errors as er

NEED_FORMAT = "needset-need-1"
KINDS       = ( "near_copy", "work_alike", "cross_language", "nothing" )
LANGS       = ( "py", "ts" )
ROUTES      = ( "vector", "sampled" )
STATUSES    = ( "drafted", "checked", "labelled", "final" )
ROUTED      = ( "work_alike", "cross_language" )
TOP_KEYS    = ( "id", "kind", "write_lang", "seed", "selection_route", "key", "need", "source_commit", "drafter", "check", "status" )
DRAFTER_KEYS = ( "model", "prompt_version", "server" )
CHECK_KEYS   = ( "model", "result", "note", "mechanical" )
RESULTS      = ( "agree", "disagree", "unsure" )


def need_id( rec ):
    """
    Return the stable id of a need.

    Requires:
        - rec holds kind, write_lang, seed, need and source_commit

    Ensures:
        - returns "n-" and 10 hex digits of the sha256 of those five fields in a fixed order
        - the id does not depend on the key order of rec, on its key, check or status
    """
    parts = [ rec[ "kind" ], rec[ "write_lang" ], rec[ "seed" ], rec[ "need" ], rec[ "source_commit" ] ]
    return "n-" + hashlib.sha256( json.dumps( parts, sort_keys=True ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def new_need( kind, write_lang, seed, selection_route, key_symbols, key_lang, need, source_commit, drafter, smoke=False ):
    """
    Build a freshly drafted need record.

    Requires:
        - the arguments satisfy validate_need once assembled
        - drafter holds model, prompt_version and server

    Ensures:
        - returns a validated record with status "drafted", key version 1 and no check
        - carries "smoke": true only when smoke is true

    Raises:
        - NeedsetError BAD_NEED when the assembled record is invalid
    """
    rec = { "kind": kind, "write_lang": write_lang, "seed": seed, "selection_route": selection_route,
            "key": { "symbols": list( key_symbols ), "key_lang": key_lang, "version": 1 },
            "need": need, "source_commit": source_commit, "drafter": dict( drafter ), "check": None, "status": "drafted" }
    rec[ "id" ] = need_id( rec )
    if smoke: rec[ "smoke" ] = True
    validate_need( rec )
    return rec


def _fail( rec, why ):
    """Raises: NeedsetError BAD_NEED naming the need and the reason."""
    name = rec.get( "id", "?" ) if isinstance( rec, dict ) else "?"
    raise er.NeedsetError( er.BAD_NEED, f"{name}: {why}" )


def _text( value ):
    """Ensures: returns True for a non-empty string."""
    return isinstance( value, str ) and value.strip() != ""


def validate_need( rec ):
    """
    Check one need record against the needset-need-1 format.

    Requires:
        - rec is any object

    Ensures:
        - returns None when the record is valid
        - a matched kind has a seed and a non-empty key; a nothing need has neither
        - selection_route is vector or sampled for the two routed kinds and None otherwise
        - a record at status checked or later carries a check block with a model, a result of agree, disagree or unsure, a note and a mechanical list
        - the id equals need_id of the record

    Raises:
        - NeedsetError BAD_NEED naming the first violation
    """
    if not isinstance( rec, dict ): _fail( rec, "not a dict" )
    for k in TOP_KEYS:
        if k not in rec: _fail( rec, f"missing key {k!r}" )
    if rec[ "kind" ] not in KINDS: _fail( rec, f"unknown kind {rec[ 'kind' ]!r}" )
    if rec[ "write_lang" ] not in LANGS: _fail( rec, f"unknown write_lang {rec[ 'write_lang' ]!r}" )
    if rec[ "status" ] not in STATUSES: _fail( rec, f"unknown status {rec[ 'status' ]!r}" )
    for k in ( "need", "source_commit" ):
        if not _text( rec[ k ] ): _fail( rec, f"{k} must be a non-empty string" )
    key = rec[ "key" ]
    if not isinstance( key, dict ) or not isinstance( key.get( "symbols" ), list ) or not all( _text( s ) for s in key[ "symbols" ] ): _fail( rec, "key.symbols must be a list of ids" )
    if not isinstance( key.get( "version" ), int ) or isinstance( key[ "version" ], bool ) or key[ "version" ] < 1: _fail( rec, "key.version must be a positive int" )
    if rec[ "kind" ] == "nothing":
        if rec[ "seed" ] is not None or key[ "symbols" ] or key.get( "key_lang" ) is not None: _fail( rec, "a nothing need has no seed, no key symbols and no key_lang" )
    else:
        if not _text( rec[ "seed" ] ): _fail( rec, "a matched need needs a seed" )
        if not key[ "symbols" ]: _fail( rec, "a matched need needs a non-empty key" )
        if key.get( "key_lang" ) not in LANGS: _fail( rec, "key.key_lang must be py or ts" )
    if rec[ "kind" ] in ROUTED:
        if rec[ "selection_route" ] not in ROUTES: _fail( rec, f"selection_route must be one of {ROUTES}" )
    elif rec[ "selection_route" ] is not None: _fail( rec, "selection_route is only for work_alike and cross_language" )
    drafter = rec[ "drafter" ]
    if not isinstance( drafter, dict ) or not all( _text( drafter.get( k ) ) for k in DRAFTER_KEYS ): _fail( rec, f"drafter needs {DRAFTER_KEYS}" )
    check = rec[ "check" ]
    if rec[ "status" ] == "drafted":
        if check is not None: _fail( rec, "a drafted need has no check yet" )
    else:
        if not isinstance( check, dict ) or any( k not in check for k in CHECK_KEYS ): _fail( rec, f"a checked need needs a check block with {CHECK_KEYS}" )
        if not _text( check[ "model" ] ): _fail( rec, "check.model must be a non-empty string" )
        if check[ "result" ] not in RESULTS: _fail( rec, f"check.result must be one of {RESULTS}" )
        if not isinstance( check[ "note" ], str ): _fail( rec, "check.note must be a string" )
        if not isinstance( check[ "mechanical" ], list ): _fail( rec, "check.mechanical must be a list" )
    if "smoke" in rec and rec[ "smoke" ] is not True: _fail( rec, "smoke is only ever true" )
    if rec[ "id" ] != need_id( rec ): _fail( rec, f"id does not match need_id: {need_id( rec )}" )
