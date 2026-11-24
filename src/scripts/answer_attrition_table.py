"""
The attrition table: how many units of Rick's answer survive each pipeline step.

The script only reads. Every database is read through a SQLAlchemy session. Its first statement
makes the transaction read-only, as retune_run.read_cohort does, and the transaction is always
rolled back. The script writes a JSON result and a markdown receipt, and nothing else.

The units are the stance, the comment, typed Other text and each multi-select pick.
They also include an explicit empty selection and a timeout with the default it fell back to.
The last two are open-ended text and each field of a batch open-ended answer.
The six steps each name the symbol they measured.

Run it pinned to the tree. The live database needs the usual config environment:
    cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/answer_attrition_table.py \
        --archive io/phase4-archive-run-2/archive.sqlite --records io/phase4-archive-run-2/records.jsonl \
        --live --out-json <result.json> --out-md <receipt.md>
"""

import argparse
import json
import re
import subprocess
import types
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cosa.agents.prediction_engine import accuracy_comparators as ac
from cosa.agents.prediction_engine import context_baseline
from cosa.agents.prediction_engine.exposure import compare_draft_to_answer, decode_answer_fields, revealed_before_answer
from cosa.agents.prediction_engine.history_derive import attribution_tier, derive_answer
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.agents.prediction_engine.three_way_stance import neighbours_of
from cosa.agents.principle_learner.extractor_rules import field_answers, owners_own_answer
from cosa.research.preference_replay import replay_loop
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import extract_qualifier_comment

WINDOW_START = "2026-09-10"
STANCES      = ( "yes", "no", "neither" )
WHOLE        = "$answer"
UNIT_TAGS    = ( "stance:yes", "stance:no", "stance:neither", "stance:none", "comment", "typed_other", "multi_pick", "single_listed_pick",
                 "empty_selection", "open_text", "batch_field", "timeout" )
SQL_ROWS     = ( "SELECT id, recipient_id, response_type, response_value, response_options, created_at, responded_at, sender_id "
                 "FROM notifications WHERE response_value IS NOT NULL AND response_type IN ( 'yes_no', 'multiple_choice', 'open_ended_batch', 'open_ended' )" )
SQL_EVIDENCE = "SELECT notification_id, field_key, retracted_at FROM preference_evidence"
SQL_LOG      = "SELECT notification_id, fold_opened_at, draft_at_reveal FROM prediction_log WHERE fold_opened_at IS NOT NULL"
READ_ONLY    = { "postgresql": "SET TRANSACTION READ ONLY", "sqlite": "PRAGMA query_only = ON" }

# step column -> the symbol it measured, in step order
STEP_SYMBOLS = {
    "1p_production_readers"            : "notification_utils.extract_qualifier_comment and exposure.decode_answer_fields",
    "1c_plain_first_word_reader"       : "a plain first-word reader (the control)",
    "2_derive_answer"                  : "history_derive.derive_answer",
    "3_field_answers"                  : "extractor_rules.field_answers",
    "3g_after_extractor_gates"         : "extractor_rules.owners_own_answer and review_card.is_review_card",
    "4_evidence_linked"                : "preference_evidence rows, keyed by notification and field",
    "4n_neighbours_of"                 : "three_way_stance.neighbours_of, run on the stored decision",
    "5a_lookup_case_store"             : "PredictionEngine._store_decision",
    "5a_lookup_counts_as_vote"         : "PredictionEngine._normalise_text and the stored decision's own readers",
    "5b_model_prompt"                  : "context_baseline.build_user_prompt",
    "6_scorer_moves_match"             : "replay_loop._score and accuracy_comparators",
    "6_comment_computed_beside"        : "accuracy_comparators.compare_yes_no (qualifier_match)",
    "6_typed_scored_as_miss_switch_off": "accuracy_comparators.compare_multiple_choice, per-field switch off",
    "6_typed_left_out_switch_on"       : "accuracy_comparators.compare_multiple_choice, per-field switch on",
}


def norm_id( value ):
    """
    Return an id with hyphens removed and lower case.

    Requires:
        - value has a string form

    Ensures:
        - the archive's hyphen-free ids and the app's hyphenated ids compare equal
    """
    return str( value ).replace( "-", "" ).lower()


def as_json( value ):
    """
    Decode a JSON text; pass a decoded value through.

    Requires:
        - value is any stored value

    Ensures:
        - returns the decoded value for a str or bytes that holds JSON, None for one that does not, and any other value unchanged
    """
    if isinstance( value, ( str, bytes ) ):
        try: return json.loads( value )
        except ValueError: return None
    return value


# ---------------------------------------------------------------- read only loaders

def set_read_only( session ):
    """
    Make the session's transaction refuse writes, as the first statement.

    Requires:
        - session is an active SQLAlchemy session on PostgreSQL or SQLite

    Ensures:
        - a later write in the same transaction fails

    Raises:
        - ValueError naming the dialect when it has no read-only statement
    """
    dialect = session.get_bind().dialect.name
    if dialect not in READ_ONLY: raise ValueError( f"no read-only statement for dialect {dialect!r}" )
    session.execute( text( READ_ONLY[ dialect ] ) )


def clean_row( raw ):
    """
    Shape one notification row as the pipeline's code reads it.

    Requires:
        - raw is a mapping with id, recipient_id, response_value and response_options

    Ensures:
        - ids are strings, the recipient id is hyphenated, and both stored JSON columns are decoded
    """
    row = dict( raw )
    row[ "id" ]               = str( row[ "id" ] )
    row[ "recipient_id" ]     = str( uuid.UUID( str( row[ "recipient_id" ] ) ) )
    row[ "response_value" ]   = as_json( row[ "response_value" ] )
    row[ "response_options" ] = as_json( row[ "response_options" ] )
    return row


def read_tables( session ):
    """
    Read the answered rows, the evidence rows and the reveal log in a read-only transaction.

    Requires:
        - session is an active SQLAlchemy session on a database with notifications, preference_evidence and prediction_log

    Ensures:
        - the first statement makes the transaction read-only, and the transaction is rolled back even on an error
        - returns ( rows, evidence, log ) as lists of dicts, the rows shaped by clean_row
    """
    set_read_only( session )
    try:
        rows     = [ clean_row( r._mapping ) for r in session.execute( text( SQL_ROWS ) ) ]
        evidence = [ dict( r._mapping ) for r in session.execute( text( SQL_EVIDENCE ) ) ]
        log      = [ dict( r._mapping ) for r in session.execute( text( SQL_LOG ) ) ]
    finally:
        session.rollback()
    return rows, evidence, log


def open_archive_session( path ):
    """
    Open the run 2 archive through a read-only SQLite URI.

    Requires:
        - path is an existing SQLite file

    Ensures:
        - returns a session on a connection that cannot write to the file
    """
    return Session( create_engine( f"sqlite:///file:{path}?mode=ro&uri=true" ) )


def provenance():
    """
    Name the run: its time and the git sha it ran on.

    Ensures:
        - returns { "run_time_utc", "git_sha" }; the sha is "unknown" when git cannot say
    """
    done = subprocess.run( [ "git", "rev-parse", "HEAD" ], capture_output=True, text=True )
    return { "run_time_utc": datetime.now( timezone.utc ).isoformat( timespec="seconds" ),
             "git_sha"     : done.stdout.strip() if done.returncode == 0 else "unknown" }


# ---------------------------------------------------------------- units

def schema_of( options ):
    """
    Read a stored card schema into { header: { "labels": set, "multi": bool } }.

    Requires:
        - options is a stored response_options value, or None

    Ensures:
        - returns {} when it is not a schema
    """
    options = as_json( options )
    if not isinstance( options, dict ) or not isinstance( options.get( "questions" ), list ): return {}
    out = {}
    for q in options[ "questions" ]:
        if isinstance( q, dict ) and isinstance( q.get( "header" ), str ):
            labels = { o[ "label" ].strip() for o in ( q.get( "options" ) or [] ) if isinstance( o, dict ) and isinstance( o.get( "label" ), str ) }
            out[ q[ "header" ] ] = { "labels": labels, "multi": bool( q.get( "multi_select" ) ) }
    return out


def field_units( kind, header, value, labels ):
    """
    Classify one field's value into units, independent of the code under test.

    Requires:
        - value is a list (multi-select) or a string; labels is the set of labels the field offered

    Ensures:
        - returns [ ( tag, header, ident ) ]
        - a list is one unit per pick, or one empty_selection when empty; a blank string is an empty_selection
        - on a batch card each non-blank field is a batch_field; elsewhere a pick is a multi_pick or single_listed_pick
          when it is a label, typed_other when the field offered labels and it is not one, and open_text when it offered none
    """
    if isinstance( value, list ):
        if not value: return [ ( "empty_selection", header, "" ) ]
        return [ ( "multi_pick" if str( p ).strip() in labels else "typed_other", header, str( p ).strip() ) for p in value ]
    text_ = value.strip()
    if not text_: return [ ( "empty_selection", header, "" ) ]
    if kind == "open_ended_batch": return [ ( "batch_field", header, text_ ) ]
    if not labels: return [ ( "open_text", header, text_ ) ]
    return [ ( "single_listed_pick" if text_ in labels else "typed_other", header, text_ ) ]


def answers_map( value ):
    """
    Decode the answers map of a stored card answer with plain json.

    Requires:
        - value is a stored response_value

    Ensures:
        - returns the { header: pick } map, or None when absent
    """
    if not isinstance( value, dict ): return None
    if isinstance( value.get( "answers" ), dict ): return value[ "answers" ]
    inner = as_json( value[ "value" ] ) if isinstance( value.get( "value" ), str ) else value.get( "value" )
    return inner[ "answers" ] if isinstance( inner, dict ) and isinstance( inner.get( "answers" ), dict ) else None


def is_timeout( row ):
    """
    Say whether the stored answer is a timeout default, not a person's answer.

    Requires:
        - row is a clean_row dict

    Ensures:
        - returns True only when history_derive.attribution_tier names the answer a timeout default
    """
    return attribution_tier( row ) == "timeout_default"


def timeout_units( row ):
    """
    Name the one unit of a timeout row: the timeout and the default it fell back to.

    Requires:
        - row is a timeout row

    Ensures:
        - returns one unit tagged timeout, whose ident is the default as text
    """
    default = row[ "response_value" ].get( "value" )
    return [ ( "timeout", WHOLE, default if isinstance( default, str ) else json.dumps( default, sort_keys=True ) ) ]


def stance_units( text_ ):
    """
    Read a yes/no text into its stance and comment units with the production parser.

    Requires:
        - text_ is a string or None

    Ensures:
        - returns the stance unit, stance:none when unrecognised, and a comment unit when there is a comment
    """
    stance, comment = extract_qualifier_comment( text_ if isinstance( text_, str ) else None )
    units = [ ( "stance:" + ( stance or "none" ), WHOLE, "" ) ]
    if comment: units.append( ( "comment", WHOLE, "" ) )
    return units


def production_units( row ):
    """
    The production readers' units in the stored answer: the first step's main column.

    Requires:
        - row is an answered clean_row dict, not a timeout

    Ensures:
        - yes/no is read by extract_qualifier_comment (stance and comment), and decode_answer_fields must also read it
        - open-ended text and every card field come from decode_answer_fields
    """
    value, kind = row[ "response_value" ], row[ "response_type" ]
    decoded = decode_answer_fields( kind, value )
    if kind == "yes_no": return stance_units( value.get( "value" ) )
    if kind == "open_ended": return [ ( "open_text", WHOLE, decoded[ WHOLE ][ 0 ] ) ] if decoded[ WHOLE ] else []
    if decoded is None: return []
    schema = schema_of( row[ "response_options" ] )
    units  = []
    for header, picks in decoded.items():
        entry = schema.get( header, { "labels": set(), "multi": False } )
        val   = list( picks ) if entry[ "multi" ] else ( picks[ 0 ] if picks else "" )
        units.extend( field_units( kind, header, val, entry[ "labels" ] ) )
    return units


def plain_units( row ):
    """
    The control reader's units in the stored answer: the first step's second column.

    Requires:
        - row is an answered clean_row dict, not a timeout

    Ensures:
        - yes/no is read by the first word and a "[comment:" marker, not by the production parser
        - open-ended text and card fields come from the stored JSON as written
    """
    value, kind = row[ "response_value" ], row[ "response_type" ]
    body = value.get( "value" )
    if kind == "yes_no":
        s     = body if isinstance( body, str ) else ""
        first = re.match( r"\s*(yes|no|neither)\b", s, re.IGNORECASE )
        units = [ ( "stance:" + ( first.group( 1 ).lower() if first else "none" ), WHOLE, "" ) ]
        if "[comment:" in s.lower(): units.append( ( "comment", WHOLE, "" ) )
        return units
    if kind == "open_ended": return [ ( "open_text", WHOLE, body.strip() ) ] if isinstance( body, str ) and body.strip() else []
    answers = answers_map( value )
    if answers is None: return []
    schema = schema_of( row[ "response_options" ] )
    units  = []
    for header, val in answers.items():
        units.extend( field_units( kind, header, val if isinstance( val, ( list, str ) ) else str( val ), schema.get( header, { "labels": set() } )[ "labels" ] ) )
    return units


def derived_units( answer, row ):
    """
    Step 2: the units in derive_answer's output.

    Requires:
        - answer is derive_answer's first value; row is the clean_row it came from

    Ensures:
        - an unread answer has no units
    """
    kind = answer[ "kind" ]
    if kind == "stance": return stance_units( answer[ "stance" ] + ( f" [comment: {answer[ 'qualifier' ]}]" if answer[ "qualifier" ] else "" ) )
    if kind == "text": return [ ( "open_text", WHOLE, answer[ "text" ].strip() ) ] if answer[ "text" ] and answer[ "text" ].strip() else []
    if kind != "fields": return []
    schema = schema_of( row[ "response_options" ] )
    units  = []
    for header, rec in answer[ "fields" ].items():
        labels = schema.get( header, { "labels": set() } )[ "labels" ]
        units.extend( field_units( row[ "response_type" ], header, list( rec[ "selected" ] ) if rec[ "mode" ] == "multi" else ( rec[ "text" ] or "" ), labels ) )
    return units


def writer_units( derived, entries ):
    """
    Step 3: the derived units that are present in field_answers' entries.

    Requires:
        - derived is a list of units; entries is field_answers' result

    Ensures:
        - a unit survives only when its field has an entry and the entry's text still holds it
    """
    by_key = { e[ "field_key" ]: e for e in entries }
    kept   = []
    for tag, field_key, ident in derived:
        entry = by_key.get( field_key )
        if entry is None: continue
        words = entry[ "text" ].split( None, 1 )
        if tag.startswith( "stance:" ): ok = bool( words ) and words[ 0 ].lower() == tag[ 7: ]
        elif tag == "comment":         ok = len( words ) == 2
        elif tag == "empty_selection": ok = entry[ "text" ] == ""
        else:                          ok = ident in entry[ "text" ]
        if ok: kept.append( ( tag, field_key, ident ) )
    return kept


# ---------------------------------------------------------------- steps 4 and 5

class StubStore:
    """Records what _store_decision hands to the case store; keeps nothing else."""

    def __init__( self ):
        """Start with nothing recorded."""
        self.kw = None

    def add_decision( self, **kw ):
        """Record the keyword arguments of the one call."""
        self.kw = kw


def stored_decision( row ):
    """
    Run the real PredictionEngine._store_decision on a stub store.

    Requires:
        - row is a clean_row dict with a dict response_value

    Ensures:
        - returns the decision_value it would store, or None when it stores nothing
    """
    engine = object.__new__( PredictionEngine )
    store  = StubStore()
    engine.debug                      = False
    engine.failure_visibility_enabled = False
    engine._get_embedding_store       = lambda: store
    engine._get_embedding_provider    = lambda: types.SimpleNamespace( generate_embedding=lambda text, content_type="prose": [ 0.0 ] )
    result = types.SimpleNamespace( metadata={ "original_message": "q" }, category="c" )
    v = row[ "response_value" ]
    engine._store_decision( row[ "id" ], result, v.get( "value" ), row[ "response_type" ], v.get( "answered_by" ) )
    return None if store.kw is None else store.kw[ "decision_value" ]


def store_units( row, decision_value ):
    """
    The units readable from a stored decision_value, read as the engine reads it.

    Requires:
        - decision_value is what stored_decision returned

    Ensures:
        - returns [] for nothing stored or an unreadable value
    """
    if decision_value is None: return []
    kind = row[ "response_type" ]
    if kind == "yes_no":
        stance, _ = extract_qualifier_comment( decision_value )
        return [] if stance is None else stance_units( decision_value )
    if kind == "open_ended": return [ ( "open_text", WHOLE, decision_value.strip() ) ] if decision_value.strip() else []
    parsed = PredictionEngine._parse_mc_decision_value( decision_value )
    if parsed is None: return []
    schema = schema_of( row[ "response_options" ] )
    units  = []
    for header, val in parsed[ "answers" ].items():
        units.extend( field_units( kind, header, val, schema.get( header, { "labels": set() } )[ "labels" ] ) )
    return units


def vote_units( row, stored ):
    """
    The stored units the lookup forecaster counts as a vote.

    Requires:
        - stored is store_units' result

    Ensures:
        - a stance, or a pick whose normalised text is an offered label, is a vote; the comment, typed text and the rest are not
    """
    schema = schema_of( row[ "response_options" ] )
    norm   = { h: { PredictionEngine._normalise_text( label ) for label in s[ "labels" ] } for h, s in schema.items() }
    return [ u for u in stored if u[ 0 ].startswith( "stance:" ) or
             ( u[ 0 ] in ( "multi_pick", "single_listed_pick" ) and PredictionEngine._normalise_text( u[ 2 ] ) in norm.get( u[ 1 ], set() ) ) ]


def neighbour_units( row, decision_value ):
    """
    What three_way_stance.neighbours_of reads from a stored yes/no decision.

    Requires:
        - decision_value is what stored_decision returned

    Ensures:
        - returns the stance unit, and the comment unit when neighbours_of read a qualifier; [] for any other type or no stance
    """
    if row[ "response_type" ] != "yes_no" or decision_value is None: return []
    when = datetime( 2026, 1, 1, tzinfo=timezone.utc )
    ask  = { "question_embedding": [ 1.0, 0.0 ], "asked_at": datetime( 2026, 1, 2, tzinfo=timezone.utc ) }
    case = { "question_embedding": [ 1.0, 0.0 ], "decision_value": decision_value, "responded_at": when }
    found = neighbours_of( ask, [ case ], 30.0 )[ 0 ]
    if found[ "stance" ] is None: return []
    return [ ( "stance:" + found[ "stance" ], WHOLE, "" ) ] + ( [ ( "comment", WHOLE, "" ) ] if found[ "qualifier" ] else [] )


def blank_episode( kind ):
    """
    A card with no answer in it, shaped as episode_view returns it.

    Requires:
        - kind is a response type

    Ensures:
        - returns the episode dict build_user_prompt reads
    """
    return { "message": "q", "response_type": kind, "fields": [], "title": "t", "abstract": "a", "links": [], "default": "d", "timeout_seconds": 60 }


def prompt_units( row, units, build=context_baseline.build_user_prompt ):
    """
    The units whose text changes the model forecasters' prompt when planted.

    Requires:
        - units are the row's production units; build takes an episode like build_user_prompt

    Ensures:
        - a unit survives when planting its text under answer, response_value and history changes the prompt
        - a comparison of two prompts, so a label that the card already prints is not mistaken for a surviving answer
    """
    base   = blank_episode( row[ "response_type" ] if row[ "response_type" ] in context_baseline.SUPPORTED_TYPES else "yes_no" )
    plain  = build( base )
    kept   = []
    for unit in units:
        marker = unit[ 2 ] or unit[ 0 ]
        if build( { **base, "answer": marker, "response_value": marker, "history": marker } ) != plain: kept.append( unit )
    return kept


# ---------------------------------------------------------------- step 6

def perfect_forecast( row ):
    """
    The forecast that equals the stored answer.

    Requires:
        - row is a clean_row dict

    Ensures:
        - returns { "value": stance } for a recognised yes/no, { "value": text } for open text, { "answers": ... } for a card, or None
    """
    value, kind = row[ "response_value" ], row[ "response_type" ]
    if kind == "yes_no":
        stance = extract_qualifier_comment( value.get( "value" ) if isinstance( value.get( "value" ), str ) else None )[ 0 ]
        return None if stance is None else { "value": stance }
    if kind == "open_ended": return { "value": value.get( "value" ) }
    answers = answers_map( value )
    return None if answers is None else { "answers": answers }


def score_units( row, raw ):
    """
    Probe the real scorers with forecasts built from the answer.

    Requires:
        - raw are the row's production units

    Ensures:
        - returns { "match": units whose change moves the score, "detail": comment units computed beside the score,
                    "typed_miss": typed units scored as a miss with the per-field switch off,
                    "typed_left_out": typed units left out of the score with it on }
        - a timeout, open-text, batch-field or empty-selection unit moves the match when a forecast equal to the stored answer scores right
    """
    out = { "match": [], "detail": [], "typed_miss": [], "typed_left_out": [] }
    v, kind, opts = row[ "response_value" ], row[ "response_type" ], row[ "response_options" ]
    perfect = perfect_forecast( row )
    if perfect is None: return out
    perfect_scores = replay_loop._score( kind, perfect, v, opts )
    if kind == "yes_no":
        text_ = v.get( "value" )
        for unit in raw:
            tag = unit[ 0 ]
            if tag.startswith( "stance:" ) and tag[ 7: ] == perfect[ "value" ]:
                other = next( s for s in STANCES if s != perfect[ "value" ] )
                if perfect_scores and not replay_loop._score( kind, { "value": other }, v, opts ): out[ "match" ].append( unit )
            if tag == "comment":
                same, _ = ac.compare_yes_no( perfect, { "value": text_ } )
                diff, d2 = ac.compare_yes_no( { "value": f"{perfect[ 'value' ]} [comment: zz different zz]" }, { "value": text_ } )
                if same != diff: out[ "match" ].append( unit )
                _, d3 = ac.compare_yes_no( { "value": text_ }, { "value": text_ } )
                if d3[ "qualifier_match" ] and not d2[ "qualifier_match" ]: out[ "detail" ].append( unit )
            if tag == "timeout" and perfect_scores: out[ "match" ].append( unit )
        return out
    if kind != "multiple_choice":
        if perfect_scores: out[ "match" ].extend( raw )
        return out
    if not perfect_scores: return out
    schema   = schema_of( opts )
    labels   = { h: s[ "labels" ] for h, s in schema.items() }
    guess    = { "answers": { h: ( sorted( labels[ h ] )[ :1 ] if labels.get( h ) else "" ) for h in perfect[ "answers" ] } }
    actual   = replay_loop._actual_dict( v, kind )
    _, d_off = ac.get_comparator( kind, response_options=opts )( guess, actual )
    _, d_on  = ac.get_comparator( kind, response_options=opts, per_field=True )( guess, actual )
    rec_off  = { f[ "header" ]: f for f in d_off.get( "fields", [] ) }
    rec_on   = { f[ "header" ]: f for f in d_on.get( "fields", [] ) }
    for unit in raw:
        tag, header, _ = unit
        if tag == "timeout": out[ "match" ].append( unit )
        if header not in rec_off: continue
        out[ "match" ].append( unit )
        if tag == "typed_other":
            if not rec_off[ header ][ "exact" ]: out[ "typed_miss" ].append( unit )
            if rec_on.get( header, {} ).get( "outcome" ) == ac.FIELD_OUTCOME_OTHER_WRITE_IN: out[ "typed_left_out" ].append( unit )
    return out


# ---------------------------------------------------------------- the measurement

def with_source( row, source ):
    """
    Copy a row with a different answer source.

    Requires:
        - row has a dict response_value

    Ensures:
        - returns a new row; the original is untouched
    """
    return { **row, "response_value": { **row[ "response_value" ], "source": source } }


def timeout_steps( row, step_units ):
    """
    The derive and writer steps for a timeout row.

    Requires:
        - row is a timeout row; step_units is the unit list

    Ensures:
        - a unit survives a step only when that step's output still says the answer was a timeout
        - returns { "2": units, "3": units } holding the timeout unit where derive_answer and field_answers give a different
          output for the same row marked as an on-screen answer, and nothing where the output does not depend on the source
    """
    shown = with_source( row, "ui" )
    d_t, _ = derive_answer( row )
    d_s, _ = derive_answer( shown )
    return { "2": step_units if d_t != d_s else [], "3": step_units if field_answers( d_t ) != field_answers( d_s ) else [] }


def measure_row( row, have, build=context_baseline.build_user_prompt ):
    """
    Count one answered row's units at every step.

    Requires:
        - row is a clean_row dict whose response_value is a dict; have is the set of ( notification id, field key ) with live evidence

    Ensures:
        - returns { "steps": { step: Counter of units }, "derived": derive_answer's first value, "entries": field_answers' result }
    """
    v, nid = row[ "response_value" ], norm_id( row[ "id" ] )
    if is_timeout( row ):
        raw = timeout_units( row )
        ts  = timeout_steps( row, raw )
        dv  = stored_decision( row )
        stored = store_units( row, dv )
        sc = score_units( row, raw )
        linked = [ u for u in raw if any( key[ 0 ] == nid for key in have ) ]
        return { "steps": { "1p_production_readers": Counter( raw ), "1c_plain_first_word_reader": Counter( raw ), "2_derive_answer": Counter( ts[ "2" ] ),
                            "3_field_answers": Counter( ts[ "3" ] ), "3g_after_extractor_gates": Counter(), "4_evidence_linked": Counter( linked ),
                            "4n_neighbours_of": Counter( [ raw[ 0 ] ] if neighbour_units( row, dv ) else [] ), "5a_lookup_case_store": Counter( raw if dv is not None else [] ),
                            "5a_lookup_counts_as_vote": Counter( raw if vote_units( row, stored ) else [] ), "5b_model_prompt": Counter( prompt_units( row, raw, build ) ),
                            "6_scorer_moves_match": Counter( sc[ "match" ] ), "6_comment_computed_beside": Counter(), "6_typed_scored_as_miss_switch_off": Counter(),
                            "6_typed_left_out_switch_on": Counter() }, "derived": None, "entries": [] }
    prod, plain = production_units( row ), plain_units( row )
    answer, _   = derive_answer( { "response_type": row[ "response_type" ], "response_value": v, "recipient_id": row[ "recipient_id" ] } )
    step2   = Counter( derived_units( answer, row ) ) & Counter( prod )
    entries = field_answers( answer )
    step3   = Counter( writer_units( list( step2.elements() ), entries ) )
    gated   = owners_own_answer( types.SimpleNamespace( response_value=v, recipient_id=row[ "recipient_id" ] ) ) and not is_review_card( row[ "response_options" ] )
    dv      = stored_decision( row )
    stored  = Counter( store_units( row, dv ) ) & Counter( prod )
    sc      = score_units( row, prod )
    return { "steps": { "1p_production_readers": Counter( prod ), "1c_plain_first_word_reader": Counter( plain ), "2_derive_answer": step2, "3_field_answers": step3,
                        "3g_after_extractor_gates": step3 if gated else Counter(), "4_evidence_linked": Counter( { u: c for u, c in step3.items() if ( nid, u[ 1 ] ) in have } ),
                        "4n_neighbours_of": Counter( neighbour_units( row, dv ) ) & Counter( prod ), "5a_lookup_case_store": stored,
                        "5a_lookup_counts_as_vote": Counter( vote_units( row, list( stored.elements() ) ) ),
                        "5b_model_prompt": Counter( prompt_units( row, prod, build ) ), "6_scorer_moves_match": Counter( sc[ "match" ] ),
                        "6_comment_computed_beside": Counter( sc[ "detail" ] ), "6_typed_scored_as_miss_switch_off": Counter( sc[ "typed_miss" ] ),
                        "6_typed_left_out_switch_on": Counter( sc[ "typed_left_out" ] ) }, "derived": answer, "entries": entries }


def label_equality( row ):
    """
    Classify each single-text field of a card answer against its card's labels.

    Requires:
        - row is an answered multiple_choice or open_ended_batch clean_row dict

    Ensures:
        - returns a Counter over: equals a label character for character; equals one except spaces; except case or the
          (Recommended) suffix; starts with a label and adds words; matches no label
    """
    out    = Counter()
    schema = schema_of( row[ "response_options" ] )
    strip  = lambda s: re.sub( r"\s*\(recommended\)\s*$", "", s.strip(), flags=re.I ).casefold()
    for header, val in ( answers_map( row[ "response_value" ] ) or {} ).items():
        labels = schema.get( header, { "labels": set() } )[ "labels" ]
        if not labels or not isinstance( val, str ) or not val.strip(): continue
        if val in labels:                                  out[ "equals a label character for character (a click cannot be told from typing)" ] += 1
        elif val.strip() in labels:                        out[ "equals a label except surrounding spaces" ] += 1
        elif strip( val ) in { strip( x ) for x in labels }: out[ "equals a label except case or the (Recommended) suffix" ] += 1
        elif any( len( strip( x ) ) > 3 and val.strip().casefold().startswith( strip( x ) ) for x in labels ): out[ "starts with a label then adds words" ] += 1
        else:                                              out[ "matches no label" ] += 1
    return out


def typed_denominators( rows, units_by_row ):
    """
    Count the typed text in every denominator, so figures for different units differ.

    Requires:
        - rows are the answered, non-timeout rows; units_by_row maps a row id to its production units

    Ensures:
        - returns { name: count } for: typed fields; cards holding at least one typed field; distinct ( card, header ) pairs;
          distinct ( header, text ) pairs; and the typed fields on cards of each response type
    """
    fields, cards, pairs, texts, per_type = 0, set(), set(), set(), Counter()
    for row in rows:
        for tag, header, ident in units_by_row[ row[ "id" ] ]:
            if tag != "typed_other": continue
            fields += 1
            cards.add( row[ "id" ] )
            pairs.add( ( row[ "id" ], header ) )
            texts.add( ( header, ident ) )
            per_type[ "typed fields on " + row[ "response_type" ] ] += 1
    return { "typed fields": fields, "cards holding a typed field": len( cards ), "distinct ( card, header ) pairs": len( pairs ),
             "distinct ( header, text ) pairs": len( texts ), **per_type }


def draft_summary( rows, log ):
    """
    Count the reveals before an answer and what the extractor would read from a stored draft.

    Requires:
        - rows are clean_row dicts; log rows carry notification_id, fold_opened_at and draft_at_reveal

    Ensures:
        - returns counts of reveals on answered rows, reveals before the answer, stored drafts, and the outcome
          compare_draft_to_answer gives each stored draft
    """
    by_id = { norm_id( r[ "id" ] ): r for r in rows }
    out   = Counter()
    for entry in log:
        row = by_id.get( norm_id( entry[ "notification_id" ] ) )
        if row is None: continue
        out[ "reveals on answered rows" ] += 1
        if revealed_before_answer( aware_moment( entry[ "fold_opened_at" ] ), aware_moment( row[ "responded_at" ] ) ): out[ "reveals before the answer" ] += 1
        draft = as_json( entry[ "draft_at_reveal" ] )
        if draft in ( None, "" ): continue
        out[ "stored drafts" ] += 1
        out[ "draft outcome: " + compare_draft_to_answer( row[ "response_type" ], draft, row[ "response_value" ] )[ "outcome" ] ] += 1
    return dict( out )


def measure( rows, evidence, log, population, build=context_baseline.build_user_prompt ):
    """
    Count the units of the given rows at every step.

    Requires:
        - rows are clean_row dicts; evidence and log are read_tables' lists from the same database

    Ensures:
        - returns { "population", "answers": { type: count }, "timeouts": { type: count }, "units": { tag: { step: count } }, "unread_shapes",
                    "unreadable_card_answers", "label_equality", "typed_denominators", "drafts", "evidence_rows" }
        - rows whose stored value is not a dict are counted and left out of every unit count
    """
    have    = { ( norm_id( e[ "notification_id" ] ), e[ "field_key" ] ) for e in evidence if e[ "retracted_at" ] is None }
    steps   = defaultdict( Counter )
    answers, timeouts, unread, labels, odd, unreadable = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    prod_by_row, answered = {}, []
    for row in rows:
        if not isinstance( row[ "response_value" ], dict ):
            odd[ row[ "response_type" ] ] += 1
            continue
        (timeouts if is_timeout( row ) else answers)[ row[ "response_type" ] ] += 1
        done = measure_row( row, have, build )
        for step, counter in done[ "steps" ].items():
            for unit, count in counter.items(): steps[ unit[ 0 ] ][ step ] += count
        if is_timeout( row ): continue
        answered.append( row )
        prod_by_row[ row[ "id" ] ] = list( done[ "steps" ][ "1p_production_readers" ].elements() )
        if done[ "derived" ][ "kind" ] == "unread" and row[ "response_type" ] != "yes_no": unreadable[ row[ "response_type" ] ] += 1
        if done[ "derived" ][ "kind" ] == "unread" and row[ "response_type" ] == "yes_no":
            body  = done[ "derived" ].get( "text" )
            shape = "empty or missing text" if not isinstance( body, str ) or not body.strip() else \
                    ( "first word is a stance, rest not read" if re.match( r"\s*(yes|no|neither)\b", body, re.I ) else "no stance word" )
            unread[ shape ] += 1
        if row[ "response_type" ] in ( "multiple_choice", "open_ended_batch" ): labels.update( label_equality( row ) )
    return { "population": population, "answers": dict( answers ), "timeouts": dict( timeouts ), "stored_value_not_an_object": dict( odd ),
             "units": { tag: dict( c ) for tag, c in steps.items() }, "unread_shapes": dict( unread ), "unreadable_card_answers": dict( unreadable ), "label_equality": dict( labels ),
             "typed_denominators": typed_denominators( answered, prod_by_row ), "drafts": draft_summary( rows, log ),
             "evidence_rows": len( [ e for e in evidence if e[ "retracted_at" ] is None ] ) }


# ---------------------------------------------------------------- the report

def render_markdown( result ):
    """
    Turn a result into the markdown receipt, one table per population.

    Requires:
        - result is run()'s dict

    Ensures:
        - every step column is named with the symbol it measured, and the run time and git sha open the document
    """
    lines = [ "# The attrition table, acceptance run", "", f"**Run time:** {result[ 'run_time_utc' ]} UTC. **Code:** git sha `{result[ 'git_sha' ]}`. Read only: nothing was written to any database.", "",
              "## The steps and the symbol each measured", "", "| step | symbol measured |", "|---|---|" ]
    lines += [ f"| {step} | {symbol} |" for step, symbol in STEP_SYMBOLS.items() ]
    for pop in result[ "populations" ]:
        lines += [ "", f"## {pop[ 'population' ]}", "",
                   f"Answers by type: {pop[ 'answers' ]}. Timeouts by type: {pop[ 'timeouts' ]}. Evidence rows: {pop[ 'evidence_rows' ]}.", "",
                   "| unit | " + " | ".join( STEP_SYMBOLS ) + " |", "|---|" + "---|" * len( STEP_SYMBOLS ) ]
        for tag in UNIT_TAGS:
            if tag in pop[ "units" ]: lines.append( f"| {tag} | " + " | ".join( str( pop[ "units" ][ tag ].get( step, 0 ) ) for step in STEP_SYMBOLS ) + " |" )
        lines += [ "", f"Unread yes/no shapes: {pop[ 'unread_shapes' ]}. Card answers derive_answer could not read: {pop[ 'unreadable_card_answers' ]}. Label equality: {pop[ 'label_equality' ]}. Drafts: {pop[ 'drafts' ]}.",
                   "", "Typed text by denominator: " + "; ".join( f"{k} = {v}" for k, v in pop[ "typed_denominators" ].items() ) + "." ]
    findings = [ f"- {pop[ 'population' ]}: {tag}: production readers {c.get( '1p_production_readers', 0 )}, plain reader {c.get( '1c_plain_first_word_reader', 0 )}"
                 for pop in result[ "populations" ] for tag, c in pop[ "units" ].items() if c.get( "1p_production_readers", 0 ) != c.get( "1c_plain_first_word_reader", 0 ) ]
    lines += [ "", "## Step 1 findings: units where the two readers differ", "" ] + ( findings or [ "- none" ] )
    return "\n".join( lines ) + "\n"


def run( archive_path, records_path, live_session, build=context_baseline.build_user_prompt ):
    """
    Measure the archive and the live database, read only.

    Requires:
        - archive_path is the run 2 archive and records_path its records.jsonl, or both None to skip the archive
        - live_session is an active session on the live database, or None to skip it

    Ensures:
        - returns { "run_time_utc", "git_sha", "populations": [ measure results ] }
        - the archive populations are the evaluation cards named in records_path and every answered row; the live ones
          are the cards asked on or after WINDOW_START and every answered row
    """
    result = { **provenance(), "populations": [] }
    if archive_path is not None:
        with open_archive_session( archive_path ) as session:
            rows, evidence, log = read_tables( session )
            session.get_bind().dispose()
        with open( records_path ) as handle: window = { norm_id( json.loads( line )[ "id" ] ) for line in handle }
        cards = [ r for r in rows if norm_id( r[ "id" ] ) in window and r[ "response_type" ] in ( "yes_no", "multiple_choice" ) ]
        result[ "populations" ] += [ measure( cards, evidence, log, "run 2 archive, the evaluation cards", build ), measure( rows, evidence, log, "run 2 archive, every answered row", build ) ]
    if live_session is not None:
        rows, evidence, log = read_tables( live_session )
        recent = [ r for r in rows if str( r[ "created_at" ] )[ :10 ] >= WINDOW_START and r[ "response_type" ] in ( "yes_no", "multiple_choice" ) ]
        result[ "populations" ] += [ measure( recent, evidence, log, f"live database, asked on or after {WINDOW_START}", build ), measure( rows, evidence, log, "live database, every answered row", build ) ]
    return result


def main( argv=None ):
    """
    Command line entry: measure, then write the JSON result and the markdown receipt.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - writes the files named by --out-json and --out-md, and prints the table
    """
    parser = argparse.ArgumentParser( description="The attrition table of Rick's answer through the pipeline (read only)." )
    parser.add_argument( "--archive" )
    parser.add_argument( "--records" )
    parser.add_argument( "--live", action="store_true" )
    parser.add_argument( "--out-json", required=True )
    parser.add_argument( "--out-md", required=True )
    args = parser.parse_args( argv )
    if args.live:
        from cosa.rest.db.database import get_db
        with get_db() as session: result = run( args.archive, args.records, session )
    else:
        result = run( args.archive, args.records, None )
    with open( args.out_json, "w" ) as handle: json.dump( result, handle, indent=1, sort_keys=True, default=str )
    markdown = render_markdown( result )
    with open( args.out_md, "w" ) as handle: handle.write( markdown )
    print( markdown )


if __name__ == "__main__":  # pragma: no cover - command line entry, exercised through main() in the tests
    main()
