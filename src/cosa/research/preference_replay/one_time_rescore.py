"""
The one-time re-score of the five context arms under the complete-action measure.

It reads the committed per-ask files of the five arms, which hold each arm's stored forecast and its old
correct flag. It reads the full answers by id from the database in a read-only transaction. It scores each
stored forecast as it is, with no judge. A stance-only forecast against an answer that carries a condition
is an omission. A free-text condition that would need the judge stays undecided and is counted so.
It makes no model call, recomputes no forecast and writes only its report.
The old column is the stored flag. The new column is the complete-action measure beside it.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import cosa.utils.util as cu
from cosa.agents.prediction_engine.accuracy_comparators import get_comparator
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.preference_replay.replay_loop import _actual_dict
from cosa.research.preference_replay.retune_run import read_cohort
from cosa.rest.db.database import get_db
from cosa.utils.agreement_stats import mcnemar_exact
from cosa.utils.atomic_json import write_json_atomic
from cosa.utils.file_hash import file_sha256

ARM_FILE_STEMS = { "Q": "q", "Q+A": "q-a", "Q+O": "q-o", "Q+P": "q-p", "Q+H": "q-h" }
PAIRED_ARM     = "Q"
SWITCH_PATTERN = re.compile( r"^(prediction [^=#]*?(?:enabled|switch))\s*=\s*(\S+)", re.MULTILINE )
NOT_STORED     = "no stored per-ask forecasts"
PHASES_NOT_STORED = {
    "phase 7":  "only prediction-phase7-paired-report.json, aggregate counts; no per-ask forecast",
    "phase 8":  "prediction-three-way-replay-report.md says its raw per-ask output was not committed; recomputing it is a replay, not a re-score",
    "phase 9":  "prediction-calibration.json holds a fitted curve, no per-ask forecast",
    "phase 10": "deferred to 11 Dec, nothing run, nothing reported",
    "phase 11": "the failure half counts abstention reasons, with no forecast to score",
}


def read_switches( ini_path: str ) -> Dict[str, str]:
    """
    Read the state of every prediction switch from the INI file.

    Requires:
        - ini_path names an INI file whose lines read "key = value"

    Ensures:
        - returns each key that begins "prediction" and ends "enabled" or "switch", with its value text
        - a commented line is not read
    """
    with open( ini_path, encoding="utf-8" ) as handle: text = handle.read()
    return { key.strip(): value for key, value in SWITCH_PATTERN.findall( text ) }


def read_answers( session ) -> Dict[str, Dict[str, Any]]:
    """
    Read every scored ask's full answer and answer schema, in a read-only transaction.

    Requires:
        - session is an active SQLAlchemy session

    Ensures:
        - returns ask id to { actual_value, response_options, response_type }
        - read_cohort makes the transaction read-only first, so the database refuses a write
    """
    asks, _ = read_cohort( session, None )
    return { ask[ "id" ]: { "actual_value": ask[ "actual_value" ], "response_options": ask[ "response_options" ], "response_type": ask[ "response_type" ] } for ask in asks }


def score_ask( record: Dict[str, Any], answer: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Score one stored forecast by the complete-action measure, with no judge.

    Requires:
        - record is a per-ask record with response_type, forecast and correct
        - answer is the entry read_answers returns for its id

    Ensures:
        - returns { old, new, decided }; old is the stored flag
        - new is True, False, or None when only the judge could decide
        - an abstention (forecast None) is False and decided, as the measure charges it
    """
    comparator = get_comparator( record[ "response_type" ], response_options=answer[ "response_options" ], complete_action=True )
    match, _   = comparator( record[ "forecast" ], _actual_dict( answer[ "actual_value" ], record[ "response_type" ] ) )
    return { "old": bool( record[ "correct" ] ), "new": match, "decided": match is not None }


def score_arm( records: List[Dict[str, Any]], answers: Dict[str, Dict[str, Any]] ) -> Dict[str, Dict[str, Any]]:
    """
    Score every record of one arm, keyed by ask id.

    Requires:
        - every record id is in answers

    Raises:
        - KeyError naming an ask whose answer was not read
    """
    return { record[ "id" ]: dict( score_ask( record, answers[ record[ "id" ] ] ), response_type=record[ "response_type" ] ) for record in records }


def tally( scores: Dict[str, Dict[str, Any]], kind: Optional[str] = None ) -> Dict[str, Any]:
    """
    Count one arm's old and new columns, with decided coverage beside them.

    Requires:
        - scores is what score_arm returns; kind is a response type or None for all

    Ensures:
        - returns asks, old_correct, new_passed, decided, undecided and coverage (decided over asks)
        - an undecided ask counts in asks and undecided, never in new_passed
    """
    cells    = [ s for s in scores.values() if kind is None or s[ "response_type" ] == kind ]
    decided  = sum( 1 for s in cells if s[ "decided" ] )
    return { "asks": len( cells ), "old_correct": sum( 1 for s in cells if s[ "old" ] ), "new_passed": sum( 1 for s in cells if s[ "new" ] is True ),
             "decided": decided, "undecided": len( cells ) - decided, "coverage": decided / len( cells ) if cells else 0.0 }


def paired( arm: Dict[str, Dict[str, Any]], base: Dict[str, Dict[str, Any]], column: str ) -> Dict[str, Any]:
    """
    Pair an arm with a baseline on one column, the way the report's old rows were paired.

    Requires:
        - arm and base score the same ids; column is "old" or "new"

    Ensures:
        - the new column pairs only the asks decided in both; the old column pairs every ask
        - returns n, arm_only, base_only, difference (arm_only minus base_only), sign (-1, 0 or 1) and the exact McNemar p
    """
    ids = [ i for i in arm if column == "old" or ( arm[ i ][ "decided" ] and base[ i ][ "decided" ] ) ]
    ok  = lambda s: s[ column ] is True
    a   = sum( 1 for i in ids if ok( arm[ i ] ) and not ok( base[ i ] ) )
    b   = sum( 1 for i in ids if ok( base[ i ] ) and not ok( arm[ i ] ) )
    return { "n": len( ids ), "arm_only": a, "base_only": b, "difference": a - b, "sign": ( a > b ) - ( a < b ), "p_value": mcnemar_exact( a, b ) }


def rescore( per_arm: Dict[str, List[Dict[str, Any]]], answers: Dict[str, Dict[str, Any]] ) -> Dict[str, Any]:
    """
    Re-score every arm and pair each with Q and, on yes/no asks, with always-yes.

    Requires:
        - per_arm maps an arm name to its per-ask records, the same ids in each; PAIRED_ARM is among them
        - answers covers every id

    Ensures:
        - returns { arms: { arm: { all, by_type, vs_q, vs_always_yes } } }
        - each vs_ entry holds old, new and sign_reversed: both signs nonzero and unequal; a sign that moves to or from zero is shown, not flagged
        - the always-yes forecast is the stored always_yes_correct flag for the old column and the constant yes forecast for the new
    """
    scored = { arm: score_arm( records, answers ) for arm, records in per_arm.items() }
    yes    = { r[ "id" ]: score_ask( dict( r, forecast={ "value": "yes" }, correct=r[ "always_yes_correct" ] ), answers[ r[ "id" ] ] ) for r in per_arm[ PAIRED_ARM ] if r[ "response_type" ] == "yes_no" }
    yes    = { i: dict( s, response_type="yes_no" ) for i, s in yes.items() }
    out    = {}
    for arm, scores in scored.items():
        yn      = { i: s for i, s in scores.items() if s[ "response_type" ] == "yes_no" }
        entry   = { "all": tally( scores ), "by_type": { kind: tally( scores, kind ) for kind in sorted( { s[ "response_type" ] for s in scores.values() } ) } }
        for name, base, mine in ( ( "vs_q", scored[ PAIRED_ARM ], scores ), ( "vs_always_yes", yes, yn ) ):
            if name == "vs_q" and arm == PAIRED_ARM: continue
            old, new = paired( mine, base, "old" ), paired( mine, base, "new" )
            entry[ name ] = { "old": old, "new": new, "sign_reversed": old[ "sign" ] * new[ "sign" ] == -1 }
        out[ arm ] = entry
    return { "arms": out, "always_yes": tally( yes ) }


def load_per_ask( per_ask_dir: str ) -> Dict[str, Any]:
    """
    Read the five committed per-ask files.

    Requires:
        - per_ask_dir holds prediction-context-arm-<stem>-per-ask.json for each arm

    Ensures:
        - returns { records: { arm: asks }, files: { arm: { sha256, code_sha, ids_sha256 } } }

    Raises:
        - ValueError when the arms did not score the same ids in the same order
    """
    records, files = {}, {}
    for arm, stem in ARM_FILE_STEMS.items():
        path = f"{per_ask_dir}/prediction-context-arm-{stem}-per-ask.json"
        with open( path, encoding="utf-8" ) as handle: doc = json.load( handle )
        records[ arm ] = doc[ "run" ][ "asks" ]
        files[ arm ]   = { "file": path, "sha256": file_sha256( path ), "code_sha": doc[ "code_sha" ], "ids_sha256": doc[ "ids" ][ "only_ids_sha256" ], "ids_count": doc[ "ids" ][ "only_ids_count" ] }
    base = [ r[ "id" ] for r in records[ PAIRED_ARM ] ]
    for arm, rows in records.items():
        if [ r[ "id" ] for r in rows ] != base: raise ValueError( f"arm {arm} did not score the same asks in the same order as {PAIRED_ARM}" )
    return { "records": records, "files": files }


def build_report( per_ask: Dict[str, Any], answers: Dict[str, Dict[str, Any]], run_facts: Dict[str, Any], switches: Dict[str, str] ) -> Dict[str, Any]:
    """
    Assemble the report: provenance, the figures, and the phases with nothing to re-score.

    Requires:
        - per_ask is load_per_ask's result; answers is read_answers' result; run_facts holds the scored sha, the command and the time

    Ensures:
        - carries the scored sha, the per-ask files' shas, the cohort shas, the switch states, the denominators and PHASES_NOT_STORED
        - any context arm whose paired sign reverses is listed under reversals, as a finding and not an action
    """
    result    = rescore( per_ask[ "records" ], answers )
    reversals = [ { "arm": arm, "against": name, "old": entry[ name ][ "old" ][ "difference" ], "new": entry[ name ][ "new" ][ "difference" ] }
                  for arm, entry in result[ "arms" ].items() for name in ( "vs_q", "vs_always_yes" ) if name in entry and entry[ name ][ "sign_reversed" ] ]
    return { "title": "One-time re-score of phase 6 under the complete-action measure", "run": run_facts, "per_ask_files": per_ask[ "files" ],
             "switches": switches, "judge": "none; a free-text condition that needs the judge is undecided", "model_calls": 0,
             "result": result, "reversals": reversals, "phases_without_stored_forecasts": { phase: f"{NOT_STORED}: {why}" for phase, why in PHASES_NOT_STORED.items() } }


def render_markdown( report: Dict[str, Any] ) -> str:
    """
    Lay the report out as Markdown: provenance, tables, reversals, unscored phases.

    Requires:
        - report is build_report's result

    Ensures:
        - every figure carries its decided coverage beside it
    """
    run   = report[ "run" ]
    lines = [ f"# {report[ 'title' ]}", "", f"- scored sha: {run[ 'code_sha' ]}", f"- generated: {run[ 'started' ]}", f"- command: `{run[ 'command' ]}`", f"- model calls: {report[ 'model_calls' ]}; judge: {report[ 'judge' ]}", "",
              "## Cohort", "" ]
    for arm, info in report[ "per_ask_files" ].items(): lines.append( f"- {arm}: {info[ 'ids_count' ]} frozen ids (sha256 {info[ 'ids_sha256' ]}), scored on code {info[ 'code_sha' ][ :9 ]}, file sha256 {info[ 'sha256' ]}" )
    lines += [ "", "## Switches", "" ] + [ f"- {key}: {value}" for key, value in sorted( report[ "switches" ].items() ) ]
    lines += [ "", "## Old and new, by arm", "", "| arm | type | asks | old correct | new passed | decided | undecided | coverage |", "|---|---|---|---|---|---|---|---|" ]
    for arm, entry in report[ "result" ][ "arms" ].items():
        for kind, cell in [ ( "all", entry[ "all" ] ) ] + list( entry[ "by_type" ].items() ):
            lines.append( f"| {arm} | {kind} | {cell[ 'asks' ]} | {cell[ 'old_correct' ]} | {cell[ 'new_passed' ]} | {cell[ 'decided' ]} | {cell[ 'undecided' ]} | {cell[ 'coverage' ]:.3f} |" )
    lines += [ "", "## Paired differences (arm only minus other only)", "", "| arm | against | old n | old diff | old p | new n (decided in both) | new diff | new p | sign reversed |", "|---|---|---|---|---|---|---|---|---|" ]
    for arm, entry in report[ "result" ][ "arms" ].items():
        for name in ( "vs_q", "vs_always_yes" ):
            if name in entry:
                o, n = entry[ name ][ "old" ], entry[ name ][ "new" ]
                lines.append( f"| {arm} | {name} | {o[ 'n' ]} | {o[ 'difference' ]} | {o[ 'p_value' ]:.4f} | {n[ 'n' ]} | {n[ 'difference' ]} | {n[ 'p_value' ]:.4f} | {entry[ name ][ 'sign_reversed' ]} |" )
    lines += [ "", "## Sign reversals (a finding, not acted on)", "", *( [ f"- {r[ 'arm' ]} {r[ 'against' ]}: old {r[ 'old' ]}, new {r[ 'new' ]}" for r in report[ "reversals" ] ] or [ "- none" ] ) ]
    lines += [ "", "## Phases with nothing to re-score", "" ] + [ f"- {phase}: {why}" for phase, why in report[ "phases_without_stored_forecasts" ].items() ]
    return "\n".join( lines ) + "\n"


def main( argv: Optional[Sequence[str]] = None, printer: Callable = print, session_factory: Optional[Callable] = None, code_sha: Optional[str] = None, clock: Optional[Callable] = None ) -> int:
    """
    Run the one-time re-score and write its report beside a JSON copy.

    Requires:
        - argv holds --per-ask-dir and --out-dir; --out-dir is under io/write-ups/online-preference-learning/, never src/rnd
        - the factories and code_sha are injected by tests and default to the real ones

    Ensures:
        - reads the answers read-only, scores, and writes only <out-dir>/2026.11.23-one-time-rescore.{md,json}
        - writes no checkpoint file and makes no model call
        - returns 0 after the report is written

    Raises:
        - ValueError when --out-dir is under src/rnd
    """
    parser = argparse.ArgumentParser( description="Re-score the five context arms' stored forecasts under the complete-action measure." )
    parser.add_argument( "--per-ask-dir", required=True )
    parser.add_argument( "--out-dir", required=True )
    args = parser.parse_args( argv )
    if "/src/rnd" in args.out_dir or "/src/cosa/rnd" in args.out_dir: raise ValueError( "the report goes under io/write-ups, never src/rnd" )
    command = "python -m cosa.research.preference_replay.one_time_rescore " + " ".join( list( argv ) if argv is not None else sys.argv[ 1: ] )
    run     = { "command": command, "code_sha": code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" ),
                "started": ( clock or ( lambda: datetime.now( timezone.utc ) ) )().isoformat() }
    per_ask = load_per_ask( args.per_ask_dir )
    with ( session_factory or get_db )() as session: answers = read_answers( session )
    report  = build_report( per_ask, answers, run, read_switches( cu.get_project_root() + "/src/conf/lupin-app.ini" ) )
    stem    = f"{args.out_dir}/2026.11.23-one-time-rescore"
    write_json_atomic( f"{stem}.json", report, indent=2, trailing_newline=True, sort_keys=True )
    with open( f"{stem}.md", "w", encoding="utf-8" ) as handle: handle.write( render_markdown( report ) )
    printer( f"wrote {stem}.md and {stem}.json" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
