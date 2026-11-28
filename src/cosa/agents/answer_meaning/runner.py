"""
Write a v2 meaning row for stored answers, one per answer.

The rules layer reads the answer, the model layer labels what plain code could not, and the repository appends the row.
A second run adds nothing. No database session is held while the model is called.

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m cosa.agents.answer_meaning.runner [--ids-file F] [--limit N]
"""
import argparse
import collections
import functools
import importlib
import json
import sys
import uuid

from cosa.agents.answer_meaning import rules
from cosa.repo.labelling.gold_progress import stamp_line
from cosa.rest.db.repositories.answer_meaning_repository import SCHEMA_VERSION_V2, AnswerMeaningRepository, MeaningAlreadyRecorded
from cosa.rest.postgres_models import Notification
from cosa.utils.notification_utils import sender_session_suffix

LABELLER_MODULE = "cosa.agents.answer_meaning.labeller"
LABEL_KEYS      = ( "relation", "stance", "stance_source" )
PROGRESS_EVERY  = 100

# What the labeller's report may claim (plan section 6). With no class lifted, the first line is the plan's text, unchanged.
STAMP = (
    stamp_line(),
    "no certificate: multiple-choice, open-ended and batch relations",
    "pass line for yes: not yet run (plan step 9)",
)


def bound_labeller( model=None ):
    """
    Bind the model layer to one model.

    Requires:
        - the model layer module is importable
        - model is a model id, or None for the model the model layer reads from the INI

    Ensures:
        - returns ( annotator, label ), label taking a draft alone
    """
    labeller = importlib.import_module( LABELLER_MODULE )
    chosen   = model or labeller.model_id()
    return labeller.annotator_of( chosen ), functools.partial( labeller.label, model=chosen )


def meaning_of( draft, label ):
    """
    Turn a draft into the columns of one meaning record, writing nothing.

    Requires:
        - draft comes from rules.draft_of; label is the model layer's label function, which takes the draft

    Ensures:
        - each field's entry is the rules layer's full entry with the label's relation, stance and stance_source laid over it
        - the draft's plain entries are kept
        - acts, conditions, supporting_spans, uncertainty and unknowns are the label's
    """
    out    = label( draft )
    native = {}
    for key, field in draft[ "fields" ].items():
        entry = rules.entry_of( field )
        entry.update( { name: value for name, value in out[ "native_answer" ][ key ].items() if name in LABEL_KEYS } )
        native[ key ] = entry
    native.update( draft[ "plain" ] )
    return dict( out, native_answer=native )


def record_one( session_scope, notification_id, annotator, label ):
    """
    Write the meaning of one stored answer, unless it already has a row.

    Requires:
        - session_scope returns a context manager yielding a session that commits on a clean exit
        - notification_id is a UUID string of an answered notification; annotator and label come from one model

    Ensures:
        - with a row already under this annotator, returns { "status": "already" } and calls no model
        - otherwise appends one v2 row and returns { "status": "written", "relations": [..], "unknowns": [..] }
        - a row that appears between the check and the add gives { "status": "already" }
        - no session is open during the model call

    Raises:
        - LookupError when there is no such notification
        - whatever the model layer raises to stop a run
    """
    key   = uuid.UUID( str( notification_id ) )
    draft = answered_at = session_key = None
    with session_scope() as session:
        notification = session.get( Notification, key )
        found        = notification is not None
        if found and AnswerMeaningRepository( session ).get( key, SCHEMA_VERSION_V2, annotator ) is None:
            draft       = rules.draft_of( notification )
            answered_at = notification.responded_at
            session_key = sender_session_suffix( notification.sender_id )
    if not found: raise LookupError( f"no notification {key}" )
    if draft is None: return { "status": "already" }
    meaning = meaning_of( draft, label )
    try:
        with session_scope() as session:
            AnswerMeaningRepository( session ).add(
                key, annotator, "labeller", meaning[ "native_answer" ], meaning[ "acts" ], meaning[ "conditions" ], None, meaning[ "unknowns" ],
                schema_version=SCHEMA_VERSION_V2, supporting_spans=meaning[ "supporting_spans" ], uncertainty=meaning[ "uncertainty" ],
                answered_at=answered_at, session_key=session_key )
    except MeaningAlreadyRecorded:
        return { "status": "already" }
    return { "status": "written", "unknowns": list( meaning[ "unknowns" ] ),
             "relations": [ entry[ "relation" ] for entry in meaning[ "native_answer" ].values() if "relation" in entry ] }


def stored_answer_ids( session ):
    """
    List every stored answer to a card.

    Requires:
        - session is an active session on the database that holds the notifications

    Ensures:
        - returns the ids, oldest first, of notifications of the four card types that hold a response value
    """
    rows = session.query( Notification.id, Notification.response_value ).filter(
        Notification.response_type.in_( rules.TEXT_TYPES + rules.FIELD_TYPES ) ).order_by( Notification.created_at, Notification.id )
    return [ str( key ) for key, value in rows if value is not None ]


def run( session_scope, annotator, label, ids=None, limit=None, every=PROGRESS_EVERY ):
    """
    Label stored answers one by one and report what was written.

    Requires:
        - session_scope, annotator and label are as record_one takes them
        - ids is None for every stored answer, or a list of notification ids; limit is None or a positive integer

    Ensures:
        - returns annotator, answers, written, already, relations and unknowns (counts over the rows written) and the stamp
        - prints a progress line every `every` answers
        - a second run over the same answers writes nothing

    Raises:
        - whatever record_one raises; the rows written before it stay, and a rerun skips them
    """
    if ids is None:
        with session_scope() as session: ids = stored_answer_ids( session )
    ids       = ids[ :limit ]
    statuses  = collections.Counter()
    relations = collections.Counter()
    unknowns  = collections.Counter()
    for number, notification_id in enumerate( ids, start=1 ):
        report = record_one( session_scope, notification_id, annotator, label )
        statuses[ report[ "status" ] ] += 1
        relations.update( report.get( "relations", [] ) )
        unknowns.update( report.get( "unknowns", [] ) )
        if number % every == 0: print( f"[meaning runner] {number}/{len( ids )}", file=sys.stdout, flush=True )
    return { "annotator": annotator, "answers": len( ids ), "written": statuses[ "written" ], "already": statuses[ "already" ],
             "relations": dict( relations ), "unknowns": dict( unknowns ), "stamp": list( STAMP ) }


def main( argv=None, session_scope=None ):
    """
    Run the labeller over stored answers and print the report as json.

    Requires:
        - the database named by the configuration is reachable, unless session_scope is given

    Ensures:
        - --ids-file names a file of one notification id per line; without it every stored answer is read
        - prints the report and returns 0
    """
    parser = argparse.ArgumentParser( description="Write a meaning row for stored answers." )
    parser.add_argument( "--ids-file" )
    parser.add_argument( "--limit", type=int )
    parser.add_argument( "--model" )
    args = parser.parse_args( argv )
    if session_scope is None:
        from cosa.rest.db.database import get_db as session_scope
    ids = None
    if args.ids_file:
        with open( args.ids_file, encoding="utf-8" ) as handle: ids = [ line.strip() for line in handle if line.strip() ]
    annotator, label = bound_labeller( args.model )
    report = run( session_scope, annotator, label, ids=ids, limit=args.limit, every=PROGRESS_EVERY )
    print( json.dumps( report, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
