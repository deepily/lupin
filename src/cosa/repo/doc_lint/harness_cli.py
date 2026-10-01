"""
Command line for the judge harness: run a file of before/after pairs and write the exit-gate report.

    python -m cosa.repo.doc_lint.harness_cli --pairs pairs.json --ledger run.jsonl --out report.json \
        --extractor-model ... --judge-model ... --escalation-model ... --writer-model ...

Every model id is required. Rerunning the same command after a kill resumes from the ledger.
"""

import argparse
import asyncio
import json
import sys

from . import harness_report, harness_runner


def parse_args( argv ):
    """Parse the command line; every model id is required and none has a default."""
    parser = argparse.ArgumentParser( description="Run the claim-preservation judge harness." )
    parser.add_argument( "--pairs", required=True, help="JSON list of { id, old, new, design?, seed_span? }" )
    parser.add_argument( "--ledger", required=True, help="append-only ledger file; reuse it to resume" )
    parser.add_argument( "--out", required=True, help="where to write the report JSON" )
    for name in ( "extractor", "judge", "escalation", "writer" ):
        parser.add_argument( f"--{name}-model", required=True )
    parser.add_argument( "--extractor-lists", type=int, default=2 )
    parser.add_argument( "--judge-runs", type=int, default=3 )
    return parser.parse_args( argv )


def main( argv, query_fn=None ):
    """
    Run the harness and write the report.

    Requires:
        - argv is the argument list without the program name
        - query_fn, when given, stands in for the SDK in tests

    Ensures:
        - returns 0 after writing the report, printing one summary line
        - returns 2 and prints the reason when the model configuration is refused
    """
    args   = parse_args( argv )
    config = harness_runner.HarnessConfig( args.extractor_model, args.judge_model, args.escalation_model,
                                           args.writer_model, args.extractor_lists, args.judge_runs )
    try:
        harness_runner.check_models( config )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    with open( args.pairs, encoding="utf-8" ) as f: pairs = json.load( f )
    results = asyncio.run( harness_runner.run_all( pairs, config, harness_runner.Ledger( args.ledger ), query_fn=query_fn ) )
    report  = harness_report.build_report( results, config )
    with open( args.out, "w", encoding="utf-8" ) as f: json.dump( report, f, indent=2 )
    print( f"report written to {args.out}: default_gate_pass={report[ 'default_gate_pass' ]}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
