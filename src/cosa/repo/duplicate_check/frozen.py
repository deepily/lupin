"""The decided values of the frozen configuration, and the command that freezes them."""
import argparse
import json
import pathlib

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs
from cosa.repo.duplicate_check import blind, config, errors as err, judge

CONF_FOLDER       = "/src/conf"
FROZEN_GLOB       = "semdup-frozen-*.json"   # one file per judge model; semdup-frozen-2.json is kept because the passing record names it
# P4, provisional: row dc71467c re-asks before the experiments. A change here is a new frozen file and a proof rerun.
BACKEND           = judge.MaxPlanBackend.name
TEMPERATURE       = judge.MaxPlanBackend.temperature_record
# P5 (Rick, voice ruling of the freeze day): an unscorable run takes the worst rank in its arm and is reported by name with its cause. Phase 8 registers the policy of this name.
UNSCORABLE_POLICY = "worst-rank"
# Two distinctive strings the Phase 5 harness writes to mark its arms (Cheech's go); the blindness census proves neither occurs in any definition.
ARM_LABELS        = ( "arm-label-with-9c41e7", "arm-label-without-9c41e7" )
# Cheech's go: 10,000 characters cut 0.88% of the 10,158 pool definitions of 25 nodes or more (p50 938, p90 3,131, p99 9,166, max 70,712).
BODY_CHARS        = 10000
# jscpd's own defaults, as plan C4 says, except max_size: its default of 100 kb skips the 1.4 MB monolith without a word (label prep, row 6e821290).
# chosen_in names the run that set the values.
JSCPD             = { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "max_size": "5mb", "chosen_in": "label-prep-max-size" }


def selected_model():
    """
    Return the judge model this run uses.

    Ensures:
        - returns the value of `duplicate check judge model` in lupin-app.ini, read when called
    """
    return chs.model_id( chs.JUDGE_MODEL_KEY )


def frozen_path():
    """
    Return where the selected model's frozen configuration lives.

    Ensures:
        - returns the one file of src/conf matching semdup-frozen-*.json whose model_id is the selected model
        - when none matches, returns src/conf/semdup-frozen-<model>.json, which does not exist, so verify_frozen raises FileNotFoundError naming the model and a caller that only builds a path still works

    Raises:
        - DuplicateCheckError CONFIG_DRIFT if more than one such file exists
    """
    model   = selected_model()
    folder  = pathlib.Path( cu.get_project_root() + CONF_FOLDER )
    matches = [ str( path ) for path in sorted( folder.glob( FROZEN_GLOB ) ) if json.loads( path.read_text( encoding="utf-8" ) )[ "model_id" ] == model ]
    if not matches: return str( folder / f"semdup-frozen-{model}.json" )
    if len( matches ) > 1: raise err.DuplicateCheckError( err.CONFIG_DRIFT, f"more than one frozen file for judge model {model!r}: {matches}" )
    return matches[ 0 ]


def live_config():
    """
    Build the configuration this code would run with now.

    Ensures:
        - returns build_config over the decided values above, the selected model, the judge's prompt, template and parser, and the scrub list of the tool tokens and ARM_LABELS
        - two calls return equal dicts, so verify_frozen can compare a run with the file
    """
    return config.build_config( BACKEND, TEMPERATURE, UNSCORABLE_POLICY, *judge.prompt_parts(), blind.scrub_tokens( ARM_LABELS ), BODY_CHARS, JSCPD, model_id=selected_model() )


def main( argv=None ):
    """
    Freeze the live configuration once and print its sha.

    Requires:
        - argv is a list of arguments, or None for the command line; --path names the file to write and is required, because a model with no frozen file has no path to default to

    Ensures:
        - writes the selected model's configuration through config.freeze and prints the path and the config sha
        - returns 0

    Raises:
        - DuplicateCheckError CONFIG_ALREADY_FROZEN if a file exists at the path
    """
    parser = argparse.ArgumentParser( description="Freeze the duplicate check configuration once." )
    parser.add_argument( "--path", required=True )
    args   = parser.parse_args( argv )
    sha    = config.freeze( live_config(), args.path )
    print( f"frozen {args.path} config_sha={sha}" )
    return 0


if __name__ == "__main__": raise SystemExit( main() )  # pragma: no cover - command-line entry point
