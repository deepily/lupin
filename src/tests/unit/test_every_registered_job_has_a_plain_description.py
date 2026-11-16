"""
Every background job carries a plain-English description of one to three sentences.

Rick, 15 Nov: an operator who has never seen a service needs an orienting summary at the top of its abstract.
The text is stored once, in src/conf/job-registry.json, and both payloads (health summary and switch rows) carry it,
so neither web client holds a copy.
"""
import datetime
import json
import re

import pytest

import cosa.utils.util as cu
from cosa.agents.dm_tutor.sentences import count_sentences
from cosa.rest import cron_job_switches as sw
from cosa.rest import job_health as jh
from cosa.rest import job_registry as jr

JARGON   = ( "lora", "token", "symbol", "vector" )
ROW_ID   = re.compile( r"\b(?=[0-9a-f]*\d)[0-9a-f]{8}\b" )
FIXTURE  = "/src/tests/fixtures/jobs/jobs-summary.fixture.json"


def registry_jobs():
    """Ensures: returns the committed registry's jobs, read straight from the file."""
    return json.loads( open( cu.get_project_root() + "/src/conf/job-registry.json", encoding="utf-8" ).read() )[ "jobs" ]


def test_every_registered_job_has_a_description_of_one_to_three_sentences():
    jobs = registry_jobs()
    assert len( jobs ) == 25, "the registry's job count moved: re-check that every new job has a description"
    for job in jobs:
        text = job.get( "description" )
        assert isinstance( text, str ) and text.strip(), f"{job[ 'job' ]} has no description"
        assert 1 <= count_sentences( text ) <= 3, f"{job[ 'job' ]}: {count_sentences( text )} sentences"


def test_no_description_uses_jargon_or_names_a_row_id():
    for job in registry_jobs():
        lowered = job[ "description" ].lower()
        for word in JARGON: assert word not in lowered, f"{job[ 'job' ]} uses the word {word!r}"
        assert ROW_ID.search( job[ "description" ] ) is None, f"{job[ 'job' ]} names a row id"


def test_the_loader_accepts_the_committed_registry_and_hands_every_job_its_own_text():
    loaded = jr.load_registry( cu.get_project_root() )[ "jobs" ]
    assert [ j[ "description" ] for j in loaded ] == [ j[ "description" ] for j in registry_jobs() ]


def test_the_switch_rows_carry_the_registry_text_for_every_job_not_a_fallback():
    jobs = registry_jobs()
    rows = sw.build_rows( jobs )
    assert len( rows ) == len( jobs ) == 25
    for job, row in zip( jobs, rows ): assert row[ "description" ] == job[ "description" ], job[ "job" ]


def test_the_health_summary_entry_carries_the_registry_text_for_every_job():
    now   = datetime.datetime( 2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc )
    tune  = { "window_days": 7, "growth_min_items": 5, "growth_min_percent": 5, "lock_stale_seconds": 10800 }
    shown = 0
    for job in registry_jobs():
        entry = { **job, "grace_minutes": 30, "notify_interval_minutes": 30 }
        got   = jh.assess( entry, None, now, now - datetime.timedelta( hours = 2 ), tune )
        assert got[ "description" ] == job[ "description" ], job[ "job" ]
        shown += 1
    assert shown == 25


def test_the_committed_jobs_fixture_carries_each_jobs_registry_text():
    fixture  = json.loads( open( cu.get_project_root() + FIXTURE, encoding="utf-8" ).read() )[ "jobs" ]
    by_job   = { j[ "job" ]: j[ "description" ] for j in registry_jobs() }
    assert len( fixture ) > 0
    for item in fixture: assert item[ "description" ] == by_job[ item[ "job" ] ], item[ "job" ]


@pytest.mark.parametrize( "text, count", [
    ( "One sentence.", 1 ),
    ( "One. Two.", 2 ),
    ( "One! Two? Three.", 3 ),
    ( "No closing mark", 1 ),
    ( "Use e.g. this thing. It runs at 10:00 on v0.2.3 builds.", 2 ),
    ( "A. B. C. D.", 4 ),
    ( "   ", 0 ),
] )
def test_the_sentence_counter_ignores_e_g_times_and_version_numbers( text, count ):
    assert count_sentences( text ) == count


def test_the_loader_refuses_a_missing_blank_or_four_sentence_description( tmp_path ):
    base = { "job": "j", "title": "J", "owner": "cheech", "schedule": [ { "cron": "0 10 * * *" } ] }
    for bad, why in ( ( {}, "lacks a description" ), ( { "description": "  " }, "lacks a description" ), ( { "description": "A. B. C. D." }, "over 3 sentences" ) ):
        ( tmp_path / "src/conf" ).mkdir( parents=True, exist_ok=True )
        ( tmp_path / jr.REGISTRY_FILE ).write_text( json.dumps( { "schema": jr.REGISTRY_SCHEMA, "defaults": {}, "jobs": [ { **base, **bad } ] } ) )
        with pytest.raises( ValueError, match=why ): jr.load_registry( tmp_path )
