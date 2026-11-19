"""
The committed checkpoint report, its cohort file and its freeze file agree.

The expected counts below are literals read from the retune report and the replay of 19 November 2026.
"""

import hashlib
import json

import cosa.utils.util as cu
from cosa.research.phi4_flash_lite_study.freeze_corpus import verify_snapshot
from cosa.research.preference_replay import checkpoint_report as cr

ROOT           = cu.get_project_root()
REPORT_PATH    = ROOT + "/src/conf/prediction-checkpoint-report.md"
CHECKPOINT     = ROOT + "/src/conf/prediction-checkpoint.json"
COHORT_FILE    = ROOT + "/src/conf/prediction-checkpoint-cohort.jsonl"
COHORT_MANIFEST = ROOT + "/src/conf/prediction-checkpoint-cohort-manifest.json"
RETUNE_REPORT  = ROOT + "/src/conf/prediction-retune-report.json"


def _freeze():
    with open( CHECKPOINT, "r", encoding="utf-8" ) as handle: return json.load( handle )


def test_the_freeze_file_names_the_sha_of_the_report_on_disk():
    with open( REPORT_PATH, "rb" ) as handle: on_disk = hashlib.sha256( handle.read() ).hexdigest()
    assert _freeze()[ "report_sha256" ] == on_disk


def test_the_cohort_file_re_derives_the_frozen_cohort_sha_and_holds_3608_asks():
    ok, detail = verify_snapshot( COHORT_FILE, COHORT_MANIFEST )
    assert ok, detail
    assert _freeze()[ "cohort_rows" ] == 3608


def test_the_frozen_cohort_sha_is_the_retune_reports_all_ask_sha():
    with open( RETUNE_REPORT, "r", encoding="utf-8" ) as handle: retune = json.load( handle )
    assert _freeze()[ "cohort_sha256" ] == retune[ "cohort_sha256_all_ids" ]


def test_a_baseline_record_on_another_cohort_is_refused_and_the_frozen_one_is_accepted():
    messages = []
    frozen   = _freeze()[ "cohort_sha256" ]
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": frozen } ], CHECKPOINT, messages.append ) == 0
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": "0" * 64 } ], CHECKPOINT, messages.append ) == 3
    assert len( messages ) == 1 and frozen in messages[ 0 ]


def test_the_report_opens_with_the_replayable_count_and_both_windows_mix():
    with open( REPORT_PATH, "r", encoding="utf-8" ) as handle: text = handle.read()
    assert "Only 1302 of 3608 asks were replayable: 2306 had no stored vector" in text
    assert "| tune | 547 | 364 | 911 |" in text and "| final | 176 | 215 | 391 |" in text
    assert text.index( "## Coverage" ) < text.index( "## yes_no" )


def _report_text():
    with open( REPORT_PATH, "r", encoding="utf-8" ) as handle: return handle.read()


def _cohort_ids():
    with open( COHORT_FILE, "r", encoding="utf-8" ) as handle: return [ json.loads( line )[ "id" ] for line in handle if line.strip() ]


def test_the_manifest_sha_and_row_count_equal_the_freeze_files():
    with open( COHORT_MANIFEST, "r", encoding="utf-8" ) as handle: manifest = json.load( handle )
    assert manifest[ "snapshot_sha256" ] == _freeze()[ "cohort_sha256" ]
    assert manifest[ "snapshot_row_count" ] == _freeze()[ "cohort_rows" ]


def test_the_report_header_names_the_freeze_files_cohort_sha_settings_commit_and_count():
    text, freeze = _report_text(), _freeze()
    assert f"- cohort sha256: `{freeze[ 'cohort_sha256' ]}`" in text
    assert f"- settings commit: `{freeze[ 'settings_commit' ]}`" in text
    assert f"- cohort asks: {freeze[ 'cohort_rows' ]}" in text


def test_the_report_lists_exactly_the_cohort_files_ids_in_order():
    ids   = _cohort_ids()
    lines = _report_text().splitlines()
    start = lines.index( "## Cohort ids" ) + 2
    listed = [ line[ 2: ] for line in lines[ start: ] if line.startswith( "- " ) ]
    assert len( ids ) == 3608
    assert listed == ids


def test_the_score_table_sums_equal_the_retune_best_points_correct_counts():
    with open( RETUNE_REPORT, "r", encoding="utf-8" ) as handle: best = json.load( handle )[ "best_point" ]
    rows   = [ line.split( "|" )[ 1: -1 ] for line in _report_text().splitlines() if line.startswith( "| tune | " ) or line.startswith( "| final | " ) ]
    scored = [ [ cell.strip() for cell in row ] for row in rows if len( row ) == 5 ]
    assert len( scored ) == 4
    for window, expected in ( ( "tune", best[ "tune_correct" ] ), ( "final", best[ "final_correct" ] ) ):
        assert sum( int( row[ 3 ] ) for row in scored if row[ 0 ] == window ) == expected
    assert ( best[ "tune_correct" ], best[ "final_correct" ] ) == ( 287, 177 )
