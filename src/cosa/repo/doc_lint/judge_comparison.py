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

from . import claim_judge, harness_report, harness_runner, jev_judge, jev_transport, labelled_pairs

KINDS         = ( "delete", "weaken", "relocate", "paraphrase" )
REMOVING_KINDS = ( "delete", "weaken" )
GROUPS        = KINDS + ( "injection (removed claim)", "injection (kept claim)" )
KEY_FIELDS    = ( "kind", "seeded_positive", "injection" )


class LedgerIncomplete( RuntimeError ):
    """A model or Jev call was needed, so the ledger lacks a row this judge would read."""


class ReportMismatch( ValueError ):
    """The harness report's unanswered count cannot be squared with the passes the ledger lacks."""


class MissingRowProbe:
    """
    Stands in for a judge back end over a finished ledger and counts the passes it lacks.

    Requires:
        - real is the back end the run used, with its key_id and prompt_version

    Ensures:
        - carries the real back end's key_id and prompt_version, so the runner looks up the same ledger keys
        - judge is called only for a pass with no ledger row; it records that pass's claim count and answers
          every claim uncertain with no noul, so nothing is invented and no call is made
        - complete is False, so the runner would never ledger what it returns
    """

    def __init__( self, real ):
        self.key_id         = real.key_id
        self.prompt_version = real.prompt_version
        self.missing        = []

    async def judge( self, claims, new_text, design_text, query_fn=None ):
        """Record one missing pass and return an unanswered Judgement per claim."""
        self.missing.append( len( claims ) )
        return [ claim_judge.Judgement( c, "uncertain", False, "no ledger row for this pass", None ) for c in claims ]

    def complete( self, judged ):
        """Never complete: a probe's answers are not kept."""
        return False


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
        - ValueError when the kind and seeded_positive disagree: delete and weaken remove a claim, relocate
          and paraphrase keep every claim, and a row that says otherwise would mix the two error types
    """
    out = {}
    for row in labelled_pairs._read_jsonl( keys_path ):
        for field in KEY_FIELDS:
            if field not in row: raise ValueError( f"key {row.get( 'id' )}: field {field!r} is missing" )
        if row[ "kind" ] not in KINDS: raise ValueError( f"key {row[ 'id' ]}: unknown kind {row[ 'kind' ]!r}" )
        if not isinstance( row[ "seeded_positive" ], bool ) or not isinstance( row[ "injection" ], bool ):
            raise ValueError( f"key {row[ 'id' ]}: seeded_positive and injection must be true or false" )
        if row[ "seeded_positive" ] != ( row[ "kind" ] in REMOVING_KINDS ):
            raise ValueError( f"key {row[ 'id' ]}: kind {row[ 'kind' ]!r} with seeded_positive {row[ 'seeded_positive' ]} cannot be grouped, because its error type is undefined" )
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
        - an unseeded pair whose judge was skipped (empty new text) is in neither wrong nor n: the row counts it in new_text_empty,
          and a row with no other pair has rate and bound None

    Raises:
        - ValueError when a result has no key, or when a group mixes seeded and unseeded pairs
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
        if any( ( r[ "seed_span" ] is not None ) != seeded for r in group ): raise ValueError( f"group {name!r} mixes pairs with and without a seeded removal" )
        empty    = [ r for r in group if r.get( "judge_skipped" ) and not seeded ]
        group    = [ r for r in group if r not in empty ]
        per_list = [ sum( 1 for r in group if wrong_on( r, s ) ) for s in range( slots ) ]
        worst    = max( range( slots ), key=lambda s: ( per_list[ s ], -s ) )
        wrong    = per_list[ worst ]
        if not group:
            rows.append( { "group": name, "expected": "not flagged", "n": 0, "wrong": 0, "per_list": per_list, "worst_list": worst,
                           "rate": None, "bound": None, "new_text_empty": len( empty ) } )
            continue
        bound    = harness_report.upper_bound( wrong, len( group ) ) if seeded else harness_report.interval( wrong, len( group ) )[ 1 ]
        rows.append( { "group": name, "expected": "flagged" if seeded else "not flagged", "n": len( group ), "wrong": wrong,
                       "per_list": per_list, "worst_list": worst, "rate": wrong / len( group ), "bound": bound,
                       "new_text_empty": len( empty ) } )
    return rows


def distinct_judged_calls( judged, config ):
    """
    Count the judge calls a ledger holds for the pairs that reached the judge.

    Ensures:
        - returns lists x runs per distinct judged text pair; a skipped pair has none
    """
    return judged * config[ "extractor_lists" ] * config[ "judge_runs" ]


def pair_hashes( pairs ):
    """
    Return the ( old hash, new-side hash ) every ledger key of these pairs carries.

    Requires:
        - pairs are harness pairs

    Ensures:
        - the hashes are read from harness_runner.ledger_key itself, so the two cannot disagree
    """
    return { tuple( harness_runner.ledger_key( "x", p, "", "", 0 ).split( "|" )[ 1 : 3 ] ) for p in pairs }


def call_counts( ledger, models, pairs ):
    """
    Count the finished model calls in a ledger that belong to one split's pairs.

    Requires:
        - ledger is a harness_runner.Ledger; models maps a judge name to the model field its judge keys carry
        - pairs are the split's harness pairs

    Ensures:
        - returns { "extract": n, "judge": { name: n } }, read from the stage and model fields of each key
        - a row whose old and new text hashes are not one of these pairs' is not counted, so a ledger that
          also holds another split's calls does not inflate this one's
        - a Claude judge key carries "<judge>+<escalation>" and a Jev key its key_id, each whole, so a judge
          is counted when its model field equals the string given
    """
    out    = { "extract": 0, "judge": { name: 0 for name in models } }
    mine   = pair_hashes( pairs )
    for key in ledger.entries:
        stage, old_hash, new_hash, _, model = key.split( "|" )[ : 5 ]
        if ( old_hash, new_hash ) not in mine: continue
        if stage == "extract": out[ "extract" ] += 1
        for name, field in models.items():
            if stage == "judge" and model == field: out[ "judge" ][ name ] += 1
    return out


def rebuild( pairs, config, ledger, backend=None ):
    """
    Rebuild one judge's results from a finished ledger, with no model call.

    Requires:
        - pairs are harness pairs; ledger holds every call config would make, except that a back-end judge
          (Jev) may lack the passes in which the back end gave no answer, which the harness never ledgers

    Ensures:
        - returns ( results, report, missing ), the report being harness_report.build_report's
        - missing lists the claim count of each pass a back-end judge lacks; it is empty for the Claude judge
        - a missing pass of a back-end judge is answered unanswered by a MissingRowProbe, so it counts in the
          report's judge_unanswered and the figures are not to be used while missing is not empty
        - a missing ledger row raises LedgerIncomplete instead of calling a model, however the transport wraps the refusal
        - any other error is raised as it is
    """
    probe = MissingRowProbe( backend ) if backend else None
    try:
        results = asyncio.run( harness_runner.run_all( pairs, config, ledger, query_fn=refuse_model_call, judge_backend=probe ) )
    except Exception as e:
        if caused_by_missing_row( e ): raise LedgerIncomplete( "the ledger is incomplete for this judge: a call it would make has no finished row" ) from e
        raise
    report  = harness_report.build_report( results, config, judge_prompt_version=backend.prompt_version if backend else None, jev_run=backend is not None )
    return results, report, probe.missing if probe else []


def check_report_binds( name, report, pairs_sha, judge_version, judge_model, binding ):
    """
    Refuse a harness report that does not belong to the run the ledger and pairs came from.

    Requires:
        - report is a harness report JSON; pairs_sha is the sha256 of the pairs file in hand
        - judge_version and judge_model are the Jev back end's prompt version and model id; binding is the
          ledger's recorded Claude Code binding, or None for an unbound ledger

    Ensures:
        - returns None when the report's pairs sha, judge prompt version, judge model and harness version equal these,
          and, for a bound ledger, its Claude Code path and version equal the binding
        - a report with no harness_version key is a version 1 report and reads as 1
        - the thresholds are not in the report, so a report from a run at other thresholds is not caught here;
          the ledger keys carry them, and a run at other thresholds would have no rows to rebuild from

    Raises:
        - ReportMismatch naming the field and both values when one differs
    """
    seen = { "pairs_sha": report.get( "pairs_sha" ), "judge prompt version": report[ "prompt_versions" ][ "judge" ], "judge model": report[ "models" ][ "judge" ],
             "harness version": report.get( "harness_version", 1 ) }
    want = { "pairs_sha": pairs_sha, "judge prompt version": judge_version, "judge model": judge_model, "harness version": harness_runner.HARNESS_VERSION }
    if binding is not None:
        seen[ "claude binary" ] = f"claude_cli={report.get( 'claude_cli' )}|version={report.get( 'claude_cli_version' )}"
        want[ "claude binary" ] = binding
    for field in want:
        if seen[ field ] != want[ field ]: raise ReportMismatch( f"{name}: the harness report is not from this run: {field} is {seen[ field ]!r} in the report and {want[ field ]!r} here" )


def check_unanswered( name, missing, reported ):
    """
    Square the passes a ledger lacks with the unanswered count the same run reported.

    Requires:
        - missing is rebuild's list of claim counts; reported is the run's judge_unanswered

    Ensures:
        - returns None when the missing passes number at most the unanswered claims, which number at most
          the claims in those passes: every missing pass holds at least one unanswered claim and no more
          than all its claims, and so no pass is missing exactly when no claim went unanswered
        - it is a bound, not an equality, so it cannot catch a reported count that is wrong by less than the slack
          between the passes and the claims in them
        - equality with the claims in the missing passes is not required: a pass is dropped from the ledger
          when any of its claims went unanswered, so it can also hold answered ones

    Raises:
        - ReportMismatch naming both numbers when they cannot both be true
    """
    held = sum( missing )
    if len( missing ) <= reported <= held: return None
    raise ReportMismatch( f"{name}: the ledger lacks {len( missing )} judge passes holding {held} claims, but the harness report says {reported} claims went unanswered "
                          f"(expected zero for both, or passes <= unanswered <= claims in those passes)" )


def build_comparison( split, pairs, keys, ledger, judges, elapsed=None, reports=None ):
    """
    Build the comparison for one split: a figure set per judge, and the shared counts.

    Requires:
        - split is "dev" or "gate"; pairs, keys and ledger describe one finished run
        - judges is { name: ( HarnessConfig, backend or None ) }
        - elapsed is { name: seconds } or None
        - reports is { name: the harness report JSON of that judge's run } or None

    Ensures:
        - returns { split, pairs, config, judges, calls }; config holds each judge's extractor lists and judge runs;
          each judge holds model, headline (the harness report's figures), groups (group_rows), and seconds
        - a judge whose ledger is incomplete is { "incomplete": reason } and never a partial figure set
        - a judge whose ledger holds more or fewer calls than its configuration makes is incomplete too, so a run
          made with more lists or runs is not rebuilt from a subset and passed off as whole
        - a back-end judge (Jev) whose ledger lacks passes is incomplete, and the reason states how many (pair, list,
          run) passes and how many claims, because the harness does not ledger a pass in which a claim got no answer
        - when reports gives that judge's run, its judge_unanswered must square with those passes (check_unanswered)
        - calls is call_counts over this split's pairs; a judge's seconds are copied from elapsed, else None

    Raises:
        - ReportMismatch when a report's unanswered count cannot be squared with the ledger's missing passes
    """
    out = { "split": split, "pairs": len( pairs ), "config": {}, "judges": {}, "calls": None }
    models = {}
    for name, ( config, backend ) in judges.items():
        models[ name ] = backend.key_id if backend else config.judge_model + "+" + config.escalation_model
        out[ "config" ][ name ] = { "extractor_lists": config.extractor_lists, "judge_runs": config.judge_runs }
        try:
            results, report, missing = rebuild( pairs, config, ledger, backend )
        except LedgerIncomplete as e:
            out[ "judges" ][ name ] = { "incomplete": str( e ) }
            continue
        if reports and name in reports: check_unanswered( name, missing, reports[ name ][ "judge_unanswered" ] )
        if missing:
            out[ "judges" ][ name ] = { "incomplete": f"{len( missing )} judge passes (pair, list, run) holding {sum( missing )} claims have no ledger row, because the harness does not ledger a pass "
                                                      f"in which a claim got no answer from the judge", "missing_passes": len( missing ), "missing_claims": sum( missing ) }
            continue
        slots = config.extractor_lists
        out[ "judges" ][ name ] = {
            "model"       : config.judge_model,
            "headline"    : report,
            "groups"      : group_rows( results, keys, slots ),
            "seconds"     : None if elapsed is None else elapsed.get( name )
        }
    out[ "calls" ] = call_counts( ledger, models, pairs )
    distinct = len( pair_hashes( pairs ) )
    judged   = len( pair_hashes( [ p for p in pairs if harness_runner.judge_skipped( p ) is None ] ) )
    for name, judge in out[ "judges" ].items():
        want_extract = distinct * out[ "config" ][ name ][ "extractor_lists" ]
        want_judge   = distinct_judged_calls( judged, out[ "config" ][ name ] )
        if "incomplete" in judge or ( out[ "calls" ][ "extract" ], out[ "calls" ][ "judge" ][ name ] ) == ( want_extract, want_judge ): continue
        out[ "judges" ][ name ] = { "incomplete": f"the ledger holds {out[ 'calls' ][ 'extract' ]} extractor and {out[ 'calls' ][ 'judge' ][ name ]} judge calls for this split, "
                                                  f"and {out[ 'config' ][ name ][ 'extractor_lists' ]} lists x {out[ 'config' ][ name ][ 'judge_runs' ]} runs over {distinct} pairs make {want_extract} and {want_judge}" }
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
    lines         = [ f"### {split} split ({comparison[ 'pairs' ]} pairs)", "",
                      "Configuration: " + "; ".join( f"{n} {c[ 'extractor_lists' ]} extractor lists x {c[ 'judge_runs' ]} judge runs" for n, c in comparison[ "config" ].items() ) + ".", "" ]
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
        if m[ "positives" ]: passes[ n ] = ( m[ "misses" ] / m[ "positives" ], m[ "upper_bound" ] )
        if a[ "unseeded" ]:  alarms[ n ] = ( a[ "false_alarm_rate" ], fa[ 1 ] )
        lines.append( f"| {n} | {m[ 'positives' ]} | {m[ 'misses' ]} | {pct( passes[ n ][ 0 ] if n in passes else None )} | {pct( m[ 'upper_bound' ] if n in passes else None )} | {a[ 'unseeded' ]} | {a[ 'false_alarms' ]} | "
                      f"{pct( alarms[ n ][ 0 ] if n in alarms else None )} | {pct( alarms[ n ][ 1 ] if n in alarms else None )} | {pct( h[ 'agreement_all' ][ 'rate' ] )}{_excluded( h, 'agreement_all' )} | {pct( h[ 'agreement_seeded' ][ 'rate' ] )}{_excluded( h, 'agreement_seeded' )} |" )
    lines += [ "", "| judge | group | expected | n | wrong | rate | 95% bound | worst list |", "|---|---|---|---|---|---|---|---|" ]
    for n, j in done.items():
        for g in j[ "groups" ]:
            lines.append( f"| {n} | {g[ 'group' ]} | {g[ 'expected' ]} | {g[ 'n' ]} | {g[ 'wrong' ]} | {pct( g[ 'rate' ] )} | {pct( g[ 'bound' ] )} | {g[ 'worst_list' ]} |" )
    empties = [ f"{n} {g[ 'group' ]} {g[ 'new_text_empty' ]}" for n, j in done.items() for g in j[ "groups" ] if g[ "new_text_empty" ] ]
    if empties: lines += [ "", "New text empty, in neither n nor wrong: " + "; ".join( empties ) + "." ]
    calls = comparison[ "calls" ]
    lines += [ "", f"Extractor calls (shared by every judge): {calls[ 'extract' ]}.", "",
               "| judge | judge calls | escalations | discarded claims | no Jev answer | seconds |", "|---|---|---|---|---|---|" ]
    for n, j in done.items():
        h = j[ "headline" ]
        lines.append( f"| {n} | {calls[ 'judge' ][ n ]} | {h[ 'escalations' ]} | {h[ 'discarded_claims' ]} | {h[ 'judge_unanswered' ] if h[ 'judge_unanswered' ] is not None else 'n/a'} | {j[ 'seconds' ] if j[ 'seconds' ] is not None else 'n/a'} |" )
    names = list( done )
    if names:
        for title, figures, what in ( ( "False-pass rate and 95% upper bound", passes, "seeded pairs" ), ( "False-alarm rate and 95% upper end", alarms, "unseeded pairs" ) ):
            drawn = [ n for n in names if n in figures ]
            lines += [ "", f"No chart point for {', '.join( n for n in names if n not in figures )}: no {what}." ] if len( drawn ) < len( names ) else []
            if drawn: lines += [ "" ] + _chart( f"{title}, {split} split", drawn, [ figures[ n ][ 0 ] for n in drawn ], [ figures[ n ][ 1 ] for n in drawn ], "bar", "line" )
        for title, wanted in ( ( "False-pass rate by pair type", ( "delete", "weaken", "injection (removed claim)" ) ),
                               ( "False-alarm rate by pair type", ( "relocate", "paraphrase", "injection (kept claim)" ) ) ):
            present = [ w for w in wanted if any( g[ "group" ] == w for j in done.values() for g in j[ "groups" ] )
                        and all( g[ "rate" ] is not None for j in done.values() for g in j[ "groups" ] if g[ "group" ] == w ) ]
            if not present: continue
            series  = { n: [ { g[ "group" ]: g[ "rate" ] for g in done[ n ][ "groups" ] }[ w ] for w in present ] for n in names }
            lines  += [ "" ] + _lines_chart( f"{title}, {split} split", present, series )
        lines += [ "" ] + _calls_chart( f"Judge calls, {split} split", names, [ calls[ "judge" ][ n ] for n in names ] )
    return "\n".join( lines ) + "\n"


def _excluded( headline, figure ):
    """
    Name the pairs with empty new text that left an agreement figure's denominator.

    Ensures:
        - returns " (n pairs left out)", or an empty string when none left
    """
    left = headline[ figure ][ "excluded_pairs" ]
    return f" ({left} pairs left out)" if left else ""


def _chart( title, names, first, second, kind_a, kind_b ):
    """Return an xychart block with two series over the judges, on a shared axis."""
    top = axis_top( first + second )
    return [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( f'\"{n}\"' for n in names )}]", f'    y-axis "share" 0 --> {top:.2f}',
             f"    {kind_a} [{', '.join( f'{v:.4f}' for v in first )}]", f"    {kind_b} [{', '.join( f'{v:.4f}' for v in second )}]", "```" ]


def _lines_chart( title, groups, series ):
    """Return an xychart block with one line per judge across the pair groups."""
    top = axis_top( [ v for vals in series.values() for v in vals ] )
    out = [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( f'\"{g}\"' for g in groups )}]", f'    y-axis "share" 0 --> {top:.2f}' ]
    out += [ f"    line [{', '.join( f'{v:.4f}' for v in vals )}]" for vals in series.values() ]
    out += [ "```", "Lines, in order: " + ", ".join( series ) + "." ]
    return out


def _calls_chart( title, names, counts ):
    """Return an xychart block with one bar per judge for its call count."""
    return [ "```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis [{', '.join( f'\"{n}\"' for n in names )}]", f'    y-axis "calls" 0 --> {max( counts + [ 1 ] )}',
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
    parser.add_argument( "--jev-report", help="the Jev run's harness report JSON: its judge_unanswered must square with the passes the ledger lacks" )
    parser.add_argument( "--frozen-pairs-sha", help="gate only: sha256 of the pairs file registered before the gate run" )
    parser.add_argument( "--extractor-lists", type=int, default=2, help="extractor lists per pair in the run being rebuilt" )
    parser.add_argument( "--claude-judge-runs", type=int, default=3, help="judge passes per list for Haiku and Sonnet" )
    parser.add_argument( "--jev-judge-runs", type=int, default=1, help="judge passes per list for Jev" )
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
        - returns 2 when the ledgers do not all record the same Claude Code binary and version, naming each; an
          unbound ledger among bound ones is a mix too
        - returns 4 and writes nothing when --jev-report is not from this run (pairs sha, judge version, judge model or Claude
          binary differ), or its judge_unanswered cannot be squared with the passes the ledger lacks, naming both
        - returns 3 when --split gate has no --frozen-pairs-sha, or it is not the sha256 of the pairs file
        - the one binding is written into the JSON as claude_cli_binding, or null when no ledger records one
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
    ledgers  = [ harness_runner.Ledger( path ) for path in args.ledger ]
    bindings = { l.recorded for l in ledgers }
    if len( bindings ) > 1:
        print( "REFUSED: the ledgers were written under different Claude Code binaries: " + "; ".join( f"{path} = {l.recorded!r}" for path, l in zip( args.ledger, ledgers ) ), file=sys.stderr )
        return 2
    ledger = ledgers[ 0 ]
    for other in ledgers[ 1 : ]: ledger.entries.update( other.entries )
    ext, esc, wri = args.extractor_model, args.escalation_model, args.writer_model
    judges = {
        "haiku" : ( harness_runner.HarnessConfig( ext, args.haiku_model,  esc, wri, args.extractor_lists, args.claude_judge_runs ), None ),
        "sonnet": ( harness_runner.HarnessConfig( ext, args.sonnet_model, esc, wri, args.extractor_lists, args.claude_judge_runs ), None ),
        "jev"   : ( harness_runner.HarnessConfig( ext, args.jev_model,    esc, wri, args.extractor_lists, args.jev_judge_runs ),
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
    reports = None
    if args.jev_report:
        with open( args.jev_report, encoding="utf-8" ) as f: reports = { "jev": json.load( f ) }
    try:
        if reports: check_report_binds( "jev", reports[ "jev" ], sha, judges[ "jev" ][ 1 ].prompt_version, args.jev_model, ledger.recorded )
        comparison = build_comparison( args.split, pairs, keys, ledger, judges, elapsed, reports )
    except ReportMismatch as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return 4
    comparison[ "pairs_sha" ] = sha
    comparison[ "claude_cli_binding" ] = ledger.recorded
    with open( args.out_json, "w", encoding="utf-8" ) as f: json.dump( comparison, f, indent=1 )
    with open( args.out_md, "w", encoding="utf-8" ) as f: f.write( render_markdown( comparison ) )
    for n, j in comparison[ "judges" ].items(): print( f"{n}: {'incomplete' if 'incomplete' in j else 'ok'}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main( sys.argv[ 1: ] ) )
