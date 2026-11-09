"""
The verdict-line writer of the check, and the weekly table's reading of its file.

Every run is a real result file in a temporary folder, written under the name the check gives it. The store is a small amender
that answers in the shape of the real task store and records each note it was sent. Nothing calls a model or touches the shared data folder.
"""
import io
import json

import pytest

from lupin_mcp import duplicate_check_verdicts as dv
from lupin_mcp import reuse_behaviour as rb

RUN  = "2026-11-03-111218-hand"
ROW  = "11111111-2222-3333-4444-555555555555"
LINE_OK = f"DUPCHECK-VERDICT run={RUN} finding=d-a1 verdict=EXTEND class=helper-copy by=cheech ts=2026-11-03T22:41:04Z"


class Amender:
    """A task store that records each amend and answers ok or with a refusal."""

    def __init__( self, ok=True ):
        self.ok    = ok
        self.sent  = [ ]

    def amend( self, row_id, note ):
        self.sent.append( ( row_id, note ) )
        return self.ok, 200 if self.ok else 404, { "item": { } } if self.ok else { "detail": "no such row" }


def write_run( folder, stamp, ids, trigger="hand" ):
    """Ensures: writes a finished run's file under the check's own name, one finding per id."""
    ( folder / f"{stamp}-{trigger}.json" ).write_text( json.dumps( { "date": stamp[ :10 ], "trigger": trigger, "status": "carried", "judged": 9, "judge_calls": 9, "elapsed_seconds": 60.0,
                                                                    "findings": [ { "id": i, "correlation_key": f"epic:dupcheck-{i}" } for i in ids ] } ), encoding="utf-8" )


def swap( field, value ):
    """Ensures: returns LINE_OK with one field's value replaced."""
    words = dict( w.split( "=", 1 ) for w in LINE_OK.split( " " )[ 1: ] )
    words[ field ] = value
    return "DUPCHECK-VERDICT " + " ".join( f"{k}={v}" for k, v in words.items() )


@pytest.fixture
def folder( tmp_path ):
    """Ensures: a check folder with the 3 Nov run, three findings, and another day's run."""
    out = tmp_path / "duplicate-check-daily"
    out.mkdir()
    write_run( out, "2026-11-03-111218", [ "d-a1", "d-a2", "d-a3" ] )
    write_run( out, "2026-11-04-180000", [ "d-b1" ], trigger="cron" )
    return out


def lines( folder ):
    return [ json.loads( l ) for l in ( folder / "verdicts.jsonl" ).read_text( encoding="utf-8" ).splitlines() ]


FIELD_VALUES = { "run": "2026-11-04-180000-cron", "finding": "d-a2", "verdict": "DUPLICATE", "class": "different-job", "by": "john", "ts": "2026-11-04T01:02:03+00:00" }


@pytest.mark.parametrize( "field", dv.FIELDS )
def test_each_field_of_the_line_is_written_to_the_file_and_the_row_as_given_( folder, field ):
    value = FIELD_VALUES[ field ]
    if field == "run": write_run( folder, "2026-11-04-180000", [ "d-a1" ], trigger="cron" )
    line  = swap( field, value )
    store = Amender()
    got   = dv.write_verdict( line, folder, ROW, store )
    assert got[ field ] == value and lines( folder ) == [ got ]
    assert got == dict( w.split( "=", 1 ) for w in line.split( " " )[ 1: ] ), "no field is rewritten on its way to the file"
    assert store.sent == [ ( ROW, line ) ], "the row gets the line exactly as the file's record was made from"


@pytest.mark.parametrize( "field, bad", [ ( "run", "2026-11-03-111218" ), ( "run", "../2026-11-03-111218-hand" ), ( "run", "2026-13-03-111218-hand" ), ( "finding", "d a1" ), ( "finding", "" ),
                                           ( "verdict", "REAL" ), ( "verdict", "distinct" ), ( "class", "Helper Copy" ), ( "class", "helper_copy" ), ( "class", "-x" ), ( "class", "" ),
                                           ( "by", "" ), ( "by", "a=b" ), ( "ts", "2026-11-03 22:41:04" ), ( "ts", "2026-11-03T22:41:04-05:00" ), ( "ts", "2026-11-03T25:41:04Z" ), ( "ts", "2026-02-31T22:41:04Z" ) ] )
def test_a_malformed_value_in_any_field_is_refused_and_nothing_is_written( folder, field, bad ):
    store = Amender()
    with pytest.raises( dv.VerdictRefused ): dv.write_verdict( swap( field, bad ), folder, ROW, store )
    assert not ( folder / "verdicts.jsonl" ).exists() and store.sent == [ ]


@pytest.mark.parametrize( "line", [ "", "hello", LINE_OK + " extra=1", LINE_OK.replace( "DUPCHECK-VERDICT", "VERDICT" ), "DUPCHECK-VERDICT  " + LINE_OK.split( " ", 1 )[ 1 ], LINE_OK + " ", LINE_OK.replace( "class=helper-copy by=cheech", "by=cheech class=helper-copy" ) ] )
def test_a_line_of_the_wrong_shape_or_field_order_is_refused( folder, line ):
    with pytest.raises( dv.VerdictRefused, match="does not match" ): dv.write_verdict( line, folder, ROW, Amender() )


def test_an_unreal_calendar_date_in_the_run_is_refused_with_its_own_reason( folder ):
    with pytest.raises( dv.VerdictRefused, match="does not exist" ): dv.write_verdict( swap( "run", "2026-02-30-111218-hand" ), folder, ROW, Amender() )


def test_a_finding_id_that_is_not_in_that_runs_file_is_refused_even_when_another_run_holds_it( folder ):
    store = Amender()
    with pytest.raises( dv.VerdictRefused, match="d-b1 is not in run" ): dv.write_verdict( swap( "finding", "d-b1" ), folder, ROW, store )
    assert not ( folder / "verdicts.jsonl" ).exists() and store.sent == [ ]


def test_a_run_with_no_result_file_or_one_that_cannot_be_read_is_refused( folder ):
    with pytest.raises( dv.VerdictRefused, match="no readable result file" ): dv.write_verdict( swap( "run", "2026-11-09-120000-hand" ), folder, ROW, Amender() )
    ( folder / "2026-11-09-120000-hand.json" ).write_text( "{ cut off", encoding="utf-8" )
    with pytest.raises( dv.VerdictRefused, match="no readable result file" ): dv.write_verdict( swap( "run", "2026-11-09-120000-hand" ), folder, ROW, Amender() )


def test_a_second_line_for_the_same_finding_is_refused_and_a_second_finding_is_taken( folder ):
    store = Amender()
    dv.write_verdict( LINE_OK, folder, ROW, store )
    with pytest.raises( dv.VerdictRefused, match="already has a verdict line" ): dv.write_verdict( swap( "verdict", "DISTINCT" ), folder, ROW, store )
    dv.write_verdict( swap( "finding", "d-a2" ), folder, ROW, store )
    assert [ r[ "finding" ] for r in lines( folder ) ] == [ "d-a1", "d-a2" ] and len( store.sent ) == 2, "the file and the row hold the same two lines"


def test_a_store_that_refuses_the_amend_leaves_no_file_when_there_was_none_so_file_and_row_cannot_disagree( folder ):
    store = Amender( ok=False )
    with pytest.raises( dv.VerdictRefused, match=r"refused the amend onto row .* \(HTTP 404\).*put back as it was" ): dv.write_verdict( LINE_OK, folder, ROW, store )
    assert not ( folder / "verdicts.jsonl" ).exists() and store.sent == [ ( ROW, LINE_OK ) ]


def test_a_store_that_refuses_the_amend_puts_an_existing_file_back_byte_for_byte( folder ):
    dv.write_verdict( swap( "finding", "d-a2" ), folder, ROW, Amender() )
    before = ( folder / "verdicts.jsonl" ).read_bytes()
    with pytest.raises( dv.VerdictRefused, match="put back as it was" ): dv.write_verdict( LINE_OK, folder, ROW, Amender( ok=False ) )
    assert ( folder / "verdicts.jsonl" ).read_bytes() == before


class Exploding:
    """A store whose amend raises, as a client bug or an interrupt would."""

    def __init__( self, error ):
        self.error = error

    def amend( self, row_id, note ):
        raise self.error


@pytest.mark.parametrize( "error", [ RuntimeError( "client bug" ), KeyboardInterrupt() ], ids=[ "runtime-error", "keyboard-interrupt" ] )
def test_any_exception_from_the_amend_puts_the_file_back_and_is_raised_on_unchanged( folder, error ):
    dv.write_verdict( swap( "finding", "d-a2" ), folder, ROW, Amender() )
    before = ( folder / "verdicts.jsonl" ).read_bytes()
    with pytest.raises( type( error ) ) as seen: dv.write_verdict( LINE_OK, folder, ROW, Exploding( error ) )
    assert seen.value is error and ( folder / "verdicts.jsonl" ).read_bytes() == before


def test_an_exception_from_the_amend_removes_a_file_that_did_not_exist_before( folder ):
    with pytest.raises( RuntimeError ): dv.write_verdict( LINE_OK, folder, ROW, Exploding( RuntimeError( "x" ) ) )
    assert not ( folder / "verdicts.jsonl" ).exists()


def test_an_exception_from_the_amend_still_raises_when_the_file_cannot_be_put_back( folder, monkeypatch ):
    monkeypatch.setattr( dv.pathlib.Path, "unlink", lambda self, *a, **k: ( _ for _ in () ).throw( PermissionError( "read-only" ) ) )
    with pytest.raises( RuntimeError, match="client bug" ): dv.write_verdict( LINE_OK, folder, ROW, Exploding( RuntimeError( "client bug" ) ) )


def test_a_file_that_cannot_be_appended_is_refused_with_the_row_untouched_and_says_so( folder ):
    ( folder / "verdicts.jsonl" ).mkdir()
    store = Amender()
    with pytest.raises( dv.VerdictRefused, match="could not append.*IsADirectoryError.*row was not amended" ): dv.write_verdict( LINE_OK, folder, ROW, store )
    assert store.sent == [ ]


def test_a_rollback_that_cannot_run_says_the_line_is_still_in_the_file( folder, monkeypatch ):
    real = dv.pathlib.Path.unlink

    def broken( self, *a, **k ): raise PermissionError( "read-only" )

    monkeypatch.setattr( dv.pathlib.Path, "unlink", broken )
    with pytest.raises( dv.VerdictRefused, match="still in .*could not be taken out \\(PermissionError: read-only\\)" ): dv.write_verdict( LINE_OK, folder, ROW, Amender( ok=False ) )
    monkeypatch.setattr( dv.pathlib.Path, "unlink", real )
    assert len( lines( folder ) ) == 1


def test_the_command_turns_a_file_that_cannot_be_written_into_exit_3_naming_what_was_not_written( folder ):
    ( folder / "verdicts.jsonl" ).mkdir()
    out = io.StringIO()
    assert dv.main( [ LINE_OK, "--row", ROW, "--data-dir", str( folder.parent ) ], out=out, amender=Amender() ) == 3
    assert "REFUSING" in out.getvalue() and "row was not amended" in out.getvalue()


def test_a_file_only_back_fill_never_asks_the_store_and_makes_the_folder_if_it_is_absent( tmp_path ):
    out = tmp_path / "later"
    out.mkdir()
    write_run( out, "2026-11-03-111218", [ "d-a1" ] )
    gone = tmp_path / "gone"
    with pytest.raises( dv.VerdictRefused ): dv.write_verdict( LINE_OK, gone, None, None )
    assert dv.write_verdict( LINE_OK, out, None, None )[ "finding" ] == "d-a1" and len( lines( out ) ) == 1


def test_the_command_writes_the_line_amends_the_row_and_prints_what_it_wrote( folder ):
    out, store = io.StringIO(), Amender()
    assert dv.main( [ LINE_OK, "--row", ROW, "--data-dir", str( folder.parent ) ], out=out, amender=store ) == 0
    assert out.getvalue().startswith( "WROTE: " ) and json.loads( out.getvalue()[ 7: ] ) == lines( folder )[ 0 ] and store.sent == [ ( ROW, LINE_OK ) ]


def test_the_command_refuses_with_exit_3_and_says_nothing_was_written( folder ):
    out = io.StringIO()
    assert dv.main( [ swap( "finding", "d-zz" ), "--row", ROW, "--data-dir", str( folder.parent ) ], out=out, amender=Amender() ) == 3
    assert "REFUSING" in out.getvalue() and "Nothing was written" in out.getvalue() and not ( folder / "verdicts.jsonl" ).exists()


def test_the_command_files_a_back_fill_with_file_only_and_needs_exactly_one_of_row_and_file_only( folder ):
    assert dv.main( [ LINE_OK, "--file-only", "--data-dir", str( folder.parent ) ], out=io.StringIO() ) == 0 and len( lines( folder ) ) == 1
    for extra in ( [ ], [ "--row", ROW, "--file-only" ] ):
        with pytest.raises( SystemExit ): dv.main( [ LINE_OK, "--data-dir", str( folder.parent ), *extra ], out=io.StringIO() )


def test_the_command_builds_the_live_store_when_a_row_is_given_and_none_is_passed( folder, monkeypatch ):
    store = Amender()
    monkeypatch.setattr( dv.ff, "LiveStore", lambda: store )
    assert dv.main( [ LINE_OK, "--row", ROW, "--data-dir", str( folder.parent ) ], out=io.StringIO() ) == 0 and store.sent == [ ( ROW, LINE_OK ) ]


# ---- the weekly table's side ----

def page_of( folder ):
    return rb.weekly_report( [], [], [], "2026-11-08", tz=rb.datetime.timezone.utc, check_dir=folder, store=None )


def row_of( page, day ):
    return [ c.strip() for c in [ l for l in page.splitlines() if l.startswith( f"| {day} " ) ][ 0 ].strip( "|" ).split( "|" ) ]


def test_a_run_with_findings_and_no_verdict_shows_not_triaged_in_real_not_and_precision_never_zero( folder ):
    row = row_of( page_of( folder ), "2026-11-03" )
    assert row[ 6: ] == [ "3", "not triaged", "not triaged", "3", "not triaged" ]
    assert row_of( page_of( folder ), "total" )[ 7: ] == [ "not triaged", "not triaged", "4", "not triaged" ]


def test_logged_verdicts_count_real_as_duplicate_plus_extend_and_not_as_distinct_with_precision( folder ):
    for fid, verdict in ( ( "d-a1", "DUPLICATE" ), ( "d-a2", "EXTEND" ), ( "d-a3", "DISTINCT" ) ):
        dv.write_verdict( swap( "finding", fid ).replace( "verdict=EXTEND", f"verdict={verdict}" ), folder, ROW, Amender() )
    row = row_of( page_of( folder ), "2026-11-03" )
    assert row[ 6: ] == [ "3", "2", "1", "0", "2/3 (66.7%, 20.8-93.9%)" ]
    assert row_of( page_of( folder ), "2026-11-04" )[ 7: ] == [ "not triaged", "not triaged", "1", "not triaged" ], "the other day's run is still untriaged"
    assert row_of( page_of( folder ), "total" )[ 7: ] == [ "2", "1", "1", "2/3 (66.7%, 20.8-93.9%)" ], "the untriaged finding is open, in neither side"


def test_a_partly_triaged_run_shows_counts_and_the_rest_as_no_verdict_yet( folder ):
    dv.write_verdict( LINE_OK, folder, ROW, Amender() )
    assert row_of( page_of( folder ), "2026-11-03" )[ 6: ] == [ "3", "1", "0", "2", "1/1 (100.0%, 20.7-100.0%)" ]


def test_a_run_with_no_findings_stays_zeros_not_not_triaged( tmp_path ):
    out = tmp_path / "duplicate-check-daily"
    out.mkdir()
    write_run( out, "2026-11-05-180000", [ ], trigger="cron" )
    assert row_of( page_of( out ), "2026-11-05" )[ 6: ] == [ "0", "0", "0", "0", "0/0 (n/a)" ]


def test_the_findings_own_verdict_field_wins_over_the_log_and_the_log_wins_over_the_store( folder ):
    dv.write_verdict( LINE_OK, folder, ROW, Amender() )
    run, _ = rb.read_check_runs( folder, rb.week_of( "2026-11-08" ) )
    got    = rb.check_counts( run[ 0 ], None, rb.read_verdicts( folder ) )
    assert got == { "real": 1, "not_dup": 0, "open": 2 }
    assert rb.verdict_of( "distinct", "k", None, "EXTEND" ) == "DISTINCT"
    assert rb.verdict_of( None, "k", None, "EXTEND" ) == "EXTEND", "no store is read when the log has the word"
    assert rb.check_counts( run[ 0 ], None ) == { "real": 0, "not_dup": 0, "open": 3 }, "no log means no log verdicts"


def test_the_log_is_matched_by_run_stem_and_finding_id_together( folder ):
    write_run( folder, "2026-11-04-180000", [ "d-a1" ], trigger="cron" )
    dv.write_verdict( LINE_OK, folder, ROW, Amender() )
    runs, _ = rb.read_check_runs( folder, rb.week_of( "2026-11-08" ) )
    by_stem = { r[ "stem" ]: rb.check_counts( r, None, rb.read_verdicts( folder ) ) for r in runs }
    assert by_stem[ RUN ][ "real" ] == 1 and by_stem[ "2026-11-04-180000-cron" ][ "real" ] == 0, "the same finding id on another run is not ruled on"


def test_read_verdicts_takes_the_last_line_for_a_pair_and_an_absent_file_is_empty( tmp_path ):
    assert rb.read_verdicts( tmp_path ) == { }
    ( tmp_path / "verdicts.jsonl" ).write_text( json.dumps( { "run": "r", "finding": "f", "verdict": "DISTINCT" } ) + "\n" + json.dumps( { "run": "r", "finding": "f", "verdict": "EXTEND" } ) + "\n", encoding="utf-8" )
    assert rb.read_verdicts( tmp_path ) == { ( "r", "f" ): "EXTEND" }


@pytest.mark.parametrize( "text", [ "{ cut off", "[1]", '{"run": "r", "finding": "f"}', '{"run": "r", "finding": "f", "verdict": "REAL"}' ] )
def test_a_line_that_is_not_a_verdict_record_stops_the_page_with_its_line_number( tmp_path, text ):
    ( tmp_path / "verdicts.jsonl" ).write_text( json.dumps( { "run": "r", "finding": "f", "verdict": "EXTEND" } ) + "\n" + text + "\n", encoding="utf-8" )
    with pytest.raises( ValueError, match="verdicts.jsonl line 2 is not a verdict record" ): rb.read_verdicts( tmp_path )


def test_the_weekly_command_refuses_with_exit_3_when_the_verdict_file_is_corrupt( folder ):
    ( folder / "verdicts.jsonl" ).write_text( "garbage\n", encoding="utf-8" )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( folder.parent ), "--end", "2026-11-08" ], out=out, store=None ) == 3 and "line 1" in out.getvalue()


def test_the_verdict_file_name_is_the_one_the_writer_appends_to_and_it_sits_beside_the_result_files( folder ):
    dv.write_verdict( LINE_OK, folder, ROW, Amender() )
    assert rb.VERDICTS_FILE == "verdicts.jsonl" and ( folder / rb.VERDICTS_FILE ).is_file() and ( folder / "2026-11-03-111218-hand.json" ).is_file()


def test_settled_keys_are_the_keys_of_the_findings_a_line_rules_on_whatever_the_verdict_and_nothing_else( folder ):
    ( folder / "verdicts.jsonl" ).write_text( "\n".join( json.dumps( { "run": "2026-11-03-111218-hand", "finding": fid, "verdict": v, "class": "c", "by": "x", "ts": "t" } )
                                                         for fid, v in ( ( "d-a1", "DISTINCT" ), ( "d-a3", "DUPLICATE" ) ) ) + "\n" )
    assert rb.settled_keys( folder ) == { "epic:dupcheck-d-a1", "epic:dupcheck-d-a3" }


def test_a_line_for_a_run_with_no_readable_file_or_a_finding_without_a_key_settles_nothing_and_no_file_is_empty( folder, tmp_path ):
    assert rb.settled_keys( folder ) == set()
    ( folder / "2026-11-05-090000-cron.json" ).write_text( json.dumps( { "date": "2026-11-05", "trigger": "cron", "judge_calls": 1, "elapsed_seconds": 1.0, "findings": [ { "id": "d-k" } ] } ) )
    ( folder / "verdicts.jsonl" ).write_text( "\n".join( json.dumps( { "run": r, "finding": f, "verdict": "EXTEND", "class": "c", "by": "x", "ts": "t" } )
                                                         for r, f in ( ( "2026-11-09-000000-hand", "d-gone" ), ( "2026-11-05-090000-cron", "d-k" ) ) ) + "\n" )
    assert rb.settled_keys( folder ) == set()


def test_a_damaged_verdicts_line_is_raised_by_settled_keys_as_read_verdicts_raises_it( folder ):
    ( folder / "verdicts.jsonl" ).write_text( "garbage\n" )
    with pytest.raises( ValueError, match="line 1 is not a verdict record" ): rb.settled_keys( folder )
