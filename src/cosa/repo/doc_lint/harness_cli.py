"""
Command line for the judge harness: run before/after pairs and write the exit-gate report.

    python -m cosa.repo.doc_lint.harness_cli --pairs pairs.json --ledger run.jsonl --out report.json \
        --extractor-model ... --judge-model ... --escalation-model ... --writer-model ...

Every model id is required. Rerunning the same command after a kill resumes from the ledger.
"""

import argparse
import asyncio
import hashlib
import json
import sys

from . import claim_extractor, claim_judge, harness_report, harness_runner, jev_judge, jev_transport, labelled_pairs


def parse_args( argv ):
    """Parse the command line; every model id is required and none has a default."""
    parser = argparse.ArgumentParser( description="Run the claim-preservation judge harness." )
    parser.add_argument( "--pairs", required=True, help="JSON list of { id, old, new, design?, seed_span? }, or a labelled-set JSON Lines file when --keys is given" )
    parser.add_argument( "--keys", help="labelled-set keys file: --pairs is then read as the labelled set's pairs file (dev split only)" )
    parser.add_argument( "--ledger", required=True, help="append-only ledger file; reuse it to resume" )
    parser.add_argument( "--out", required=True, help="where to write the report JSON" )
    for name in ( "extractor", "judge", "escalation", "writer" ):
        parser.add_argument( f"--{name}-model", required=True )
    parser.add_argument( "--judge-backend", choices=( "claude", "jev" ), default="claude", help="jev: --judge-model is the pinned Jev id" )
    parser.add_argument( "--t-lo", type=float, help="jev only: noul at or below this is absent" )
    parser.add_argument( "--t-hi", type=float, help="jev only: noul at or above this is present" )
    parser.add_argument( "--allow-design-text", action="store_true", help="labelled set only; real Design: documents need Rick's approval" )
    parser.add_argument( "--extractor-lists", type=int, default=2 )
    parser.add_argument( "--judge-runs", type=int, default=3 )
    parser.add_argument( "--gate", action="store_true", help="a gate run: refuse unless --frozen-versions matches" )
    parser.add_argument( "--frozen-pairs-sha", help="sha256 of the pairs file registered before the gate run" )
    parser.add_argument( "--frozen-versions", help="extractor and judge prompt versions registered before the gate run, comma separated" )
    return parser.parse_args( argv )


def main( argv, query_fn=None ):
    """
    Run the harness and write the report.

    Requires:
        - argv is the argument list without the program name
        - query_fn, when given, stands in for the SDK in tests

    Ensures:
        - returns 0 after writing the report, printing one summary line
        - returns 2 and prints the reason when the model configuration is refused, or when the Jev
          back end refuses to run: no key, a refused request, or a design document without --allow-design-text
        - returns 3 and runs nothing when --gate is set and --frozen-versions is missing or is not
          the extractor and judge versions in this code, so a gate run cannot use prompts
          that changed after they were registered
        - returns 3 and runs nothing when --gate is set and --frozen-pairs-sha is missing or is
          not the sha256 of the pairs file, so the gate file cannot change after registration
        - the report carries the sha256 of the pairs file
    """
    args   = parse_args( argv )
    config = harness_runner.HarnessConfig( args.extractor_model, args.judge_model, args.escalation_model,
                                           args.writer_model, args.extractor_lists, args.judge_runs )
    try:
        harness_runner.check_models( config )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    backend = None
    judge_version = claim_judge.PROMPT_VERSION
    if args.judge_backend == "jev":
        try:
            backend = jev_judge.JevBackend( args.judge_model, args.t_lo, args.t_hi, args.escalation_model, allow_design_text=args.allow_design_text )
        except ValueError as e:
            print( f"REFUSED: {e}", file=sys.stderr )
            return 2
        judge_version = backend.prompt_version
    current = f"{claim_extractor.PROMPT_VERSION},{judge_version}"
    if args.gate and args.frozen_versions != current:
        print( f"REFUSED: gate run needs --frozen-versions {current}, got {args.frozen_versions}", file=sys.stderr )
        return 3
    with open( args.pairs, "rb" ) as f: raw = f.read()
    pairs_sha = hashlib.sha256( raw ).hexdigest()
    if args.gate and args.frozen_pairs_sha != pairs_sha:
        print( f"REFUSED: gate run needs --frozen-pairs-sha {pairs_sha}, got {args.frozen_pairs_sha}", file=sys.stderr )
        return 3
    try:
        pairs = json.loads( raw ) if args.keys is None else labelled_pairs.load_pairs( args.pairs, args.keys )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    try:
        results = asyncio.run( harness_runner.run_all( pairs, config, harness_runner.Ledger( args.ledger ), query_fn=query_fn, judge_backend=backend ) )
    except jev_transport.JevConfigError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    report  = harness_report.build_report( results, config, judge_prompt_version=judge_version, jev_run=backend is not None )
    report[ "pairs_sha" ] = pairs_sha
    with open( args.out, "w", encoding="utf-8" ) as f: json.dump( report, f, indent=2 )
    print( f"report written to {args.out}: default_gate_pass={report[ 'default_gate_pass' ]}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
