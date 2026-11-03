"""
The daily duplicate check table of the weekly fleet page.

Every run is a real file in a temporary folder, written under the name the check gives its own: <date>-<time>-<trigger>.json.
The two small failed runs are copies of files the check wrote earlier; the others carry the same fields.
Verdicts come from a store client that answers in the shape of the real task store, amendment text included.
Nothing here calls a model or touches the shared data folder.
"""
import datetime
import io
import json

import pytest

from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_filing as ff
from lupin_mcp import reuse_behaviour as rb

UTC  = datetime.timezone.utc
WEEK = rb.week_of( "2026-11-08" )

REAL_PREREQUISITE_FAILURE = '{\n "cap": 100,\n "date": "2026-11-03",\n "detail": "the binary None reports no version",\n "elapsed_seconds": 0.4,\n "judge_calls": 0,\n "prerequisite": "claude_binary",\n "status": "failed",\n "trigger": "hand"\n}'
REAL_JUDGING_FAILURE      = ( '{"cap": 100, "date": "2026-11-02", "elapsed_seconds": 2764.735, "error": "DuplicateCheckError: BLINDNESS_BREACH: scrub tokens survive in text bound for the judge",'
                              ' "judge_calls": 100, "stage": "judging", "status": "failed", "trigger": "hand", "window": {"commits": 3, "end": "b", "start": "a"}}' )


def amendment( word, who="john 3e68f540", reason="because." ):
    """Ensures: returns an amendment as the store appends it to a row body."""
    return f"\n\n[amendment · {who} · 2026-11-03T20:39:43.740140+00:00]\nVERDICT {word} (John, 3 Nov). {reason}"


class RowClient:
    """A task-store client that answers a key with seeded rows and records each ask."""

    def __init__( self, bodies, ok=True ):
        self.bodies = bodies
        self.asked  = []
        self.ok     = ok

    def query_by_correlation_key( self, settings, api_key, key, every_state=False ):
        self.asked.append( ( key, every_state ) )
        rows = [ { "body": b, "correlation_key": key } for b in self.bodies.get( key, [] ) ]
        return self.ok, 200 if self.ok else 500, { "tasks": rows, "count": len( rows ) }


def live( bodies, ok=True ):
    """Ensures: returns the real LiveStore over a RowClient."""
    store        = ff.LiveStore( settings={ "api_base_url": "http://x" }, api_key="k" )
    store.client = RowClient( bodies, ok )
    return store


def finding( key, verdict=None ):
    return { "id": f"d-{key}", "name": "n", "correlation_key": f"epic:dupcheck-{key}" } | ( { "verdict": verdict } if verdict is not None else { } )


def write_run( folder, stamp, trigger, **fields ):
    """Ensures: writes a finished run's file, with any field overridden."""
    base = { "date": stamp[ :10 ], "trigger": trigger, "status": "carried", "judged": 0, "judge_calls": 0, "elapsed_seconds": 60.0, "findings": [ ] }
    ( folder / f"{stamp}-{trigger}.json" ).write_text( json.dumps( base | fields ), encoding="utf-8" )


@pytest.fixture
def folder( tmp_path ):
    """Ensures: a week of runs, one outside the week, and files that are not runs."""
    out = tmp_path / "duplicate-check-daily"
    out.mkdir()
    ( out / "2026-11-02-211352-hand.json" ).write_text( REAL_JUDGING_FAILURE, encoding="utf-8" )
    ( out / "2026-11-03-111106-hand.json" ).write_text( REAL_PREREQUISITE_FAILURE, encoding="utf-8" )
    write_run( out, "2026-11-03-111218", "hand", judged=100, judge_calls=100, elapsed_seconds=679.838,
               findings=[ finding( "a1" ), finding( "a2" ), finding( "a3", "extend" ), finding( "a4" ), finding( "a5", "maybe" ) ] )
    write_run( out, "2026-11-04-180000", "cron", judged=7, judge_calls=9, elapsed_seconds=90.0, findings=[ finding( "b1" ), finding( "b2" ) ] )
    write_run( out, "2026-10-20-180000", "cron", judged=50, judge_calls=50, elapsed_seconds=600.0, findings=[ finding( "old" ) ] )
    ( out / "last-success.json" ).write_text( '{"commit": "2713f32dbb4bf4c4a004770d77e50f9f4d0876dc"}', encoding="utf-8" )
    ( out / "notes.json" ).write_text( "not a run", encoding="utf-8" )
    return out


BODIES = { "epic:dupcheck-a1": [ "The daily check judged x." + amendment( "DUPLICATE" ) ],
           "epic:dupcheck-a2": [ "The daily check judged y." + amendment( "DUPLICATE" ) + amendment( "DISTINCT" ) ],
           "epic:dupcheck-a4": [ "The daily check judged z." ],
           "epic:dupcheck-b1": [ "The daily check judged w." + amendment( "DISTINCT" ) ],
           "epic:dupcheck-b2": [ "The daily check judged v." + amendment( "DISTINCT" ) ] }

HEAD = "| date | trigger | commits judged | judge calls | minutes | findings | real duplicates | not duplicates | no verdict yet | precision (real of ruled) |"


def cells( page, which ):
    """Ensures: returns one column of the table, total last."""
    lines = [ l for l in page.split( "Daily duplicate check\n\n", 1 )[ 1 ].split( "\n\n" )[ 0 ].splitlines() if l.startswith( "| " ) ]
    assert lines[ 0 ] == HEAD
    return [ [ c.strip() for c in l.strip( "|" ).split( "|" ) ][ which ] for l in lines[ 2: ] ]


def page_of( folder, bodies=None ):
    return rb.weekly_report( [], [], [], "2026-11-08", tz=UTC, check_dir=folder, store=live( BODIES if bodies is None else bodies ) )


COLUMNS = [ ( "date",           0, [ "2026-11-02", "2026-11-03", "2026-11-03", "2026-11-04", "total" ] ),
            ( "trigger",        1, [ "hand", "hand", "hand", "cron", "" ] ),
            ( "commits judged", 2, [ "0", "0", "100", "7", "107" ] ),
            ( "judge calls",    3, [ "100", "0", "100", "9", "209" ] ),
            ( "minutes",        4, [ "46.1", "0.0", "11.3", "1.5", "58.9" ] ),
            ( "findings",       5, [ "0", "0", "5", "2", "7" ] ),
            ( "real",           6, [ "0", "0", "2", "0", "2" ] ),
            ( "not",            7, [ "0", "0", "1", "2", "3" ] ),
            ( "no verdict yet", 8, [ "0", "0", "2", "0", "2" ] ),
            ( "precision",      9, [ "0/0 (n/a)", "0/0 (n/a)", "2/3 (66.7%, 20.8-93.9%)", "0/2 (0.0%, 0.0-65.8%)", "2/5 (40.0%, 11.8-76.9%)" ] ) ]


@pytest.mark.parametrize( "name, which, expected", COLUMNS, ids=[ c[ 0 ] for c in COLUMNS ] )
def test_column_( folder, name, which, expected ):
    assert cells( page_of( folder ), which ) == expected


def test_a_run_with_no_findings_stays_as_a_row_of_zeros_and_the_run_outside_the_week_and_the_files_that_are_not_runs_do_not_appear( folder ):
    page = page_of( folder )
    assert "| 2026-11-02 | hand | 0 | 100 | 46.1 | 0 | 0 | 0 | 0 | 0/0 (n/a) |" in page
    assert "2026-10-20" not in page and "last-success" not in page and len( cells( page, 0 ) ) == 5


def test_the_total_precision_is_taken_from_the_summed_counts_not_averaged_from_the_rows( folder ):
    assert cells( page_of( folder ), 9 )[ -1 ] == "2/5 (40.0%, 11.8-76.9%)", "rows read 2/3 and 0/2, whose mean would be 33.3%"


def test_the_table_follows_the_audits_and_a_week_with_no_runs_is_the_total_row_alone( tmp_path ):
    ( tmp_path / "duplicate-check-daily" ).mkdir()
    page = rb.weekly_report( [], [], [], "2026-11-08", tz=UTC, check_dir=tmp_path / "duplicate-check-daily" )
    assert page.endswith( f"Daily duplicate check\n\n{HEAD}\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| total |  | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 0/0 (n/a) |" )
    assert page.index( "| Audits |" ) < page.index( "Daily duplicate check" )
    assert "Left out" not in page, "nothing unreadable, so no left-out table"


def test_a_missing_folder_is_a_week_with_no_runs_and_not_an_error( tmp_path ):
    assert rb.read_check_runs( tmp_path / "nowhere", WEEK ) == ( [ ], 0 )


def test_an_unreadable_result_file_is_counted_under_left_out_of_the_week( folder ):
    ( folder / "2026-11-05-100000-cron.json" ).write_text( "{ cut off", encoding="utf-8" )
    ( folder / "2026-11-05-110000-cron.json" ).write_text( "[1, 2]", encoding="utf-8" )
    ( folder / "2026-11-05-120000-cron.json" ).write_text( json.dumps( { "date": "soon", "trigger": "cron", "judge_calls": 0, "elapsed_seconds": 1 } ), encoding="utf-8" )
    ( folder / "2026-11-05-130000-cron.json" ).write_text( json.dumps( { "date": "2026-11-05", "trigger": "cron", "judge_calls": 0 } ), encoding="utf-8" )
    ( folder / "2026-11-05-140000-cron.json" ).write_text( json.dumps( { "date": "2026-11-05", "trigger": "cron", "judge_calls": 0, "elapsed_seconds": 1, "findings": [ 7 ] } ), encoding="utf-8" )
    ( folder / "2026-11-05-150000-cron.json" ).mkdir()
    page = page_of( folder )
    assert "| duplicate-check result files that cannot be read | 6 |" in page and "| call log records with no readable time | 0 |" in page
    assert len( cells( page, 0 ) ) == 5, "the readable runs are still all there"


def test_a_run_dated_outside_the_week_is_in_neither_the_rows_nor_the_unreadable_count( folder ):
    runs, bad = rb.read_check_runs( folder, WEEK )
    assert bad == 0 and [ r[ "day" ].isoformat() for r in runs ] == [ "2026-11-02", "2026-11-03", "2026-11-03", "2026-11-04" ]


def test_the_folder_name_is_the_one_the_check_writes_to():
    assert rb.CHECK_FOLDER == daily.FOLDER[ 0 ]


def test_the_verdict_field_of_a_finding_wins_over_the_store_in_any_case():
    store = live( { "k": [ "x" + amendment( "DISTINCT" ) ] } )
    assert rb.verdict_of( "duplicate", "k", store ) == "DUPLICATE" and rb.verdict_of( "Extend", "k", store ) == "EXTEND" and rb.verdict_of( "DISTINCT", None, None ) == "DISTINCT"
    assert store.client.asked == [ ], "a finding that carries its verdict costs no store read"


def test_a_verdict_is_read_from_the_last_amendment_and_asked_for_in_every_state():
    store = live( { "k": [ "x" + amendment( "DUPLICATE" ) + amendment( "EXTEND" ), "y" + amendment( "DISTINCT" ) ] } )
    assert rb.verdict_of( None, "k", store ) == "DISTINCT"
    assert store.client.asked == [ ( "k", True ) ], "held and closed rows count, as the filing's own probe reads them"
    assert rb.verdict_of( "maybe", "k", store ) == "DISTINCT"


def test_no_verdict_is_none_when_there_is_no_key_store_row_or_answer():
    assert rb.verdict_of( None, None, live( { } ) ) is None and rb.verdict_of( None, "k", None ) is None
    assert rb.verdict_of( None, "k", live( { } ) ) is None
    assert rb.verdict_of( None, "k", live( { "k": [ "judged it, no word yet" ] } ) ) is None
    assert rb.verdict_of( None, "k", live( { "k": [ "x" + amendment( "DUPLICATE" ) ] }, ok=False ) ) is None, "a read that did not answer is no verdict"
    assert rb.verdict_of( None, "k", live( { "k": [ "VERDICT DUPLICATE typed into the body, not an amendment" ] } ) ) is None


def test_a_report_with_no_check_dir_has_no_such_table_and_no_extra_left_out_row( folder ):
    page = rb.weekly_report( [], [], [], "2026-11-08", tz=UTC )
    assert "Daily duplicate check" not in page and "result files" not in page


def test_the_command_prints_the_table_from_the_data_folder_and_the_check_dir_flag_moves_it( tmp_path, folder ):
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( folder.parent ), "--end", "2026-11-08" ], out=out, store=live( BODIES ) ) == 0
    assert cells( out.getvalue(), 6 ) == [ "0", "0", "2", "0", "2" ]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write_run( elsewhere, "2026-11-06-180000", "cron", judged=1, judge_calls=1, findings=[ finding( "c1", "duplicate" ) ] )
    out2 = io.StringIO()
    assert rb.main( [ "--data-dir", str( folder.parent ), "--check-dir", str( elsewhere ), "--end", "2026-11-08" ], out=out2, store=live( { } ) ) == 0
    assert cells( out2.getvalue(), 6 ) == [ "1", "1" ]


def test_the_command_builds_the_live_store_when_none_is_given( folder, monkeypatch ):
    made  = [ ]
    store = live( BODIES )
    monkeypatch.setattr( rb.ff, "LiveStore", lambda: made.append( 1 ) or store )
    assert rb.main( [ "--data-dir", str( folder.parent ), "--end", "2026-11-08" ], out=io.StringIO() ) == 0 and made == [ 1 ]
