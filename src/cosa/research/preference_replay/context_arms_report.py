"""
The report that compares the five context arms, one row per arm.

Each arm is one replay of the same final-window asks, with that arm's vectors.
A row holds the arm's correct count per 100 by answer type.
It also holds the paired exact McNemar result against Q and against always-yes,
by the same summary the checkpoint report uses. The report also carries the coverage
table, so a reader sees how many asks each arm changed, and the reconciliations of those counts.
"""

from typing import Any, Dict, List, Optional

from cosa.research.preference_replay.context_arms import ARMS
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, summarize

BASELINE_ARM = "always_yes"
PAIRED_ARM   = "q_arm"


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


def compare_arms( runs: Dict[str, Dict[str, Any]], operational_floor: int ) -> List[Dict[str, Any]]:
    """
    Score every arm against Q and against always-yes.

    Requires:
        - runs maps arm names, a subset of the arm tuple that includes Q, to replay runs holding an always_yes baseline
        - operational_floor is the discordant-pair floor stated before the run

    Ensures:
        - returns one row per arm, in the arm tuple's order, each { arm, asks, by_type, vs_always_yes, vs_q }
        - vs_q is None for Q itself; otherwise it is summarize with Q as the baseline
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
                       "vs_always_yes": summarize( runs[ arm ], BASELINE_ARM, operational_floor ),
                       "vs_q": None if arm == "Q" else summarize( _paired_with_q( runs[ arm ], runs[ "Q" ] ), PAIRED_ARM, operational_floor ) } )
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
        - the results table gives correct per 100 for each answer type, then the pairs against Q and against always-yes
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
               " | vs Q: arm only | vs Q: Q only | vs Q: p | vs Q: verdict | vs always-yes: arm only | vs always-yes: yes only | vs always-yes: p | vs always-yes: verdict |",
               "|---|" + "---|" * ( len( kinds ) + 8 ) ]
    for row in rows:
        cells = " | ".join( f"{row[ 'by_type' ][ kind ][ 'per_100' ]:.1f} ({row[ 'by_type' ][ kind ][ 'asks' ]})" if kind in row[ "by_type" ] else "-" for kind in kinds )
        lines.append( f"| {row[ 'arm' ]} | {cells} | {_pair_cells( row[ 'vs_q' ] )} | {_pair_cells( row[ 'vs_always_yes' ] )} |" )
    return "\n".join( lines ) + "\n"
