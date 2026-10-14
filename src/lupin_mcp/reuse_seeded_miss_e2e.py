"""
The seeded-miss end-to-end run: seed a miss, repair the page, prove it by replay.

A throwaway repository holds five public functions and two capability pages.
The question is "read the articles of an RSS feed".
The wrong page is chosen and decides alone, so the right symbol is never asked.
That is the seeded miss, and its receipt takes the page route.
The run records the miss as a store row and rewrites the right page's index line.
It replays the receipt five times before and five times after, each repeat its own draw.
A second miss, from a full-sweep receipt, must be refused: no summary rewrite can repair it.

Modes:
    dry (default)  a stand-in Jev answers from word overlap.
                   `--answers DIR` instead replays the `jev-cache` folder of an earlier run.
                   It refuses any request that folder does not hold.
                   There is no HTTP, key or ledger, and the store is an in-memory stand-in.
    --live         asks the real Jev through the account ledger.
                   The key is read from JEV_API_TOASTER.
                   Needs --ledger and --ceiling.
                   Add --store live to write the rows to the task store.

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
from cosa.repo.symindex.repair_check import PAGE_ROUTES, R, REPAIRED, UnrepairableReceipt, replayer_over, run_repair_check
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

CAUGHT_BY      = "seeded-miss-e2e"
PACK_SIZE      = 10
NEED_PAGE      = "read the articles of an RSS feed"
SYMBOL_PAGE    = "cosa.feeds.parse_feed"
NEED_FULL      = "list the episodes of a podcast"
SYMBOL_FULL    = "cosa.feeds.episodes"
WRONG_PAGE     = "news-page"
RIGHT_PAGE     = "feeds-page"
WRONG_LINE     = "reading articles from any source, news or feed items. `cosa` (newsx)"
TERSE_LINE     = "plumbing helpers. `cosa` (feeds)"
REPAIRED_LINE  = "reading RSS feeds and returning their articles. `cosa` (feeds)"
FILES          = { "src/cosa/newsx.py"      : 'def read_articles( source ):\n    """Read articles from a news source."""\n    return []\n',
                   "src/cosa/feeds.py"      : 'def parse_feed( url ):\n    """Parse an RSS feed into Article objects."""\n    return []\n\n\n'
                                              'def episodes( url ):\n    """Return the items."""\n    return []\n',
                   "src/lupin_mcp/tool.py"  : 'def serve():\n    """Serve the tools."""\n    return 1\n' }
PINS           = { WRONG_PAGE: "cosa.newsx.read_articles@aaaaaaaaaa", RIGHT_PAGE: "cosa.feeds.parse_feed@bbbbbbbbbb" }
STOP_WORDS     = frozenset( ( "the", "and", "for", "its", "with", "that", "this", "from", "are", "was" ) )
RELEVANT       = { "reuse": 0.95, "extend": 0.03, "unrelated": 0.02 }
UNRELATED      = { "reuse": 0.02, "extend": 0.03, "unrelated": 0.95 }
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


def make_context( root, data, out, transport=None, ceiling=None, run_name=None, ledger=None ):
    """Ensures: returns a packed ReuseContext; with no transport the live one is built later."""
    return rt.ReuseContext( root, data, out_dir=out, transport=transport, sweeper=rp.packed_sweeper( PACK_SIZE ), request_shape=rp.SHAPE, pack_size=PACK_SIZE,
                            token_ceiling=ceiling, run_name=run_name, ledger=ledger )


def seed_cache( answers, data ):
    """
    Copy a saved jev-cache folder into a run's data folder.

    Requires:
        - answers is a folder that exists

    Raises:
        - RunRefused when it does not
    """
    if not pathlib.Path( answers ).is_dir(): raise RunRefused( f"--answers {answers} is not a folder" )
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


def page_scenario( ctx, root, librarian, store, runs ):
    """
    Seed, detect, repair and verify a miss from a page-route receipt.

    Ensures:
        - returns a report dict; "ok" is True only when the receipt took a page route and lacked the symbol,
          the repair check gave its fixed verdict with no hit before and every run a hit after, and every replay's
          stored receipt took a page route
        - the right page's index line is rewritten only inside the repair check, after a clean before-phase
    """
    seed   = rt.page_route_need_impl( NEED_PAGE, None, ctx )
    report = { "need": NEED_PAGE, "symbol": SYMBOL_PAGE, "status": seed[ "status" ], "ok": False }
    if seed[ "status" ] != "ok": return { **report, "reason": f"seed ask failed: {seed.get( 'error' )}" }
    rid = seed[ "receipt_id" ]
    receipt = json.loads( next( ( pathlib.Path( ctx.data ) / "receipts" ).glob( f"{rid}*.json" ) ).read_text( encoding="utf-8" ) )
    report.update( { "receipt_id": rid, "route": receipt[ "route" ], "shortlist_before": shortlist_of( seed ) } )
    if receipt[ "route" ] not in PAGE_ROUTES or SYMBOL_PAGE in report[ "shortlist_before" ]:
        return { **report, "reason": "the seed did not produce a page-route miss" }
    title, outcome = record_miss( librarian, store, rid, SYMBOL_PAGE, NEED_PAGE )
    report[ "row" ] = { "title": title, "outcome": outcome }
    routes = []

    def replay_tool( receipt_id, repeat ):
        result = rt.replay_impl( receipt_id, ctx, repeat=repeat )
        if result[ "status" ] == "ok": routes.append( result[ "stored" ][ "route" ] )
        return result

    check = run_repair_check( replayer_over( replay_tool ), lambda: write_index( root, REPAIRED_LINE ), rid, SYMBOL_PAGE, runs=runs )
    report[ "repair" ] = { "verdict": check.verdict, "before": check.before, "after": check.after, "runs": check.runs, "replay_routes": sorted( set( routes ) ) }
    if check.verdict != REPAIRED or check.before != 0 or check.after != runs or not set( routes ) <= set( PAGE_ROUTES ):
        return { **report, "reason": f"repair check gave {check.verdict}" }
    report[ "row" ][ "repaired_noted" ] = mark_repaired( store, title, rid, SYMBOL_PAGE )
    report[ "ok" ] = outcome == "created" and report[ "row" ][ "repaired_noted" ]
    return report


def full_scenario( ctx, librarian, store, runs ):
    """
    Detect a miss from a full-sweep receipt and show that the repair check refuses it.

    Ensures:
        - returns a report dict; "ok" is True only when the receipt took the full route without the symbol and
          the repair check raised UnrepairableReceipt, so no rewrite was made
    """
    seed   = rt.sweep_need_impl( NEED_FULL, None, ctx )
    report = { "need": NEED_FULL, "symbol": SYMBOL_FULL, "status": seed[ "status" ], "ok": False }
    if seed[ "status" ] != "ok": return { **report, "reason": f"seed ask failed: {seed.get( 'error' )}" }
    rid = seed[ "receipt_id" ]
    receipt = json.loads( next( ( pathlib.Path( ctx.data ) / "receipts" ).glob( f"{rid}*.json" ) ).read_text( encoding="utf-8" ) )
    report.update( { "receipt_id": rid, "route": receipt[ "route" ], "shortlist_before": shortlist_of( seed ) } )
    if receipt[ "route" ] != "full" or SYMBOL_FULL in report[ "shortlist_before" ]:
        return { **report, "reason": "the seed did not produce a full-sweep miss" }
    title, outcome = record_miss( librarian, store, rid, SYMBOL_FULL, NEED_FULL )
    report[ "row" ] = { "title": title, "outcome": outcome }
    rewrites = []
    try:
        run_repair_check( replayer_over( lambda receipt_id, repeat: rt.replay_impl( receipt_id, ctx, repeat=repeat ) ), lambda: rewrites.append( 1 ), rid, SYMBOL_FULL, runs=runs )
    except UnrepairableReceipt as error:
        report[ "repair" ] = { "verdict": "UNREPAIRABLE", "reason": str( error ), "rewrites": len( rewrites ) }
        report[ "ok" ] = not rewrites and outcome == "created"
        return report
    return { **report, "reason": "the repair check accepted a full-sweep receipt" }


def run( work, mode, answers=None, ceiling=None, ledger_path=None, store_kind="fake", runs=R, environ=None, log=print ):
    """
    Run both scenarios and write the report and the misses file.

    Requires:
        - work is an empty or absent folder; mode is "dry" or "live"
        - live needs ceiling and ledger_path, and the key in the environment

    Ensures:
        - returns ( exit_code, report ); 0 when both scenarios held and the exported misses read as expected
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
    if store_kind not in ( "fake", "live" ): raise RunRefused( f"--store must be fake or live, got {store_kind!r}" )
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
    if store_kind == "live":
        store = _live_store()
        if mode != "live": raise RunRefused( "--store live is for a live run" )
    else:
        store = FakeStore()
    librarian = Librarian( store, str( work / "pending.jsonl" ), log )
    try:
        page   = page_scenario( ctx, root, librarian, store, runs )
        full   = full_scenario( ctx, librarian, store, runs )
    finally:
        if mode == "live" and ctx.transport is not None: ctx.transport.budget.end()
    if isinstance( stand_in, NoCallTransport ) and stand_in.refused:
        raise SavedAnswerMissing( f"{len( stand_in.refused )} requests were not in the saved answers; first need: {stand_in.refused[ 0 ]!r}" )
    export = miss_record.export_report( store.query_all( CORRELATION_KEY )[ 2 ][ "tasks" ], str( work / "misses.jsonl" ), allow_empty=True )
    exported = { m[ "symbol" ]: m[ "repaired" ] for m in miss_record.collect( store.query_all( CORRELATION_KEY )[ 2 ][ "tasks" ] ) }
    expected = { SYMBOL_PAGE: True, SYMBOL_FULL: False }
    report   = { "mode": mode if mode == "live" else ( "dry-saved" if answers is not None else "dry-stand-in" ), "store": store_kind, "runs": runs,
                 "page": page, "full": full, "exported": exported, "exported_skipped": export.skipped,
                 "calls": stand_in.calls if stand_in is not None else None }
    report[ "ok" ] = bool( page[ "ok" ] and full[ "ok" ] and exported == expected and not export.skipped )
    ( work / "report.json" ).write_text( json.dumps( report, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    return ( 0 if report[ "ok" ] else 1 ), report


def _live_store():
    """Ensures: returns the live task-store adapter, built from the client settings."""
    from cosa.repo.symindex.librarian_tick import LiveStore
    from lupin_cli.claude_code.hooks.lib import task_store_client as client
    from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
    return LiveStore( load_task_store_settings(), client.read_api_key(), client )


def summary_lines( report ):
    """Ensures: returns a short table of the report as text lines."""
    page, full = report[ "page" ], report[ "full" ]
    rows = [ f"mode {report[ 'mode' ]}  store {report[ 'store' ]}  calls {report[ 'calls' ]}",
             f"page  route {page.get( 'route' )}  before {page.get( 'shortlist_before' )}  repair {page.get( 'repair' )}  ok {page[ 'ok' ]}",
             f"full  route {full.get( 'route' )}  before {full.get( 'shortlist_before' )}  repair {full.get( 'repair' )}  ok {full[ 'ok' ]}",
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
