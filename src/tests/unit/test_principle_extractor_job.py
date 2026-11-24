"""
The principle extractor job, run over real SQL on an in-memory SQLite copy of the tables.

The model is a recorded double handed to model_transport.complete through its query_fn seam.
So the real call path runs (budget charge, options, text collection), and nothing reaches a live model or a GPU.
Embeddings are a keyword-count double padded to the column's 768 dimensions. All rows are synthetic.
"""

import ast
import asyncio
import concurrent.futures
import inspect
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import cosa.agents.principle_learner.extractor_job as job_module
import cosa.agents.principle_learner.extractor_prompt as prompt_module
import cosa.agents.principle_learner.extractor_rules as rules_module
import cosa.agents.principle_learner.extractor_store as store_module
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay.scratch_db import scratch_session, session_scope
from cosa.rest.job_state import JobState
from cosa.rest.postgres_models import Notification, PredictionLog, PreferenceEvidence, PreferencePrinciple

OWNER   = uuid.UUID( "00000000-0000-4000-8000-0000000000aa" )
OTHER   = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
ENCODER = "test-encoder:v1"
OLD_ENC = "other-encoder:v0"
T0      = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER  = "claude.code@lupin.deepily.ai#ab12cd34"
MODEL   = "claude-test-model"
NOW     = datetime( 2026, 11, 10, 13, 0, tzinfo=timezone.utc )


def vec( *head ):
    """
    Pad a short vector to the column's 768 dimensions.

    Requires:
        - head is a few numbers

    Ensures:
        - returns a list of 768 floats, head first and zeros after
    """
    return list( head ) + [ 0.0 ] * ( 768 - len( head ) )


def embed( text ):
    """
    Embed a text by counting three keywords.

    Requires:
        - text is a string

    Ensures:
        - returns a 768-dimension vector of the counts of "approval", "budget" and "link", plus a small constant
    """
    lowered = text.lower()
    return vec( lowered.count( "approval" ), lowered.count( "budget" ), lowered.count( "link" ), 0.01 )


@pytest.fixture
def db():
    """
    Give a session over empty in-memory copies of the tables the extractor reads and writes.

    Ensures:
        - yields an active session from scratch_session; the SQLite caveats on ids are in that module
    """
    with scratch_session() as session:
        yield session


def _factory( db ):
    """
    Wrap a session as the session_factory the job takes.

    Ensures:
        - returns a callable giving a context manager that yields db and commits on success
    """
    return lambda: session_scope( db )


class Model:
    """A recorded model double: it answers each call with the next reply."""

    def __init__( self, *replies ):
        self.replies = list( replies )
        self.sent    = []

    async def __call__( self, prompt, options ):
        """
        Stand in for the SDK's query function.

        Requires:
            - a reply is queued

        Ensures:
            - records the prompt, then yields one assistant message and one result message with the next reply
        """
        self.sent.append( prompt )
        text = self.replies.pop( 0 ) if len( self.replies ) > 1 else self.replies[ 0 ]
        yield AssistantMessage( content=[ TextBlock( text=text ) ], model=MODEL )
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", result=text )


def _reply( *fields ):
    """
    Write a model reply holding the given field results.

    Ensures:
        - returns the JSON text of { "fields": [ ... ] }
    """
    return json.dumps( { "fields": list( fields ) } )


def _result( field_key="$answer", hypotheses=None, relations=None, dimension="ask.approval_needs_link", kind="ask_form" ):
    """
    Build one field result as the model returns it.

    Ensures:
        - returns a dict with the field key, kind, dimension, hypotheses and relations
    """
    return { "field_key": field_key, "kind": kind, "dimension": dimension, "hypotheses": hypotheses or [], "relations": relations or {} }


def _hyp( statement="An approval request must link the thing being approved.", **extra ):
    """
    Build a hypothesis as the model returns it.

    Ensures:
        - returns a dict with a statement, a global scope and a rationale, plus extra
    """
    return { "statement": statement, "scope": "global", "rationale": "approval needs the link", **extra }


def _ask( db, minutes=0, answer="no", answered_by=OWNER, source="ui", **extra ):
    """
    Insert a yes/no ask answered by its owner, and return its id as text.

    Requires:
        - answer is "no", "yes" or an answer string; answered_by is a user id or None

    Ensures:
        - the row has a stored answer { value, source, answered_by } one minute after the ask unless extra overrides it
    """
    value = { "value": answer, "source": source }
    if answered_by is not None: value[ "answered_by" ] = { "user_id": str( answered_by ) }
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=OWNER, message="Approve it?", title="Approval needed", abstract="Please approve with a link",
                type="task", priority="medium", created_at=T0 + timedelta( minutes=minutes ), response_requested=True, response_type="yes_no",
                responded_at=T0 + timedelta( minutes=minutes + 1 ), response_value=value )
    row.update( extra )
    db.add( Notification( **row ) )
    db.commit()
    return str( row[ "id" ] )


def _principle( db, encoder=ENCODER, vector=None, scope="global", dimension="ask.approval_needs_link", statement="Existing principle.", owner=OWNER, version="old-extractor", created_at=None ):
    """
    Insert a principle and return its row.

    Ensures:
        - the row belongs to owner with the given encoder, vector, scope, dimension and statement, and the test extractor version
    """
    row = PreferencePrinciple( id=uuid.uuid4(), owner_id=str( owner ), kind="decision", dimension=dimension, statement=statement, scope=scope,
                               embedding=vector if vector is not None else vec( 1, 0, 1, 0.01 ), encoder_version=encoder, extractor_version=version,
                               created_at=created_at if created_at is not None else NOW - timedelta( days=1 ) )
    db.add( row )
    db.commit()
    return row


def _run( db, notification_id, model, now=NOW, **extra ):
    """
    Build the job over the test doubles and run its async body to the end.

    Ensures:
        - returns ( summary dict, job )
    """
    job = PrincipleExtractorJob( notification_id, str( OWNER ), "owner@example.com", query_fn=model, embed_fn=embed, session_factory=_factory( db ),
                                 model=MODEL, timeout_seconds=30, encoder=ENCODER, clock=lambda: now, **extra )
    return json.loads( asyncio.run( job._execute() ) ), job


def _counts( db ):
    """
    Count the principle and evidence rows.

    Ensures:
        - returns ( principles, evidence )
    """
    return db.query( PreferencePrinciple ).count(), db.query( PreferenceEvidence ).count()


def test_a_no_answer_creates_a_principle_and_a_supporting_evidence_row_with_both_times( db ):
    ask   = _ask( db, answer="no" )
    model = Model( _reply( _result( hypotheses=[ _hyp( condition="approval", grounded_in="card" ) ] ) ) )
    out, _ = _run( db, ask, model )
    principle = db.query( PreferencePrinciple ).one()
    evidence  = db.query( PreferenceEvidence ).one()
    assert out[ "status" ] == "extracted" and ( out[ "principles_created" ], out[ "evidence_written" ] ) == ( 1, 1 )
    assert ( principle.owner_id, principle.kind, principle.scope, principle.encoder_version ) == ( str( OWNER ), "ask_form", "global", ENCODER )
    assert principle.extractor_version == f"{MODEL}:extractor-v2-vocab-2026.11.19" and principle.embedding is not None
    assert principle.created_at.replace( tzinfo=timezone.utc ) == NOW
    assert ( evidence.relation, evidence.condition, evidence.source, evidence.field_key ) == ( "supports", "approval", "extractor", "$answer" )
    assert str( evidence.notification_id ) == ask and evidence.extractor_version == principle.extractor_version
    assert evidence.answered_at.replace( tzinfo=timezone.utc ) == T0 + timedelta( minutes=1 ) and evidence.extracted_at.replace( tzinfo=timezone.utc ) == NOW


def test_a_condition_not_in_the_card_or_answer_is_stored_as_unknown( db ):
    ask = _ask( db, answer="no" )
    _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp( condition="on release day" ) ] ) ) ) )
    assert db.query( PreferenceEvidence ).one().condition == "unknown"


def test_running_the_extractor_twice_over_the_same_answer_adds_nothing_the_second_time( db ):
    ask   = _ask( db, answer="no" )
    reply = _reply( _result( hypotheses=[ _hyp() ] ) )
    first, _  = _run( db, ask, Model( reply ) )
    after_one = _counts( db )
    second, _ = _run( db, ask, Model( reply ) )
    assert after_one == ( 1, 1 ) and _counts( db ) == after_one
    assert ( second[ "principles_created" ], second[ "principles_reused" ], second[ "evidence_written" ], second[ "evidence_existing" ] ) == ( 0, 1, 0, 1 )
    assert ( first[ "principles_created" ], first[ "evidence_written" ] ) == ( 1, 1 )


def test_a_new_extractor_version_appends_beside_the_old_rows_and_never_overwrites_them( db ):
    ask   = _ask( db, answer="no" )
    reply = _reply( _result( hypotheses=[ _hyp() ] ) )
    _run( db, ask, Model( reply ) )
    job = PrincipleExtractorJob( ask, str( OWNER ), "o@example.com", query_fn=Model( reply ), embed_fn=embed, session_factory=_factory( db ),
                                 model="claude-other-model", timeout_seconds=30, encoder=ENCODER, clock=lambda: NOW )
    asyncio.run( job._execute() )
    assert _counts( db ) == ( 2, 2 )
    assert { row.extractor_version for row in db.query( PreferenceEvidence ) } == { f"{MODEL}:extractor-v2-vocab-2026.11.19", "claude-other-model:extractor-v2-vocab-2026.11.19" }


def test_a_hypothesis_joins_a_named_principle_of_the_same_scope_even_when_the_dimension_differs( db ):
    known = _principle( db, dimension="ask.link_required" )
    ask   = _ask( db, answer="no" )
    out, _ = _run( db, ask, Model( _reply( _result( dimension="ask.approval_needs_link", hypotheses=[ _hyp( "Links matter for approvals." ) ],
                                                    relations={ str( known.id ): "refines" } ) ) ) )
    evidence = db.query( PreferenceEvidence ).one()
    assert db.query( PreferencePrinciple ).count() == 1 and evidence.principle_id == known.id and evidence.relation == "refines"
    assert out[ "dimension_mismatches" ] == [ { "principle_id": str( known.id ), "field_key": "$answer" } ] and out[ "principles_created" ] == 0


def test_two_paraphrased_answers_join_one_principle_when_the_double_names_it_for_the_second( db ):
    first  = _ask( db, 0, answer="no [comment: link it]" )
    second = _ask( db, 5, answer="no [comment: i need the approval link]" )
    _run( db, first, Model( _reply( _result( dimension="ask.approval_needs_link", hypotheses=[ _hyp() ] ) ) ) )
    principle = db.query( PreferencePrinciple ).one()
    # the second answer's paraphrase uses another dimension string, and the double names the first principle
    out, _ = _run( db, second, Model( _reply( _result( dimension="ask.link_for_approval", hypotheses=[ _hyp( "Approvals need a link to the thing." ) ],
                                                        relations={ str( principle.id ): "supports" } ) ) ), now=NOW + timedelta( minutes=5 ) )
    assert db.query( PreferencePrinciple ).count() == 1
    assert sorted( str( e.notification_id ) for e in db.query( PreferenceEvidence ) ) == sorted( [ first, second ] )
    assert out[ "dimension_mismatches" ] and db.query( PreferenceEvidence ).filter_by( principle_id=principle.id ).count() == 2


def test_a_named_principle_of_another_scope_is_not_joined_and_a_new_principle_is_made( db ):
    known = _principle( db, scope="project:lupin" )
    ask   = _ask( db, answer="no" )
    _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp( "A global habit." ) ], relations={ str( known.id ): "supports" } ) ) ) )
    assert db.query( PreferencePrinciple ).count() == 2 and db.query( PreferenceEvidence ).one().principle_id != known.id
    assert db.query( PreferencePrinciple ).filter( PreferencePrinciple.id != known.id ).one().continues_principle_id == known.id, "it names an earlier-version principle"


CURRENT = f"{MODEL}:extractor-v2-vocab-2026.11.19"


def _new_principle( db, known_ids ):
    """
    Return the one principle that is not among the known ones.

    Ensures:
        - returns the row; raises if there is not exactly one
    """
    return db.query( PreferencePrinciple ).filter( PreferencePrinciple.id.notin_( known_ids ) ).one()


def test_a_new_principle_continues_the_lowest_id_among_the_named_earlier_version_principles( db ):
    first  = _principle( db, scope="project:lupin", statement="One." )
    second = _principle( db, scope="project:lupin", statement="Two." )
    lowest = min( first.id, second.id, key=str )
    _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], relations={ str( first.id ): "refines", str( second.id ): "supports" } ) ) ) )
    assert _new_principle( db, [ first.id, second.id ] ).continues_principle_id == lowest


def test_a_relation_within_the_current_version_never_sets_continues_whatever_the_relation_word( db ):
    same = _principle( db, scope="project:lupin", version=CURRENT )
    _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], relations={ str( same.id ): "contradicts" } ) ) ) )
    assert _new_principle( db, [ same.id ] ).continues_principle_id is None


def test_a_principle_that_names_no_other_continues_none_and_a_reused_one_is_never_changed( db ):
    ask   = _ask( db, answer="no" )
    reply = _reply( _result( hypotheses=[ _hyp() ] ) )
    _run( db, ask, Model( reply ) )
    only  = db.query( PreferencePrinciple ).one()
    assert only.continues_principle_id is None
    earlier = _principle( db, scope="project:lupin", statement="Earlier.", vector=only.embedding )
    _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp() ], relations={ str( earlier.id ): "supports" } ) ) ) )
    db.refresh( only )
    assert only.continues_principle_id is None and db.query( PreferencePrinciple ).count() == 2


def test_every_evidence_row_carries_the_session_of_the_answered_ask_or_none_when_it_has_none( db ):
    ask = _ask( db, answer="no" )
    _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert [ e.session_key for e in db.query( PreferenceEvidence ) ] == [ "ab12cd34" ]
    bare = _ask( db, 5, answer="no", sender_id="claude.code@lupin.deepily.ai" )
    _run( db, bare, Model( _reply( _result( hypotheses=[ _hyp( "Another way to say it." ) ] ) ) ) )
    assert sorted( e.session_key is None for e in db.query( PreferenceEvidence ) ) == [ False, True ]


def test_a_bare_yes_adds_a_supporting_row_to_a_principle_that_applied_and_creates_no_principle( db ):
    known = _principle( db )
    ask   = _ask( db, answer="yes" )
    out, _ = _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp( "A new idea." ) ], relations={ str( known.id ): "supports" } ) ) ) )
    evidence = db.query( PreferenceEvidence ).one()
    assert db.query( PreferencePrinciple ).count() == 1 and evidence.principle_id == known.id and evidence.relation == "supports" and evidence.condition is None
    assert { "field_key": "$answer", "what": "hypotheses", "reason": "bare_yes_creates_none" } in out[ "rejected" ]


def test_a_bare_yes_with_no_principle_to_support_skips_the_model_call( db ):
    ask   = _ask( db, answer="yes" )
    model = Model( _reply() )
    out, _ = _run( db, ask, model )
    assert out[ "status" ] == "skipped_no_input" and model.sent == [] and _counts( db ) == ( 0, 0 )


def test_only_principles_of_the_current_encoder_are_shown_to_the_model_whatever_their_distance( db ):
    near_other = _principle( db, encoder=OLD_ENC, vector=vec( 1, 0, 1, 0.01 ), statement="Other encoder, nearest." )
    far_same   = _principle( db, vector=vec( 0, 1, 0, 0.01 ), statement="Same encoder, farther." )
    ask   = _ask( db, answer="no" )
    model = Model( _reply( _result( hypotheses=[ _hyp() ], relations={ str( near_other.id ): "supports" } ) ) )
    out, _ = _run( db, ask, model )
    assert "Same encoder, farther." in model.sent[ 0 ] and "Other encoder, nearest." not in model.sent[ 0 ] and str( far_same.id ) in model.sent[ 0 ]
    assert { "field_key": "$answer", "what": f"relation {near_other.id}", "reason": "principle_not_shown" } in out[ "rejected" ]
    assert db.query( PreferenceEvidence ).filter_by( principle_id=near_other.id ).count() == 0


def test_fetch_neighbours_filters_owner_and_encoder_ranks_by_best_cosine_and_cuts_to_k( db ):
    a = _principle( db, vector=vec( 1, 0, 0, 0 ), statement="a" )
    b = _principle( db, vector=vec( 0, 1, 0, 0 ), statement="b" )
    _principle( db, vector=vec( 1, 1, 0, 0 ), statement="c" )
    _principle( db, encoder=OLD_ENC, vector=vec( 1, 0, 0, 0 ) )
    _principle( db, owner=OTHER, vector=vec( 1, 0, 0, 0 ) )
    db.add( PreferencePrinciple( id=uuid.uuid4(), owner_id=str( OWNER ), kind="decision", dimension="d", statement="no vector", scope="global", embedding=None,
                                 encoder_version=ENCODER, extractor_version="x", created_at=NOW - timedelta( days=1 ) ) )
    db.add( PreferencePrinciple( id=uuid.uuid4(), owner_id=str( OWNER ), kind="decision", dimension="d", statement="zero", scope="global", embedding=vec( 0, 0, 0, 0 ),
                                 encoder_version=ENCODER, extractor_version="x", created_at=NOW - timedelta( days=1 ) ) )
    db.commit()
    got = store_module.fetch_neighbours( db, str( OWNER ), ENCODER, [ vec( 1, 0, 0, 0 ), vec( 0, 1, 0, 0 ) ], NOW, k=2 )
    assert sorted( row.statement for row in got ) == [ "a", "b" ] and len( got ) == 2
    assert [ row.statement for row in store_module.fetch_neighbours( db, str( OWNER ), ENCODER, [ vec( 1, 0, 0, 0 ) ], NOW, k=3 ) ][ :2 ] == [ "a", "c" ]
    assert a.id and b.id


def test_fetch_neighbours_cutoff_is_strict_and_hides_later_principles( db ):
    _principle( db, vector=vec( 1, 0, 0, 0 ), statement="earlier", created_at=NOW - timedelta( seconds=1 ) )
    _principle( db, vector=vec( 1, 0, 0, 0 ), statement="same moment", created_at=NOW )
    _principle( db, vector=vec( 1, 0, 0, 0 ), statement="later", created_at=NOW + timedelta( seconds=1 ) )
    got = store_module.fetch_neighbours( db, str( OWNER ), ENCODER, [ vec( 1, 0, 0, 0 ) ], NOW )
    assert [ row.statement for row in got ] == [ "earlier" ]


def test_an_answer_after_a_reveal_with_no_draft_is_used_and_reported_as_possibly_influenced( db ):
    ask = _ask( db, answer="no" )
    db.add( PredictionLog( id=uuid.uuid4(), notification_id=uuid.UUID( ask ), response_type="yes_no", category="c", prediction_strategy="s", predicted_at=T0,
                           prediction_confidence=0.5, similar_case_count=0, fold_opened_at=T0 + timedelta( seconds=30 ) ) )
    db.commit()
    model  = Model( _reply( _result( hypotheses=[ _hyp() ] ) ) )
    out, _ = _run( db, ask, model )
    assert out[ "possibly_influenced" ] == [ "$answer" ] and '"possibly_influenced": true' in model.sent[ 0 ] and out[ "status" ] == "extracted"


def test_an_answer_after_a_reveal_that_came_after_the_ask_time_uses_the_stored_draft( db ):
    ask = _ask( db, answer="no" )
    db.add( PredictionLog( id=uuid.uuid4(), notification_id=uuid.UUID( ask ), response_type="yes_no", category="c", prediction_strategy="s", predicted_at=T0,
                           prediction_confidence=0.5, similar_case_count=0, fold_opened_at=T0 + timedelta( seconds=30 ),
                           draft_at_reveal={ "value": "unaided draft text" } ) )
    db.commit()
    model  = Model( _reply( _result( hypotheses=[ _hyp() ] ) ) )
    out, _ = _run( db, ask, model )
    assert out[ "possibly_influenced" ] == [] and "unaided draft text" in model.sent[ 0 ] and out[ "status" ] == "extracted"


def test_an_answer_with_no_reveal_is_not_marked_influenced( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert out[ "possibly_influenced" ] == []


@pytest.mark.parametrize( "extra", [ dict( source="proxy" ), dict( answered_by=None ), dict( answered_by=OTHER ), dict( source="timeout_default" ) ] )
def test_an_answer_not_attributed_to_its_owner_writes_nothing_and_calls_no_model( db, extra ):
    model = Model( _reply( _result( hypotheses=[ _hyp() ] ) ) )
    out, _ = _run( db, _ask( db, **extra ), model )
    assert out[ "status" ] == "skipped_not_attributed" and model.sent == [] and _counts( db ) == ( 0, 0 )


def test_an_unattributable_stored_value_that_is_not_a_dict_is_skipped( db ):
    model = Model( _reply() )
    out, _ = _run( db, _ask( db, response_value=None ), model )
    assert out[ "status" ] == "skipped_not_attributed" and model.sent == []


def test_an_answer_that_cannot_be_read_calls_no_model( db ):
    model = Model( _reply() )
    out, _ = _run( db, _ask( db, answer="purple elephant" ), model )
    assert out[ "status" ] == "skipped_nothing_to_read" and model.sent == []


def test_a_card_answer_is_read_per_field_and_each_field_is_written_under_its_own_key( db ):
    options = { "questions": [ { "header": "held_bugs", "question": "Approve the held bugs?", "options": [ { "label": "Approve" }, { "label": "Hold" } ] },
                               { "header": "budget", "question": "Budget?", "input_type": "text" } ] }
    ask = _ask( db, response_type="multiple_choice", response_options=options,
                response_value={ "value": json.dumps( { "answers": { "held_bugs": "Hold", "budget": "no limit" } } ), "source": "ui", "answered_by": { "user_id": str( OWNER ) } } )
    model = Model( _reply( _result( "held_bugs", [ _hyp( "Hold bugs until they are linked.", condition="Hold" ) ] ),
                           _result( "budget", [ _hyp( "Skip budgets.", condition="no limit" ) ], dimension="decision.budget", kind="decision" ) ) )
    out, _ = _run( db, ask, model )
    assert { e.field_key for e in db.query( PreferenceEvidence ) } == { "held_bugs", "budget" } and out[ "evidence_written" ] == 2


def test_a_field_the_reply_leaves_out_is_reported_and_nothing_is_written_for_it( db ):
    ask = _ask( db, response_type="multiple_choice", response_options={ "questions": [ { "header": "a", "question": "A?", "options": [ { "label": "x" } ] } ] },
                response_value={ "value": json.dumps( { "answers": { "a": "x" } } ), "source": "ui", "answered_by": { "user_id": str( OWNER ) } } )
    out, _ = _run( db, ask, Model( _reply( _result( "unrelated", [ _hyp() ] ) ) ) )
    assert { "field_key": "a", "what": "field", "reason": "field_missing_from_reply" } in out[ "rejected" ] and _counts( db ) == ( 0, 0 )


def test_a_rejected_hypothesis_writes_nothing_and_is_listed_with_its_reason( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp( "x" * 240 ) ] ) ) ) )
    assert _counts( db ) == ( 0, 0 ) and out[ "rejected" ] == [ { "field_key": "$answer", "what": "hypothesis 0", "reason": "statement_too_long" } ]


def test_a_global_statement_naming_a_project_the_owner_asked_from_is_rejected_here_too( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp( "Lupin cards need approval links." ) ] ) ) ) )
    assert _counts( db ) == ( 0, 0 ) and out[ "rejected" ][ 0 ][ "reason" ] == "global_statement_names_project"


def test_a_dimension_outside_the_approved_headings_is_reported_and_the_principle_is_still_written( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], dimension="ask.approval_needs_link" ) ) ) )
    assert out[ "off_vocabulary" ] == [ { "field_key": "$answer", "dimension": "ask.approval_needs_link" } ] and _counts( db ) == ( 1, 1 )


def test_a_dimension_that_is_an_approved_heading_is_not_reported_and_is_stored_as_written( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], dimension="Fix the real cause" ) ) ) )
    assert out[ "off_vocabulary" ] == [] and _counts( db ) == ( 1, 1 )
    assert db.query( PreferencePrinciple ).one().dimension == "Fix the real cause"


def test_a_heading_in_the_wrong_case_is_off_vocabulary_because_the_match_is_exact( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], dimension="fix the real cause" ) ) ) )
    assert out[ "off_vocabulary" ] == [ { "field_key": "$answer", "dimension": "fix the real cause" } ]


def test_an_off_vocabulary_field_that_keeps_one_hypothesis_and_loses_another_is_still_reported_and_written( db ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp(), _hyp( "x" * 240 ) ], dimension="ask.approval_needs_link" ) ) ) )
    assert out[ "off_vocabulary" ] == [ { "field_key": "$answer", "dimension": "ask.approval_needs_link" } ]
    assert out[ "rejected" ] == [ { "field_key": "$answer", "what": "hypothesis 1", "reason": "statement_too_long" } ] and _counts( db ) == ( 1, 1 )


def test_a_bare_yes_field_with_an_off_vocabulary_dimension_writes_no_principle_and_is_not_reported( db ):
    known  = _principle( db )
    out, _ = _run( db, _ask( db, answer="yes" ), Model( _reply( _result( dimension="ask.approval_needs_link", relations={ str( known.id ): "supports" } ) ) ) )
    assert out[ "off_vocabulary" ] == [] and _counts( db ) == ( 1, 1 )


def test_a_relation_from_a_heading_to_an_old_name_under_that_heading_is_not_a_mismatch_but_another_heading_is( db ):
    same  = _principle( db, dimension="fix_depth", statement="Fix roots." )
    other = _principle( db, dimension="question_deduplication", statement="Ask once." )
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( dimension="Fix the real cause", hypotheses=[ _hyp( "Roots first." ) ],
                                                                         relations={ str( same.id ): "refines", str( other.id ): "supports" } ) ) ) )
    assert out[ "dimension_mismatches" ] == [ { "principle_id": str( other.id ), "field_key": "$answer" } ]


@pytest.mark.parametrize( "kind, dimension", [ ( "ask_form", "   " ), ( "not_a_kind", "ask.approval_needs_link" ) ] )
def test_a_wholly_rejected_field_is_not_also_listed_as_off_vocabulary( db, kind, dimension ):
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ], dimension=dimension, kind=kind ) ) ) )
    assert out[ "off_vocabulary" ] == [] and out[ "rejected" ][ 0 ][ "reason" ] == "kind_or_dimension_invalid" and _counts( db ) == ( 0, 0 )


def test_a_reply_that_is_not_json_is_reported_and_nothing_is_written( db ):
    out, _ = _run( db, _ask( db, answer="no", abstract=None ), Model( "I could not decide." ) )
    assert out[ "status" ] == "unparseable" and _counts( db ) == ( 0, 0 ) and out[ "off_vocabulary" ] == []


def test_a_missing_notification_is_a_lookup_error_and_a_model_failure_reaches_the_queue( db ):
    with pytest.raises( LookupError, match="does not exist" ):
        _run( db, str( uuid.uuid4() ), Model( _reply() ) )
    async def broken( prompt, options ):
        yield ResultMessage( subtype="error", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s", result="boom" )
    with pytest.raises( model_transport.ModelCallError ):
        _run( db, _ask( db, answer="no" ), broken )
    assert _counts( db ) == ( 0, 0 )


def test_do_all_runs_on_a_pool_worker_thread_with_no_loop_and_marks_the_job_completed( db ):
    ask = _ask( db, answer="no" )
    job = PrincipleExtractorJob( ask, str( OWNER ), "o@example.com", query_fn=Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ), embed_fn=embed,
                                 session_factory=_factory( db ), model=MODEL, timeout_seconds=30, encoder=ENCODER, clock=lambda: NOW )
    with concurrent.futures.ThreadPoolExecutor( max_workers=1 ) as pool:
        text = pool.submit( job.do_all ).result( timeout=30 )
    assert json.loads( text )[ "status" ] == "extracted" and job.state == JobState.COMPLETED and _counts( db ) == ( 1, 1 )
    assert job.session_id == "principle-extractor" and job.id_hash.startswith( "pe-" ) and job.last_question_asked == f"[Principle extractor] {ask}"


def test_a_failed_run_marks_the_job_failed_and_raises( db ):
    job = PrincipleExtractorJob( str( uuid.uuid4() ), str( OWNER ), "o@example.com", query_fn=Model( _reply() ), embed_fn=embed, session_factory=_factory( db ),
                                 model=MODEL, timeout_seconds=30, encoder=ENCODER )
    with pytest.raises( LookupError ): job.do_all()
    assert job.state == JobState.FAILED


def test_the_job_sends_the_owner_nothing_a_full_run_calls_no_notification_progress_or_voice_helper( db, monkeypatch ):
    def forbidden( *args, **kwargs ): raise AssertionError( "the extractor must stay silent" )
    for name in ( "notify_progress", "notify_completion" ): monkeypatch.setattr( AgenticJobBase, name, forbidden )
    import cosa.agents.utils.voice_io as voice_io
    monkeypatch.setattr( voice_io, "notify", forbidden )
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert out[ "status" ] == "extracted"


SENDING_MODULES = ( "voice", "agent_notification_dispatcher", "routers.notifications", "notification_fifo_queue", "notification_proxy", "websocket" )


def test_no_extractor_module_imports_a_module_that_sends_to_the_owner():
    for module in ( job_module, prompt_module, rules_module, store_module ):
        tree  = ast.parse( inspect.getsource( module ) )
        names = [ alias.name for node in ast.walk( tree ) if isinstance( node, ast.Import ) for alias in node.names ]
        names += [ node.module or "" for node in ast.walk( tree ) if isinstance( node, ast.ImportFrom ) ]
        assert not [ n for n in names if any( sending in n.lower() for sending in SENDING_MODULES ) ], ( module.__name__, names )


def test_settings_come_from_the_ini_keys_when_not_given_and_the_extractor_version_names_the_model():
    job = PrincipleExtractorJob( str( uuid.uuid4() ), str( OWNER ), "o@example.com" )
    model, timeout, encoder = job._settings()
    assert model == "claude-sonnet-5-5" and timeout == 180 and encoder == "nomic-ai/nomic-embed-text-v1.5:statement-rationale-v1"
    assert job_module.encoder_version() == encoder


def test_the_string_the_extractor_stores_is_the_string_retrieval_filters_on():
    """
    The extractor stores principles under one encoder string, and retrieval filters on one.

    The two once differed ( ":statement-rationale-v1" against "|statement-and-rationale-v1" ), so a retrieval
    built from the retrieval side would have matched no stored row. One side is pinned to a literal here.
    """
    from cosa.agents.prediction_engine.principle_retrieval import encoder_version_of
    model = "nomic-ai/nomic-embed-text-v1.5"
    assert encoder_version_of( model ) == "nomic-ai/nomic-embed-text-v1.5:statement-rationale-v1"
    assert job_module.encoder_version() == encoder_version_of( model )


def test_the_default_embedding_and_session_doors_call_the_projects_own_helpers( monkeypatch ):
    import cosa.memory.embedding_provider as provider
    import cosa.rest.db.database as database
    seen = []
    class FakeProvider:
        def generate_embedding( self, text, content_type ):
            seen.append( ( text, content_type ) )
            return [ 1.0, 2.0 ]
    monkeypatch.setattr( provider, "get_embedding_provider", lambda: FakeProvider() )
    assert job_module.default_embed( "x" ) == [ 1.0, 2.0 ] and seen == [ ( "x", "prose" ) ]
    @contextmanager
    def fake_get_db():
        yield "a session"
    monkeypatch.setattr( database, "get_db", fake_get_db )
    with job_module.default_session() as session: assert session == "a session"


def test_the_job_uses_the_default_doors_when_none_are_given( db, monkeypatch ):
    import cosa.memory.embedding_provider as provider
    import cosa.rest.db.database as database
    monkeypatch.setattr( provider, "get_embedding_provider", lambda: SimpleNamespace( generate_embedding=lambda text, content_type: embed( text ) ) )
    monkeypatch.setattr( database, "get_db", _factory( db ) )
    ask = _ask( db, answer="no" )
    job = PrincipleExtractorJob( ask, str( OWNER ), "o@example.com", query_fn=Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ), model=MODEL, timeout_seconds=30, encoder=ENCODER )
    assert json.loads( asyncio.run( job._execute() ) )[ "status" ] == "extracted" and _counts( db ) == ( 1, 1 )


def test_the_model_is_called_through_the_transport_module_so_a_patch_on_complete_is_seen( db, monkeypatch ):
    seen = []
    async def fake_complete( model, system, user, query_fn=None, timeout_seconds=None, **kw ):
        seen.append( ( model, timeout_seconds ) )
        return _reply( _result( hypotheses=[ _hyp() ] ) )
    monkeypatch.setattr( model_transport, "complete", fake_complete )
    out, _ = _run( db, _ask( db, answer="no" ), None )
    assert seen == [ ( MODEL, 30 ) ] and out[ "status" ] == "extracted"


def _switches( monkeypatch, *keys ):
    """Turn only the named learner switches on, as the job reads them."""
    monkeypatch.setattr( PrincipleExtractorJob, "_flag", lambda self, key: key in keys )


def test_with_every_new_switch_off_an_unread_yes_no_text_is_skipped_and_the_version_has_no_tags( db ):
    ask    = _ask( db, answer="Maybe later" )
    model  = Model( _reply() )
    out, _ = _run( db, ask, model )
    assert out[ "status" ] == "skipped_nothing_to_read" and model.sent == []
    assert prompt_module.current_extractor_version( MODEL, lambda key: False ) == f"{MODEL}:{prompt_module.PROMPT_VERSION}"


def test_an_unread_yes_no_text_reaches_the_writer_with_the_flag_when_the_unread_switch_is_on( db, monkeypatch ):
    _switches( monkeypatch, prompt_module.UNREAD_KEY )
    known  = _principle( db )
    ask    = _ask( db, answer="Maybe later" )
    model  = Model( _reply( _result( relations={ str( known.id ): "refines" } ) ) )
    out, _ = _run( db, ask, model )
    assert out[ "status" ] == "extracted" and '"unread_stance": true' in model.sent[ 0 ] and "Maybe later" in model.sent[ 0 ]
    row = db.query( PreferenceEvidence ).one()
    assert row.relation == "refines" and row.extractor_version.endswith( "+unread" )


def test_an_unread_yes_no_text_may_create_a_principle_like_any_non_bare_answer( db, monkeypatch ):
    _switches( monkeypatch, prompt_module.UNREAD_KEY )
    ask    = _ask( db, answer="Maybe later" )
    out, _ = _run( db, ask, Model( _reply( _result( hypotheses=[ _hyp( "Hold the ask until the owner is back." ) ] ) ) ) )
    assert out[ "status" ] == "extracted" and _counts( db ) == ( 1, 1 )


def test_an_unreadable_card_answer_stays_skipped_with_the_unread_switch_on( db, monkeypatch ):
    _switches( monkeypatch, prompt_module.UNREAD_KEY )
    ask    = _ask( db, answer="{not an answers map", response_type="multiple_choice" )
    model  = Model( _reply() )
    out, _ = _run( db, ask, model )
    assert out[ "status" ] == "skipped_nothing_to_read" and model.sent == []


def test_a_bare_yes_contradicting_a_principle_is_stored_as_contradicts_only_with_the_bare_yes_switch_on( db, monkeypatch ):
    known = _principle( db )
    reply = _reply( _result( relations={ str( known.id ): "contradicts" } ) )
    out, _ = _run( db, _ask( db, answer="yes" ), Model( reply ) )
    assert db.query( PreferenceEvidence ).count() == 0 and { "field_key": "$answer", "what": f"relation {known.id}", "reason": "bare_yes_only_supports" } in out[ "rejected" ]
    _switches( monkeypatch, prompt_module.BARE_YES_KEY )
    out, _ = _run( db, _ask( db, minutes=10, answer="yes" ), Model( reply ) )
    evidence = db.query( PreferenceEvidence ).one()
    assert evidence.relation == "contradicts" and evidence.condition is None and evidence.extractor_version.endswith( "+bareyes" )


def test_an_uninformative_bare_yes_is_stored_with_its_antecedent_quote_and_no_condition_when_the_switch_is_on( db, monkeypatch ):
    known = _principle( db )
    field = _result( relations={ str( known.id ): "uninformative" } )
    field[ "antecedents" ] = { str( known.id ): { "quote": "when the card names a deadline", "card_lacks_it": True } }
    reply = _reply( field )
    out, _ = _run( db, _ask( db, answer="yes" ), Model( reply ) )
    assert db.query( PreferenceEvidence ).count() == 0 and out[ "rejected" ][ 0 ][ "reason" ] == "relation_unknown"
    _switches( monkeypatch, prompt_module.UNINFORMATIVE_KEY )
    out, _ = _run( db, _ask( db, minutes=10, answer="yes" ), Model( reply ) )
    evidence = db.query( PreferenceEvidence ).one()
    assert evidence.relation == "uninformative" and evidence.antecedent == "when the card names a deadline" and evidence.condition is None
    assert evidence.extractor_version.endswith( "+uninformative" )


def test_an_uninformative_reply_without_the_quote_is_refused_and_writes_no_row( db, monkeypatch ):
    _switches( monkeypatch, prompt_module.UNINFORMATIVE_KEY )
    known  = _principle( db )
    out, _ = _run( db, _ask( db, answer="yes" ), Model( _reply( _result( relations={ str( known.id ): "uninformative" } ) ) ) )
    assert db.query( PreferenceEvidence ).count() == 0 and out[ "rejected" ][ 0 ][ "reason" ] == "uninformative_without_quote"


def test_a_supporting_row_leaves_the_antecedent_column_empty( db ):
    known = _principle( db )
    _run( db, _ask( db, answer="yes" ), Model( _reply( _result( relations={ str( known.id ): "supports" } ) ) ) )
    assert db.query( PreferenceEvidence ).one().antecedent is None


@pytest.mark.skipif( not os.environ.get( "LUPIN_LIVE_UNREAD_TEXTS" ), reason="live check: set LUPIN_LIVE_UNREAD_TEXTS to a JSON list of { title, message, abstract, text } for the unread yes/no texts" )
def test_live_the_unread_yes_no_texts_each_produce_a_stored_row_through_the_real_model( db, monkeypatch ):
    """Live check (plan row 3): the real model reads each unread text; none is skipped."""
    _switches( monkeypatch, job_module.UNREAD_KEY )
    texts = json.load( open( os.environ[ "LUPIN_LIVE_UNREAD_TEXTS" ] ) )
    assert len( texts ) == 4
    for item in texts:
        ask = _ask( db, answer=item[ "text" ], title=item[ "title" ], message=item[ "message" ], abstract=item[ "abstract" ] )
        job = PrincipleExtractorJob( ask, str( OWNER ), "owner@example.com", embed_fn=embed, session_factory=_factory( db ), model="claude-sonnet-5-5",
                                     timeout_seconds=180, encoder=ENCODER, clock=lambda: NOW )
        before = db.query( PreferenceEvidence ).count()
        assert json.loads( asyncio.run( job._execute() ) )[ "status" ] == "extracted"
        assert db.query( PreferenceEvidence ).count() > before
