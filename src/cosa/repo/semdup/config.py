"""The frozen configuration of the duplicate checker: built, written once, checked per run."""
import hashlib
import json
import os
import uuid

from cosa.repo.doc_lint import model_transport
from cosa.repo.semdup import errors as err
from cosa.repo.symindex import dups
from cosa.repo.symindex.candidates.vector_store import canonical

MODEL_ID       = "claude-fable-5-1"
PROMPT_NAME    = "semdup"
MAX_CANDIDATES = 10
MIN_CANDIDATES = 5
LIST_DEPTH     = 10
FUSION_HEAD    = 2
CLONE_COVER    = 0.5
JSCPD_KEYS     = ( "version", "min_tokens", "min_lines", "chosen_in" )
ELIDED_FIELD   = "config_sha"


def _sha( text ):
    """
    Return the hex sha256 of a string.

    Requires:
        - text is a string

    Ensures:
        - returns 64 lower-case hex digits
    """
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def is_empty( value ):
    """
    Say whether a decision field is still unset.

    Requires:
        - nothing about value

    Ensures:
        - True for None and for a string that is empty or only white space
        - False for everything else, so a temperature of 0 counts as set
    """
    return value is None or ( isinstance( value, str ) and value.strip() == "" )


def config_sha( cfg ):
    """
    Return the sha of a configuration, taken over every field except its own sha.

    Requires:
        - cfg is a dict that can be written as JSON

    Ensures:
        - the same fields give the same sha whatever the key order
        - a change to any field other than config_sha changes it
    """
    payload = { key: value for key, value in cfg.items() if key != ELIDED_FIELD }
    return _sha( canonical( payload ) )


def build_config( backend, temperature, unscorable_policy, system_prompt, user_template, parser_source, scrub, body_chars, jscpd, clone_cover=CLONE_COVER, min_nodes=dups.DEFAULT_MIN_NODE ):
    """
    Build the configuration dict that freeze writes, holding every constant of a run.

    Requires:
        - backend, temperature and unscorable_policy are the decisions of rulings P4 and P5; they have no default and may be
          None or empty here, which freeze (or aggregate_runs, for the policy) then refuses
        - system_prompt, user_template and parser_source are the judge's prompt texts and the source of its parser
        - scrub is the list of blindness tokens
        - body_chars is the cut applied to a body before it is embedded
        - jscpd is a dict with the four keys version, min_tokens, min_lines and chosen_in

    Ensures:
        - returns a dict holding model_id, the three decisions, prompt_version, the prompt, parser and scrub shas, the
          candidate constants, body_chars, clone_cover, jscpd and config_sha
        - prompt_version changes when any word of the prompt or any line of the parser changes
        - the scrub sha does not depend on the order of the tokens
        - config_sha equals config_sha( the dict )

    Raises:
        - ValueError if jscpd lacks a key or carries an extra one
    """
    if set( jscpd ) != set( JSCPD_KEYS ): raise ValueError( f"jscpd must hold exactly {list( JSCPD_KEYS )}, got {sorted( jscpd )}" )
    cfg = {
        "model_id"          : MODEL_ID,
        "backend"           : backend,
        "temperature"       : temperature,
        "unscorable_policy" : unscorable_policy,
        "prompt_version"    : model_transport.prompt_version( PROMPT_NAME, system_prompt, user_template, parser_source ),
        "system_prompt_sha" : _sha( system_prompt ),
        "parser_sha"        : _sha( parser_source ),
        "min_nodes"         : min_nodes,
        "max_candidates"    : MAX_CANDIDATES,
        "min_candidates"    : MIN_CANDIDATES,
        "list_depth"        : LIST_DEPTH,
        "fusion_head"       : FUSION_HEAD,
        "body_chars"        : body_chars,
        "clone_cover"       : clone_cover,
        "jscpd"             : { key: jscpd[ key ] for key in JSCPD_KEYS },
        "scrub_sha"         : _sha( json.dumps( sorted( scrub ) ) ),
    }
    cfg[ ELIDED_FIELD ] = config_sha( cfg )
    return cfg


def freeze( cfg, path ):
    """
    Write the configuration to path once and return its sha.

    Requires:
        - cfg came from build_config and was not edited afterwards
        - path names a file inside a folder, which may not exist yet

    Ensures:
        - nothing is written unless backend and temperature are both set (a temperature of 0 is set)
        - the file appears under its final name complete or not at all: it is written to a temporary name and linked into place, and the link fails if a file is there
        - so two freezes cannot both succeed, no file is ever replaced, and a kill mid-write leaves no partial frozen file
        - returns config_sha of the written configuration

    Raises:
        - SemdupError CONFIG_UNDECIDED if backend or temperature is empty, naming which
        - SemdupError CONFIG_DRIFT if cfg was edited after build_config
        - SemdupError CONFIG_ALREADY_FROZEN if a file exists at path
    """
    unset = [ name for name in ( "backend", "temperature" ) if is_empty( cfg[ name ] ) ]
    if unset: raise err.SemdupError( err.CONFIG_UNDECIDED, f"{' and '.join( unset )} not decided (parking item P4)" )
    if cfg[ ELIDED_FIELD ] != config_sha( cfg ): raise err.SemdupError( err.CONFIG_DRIFT, "the configuration was edited after build_config" )
    folder = os.path.dirname( path )
    os.makedirs( folder, exist_ok=True )
    tmp = os.path.join( folder, f".{os.path.basename( path )}.{os.getpid()}.{uuid.uuid4().hex}.tmp" )
    with open( tmp, "w", encoding="utf-8" ) as f: f.write( json.dumps( cfg, indent=2, sort_keys=True ) + "\n" )
    try:
        os.link( tmp, path )
    except FileExistsError:
        raise err.SemdupError( err.CONFIG_ALREADY_FROZEN, f"a frozen configuration already exists at {path}" ) from None
    finally:
        os.unlink( tmp )
    return cfg[ ELIDED_FIELD ]


def verify_frozen( path, live ):
    """
    Check the frozen file against its own sha and against what this run would use.

    Requires:
        - path is a frozen file written by freeze
        - live is the dict build_config gives for the prompt, parser, scrub list and constants in the code now

    Ensures:
        - returns the frozen configuration when its recomputed sha equals its stored sha and every other field equals the
          live one
        - every field is compared on its own, and the error names each field that differs

    Raises:
        - FileNotFoundError if there is no file at path
        - SemdupError CONFIG_DRIFT if the file was edited, or a live field differs from the frozen one
    """
    with open( path, encoding="utf-8" ) as f: frozen = json.load( f )
    recomputed = config_sha( frozen )
    if recomputed != frozen[ ELIDED_FIELD ]: raise err.SemdupError( err.CONFIG_DRIFT, f"stored sha {frozen[ ELIDED_FIELD ]} but the file recomputes to {recomputed}" )
    differing = sorted( key for key in set( frozen ) | set( live ) if key != ELIDED_FIELD and frozen.get( key ) != live.get( key ) )
    if differing: raise err.SemdupError( err.CONFIG_DRIFT, f"live values differ from the frozen file in: {', '.join( differing )}" )
    return frozen


def aggregate_runs( reports, cfg ):
    """
    Hand the run reports to the unscorable-run policy, refusing when none is named.

    Requires:
        - reports is a list of run reports, each with a "run" id; an unscorable one has status "unscorable"
        - cfg is a configuration dict

    Ensures:
        - never drops, zero-fills or excludes a run
        - returns { "reports", "unscorable", "policy" }: the reports as given, the run ids of the unscorable ones in
          input order, and the policy name from cfg, for the stop rule of the scoring phase to apply

    Raises:
        - SemdupError POLICY_UNDECIDED if any report is unscorable while unscorable_policy is empty (parking item P5)
    """
    unscorable = [ report[ "run" ] for report in reports if report.get( "status" ) == "unscorable" ]
    if unscorable and is_empty( cfg[ "unscorable_policy" ] ):
        raise err.SemdupError( err.POLICY_UNDECIDED, f"runs {', '.join( unscorable )} are unscorable and no policy is named (parking item P5)" )
    return { "reports": list( reports ), "unscorable": unscorable, "policy": cfg[ "unscorable_policy" ] }
