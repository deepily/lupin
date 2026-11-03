"""
The behaviour report: lookups, outcome lines by kind, refusals by reason.

The seeded files are small and written here, so the expected tables are stated in the test.
A second group of tests drives the real checkers and shows that every reason they can give has a label in the report.
Nothing here calls a model or touches the shared data folder.
"""
import io
import json
import pathlib

import cosa.utils.util as cu
from lupin_mcp import reuse_behaviour as rb
from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_refusals as rr

PLAN = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.24-reuse-detection-remediation-plan.md"
ROOT = pathlib.Path( cu.get_project_root() )
RID  = "5d37236290c7d93f"
SID  = "rs-bc3ca2c901"


def outcome( kind_text, rid=RID, sid=SID ):
    return f"REUSE-OUTCOME {rid} :: {sid} :: {kind_text} :: {PLAN}#12.3-C5"


def row( n, line, status, *reasons ):
    return { "doc": "d" * 64, "n": n, "line": line, "status": status, "reasons": list( reasons ), "pairs": [] }


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


def test_the_command_prints_the_same_report_from_the_two_files( tmp_path ):
    seed( tmp_path, calls(), rows() )
    out = io.StringIO()
    assert rb.main( [ "--data-dir", str( tmp_path ) ], out=out ) == 0
    assert out.getvalue().strip() == EXPECTED
    out2 = io.StringIO()
    elsewhere = tmp_path / "logs-elsewhere"
    ( tmp_path / "call-log" ).rename( elsewhere )
    assert rb.main( [ "--data-dir", str( tmp_path ), "--log-dir", str( elsewhere ) ], out=out2 ) == 0 and out2.getvalue() == out.getvalue()


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
