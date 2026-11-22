"""
The report that compares the five context arms, one row per arm.

Each arm is one replay of the same final-window asks, with that arm's vectors.
A row holds the arm's correct count per 100 by answer type.
It also holds the paired exact McNemar result against Q and against always-yes,
by the same summary the checkpoint report uses. The report also carries the coverage
table, so a reader sees how many asks each arm changed, and the reconciliations of those counts.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import cosa.utils.util as cu
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.preference_replay.arm_scoring import expand
from cosa.research.preference_replay.context_arms import ARMS
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, summarize

BASELINE_ARM = "always_yes"
PAIRED_ARM   = "q_arm"
YES_NO       = "yes_no"


def _engine_records( run: Dict[str, Any] ) -> List[Dict[str, Any]]:
    """
    Read the engine's per-ask records out of one replay run.

    Requires:
        - run is the dict replay returns

    Ensures:
        - returns the records of the engine arm, in replay order
    """
    return run[ "records" ][ ENGINE_ARM ]


def _ids( run: Dict[str, Any] ) -> List[str]:
    """
    List the asks one run replayed, in order.

    Requires:
        - run is the dict replay returns

    Ensures:
        - returns the notification ids of the engine records
    """
    return [ record[ "meta" ][ "notification_id" ] for record in _engine_records( run ) ]


def _per_100_by_type( run: Dict[str, Any] ) -> Dict[str, Dict[str, Any]]:
    """
    Score one run by answer type.

    Requires:
        - run is the dict replay returns

    Ensures:
        - returns response type to { asks, correct, per_100 }, with types in sorted order
        - per_100 is 100 times correct over asks
    """
    tally = {}
    for record in _engine_records( run ):
        cell = tally.setdefault( record[ "meta" ][ "response_type" ], { "asks": 0, "correct": 0 } )
        cell[ "asks" ]   += 1
        cell[ "correct" ] += 1 if record[ "meta" ][ "correct" ] else 0
    return { kind: dict( cell, per_100=100.0 * cell[ "correct" ] / cell[ "asks" ] ) for kind, cell in sorted( tally.items() ) }


def _paired_with_q( run: Dict[str, Any], q_run: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Make a run in which Q stands as the baseline of an arm.

    Requires:
        - run and q_run replayed the same asks in the same order

    Ensures:
        - returns a run whose baseline records are Q's engine records, so summarize pairs the arm with Q
        - the inputs are not changed
    """
    return dict( run, records={ ENGINE_ARM: _engine_records( run ), PAIRED_ARM: _engine_records( q_run ) } )


def _slice( run: Dict[str, Any], kind: str ) -> Dict[str, Any]:
    """
    Cut a run to the asks of one answer type.

    Requires:
        - run is the dict replay returns

    Ensures:
        - returns a run whose every arm holds only the records of that type, in order
        - the inputs are not changed
    """
    return dict( run, records={ arm: [ r for r in records if r[ "meta" ][ "response_type" ] == kind ] for arm, records in run[ "records" ].items() } )


def _kinds( run: Dict[str, Any] ) -> List[str]:
    """
    List the answer types a run replayed, sorted.

    Requires:
        - run is the dict replay returns

    Ensures:
        - returns each response type once, the keys of _per_100_by_type
    """
    return sorted( _per_100_by_type( run ) )


def compare_arms( runs: Dict[str, Dict[str, Any]], operational_floor: int ) -> List[Dict[str, Any]]:
    """
    Score every arm against Q and against always-yes.

    Requires:
        - runs maps arm names, a subset of the arm tuple that includes Q, to replay runs holding an always_yes baseline
        - operational_floor is the discordant-pair floor stated before the run

    Ensures:
        - returns one row per arm, in the arm tuple's order, each { arm, asks, by_type, vs_always_yes, vs_q, vs_q_by_type }
        - vs_always_yes counts the yes/no asks only, because always-yes has no answer to a multiple-choice ask; it is None with no yes/no ask
        - vs_q is None for Q itself; otherwise it is summarize with Q as the baseline
        - vs_q_by_type is empty for Q; otherwise it maps each answer type to that same summary over the type's asks
        - the arms replayed identical asks in identical order, so every pair is the same ask

    Raises:
        - ValueError if Q is missing, an arm name is unknown, or two arms replayed different asks
    """
    unknown = [ arm for arm in runs if arm not in ARMS ]
    if unknown: raise ValueError( f"unknown arms {unknown}; the arms are {ARMS}" )
    if "Q" not in runs: raise ValueError( "the Q arm is required as the baseline of every other arm" )
    expected = _ids( runs[ "Q" ] )
    rows     = []
    for arm in ( a for a in ARMS if a in runs ):
        if _ids( runs[ arm ] ) != expected: raise ValueError( f"arm {arm} replayed different asks from Q" )
        rows.append( { "arm": arm, "asks": len( expected ), "by_type": _per_100_by_type( runs[ arm ] ),
                       "vs_always_yes": summarize( _slice( runs[ arm ], YES_NO ), BASELINE_ARM, operational_floor ) if YES_NO in _kinds( runs[ arm ] ) else None,
                       "vs_q": None if arm == "Q" else summarize( _paired_with_q( runs[ arm ], runs[ "Q" ] ), PAIRED_ARM, operational_floor ),
                       "vs_q_by_type": {} if arm == "Q" else { kind: summarize( _paired_with_q( _slice( runs[ arm ], kind ), _slice( runs[ "Q" ], kind ) ),
                                                                                PAIRED_ARM, operational_floor ) for kind in _kinds( runs[ arm ] ) } } )
    return rows


def _pair_cells( summary: Optional[Dict[str, Any]] ) -> str:
    """
    Write one paired comparison as table cells.

    Requires:
        - summary is None or a summarize result

    Ensures:
        - returns "arm only | baseline only | p | verdict" cells, or dashes for None
    """
    if summary is None: return "- | - | - | -"
    return f"{summary[ 'engine_only_right' ]} | {summary[ 'baseline_only_right' ]} | {summary[ 'mcnemar' ][ 'p_value' ]:.4f} | {summary[ 'verdict' ]}"


def render_arm_report( rows: List[Dict[str, Any]], coverage: Dict[str, Dict[str, int]], reconciliations: List[Dict[str, str]],
                       provenance: Dict[str, str] ) -> str:
    """
    Render the context comparison as Markdown.

    Requires:
        - rows come from compare_arms
        - coverage maps each arm to its build_arm_texts counts
        - reconciliations is a list of { title, detail }, each stating a count and why it differs from another
        - provenance maps a label to a value, such as the commit, the vector source and the read time

    Ensures:
        - returns text with the provenance, the coverage table, the reconciliations, and one results row per arm
        - the results table gives correct per 100 for each answer type, then the pairs against Q and against always-yes on yes/no asks
        - a second table gives the pair against Q for each answer type
        - the same inputs give the same text
    """
    kinds = sorted( { kind for row in rows for kind in row[ "by_type" ] } )
    lines = [ "# Context comparison report", "" ] + [ f"- {label}: {value}" for label, value in provenance.items() ]
    lines += [ "", "## Coverage", "",
               "| arm | asks | with its section | no context | arm input empty |", "|---|---|---|---|---|" ]
    for row in rows:
        counts = coverage[ row[ "arm" ] ]
        lines.append( f"| {row[ 'arm' ]} | {counts[ 'asks' ]} | {counts[ 'with_section' ]} | {counts[ 'no_context' ]} | {counts[ 'arm_input_absent' ]} |" )
    lines += [ "", "## Reconciliations", "" ] + [ f"- **{item[ 'title' ]}**: {item[ 'detail' ]}" for item in reconciliations ]
    lines += [ "", "## Results", "",
               "| arm | " + " | ".join( f"{kind} correct per 100 (asks)" for kind in kinds ) +
               " | vs Q: arm only | vs Q: Q only | vs Q: p | vs Q: verdict | vs always-yes (yes/no only): arm only | yes only | p | verdict |",
               "|---|" + "---|" * ( len( kinds ) + 8 ) ]
    for row in rows:
        cells = " | ".join( f"{row[ 'by_type' ][ kind ][ 'per_100' ]:.1f} ({row[ 'by_type' ][ kind ][ 'asks' ]})" if kind in row[ "by_type" ] else "-" for kind in kinds )
        lines.append( f"| {row[ 'arm' ]} | {cells} | {_pair_cells( row[ 'vs_q' ] )} | {_pair_cells( row[ 'vs_always_yes' ] )} |" )
    lines += [ "", "## Against Q by answer type", "", "| arm | answer type | arm only | Q only | p | verdict |", "|---|---|---|---|---|---|" ]
    for row in rows:
        for kind, summary in row[ "vs_q_by_type" ].items(): lines.append( f"| {row[ 'arm' ]} | {kind} | {_pair_cells( summary )} |" )
    return "\n".join( lines ) + "\n"


ARM_FILE_STEMS = { "Q": "q", "Q+A": "q-a", "Q+O": "q-o", "Q+P": "q-p", "Q+H": "q-h" }


def read_coverage( side_file_prefix: str ) -> Dict[str, Dict[str, int]]:
    """
    Read each arm's coverage counts from the header of its side file.

    Requires:
        - side_file_prefix plus an arm's stem and ".jsonl" names the side file of each arm but Q

    Ensures:
        - returns { arm: { asks, with_section, no_context, arm_input_absent } }, the four counts as the side file's header wrote them
        - Q has every ask with its section, since it adds nothing to the question

    Raises:
        - ValueError if a header's three reason counts do not add up to its asks, or the arms hold different numbers of asks
    """
    coverage = {}
    for arm, stem in ARM_FILE_STEMS.items():
        if arm == "Q": continue
        with open( f"{side_file_prefix}{stem}.jsonl", encoding="utf-8" ) as handle: counts = json.loads( handle.readline() )[ "facts" ][ "arm_counts" ]
        if counts[ "with_section" ] + counts[ "no_context" ] + counts[ "arm_input_absent" ] != counts[ "asks" ]: raise ValueError( f"{arm}: the reason counts do not add up to the asks" )
        coverage[ arm ] = { key: counts[ key ] for key in ( "asks", "with_section", "no_context", "arm_input_absent" ) }
    if len( { counts[ "asks" ] for counts in coverage.values() } ) != 1: raise ValueError( "the arms hold different numbers of asks" )
    asks = next( iter( coverage.values() ) )[ "asks" ]
    return { "Q": { "asks": asks, "with_section": asks, "no_context": 0, "arm_input_absent": 0 }, **coverage }


def main( argv: Optional[Sequence[str]] = None, code_sha: Optional[str] = None, clock: Optional[Callable] = None ) -> int:
    """
    Build the context comparison report from the committed per-ask files.

    Requires:
        - argv holds --per-ask-dir (holding prediction-context-arm-<stem>-per-ask.json for each arm), --side-file-prefix
          (read_coverage), --floor, --floor-source, --out, and --notes-file, one "title: detail" reconciliation per line
        - code_sha and clock are injected by tests

    Ensures:
        - writes the Markdown report to --out, its header naming the code sha, the floor and where it comes from,
          each per-ask file's own code sha, the time, and the exact command line
        - returns 0

    Raises:
        - ValueError as compare_arms does
    """
    parser = argparse.ArgumentParser( description="Write the context comparison report." )
    for name in ( "--per-ask-dir", "--side-file-prefix", "--floor", "--floor-source", "--out" ): parser.add_argument( name, required=True )
    parser.add_argument( "--notes-file", required=True )
    args    = parser.parse_args( argv )
    command = "python -m cosa.research.preference_replay.context_arms_report " + " ".join( list( argv ) if argv is not None else sys.argv[ 1: ] )
    docs    = { arm: json.load( open( f"{args.per_ask_dir}/prediction-context-arm-{stem}-per-ask.json", encoding="utf-8" ) ) for arm, stem in ARM_FILE_STEMS.items() }
    rows       = compare_arms( { arm: expand( doc[ "run" ] ) for arm, doc in docs.items() }, int( args.floor ) )
    with open( args.notes_file, encoding="utf-8" ) as handle: notes = [ dict( zip( ( "title", "detail" ), line.rstrip( "\n" ).split( ": ", 1 ) ) ) for line in handle if line.strip() ]
    provenance = { "code sha of this report": code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" ),
                   "discordant floor": f"{args.floor} pairs; source: {args.floor_source}",
                   "per-ask files scored on code": ", ".join( f"{arm} {docs[ arm ][ 'code_sha' ][ :9 ]}" for arm in docs ),
                   "generated": ( clock or ( lambda: datetime.now( timezone.utc ) ) )().isoformat(), "command": f"`{command}`" }
    with open( args.out, "w", encoding="utf-8" ) as handle: handle.write( render_arm_report( rows, read_coverage( args.side_file_prefix ), notes, provenance ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
