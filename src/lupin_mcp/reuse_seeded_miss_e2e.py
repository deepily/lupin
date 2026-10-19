"""
The seeded-miss end-to-end run: seed a miss, repair a docstring, prove it by replay.

A throwaway repository holds five public functions and two capability pages.
The question is "list the episodes of a podcast".
The lookup runs the candidate stage and then Jev, and the symbol's own docstring does not match the need, so it is missed.
The stage here is a stand-in that returns every entry, as the real one does when the index is smaller than K.
The run records the miss as a store row and replays the receipt five times before and five times after, each repeat its own draw.
A rewrite that changes nothing must return `NO_INPUT_CHANGE`.
Rewriting the missed symbol's first docstring line must reach `REPAIRED`.
The page route this run once seeded a second miss on is gone, so the pages no longer decide anything.

What this run does not prove:
    The miss row is made by the script, not by a seat that was missed.
    The rewrite is made by the script, not by the librarian.
    The stand-in is deterministic, so five repeats show the plumbing and not the model's flip rate.
    A live run shows the same plumbing against real answers, on a five-function sandbox.

Modes:
    dry (default)  a stand-in Jev answers from word overlap.
                   `--answers DIR` instead replays the `jev-cache` folder of an earlier run.
                   It refuses any request that folder does not hold.
                   There is no HTTP, key or ledger, and the store is an in-memory stand-in.
    --live         asks the real Jev through the account ledger.
                   The key is read from JEV_API_TOASTER.
                   Needs --ledger and --ceiling.
                   The rows always go to an in-memory store; --store live is refused.

Exit 0 means every expectation held.
Exit 1 means one failed.
Exit 2 means the run was refused before anything ran.
"""
import argparse
import ast
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading

from cosa.repo.doc_lint import jev_transport
from cosa.repo.symindex import miss_record
from cosa.repo.symindex.librarian_queue import CORRELATION_KEY, MISS_PREFIX, Librarian
from cosa.repo.symindex.repair_check import NO_INPUT_CHANGE, R, REPAIRED, replayer_over, run_repair_check
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

CAUGHT_BY      = "seeded-miss-e2e"
PACK_SIZE      = 10
NEED_MISS      = "list the episodes of a podcast"
SYMBOL_MISS    = "cosa.fetchers.pull"
WRONG_PAGE     = "news-page"
RIGHT_PAGE     = "fetchers-page"
WRONG_LINE     = "reading articles from any source, news or feed items. `cosa` (newsx)"
TERSE_LINE     = "thumbnail and image size helpers. `cosa` (fetchers)"
REPAIRED_LINE  = "reading RSS feeds and returning their articles. `cosa` (fetchers)"
FILES          = { "src/cosa/newsx.py"      : 'def read_articles( source ):\n    """Read articles from a news source."""\n    return []\n',
                   "src/cosa/fetchers.py"   : 'def parse_feed( url ):\n    """Parse an RSS feed into Article objects."""\n    return []\n\n\n'
                                              'def pull( url ):\n    """Return the checksum of the payload."""\n    return []\n',
                   "src/lupin_mcp/tool.py"  : 'def serve():\n    """Serve the tools."""\n    return 1\n' }
OLD_DOC        = '"""Return the checksum of the payload."""'
NEW_DOC        = '"""List the episodes of a podcast."""'
PINS           = { WRONG_PAGE: "cosa.newsx.read_articles@aaaaaaaaaa", RIGHT_PAGE: "cosa.fetchers.parse_feed@bbbbbbbbbb" }
STOP_WORDS     = frozenset( ( "the", "and", "for", "its", "with", "that", "this", "from", "are", "was" ) )
RELEVANT       = { "reuse": 0.95, "extend": 0.03, "unrelated": 0.02 }
UNRELATED      = { "reuse": 0.02, "extend": 0.03, "unrelated": 0.95 }
MAX_ANSWERS_BYTES = 256 * 1024 * 1024
CANDIDATE_AT   = "the candidate "


class SavedAnswerMissing( RuntimeError ):
    """A request the saved answers do not hold, so the dry run stops."""


class RunRefused( RuntimeError ):
    """The run cannot start; nothing was created or sent."""


def words( text ):
    """Ensures: returns the lower-case words of three or more characters, without stop words."""
    return { w for w in re.findall( r"[a-z0-9]+", text.lower() ) if len( w ) >= 3 and w not in STOP_WORDS }


def candidate_of( instructions ):
    """
    Read the candidate text back out of one packed question's instructions.

    Requires:
        - instructions is the string pack_request built, holding "the candidate " and then the repr of the text

    Ensures:
        - returns the entry or page text, whole, whatever words follow the quoted text
        - returns None when the instructions hold no candidate
    """
    start = instructions.find( CANDIDATE_AT )
    if start < 0: return None
    begin = start + len( CANDIDATE_AT )
    quote = instructions[ begin ]
    end   = begin + 1
    while instructions[ end ] != quote:
        end += 2 if instructions[ end ] == "\\" else 1
    return ast.literal_eval( instructions[ begin:end + 1 ] )


def answer_for( need, text ):
    """Ensures: returns the relevant answer at half the need's words, else the unrelated one."""
    mine = words( need )
    return RELEVANT if mine and len( mine & words( text ) ) / len( mine ) >= 0.5 else UNRELATED


class StandInJev:
    """
    A transport that answers a packed body from the words the need and a candidate share.

    Ensures:
        - an answer depends on the need and the candidate text, so a changed page line changes it
        - bodies holds every body it was sent, and calls counts them
    Raises:
        - AssertionError for a question that holds no candidate
    """

    def __init__( self ):
        self.bodies = []
        self.lock   = threading.Lock()

    @property
    def calls( self ):
        """Ensures: returns the number of bodies sent."""
        return len( self.bodies )

    def post_with_meta( self, body ):
        """Ensures: returns ( response, meta ) as the live transport does."""
        with self.lock: self.bodies.append( body )
        need, answers = body[ "state" ][ "need" ], {}
        for key, question in body[ "questions" ].items():
            text = candidate_of( question[ "instructions" ] )
            assert text is not None, f"question {key!r} holds no candidate"
            answers[ key ] = { "probabilities": answer_for( need, text ) }
        return ( { "answers": answers, "model": body[ "model" ], "usage": { "input_tokens": 100, "output_tokens": 20 } },
                 { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 } )


class NoCallTransport:
    """
    The transport of a run on saved answers; a request that reaches it was not saved.

    Ensures:
        - every post is refused and its need is kept in refused, because the sweep treats a raised error as a failed call
        - calls is 0, as no HTTP is made
    Raises:
        - SavedAnswerMissing on every post, naming the need
    """

    calls = 0

    def __init__( self ):
        self.refused = []
        self.lock    = threading.Lock()

    def post_with_meta( self, body ):
        """Raises: SavedAnswerMissing always."""
        with self.lock: self.refused.append( body[ "state" ][ "need" ] )
        raise SavedAnswerMissing( f"the saved answers do not hold a request for need {body[ 'state' ][ 'need' ]!r}" )


class FakeStore:
    """
    An in-memory store with the three calls the librarian makes.

    Ensures:
        - create gives each row an id and an increasing updated_ts; amend appends the note to the body and moves updated_ts on
        - query returns every row, so a held or parked state never hides one
    """

    def __init__( self ):
        self.rows  = []
        self.clock = datetime.datetime( 2026, 10, 14, 12, 0, 0, tzinfo=datetime.timezone.utc )

    def _tick( self ):
        self.clock += datetime.timedelta( seconds=1 )
        return self.clock.isoformat()

    def query( self, correlation_key ):
        """Ensures: returns ( True, 200, { tasks } ) with every row."""
        return True, 200, { "tasks": [ dict( r ) for r in self.rows ] }

    def query_all( self, correlation_key ):
        """Ensures: returns the same rows as query."""
        return self.query( correlation_key )

    def create( self, payload ):
        """Ensures: stores one row from the payload and returns ( True, 201, row )."""
        row = { "id": f"fake-{len( self.rows ) + 1}", "title": payload[ "title" ], "body": payload[ "body" ], "status": "queued", "updated_ts": self._tick() }
        self.rows.append( row )
        return True, 201, dict( row )

    def amend( self, item_id, note ):
        """Ensures: appends the note to the row's body and returns ( True, 200, {} )."""
        row = next( r for r in self.rows if r[ "id" ] == item_id )
        row[ "body" ] += "\n\n[amendment]\n" + note
        row[ "updated_ts" ] = self._tick()
        return True, 200, {}


def build_sandbox( work ):
    """
    Write the throwaway repository and its wiki under work/sandbox.

    Ensures:
        - returns the repository root
        - the wrong page's line matches the need and the right page's line does not
    """
    root = pathlib.Path( work ) / "sandbox"
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    wiki = root / "src" / "docs" / "wiki"
    ( wiki / "capabilities" ).mkdir( parents=True, exist_ok=True )
    write_index( root, TERSE_LINE )
    for slug, pin in PINS.items():
        ( wiki / "capabilities" / f"{slug}.md" ).write_text( f"---\ncapability: {slug}\npins:\n  - {pin}\n---\n# {slug}\n", encoding="utf-8" )
    return root


def write_index( root, right_line ):
    """Ensures: writes the wiki index with the right page's line as given."""
    text = f"- [[{WRONG_PAGE}]] — {WRONG_LINE}\n- [[{RIGHT_PAGE}]] — {right_line}\n"
    ( pathlib.Path( root ) / "src" / "docs" / "wiki" / "INDEX.md" ).write_text( text, encoding="utf-8" )


def write_docstring( root ):
    """Ensures: rewrites the missed symbol's first docstring line to hold the need's words."""
    path = pathlib.Path( root ) / "src" / "cosa" / "fetchers.py"
    text = path.read_text( encoding="utf-8" )
    path.write_text( text.replace( OLD_DOC, NEW_DOC ), encoding="utf-8" )


class StandInStage:
    """The candidate stage's interface, answering every entry but the excluded one, sorted by id."""

    arm, K = "B2w", 128

    def manifest( self ): return { "manifest_hash": "0" * 64 }

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None, index_manifest=None, K=None ):
        """Ensures: returns every id but exclude_id, reporting K when it is given."""
        ids = sorted( e[ "id" ] for e in entries if e[ "id" ] != exclude_id )
        return { "ids": ids, "ranking": ids, "lists": { "stand-in": { "size": len( ids ), "head": ids[ :20 ] } }, "manifest_hash": "0" * 64,
                 "embed_models": { "code": "stand-in", "prose": "stand-in" }, "arm": self.arm, "K": self.K if K is None else K, "widened": False, "stage_key": "0" * 32,
                 "wiki": 0, "wiki_ids": [], "ranking_hash": "0" * 64 }


def make_context( root, data, out, transport=None, ceiling=None, run_name=None, ledger=None ):
    """Ensures: returns a packed context with the stand-in stage and the given transport."""
    return rt.ReuseContext( root, data, out_dir=out, transport=transport, sweeper=rp.packed_sweeper( PACK_SIZE, shape=rp.SHAPE_WHOLE ), request_shape=rp.SHAPE_WHOLE,
                            pack_size=PACK_SIZE, token_ceiling=ceiling, run_name=run_name, ledger=ledger, candidate_stage=StandInStage() )


def seed_cache( answers, data ):
    """
    Copy a saved jev-cache folder into a run's data folder.

    Requires:
        - answers is a folder that exists

    Ensures:
        - the size is summed file by file, and the walk stops at the first file that passes MAX_ANSWERS_BYTES
        - the folder is copied to data/jev-cache only after the check passes

    Raises:
        - RunRefused when it does not exist, or when it holds more than MAX_ANSWERS_BYTES
    """
    if not pathlib.Path( answers ).is_dir(): raise RunRefused( f"--answers {answers} is not a folder" )
    size = 0
    for f in pathlib.Path( answers ).rglob( "*" ):
        if not f.is_file(): continue
        size += f.stat().st_size
        if size > MAX_ANSWERS_BYTES:
            raise RunRefused( f"--answers {answers} holds more than {MAX_ANSWERS_BYTES} bytes; copy only the answers this run needs" )
    shutil.copytree( answers, pathlib.Path( data ) / "jev-cache" )


def shortlist_of( result ):
    """Ensures: returns the ids of a public result's shortlist."""
    return [ s[ "id" ] for s in result[ "shortlist" ] ]


def record_miss( librarian, store, receipt_id, symbol, need ):
    """
    Write one miss as a store row through the librarian.

    Ensures:
        - returns ( title, outcome ), outcome from Librarian.hold_or_create
        - the body carries the fenced miss block with repaired false
    """
    miss  = { "receipt_id": receipt_id, "symbol": symbol, "caught_by": CAUGHT_BY, "repaired": False }
    title = MISS_PREFIX + symbol
    body  = f"Seeded miss: {symbol} was not on the shortlist for the need {need!r}.\n\n" + miss_record.render_block( miss )
    return title, librarian.hold_or_create( title, body )


def mark_repaired( store, title, receipt_id, symbol ):
    """Ensures: amends the miss row with a repaired block; returns True when the store took it."""
    row  = next( r for r in store.query( CORRELATION_KEY )[ 2 ][ "tasks" ] if r[ "title" ] == title )
    note = "Repair verified by replay.\n\n" + miss_record.render_block( { "receipt_id": receipt_id, "symbol": symbol, "caught_by": CAUGHT_BY, "repaired": True } )
    return store.amend( row[ "id" ], note )[ 0 ]


def candidate_scenario( ctx, root, librarian, store, runs ):
    """
    Detect a miss from a candidate-route receipt and repair the symbol's docstring.

    Ensures:
        - returns a report dict; "ok" is True only when the receipt took the candidates route without the symbol,
          a rewrite that changed nothing returned `NO_INPUT_CHANGE`, and a rewrite of the symbol's first
          docstring line returned `REPAIRED` with no hit before and every run a hit after
        - the second check takes new draws, so it does not read the first check's cached answers
    """
    seed   = rt.check_exists_impl( NEED_MISS, ctx )
    report = { "need": NEED_MISS, "symbol": SYMBOL_MISS, "status": seed[ "status" ], "ok": False }
    if seed[ "status" ] != "ok": return { **report, "reason": f"seed ask failed: {seed.get( 'error' )}" }
    rid = seed[ "receipt_id" ]
    receipt = json.loads( next( ( pathlib.Path( ctx.data ) / "receipts" ).glob( f"{rid}*.json" ) ).read_text( encoding="utf-8" ) )
    report.update( { "receipt_id": rid, "route": receipt[ "route" ], "shortlist_before": shortlist_of( seed ) } )
    counts = receipt[ "candidate_stage" ] if "candidate_stage" in receipt else None
    report[ "entries" ] = None if counts is None else { k: counts[ k ] for k in ( "entries_total", "entries_asked", "entries_not_asked" ) }
    if counts is None or counts[ "entries_asked" ] + counts[ "entries_not_asked" ] != counts[ "entries_total" ]:
        return { **report, "reason": "the receipt's entry counts do not add up" }
    if receipt[ "route" ] != "candidates" or SYMBOL_MISS in report[ "shortlist_before" ]:
        return { **report, "reason": "the seed did not produce a candidate-route miss" }
    title, outcome = record_miss( librarian, store, rid, SYMBOL_MISS, NEED_MISS )
    report[ "row" ] = { "title": title, "outcome": outcome }

    def replay_tool( receipt_id, repeat ): return rt.replay_impl( receipt_id, ctx, repeat=repeat )

    same = run_repair_check( replayer_over( replay_tool, first_repeat=1 ), lambda: None, rid, SYMBOL_MISS, runs=runs )
    real = run_repair_check( replayer_over( replay_tool, first_repeat=runs + 2 ), lambda: write_docstring( root ), rid, SYMBOL_MISS, runs=runs )
    report[ "repair" ] = { "no_change": { "verdict": same.verdict, "before": same.before, "after": same.after },
                           "docstring": { "verdict": real.verdict, "before": real.before, "after": real.after, "runs": real.runs } }
    if same.verdict != NO_INPUT_CHANGE or real.verdict != REPAIRED or real.before != 0 or real.after != runs:
        return { **report, "reason": f"checks gave {same.verdict} and {real.verdict}" }
    report[ "row" ][ "repaired_noted" ] = mark_repaired( store, title, rid, SYMBOL_MISS )
    report[ "ok" ] = outcome == "created" and report[ "row" ][ "repaired_noted" ]
    return report


def run( work, mode, answers=None, ceiling=None, ledger_path=None, store_kind="fake", runs=R, environ=None, log=print ):
    """
    Run the candidate-route scenario and write the report and the misses file.

    Requires:
        - work is an empty or absent folder; mode is "dry" or "live"
        - live needs ceiling and ledger_path, and the key in the environment

    Ensures:
        - returns ( exit_code, report ); 0 when the scenario held and the exported misses read as expected
        - the report is also written to work/report.json and the misses to work/misses.jsonl
        - calls is the count of stand-in requests, 0 on saved answers, and None for a live run
        - nothing outside work is written in dry mode, and a dry run makes no HTTP call
    Raises:
        - RunRefused for a work folder that is not empty, a live run without its ceiling, ledger or key, or a store kind that is not fake or live
        - SavedAnswerMissing when a run on saved answers asked for anything they did not hold
    """
    environ = os.environ if environ is None else environ
    work    = pathlib.Path( work )
    if work.exists() and any( work.iterdir() ): raise RunRefused( f"{work} is not empty; give a new --work folder" )
    if store_kind != "fake": raise RunRefused( f"--store {store_kind} is refused: the rows are synthetic rows and must not enter the real store" )
    if mode == "live":
        if ceiling is None or ledger_path is None: raise RunRefused( "a live run needs --ceiling and --ledger" )
        if not jev_transport.has_key(): raise RunRefused( f"{jev_transport.KEY_VARIABLE} is not set; nothing was created" )
        if answers is not None: raise RunRefused( "--answers is for a dry run" )
    work.mkdir( parents=True, exist_ok=True )
    root, data, out = build_sandbox( work ), work / "data", work / "out"
    if answers is not None: seed_cache( answers, data )
    stand_in = None
    if mode == "live":
        from lupin_mcp import reuse_ledger
        ctx = make_context( root, data, out, ceiling=ceiling, run_name=f"seeded-miss-{work.name}", ledger=reuse_ledger.AccountLedger( ledger_path ) )
    else:
        stand_in = NoCallTransport() if answers is not None else StandInJev()
        ctx      = make_context( root, data, out, transport=stand_in )
    store     = FakeStore()
    librarian = Librarian( store, str( work / "pending.jsonl" ), log )
    try:
        found  = candidate_scenario( ctx, root, librarian, store, runs )
    finally:
        if mode == "live" and ctx.transport is not None: ctx.transport.budget.end()
    if isinstance( stand_in, NoCallTransport ) and stand_in.refused:
        raise SavedAnswerMissing( f"{len( stand_in.refused )} requests were not in the saved answers; first need: {stand_in.refused[ 0 ]!r}" )
    export = miss_record.export_report( store.query_all( CORRELATION_KEY )[ 2 ][ "tasks" ], str( work / "misses.jsonl" ), allow_empty=True )
    exported = { m[ "symbol" ]: m[ "repaired" ] for m in miss_record.collect( store.query_all( CORRELATION_KEY )[ 2 ][ "tasks" ] ) }
    expected = { SYMBOL_MISS: True }
    report   = { "mode": mode if mode == "live" else ( "dry-saved" if answers is not None else "dry-stand-in" ), "store": store_kind, "runs": runs,
                 "candidates": found, "exported": exported, "exported_skipped": export.skipped,
                 "calls": stand_in.calls if stand_in is not None else None }
    report[ "ok" ] = bool( found[ "ok" ] and exported == expected and not export.skipped )
    ( work / "report.json" ).write_text( json.dumps( report, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    return ( 0 if report[ "ok" ] else 1 ), report


def summary_lines( report ):
    """Ensures: returns a short table of the report as text lines."""
    found = report[ "candidates" ]
    rows = [ f"mode {report[ 'mode' ]}  store {report[ 'store' ]}  calls {report[ 'calls' ]}",
             f"candidates  route {found.get( 'route' )}  before {found.get( 'shortlist_before' )}  repair {found.get( 'repair' )}  ok {found[ 'ok' ]}",
             f"exported {report[ 'exported' ]}  overall {'PASS' if report[ 'ok' ] else 'FAIL'}" ]
    return rows


def main( argv=None, out=None, err=None, environ=None ):
    """
    Run the command line.

    Ensures:
        - returns run()'s exit code, or 2 for a refusal, which prints one line to err
    """
    out, err = sys.stdout if out is None else out, sys.stderr if err is None else err
    parser = argparse.ArgumentParser( prog="python -m lupin_mcp.reuse_seeded_miss_e2e", description=__doc__.split( "\n\n" )[ 0 ] )
    parser.add_argument( "--work", help="a new folder for the sandbox, data and report; default is a temporary folder" )
    parser.add_argument( "--live", action="store_true" )
    parser.add_argument( "--answers", help="a jev-cache folder from an earlier run; a dry run answers from it and refuses anything else" )
    parser.add_argument( "--ceiling", type=int )
    parser.add_argument( "--ledger" )
    parser.add_argument( "--store", default="fake", choices=( "fake", "live" ) )
    parser.add_argument( "--runs", type=int, default=R )
    args = parser.parse_args( argv )
    work = args.work or tempfile.mkdtemp( prefix="seeded-miss-" )
    if args.work is None: shutil.rmtree( work )
    try:
        code, report = run( work, "live" if args.live else "dry", args.answers, args.ceiling, args.ledger, args.store, args.runs, environ )
    except ( RunRefused, SavedAnswerMissing ) as error:
        print( f"seeded-miss-e2e: {error}", file=err )
        return 2
    print( "\n".join( summary_lines( report ) ), file=out )
    print( f"report: {pathlib.Path( work ) / 'report.json'}", file=out )
    return code


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
