"""The decided values of the frozen configuration, and the command that freezes them."""
import argparse

import cosa.utils.util as cu
from cosa.repo.semdup import blind, config, judge

FROZEN_RELATIVE   = "/src/conf/semdup-frozen-2.json"
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


def frozen_path():
    """
    Return where the frozen configuration lives in the project being run.

    Ensures:
        - returns the project root joined to FROZEN_RELATIVE
    """
    return cu.get_project_root() + FROZEN_RELATIVE


def live_config():
    """
    Build the configuration this code would run with now.

    Ensures:
        - returns build_config over the decided values above, the judge's prompt, template and parser, and the scrub list of the tool tokens and ARM_LABELS
        - two calls return equal dicts, so verify_frozen can compare a run with the file
    """
    return config.build_config( BACKEND, TEMPERATURE, UNSCORABLE_POLICY, *judge.prompt_parts(), blind.scrub_tokens( ARM_LABELS ), BODY_CHARS, JSCPD )


def main( argv=None ):
    """
    Freeze the live configuration once and print its sha.

    Requires:
        - argv is None or a list of arguments; --path names the file, default frozen_path()

    Ensures:
        - writes the file through config.freeze and prints the path and the config sha
        - returns 0

    Raises:
        - SemdupError CONFIG_ALREADY_FROZEN if a file exists at the path
    """
    parser = argparse.ArgumentParser( description="Freeze the semdup configuration once." )
    parser.add_argument( "--path", default=None )
    args   = parser.parse_args( argv )
    path   = args.path if args.path is not None else frozen_path()
    sha    = config.freeze( live_config(), path )
    print( f"frozen {path} config_sha={sha}" )
    return 0


if __name__ == "__main__": raise SystemExit( main() )  # pragma: no cover - command-line entry point
