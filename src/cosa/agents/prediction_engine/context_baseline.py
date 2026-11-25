"""
The Haiku baseline: a background forecast of one card, read from the card itself.

It is the baseline job the principles forecast and the Opus twins wait on, as ``principles_forecast``'s docstring defines it.
``ContextBaseline`` holds that contract: the model, the timeout, the error classes, the prompts, the parser and a cached call.
``run_context_forecast`` runs it for one ask through ``principles_forecast.run_arm`` with no principle block.
So the switch, the concurrency cap, the single row per card and the not-ready reasons are that function's, not a second copy.

The prompt is built in layers, and each layer is a field of the card.
The layers are the question and its fields, then the options and selection mode, then the title and abstract with their links.
The last layer is the asker's default and time budget. Both are inputs, never a label.
Earlier questions and informational updates are not part of this unit.

Every model reply is cached in a ledger keyed on the system and user prompt together.
A repeat is then a read and costs no call.
The forecast never selects, prefills or submits anything; it is stored and, behind its own switch, shown.
"""

import asyncio
import inspect
import json
import os
import re
import threading

import cosa.utils.util as cu
from cosa.agents.prediction_engine import full_answer
from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.agents.prediction_engine.principles_forecast import REASON_SWITCH, STATUS_NOT_RUN, cap_gate, run_arm, switch_enabled
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo.doc_lint import model_transport
from lupin_mcp.reuse_needset.draft import SharedLedger, ask_ledgered, make_ledger

ARM                = "C0"
SWITCH_KEY         = "prediction engine context forecast enabled"
DISPLAY_KEY        = "prediction engine context display enabled"
MODEL_KEY          = "prediction engine context model"
TIMEOUT_KEY        = "prediction engine context timeout seconds"
CAP_KEY            = "prediction engine context max concurrent"
LAYERS_KEY         = "prediction engine context layers"
LEDGER_KEY         = "prediction engine context ledger path"
LEDGER_SLOT        = "prediction-context"
LEDGER_LABEL       = "prediction-context"
ALL_LAYERS         = ( "prompt", "options", "title_abstract", "default_time" )
SUPPORTED_TYPES    = ( "yes_no", "multiple_choice" )
YES_NO_ANSWERS     = ( "yes", "no" )

SYSTEM_PROMPT = (
    "You forecast how one person will answer a question an AI coding assistant puts to them. You see only the card as it was shown. "
    "You do not decide for them and you do not choose anything for them: you state the answer you expect and how sure you are. "
    "A default or a time limit on the card says what happens if they do not answer. It is not their answer, and it is not evidence of one. "
    "Reply with one JSON object and nothing else."
)
YES_NO_FORMAT = 'Reply: {"answer": "yes" or "no", "confidence": a number from 0 to 1}.'
CHOICE_FORMAT = 'Reply: {"answers": {"<field name>": "<the option label exactly as written>"}, "confidence": a number from 0 to 1}. For a field that allows several options, give a list of labels.'


class UnsupportedAsk( ValueError ):
    """The card is of a response type this forecast does not read."""


def _text_setting( key ):
    """
    Read one required text setting.

    Requires:
        - the INI file carries the key

    Ensures:
        - returns the value as a non-empty string

    Raises:
        - MissingConfigKeyError if the key is missing or blank
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( key, return_type="string" )


def context_model():
    """
    Read the model id the baseline calls.

    Requires:
        - the INI file carries the key named by MODEL_KEY

    Ensures:
        - returns the id as a non-empty string, never a value written in code

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so the call never falls back to another model
    """
    return _text_setting( MODEL_KEY )


def context_timeout():
    """
    Read how many seconds one baseline call may take.

    Requires:
        - the INI file carries the key named by TIMEOUT_KEY

    Ensures:
        - returns a positive number

    Raises:
        - MissingConfigKeyError if the key is missing or blank
        - ValueError if the value is not above zero
    """
    seconds = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( TIMEOUT_KEY, return_type="float" )
    if seconds <= 0: raise ValueError( f"'{TIMEOUT_KEY}' must be above zero, got {seconds}" )
    return seconds


def context_layers():
    """
    Read which layers of the card the prompt carries.

    Requires:
        - the INI file carries the key named by LAYERS_KEY: a comma list of layer names

    Ensures:
        - returns the layers in ALL_LAYERS order, each at most once

    Raises:
        - ValueError if the list names a layer not in ALL_LAYERS, or names none
    """
    named = [ part.strip() for part in _text_setting( LAYERS_KEY ).split( "," ) if part.strip() ]
    bad   = [ name for name in named if name not in ALL_LAYERS ]
    if bad or not named: raise ValueError( f"'{LAYERS_KEY}' must name layers from {ALL_LAYERS}, got {named!r}" )
    return tuple( layer for layer in ALL_LAYERS if layer in named )


def context_forecast_enabled():
    """
    Say whether the background forecast call is switched on.

    Ensures:
        - returns True only when the INI key named by SWITCH_KEY is true; an unreadable setting reads as off
    """
    return switch_enabled( SWITCH_KEY )


def context_display_enabled():
    """
    Say whether the forecast is shown on the card.

    Ensures:
        - returns True only when the INI key named by DISPLAY_KEY is true; an unreadable setting reads as off
        - off never stops the background call: the call keeps running as the learner's baseline arm
    """
    return switch_enabled( DISPLAY_KEY )


def context_gate():
    """
    Make the cap gate of the baseline from its INI setting.

    Requires:
        - the INI file carries the key named by CAP_KEY

    Ensures:
        - returns a CapGate that lets in as many calls as the key says

    Raises:
        - the errors read_cap raises for a missing or non-positive setting
    """
    return cap_gate( CAP_KEY )


def _field_lines( episode, with_options ):
    """
    Describe the card's fields, with their options when that layer is on.

    Requires:
        - episode is episode_view's result

    Ensures:
        - returns one line per field naming its prompt and, for the options layer, its selection mode and each option label
          with its description; an option the asker flagged as recommended says so
    """
    lines = []
    for field in episode[ "fields" ]:
        line = f"- {field[ 'key' ] or 'field'}: {field[ 'prompt' ] or ''}".rstrip()
        if with_options:
            if field[ "mode" ] == "text": line += " (free text)"
            else:
                labels = "; ".join( f"\"{o[ 'label' ]}\"" + ( f" - {o[ 'description' ]}" if o[ "description" ] else "" ) + ( " (recommended by the asker)" if o[ "recommended" ] else "" )
                                    for o in field[ "options" ] )
                line += f" ({'several may be chosen' if field[ 'mode' ] == 'multi' else 'one may be chosen'}) options: {labels}"
        lines.append( line )
    return lines


def build_user_prompt( episode, layers=ALL_LAYERS ):
    """
    Build the user prompt from the layers of the card.

    Requires:
        - episode is episode_view's result: it carries message, response_type, fields, title, abstract, links, default and timeout_seconds
        - layers is a subset of ALL_LAYERS

    Ensures:
        - the prompt holds only fields of the card as shown, never a later answer, status or history
        - the prompt layer is the question and each field's prompt; the options layer adds each field's selection mode, labels,
          descriptions and recommended flags; the title_abstract layer adds the title, the abstract and the links in it with what each
          points to, so an approval link is visible; the default_time layer adds the default and the time budget, worded as inputs
        - ends with the reply format for the card's type

    Raises:
        - UnsupportedAsk if the card's response type is not in SUPPORTED_TYPES
    """
    kind = episode[ "response_type" ]
    if kind not in SUPPORTED_TYPES: raise UnsupportedAsk( f"the baseline forecasts {SUPPORTED_TYPES}, not {kind!r}" )
    parts = [ f"Question: {episode[ 'message' ]}" ]
    fields = _field_lines( episode, "options" in layers )
    if fields: parts.append( "Fields:\n" + "\n".join( fields ) )
    if "title_abstract" in layers:
        if episode[ "title" ]: parts.append( f"Title: {episode[ 'title' ]}" )
        if episode[ "abstract" ]: parts.append( f"Abstract:\n{episode[ 'abstract' ]}" )
        links = "\n".join( f"- {link[ 'kind' ]} link to {link[ 'target' ]}" for link in episode[ "links" ] )
        parts.append( "Links in the abstract:\n" + links if links else "Links in the abstract: none" )
    if "default_time" in layers:
        default = episode[ "default" ]
        limit   = episode[ "timeout_seconds" ]
        parts.append( "If nobody answers" + ( f" within {limit} seconds" if limit else "" ) + ", the card " +
                      ( f"falls back to \"{default}\"" if default else "has no fallback" ) + ". That fallback is not their answer." )
    parts.append( YES_NO_FORMAT if kind == "yes_no" else CHOICE_FORMAT )
    return "\n\n".join( parts )


def _confidence_of( value ):
    """
    Read the reply's confidence.

    Requires:
        - value is the parsed reply object

    Ensures:
        - returns a float from 0 to 1, read by full_answer._probability

    Raises:
        - a plain ValueError, never a ReplyRefused, if confidence is missing, not a number or outside 0 to 1; its message begins with the reason
          full_answer gave, because run_arm stores a ReplyRefused as a refusal and a plain error as unreadable_forecast
    """
    try:
        return full_answer._probability( value.get( "confidence" ), "confidence" )
    except full_answer.ReplyRefused as refused:
        raise ValueError( str( refused ) ) from refused


def _choice_of( field, given ):
    """
    Check one field's answer against the options the card offered.

    Requires:
        - field is one of episode_view's fields with options; given is the reply's value for it

    Ensures:
        - returns the label, or for a multi-select field the list of labels, each exactly as the card wrote it

    Raises:
        - ValueError if a label is not one of the field's options, or a single-choice field is given a list or several labels
    """
    labels  = [ option[ "label" ] for option in field[ "options" ] ]
    chosen  = given if isinstance( given, list ) else [ given ]
    unknown = [ label for label in chosen if label not in labels ]
    if unknown or not chosen: raise ValueError( f"field {field[ 'key' ]!r}: {unknown or given!r} is not among {labels}" )
    if field[ "mode" ] != "multi" and isinstance( given, list ): raise ValueError( f"field {field[ 'key' ]!r} takes one option, got a list" )
    return given


def parse_reply( text, episode ):
    """
    Turn the model's reply into the typed forecast.

    Requires:
        - text is the model's reply; episode is episode_view's result for the same card

    Ensures:
        - a yes/no card returns { "value": "yes" or "no", "confidence": float }
        - a multiple-choice card returns { "answers": { field key: label or labels }, "confidence": float }, one entry per option field,
          every label exactly as the card wrote it
        - a free-text field of a multiple-choice card is not forecast and is left out of answers

    Raises:
        - ValueError if the reply is unreadable, names an answer or option the card did not offer, or leaves out a field
        - UnsupportedAsk if the card's response type is not in SUPPORTED_TYPES
    """
    kind = episode[ "response_type" ]
    if kind not in SUPPORTED_TYPES: raise UnsupportedAsk( f"the baseline forecasts {SUPPORTED_TYPES}, not {kind!r}" )
    value      = recover_json_object( text )
    if not isinstance( value, dict ): raise ValueError( "the reply holds no JSON object" )
    confidence = _confidence_of( value )
    if kind == "yes_no":
        answer = value.get( "answer" )
        if answer not in YES_NO_ANSWERS: raise ValueError( f"answer must be one of {YES_NO_ANSWERS}, got {answer!r}" )
        return { "value": answer, "confidence": confidence }
    given   = value.get( "answers" )
    if not isinstance( given, dict ): raise ValueError( "answers must be an object of field name to option" )
    answers = {}
    for field in episode[ "fields" ]:
        if field[ "mode" ] == "text": continue
        if field[ "key" ] not in given: raise ValueError( f"the reply leaves out field {field[ 'key' ]!r}" )
        answers[ field[ "key" ] ] = _choice_of( field, given[ field[ "key" ] ] )
    if not answers: raise ValueError( "the card has no option field to forecast" )
    return { "answers": answers, "confidence": confidence }


def build_full_user_prompt( episode, layers=ALL_LAYERS ):
    """
    Build the user prompt that asks for the full-answer reply.

    Requires:
        - episode is episode_view's result for a card whose type is in full_answer.FULL_ANSWER_TYPES
        - layers is a subset of ALL_LAYERS

    Ensures:
        - returns build_user_prompt's text for the card with its old reply format swapped for full_answer's format for the card's type
        - when the card has option fields and the options layer is on, a block lists each option's stable id before the format

    Raises:
        - UnsupportedAsk if the card's response type is not in full_answer.FULL_ANSWER_TYPES
    """
    kind = episode[ "response_type" ]
    if kind not in full_answer.FULL_ANSWER_TYPES: raise UnsupportedAsk( f"the baseline forecasts {full_answer.FULL_ANSWER_TYPES}, not {kind!r}" )
    old    = YES_NO_FORMAT if kind in ( "yes_no", "open_ended" ) else CHOICE_FORMAT
    body   = build_user_prompt( { **episode, "response_type": "yes_no" if old == YES_NO_FORMAT else "multiple_choice" }, layers ).removesuffix( old )
    ids    = [ f"- {field[ 'key' ] or 'field'}: " + "; ".join( f"[{one}] \"{option[ 'label' ]}\"" for one, option in zip( full_answer.option_ids_of( field ), field[ "options" ] ) )
               for field in episode[ "fields" ] if field[ "options" ] ]
    block  = "Option ids, to be given exactly as written:\n" + "\n".join( ids ) + "\n\n" if ids and "options" in layers else ""
    return body + block + full_answer.FULL_FORMATS[ kind ]


def parse_full( text, episode ):
    """
    Turn a full-answer reply into the forecast record.

    Requires:
        - text is the model's reply; episode is episode_view's result for the same card

    Ensures:
        - returns full_answer.parse_full_reply's forecast record

    Raises:
        - UnsupportedAsk if the card's response type is not in full_answer.FULL_ANSWER_TYPES
        - full_answer.ReplyRefused, a ValueError that names its reason, for a reply it cannot read
    """
    kind = episode[ "response_type" ]
    if kind not in full_answer.FULL_ANSWER_TYPES: raise UnsupportedAsk( f"the baseline forecasts {full_answer.FULL_ANSWER_TYPES}, not {kind!r}" )
    return full_answer.parse_full_reply( text, episode )


def predictor_version( layers=ALL_LAYERS, full=False ):
    """
    Name the prompt and parser the baseline runs, so a change to either is a new version.

    Requires:
        - layers is a subset of ALL_LAYERS; full is True when the full-answer reply is on

    Ensures:
        - returns model_transport.prompt_version over the system prompt, the layers, and the source of the prompt builder and the parser
        - with full, the source of the whole full_answer module and of the two full-answer entry points is added, so a change to its formats or to any helper the parser calls is a new version
        - without full the value is the one this function gave before the full-answer reply existed
    """
    parts = [ "context-baseline", SYSTEM_PROMPT, ",".join( layers ), inspect.getsource( build_user_prompt ), inspect.getsource( parse_reply ), inspect.getsource( _choice_of ) ]
    if full: parts += [ "full-answer", inspect.getsource( full_answer ), inspect.getsource( build_full_user_prompt ), inspect.getsource( parse_full ) ]
    return model_transport.prompt_version( *parts )


def open_ledger( base_path=None, cli_path=None ):
    """
    Open the baseline's ledger, one file per Claude Code binary version.

    Requires:
        - base_path is None (read the INI key named by LEDGER_KEY, relative to the project root) or a file path ending .jsonl
        - cli_path is None (the SDK's own binary) or the path of a Claude Code binary

    Ensures:
        - the file name carries the binary's version, so an upgrade starts a new ledger and recomputes, and a ledger is never read under another binary
        - the directory exists
        - returns a draft.SharedLedger over draft.make_ledger's ledger, bound to the binary and LEDGER_LABEL
    """
    base    = base_path if base_path is not None else cu.get_project_root() + _text_setting( LEDGER_KEY )
    version = re.sub( r"[^A-Za-z0-9.]+", "-", model_transport.cli_version( cli_path ) or "bundled" ).strip( "-" )
    path    = base[ :-len( ".jsonl" ) ] + f"-{version}.jsonl"
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    return SharedLedger( make_ledger( path, cli_path, LEDGER_LABEL ) )


class ContextBaseline:
    """
    The baseline contract of principles_forecast, in one object.

    It holds the model, the timeout, the error classes, the prompts, the parser, the version and a cached call.
    """

    def __init__( self, model, timeout_seconds, layers, ledger, query_fn=None, full=None ):
        """
        Build the baseline.

        Requires:
            - model is a non-empty model id; timeout_seconds is above zero; layers is a subset of ALL_LAYERS
            - ledger has get( key ) and put( key, value )
            - query_fn is None, or a stand-in for the SDK with sdk_query's signature, for tests
            - full is None (read the full-answer switch once, now) or a bool

        Ensures:
            - the switch is read once here, so the prompt, the parser and the version of this baseline always agree
            - the members principles_forecast.check_baseline reads are all present
            - errors holds the model errors and the call-budget refusal, so a refused or failed call stores a not-ready row
        """
        self.model             = model
        self.timeout_seconds   = timeout_seconds
        self.layers            = tuple( layers )
        self.ledger            = ledger
        self.query_fn          = query_fn
        self.errors            = ( model_transport.ModelCallError, model_transport.CallBudgetExceeded )
        self.full              = full_answer.full_answer_enabled() if full is None else full
        self.predictor_version = predictor_version( self.layers, self.full )

    def build_prompts( self, episode ):
        """
        Return ( system prompt, user prompt ) for a card.

        Requires:
            - episode is episode_view's result

        Raises:
            - UnsupportedAsk as build_user_prompt does
        """
        return SYSTEM_PROMPT, build_full_user_prompt( episode, self.layers ) if self.full else build_user_prompt( episode, self.layers )

    def parse( self, text, episode ):
        """
        Return the typed forecast for a reply, as parse_reply does.

        Requires:
            - text is the reply; episode is episode_view's result
        """
        return parse_full( text, episode ) if self.full else parse_reply( text, episode )

    async def complete( self, model, system, user, timeout_seconds=None ):
        """
        Return the model's reply, from the ledger when the same prompt was answered before.

        Requires:
            - model, system and user are the call's model id and prompts

        Ensures:
            - a ledger hit makes no call
            - the ledger key holds the model, this version and the system and user prompt joined by a null character, so a changed system prompt can never return a stale reply
            - a miss makes one bounded call that ends, and kills its child process, at timeout_seconds
            - the reply is written to the ledger only when the call returned text

        Raises:
            - ModelCallError, ModelCallTimeout or CallBudgetExceeded as model_transport.complete does
        """
        limit = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        ask   = lambda system_prompt, user_prompt: asyncio.run( model_transport.complete( model, system_prompt, user_prompt, query_fn=self.query_fn, timeout_seconds=limit ) )
        return await asyncio.to_thread( ask_ledgered, ask, self.ledger, self.predictor_version, model, system, user, "", LEDGER_SLOT, key_new=system + "\0" + user )


_BASELINE = None
_GATE     = None
_LOCK     = threading.Lock()


def get_baseline():
    """
    Return this process's baseline, made on first use from the INI settings.

    Ensures:
        - one baseline, one ledger and one cap gate per process, so two calls never write separate ledgers
    """
    global _BASELINE, _GATE
    with _LOCK:
        if _BASELINE is None:
            _BASELINE = ContextBaseline( context_model(), context_timeout(), context_layers(), open_ledger( cli_path=model_transport.CLI_PATH ) )
            _GATE     = context_gate()
        return _BASELINE, _GATE


def reset_baseline():
    """Forget this process's baseline and gate, so the next call reads the settings again."""
    global _BASELINE, _GATE
    with _LOCK: _BASELINE, _GATE = None, None


async def run_context_forecast( notification_id, session_factory=None, c0=None, gate=None, enabled=None, clock=None ):
    """
    Make the baseline forecast for one ask and store its row under the baseline arm.

    Requires:
        - notification_id names an ask whose notification row is committed
        - session_factory is None (the app's database sessions) or returns a context-managed session
        - c0 and gate are None (this process's own) or a baseline and a CapGate, for tests
        - enabled is None (read the INI switch) or a bool

    Ensures:
        - is principles_forecast.run_arm with the baseline arm, no principle block and no version suffix, so its switch, cap, single row and not-ready reasons hold
        - with the switch off nothing is read, called or written, and the baseline is not built
        - returns { status, reason } as run_arm does

    Raises:
        - the errors get_baseline raises when the switch is on and a setting is missing
    """
    if not ( switch_enabled( SWITCH_KEY ) if enabled is None else enabled ): return { "status": STATUS_NOT_RUN, "reason": REASON_SWITCH }
    if c0 is None or gate is None:
        made_c0, made_gate = get_baseline()
        c0   = made_c0 if c0 is None else c0
        gate = made_gate if gate is None else gate
    if session_factory is None:
        from cosa.rest.db.database import get_db
        session_factory = get_db
    return await run_arm( ARM, SWITCH_KEY, "", False, session_factory, notification_id, c0, None, "", "", gate, enabled=True, clock=clock )
