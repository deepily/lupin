"""Score one run directory and write its report; a run that cannot be scored is reported."""
import argparse
import json
import pathlib

from cosa.repo.semdup import cluster, extract, pipeline
from cosa.repo.semdup import config as cfg_mod
from cosa.repo.semdup import errors as err

RESULT_FILE   = "result.json"
REPORT_FILE   = "semdup-report.json"
EXIT_SCORED   = 0
EXIT_UNSCORED = 2


def aggregate_runs( reports, cfg, policies ):
    """
    Hand the run reports to the named unscorable-run policy, refusing when none is named.

    Requires:
        - reports is a list of run reports, each with a "run" id; an unscorable one has status "unscorable"
        - cfg is a configuration dict
        - policies maps a policy name to a callable that takes the list of reports; the stop-rule phase supplies it

    Ensures:
        - never drops, zero-fills or excludes a run
        - returns { "reports", "unscorable", "policy", "applied" }: the reports as given, the run ids of the unscorable ones in
          input order, the policy name from cfg, and what the policy returned for the reports (None when none was unscorable)
        - a policy is called only when a report is unscorable, and gets the reports as given

    Raises:
        - SemdupError POLICY_UNDECIDED if any report is unscorable while unscorable_policy is empty (parking item P5)
        - SemdupError POLICY_UNKNOWN if any report is unscorable and the named policy is not in policies
    """
    unscorable = [ report[ "run" ] for report in reports if report.get( "status" ) == "unscorable" ]
    name       = cfg[ "unscorable_policy" ]
    applied    = None
    if unscorable:
        if cfg_mod.is_empty( name ):
            raise err.SemdupError( err.POLICY_UNDECIDED, f"runs {', '.join( unscorable )} are unscorable and no policy is named (parking item P5)" )
        if name not in policies:
            raise err.SemdupError( err.POLICY_UNKNOWN, f"policy {name!r} is not one of {sorted( policies )}" )
        applied = policies[ name ]( reports )
    return { "reports": list( reports ), "unscorable": unscorable, "policy": name, "applied": applied }


def _unscorable( report, error, evidence ):
    """Return the report marked unscorable with the error as cause and the evidence."""
    return { **report, "status": "unscorable", "cause": error.code, "evidence": { "detail": error.detail, **evidence } }


def score_run( run, wiring ):
    """
    Score one run's client and return its report.

    Requires:
        - run is the harness result { run, passing_tests, pass_rate } with an optional client_builds
        - wiring holds frozen_path, live (the live configuration), root, files (absolute paths of the run's script and Python files),
          server_defs (the server definitions), client (the embedding client), cache_dir, scrub, structural_pairs (a callable taking all
          definitions and returning clone pairs), backend, ledger, slot and parallel

    Ensures:
        - the frozen configuration is checked first
        - returns a report with status "scored" and a score_per_100, or status "unscorable" with a cause and its evidence and no score
        - the causes are EXTRACT_INCOMPLETE (with the files), NO_PASSING_TESTS (the raw surplus is still in the report), BLINDNESS_BREACH
          and RUN_INCOMPLETE (with the unjudged definitions)
        - definitions under min_nodes are not judged and are counted as below_min
        - client_builds is copied into the report when the result has it
        - skipped_python lists the Python files that did not parse; they never make the run unscorable

    Raises:
        - SemdupError CONFIG_DRIFT if the live configuration differs from the frozen one
    """
    cfg        = cfg_mod.verify_frozen( wiring[ "frozen_path" ], wiring[ "live" ] )
    extraction = extract.extract_tree( wiring[ "root" ], wiring[ "files" ], "new" )
    report     = { "config_sha": cfg[ "config_sha" ], "run": run[ "run" ], "passing_tests": run[ "passing_tests" ], "pass_rate": run[ "pass_rate" ],
                   "server": wiring[ "backend" ].server_label, "skipped_python": extraction[ "skipped_python" ] }
    if "client_builds" in run: report[ "client_builds" ] = run[ "client_builds" ]
    try:
        extract.completeness( extraction )
    except err.SemdupError as e:
        unclosed = [ a[ "file" ] for a in extraction[ "script_accounts" ] if a[ "reported" ] + a[ "anonymous_walked" ] != a[ "function_like_total" ] ]
        return _unscorable( report, e, { "files": extraction[ "skipped_script" ] + unclosed } )
    new_defs    = extraction[ "definitions" ]
    judged      = [ d for d in new_defs if d[ "nodes" ] >= cfg[ "min_nodes" ] ]
    all_defs    = new_defs + wiring[ "server_defs" ]
    report      = { **report, "definitions": { "new": len( new_defs ), "server": len( wiring[ "server_defs" ] ), "judged": len( judged ) },
                    "below_min": len( new_defs ) - len( judged ) }
    try:
        outcome = pipeline.judge_all( judged, all_defs, cfg, wiring, wiring[ "slot" ] )
    except err.SemdupError as e:
        if e.code != err.BLINDNESS_BREACH: raise
        return _unscorable( report, e, {} )
    report[ "unjudged" ] = outcome[ "unjudged" ]
    if outcome[ "unjudged" ]:
        return _unscorable( report, err.SemdupError( err.RUN_INCOMPLETE, f"{len( outcome[ 'unjudged' ] )} definitions are unjudged" ), {} )
    groups            = cluster.clusters( [ d[ "id" ] for d in all_defs ], cluster.join_pairs( outcome[ "verdicts" ] ) )
    report[ "clusters" ] = cluster.sizes( groups )
    report[ "surplus" ]  = cluster.surplus( groups, { d[ "id" ]: d[ "origin" ] for d in all_defs } )
    try:
        report[ "score_per_100" ] = cluster.score( report[ "surplus" ], run[ "passing_tests" ] )
    except err.SemdupError as e:
        return _unscorable( report, e, {} )
    return { **report, "status": "scored" }


def main( argv, wiring ):
    """
    Score the run directory named on the command line and write its report there.

    Requires:
        - argv holds --run-dir, a folder with result.json from the harness
        - wiring is a callable taking ( run directory, result ) and returning the wiring dict score_run takes; the run harness supplies it

    Ensures:
        - writes <run dir>/semdup-report.json once, with sorted keys
        - returns 0 for a scored run and 2 for an unscorable one whose report is written
        - a missing --run-dir ends the process with argparse's own exit 2, before any report exists

    Raises:
        - FileExistsError if the run directory already holds a report
        - SemdupError CONFIG_DRIFT, which writes no report because the run is not the one that was frozen
    """
    parser = argparse.ArgumentParser( description="Score one semantic-duplicate run directory." )
    parser.add_argument( "--run-dir", required=True )
    args    = parser.parse_args( argv )
    run_dir = pathlib.Path( args.run_dir )
    result  = json.loads( ( run_dir / RESULT_FILE ).read_text( encoding="utf-8" ) )
    report  = score_run( result, wiring( run_dir, result ) )
    with open( run_dir / REPORT_FILE, "x", encoding="utf-8" ) as f: json.dump( report, f, indent=2, sort_keys=True )
    print( f"{report[ 'run' ]}: {report[ 'status' ]}" )
    return EXIT_SCORED if report[ "status" ] == "scored" else EXIT_UNSCORED
