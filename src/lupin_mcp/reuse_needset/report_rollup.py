"""
Roll the overnight experiments' outputs up into one markdown report.

It reads the JSON that yield_trace, forced_judge and expansion_run print or write.
It renders one table per experiment: counts with Wilson intervals, per language,
and per resolved label where the data carries one.

The positive control's table is rendered from per-pair rows. It shows the discordant
pairs a and b and the a - b <= 2 mark. The reader that turns John's control report
into those rows is a stub until his merge lands.

It makes no model call, no search and no spend-ledger write: it only reads files and returns text.
"""

import argparse
import json
import math
import pathlib

Z95          = 1.959963984540054   # two-sided 95 percent
CONTROL_MARK = 2                   # plan section 10: the control passes when a - b <= 2
NOT_RUN      = "not run"


def wilson( successes, trials, z=Z95 ):
    """
    Return the two-sided Wilson score interval for a proportion.

    Requires:
        - 0 <= successes <= trials

    Ensures:
        - returns None when trials is 0
        - returns ( lower, upper ) within 0.0 and 1.0
        - the lower end is exactly 0.0 for no successes and the upper end exactly 1.0 for all of them

    Raises:
        - ValueError when successes is outside 0..trials
    """
    if not 0 <= successes <= trials: raise ValueError( f"successes {successes} is outside 0..{trials}" )
    if trials == 0: return None
    p      = successes / trials
    denom  = 1 + z * z / trials
    centre = ( p + z * z / ( 2 * trials ) ) / denom
    half   = z * math.sqrt( p * ( 1 - p ) / trials + z * z / ( 4 * trials * trials ) ) / denom
    lower  = 0.0 if successes == 0 else max( 0.0, centre - half )
    upper  = 1.0 if successes == trials else min( 1.0, centre + half )
    return lower, upper


def share( successes, trials ):
    """
    Format a count as "k/n (p%, lo-hi%)" with its Wilson interval.

    Requires:
        - 0 <= successes <= trials

    Ensures:
        - returns "k/0 (n/a)" when there are no trials
        - percentages carry one decimal
    """
    interval = wilson( successes, trials )
    if interval is None: return f"{successes}/{trials} (n/a)"
    return f"{successes}/{trials} ({100 * successes / trials:.1f}%, {100 * interval[ 0 ]:.1f}-{100 * interval[ 1 ]:.1f}%)"


def table( headers, rows ):
    """
    Render a markdown table.

    Requires:
        - every row has as many cells as there are headers

    Ensures:
        - returns the table as text without a trailing newline
        - cells are written with str()
    """
    lines = [ "| " + " | ".join( headers ) + " |", "|" + "|".join( " --- " for _ in headers ) + "|" ]
    for row in rows: lines.append( "| " + " | ".join( str( c ) for c in row ) + " |" )
    return "\n".join( lines )


def split( doc ):
    """
    Split an experiment's JSON into its plan and its run.

    Requires:
        - doc is a module's printed result ( { live, plan, report? } ) or a report file it wrote

    Ensures:
        - returns ( plan, run ): plan is None for a bare report file; run is None for a plan-only result
    """
    if "plan" in doc: return doc[ "plan" ], doc.get( "report" )
    return None, doc


def load( path ):
    """
    Read one experiment's JSON file.

    Requires:
        - path names a file holding a JSON object

    Ensures:
        - returns the parsed object
    """
    return json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )


def counts_table( title, counts ):
    """
    Render a plain two-column count table.

    Requires:
        - counts is { name: number }

    Ensures:
        - returns a table titled title with the names in the order given
    """
    return table( [ title, "count" ], [ [ k, v ] for k, v in counts.items() ] )


def yield_section( doc ):
    """
    Render the yield trace, the needs traced end to end.

    Requires:
        - doc comes from yield_trace: its printed result or its yield-trace-report.json

    Ensures:
        - a plan-only result gives the needs per language and what a run would trace, with the figures marked not run
        - a finished trace gives the found share overall and per language with Wilson intervals, then the count by where each member was lost
        - a run that stopped or hit its budget gives its status and no figures
    """
    plan, run = split( doc )
    head      = [ "## C2 yield trace (needs traced end to end, the seed as known answer)" ]
    if run is None:
        out = [ f"Plan only: no model was asked. Seeds {plan[ 'seeds' ]}, needs {plan[ 'needs' ]}, unsaved answers {len( plan[ 'unsaved' ] )}, seeds with no final need {plan[ 'no_final_need' ]}.",
                counts_table( "language", plan[ "by_lang" ] ), f"Found share: {NOT_RUN}." ]
        return "\n\n".join( head + out )
    report = run[ "report" ]
    out    = [ f"Run status {run[ 'status' ]}, {run[ 'used' ]} of {run[ 'limit' ]} calls used." ]
    if not report.get( "traced" ):
        out.append( f"No figures: the trace did not finish ({report.get( 'reason', report.get( 'budget_detail', report.get( 'detail', 'no reason given' ) ) )})." )
        return "\n\n".join( head + out )
    rows = [ [ "all", share( report[ "found" ], report[ "members" ] ) ] ]
    for lang, f in sorted( report[ "found_by_lang" ].items() ): rows.append( [ lang, share( f[ "found" ], f[ "members" ] ) ] )
    out.append( table( [ "language", "key members found (Wilson 95%)" ], rows ) )
    out.append( counts_table( "lost at", report[ "by_lost_at" ] ) )
    return "\n\n".join( head + out )


def judge_rows( results, key ):
    """
    Count the forced judge's results by one field.

    Requires:
        - results are forced_judge result rows; key is label or lang

    Ensures:
        - returns table rows [ value, pairs, already in, answered, accepted share ] sorted by value
        - the accepted share is over the pairs the judge answered
    """
    groups = { }
    for r in results:
        g = groups.setdefault( r[ key ], { "pairs": 0, "already_in": 0, "answered": 0, "accepted": 0 } )
        g[ "pairs" ] += 1
        if r[ "was_in_shortlist" ]:
            g[ "already_in" ] += 1
            continue
        g[ "answered" ]  += bool( r[ "answered" ] )
        g[ "accepted" ]  += bool( r[ "accepted" ] )
    return [ [ v, g[ "pairs" ], g[ "already_in" ], g[ "answered" ], share( g[ "accepted" ], g[ "answered" ] ) ] for v, g in sorted( groups.items() ) ]


def forced_section( doc ):
    """
    Render the forced-shortlist judge.

    Requires:
        - doc comes from forced_judge: its printed result or its forced-judge-report.json

    Ensures:
        - a plan-only result gives the missed pairs per resolved label, the requests a run needs and the undrafted ids, with the figures marked not run
        - a finished run gives, per resolved label and per language, the pairs, those already in the shortlist, those answered and the accepted share with its Wilson interval
        - the not_same row is the judge against the human labels, so its accepts are false accepts
    """
    plan, run = split( doc )
    head      = [ "## C1 forced-shortlist judge (each missed plant placed in the 128)" ]
    if run is None:
        out = [ f"Plan only: no model was asked. Missed pairs {plan[ 'pairs' ]}, requests needed {plan[ 'requests_needed' ]} of a stage budget of {plan[ 'stage_budget' ]}, undrafted {len( plan[ 'undrafted' ] )}.",
                counts_table( "resolved label", plan[ "by_label" ] ), f"Judge recall: {NOT_RUN}." ]
        return "\n\n".join( head + out )
    out     = [ f"Run status {run[ 'status' ]}, {run[ 'used' ]} of {run[ 'limit' ]} calls used." ]
    headers = [ "pairs", "already in the 128", "answered", "accepted of answered (Wilson 95%)" ]
    out.append( table( [ "resolved label" ] + headers, judge_rows( run[ "results" ], "label" ) ) )
    out.append( table( [ "language" ] + headers, judge_rows( run[ "results" ], "lang" ) ) )
    out.append( "On the not_same row an accept is a false accept." )
    return "\n\n".join( head + out )


def expansion_section( doc ):
    """
    Render the need expansion.

    Requires:
        - doc comes from expansion_run: its printed result or its expansion-report.json

    Ensures:
        - a plan-only result gives the needs per group and what a run would ask, with the figures marked not run
        - a finished run gives, per group, the known answers entering the 128 before and after with Wilson intervals, the lifted and lowered counts and the unreadable replies
        - the shares are over the needs whose reply was readable
        - "enters 128" is fused rank 128 or better, not the production shortlist, and the table says so
        - the results do not record a language, so there is no per-language table
    """
    plan, run = split( doc )
    head      = [ "## C5 need expansion (known answer's rank before and after)" ]
    if run is None:
        out = [ f"Plan only: no model was asked. Rows {plan[ 'rows' ]}, calls needed {plan[ 'calls_needed' ]} of a stage budget of {plan[ 'stage_budget' ]}, replies already saved {plan[ 'saved_replies' ]}, undrafted {len( plan[ 'undrafted' ] )}.",
                counts_table( "group", plan[ "by_group" ] ), f"Entry into the 128: {NOT_RUN}." ]
        return "\n\n".join( head + out )
    rows = [ ]
    for group, g in run[ "summary" ].items():
        read = g[ "needs" ] - g[ "unreadable" ]
        rows.append( [ group, g[ "needs" ], g[ "unreadable" ], share( g[ "enter_before" ], read ), share( g[ "enter_after" ], read ), g[ "lifted" ], g[ "lowered" ] ] )
    out = [ f"Run status {run[ 'status' ]}, {run[ 'used' ]} of {run[ 'limit' ]} calls used.",
            table( [ "group", "needs", "unreadable", "enters 128 before (Wilson 95%)", "enters 128 after (Wilson 95%)", "lifted", "lowered" ], rows ),
            "Enters 128 means fused rank 128 or better, not the production shortlist with its forced top-5s, so it reads a little optimistic. The results record no language." ]
    return "\n\n".join( head + out )


def discordant( pairs ):
    """
    Count the control's discordant pairs.

    Requires:
        - pairs are { id, original_in, plant_in } rows for the same-job pairs that drafted, the two flags being whether each was in the 128

    Ensures:
        - returns { a, b, both, neither, passes }: a is original in and plant not, b is plant in and original not
        - passes is true when a - b is at most CONTROL_MARK
    """
    a       = sum( 1 for p in pairs if p[ "original_in" ] and not p[ "plant_in" ] )
    b       = sum( 1 for p in pairs if p[ "plant_in" ] and not p[ "original_in" ] )
    both    = sum( 1 for p in pairs if p[ "original_in" ] and p[ "plant_in" ] )
    return { "a": a, "b": b, "both": both, "neither": len( pairs ) - a - b - both, "passes": a - b <= CONTROL_MARK }


def control_pairs_from_report( report ):
    """
    Turn John's positive-control report into per-pair rows. A stub until his merge lands.

    Requires:
        - report is the parsed control report

    Raises:
        - NotImplementedError always, naming what is waiting
    """
    raise NotImplementedError( "the control report's shape is John's and is not merged yet; pass per-pair rows to control_section instead" )


def control_section( pairs=None ):
    """
    Render the positive control (plan section 10, the paired mark).

    Requires:
        - pairs is None, or rows for discordant(); the same-job pairs that drafted

    Ensures:
        - with no pairs gives a placeholder saying the control report is not read yet
        - otherwise gives a, b, both-in, neither-in, the original's and the plant's share in the 128 with Wilson intervals, and the verdict on a - b <= 2
        - the verdict is worded "the plants are not worse than the originals by more than two pairs", never "equivalent"
        - the note that retrieval is one sample, the same in both passes, is printed beside the figures
    """
    head = [ "## Positive control (plants against originals, same-job pairs that drafted)" ]
    if pairs is None: return "\n\n".join( head + [ f"Not read yet: the control report is John's and has not merged. Figures: {NOT_RUN}." ] )
    d, n = discordant( pairs ), len( pairs )
    rows = [ [ "original in the 128", share( sum( 1 for p in pairs if p[ "original_in" ] ), n ) ], [ "plant in the 128", share( sum( 1 for p in pairs if p[ "plant_in" ] ), n ) ],
             [ "a (original in, plant not)", d[ "a" ] ], [ "b (plant in, original not)", d[ "b" ] ], [ "both in", d[ "both" ] ], [ "neither in", d[ "neither" ] ], [ "a - b", d[ "a" ] - d[ "b" ] ] ]
    verdict = f"a - b <= {CONTROL_MARK}: " + ( "met" if d[ "passes" ] else "not met" ) + ". Read as: the plants are not worse than the originals by more than two pairs."
    return "\n\n".join( head + [ table( [ "figure", "value" ], rows ), verdict, "Retrieval is deterministic on frozen drafts, so this is one sample, the same in both passes; only the judge varies." ] )


def render( yield_doc=None, forced_doc=None, expansion_doc=None, control_pairs=None ):
    """
    Render the whole report.

    Requires:
        - each document is None or the parsed JSON of its experiment; control_pairs is None or rows for discordant()

    Ensures:
        - returns markdown with the control, forced judge, yield trace and expansion sections in that order, one per experiment
        - an experiment with no document gets a line saying so and no figures
    """
    parts = [ "# First-thousand overnight experiments: roll-up", "Intervals are two-sided 95 percent Wilson. A plan-only input shows counts and what a run would do; its figures are marked not run." ]
    parts.append( control_section( control_pairs ) )
    for doc, section, name in ( ( forced_doc, forced_section, "C1 forced-shortlist judge" ), ( yield_doc, yield_section, "C2 yield trace" ), ( expansion_doc, expansion_section, "C5 need expansion" ) ):
        parts.append( section( doc ) if doc is not None else f"## {name}\n\nNo input given." )
    return "\n\n".join( parts ) + "\n"


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - every input is optional; --out names a file to write, otherwise the report is printed
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "yield-trace", "forced-judge", "expansion", "out" ): ap.add_argument( "--" + name, default=None )
    return ap.parse_args( argv )


def main( argv=None, out=print ):
    """
    Read the named files and write the report.

    Ensures:
        - makes no model call, search or spend-ledger write
        - writes the report to --out when given, else passes it to out
        - returns 0
    """
    args = parse_args( argv )
    read = lambda path: None if path is None else load( path )
    text = render( read( args.yield_trace ), read( args.forced_judge ), read( args.expansion ) )
    if args.out is None: out( text )
    else: pathlib.Path( args.out ).write_text( text, encoding="utf-8" )
    return 0


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested
    raise SystemExit( main() )
