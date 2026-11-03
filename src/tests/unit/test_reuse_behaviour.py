"""
The behaviour report and its weekly form: lookups, outcome lines, refusals, audits.

The seeded files are small and written here, so the expected tables are stated in the test.
A second group of tests drives the real checkers and shows that every reason they can give has a label in the report.
Nothing here calls a model or touches the shared data folder.
"""
import datetime
import io
import json
import pathlib

import pytest

import cosa.utils.util as cu
from lupin_mcp import reuse_behaviour as rb
from lupin_mcp import reuse_exit_gate as eg
from cosa.repo.symindex.candidates import shadow_audit as sa
from lupin_mcp import reuse_refusals as rr

PLAN = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.24-reuse-detection-remediation-plan.md"
ROOT = pathlib.Path( cu.get_project_root() )
RID  = "5d37236290c7d93f"
SID  = "rs-bc3ca2c901"


def outcome( kind_text, rid=RID, sid=SID ):
    return f"REUSE-OUTCOME {rid} :: {sid} :: {kind_text} :: {PLAN}#12.3-C5"


def row( n, line, status, *reasons ):
    return { "doc": "d" * 64, "n": n, "line": line, "status": status, "reasons": list( reasons ), "pairs": [], "at": "2026-11-02T10:00:00+0000" }


def seed( data, calls, rows ):
    """Ensures: writes a call log and a refusals.jsonl into a temporary data folder."""
    ( data / "call-log" ).mkdir()
    ( data / "call-log" / "seed.jsonl" ).write_text( "\n".join( json.dumps( c ) for c in calls ) + "\n", encoding="utf-8" )
    ( data / rr.REFUSALS_NAME ).write_text( "\n".join( json.dumps( r ) for r in rows ) + "\nnot json\n[1]\n", encoding="utf-8" )


def calls():
    ok = lambda tool, i: { "ts": "2026-11-02T10:00:00+00:00", "tool": tool, "caller": "p x", "session": "x", "receipt_id": f"{i:016x}", "error": None, "args": "{}" }
    return [ ok( "check_exists", 1 ), ok( "check_exists", 2 ), ok( "fetch_similar", 3 ),
             dict( ok( "check_exists", 4 ), error="CALL_FAILED" ), { "ts": "2026-11-02T10:00:00+00:00", "tool": "record_search", "caller": "p x", "session": "x", "search_id": SID, "error": None, "args": "{}" } ]


def rows():
    return [ row( 1, outcome( "REUSED a.b" ), "accepted" ),
             row( 2, outcome( "EXTENDED a.b" ), "refused", f"receipt {RID} is not in the log; re-run the lookup and check the log folder" ),
             row( 3, outcome( "WROTE_NEW it differs" ), "refused", "excluded.x has no EXCLUDED_ refusal in the log; re-run the lookup", "the outcome is WROTE_NEW but the ruling disagrees (m.x is DUPLICATE)" ),
             row( 4, f"REUSE-OUTCOME {RID} :: {SID} :: REUSED two tokens :: {PLAN}#12.3-C5", "refused", "the line does not match the REUSE-OUTCOME shape" ),
             row( 5, outcome( "REUSED c.d" ), "accepted" ),
             row( 6, "some unexpected line", "refused", "a reason nobody wrote a label for" ) ]


EXPECTED = """| Lookups | count |
| --- | --- |
| check_exists | 2 |
| fetch_similar | 1 |
| failed (any lookup tool) | 1 |

| Scanned outcome lines | count |
| --- | --- |
| accepted | 2 |
| refused | 4 |

| Outcome lines by kind | count |
| --- | --- |
| REUSED | 2 |
| EXTENDED | 1 |
| WROTE_NEW | 1 |
| unparsed | 2 |

| Refusals by reason | count |
| --- | --- |
| line does not match the shape | 1 |
| receipt not in the log | 1 |
| search not in the log for the receipt | 0 |
| excluded with no logged refusal | 1 |
| unindexed in only one id slot | 0 |
| unindexed search beside a real receipt | 0 |
| unindexed file the index holds | 0 |
| outcome line with no ruling line | 0 |
| outcome and ruling kinds disagree | 1 |
| other (not in this list) | 1 |"""


def test_a_report_from_a_seeded_refusals_file_and_call_log_equals_the_stated_table( tmp_path ):
    seed( tmp_path, calls(), rows() )
    records, _ = eg.merge_call_logs( tmp_path / "call-log" )
    got        = rb.report( records, rb.read_refusals( tmp_path ) )
    assert got == EXPECTED


AUDITS_ZERO = "| Audits | count |\n| --- | --- |\n| known-miss audits | 0 |\n| random-sample audits | 0 |"
TITLE       = "Reuse behaviour, 2026-10-27 to 2026-11-02 (seven days, the whole fleet, no seat named)"


@pytest.fixture
def utc( monkeypatch ):
    """Ensures: the report reads days in UTC, whatever the host's zone."""
    monkeypatch.setattr( rb, "local_tz", lambda: datetime.timezone.utc )


def test_the_command_prints_the_same_report_from_the_two_files( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02" ], out=out ) == 0
    assert out.getvalue().strip() == f"{TITLE}\n\n{EXPECTED}\n\n{AUDITS_ZERO}"
    out2 = io.StringIO()
    elsewhere = tmp_path / "logs-elsewhere"
    ( tmp_path / "call-log" ).rename( elsewhere )
    assert rb.main( [ "--data-dir", str( tmp_path ), "--log-dir", str( elsewhere ), "--end", "20261102" ], out=out2 ) == 0 and out2.getvalue() == out.getvalue()


def test_a_missing_refusals_file_and_an_empty_log_give_a_report_of_zeros( tmp_path ):
    ( tmp_path / "call-log" ).mkdir()
    assert rb.read_refusals( tmp_path ) == []
    text = rb.report( eg.merge_call_logs( tmp_path / "call-log" )[ 0 ], [] )
    assert "| check_exists | 0 |" in text and "| REUSED | 0 |" in text and "| accepted | 0 |" in text and "| other (not in this list) | 0 |" in text


def test_every_reason_the_checkers_can_give_has_its_own_label():
    known   = { "check_exists": RID }
    ruling  = f"RULING m.good :: DUPLICATE :: reuse-receipt: {RID}\nRULING m.kind :: DISTINCT it differs :: reuse-receipt: 1123456789abcdef"
    lines   = [ "REUSE-OUTCOME bad shape", outcome( "REUSED a.b", rid="0123456789abcdef" ), outcome( "REUSED a.b", sid="rs-0000000000" ),
                f"REUSE-OUTCOME excluded :: {SID} :: WROTE_NEW m.nolog refused :: {PLAN}#12.3-C5",
                f"REUSE-OUTCOME unindexed :: {SID} :: WROTE_NEW src/rnd/x.md :: {PLAN}#12.3-C5",
                f"REUSE-OUTCOME {RID} :: unindexed :: WROTE_NEW a note :: {PLAN}#12.3-C5",
                f"REUSE-OUTCOME unindexed :: unindexed :: WROTE_NEW src/lupin_mcp/x.py :: {PLAN}#12.3-C5",
                outcome( "REUSED a.b", rid="3123456789abcdef" ),
                outcome( "REUSED a.b", rid="1123456789abcdef" ) ]
    text    = ruling + "\n" + "\n".join( lines )
    verdicts = rr.judge( text, { RID: "check_exists", "1123456789abcdef": "check_exists", "3123456789abcdef": "check_exists" },
                         { RID: { SID: [] }, "1123456789abcdef": { SID: [] }, "3123456789abcdef": { SID: [] } }, {}, eg.parse_rulings( text ), ROOT )
    reasons  = [ reason for v in verdicts for reason in v[ "reasons" ] ]
    labels   = {rb.reason_label( r ) for r in reasons}
    assert len( verdicts ) == len( lines ) and all( v[ "status" ] == "refused" for v in verdicts ), "every seeded line was refused, for a reason"
    assert rb.OTHER_REASON not in labels, [ r for r in reasons if rb.reason_label( r ) == rb.OTHER_REASON ]
    assert labels == {label for _, label in rb.REASON_LABELS}, "each label is the real wording of at least one checker"


def test_two_lookups_that_share_a_receipt_id_count_as_two():
    again = lambda tool: { "ts": "2026-11-02T10:00:00+00:00", "tool": tool, "caller": "p x", "session": "x", "receipt_id": "0123456789abcdef", "error": None, "args": "{}" }
    got   = rb.count_lookups( [ again( "check_exists" ), again( "check_exists" ), again( "fetch_similar" ) ] )
    assert got == { "check_exists": 2, "fetch_similar": 1, "failed (any lookup tool)": 0 }, "the same receipt id twice is two lookups, not one"


def test_a_failed_search_record_is_not_counted_as_a_failed_lookup():
    search = { "ts": "2026-11-02T10:00:00+00:00", "tool": "record_search", "caller": "p x", "session": "x", "search_id": SID, "error": "BAD_SEARCH_KEY", "args": "{}" }
    lookup = { "ts": "2026-11-02T10:00:00+00:00", "tool": "check_exists", "caller": "p x", "session": "x", "receipt_id": None, "error": "CALL_FAILED", "args": "{}" }
    assert rb.count_lookups( [ search ] ) == { "check_exists": 0, "fetch_similar": 0, "failed (any lookup tool)": 0 }
    assert rb.count_lookups( [ search, lookup ] )[ "failed (any lookup tool)" ] == 1, "only the lookup tool's failure counts"


def stamped( tool, stamp, **more ):
    """Ensures: returns a call log record with this time stamp."""
    base = { "tool": tool, "caller": "somebody 1234abcd", "session": "1234abcd", "receipt_id": "0123456789abcdef", "error": None, "args": "{}" }
    return { **base, **( { "ts": stamp } if stamp is not None else {} ), **more }


def receipt_of( need, day, known_miss ):
    """Ensures: returns a real audit receipt for a need, audited on a day."""
    return sa.audit_receipt( need, "py", "gen-1", "idx-1", { "verdict": "REUSE", "candidate_ids": [ "a" ] }, { "verdict": "NEW", "causal_ids": [] }, day, known_miss=known_miss )


WEEK_CALLS = [ stamped( "check_exists", "2026-10-27T05:30:00+00:00" ),                         # 00:30 on the first day, in UTC-5
               stamped( "fetch_similar", "2026-11-03T04:59:59+00:00" ),                         # 23:59:59 on the last day
               stamped( "check_exists", "2026-10-27T04:59:59+00:00" ),                          # one second before the week
               stamped( "check_exists", "2026-11-03T05:00:00+00:00" ),                          # the first second after it
               stamped( "check_exists", "2026-11-01T12:00:00+00:00", error="CALL_FAILED" ),
               stamped( "check_exists", "garbage" ), stamped( "fetch_similar", None ) ]
WEEK_ROWS  = [ { **row( 1, outcome( "REUSED a.b" ), "accepted" ), "at": "2026-11-02T10:00:00-0500" },
               { **row( 2, outcome( "EXTENDED a.b" ), "refused", f"receipt {RID} is not in the log; re-run" ), "at": "2026-10-30T10:00:00-0500" },
               { **row( 3, outcome( "WROTE_NEW it differs" ), "refused", "the outcome is WROTE_NEW but the ruling disagrees" ), "at": "2026-10-26T23:59:59-0500" },
               { **row( 4, outcome( "REUSED c.d" ), "accepted" ), "at": "2026-11-03T00:00:00-0500" },
               { **row( 5, "odd line", "refused", "the line does not match the REUSE-OUTCOME shape" ), "at": "2026-11-01T09:00:00-0500" },
               { k: v for k, v in row( 6, outcome( "REUSED e.f" ), "accepted" ).items() if k != "at" } ]
WEEK_RECEIPTS = [ receipt_of( "n1", "2026-11-02", True ), receipt_of( "n2", "2026-10-27", False ), receipt_of( "n3", "2026-10-26", False ),
                  receipt_of( "n4", "2026-11-03", True ), receipt_of( "n5", "2026-11-01", False ) ]
EST = datetime.timezone( datetime.timedelta( hours=-5 ) )

WEEK_EXPECTED = """Reuse behaviour, 2026-10-27 to 2026-11-02 (seven days, the whole fleet, no seat named)

| Lookups | count |
| --- | --- |
| check_exists | 1 |
| fetch_similar | 1 |
| failed (any lookup tool) | 1 |

| Scanned outcome lines | count |
| --- | --- |
| accepted | 1 |
| refused | 2 |

| Outcome lines by kind | count |
| --- | --- |
| REUSED | 1 |
| EXTENDED | 1 |
| WROTE_NEW | 0 |
| unparsed | 1 |

| Refusals by reason | count |
| --- | --- |
| line does not match the shape | 1 |
| receipt not in the log | 1 |
| search not in the log for the receipt | 0 |
| excluded with no logged refusal | 0 |
| unindexed in only one id slot | 0 |
| unindexed search beside a real receipt | 0 |
| unindexed file the index holds | 0 |
| outcome line with no ruling line | 0 |
| outcome and ruling kinds disagree | 0 |
| other (not in this list) | 0 |

| Audits | count |
| --- | --- |
| known-miss audits | 1 |
| random-sample audits | 2 |

| Left out of the week | count |
| --- | --- |
| call log records with no readable time | 2 |
| outcome records with no readable time | 1 |"""


def test_a_seeded_week_equals_the_table_stated_here_and_records_just_outside_it_are_left_out():
    assert rb.weekly_report( WEEK_CALLS, WEEK_ROWS, WEEK_RECEIPTS, "2026-11-02", tz=EST ) == WEEK_EXPECTED
    in_utc = rb.weekly_report( WEEK_CALLS, WEEK_ROWS, WEEK_RECEIPTS, "2026-11-02", tz=datetime.timezone.utc )
    assert in_utc != WEEK_EXPECTED, "the same records fall in other days when read in another zone, so the zone is used"


def test_the_audits_are_split_by_the_receipts_own_flag_and_dated_by_the_audit_day():
    week = rb.week_of( "2026-11-02" )
    assert rb.count_audits( WEEK_RECEIPTS, week ) == { "known-miss audits": 1, "random-sample audits": 2 }
    assert rb.count_audits( [], week ) == { "known-miss audits": 0, "random-sample audits": 0 }
    assert rb.count_audits( WEEK_RECEIPTS, rb.week_of( "2026-11-03" ) ) == { "known-miss audits": 2, "random-sample audits": 1 }, "the next day's week drops 10-27 and takes 11-03"


def test_no_seat_or_person_is_named_and_no_table_has_a_column_for_one():
    page = rb.weekly_report( WEEK_CALLS, WEEK_ROWS, WEEK_RECEIPTS, "2026-11-02", tz=EST )
    assert "somebody" not in page and "1234abcd" not in page
    heads = [ line for line in page.splitlines() if line.startswith( "| " ) and line.endswith( "| count |" )]
    assert len( heads ) == 6 and all( h.count( "|" ) == 3 for h in heads ), "every table is a name and a count, nothing else"


def test_a_week_with_nothing_undated_has_no_left_out_table():
    page = rb.weekly_report( [ stamped( "check_exists", "2026-11-01T12:00:00+00:00" ) ], [], [], "2026-11-02", tz=datetime.timezone.utc )
    assert "Left out" not in page and page.startswith( "Reuse behaviour, 2026-10-27 to 2026-11-02" )
    only_rows = rb.weekly_report( [], [ { k: v for k, v in row( 1, "x", "refused" ).items() if k != "at" } ], [], "2026-11-02", tz=datetime.timezone.utc )
    assert "| call log records with no readable time | 0 |" in only_rows and "| outcome records with no readable time | 1 |" in only_rows
    only_calls = rb.weekly_report( [ stamped( "check_exists", None ) ], [], [], "2026-11-02", tz=datetime.timezone.utc )
    assert "| call log records with no readable time | 1 |" in only_calls and "| outcome records with no readable time | 0 |" in only_calls


def test_a_time_stamp_is_read_only_when_it_is_text_with_an_offset():
    utc = datetime.timezone.utc
    assert rb.day_of( "2026-11-02T23:30:00-05:00", utc ) == datetime.date( 2026, 11, 3 )
    assert rb.day_of( "2026-11-02T23:30:00-0500", EST ) == datetime.date( 2026, 11, 2 )
    assert rb.day_of( "2026-11-02T10:00:00", utc ) is None, "no offset: the day cannot be told"
    assert rb.day_of( "garbage", utc ) is None and rb.day_of( None, utc ) is None and rb.day_of( 5, utc ) is None
    assert rb.week_of( datetime.date( 2026, 11, 2 ) ) == ( datetime.date( 2026, 10, 27 ), datetime.date( 2026, 11, 2 ) )
    with pytest.raises( ValueError ): rb.week_of( "next tuesday" )


def test_the_host_zone_is_used_when_none_is_given( monkeypatch ):
    monkeypatch.setattr( rb, "local_tz", lambda: EST )
    assert rb.weekly_report( WEEK_CALLS, WEEK_ROWS, WEEK_RECEIPTS, "2026-11-02" ) == WEEK_EXPECTED


def test_the_real_host_zone_is_a_time_zone():
    assert isinstance( rb.local_tz(), datetime.tzinfo )


def test_write_saves_the_page_under_the_data_folder_by_its_end_date_and_replaces_it_the_next_time( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    for receipt in ( receipt_of( "w1", "2026-11-01", True ), receipt_of( "w2", "2026-11-02", False ) ): sa.store_receipt( tmp_path, receipt )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02", "--write" ], out=out ) == 0
    page = tmp_path / rb.PAGE_FOLDER / "reuse-behaviour-2026-11-02.txt"
    assert page.read_text( encoding="utf-8" ) == out.getvalue() and "| known-miss audits | 1 |" in out.getvalue() and "| random-sample audits | 1 |" in out.getvalue()
    page.write_text( "stale", encoding="utf-8" )
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02", "--write" ], out=io.StringIO() ) == 0 and page.read_text( encoding="utf-8" ) != "stale"
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02" ], out=io.StringIO() ) == 0 and len( list( ( tmp_path / rb.PAGE_FOLDER ).iterdir() ) ) == 1, "a run without --write adds no page"


def test_the_end_date_defaults_to_the_sunday_that_closes_the_last_complete_week( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    before = rb.last_complete_week_end( datetime.datetime.now().astimezone().date() ).isoformat()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--write" ], out=io.StringIO() ) == 0
    after  = rb.last_complete_week_end( datetime.datetime.now().astimezone().date() ).isoformat()
    names  = [ p.name for p in ( tmp_path / rb.PAGE_FOLDER ).iterdir() ]
    assert names in ( [ f"reuse-behaviour-{before}.txt" ], [ f"reuse-behaviour-{after}.txt" ] )
    assert datetime.date.fromisoformat( names[ 0 ][ 16:26 ] ).weekday() == 6, "the page is named by a Sunday"


@pytest.mark.parametrize( "today, end", [ ( "2026-11-02", "2026-11-01" ),      # Monday: the week that ended yesterday
                                          ( "2026-11-03", "2026-11-01" ), ( "2026-11-04", "2026-11-01" ), ( "2026-11-05", "2026-11-01" ),
                                          ( "2026-11-06", "2026-11-01" ), ( "2026-11-07", "2026-11-01" ),
                                          ( "2026-11-08", "2026-11-01" ),      # Sunday: this week is not over
                                          ( "2026-11-09", "2026-11-08" ) ] )  # the next Monday: the week ending 11-08 is complete
def test_the_last_complete_week_ends_on_the_latest_sunday_before_today( today, end ):
    assert rb.last_complete_week_end( datetime.date.fromisoformat( today ) ) == datetime.date.fromisoformat( end )


def test_a_boot_on_any_day_of_the_week_reads_the_same_week_as_the_monday_cron_run():
    monday = datetime.date( 2026, 11, 9 )
    days   = [ monday + datetime.timedelta( days=i ) for i in range( 7 ) ]
    assert len( { rb.last_complete_week_end( d ) for d in days[ :6 ] } ) == 1 and rb.last_complete_week_end( days[ 0 ] ) == datetime.date( 2026, 11, 8 )
    assert all( rb.week_of( rb.last_complete_week_end( d ) )[ 0 ].weekday() == 0 for d in days ), "every default week starts on a Monday"
    ends = [ rb.last_complete_week_end( datetime.date( 2026, 10, 5 ) + datetime.timedelta( days=i ) ) for i in range( 28 ) ]
    firsts = sorted( { e for e in ends } )
    assert all( b - a == datetime.timedelta( days=7 ) for a, b in zip( firsts, firsts[ 1: ] ) ), "the default weeks follow one another with no gap and no overlap"


def test_nothing_is_saved_without_write( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    sa.store_receipt( tmp_path, receipt_of( "q1", "2026-11-01", True ) )
    before = sorted( p.relative_to( tmp_path ).as_posix() for p in tmp_path.rglob( "*" ) )
    sizes  = { p: p.stat().st_size for p in tmp_path.rglob( "*" ) if p.is_file() }
    for args in ( [ "--end", "2026-11-02" ], [] ):
        out = io.StringIO()
        assert rb.main( [ "--data-dir", str( tmp_path ), *args ], out=out ) == 0 and out.getvalue().startswith( "Reuse behaviour," )
    assert sorted( p.relative_to( tmp_path ).as_posix() for p in tmp_path.rglob( "*" ) ) == before, "no file or folder was made"
    assert not ( tmp_path / rb.PAGE_FOLDER ).exists() and { p: p.stat().st_size for p in tmp_path.rglob( "*" ) if p.is_file() } == sizes, "and none was changed"


def test_a_date_that_is_not_a_date_makes_no_page( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "tomorrow" ], out=out ) == 3 and "Nothing was made." in out.getvalue() and "ValueError" in out.getvalue()


def test_a_corrupt_receipt_makes_no_page( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    ( tmp_path / "receipts" ).mkdir()
    ( tmp_path / "receipts" / "shadow-bad.json" ).write_text( "not json", encoding="utf-8" )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02", "--write" ], out=out ) == 3 and "CandidateError" in out.getvalue() and "Nothing was made." in out.getvalue()
    assert not ( tmp_path / rb.PAGE_FOLDER ).exists()


def test_a_page_that_cannot_be_saved_is_refused( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    ( tmp_path / rb.PAGE_FOLDER ).write_text( "a file where the folder goes", encoding="utf-8" )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02", "--write" ], out=out ) == 3 and "FileExistsError" in out.getvalue() and "Nothing was made." in out.getvalue()


def test_the_data_folder_defaults_to_the_lookup_tools_choice( tmp_path, utc, monkeypatch ):
    seed( tmp_path, calls(), rows() )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path ) )
    out = io.StringIO()
    assert rb.main( [ "--end", "2026-11-02" ], out=out ) == 0 and out.getvalue().startswith( TITLE )


def test_the_command_prints_to_standard_output_by_default( tmp_path, utc, capsys ):
    seed( tmp_path, calls(), rows() )
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "2026-11-02" ] ) == 0
    assert capsys.readouterr().out.startswith( TITLE )


def test_the_cron_lines_are_the_weekly_line_and_the_reboot_line_built_like_the_daily_checks():
    weekly, reboot = rb.cron_lines( "/r", "/r/.venv/bin/python", "/r/io/weekly.log", carried={ "DEEPILY_DATA_DIR": "/d d" } )
    run = "cd /r && LUPIN_ROOT=/r PYTHONPATH=/r/src DEEPILY_DATA_DIR='/d d' /r/.venv/bin/python -m lupin_mcp.reuse_behaviour --write >> /r/io/weekly.log 2>&1 # reuse-behaviour-weekly"
    assert weekly == f"17 12 * * 1 {run}" and reboot == f"@reboot sleep 360 && {run}"
    assert rb.cron_lines( "/r", "py", "/l" )[ 0 ] == "17 12 * * 1 cd /r && LUPIN_ROOT=/r PYTHONPATH=/r/src py -m lupin_mcp.reuse_behaviour --write >> /l 2>&1 # reuse-behaviour-weekly"


def test_print_cron_shows_the_two_lines_and_installs_nothing( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    out = io.StringIO()
    assert rb.main( [ "--print-cron", "--log-path", "/l", "--python", "py" ], out=out ) == 0
    lines = out.getvalue().splitlines()
    assert len( lines ) == 2 and lines[ 0 ].startswith( "17 12 * * 1 cd " ) and lines[ 1 ].startswith( "@reboot sleep 360 && cd " ) and all( l.endswith( rb.CRON_TAG ) for l in lines )
    refused = io.StringIO()
    assert rb.main( [ "--print-cron" ], out=refused ) == 3 and "--print-cron needs --log-path" in refused.getvalue()


def test_a_compact_end_date_is_saved_under_the_dashed_date( tmp_path, utc ):
    seed( tmp_path, calls(), rows() )
    assert rb.main( [ "--data-dir", str( tmp_path ), "--end", "20261102", "--write" ], out=io.StringIO() ) == 0
    assert [ p.name for p in ( tmp_path / rb.PAGE_FOLDER ).iterdir() ] == [ "reuse-behaviour-2026-11-02.txt" ]
