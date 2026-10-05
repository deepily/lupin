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
import os
import sys

from cosa.orchestration.agy import runtime as agy_runtime

from . import claim_extractor, claim_judge, harness_report, harness_runner, jev_judge, jev_transport, labelled_pairs, model_transport


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
    parser.add_argument( "--claude-cli-path", help="run this Claude Code binary instead of the SDK's bundled one (newer model ids can need a newer binary)" )
    parser.add_argument( "--transport", choices=model_transport.TRANSPORTS, default="claude", help="agy: every model call goes to a Gemini model through the agy command-line agent, and each model id is an agy model identifier" )
    parser.add_argument( "--agy-bin", help="agy only: the agy binary to run, a command name or a path (default: agy on the search path)" )
    parser.add_argument( "--raw-failures", help="append every unreadable extractor reply, with its pair and list, to this JSON Lines file (keep it out of the repo)" )
    parser.add_argument( "--call-ledger", help="file that counts every call to a capped model across runs and restarts; keep it outside the repo" )
    parser.add_argument( "--model-cap", action="append", default=[], metavar="MODEL=N", help="refuse the call after N calls to MODEL, counted in --call-ledger; repeat for more models" )
    parser.add_argument( "--extractor-lists", type=int, default=2 )
    parser.add_argument( "--judge-runs", type=int, help="judge passes over each claim list: 3 for the Claude judge, 1 for Jev, whose answers are deterministic" )
    parser.add_argument( "--judge-thinking", choices=model_transport.THINKING_SETTINGS, default="default", help="off: the first-pass Claude judge call runs with thinking disabled; extractor and escalation calls are unchanged. A different setting is a different ledger key, never a reused verdict" )
    parser.add_argument( "--parallel", type=int, default=1, help="pairs in flight at once (1 = one at a time)" )
    parser.add_argument( "--gate", action="store_true", help="the one door onto the gate split: refuse unless versions, thresholds and the pairs sha are frozen; run by a seat other than the implementer" )
    parser.add_argument( "--frozen-pairs-sha", help="sha256 of the pairs file registered before the gate run" )
    parser.add_argument( "--frozen-thresholds", help="jev gate run: t_lo,t_hi registered before the gate run, as written on the command line" )
    parser.add_argument( "--frozen-versions", help="extractor and judge prompt versions registered before the gate run, comma separated" )
    return parser.parse_args( argv )


def raw_failure_sink( path ):
    """
    Return the on_unreadable callback that keeps unreadable extractor replies in a file, or None without a path.

    Requires:
        - path is None or a writable file path outside the repo

    Ensures:
        - each call appends one JSON line { id, slot, attempt, error, raw } and flushes it to disk
    """
    if path is None: return None
    def sink( pair_id, slot, attempt, raw, error ):
        with open( path, "a", encoding="utf-8" ) as f:
            f.write( json.dumps( { "id": pair_id, "slot": slot, "attempt": attempt, "error": error, "raw": raw } ) + "\n" )
            f.flush()
            os.fsync( f.fileno() )
    return sink


def main( argv, query_fn=None, agy_runner=None ):
    """
    Run the harness and write the report.

    Requires:
        - argv is the argument list without the program name
        - query_fn, when given, stands in for the SDK in tests
        - agy_runner, when given, stands in for subprocess.run on the agy path in tests

    Ensures:
        - returns 0 after writing the report, printing one summary line
        - returns 2 and prints the reason when the model configuration is refused, or when the Jev
          back end refuses to run: no key, a refused request, or a design document without --allow-design-text
        - returns 3 and runs nothing when --gate is set and --frozen-versions is missing or is not
          the extractor and judge versions in this code, so a gate run cannot use prompts
          that changed after they were registered
        - returns 4 and runs nothing when a seeded pair's span is not itself quotable (locate_quote
          refuses it): a removal the extractor cannot express would be an unmeasurable miss
        - returns 2 when --claude-cli-path is not an executable file; the report records the path used, or None for the SDK's own
        - returns 2 and opens nothing when a pairs or keys path names the gate split and --gate is not set
        - returns 3 and runs nothing when --gate is set with the Jev back end and --frozen-thresholds
          is missing or is not the --t-lo and --t-hi given
        - returns 2 when --t-lo or --t-hi is given with the Claude back end, where they would be ignored
        - returns 3 and runs nothing when --gate is set and --frozen-pairs-sha is missing or is
          not the sha256 of the pairs file, so the gate file cannot change after registration
        - the report carries the sha256 of the pairs file
        - returns 2 when --parallel is below 1, or --judge-thinking off is given with the Jev back end, where it would be ignored
        - the report carries call_timing (seconds and calls per stage) and the judge_thinking setting
        - --model-cap MODEL=N with --call-ledger caps that model's calls; the report and the last printed lines carry each capped model's count and cap
        - returns 2 when a cap is not MODEL=N with N an int of zero or more, or caps are given without a ledger
        - a call the cap refuses raises CallBudgetExceeded and ends the run; the ledger keeps the count for the next run
        - with --transport agy the ledger binding is the agy binary's path, size, modification time and version,
          and the report carries transport, agy_binding and agy_usage (tokens per model id)
        - returns 2 when --transport agy is given with --claude-cli-path or with --judge-thinking off, when
          --agy-bin is given without --transport agy, or when the agy binary is not usable
        - returns 2 when the agy binary changes during the run, whichever pair's failure run_all raised;
          finished calls stay in the ledger, which resumes only under the binary it was written with,
          and the refusal says to rerun with a new --ledger
        - with --transport agy the report's call_profile and call_residual_context describe the agy call,
          not the Claude isolation profile
        - the transport is set back to Claude before returning, whatever the outcome
    """
    args   = parse_args( argv )
    runs   = args.judge_runs if args.judge_runs is not None else ( 1 if args.judge_backend == "jev" else 3 )
    config = harness_runner.HarnessConfig( args.extractor_model, args.judge_model, args.escalation_model,
                                           args.writer_model, args.extractor_lists, runs, args.judge_thinking )
    if args.parallel < 1:
        print( "REFUSED: --parallel must be 1 or more", file=sys.stderr )
        return 2
    if args.judge_backend == "jev" and args.judge_thinking != "default":
        print( "REFUSED: --judge-thinking only applies to --judge-backend claude", file=sys.stderr )
        return 2
    if args.judge_backend == "claude" and ( args.t_lo is not None or args.t_hi is not None ):
        print( "REFUSED: --t-lo and --t-hi only apply to --judge-backend jev", file=sys.stderr )
        return 2
    try:
        harness_runner.check_models( config )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    if args.transport == "agy" and args.claude_cli_path is not None:
        print( "REFUSED: --claude-cli-path only applies to --transport claude", file=sys.stderr )
        return 2
    if args.transport == "agy" and args.judge_thinking != "default":
        print( "REFUSED: --judge-thinking only applies to --transport claude; with agy the reasoning level is part of the model id", file=sys.stderr )
        return 2
    if args.transport != "agy" and args.agy_bin is not None:
        print( "REFUSED: --agy-bin only applies to --transport agy", file=sys.stderr )
        return 2
    try:
        model_transport.configure( args.claude_cli_path )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    try:
        return run_after_checks( args, config, query_fn, agy_runner )
    finally:
        model_transport.configure_claude()


def run_after_checks( args, config, query_fn, agy_runner ):
    """
    Do the work of main once the command line has passed its first checks.

    Requires:
        - args and config are main's parsed arguments and harness configuration
        - query_fn and agy_runner are main's test stand-ins, or None

    Ensures:
        - returns main's exit code; main sets the transport back to Claude afterwards
    """
    try:
        caps = { m: int( n ) for m, _, n in ( c.rpartition( "=" ) for c in args.model_cap ) }
        model_transport.set_budget( args.call_ledger, caps )
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
    if args.gate and args.judge_backend == "jev" and args.frozen_thresholds != f"{args.t_lo},{args.t_hi}":
        print( f"REFUSED: gate run needs --frozen-thresholds {args.t_lo},{args.t_hi}, got {args.frozen_thresholds}", file=sys.stderr )
        return 3
    if not args.gate:
        try:
            for path in ( args.pairs, args.keys ):
                if path is not None: labelled_pairs.refuse_gate_path( path )
        except ValueError as e:
            print( f"REFUSED: {e}", file=sys.stderr )
            return 2
    with open( args.pairs, "rb" ) as f: raw = f.read()
    pairs_sha = hashlib.sha256( raw ).hexdigest()
    if args.gate and args.frozen_pairs_sha != pairs_sha:
        print( f"REFUSED: gate run needs --frozen-pairs-sha {pairs_sha}, got {args.frozen_pairs_sha}", file=sys.stderr )
        return 3
    try:
        pairs = json.loads( raw ) if args.keys is None else labelled_pairs.load_pairs( args.pairs, args.keys, gate=args.gate )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    unquotable = harness_runner.unquotable_seeds( pairs )
    if unquotable:
        print( f"REFUSED: {len( unquotable )} seeded span(s) cannot be quoted under the extractor's floors, so the run could not catch them: {', '.join( unquotable )}", file=sys.stderr )
        return 4
    if args.transport == "agy":
        try:
            binding = model_transport.configure_agy( args.agy_bin if args.agy_bin is not None else agy_runtime.DEFAULT_AGY_BIN, runner=agy_runner )
        except ValueError as e:
            print( f"REFUSED: {e}", file=sys.stderr )
            return 2
    else:
        binding = f"claude_cli={args.claude_cli_path}|version={model_transport.cli_version( args.claude_cli_path )}"
    try:
        results = asyncio.run( harness_runner.run_all( pairs, config, harness_runner.Ledger( args.ledger, binding=binding ), query_fn=query_fn, judge_backend=backend,
                                                       on_unreadable=raw_failure_sink( args.raw_failures ), parallel=args.parallel ) )
    except ( jev_transport.JevConfigError, harness_runner.LedgerBindingError ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    except Exception:
        # With pairs in flight together, run_all raises the earliest pair's failure, which can be an
        # ordinary failed call while another pair saw the binary change. The change is the reason.
        if model_transport.AGY_STOP is None: raise
        print( f"REFUSED: {model_transport.AGY_STOP}; the ledger is bound to the binary the run began with, so rerun with a new --ledger", file=sys.stderr )
        return 2
    report  = harness_report.build_report( results, config, judge_prompt_version=judge_version, jev_run=backend is not None )
    report[ "pairs_sha" ] = pairs_sha
    report[ "transport" ] = args.transport
    if args.transport == "agy":
        report[ "agy_binding" ] = binding
        report[ "agy_usage" ]   = model_transport.agy_usage_summary()
    report[ "claude_cli" ]         = args.claude_cli_path
    report[ "claude_cli_version" ] = model_transport.cli_version( args.claude_cli_path )
    report[ "call_budget" ]        = model_transport.budget_summary()
    report[ "call_profile" ]       = model_transport.AGY_CALL_PROFILE if args.transport == "agy" else model_transport.CALL_PROFILE
    report[ "call_residual_context" ] = model_transport.AGY_RESIDUAL_CONTEXT if args.transport == "agy" else model_transport.RESIDUAL_CONTEXT
    with open( args.out, "w", encoding="utf-8" ) as f: json.dump( report, f, indent=2 )
    print( f"report written to {args.out}: default_gate_pass={report[ 'default_gate_pass' ]}" )
    print( f"parse_failed_pairs={report[ 'parse_failed_pairs' ]} retry_calls={report[ 'retry_calls' ]}" )
    for stage, t in report[ "call_timing" ][ "stages" ].items(): print( f"call time {stage}: {t[ 'seconds' ]:.1f}s over {t[ 'calls' ]} calls" )
    for model, b in report[ "call_budget" ].items(): print( f"call budget {model}: {b[ 'used' ]} of {b[ 'cap' ]} calls used" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
