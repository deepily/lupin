#!/usr/bin/env python
"""
Vertex request-response logging — the runner (design §4 / cascade §C).

The executable form of the harness in `cosa.utils.vertex_logging`.

THE DIVISION OF LABOUR, WHICH IS THE POINT OF THIS FILE
------------------------------------------------------
Per the cascade's standing orders, **every prediction call and every GCP write belongs to Mr.
Radio, on Rick's explicit word.** So this script does NOT fire them. It owns the part that must
be RIGHT — the verdict — and it hands the part that costs MONEY to the seat authorized to spend.

    --plan    (DEFAULT)  print the live-call manifest. Fires nothing. Free.
    --emit               mint sentinels + print the EXACT L0/L1/L2 commands for Mr. Radio to run.
    --verify             read BigQuery ONLY, apply the canary law, render a verdict.

`--verify` is read-only: no predictions, no writes, no spend. It is where the discipline lives —
it will return INADMISSIBLE (exit 1) rather than let anyone read an unproven silence as a result.

FIRE ORDER IS LOAD-BEARING: L0 (subject) BEFORE L2 (canary). ORDERING IS EVIDENCE — if the LATER
call lands and the EARLIER one does not, "it was just slow" is a materially weaker explanation.
`ProbePlan` REFUSES to be built the other way round.
"""

import argparse
import json
import os
import subprocess
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.utils.vertex_logging import (
    DEFAULT_LOG_DATASET,
    VERDICT_INADMISSIBLE,
    LoggingReadout,
    ProbePlan,
    VertexLoggingError,
    describe_live_calls,
    mint_sentinel,
    readout_positive_control_sql,
    run_probe,
)

# The probe prompt carries the sentinel and asks for a one-token answer, so the spend is a rounding
# error. It contains NO user data — the sentinel is a random hex string by construction.
PROBE_PROMPT = "Reply with exactly this token and nothing else: {sentinel}"


def make_bq_query_fn( runner=subprocess.run, debug=False ):
    """
    Build a BigQuery query function backed by the `bq` CLI.

    Requires:
        - runner has the subprocess.run signature, returning .returncode / .stdout / .stderr

    Ensures:
        - returns query_fn( sql, params ) -> list of dict rows
        - the sentinel travels as a BOUND parameter, never interpolated into SQL

    Raises:
        - VertexLoggingError when bq exits non-zero — A FAILED READ IS NOT AN EMPTY RESULT, and
          reporting one as "no rows" would be the exact bug this harness exists to prevent
    """
    def query_fn( sql, params ):
        command = [ "bq", "query", "--format=json", "--use_legacy_sql=false", "--quiet" ]
        for name, value in params.items():
            command.append( f"--parameter={name}:STRING:{value}" )
        command.append( sql )

        if debug: print( f"[bq] {sql.splitlines()[ 0 ][ :90 ]}…" )
        completed = runner( command, capture_output=True, text=True )
        if completed.returncode != 0:
            raise VertexLoggingError(
                f"bq query FAILED (exit {completed.returncode}): {completed.stderr.strip()}. A failed READ "
                f"is not an empty result. Reporting it as 'no rows' would be the exact bug this harness "
                f"exists to prevent."
            )
        return json.loads( completed.stdout ) if completed.stdout.strip() else []

    return query_fn


def print_plan( project_id, vertex_location, bq_location ):
    """
    Print the live-call manifest and fire NOTHING.

    Ensures:
        - returns 0
    """
    print( "\nLIVE-CALL MANIFEST — nothing below has been fired.\n" )
    for call in describe_live_calls( project_id, vertex_location, bq_location ):
        print( f"  [{call[ 'id' ]}]" )
        print( f"      call   : {call[ 'call' ]}" )
        print( f"      write  : {call[ 'write' ]}" )
        print( f"      spend  : {call[ 'spend' ]}" )
        print( f"      proves : {call[ 'proves' ]}" )
        if "if_yes" in call: print( f"      IF YES : {call[ 'if_yes' ]}" )
        if "if_no"  in call: print( f"      IF NO  : {call[ 'if_no' ]}" )
        # The mechanism is printed SEPARATELY and immediately under the conclusion, so a reader cannot
        # take the conclusion home without the limit that governs it. A confession is not a correction.
        if "if_no_mechanism" in call: print( f"      MECHANISM : {call[ 'if_no_mechanism' ]}" )
        print()
    print( "AUTHORITY: the prediction calls and the BigQuery write are Mr. Radio's, on Rick's explicit word." )
    print( "This script will not fire them. Run --emit to get the exact commands.\n" )
    return 0


def print_emit( project_id, vertex_location, dataset ):
    """
    Mint the sentinels and print the EXACT commands for the authorized seat to run.

    The sentinels are minted HERE so that the two halves of the probe cannot drift apart, and so
    that nobody hand-types a sentinel that turns out to be ambient.

    Ensures:
        - returns 0
        - prints L0 before L2, because the SUBJECT must be fired before the CANARY
    """
    subject = mint_sentinel()     # L0 — gpt-oss-120b-maas. FIRED FIRST.
    canary  = mint_sentinel()     # L2 — claude-opus-4-8 @ global. Fired second.
    control = mint_sentinel()     # L1 — the readout positive control.

    # The two publishers are reached by DIFFERENT surfaces, and conflating them would emit a runbook
    # that 404s. Anthropic answers on :rawPredict. The Model Garden MaaS models answer on the
    # OpenAI-compatible endpoint — which is ALSO the region-blind one (bug 13c3c480).
    raw_predict = ( f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/"
                    f"{vertex_location}/publishers/{{publisher}}/models/{{model}}:rawPredict" )
    maas_openai = ( f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/"
                    f"{vertex_location}/endpoints/openapi/chat/completions" )

    write_sql, verify_sql = readout_positive_control_sql( project_id, dataset, control )

    print( "\n=== L1 — READOUT POSITIVE CONTROL (BigQuery only; no model; ~$0) ===" )
    print( "Proves the READOUT is awake, so a later null means 'the write pipeline produced nothing'" )
    print( "rather than 'we cannot see anything'. RUN THIS BEFORE TRUSTING ANY NULL.\n" )
    print( f"  bq query --use_legacy_sql=false \"{write_sql.replace( chr( 10 ), ' ' )}\"" )
    print( f"  bq query --use_legacy_sql=false \"{verify_sql}\"      # expect n = 1\n" )

    print( "=== L0 — SUBJECT: gpt-oss-120b-maas. FIRE THIS FIRST. (~$0.001) ===" )
    print( "Answers the PRIVACY question (823be9cc): is gpt-oss chain-of-thought landing in BigQuery?\n" )
    print( f"  sentinel : {subject}" )
    print( f"  endpoint : {maas_openai}" )
    print( f"  body     : {json.dumps( { 'model' : 'openai/gpt-oss-120b-maas', 'messages' : [ { 'role' : 'user', 'content' : PROBE_PROMPT.format( sentinel=subject ) } ] } )}" )
    print( "  NOTE     : record the fire time. It MUST be <= L2's — ordering is evidence." )
    print( "  ⚠️ SCOPE  : this endpoint IGNORES its locations/ segment (bug 13c3c480 — byte-identical" )
    print( "             200s for global, us-central1, and the FICTIONAL narnia-1). So we CANNOT control" )
    print( "             which location serves it. Consequence, stated rather than buried: a NULL here" )
    print( "             answers the question that MATTERS — 'is CoT being persisted?' — but it does NOT" )
    print( "             isolate the MECHANISM (publisher-scope vs location-scope). Those are two worlds" )
    print( "             this one observation cannot separate. Report the privacy answer; leave the" )
    print( "             mechanism OPEN rather than inventing which of the two explained it.\n" )

    print( "=== L2 — CANARY: claude-opus-4-8 @ global. FIRE THIS SECOND. (~$0.01) ===" )
    print( "Proves AC-D7 (DATA ARRIVES), and is the canary that makes L0's silence admissible.\n" )
    print( f"  sentinel : {canary}" )
    print( f"  prompt   : {PROBE_PROMPT.format( sentinel=canary )}" )
    print( f"  endpoint : {raw_predict.format( publisher='anthropic', model='claude-opus-4-8' )}" )
    print( "  NOTE     : :rawPredict is the ONLY certified region oracle. The publisher-model metadata" )
    print( "             GET and the MaaS openapi path are BOTH region-blind — neither may certify.\n" )

    print( "=== THEN VERIFY (read-only, no spend) ===\n" )
    print( f"  python src/scripts/verify_vertex_logging.py --verify \\\n"
           f"      --canary-sentinel {canary} --canary-fired-at <epoch_seconds> \\\n"
           f"      --subject-sentinel {subject} --subject-fired-at <epoch_seconds>\n" )
    return 0


def run_verify( args, clock, sleeper, query_fn ):
    """
    Read BigQuery ONLY and render a verdict under the canary law. No predictions. No writes. No spend.

    Requires:
        - args carries the sentinels, the fire times, and the poll bounds
        - clock/sleeper/query_fn are injected (so this is testable without a network)

    Ensures:
        - prints the verdict and EVERY residual assumption attached to it
        - returns 0 for PROVEN or REFUTED, 1 for INADMISSIBLE

    Raises:
        - VertexLoggingError when the plan is malformed (e.g. subject fired AFTER the canary)
    """
    readout = LoggingReadout( args.project_id, dataset=args.dataset, query_fn=query_fn, debug=args.debug )
    plan    = ProbePlan(
        args.canary_sentinel, args.canary_fired_at,
        subject_sentinel = args.subject_sentinel,
        subject_fired_at = args.subject_fired_at,
        max_wait_s       = args.max_wait_s,
        poll_interval_s  = args.poll_interval_s,
    )

    result = run_probe( readout, plan, clock=clock, sleeper=sleeper, debug=args.debug )

    print( f"\nVERDICT: {result.verdict}" )
    print( f"  readout state  : {result.readout_state}" )
    print( f"  canary tables  : {result.canary_tables}" )
    print( f"  subject tables : {result.subject_tables}" )
    print( f"  polls          : {result.polls}   elapsed: {result.elapsed_s}s" )

    if result.subject_tables:
        print( "\n🔴 THE SUBJECT LANDED. The logging config COVERS the MaaS publisher." )
        print( "   Raw chain-of-thought (reasoning_content) is being persisted to BigQuery at 100% sampling." )
        print( "   HALT. Escalate to Rick. Do NOT dump the row." )

    for note in result.residual_assumptions:
        print( f"\n  ⚠️  {note}" )

    if result.verdict == VERDICT_INADMISSIBLE:
        print( "\nEXIT 1 — INADMISSIBLE is NOT a pass and NOT a fail. The instrument never proved it was awake.\n" )
        return 1
    print()
    return 0


def build_parser():
    """Ensures: returns the argument parser. --plan is the default, and it is free."""
    parser = argparse.ArgumentParser( description="Vertex request-response logging verification harness." )
    parser.add_argument( "--emit",             action="store_true", help="Mint sentinels + print the exact L0/L1/L2 commands." )
    parser.add_argument( "--verify",           action="store_true", help="Read BigQuery only and render a verdict." )
    parser.add_argument( "--project-id",       default=os.environ.get( "LUPIN_GCP_PROJECT_ID", "" ) )
    parser.add_argument( "--vertex-location",  default=os.environ.get( "LUPIN_VERTEX_REGION", "global" ) )
    parser.add_argument( "--bq-location",      default="US" )
    parser.add_argument( "--dataset",          default=DEFAULT_LOG_DATASET )
    parser.add_argument( "--canary-sentinel",  default=None )
    parser.add_argument( "--canary-fired-at",  type=float, default=None )
    parser.add_argument( "--subject-sentinel", default=None )
    parser.add_argument( "--subject-fired-at", type=float, default=None )
    parser.add_argument( "--max-wait-s",       type=int, default=1800 )
    parser.add_argument( "--poll-interval-s",  type=int, default=30 )
    parser.add_argument( "--debug",            action="store_true" )
    return parser


def main( argv=None, clock=None, sleeper=None, query_fn=None ):
    """
    Entry point. Defaults to --plan, which fires nothing.

    Ensures:
        - returns 0 on a clean plan/emit, or on a PROVEN/REFUTED verdict
        - returns 1 on INADMISSIBLE — fail loud; an unproven instrument is not a pass
        - returns 2 on a usage error or a guard refusal
    """
    import time

    args = build_parser().parse_args( argv )

    if not args.project_id:
        print( "ERROR: --project-id (or LUPIN_GCP_PROJECT_ID) is required. Never hardcode it.", file=sys.stderr )
        return 2

    try:
        if args.emit:
            return print_emit( args.project_id, args.vertex_location, args.dataset )

        if args.verify:
            if not args.canary_sentinel or args.canary_fired_at is None:
                print( "ERROR: --verify needs --canary-sentinel and --canary-fired-at. Without a canary there "
                       "is no instrument, and without an instrument there is no verdict.", file=sys.stderr )
                return 2
            return run_verify(
                args,
                clock    = clock    if clock    is not None else time.monotonic,
                sleeper  = sleeper  if sleeper  is not None else time.sleep,
                query_fn = query_fn if query_fn is not None else make_bq_query_fn( debug=args.debug ),
            )

        return print_plan( args.project_id, args.vertex_location, args.bq_location )

    except VertexLoggingError as error:
        print( f"REFUSED: {error}", file=sys.stderr )
        return 2


if __name__ == "__main__":
    sys.exit( main() )
