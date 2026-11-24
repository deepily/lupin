"""
Append-only store for the meaning record of a stored answer.

The observation of an answer is a view over existing columns, and the forecast sits in prediction_arm_forecast.
This module holds the third record: a versioned reading of what the answer meant. It copies the design of
preference_evidence. A new schema version or a new annotator is a new row, and the old row stays. This repository only adds rows and reads them.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
import uuid

from sqlalchemy.orm import Session

from cosa.rest.postgres_models import AnswerMeaning

SCHEMA_VERSION = "answer-meaning-v1"

SOURCES        = ( "labeller", "human" )

# The native types of an answer, one per kind of field a card can hold.
NATIVE_KINDS   = ( "yes_no_stance", "selected_options", "multi_selected_options", "empty_selection", "write_in_text", "open_ended_text", "batch_field_text" )

# The unknowns, kept apart from what was said.
UNKNOWN_KINDS  = ( "no_explicit_stance", "neither", "cancellation", "absent_field", "unreadable_payload", "uncertain_annotator" )

MEANING_KINDS  = NATIVE_KINDS + UNKNOWN_KINDS

ACT_KINDS      = ( "approve", "decline", "challenge_premise", "request_information", "defer", "propose_alternative" )
ALIGNMENTS     = ( "aligned", "diverges", "partial", "no_recommendation", "unknown" )


class MeaningAlreadyRecorded( ValueError ):
    """Raised when a meaning is added under a key that already has a row."""


def kinds_in( meaning: Dict[str, Any] ) -> Set[str]:
    """
    Name the kinds a meaning shows.

    Requires:
        - meaning is a dict with a native_answer map of field entries, each carrying a "kind", and an unknowns list

    Ensures:
        - returns the set of the native kinds of its field entries joined with its unknowns
    """
    return { entry[ "kind" ] for entry in meaning[ "native_answer" ].values() } | set( meaning[ "unknowns" ] )


def _refuse_unknown( label: str, values: Iterable[str], allowed: Iterable[str] ) -> None:
    """
    Refuse any value that is not on the list of allowed values.

    Requires:
        - values and allowed are iterables of strings

    Ensures:
        - returns None when every value is allowed

    Raises:
        - ValueError naming the label and the first value that is not allowed
    """
    allowed = tuple( allowed )
    for value in values:
        if value not in allowed: raise ValueError( f"{label} {value!r} is not one of {allowed}" )


class AnswerMeaningRepository:
    """
    Add and read meaning records. Nothing here updates or deletes a row.

    Requires:
        - session is an open SQLAlchemy session on a database holding answer_meaning
    """

    def __init__( self, session: Session ):
        """
        Bind the repository to a session.

        Requires:
            - session is an open SQLAlchemy session

        Ensures:
            - holds the session; touches nothing
        """
        self.session = session

    def add( self, notification_id: str, annotator: str, source: str, native_answer: Dict[str, Any], acts: List[Dict[str, Any]],
             conditions: List[Dict[str, Any]], alignment: str, unknowns: List[str], schema_version: str = SCHEMA_VERSION,
             supporting_spans: Optional[list] = None, uncertainty: Optional[float] = None, answered_at: Optional[datetime] = None,
             annotated_at: Optional[datetime] = None, session_key: Optional[str] = None ) -> AnswerMeaning:
        """
        Add one meaning record, never replacing an earlier one.

        Requires:
            - notification_id is a UUID string; annotator is a non-empty name; source is a name from the sources list
            - native_answer maps a field key to an entry whose "kind" is one of NATIVE_KINDS
            - acts is a list of dicts whose "act" is one of ACT_KINDS
            - conditions is a list of dicts that each carry "modifies_option_id": an option id, or None for the whole answer
            - alignment is a name from the alignments list; unknowns is a list of unknown kinds

        Ensures:
            - writes one answer_meaning row and flushes it, without committing
            - a second schema version, or a second annotator, for the same notification is a new row and the first survives
            - annotated_at is the current time when not given

        Raises:
            - ValueError for a source, kind, act, alignment or unknown not on its list, or a condition with no modifies_option_id key
            - MeaningAlreadyRecorded when the key already has a row; that row is left as it was
        """
        _refuse_unknown( "source", [ source ], SOURCES )
        _refuse_unknown( "native kind", [ entry[ "kind" ] for entry in native_answer.values() ], NATIVE_KINDS )
        _refuse_unknown( "act", [ act[ "act" ] for act in acts ], ACT_KINDS )
        _refuse_unknown( "alignment", [ alignment ], ALIGNMENTS )
        _refuse_unknown( "unknown", unknowns, UNKNOWN_KINDS )
        for condition in conditions:
            if "modifies_option_id" not in condition: raise ValueError( "every condition names modifies_option_id, or None for the whole answer" )
        key = uuid.UUID( str( notification_id ) )
        if self.get( key, schema_version, annotator ) is not None:
            raise MeaningAlreadyRecorded( f"answer_meaning for {key}, {schema_version}, {annotator} already has a row" )
        row = AnswerMeaning(
            notification_id = key, schema_version = schema_version, annotator = annotator, source = source,
            native_answer   = native_answer, acts = acts, conditions = conditions, alignment = alignment, unknowns = unknowns,
            supporting_spans = supporting_spans, uncertainty = uncertainty, answered_at = answered_at,
            annotated_at    = annotated_at or datetime.now( timezone.utc ), session_key = session_key,
        )
        self.session.add( row )
        self.session.flush()
        return row

    def get( self, notification_id, schema_version: str, annotator: str ) -> Optional[AnswerMeaning]:
        """
        Read the one record under a key.

        Requires:
            - notification_id is a UUID or a UUID string

        Ensures:
            - returns the row, or None when the key has none
        """
        return self.session.query( AnswerMeaning ).filter(
            AnswerMeaning.notification_id == uuid.UUID( str( notification_id ) ),
            AnswerMeaning.schema_version  == schema_version,
            AnswerMeaning.annotator       == annotator,
        ).first()

    def versions( self, notification_id ) -> List[AnswerMeaning]:
        """
        Read every record of one notification, oldest first.

        Requires:
            - notification_id is a UUID or a UUID string

        Ensures:
            - returns all rows for the notification across schema versions and annotators, ordered by annotated_at
            - returns an empty list when there are none
        """
        return self.session.query( AnswerMeaning ).filter(
            AnswerMeaning.notification_id == uuid.UUID( str( notification_id ) )
        ).order_by( AnswerMeaning.annotated_at, AnswerMeaning.annotator ).all()
