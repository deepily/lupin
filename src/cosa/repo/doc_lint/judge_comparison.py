"""
Judge comparison: per-judge, per-pair-type figures from a finished ledger.

The harness writes one aggregate report per run. This module reads the finished ledger and the labelled
set's keys and makes no model call. It adds what the aggregate leaves out: the split by pair type, the
call counts, and tables and Mermaid charts computed from the same JSON. A missing ledger row stops the run.
"""

import argparse
import asyncio
import hashlib
import json
import math
import sys

from . import harness_report, harness_runner, jev_judge, jev_transport, labelled_pairs

KINDS         = ( "delete", "weaken", "relocate", "paraphrase" )
GROUPS        = KINDS + ( "injection (removed claim)", "injection (kept claim)" )
KEY_FIELDS    = ( "kind", "seeded_positive", "injection" )


class LedgerIncomplete( RuntimeError ):
    """A model or Jev call was needed, so the ledger lacks a row this judge would read."""


def caused_by_missing_row( error ):
    """Say whether a LedgerIncomplete sits anywhere in an error's chain."""
    while error is not None:
        if isinstance( error, LedgerIncomplete ): return True
        error = error.__cause__ or error.__context__
    return False


async def refuse_model_call( prompt, options ):
    """Stand in for the model: any call means the ledger is missing a row."""
    raise LedgerIncomplete( "a model call was needed: the ledger is incomplete for this judge" )
    yield  # pragma: no cover - makes this an async generator, as the SDK call is


def refuse_post( url, headers, body, timeout ):
    """Stand in for the Jev request: any call means the ledger is missing a row."""
    raise LedgerIncomplete( "a Jev call was needed: the ledger is incomplete for this judge" )


def key_rows( keys_path ):
    """
    Read the keys file into { id: row } with the three fields this module groups by.

    Requires:
        - keys_path names a JSON Lines file with one object per pair

    Ensures:
        - returns { id: { kind, seeded_positive, injection } }
        - kind is one of the four pair kinds; seeded_positive and injection are bools

    Raises:
        - ValueError when a row lacks a field, names an unknown kind, or holds a non-bool flag
    """
    out = {}
    for row in labelled_pairs._read_jsonl( keys_path ):
        for field in KEY_FIELDS:
            if field not in row: raise ValueError( f"key {row.get( 'id' )}: field {field!r} is missing" )
        if row[ "kind" ] not in KINDS: raise ValueError( f"key {row[ 'id' ]}: unknown kind {row[ 'kind' ]!r}" )
        if not isinstance( row[ "seeded_positive" ], bool ) or not isinstance( row[ "injection" ], bool ):
            raise ValueError( f"key {row[ 'id' ]}: seeded_positive and injection must be true or false" )
        out[ row[ "id" ] ] = { f: row[ f ] for f in KEY_FIELDS }
    return out


def groups_of( key ):
    """
    Name the table rows a pair belongs to.

    Requires:
        - key is a key_rows value

    Ensures:
        - returns its kind, plus one injection row when the injection flag is set: removed claim for a seeded
          positive, kept claim otherwise, since the expected verdict follows seeded_positive
    """
    names = [ key[ "kind" ] ]
    if key[ "injection" ]: names.append( "injection (removed claim)" if key[ "seeded_positive" ] else "injection (kept claim)" )
    return names


def wrong_on( result, slot ):
    """
    Say whether one extractor list judged a pair wrongly.

    Requires:
        - result is a run_pair result

    Ensures:
        - a seeded pair is wrong when the removal was not caught (a false pass)
        - an unseeded pair is wrong when any claim was flagged as dropped (a false alarm)
    """
    claim_list = result[ "lists" ][ slot ]
    if result[ "seed_span" ] is not None: return not harness_report.caught( claim_list, tuple( result[ "seed_span" ] ) )
    return harness_report.flagged( claim_list )


def group_rows( results, keys, slots ):
    """
    Count the wrong verdicts per pair group, on the worse of the extractor lists.

    Requires:
        - results come from run_all; keys is key_rows output covering every result id; slots is the list count

    Ensures:
        - returns one row per pair group that has pairs: group, expected (flagged or not flagged), n,
          wrong, per_list (the wrong count on each list), worst_list, rate, and bound
        - bound is the one-sided 95% upper bound for a group of removed claims, and the upper end of the
          two-sided 95% interval for a group of kept claims
        - a group is a false-pass group when its pairs are seeded, else a false-alarm group
        - an injection pair is counted in its kind's row and in its injection row

    Raises:
        - ValueError when a result has no key
    """
    members = { name: [] for name in GROUPS }
    for r in results:
        if r[ "id" ] not in keys: raise ValueError( f"pair {r[ 'id' ]} has no key" )
        for name in groups_of( keys[ r[ "id" ] ] ): members[ name ].append( r )
    rows = []
    for name in GROUPS:
        group = members[ name ]
        if not group: continue
        seeded   = group[ 0 ][ "seed_span" ] is not None
        per_list = [ sum( 1 for r in group if wrong_on( r, s ) ) for s in range( slots ) ]
        worst    = max( range( slots ), key=lambda s: ( per_list[ s ], -s ) )
        wrong    = per_list[ worst ]
        bound    = harness_report.upper_bound( wrong, len( group ) ) if seeded else harness_report.interval( wrong, len( group ) )[ 1 ]
        rows.append( { "group": name, "expected": "flagged" if seeded else "not flagged", "n": len( group ), "wrong": wrong,
                       "per_list": per_list, "worst_list": worst, "rate": wrong / len( group ), "bound": bound } )
    return rows


def call_counts( ledger, models ):
    """
    Count the finished model calls in a ledger.

    Requires:
        - ledger is a harness_runner.Ledger; models maps a judge name to the model field its judge keys carry

    Ensures:
        - returns { "extract": n, "judge": { name: n } }, read from the stage and model fields of each key
        - a Claude judge key carries "<judge>+<escalation>" and a Jev key its key_id, so a judge is counted
          when its field starts with the model string given
    """
    out = { "extract": 0, "judge": { name: 0 for name in models } }
    for key in ledger.entries:
        stage, _, _, _, model = key.split( "|" )[ : 5 ]
        if stage == "extract": out[ "extract" ] += 1
        for name, field in models.items():
            if stage == "judge" and model.startswith( field ): out[ "judge" ][ name ] += 1
    return out


def rebuild( pairs, config, ledger, backend=None ):
    """
    Rebuild one judge's results from a finished ledger, with no model call.

    Requires:
        - pairs are harness pairs; ledger holds every call config would make

    Ensures:
        - returns ( results, report ), the report being harness_report.build_report's
        - a missing ledger row raises LedgerIncomplete instead of calling a model, however the transport wraps the refusal
        - any other error is raised as it is
    """
    try:
        results = asyncio.run( harness_runner.run_all( pairs, config, ledger, query_fn=refuse_model_call, judge_backend=backend ) )
    except Exception as e:
        if caused_by_missing_row( e ): raise LedgerIncomplete( "the ledger is incomplete for this judge: a call it would make has no finished row" ) from e
        raise
    report  = harness_report.build_report( results, config, judge_prompt_version=backend.prompt_version if backend else None, jev_run=backend is not None )
    return results, report


def build_comparison( split, pairs, keys, ledger, judges, elapsed=None ):
    """
    Build the comparison for one split: a figure set per judge, and the shared counts.

    Requires:
        - split is "dev" or "gate"; pairs, keys and ledger describe one finished run
        - judges is { name: ( HarnessConfig, backend or None ) }
        - elapsed is { name: seconds } or None

    Ensures:
        - returns { split, pairs, judges, calls }; each judge holds model, headline (the harness report's
          figures, worse list first), groups (group_rows), and escalations, unanswered and discarded counts
        - a judge whose ledger is incomplete is { "incomplete": reason } and never a partial figure set
        - calls is call_counts over the ledger; a judge's seconds are copied from elapsed when given, else None
    """
    out = { "split": split, "pairs": len( pairs ), "judges": {}, "calls": None }
    models = {}
    for name, ( config, backend ) in judges.items():
        models[ name ] = backend.key_id if backend else config.judge_model + "+" + config.escalation_model
        try:
            results, report = rebuild( pairs, config, ledger, backend )
        except LedgerIncomplete as e:
            out[ "judges" ][ name ] = { "incomplete": str( e ) }
            continue
        slots = config.extractor_lists
        out[ "judges" ][ name ] = {
            "model"       : config.judge_model,
            "headline"    : report,
            "groups"      : group_rows( results, keys, slots ),
            "seconds"     : None if elapsed is None else elapsed.get( name )
        }
    out[ "calls" ] = call_counts( ledger, models )
    return out


def pct( value ):
    """Format a share as a percent with one decimal, or "n/a" for None."""
    return "n/a" if value is None else f"{value * 100:.1f}%"


def axis_top( values ):
    """Return a chart axis top just above the largest value: 0.05 steps, at least 0.05."""
    return max( 0.05, math.ceil( max( values + [ 0.0 ] ) / 0.05 ) * 0.05 )


def worst_list( headline, field ):
    """Return the headline list entry with the highest value of field (misses or false_alarms)."""
    return max( headline[ "lists" ], key=lambda l: ( l[ field ], -l[ "slot" ] ) )


def render_markdown( comparison ):
    """
    Render one split's tables and Mermaid charts as markdown.

    Requires:
        - comparison is build_comparison output

    Ensures:
        - returns a str: the headline table, the by-group table, the calls table and four charts
        - every number in it is read from the comparison dict; a judge that is incomplete gets one line saying so
        - charts hold the rate and its bound as two series, since Mermaid draws no error bars
    """
    split, judges = comparison[ "split" ], comparison[ "judges" ]
    done          = { n: j for n, j in judges.items() if "incomplete" not in j }
    lines         = [ f"### {split} split ({comparison[ 'pairs' ]} pairs)", "" ]
    for n, j in judges.items():
        if "incomplete" in j: lines += [ f"**{n}: incomplete.** {j[ 'incomplete' ]}", "" ]
    lines += [ "| judge | seeded n | false passes | false-pass rate | 95% upper bound | unseeded n | false alarms | false-alarm rate | 95% upper end | agreement, all | agreement, seeded |",
               "|---|---|---|---|---|---|---|---|---|---|---|" ]
    passes, alarms = {}, {}
    for n, j in done.items():
        h  = j[ "headline" ]
        m  = worst_list( h, "misses" )
        a  = worst_list( h, "false_alarms" )
        fa = harness_report.interval( a[ "false_alarms" ], a[ "unseeded" ] )
        passes[ n ] = ( m[ "misses" ] / m[ "positives" ] if m[ "positives" ] else 0.0, m[ "upper_bound" ] or 0.0 )
        alarms[ n ] = ( a[ "false_alarm_rate" ] or 0.0, fa[ 1 ] if fa else 0.0 )
        lines.append( f"| {n} | {m[ 'positives' ]} | {m[ 'misses' ]} | {pct( passes[ n ][ 0 ] )} | {pct( m[ 'upper_bound' ] )} | {a[ 'unseeded' ]} | {a[ 'false_alarms' ]} | "
                      f"{pct( a[ 'false_alarm_rate' ] )} | {pct( fa[ 1 ] if fa else None )} | {pct( h[ 'agreement_all' ][ 'rate' ] )} | {pct( h[ 'agreement_seeded' ][ 'rate' ] )} |" )
    lines += [ "", "| judge | group | expected | n | wrong | rate | 95% bound | worst list |", "|---|---|---|---|---|---|---|---|" ]
    for n, j in done.items():
        for g in j[ "groups" ]:
            lines.append( f"| {n} | {g[ 'group' ]} | {g[ 'expected' ]} | {g[ 'n' ]} | {g[ 'wrong' ]} | {pct( g[ 'rate' ] )} | {pct( g[ 'bound' ] )} | {g[ 'worst_list' ]} |" )
    calls = comparison[ "calls" ]
    lines += [ "", f"Extractor calls (shared by every judge): {calls[ 'extract' ]}.", "",
               "| judge | judge calls | escalations | discarded claims | no Jev answer | seconds |", "|---|---|---|---|---|---|" ]
    for n, j in done.items():
        h = j[ "headline" ]
        lines.append( f"| {n} | {calls[ 'judge' ][ n ]} | {h[ 'escalations' ]} | {h[ 'discarded_claims' ]} | {h[ 'judge_unanswered' ] if h[ 'judge_unanswered' ] is not None else 'n/a'} | {j[ 'seconds' ] if j[ 'seconds' ] is not None else 'n/a'} |" )
    names = list( done )
    if names:
        lines += [ "" ] + _chart( f"False-pass rate and 95% upper bound, {split} split", names, [ passes[ n ][ 0 ] for n in names ], [ passes[ n ][ 1 ] for n in names ], "bar", "line" )
        lines += [ "" ] + _chart( f"False-alarm rate and 95% upper end, {split} split", names, [ alarms[ n ][ 0 ] for n in names ], [ alarms[ n ][ 1 ] for n in names ], "bar", "line" )
        for title, wanted in ( ( "False-pass rate by pair type", ( "delete", "weaken", "injection (removed claim)" ) ),
                               ( "False-alarm rate by pair type", ( "relocate", "paraphrase", "injection (kept claim)" ) ) ):
            present = [ w for w in wanted if any( g[ "group" ] == w for j in done.values() for g in j[ "groups" ] ) ]
            if not present: continue
            series  = { n: [ next( ( g[ "rate" ] for g in done[ n ][ "groups" ] if g[ "group" ] == w ), 0.0 ) for w in present ] for n in names }
            lines  += [ "" ] + _lines_chart( f"{title}, {split} split", present, series )
        lines += [ "" ] + _calls_chart( f"Judge calls, {split} split", names, [ calls[ "judge" ][ n ] for n in names ] )
    return "\n".join( lines ) + "\n"


def _chart( title, names, first, second, kind_a, kind_b ):
    """Return an xychart block with two series over the judges, on a shared axis."""
    top = axis_top( first + second )
    return [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( names )}]", f'    y-axis "share" 0 --> {top:.2f}',
             f"    {kind_a} [{', '.join( f'{v:.4f}' for v in first )}]", f"    {kind_b} [{', '.join( f'{v:.4f}' for v in second )}]", "```" ]


def _lines_chart( title, groups, series ):
    """Return an xychart block with one line per judge across the pair groups."""
    top = axis_top( [ v for vals in series.values() for v in vals ] )
    out = [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( g.replace( ' ', '_' ) for g in groups )}]", f'    y-axis "share" 0 --> {top:.2f}' ]
    out += [ f"    line [{', '.join( f'{v:.4f}' for v in vals )}]" for vals in series.values() ]
    out += [ "```", "Lines, in order: " + ", ".join( series ) + "." ]
    return out


def _calls_chart( title, names, counts ):
    """Return an xychart block with one bar per judge for its call count."""
    return [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( names )}]", f'    y-axis "calls" 0 --> {max( counts + [ 1 ] )}',
             f"    bar [{', '.join( str( c ) for c in counts )}]", "```" ]


def parse_args( argv ):
    """Parse the command line; every model id is required and none has a default."""
    parser = argparse.ArgumentParser( description="Rebuild per-judge, per-pair-type figures from a finished harness ledger." )
    parser.add_argument( "--pairs", required=True )
    parser.add_argument( "--keys", required=True )
    parser.add_argument( "--ledger", required=True, nargs="+", help="one or more ledger files, merged in the order given" )
    parser.add_argument( "--split", choices=( "dev", "gate" ), required=True )
    parser.add_argument( "--out-json", required=True )
    parser.add_argument( "--out-md", required=True )
    parser.add_argument( "--t-lo", type=float, required=True )
    parser.add_argument( "--t-hi", type=float, required=True )
    parser.add_argument( "--elapsed", help="JSON file { judge name: seconds }, written by whoever launched the run" )
    parser.add_argument( "--frozen-pairs-sha", help="gate only: sha256 of the pairs file registered before the gate run" )
    for name in ( "extractor", "escalation", "writer", "haiku", "sonnet", "jev" ):
        parser.add_argument( f"--{name}-model", required=True )
    return parser.parse_args( argv )


def main( argv ):
    """
    Rebuild the comparison from a finished ledger and write its JSON and markdown.

    Requires:
        - argv is the argument list without the program name

    Ensures:
        - returns 0 after writing both files, printing one line per judge
        - returns 2 when a model id is refused or a gate path is named without --split gate
        - returns 3 when --split gate has no --frozen-pairs-sha, or it is not the sha256 of the pairs file
        - a judge whose ledger lacks a row is written as incomplete, never as a partial figure set
        - makes no model call and writes only the two output files and a merged ledger copy in memory
    """
    args = parse_args( argv )
    gate = args.split == "gate"
    with open( args.pairs, "rb" ) as f: sha = hashlib.sha256( f.read() ).hexdigest()
    if gate and args.frozen_pairs_sha != sha:
        print( f"REFUSED: gate split needs --frozen-pairs-sha {sha}, got {args.frozen_pairs_sha}", file=sys.stderr )
        return 3
    try:
        pairs = labelled_pairs.load_pairs( args.pairs, args.keys, gate=gate )
        keys  = key_rows( args.keys )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    ledger = harness_runner.Ledger( args.ledger[ 0 ] )
    for path in args.ledger[ 1 : ]: ledger.entries.update( harness_runner.Ledger( path ).entries )
    ext, esc, wri = args.extractor_model, args.escalation_model, args.writer_model
    judges = {
        "haiku" : ( harness_runner.HarnessConfig( ext, args.haiku_model,  esc, wri, 2, 3 ), None ),
        "sonnet": ( harness_runner.HarnessConfig( ext, args.sonnet_model, esc, wri, 2, 3 ), None ),
        "jev"   : ( harness_runner.HarnessConfig( ext, args.jev_model,    esc, wri, 2, 1 ),
                    jev_judge.JevBackend( args.jev_model, args.t_lo, args.t_hi, esc, post_fn=refuse_post, environ={ jev_transport.KEY_VARIABLE: "unused" } ) ),
    }
    try:
        for config, _ in judges.values(): harness_runner.check_models( config )
    except ValueError as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 2
    elapsed = None
    if args.elapsed:
        with open( args.elapsed, encoding="utf-8" ) as f: elapsed = json.load( f )
    comparison = build_comparison( args.split, pairs, keys, ledger, judges, elapsed )
    comparison[ "pairs_sha" ] = sha
    with open( args.out_json, "w", encoding="utf-8" ) as f: json.dump( comparison, f, indent=1 )
    with open( args.out_md, "w", encoding="utf-8" ) as f: f.write( render_markdown( comparison ) )
    for n, j in comparison[ "judges" ].items(): print( f"{n}: {'incomplete' if 'incomplete' in j else 'ok'}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
