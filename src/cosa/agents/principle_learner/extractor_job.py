"""
The principle extractor: a queued job turning one human answer into evidence.

The job runs after an answer. It reads the ask through episode_view and decodes the answer.
It asks one model for hypotheses per field and holds the reply to the rules in extractor_rules.
Then it writes principles and evidence rows. It sends the owner nothing: no notification, no progress card, no voice.

The model door is cosa.repo.doc_lint.model_transport.complete, awaited inside _execute. The queue's pool runs
do_all on a worker thread, where asyncio.run has no loop to clash with.
"""

import asyncio
import json
import threading
import time
import uuid
from contextlib import contextmanager

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.prediction_engine.episode_view import episode_view, revealed_at, revealed_draft
from cosa.agents.prediction_engine.history_derive import attribution_tier, derive_answer
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.agents.principle_learner import extractor_store
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt, parse_reply
from cosa.agents.principle_learner.extractor_rules import card_text, check_field, field_answers, project_names, unaided_answer
from cosa.agents.principle_learner.vocabulary import is_heading
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo.doc_lint import model_transport
from cosa.rest.postgres_models import Notification
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import sender_session_suffix
import cosa.utils.util as cu

SESSION_ID         = "principle-extractor"
MODEL_KEY          = "prediction learner extractor model"
TIMEOUT_KEY        = "prediction learner extractor timeout seconds"
ENCODER_MODEL_KEY  = "local embedding prose model name"
ENCODER_RECIPE     = "statement-rationale-v1"
OWNER_SOURCE       = "ui"
PROBE_SYSTEM       = "Answer with the single word ok."
PROBE_QUESTION     = "Are you there?"


def encoder_version():
    """
    Name the embedding model and the text recipe that make a principle's vector.

    Requires:
        - the INI file carries the prose embedding model name

    Ensures:
        - returns "<model name>:<recipe>", the string stored in encoder_version
    """
    return f"{ConfigurationManager( env_var_name='LUPIN_CONFIG_MGR_CLI_ARGS' ).get_required( ENCODER_MODEL_KEY )}:{ENCODER_RECIPE}"


def default_embed( text ):
    """
    Embed one text with the configured embedding provider, as prose.

    Requires:
        - text is a non-empty string
        - the configured provider makes 768-dimension vectors, the width of the principle table's column

    Ensures:
        - returns the provider's vector as a list of floats
        - a provider that makes another width fails loudly when a principle is stored, never silently
    """
    from cosa.memory.embedding_provider import get_embedding_provider
    return get_embedding_provider().generate_embedding( text, content_type="prose" )


@contextmanager
def default_session():
    """
    Open a database session that commits on success and rolls back on error.

    Ensures:
        - yields what cosa.rest.db.database.get_db yields
    """
    from cosa.rest.db.database import get_db
    with get_db() as session: yield session


class PrincipleExtractorJob( AgenticJobBase ):
    """
    Extract principles and evidence from one answered ask, silently.

    Requires:
        - notification_id names an answered notification
        - user_id and user_email are the answering owner's id and email

    Ensures:
        - the session id is fixed at "principle-extractor"
        - the job never calls a notification, progress or voice helper
        - a skipped answer (not attributed to its owner, or nothing to read) writes nothing and calls no model
    """

    JOB_TYPE   = "principle_extractor"
    JOB_PREFIX = "pe"

    def __init__( self, notification_id, user_id, user_email, query_fn=None, embed_fn=None, session_factory=None, model=None,
                  timeout_seconds=None, encoder=None, clock=None, probe=False, debug=False, verbose=False ):
        """
        Build the job.

        Requires:
            - notification_id is a notification UUID, as text or UUID
            - query_fn, embed_fn, session_factory, model, timeout_seconds, encoder and clock are None or test stand-ins:
              query_fn as model_transport.complete takes it, embed_fn from text to vector, session_factory a context manager
              yielding a session, clock a callable returning an aware datetime

        Ensures:
            - the job id has the "pe" prefix and the session id is "principle-extractor"
            - model, timeout and encoder are read from the INI file when the job runs, not here
            - probe True makes the job check the model door and touch no notification or table
            - cost_summary is None, so a done or dead queue listing can serialize the job
        """
        super().__init__( user_id=user_id, user_email=user_email, session_id=SESSION_ID, debug=debug, verbose=verbose )
        self.notification_id = str( notification_id )
        self.query_fn        = query_fn
        self.embed_fn        = embed_fn
        self.session_factory = session_factory
        self.model           = model
        self.timeout_seconds = timeout_seconds
        self.encoder         = encoder
        self.clock           = clock
        self.probe           = probe
        self.cost_summary    = None  # queues.py reads it on every agentic job; the extractor reports no cost

    @property
    def last_question_asked( self ):
        """
        Display string for the queue listing.

        Ensures:
            - returns "[Principle extractor] " and the notification id
        """
        return f"[Principle extractor] {self.notification_id}"

    def do_all( self ):
        """
        Run the extraction to completion.

        Ensures:
            - returns the conversational summary the queue stores
            - raises whatever _execute raises, after the state is marked failed
        """
        return self._run_execute( "PrincipleExtractorJob", self.notification_id, "Extraction failed" )

    def _settings( self ):
        """
        Resolve the model, timeout and encoder version for this run.

        Ensures:
            - returns ( model, timeout_seconds, encoder_version ), each taken from the constructor when given, else from the INI file
            - the extractor version is the model id and the prompt version, so a new prompt appends rows beside the old ones

        Raises:
            - MissingConfigKeyError if a needed INI key is absent
        """
        config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        model  = self.model if self.model is not None else config.get_required( MODEL_KEY )
        limit  = self.timeout_seconds if self.timeout_seconds is not None else config.get_required( TIMEOUT_KEY, return_type="int" )
        return model, limit, self.encoder if self.encoder is not None else encoder_version()

    async def _execute( self ):
        """
        Read the answer, ask the model once, and write the checked result.

        Ensures:
            - returns a JSON summary: status, counts, the rejections with their reasons, the dimension mismatches,
              the off-vocabulary dimensions and the fields marked possibly influenced
            - a kept field with at least one written hypothesis whose dimension is not one of the approved headings
              is listed in off_vocabulary, and its principles are still written; the check reports, it never blocks
            - status is skipped_review_card, skipped_not_attributed, skipped_nothing_to_read, skipped_no_input, unparseable or extracted
            - evidence rows carry answered_at from the answer and extracted_at from the clock
            - nothing is sent to the owner

        Raises:
            - LookupError if the notification does not exist
            - whatever model_transport.complete raises, so the queue sees the failure
        """
        if self.probe: return await self._probe_model_door()
        model, timeout, encoder = self._settings()
        embed = self.embed_fn if self.embed_fn is not None else default_embed
        with ( self.session_factory if self.session_factory is not None else default_session )() as session:
            summary = await self._extract( session, model, timeout, encoder, embed )
        return summary

    async def _probe_model_door( self ):
        """
        Check, from this server process, that the model door answers or fails with a named error.

        The probe makes the same call the extractor makes, through the same class and the same await,
        with one fixed question. It reads nothing from the database and sends the owner nothing.

        Requires:
            - runs inside _execute, so a loop is already running on this pool worker thread

        Ensures:
            - returns JSON with status probe_ok when the call returns non-empty text, else probe_error
            - probe_error carries the error class name and message of a ModelCallError or CallBudgetExceeded
            - the JSON names the model, the timeout, the thread, whether a loop was running, the transport,
              the CLI path as set ( None means unset ), the cap for the model as a literal ( None means no cap )
              and every cap in model_transport.BUDGET_CAPS
            - the call is bounded by the timeout, so the probe never hangs

        Raises:
            - MissingConfigKeyError if the model or timeout key is absent
            - any exception other than the two named above, so the queue sees a real failure
        """
        model, timeout, _ = self._settings()
        report = {
            "model"         : model,
            "timeout"       : timeout,
            "thread"        : threading.current_thread().name,
            "loop_running"  : asyncio.get_running_loop().is_running(),
            "transport"     : model_transport.TRANSPORT,
            "cli_path"      : model_transport.CLI_PATH,
            "budget_cap"    : model_transport.BUDGET_CAPS.get( model ),
            "budget_caps"   : dict( model_transport.BUDGET_CAPS ),
        }
        started = time.monotonic()
        try:
            text = await model_transport.complete( model, PROBE_SYSTEM, PROBE_QUESTION, query_fn=self.query_fn, timeout_seconds=timeout )
        except ( model_transport.ModelCallError, model_transport.CallBudgetExceeded ) as e:
            report.update( { "status": "probe_error", "error_type": type( e ).__name__, "error": str( e ) } )
        else:
            report.update( { "status": "probe_ok", "reply": text.strip()[ :200 ] } )
        report[ "seconds" ] = round( time.monotonic() - started, 2 )
        return json.dumps( report, sort_keys=True )

    async def _extract( self, session, model, timeout, encoder, embed ):
        """
        Do the work of one extraction inside an open session.

        Requires:
            - session is an active SQLAlchemy session
            - model, timeout and encoder are the run's settings and embed takes a text and returns a vector

        Ensures:
            - returns the JSON summary _execute documents
            - writes through the session only; the caller commits
        """
        extractor = f"{model}:{PROMPT_VERSION}"
        row = session.get( Notification, uuid.UUID( self.notification_id ) )
        if row is None: raise LookupError( f"notification {self.notification_id} does not exist" )
        if is_review_card( row.response_options ): return self._summary( "skipped_review_card" )
        raw = { "recipient_id": str( row.recipient_id ), "response_type": row.response_type, "response_value": row.response_value }
        if attribution_tier( raw ) != "recipient" or not isinstance( row.response_value, dict ) or row.response_value.get( "source" ) != OWNER_SOURCE:
            return self._summary( "skipped_not_attributed" )
        entries = field_answers( derive_answer( raw )[ 0 ] )
        if not entries: return self._summary( "skipped_nothing_to_read" )
        episode    = episode_view( session, row.id )
        draft      = revealed_draft( session, row.id )
        reveal     = revealed_at( session, row.id )
        influenced = []
        for entry in entries:
            entry[ "text" ], entry[ "possibly_influenced" ] = unaided_answer( entry[ "text" ], draft, entry[ "field_key" ], reveal, row.responded_at )
            if entry[ "possibly_influenced" ]: influenced.append( entry[ "field_key" ] )
        vectors    = [ embed( card_text( episode ) ) ] + [ embed( entry[ "text" ] ) for entry in entries if entry[ "text" ] ]
        now        = self.clock() if self.clock is not None else aware_moment( cu.get_current_datetime_iso() )
        neighbours = extractor_store.fetch_neighbours( session, str( row.recipient_id ), encoder, vectors, now )
        if all( entry[ "bare_yes" ] for entry in entries ) and not neighbours: return self._summary( "skipped_no_input" )
        reply      = await model_transport.complete( model, SYSTEM_PROMPT, build_user_prompt( episode, entries, neighbours ),
                                                     query_fn=self.query_fn, timeout_seconds=timeout )
        fields     = parse_reply( reply )
        if fields is None: return self._summary( "unparseable", influenced=influenced )
        senders  = [ sender for ( sender, ) in session.query( Notification.sender_id ).filter( Notification.recipient_id == row.recipient_id ).distinct() ]
        projects = project_names( senders )
        report   = { "principles_created": 0, "principles_reused": 0, "evidence_written": 0, "evidence_existing": 0, "dimension_mismatches": [], "off_vocabulary": [], "rejected": [] }
        ids      = { str( principle.id ) for principle in neighbours }
        by_key   = { field.get( "field_key" ): field for field in fields }
        for entry in entries:
            if entry[ "field_key" ] not in by_key:
                report[ "rejected" ].append( { "field_key": entry[ "field_key" ], "what": "field", "reason": "field_missing_from_reply" } )
                continue
            grounding = card_text( episode ) + "\n" + entry[ "text" ]
            checked   = check_field( by_key[ entry[ "field_key" ] ], grounding, projects, entry[ "bare_yes" ], ids )
            report[ "rejected" ].extend( { "field_key": entry[ "field_key" ], **item } for item in checked[ "rejected" ] )
            # field_kept is redundant today, because a wholly rejected field keeps no hypotheses; it stays so the rule reads as stated
            field_kept = not any( item[ "what" ] == "field" for item in checked[ "rejected" ] )
            if field_kept and checked[ "hypotheses" ] and not is_heading( checked[ "dimension" ] ):
                report[ "off_vocabulary" ].append( { "field_key": entry[ "field_key" ], "dimension": checked[ "dimension" ] } )
            extractor_store.apply_field( session, str( row.recipient_id ), row.id, entry[ "field_key" ], checked, neighbours,
                                         ( aware_moment( row.responded_at ), now ), ( extractor, encoder ), embed,
                                         sender_session_suffix( row.sender_id ), report )
        return self._summary( "extracted", report=report, influenced=influenced )

    def _summary( self, status, report=None, influenced=None ):
        """
        Write the job's result as a JSON string.

        Requires:
            - status is one of the status words _execute documents

        Ensures:
            - returns JSON with status, the report counters (zeros when none), and the possibly-influenced field keys
        """
        base = { "principles_created": 0, "principles_reused": 0, "evidence_written": 0, "evidence_existing": 0, "dimension_mismatches": [], "off_vocabulary": [], "rejected": [] }
        return json.dumps( { "status": status, **( report or base ), "possibly_influenced": influenced or [] }, sort_keys=True )
