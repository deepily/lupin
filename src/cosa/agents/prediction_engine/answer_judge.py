"""
The model judge: does a forecast keep what the answer asked, and add nothing.

accuracy_comparators._ask_judge takes the callable that make_judge builds. The model splits each
text into atoms. It gives every atom a coverage or contradiction status against the other text.
The two booleans are computed here from those statuses, never taken from the model.

The call goes through bounded Claude Code (model_transport). It exposes no temperature. So a
verdict is tied to a recorded identity: the model, the rubric file's sha256, and the
sha256 of everything else that shapes a verdict.
"""

import dataclasses
import hashlib
import inspect
import json

from claude_agent_sdk import query as sdk_query

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo.doc_lint import model_transport
from cosa.utils.file_hash import file_sha256

MODEL_KEY             = "principle learner answer judge model"
RUBRIC_PATH           = "/src/conf/prompts/answer-judge-rubric.txt"
NO_TEXT               = "(none)"
ACTUAL_STATUSES       = ( "covered", "missing", "contradicted" )
PREDICTED_STATUSES    = ( "supported", "unsupported", "contradicted" )
EVIDENCED_STATUSES    = ( "covered", "supported", "contradicted" )
IDENTITY_FIELDS       = ( "model", "rubric_sha256", "prompt_sha256" )
SAMPLING_FIELDS       = ( "temperature", "top_p", "top_k", "seed" )


class JudgeReplyError( ValueError ):
    """The model's reply could not be read as a verdict; the reply text is kept on raw_reply."""

    def __init__( self, reason, raw_reply ):
        """
        Keep the reason and the reply that failed it.

        Requires:
            - reason and raw_reply are strings

        Ensures:
            - the message is the reason, and raw_reply holds the text unchanged
        """
        super().__init__( reason )
        self.raw_reply = raw_reply


class JudgeHashMismatch( RuntimeError ):
    """The judge about to be used is not the one whose identity was recorded."""


def _plain( text ):
    """
    Normalise a text for the quote check: lower case, single spaces.

    Requires:
        - text is a string

    Ensures:
        - returns the case-folded words joined by one space
    """
    return " ".join( text.casefold().split() )


def build_user_prompt( predicted_text, actual_text, suffix ):
    """
    Put the two texts inside tags that neither text can close.

    Requires:
        - each text is a string or None; suffix occurs in neither

    Ensures:
        - a None or blank text is shown as NO_TEXT
        - returns the actual block, then the predicted block
    """
    actual    = actual_text    if ( actual_text    or "" ).strip() else NO_TEXT
    predicted = predicted_text if ( predicted_text or "" ).strip() else NO_TEXT
    return model_transport.wrap( "actual", suffix, actual ) + "\n" + model_transport.wrap( "predicted", suffix, predicted )


def _read_atoms( rows, statuses, own_text, other_text, side, reply ):
    """
    Check one atom list of a reply and return it cleaned.

    Requires:
        - rows is the parsed list value; statuses are the words allowed on this side
        - own_text is the text this list splits and other_text the one its evidence quotes

    Ensures:
        - returns [ { atom, status, evidence } ]; evidence is None for a status that needs none
        - an evidenced status carries words that occur in other_text, ignoring case and spacing
        - a side with text has at least one atom and a side without text has none

    Raises:
        - JudgeReplyError when any of that does not hold
    """
    if not isinstance( rows, list ): raise JudgeReplyError( f"{side} is not a list", reply )
    if bool( rows ) != bool( own_text.strip() ): raise JudgeReplyError( f"{side} must hold atoms exactly when its text is not empty", reply )
    atoms = []
    for row in rows:
        if not isinstance( row, dict ): raise JudgeReplyError( f"{side} holds a row that is not an object", reply )
        atom, status, evidence = row.get( "atom" ), row.get( "status" ), row.get( "evidence" )
        if not isinstance( atom, str ) or not atom.strip(): raise JudgeReplyError( f"{side} holds an atom with no text", reply )
        if status not in statuses: raise JudgeReplyError( f"{side} holds an unknown status {status!r}", reply )
        if status not in EVIDENCED_STATUSES:
            evidence = None
        elif not isinstance( evidence, str ) or not _plain( evidence ) or _plain( evidence ) not in _plain( other_text ):
            raise JudgeReplyError( f"{side}: the evidence for {atom!r} does not quote the other text", reply )
        atoms.append( { "atom": atom, "status": status, "evidence": evidence } )
    return atoms


def parse_verdict( reply, predicted_text, actual_text ):
    """
    Turn a model reply into a verdict, computing both booleans from the atom statuses.

    Requires:
        - reply is the model's text; predicted_text and actual_text are the strings or None it was asked about

    Ensures:
        - returns { keeps_every_restriction, invents_nothing, actual_atoms, predicted_atoms }
        - keeps_every_restriction is True when every actual atom is covered
        - invents_nothing is True when every predicted atom is supported
        - a code fence or words around the one JSON object are ignored

    Raises:
        - JudgeReplyError when the reply holds no readable object of the stated shape
    """
    try:
        data = json.loads( reply[ reply.find( "{" ) : reply.rfind( "}" ) + 1 ] )
    except json.JSONDecodeError as error:
        raise JudgeReplyError( f"the reply holds no JSON object: {error}", reply ) from error
    predicted, actual = predicted_text or "", actual_text or ""
    actual_atoms      = _read_atoms( data.get( "actual_atoms" ), ACTUAL_STATUSES, actual, predicted, "actual_atoms", reply )
    predicted_atoms   = _read_atoms( data.get( "predicted_atoms" ), PREDICTED_STATUSES, predicted, actual, "predicted_atoms", reply )
    return {
        "keeps_every_restriction" : all( a[ "status" ] == "covered" for a in actual_atoms ),
        "invents_nothing"         : all( a[ "status" ] == "supported" for a in predicted_atoms ),
        "actual_atoms"            : actual_atoms,
        "predicted_atoms"         : predicted_atoms,
    }


def judge_model():
    """
    Read the model id the judge calls.

    Requires:
        - the INI file carries the key named by MODEL_KEY

    Ensures:
        - returns the id as a non-empty string, never a value written in code

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so the call never falls back to another model
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( MODEL_KEY, return_type="string" )


def judge_identity( model=None, rubric_path=None ):
    """
    Name the judge by what it would send and how it would read the answer.

    Requires:
        - model is a model id, or None for judge_model(); rubric_path is None for the committed rubric, or a path to a rubric file

    Ensures:
        - returns { model, rubric_sha256, prompt_sha256 }
        - rubric_sha256 is the sha256 of the rubric file's bytes
        - prompt_sha256 changes when the transport's call profile or tag wrapper, the rubric, the prompt builder,
          the reader, the word for an empty text or a status list changes
    """
    model  = model or judge_model()
    path   = rubric_path or cu.get_project_root() + RUBRIC_PATH
    rubric = cu.get_file_as_string( path )
    shaped = ( build_user_prompt, model_transport.wrap, _plain, _read_atoms, parse_verdict )
    words  = repr( ( NO_TEXT, ACTUAL_STATUSES, PREDICTED_STATUSES, EVIDENCED_STATUSES ) )
    parts  = [ model_transport.CALL_PROFILE, rubric, words ] + [ inspect.getsource( f ) for f in shaped ]
    return {
        "model"         : model,
        "rubric_sha256" : file_sha256( path ),
        "prompt_sha256" : hashlib.sha256( "\0".join( parts ).encode( "utf-8" ) ).hexdigest(),
    }


def check_identity( recorded, current ):
    """
    Refuse a judge that is not the recorded one.

    Requires:
        - recorded and current carry IDENTITY_FIELDS

    Ensures:
        - returns None when all three agree

    Raises:
        - JudgeHashMismatch naming every field that differs
    """
    differs = [ field for field in IDENTITY_FIELDS if recorded[ field ] != current[ field ] ]
    if differs: raise JudgeHashMismatch( "refusing to score: the judge differs from the recorded one in " + ", ".join( differs ) )


def request_settings( options ):
    """
    Read the settings of a request the transport is about to send.

    Requires:
        - options is the ClaudeAgentOptions dataclass of one call

    Ensures:
        - returns { model, max_turns, tools, permission_mode, sampling }
        - sampling holds each of SAMPLING_FIELDS the options class has, with its value; it is {} when it has none
    """
    names = { field.name for field in dataclasses.fields( options ) }
    return {
        "model"           : options.model,
        "max_turns"       : options.max_turns,
        "tools"           : options.tools,
        "permission_mode" : options.permission_mode,
        "sampling"        : { name: getattr( options, name ) for name in SAMPLING_FIELDS if name in names },
    }


def make_judge( model=None, complete=model_transport.complete_sync, query_fn=None, rubric_path=None, expected_identity=None ):
    """
    Build the judge( predicted_text, actual_text ) that the complete-action comparators call.

    Requires:
        - model is a model id, or None for judge_model()
        - complete has model_transport.complete_sync's signature ( model, system, user, query_fn=... )
        - query_fn is None for the SDK's query, or an async generator standing in for it
        - expected_identity is None, or a recorded judge_identity

    Ensures:
        - returns judge( predicted_text, actual_text ), each text a string or None
        - the judge returns parse_verdict's dict plus raw_reply, identity and request_settings
        - two empty texts pass with no model call, and then raw_reply and request_settings are None
        - request_settings is read from the request the transport sent, and is None when complete sent none
        - the rubric is read once, here, so the text sent is the text hashed

    Raises:
        - JudgeHashMismatch when expected_identity differs from this judge's identity
        - the judge raises JudgeReplyError for an unreadable reply, and whatever complete raises
    """
    model    = model or judge_model()
    path     = rubric_path or cu.get_project_root() + RUBRIC_PATH
    rubric   = cu.get_file_as_string( path )
    identity = judge_identity( model, path )
    if expected_identity is not None: check_identity( expected_identity, identity )
    send     = sdk_query if query_fn is None else query_fn

    def judge( predicted_text, actual_text ):
        """Ask the model about one pair of texts and read its verdict."""
        predicted, actual = predicted_text or "", actual_text or ""
        if not predicted.strip() and not actual.strip():
            return { "keeps_every_restriction": True, "invents_nothing": True, "actual_atoms": [], "predicted_atoms": [],
                     "raw_reply": None, "identity": identity, "request_settings": None }
        sent = []

        async def observe( prompt, options ):
            """Note the request's settings, then pass it on."""
            sent.append( request_settings( options ) )
            async for message in send( prompt=prompt, options=options ): yield message

        suffix = model_transport.new_suffix( predicted, actual )
        reply  = complete( model, rubric, build_user_prompt( predicted, actual, suffix ), query_fn=observe )
        verdict = parse_verdict( reply, predicted, actual )
        verdict.update( raw_reply=reply, identity=identity, request_settings=sent[ -1 ] if sent else None )
        return verdict

    return judge


def quick_smoke_test():
    """Read one hand-written reply and print the identity, with no model call."""
    cu.print_banner( "Answer Judge Smoke Test", prepend_nl=True )
    reply   = '{"actual_atoms": [{"atom": "staging only", "status": "covered", "evidence": "staging"}], "predicted_atoms": [{"atom": "staging", "status": "supported", "evidence": "staging only"}]}'
    verdict = parse_verdict( reply, "on staging", "staging only" )
    print( f"✓ verdict: keeps={verdict[ 'keeps_every_restriction' ]} invents_nothing={verdict[ 'invents_nothing' ]}" )
    print( f"✓ identity: {judge_identity()}" )


if __name__ == "__main__":
    quick_smoke_test()
